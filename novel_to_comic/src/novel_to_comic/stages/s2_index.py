"""Stage 2: character reference images + location plates.

Part A: Generate character reference sheets
Part B: Generate location background plates
"""

import asyncio
import hashlib
import json
import re
import uuid
from pathlib import Path

from rich.console import Console

from novel_to_comic import artifacts
from novel_to_comic.clients import flux
from novel_to_comic.config import Config, GATEWAY_IMAGE_PRIMARY_MODEL
from novel_to_comic.events import EventCallback, _NOOP, make_progress
from novel_to_comic.models.story_bible import Character, StoryBible
from novel_to_comic.text_utils import clean, shorten
from novel_to_comic.usage import ApiResult
from novel_to_comic.state import (
    PipelineState,
    begin_stage,
    complete_stage,
    fail_stage,
    record_item_done,
    record_item_failed,
    save_state,
)

console = Console()


_clean = clean
_shorten = shorten

def _tokens(value: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9]+", value.lower())
        if len(token) > 2 and token not in {"the", "and", "with", "his", "her"}
    }


def _character_signature(char: Character) -> str:
    features = ", ".join(_clean(f) for f in char.distinguishing_features[:4])
    pieces = [
        f"{char.name}: {_clean(char.age_range)} {_clean(char.gender)}".strip(),
        features,
        _clean(char.default_outfit),
    ]
    return _shorten("; ".join(piece for piece in pieces if piece), 220)


def _similar_cast_members(char: Character, story_bible: StoryBible) -> list[Character]:
    char_outfit_tokens = _tokens(char.default_outfit)
    matches = []
    for other in story_bible.characters:
        if other.id == char.id:
            continue
        other_outfit_tokens = _tokens(other.default_outfit)
        outfit_overlap = len(char_outfit_tokens & other_outfit_tokens)
        if outfit_overlap >= 1:
            matches.append((outfit_overlap, other))
    return [other for _overlap, other in sorted(matches, key=lambda item: item[0], reverse=True)[:3]]


def _cast_identity_lock(char: Character, story_bible: StoryBible) -> str:
    similar = _similar_cast_members(char, story_bible)
    if not similar:
        return (
            f"CAST IDENTITY LOCK: Only {char.name} appears in this reference sheet. "
            f"Preserve these unique traits: {_character_signature(char)}."
        )

    comparisons = []
    own_features = _character_signature(char)
    for other in similar:
        comparisons.append(
            f"distinct from {other.name}, who is {_character_signature(other)}"
        )
    return (
        f"CAST IDENTITY LOCK: Only {char.name} appears in this reference sheet. "
        f"{char.name} must be immediately recognizable as {_shorten(own_features, 180)}. "
        f"Keep this face, hairline, build, posture, and silhouette visually "
        f"{'; '.join(comparisons)}. Do not merge cast members into one generic person."
    )


_SHEET_POSE_BOXES: dict[str, tuple[float, float, float, float]] = {
    # 2x2 grid produced by _character_ref_prompt — quadrant coordinates as
    # fractions of (width, height).
    "front":         (0.0, 0.0, 0.5, 0.5),
    "three_quarter": (0.5, 0.0, 1.0, 0.5),
    "profile":       (0.0, 0.5, 0.5, 1.0),
    "gesture":       (0.5, 0.5, 1.0, 1.0),
}


def _crop_sheet_to_poses(sheet_path: Path) -> None:
    """Crop a 2x2 character reference sheet into four single-pose PNGs.

    The 2x2 composite keeps style/identity coherent across the four poses
    during generation, but passing the grid directly as a panel reference
    leaks the grid layout into the model's attention. Individual poses give
    the model a clean portrait to condition on while preserving the shared
    style the sheet was generated with.
    """
    from PIL import Image

    with Image.open(sheet_path) as img:
        w, h = img.size
        for name, (x0, y0, x1, y1) in _SHEET_POSE_BOXES.items():
            box = (int(w * x0), int(h * y0), int(w * x1), int(h * y1))
            out_path = sheet_path.parent / f"{name}.png"
            img.crop(box).save(out_path)


