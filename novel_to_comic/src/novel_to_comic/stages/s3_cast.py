"""Stage 3: character reference images + location plates.

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
from novel_to_comic.config import Config, is_gpt_image_2
from novel_to_comic.events import make_progress
from novel_to_comic.models.story_bible import Character, Prop, StoryBible
from novel_to_comic.stage_runtime import StageRuntime
from novel_to_comic.text_utils import clean, shorten
from novel_to_comic.usage import ApiResult

console = Console()


_clean = clean
_shorten = shorten

_GPT_LOCATION_PLATE_WIDTH = 1536
_GPT_LOCATION_PLATE_HEIGHT = 1024

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
    addendum: str = "",
) -> dict:
    meta = {
        **_asset_meta_common(config, project_dir, style_ref),
        "kind": "character_ref",
        "character_id": char.id,
        "visual_anchor": char.visual_anchor,
        "default_outfit": char.default_outfit,
        "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
    }
    if addendum:
        meta["instruction_addendum"] = addendum
    return meta


def _location_plate_meta(
    config: Config,
    project_dir: Path,
    style_ref: Path | None,
    loc,
    prompt: str,
    width: int | None = None,
    height: int | None = None,
    addendum: str = "",
) -> dict:
    meta = {
        **_asset_meta_common(config, project_dir, style_ref),
        "kind": "location_plate",
        "location_id": loc.id,
        "visual_anchor": loc.visual_anchor,
        "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
    }
    if is_gpt_image_2(config.effective_image_model()) and width and height:
        meta["width"] = width
        meta["height"] = height
    if addendum:
        meta["instruction_addendum"] = addendum
    return meta


def _prop_ref_meta(
    config: Config,
    project_dir: Path,
    style_ref: Path | None,
    prop: Prop,
    prompt: str,
    addendum: str = "",
) -> dict:
    meta = {
        **_asset_meta_common(config, project_dir, style_ref),
        "kind": "prop_ref",
        "prop_id": prop.id,
        "visual_anchor": prop.visual_anchor,
        "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
    }
    if addendum:
        meta["instruction_addendum"] = addendum
    return meta




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


def _cast_asset_style_ref(config: Config, style_ref: Path | None) -> Path | None:
    if not is_gpt_image_2(config.effective_image_model()):
        return style_ref
    # The gpt-image-2 route treats reference inputs as edit conditioning.
    # Reusing the selected style sample for cast assets can carry over subject
    # details or texture artifacts, so keep its cast refs text-driven.
    return None


def _style_authority_block(asset_kind: str) -> str:
    return (
        "STYLE AUTHORITY:\n"
        f"- The selected style above is mandatory for this {asset_kind}, not decorative.\n"
        "- Preserve the style's medium, mark-making, palette, lighting language, edge quality, "
        "shape design, and rendering density.\n"
        "- Layout or reference-format constraints below describe composition only; do not let "
        "them flatten the image into generic clean concept art, photorealism, anime, or default "
        "digital illustration.\n"
        "- If a style reference image is provided, treat it as the visual authority for how "
        "surfaces are painted, lit, simplified, and finished."
    )


def _character_ref_prompt(
    config: Config,
    story_bible: StoryBible,
    char: Character,
    addendum: str = "",
) -> str:
    # All four views in one image guarantees identical style, identical face,
    # identical rendering. Separate calls drift even with the same text prompt.
    identity_lock = _cast_identity_lock(char, story_bible)
    addendum_block = f"\nUSER FIX NOTE: {addendum.strip()}\n" if addendum.strip() else ""
    return (
        f"{config.style_template}\n\n"
        f"{_style_authority_block('character reference sheet')}\n\n"
        f"CHARACTER REFERENCE SHEET - {char.name}, {char.gender}.\n"
        f"{identity_lock}\n"
        f"{char.visual_anchor}\n"
        f"{addendum_block}\n"
        f"One square image divided into a 2x2 grid of four equal panels: "
        f"top-left: front-facing, arms at sides; "
        f"top-right: three-quarter turn, near shoulder forward; "
        f"bottom-left: side profile, only profile of face visible; "
        f"bottom-right: three-quarter with one hand raised in gesture. "
        f"All four figures are the SAME character - identical face, hair, build, and clothing. "
        f"Each figure is fully contained within its quadrant with white space around it - no figure touches or crosses the edge of the image. "
        f"Plain uncluttered reference background; a subtle style-colored studio wash or cast light is allowed, but no scenery. "
        f"Full body head to toe in each quadrant, no cropping. No text, no labels, no grid lines. "
        f"Clean controlled surfaces; no noisy grain, speckled dappling, repeated texture fields, or muddy micro-detail.\n\n"
        f"Render every figure in the style described above."
    )


def _location_plate_prompt(config: Config, loc, addendum: str = "") -> str:
    addendum_text = addendum.strip()
    if is_gpt_image_2(config.effective_image_model()):
        addendum_block = f"\nUSER FIX NOTE: {addendum_text}\n" if addendum_text else ""
        return (
            f"{config.style_template.strip()}\n\n"
            f"{_style_authority_block('location design plate')}\n\n"
            f"LOCATION DESIGN PLATE\n"
            f"{loc.visual_anchor}\n"
            f"{addendum_block}\n"
            f"Create a clean wide environment design plate, not a texture study. "
            f"No characters present. No text. "
            f"Build the image from large simple readable masses and clear silhouettes. "
            f"Use only the setting elements from the anchor, grouped into major shapes such as "
            f"tree masses, ground plane, path, water, building, fence, sky, or shadow when they apply. "
            f"If the setting contains dense woods, underbrush, leaves, ferns, grass, debris, or bark, "
            f"summarize them as a few grouped shapes with calm gaps between them. "
            f"Leave broad quiet areas of sky, ground, water, or shadow; do not fill every surface. "
            f"Use broad opaque gouache color blocks and clean edges with minimal brush texture. "
            f"Do not render leaf-by-leaf, grass-blade-by-grass-blade, bark-chip-by-bark-chip, "
            f"or fern-frond-by-fern-frond. "
            f"No repeated stamps, pattern tiling, wallpaper texture, speckled dappling, "
            f"noisy grain, muddy micro-detail, or fractal foliage."
        )
    addendum_block = f" USER FIX NOTE: {addendum_text}." if addendum_text else ""
    return (
        f"{config.style_template}\n\n"
        f"{_style_authority_block('location design plate')}\n\n"
        f"{loc.visual_anchor}{addendum_block} "
        f"Wide establishing shot, no characters present, clean readable background, "
        f"cinematic composition. No text. No noisy grain, speckled dappling, "
        f"repeated texture fields, pattern tiling, or muddy micro-detail."
    )


def _location_plate_dimensions(config: Config) -> tuple[int | None, int | None]:
    if is_gpt_image_2(config.effective_image_model()):
        return _GPT_LOCATION_PLATE_WIDTH, _GPT_LOCATION_PLATE_HEIGHT
    return None, None


def _prop_ref_prompt(config: Config, prop: Prop, addendum: str = "") -> str:
    addendum_block = f" USER FIX NOTE: {addendum.strip()}." if addendum.strip() else ""
    return (
        f"{config.style_template}\n\n"
        f"{_style_authority_block('prop reference')}\n\n"
        f"PROP REFERENCE - {prop.name}.\n"
        f"{prop.visual_anchor}{addendum_block}\n\n"
        f"Single object, isolated on a plain neutral mid-grey background. "
        f"Three-quarter view, evenly lit, the object centered and fully visible "
        f"with generous margin on all sides — nothing crops the silhouette. "
        f"No characters, no hands, no scenery, no other objects. "
        f"No text, no labels, no captions. "
        f"Render the object's material, color, condition, and distinctive features "
        f"clearly so it can be matched in later panels. "
        f"Clean controlled surfaces; no noisy grain, speckled dappling, "
        f"repeated texture fields, pattern tiling, or muddy micro-detail."
    )


def _read_character_ref_addendum(project_dir: Path, char_id: str) -> str:
    return artifacts.read_active_addendum(
        artifacts.character_ref_instructions_path(project_dir, char_id)
    )


def _read_location_plate_addendum(project_dir: Path, loc_id: str) -> str:
    return artifacts.read_active_addendum(
        artifacts.location_plate_instructions_path(project_dir, loc_id)
    )


def _read_prop_ref_addendum(project_dir: Path, prop_id: str) -> str:
    return artifacts.read_active_addendum(
        artifacts.prop_ref_instructions_path(project_dir, prop_id)
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
    style_ref = _cast_asset_style_ref(config, _find_style_ref(project_dir, config.style_template))
    addendum = _read_character_ref_addendum(project_dir, char.id)
    prompt = _character_ref_prompt(config, story_bible, char, addendum)
    meta = _character_ref_meta(config, project_dir, style_ref, char, prompt, addendum)

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


async def regenerate_prop_ref(
    config: Config,
    project_dir: Path,
    prop_id: str,
    semaphore: asyncio.Semaphore | None = None,
) -> ApiResult[Path]:
    story_bible = artifacts.read_story_bible(project_dir)
    prop = next((p for p in story_bible.props if p.id == prop_id), None)
    if prop is None:
        raise ValueError(f"Prop not found: {prop_id}")

    sem = semaphore or asyncio.Semaphore(1)
    output_path = artifacts.prop_ref_path(project_dir, prop.id)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = output_path.with_name(
        f".{output_path.stem}.{uuid.uuid4().hex}.tmp{output_path.suffix}"
    )
    style_ref = _cast_asset_style_ref(config, _find_style_ref(project_dir, config.style_template))
    addendum = _read_prop_ref_addendum(project_dir, prop.id)
    prompt = _prop_ref_prompt(config, prop, addendum)
    meta = _prop_ref_meta(config, project_dir, style_ref, prop, prompt, addendum)

    try:
        async with sem:
            flux_result = await flux.generate_image(
                config,
                prompt,
                tmp_path,
                width=1024,
                height=1024,
                reference_image_path=style_ref,
                ref_type="style",
                feature="cast.prop_ref",
            )
        tmp_path.replace(output_path)
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
    style_ref = _cast_asset_style_ref(config, _find_style_ref(project_dir, config.style_template))
    addendum = _read_location_plate_addendum(project_dir, loc.id)
    prompt = _location_plate_prompt(config, loc, addendum)
    width, height = _location_plate_dimensions(config)
    meta = _location_plate_meta(config, project_dir, style_ref, loc, prompt, width, height, addendum)

    try:
        flux_result = None
        async with sem:
            flux_result = await flux.generate_image(
                config,
                prompt,
                tmp_path,
                width=width,
                height=height,
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
    config: Config, project_dir: Path, story_bible: StoryBible, ctx: StageRuntime,
    char_ids: list[str] | None = None,
) -> None:
    """Part B: Generate character reference sheets.

    Each character gets a single wide composite image (sheet.png) showing all
    four poses side by side. Generating all poses in one API call is the only
    reliable way to ensure style consistency — separate calls produce separate
    style interpretations regardless of reference conditioning.
    """
    console.print("[bold]Generating character reference images...[/bold]")
    ctx.log("Generating character reference sheets...")
    refs_dir = project_dir / "refs"

    # A visual style reference image is far stronger than text for locking style.
    # Without it, the model applies different stylistic conventions per character
    # type (human → concept art, cat → anime, creature → dark fantasy).
    candidate_style_ref = _find_style_ref(project_dir, config.style_template)
    style_ref = _cast_asset_style_ref(config, candidate_style_ref)
    if style_ref:
        console.print(f"[dim]Using style reference: {style_ref.name}[/dim]")
    elif candidate_style_ref and is_gpt_image_2(config.effective_image_model()):
        console.print(
            "[dim]Skipping style image reference for gpt-image-2 cast refs "
            "to avoid copied subject details and texture artifacts.[/dim]"
        )
    else:
        console.print(
            "[yellow]No style sample found — run `pipeline style` and generate a sample "
            "before indexing for tighter style consistency across character sheets.[/yellow]"
        )

    chars_to_gen = [c for c in story_bible.characters if not char_ids or c.id in char_ids]

    with make_progress(ctx.on_event) as progress:
        task = progress.add_task("Character refs", total=len(chars_to_gen))
        for char in chars_to_gen:
            char_dir = refs_dir / char.id
            char_dir.mkdir(parents=True, exist_ok=True)
            output_path = char_dir / "sheet.png"
            addendum = _read_character_ref_addendum(project_dir, char.id)
            prompt = _character_ref_prompt(config, story_bible, char, addendum)
            meta = _character_ref_meta(config, project_dir, style_ref, char, prompt, addendum)

            if artifacts.asset_matches_meta(output_path, meta):
                # Migrate older sheets that pre-date cropped-pose references.
                if not (char_dir / "front.png").exists():
                    try:
                        await asyncio.to_thread(_crop_sheet_to_poses, output_path)
                    except Exception:
                        pass
                ctx.record_item_done(cost=0.0)
                ctx.log(f"Using existing ref sheet for {char.name}", level="dim")
                ctx.progress(ctx.stage_state.items_done, ctx.stage_state.items_total)
                if task is not None:
                    progress.advance(task)
                continue

            try:
                ctx.log(f"Generating ref sheet for {char.name}")
                # Square 2x2 grid — each quadrant gives a full-body figure
                # ~512x512px of space, enough to avoid edge clipping.
                # Pass the style sample when the active image model handles
                # references reliably; gpt-image-2 cast refs stay text-driven.
                flux_result = await flux.generate_image(
                    config, prompt, output_path,
                    width=1024, height=1024,
                    reference_image_path=style_ref,
                    ref_type="style",
                    feature="cast.character_ref",
                )
                await asyncio.to_thread(_crop_sheet_to_poses, output_path)
                artifacts.write_asset_meta(output_path, meta)
                ctx.record_item_done(usage=flux_result.usage)
                ctx.progress(ctx.stage_state.items_done, ctx.stage_state.items_total)
            except Exception as e:
                cause = e.last_attempt.exception() if hasattr(e, "last_attempt") else e
                console.print(f"[red]Failed ref sheet for {char.name}: {cause}[/red]")
                ctx.record_item_failed(char.id)
                ctx.log(f"Failed ref sheet for {char.name}: {cause}", level="error")
            if task is not None:
                progress.advance(task)


async def _generate_location_plates(
    config: Config, project_dir: Path, story_bible: StoryBible, ctx: StageRuntime,
    loc_ids: list[str] | None = None,
) -> None:
    """Part C: Generate location background plates."""
    console.print("[bold]Generating location plates...[/bold]")
    ctx.log("Generating location plates...")
    plates_dir = project_dir / "plates"
    plates_dir.mkdir(parents=True, exist_ok=True)

    locs_to_gen = [loc for loc in story_bible.locations if not loc_ids or loc.id in loc_ids]

    with make_progress(ctx.on_event) as progress:
        task = progress.add_task("Location plates", total=len(locs_to_gen))
        for loc in locs_to_gen:
            output_path = plates_dir / f"{loc.id}.png"
            addendum = _read_location_plate_addendum(project_dir, loc.id)
            prompt = _location_plate_prompt(config, loc, addendum)
            style_ref = _cast_asset_style_ref(
                config,
                _find_style_ref(project_dir, config.style_template),
            )
            width, height = _location_plate_dimensions(config)
            meta = _location_plate_meta(
                config,
                project_dir,
                style_ref,
                loc,
                prompt,
                width,
                height,
                addendum,
            )
            if artifacts.asset_matches_meta(output_path, meta):
                ctx.record_item_done(cost=0.0)
                ctx.log(f"Using existing location plate for {loc.name}", level="dim")
                ctx.progress(ctx.stage_state.items_done, ctx.stage_state.items_total)
                if task is not None:
                    progress.advance(task)
                continue
            try:
                ctx.log(f"Generating location plate for {loc.name}")
                flux_result = await flux.generate_image(
                    config,
                    prompt,
                    output_path,
                    width=width,
                    height=height,
                    reference_image_path=style_ref,
                    ref_type="style",
                    feature="cast.location_plate",
                )
                artifacts.write_asset_meta(output_path, meta)
                ctx.record_item_done(usage=flux_result.usage)
                ctx.progress(ctx.stage_state.items_done, ctx.stage_state.items_total)
            except Exception as e:
                cause = e.last_attempt.exception() if hasattr(e, "last_attempt") else e
                console.print(f"[red]Failed plate for {loc.name}: {cause}[/red]")
            if task is not None:
                progress.advance(task)


async def _generate_prop_refs(
    config: Config, project_dir: Path, story_bible: StoryBible, ctx: StageRuntime,
    prop_ids: list[str] | None = None,
) -> None:
    """Generate one neutral-background reference image per story prop.

    Stage 1 already filters props down to those that recur or are plot-central,
    so every prop in the bible gets a ref sheet. For models that handle visual
    references reliably, the image is conditioned on the active style sample so
    prop refs share the panel art style. For gpt-image-2, style stays text-only
    to avoid edit-reference texture artifacts.
    """
    props_to_gen = [p for p in story_bible.props if not prop_ids or p.id in prop_ids]
    if not props_to_gen:
        return

    console.print("[bold]Generating prop reference images...[/bold]")
    ctx.log("Generating prop reference images...")

    style_ref = _cast_asset_style_ref(config, _find_style_ref(project_dir, config.style_template))

    with make_progress(ctx.on_event) as progress:
        task = progress.add_task("Prop refs", total=len(props_to_gen))
        for prop in props_to_gen:
            output_path = artifacts.prop_ref_path(project_dir, prop.id)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            addendum = _read_prop_ref_addendum(project_dir, prop.id)
            prompt = _prop_ref_prompt(config, prop, addendum)
            meta = _prop_ref_meta(config, project_dir, style_ref, prop, prompt, addendum)

            if artifacts.asset_matches_meta(output_path, meta):
                ctx.record_item_done(cost=0.0)
                ctx.log(f"Using existing prop ref for {prop.name}", level="dim")
                ctx.progress(ctx.stage_state.items_done, ctx.stage_state.items_total)
                if task is not None:
                    progress.advance(task)
                continue

            try:
                ctx.log(f"Generating prop ref for {prop.name}")
                flux_result = await flux.generate_image(
                    config, prompt, output_path,
                    width=1024, height=1024,
                    reference_image_path=style_ref,
                    ref_type="style",
                    feature="cast.prop_ref",
                )
                artifacts.write_asset_meta(output_path, meta)
                ctx.record_item_done(usage=flux_result.usage)
                ctx.progress(ctx.stage_state.items_done, ctx.stage_state.items_total)
            except Exception as e:
                cause = e.last_attempt.exception() if hasattr(e, "last_attempt") else e
                console.print(f"[red]Failed prop ref for {prop.name}: {cause}[/red]")
                ctx.record_item_failed(prop.id)
                ctx.log(f"Failed prop ref for {prop.name}: {cause}", level="error")
            if task is not None:
                progress.advance(task)


async def run(
    config: Config,
    project_dir: Path,
    ctx: StageRuntime,
    char_ids: list[str] | None = None,
    loc_ids: list[str] | None = None,
    prop_ids: list[str] | None = None,
) -> None:
    """Execute Stage 3: generate character refs, location plates, and prop refs."""
    story_bible = artifacts.read_story_bible(project_dir)

    is_partial = bool(char_ids or loc_ids or prop_ids)
    should_generate_refs = not is_partial or char_ids is not None
    should_generate_plates = not is_partial or loc_ids is not None
    should_generate_prop_refs = not is_partial or prop_ids is not None

    total_items = 0
    if should_generate_refs:
        total_items += len([c for c in story_bible.characters if not char_ids or c.id in char_ids])
    if should_generate_plates:
        total_items += len([loc for loc in story_bible.locations if not loc_ids or loc.id in loc_ids])
    if should_generate_prop_refs:
        total_items += len([p for p in story_bible.props if not prop_ids or p.id in prop_ids])

    with ctx.execute(total=total_items):
        if should_generate_refs:
            await _generate_character_refs(config, project_dir, story_bible, ctx, char_ids)
            ctx.progress(ctx.stage_state.items_done, ctx.stage_state.items_total)

        if should_generate_plates:
            await _generate_location_plates(config, project_dir, story_bible, ctx, loc_ids)

        if should_generate_prop_refs:
            await _generate_prop_refs(config, project_dir, story_bible, ctx, prop_ids)

        # Pin the style template hash so downstream stages (draw, especially)
        # can detect if the style was edited after cast plates were generated.
        # Skip pinning on partial re-runs unless plates were regenerated, since
        # a refs-only re-run doesn't replace the plates that anchor visual style.
        if not is_partial or should_generate_plates:
            from novel_to_comic.state import hash_style_template
            ctx.set_style_template_hash(hash_style_template(config.style_template))

        if not is_partial:
            console.print("[yellow]Stage 3 complete — awaiting review.[/yellow]")
            console.print("Review character refs in: refs/")
            console.print("Run [bold]pipeline approve --project . --stage cast[/bold] to continue.")


from novel_to_comic.stages import Stage  # noqa: E402
from novel_to_comic.state import PipelineState  # noqa: E402


def estimate_cost(config: Config, project_dir: Path, state: PipelineState) -> float:
    from novel_to_comic.models.story_bible import StoryBible
    from novel_to_comic.usage import estimate_image_cost
    
    sb_path = project_dir / "story_bible.json"
    if not sb_path.exists():
        return 0.0
    try:
        story_bible = StoryBible.model_validate_json(sb_path.read_text())
    except Exception:
        return 0.0
        
    missing_refs = sum(
        1 for char in story_bible.characters
        if not (project_dir / "refs" / char.id / "sheet.png").exists()
    )
    missing_plates = sum(
        1 for loc in story_bible.locations
        if not (project_dir / "plates" / f"{loc.id}.png").exists()
    )
    return estimate_image_cost(
        config.effective_image_model(),
        missing_refs + missing_plates,
        quality=getattr(config, "image_quality", None),
    )


STAGE = Stage(
    name="cast",
    run=run,
    outputs=lambda d: [d / "refs"],
    clean_paths=lambda d: [
        d / "refs", d / "plates",
        d / "adapt", d / "plan", d / "storyboard",
        d / "direct", d / "draw", d / "compose", d / "exports",
    ],
    estimate_cost=estimate_cost,
)