def _file_sha256(path: Path | None) -> str | None:
    if path is None or not path.exists():
        return None
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _relative_to_project(path: Path | None, project_dir: Path) -> str | None:
    if path is None:
        return None
    try:
        return str(path.relative_to(project_dir))
    except ValueError:
        return str(path)


def _asset_meta_common(config: Config, project_dir: Path, style_ref: Path | None) -> dict:
    return {
        "version": 1,
        "style_template": config.style_template,
        "image_model": config.effective_image_model(),
        "style_ref": _relative_to_project(style_ref, project_dir),
        "style_ref_sha256": _file_sha256(style_ref),
    }


def _character_ref_meta(
    config: Config,
    project_dir: Path,
    style_ref: Path | None,
    char: Character,
    prompt: str,
) -> dict:
    return {
        **_asset_meta_common(config, project_dir, style_ref),
        "kind": "character_ref",
        "character_id": char.id,
        "visual_anchor": char.visual_anchor,
        "default_outfit": char.default_outfit,
        "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
    }


def _location_plate_meta(
    config: Config,
    project_dir: Path,
    style_ref: Path | None,
    loc,
    prompt: str,
) -> dict:
    return {
        **_asset_meta_common(config, project_dir, style_ref),
        "kind": "location_plate",
        "location_id": loc.id,
        "visual_anchor": loc.visual_anchor,
        "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
    }




def _find_style_ref(project_dir: Path, style_template: str) -> Path | None:
    """Return the sample image that matches the active style template.

    Tries to match by comparing the template text against saved suggestions.
    Returns None if no exact sample exists. This avoids conditioning refs and
    panels on a sample from a different active style.
    """
    suggestions_path = artifacts.style_suggestions_path(project_dir)
    if suggestions_path.exists():
        try:
            data = json.loads(suggestions_path.read_text())
            suggestions = data.get("suggestions", [])
            for i, s in enumerate(suggestions, 1):
                if isinstance(s, dict) and s.get("template", "").strip() == style_template.strip():
                    candidate = artifacts.style_sample_path(project_dir, i)
                    if candidate.exists():
                        return candidate
        except Exception:
            pass

    return None


def _character_ref_style_ref(config: Config, style_ref: Path | None) -> Path | None:
    if config.effective_image_model() != GATEWAY_IMAGE_PRIMARY_MODEL:
        return style_ref
    # The primary gateway image route uses edit/reference-style conditioning.
    # Reusing a previous character sample here can copy that character's
    # clothing or body details into the next reference sheet.
    return None


def _character_ref_prompt(config: Config, story_bible: StoryBible, char: Character) -> str:
    # All four views in one image guarantees identical style, identical face,
    # identical rendering. Separate calls drift even with the same text prompt.
    identity_lock = _cast_identity_lock(char, story_bible)
    return (
        f"{config.style_template}\n\n"
        f"CHARACTER REFERENCE SHEET - {char.name}, {char.gender}.\n"
        f"{identity_lock}\n"
        f"{char.visual_anchor}\n\n"
        f"One square image divided into a 2x2 grid of four equal panels: "
        f"top-left: front-facing, arms at sides; "
        f"top-right: three-quarter turn, near shoulder forward; "
        f"bottom-left: side profile, only profile of face visible; "
        f"bottom-right: three-quarter with one hand raised in gesture. "
        f"All four figures are the SAME character - identical face, hair, build, and clothing. "
        f"Each figure is fully contained within its quadrant with white space around it - no figure touches or crosses the edge of the image. "
        f"Pure white background. Full body head to toe in each quadrant, no cropping. No text, no labels, no grid lines.\n\n"
        f"Render every figure in the style described above."
    )


def _location_plate_prompt(config: Config, loc) -> str:
    return (
        f"{config.style_template} {loc.visual_anchor} "
        f"Wide establishing shot, no characters present, detailed background, "
        f"cinematic composition. No text."
    )


async def regenerate_character_ref(
    config: Config,
    project_dir: Path,
    char_id: str,
    semaphore: asyncio.Semaphore | None = None,
) -> ApiResult[Path]:
    story_bible = artifacts.read_story_bible(project_dir)
    char = next((candidate for candidate in story_bible.characters if candidate.id == char_id), None)
    if char is None:
        raise ValueError(f"Character not found: {char_id}")

    sem = semaphore or asyncio.Semaphore(1)
    output_path = project_dir / "refs" / char.id / "sheet.png"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = output_path.with_name(
        f".{output_path.stem}.{uuid.uuid4().hex}.tmp{output_path.suffix}"
    )
    style_ref = _character_ref_style_ref(config, _find_style_ref(project_dir, config.style_template))
    prompt = _character_ref_prompt(config, story_bible, char)
    meta = _character_ref_meta(config, project_dir, style_ref, char, prompt)

    try:
        flux_result = None
        async with sem:
            flux_result = await flux.generate_image(
                config,
                prompt,
                tmp_path,
                width=1024,
                height=1024,
                reference_image_path=style_ref,
                ref_type="style",
                feature="cast.character_ref",
            )
        tmp_path.replace(output_path)
        await asyncio.to_thread(_crop_sheet_to_poses, output_path)
        artifacts.write_asset_meta(output_path, meta)
        return ApiResult(value=output_path, usage=flux_result.usage)
    finally:
        if tmp_path.exists():
            tmp_path.unlink()


async def regenerate_location_plate(
    config: Config,
    project_dir: Path,
    loc_id: str,
    semaphore: asyncio.Semaphore | None = None,
) -> ApiResult[Path]:
    story_bible = artifacts.read_story_bible(project_dir)
    loc = next((candidate for candidate in story_bible.locations if candidate.id == loc_id), None)
    if loc is None:
        raise ValueError(f"Location not found: {loc_id}")

    sem = semaphore or asyncio.Semaphore(1)
    output_path = project_dir / "plates" / f"{loc.id}.png"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = output_path.with_name(
        f".{output_path.stem}.{uuid.uuid4().hex}.tmp{output_path.suffix}"
    )
    style_ref = _find_style_ref(project_dir, config.style_template)
    prompt = _location_plate_prompt(config, loc)
    meta = _location_plate_meta(config, project_dir, style_ref, loc, prompt)

    try:
        flux_result = None
        async with sem:
            flux_result = await flux.generate_image(
                config,
                prompt,
                tmp_path,
                reference_image_path=style_ref,
                ref_type="style",
                feature="cast.location_plate",
            )
        tmp_path.replace(output_path)
        artifacts.write_asset_meta(output_path, meta)
        return ApiResult(value=output_path, usage=flux_result.usage)
    finally:
        if tmp_path.exists():
            tmp_path.unlink()


async def _generate_character_refs(
    config: Config, project_dir: Path, story_bible: StoryBible, state: PipelineState,
    char_ids: list[str] | None = None,
    on_event: EventCallback | None = None,
) -> None:
    """Part B: Generate character reference sheets.

    Each character gets a single wide composite image (sheet.png) showing all
    four poses side by side. Generating all poses in one API call is the only
    reliable way to ensure style consistency — separate calls produce separate
    style interpretations regardless of reference conditioning.
    """
    emit = on_event or _NOOP
    console.print("[bold]Generating character reference images...[/bold]")
    emit({"type": "log", "stage": "cast", "level": "info",
          "message": "Generating character reference sheets..."})
    refs_dir = project_dir / "refs"

    # A visual style reference image is far stronger than text for locking style.
    # Without it, the model applies different stylistic conventions per character
    # type (human → concept art, cat → anime, creature → dark fantasy).
    candidate_style_ref = _find_style_ref(project_dir, config.style_template)
    style_ref = _character_ref_style_ref(config, candidate_style_ref)
    if style_ref:
        console.print(f"[dim]Using style reference: {style_ref.name}[/dim]")
    elif candidate_style_ref and config.effective_image_model() == GATEWAY_IMAGE_PRIMARY_MODEL:
        console.print(
            "[dim]Skipping style image reference for primary gateway character sheets "
            "to avoid copying another character's outfit.[/dim]"
        )
    else:
        console.print(
            "[yellow]No style sample found — run `pipeline style` and generate a sample "
            "before indexing for tighter style consistency across character sheets.[/yellow]"
        )

    chars_to_gen = [c for c in story_bible.characters if not char_ids or c.id in char_ids]

    with make_progress(on_event) as progress:
        task = progress.add_task("Character refs", total=len(chars_to_gen))
        for char in chars_to_gen:
            char_dir = refs_dir / char.id
            char_dir.mkdir(parents=True, exist_ok=True)
            output_path = char_dir / "sheet.png"
            prompt = _character_ref_prompt(config, story_bible, char)
            meta = _character_ref_meta(config, project_dir, style_ref, char, prompt)

            if artifacts.asset_matches_meta(output_path, meta):
                # Migrate older sheets that pre-date cropped-pose references.
                if not (char_dir / "front.png").exists():
                    try:
                        await asyncio.to_thread(_crop_sheet_to_poses, output_path)
                    except Exception:
                        pass
                record_item_done(state, "cast", cost=0.0)
                emit({"type": "log", "stage": "cast", "level": "dim",
                      "message": f"Using existing ref sheet for {char.name}"})
                emit({"type": "stage_progress", "stage": "cast",
                      "done": state.stages["cast"].items_done,
                      "total": state.stages["cast"].items_total})
                progress.advance(task)
                continue

            try:
                emit({"type": "log", "stage": "cast", "level": "info",
                      "message": f"Generating ref sheet for {char.name}"})
                # Square 2x2 grid — each quadrant gives a full-body figure
                # ~512x512px of space, enough to avoid edge clipping.
                # Pass the style sample as a style reference to lock visual style
                # across all characters regardless of their subject type.
                flux_result = await flux.generate_image(
                    config, prompt, output_path,
                    width=1024, height=1024,
                    reference_image_path=style_ref,
                    ref_type="style",
                    feature="cast.character_ref",
                )
                await asyncio.to_thread(_crop_sheet_to_poses, output_path)
                artifacts.write_asset_meta(output_path, meta)
                record_item_done(state, "cast", usage=flux_result.usage)
                emit({"type": "stage_progress", "stage": "cast",
                      "done": state.stages["cast"].items_done,
                      "total": state.stages["cast"].items_total})
            except Exception as e:
                cause = e.last_attempt.exception() if hasattr(e, "last_attempt") else e
                console.print(f"[red]Failed ref sheet for {char.name}: {cause}[/red]")
                record_item_failed(state, "cast", char.id)
                emit({"type": "log", "stage": "cast", "level": "error",
                      "message": f"Failed ref sheet for {char.name}: {cause}"})
            progress.advance(task)


async def _generate_location_plates(
    config: Config, project_dir: Path, story_bible: StoryBible, state: PipelineState,
    loc_ids: list[str] | None = None,
    on_event: EventCallback | None = None,
) -> None:
    """Part C: Generate location background plates."""
    emit = on_event or _NOOP
    console.print("[bold]Generating location plates...[/bold]")
    emit({"type": "log", "stage": "cast", "level": "info",
          "message": "Generating location plates..."})
    plates_dir = project_dir / "plates"
    plates_dir.mkdir(parents=True, exist_ok=True)

    locs_to_gen = [loc for loc in story_bible.locations if not loc_ids or loc.id in loc_ids]

    with make_progress(on_event) as progress:
        task = progress.add_task("Location plates", total=len(locs_to_gen))
        for loc in locs_to_gen:
            output_path = plates_dir / f"{loc.id}.png"
            prompt = _location_plate_prompt(config, loc)
            style_ref = _find_style_ref(project_dir, config.style_template)
            meta = _location_plate_meta(config, project_dir, style_ref, loc, prompt)
            if artifacts.asset_matches_meta(output_path, meta):
                record_item_done(state, "cast", cost=0.0)
                emit({"type": "log", "stage": "cast", "level": "dim",
                      "message": f"Using existing location plate for {loc.name}"})
                emit({"type": "stage_progress", "stage": "cast",
                      "done": state.stages["cast"].items_done,
                      "total": state.stages["cast"].items_total})
                progress.advance(task)
                continue
            try:
                emit({"type": "log", "stage": "cast", "level": "info",
                      "message": f"Generating location plate for {loc.name}"})
                flux_result = await flux.generate_image(
                    config,
                    prompt,
                    output_path,
                    reference_image_path=style_ref,
                    ref_type="style",
                    feature="cast.location_plate",
                )
                artifacts.write_asset_meta(output_path, meta)
                record_item_done(state, "cast", usage=flux_result.usage)
                emit({"type": "stage_progress", "stage": "cast",
                      "done": state.stages["cast"].items_done,
                      "total": state.stages["cast"].items_total})
            except Exception as e:
                cause = e.last_attempt.exception() if hasattr(e, "last_attempt") else e
                console.print(f"[red]Failed plate for {loc.name}: {cause}[/red]")
            progress.advance(task)


async def run(
    config: Config,
    project_dir: Path,
    state: PipelineState,
    char_ids: list[str] | None = None,
    loc_ids: list[str] | None = None,
    on_event: EventCallback | None = None,
) -> None:
    """Execute Stage 2: generate character reference images and location plates."""
    emit = on_event or _NOOP

    story_bible = artifacts.read_story_bible(project_dir)

    is_partial = bool(char_ids or loc_ids)
    should_generate_refs = not is_partial or char_ids is not None
    should_generate_plates = not is_partial or loc_ids is not None

    total_items = 0
    if should_generate_refs:
        total_items += len([c for c in story_bible.characters if not char_ids or c.id in char_ids])
    if should_generate_plates:
        total_items += len([loc for loc in story_bible.locations if not loc_ids or loc.id in loc_ids])

    begin_stage(state, "cast", total=total_items)
    emit({"type": "stage_begin", "stage": "cast", "total": total_items})
    save_state(state, project_dir)

    try:
        if should_generate_refs:
            await _generate_character_refs(config, project_dir, story_bible, state, char_ids, on_event)
            emit({"type": "stage_progress", "stage": "cast",
                  "done": state.stages["cast"].items_done,
                  "total": state.stages["cast"].items_total})

        if should_generate_plates:
            await _generate_location_plates(config, project_dir, story_bible, state, loc_ids, on_event)

        complete_stage(state, "cast")
        emit({"type": "stage_complete", "stage": "cast",
              "done": state.stages["cast"].items_done,
              "total": state.stages["cast"].items_total})
        save_state(state, project_dir)

        if not is_partial:
            console.print("[yellow]Stage 2 complete — awaiting review.[/yellow]")
            console.print("Review character refs in: refs/")
            console.print("Run [bold]pipeline approve --project . --stage index[/bold] to continue.")

    except Exception as e:
        fail_stage(state, "cast", str(e))
        emit({"type": "stage_fail", "stage": "cast", "message": str(e)})
        save_state(state, project_dir)
        raise


from novel_to_comic.stages import Stage  # noqa: E402

STAGE = Stage(
    name="cast",
    run=run,
    outputs=lambda d: [d / "refs"],
    clean_paths=lambda d: [
        d / "refs", d / "plates",
        d / "adapt", d / "plan", d / "storyboard",
        d / "direct", d / "draw", d / "compose", d / "exports",
    ],
)
