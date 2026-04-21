"""Stage 2: optional RAG index + character reference images + location plates.

Part A: Optionally embed novel scene chunks into Qdrant.
Part B: Generate character reference sheets via FLUX.2 Pro.
Part C: Generate location background plates via FLUX.2 Pro.
"""

import asyncio
import hashlib
import json
import re
import uuid
from pathlib import Path

from rich.console import Console
from rich.progress import Progress
from tenacity import RetryError

from novel_to_comic.clients import embeddings, flux
from novel_to_comic.config import Config
from novel_to_comic.events import EventCallback, _NOOP, make_progress
from novel_to_comic.models.story_bible import Character, StoryBible
from novel_to_comic.text_utils import clean, shorten
from novel_to_comic.rag.chunker import chunk_scene_text, load_scene_texts
from novel_to_comic.rag.store import create_collection, upsert_chunks
from novel_to_comic.state import (
    PipelineState,
    begin_stage,
    complete_stage,
    fail_stage,
    record_item_done,
    save_state,
)

console = Console()


_clean = clean
_shorten = shorten

_MAX_EMBEDDING_BATCH_TEXTS = 100
_MAX_EMBEDDING_BATCH_TOKENS = 18_000


def _tokens(value: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9]+", value.lower())
        if len(token) > 2 and token not in {"the", "and", "with", "his", "her"}
    }


def _estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def _embedding_batches(chunks: list[dict]) -> list[list[dict]]:
    batches: list[list[dict]] = []
    current: list[dict] = []
    current_tokens = 0

    for chunk in chunks:
        chunk_tokens = _estimate_tokens(chunk["text"])
        would_exceed_count = len(current) >= _MAX_EMBEDDING_BATCH_TEXTS
        would_exceed_tokens = current_tokens + chunk_tokens > _MAX_EMBEDDING_BATCH_TOKENS
        if current and (would_exceed_count or would_exceed_tokens):
            batches.append(current)
            current = []
            current_tokens = 0

        current.append(chunk)
        current_tokens += chunk_tokens

    if current:
        batches.append(current)

    return batches


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


def _asset_meta_path(output_path: Path) -> Path:
    return output_path.with_suffix(f"{output_path.suffix}.meta.json")


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


def _asset_matches_meta(output_path: Path, expected: dict) -> bool:
    meta_path = _asset_meta_path(output_path)
    if not output_path.exists() or not meta_path.exists():
        return False
    try:
        actual = json.loads(meta_path.read_text())
    except Exception:
        return False
    return actual == expected


def _write_asset_meta(output_path: Path, meta: dict) -> None:
    _asset_meta_path(output_path).write_text(json.dumps(meta, indent=2, sort_keys=True))


def _find_style_ref(project_dir: Path, style_template: str) -> Path | None:
    """Return the sample image that matches the active style template.

    Tries to match by comparing the template text against saved suggestions.
    Returns None if no exact sample exists. This avoids conditioning refs and
    panels on a sample from a different active style.
    """
    suggestions_path = project_dir / "samples" / "style_suggestions.json"
    if suggestions_path.exists():
        try:
            data = json.loads(suggestions_path.read_text())
            suggestions = data.get("suggestions", [])
            for i, s in enumerate(suggestions, 1):
                if isinstance(s, dict) and s.get("template", "").strip() == style_template.strip():
                    candidate = project_dir / "samples" / f"style_{i}.png"
                    if candidate.exists():
                        return candidate
        except Exception:
            pass

    return None


def _load_story_bible(project_dir: Path) -> StoryBible:
    bible_path = project_dir / "story_bible.json"
    return StoryBible.model_validate_json(bible_path.read_text())


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
) -> Path:
    story_bible = _load_story_bible(project_dir)
    char = next((candidate for candidate in story_bible.characters if candidate.id == char_id), None)
    if char is None:
        raise ValueError(f"Character not found: {char_id}")

    sem = semaphore or asyncio.Semaphore(1)
    output_path = project_dir / "refs" / char.id / "sheet.png"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = output_path.with_name(
        f".{output_path.stem}.{uuid.uuid4().hex}.tmp{output_path.suffix}"
    )
    style_ref = _find_style_ref(project_dir, config.style_template)
    prompt = _character_ref_prompt(config, story_bible, char)
    meta = _character_ref_meta(config, project_dir, style_ref, char, prompt)

    try:
        async with sem:
            await flux.generate_image(
                config,
                prompt,
                tmp_path,
                width=1024,
                height=1024,
                reference_image_path=style_ref,
                ref_type="style",
            )
        tmp_path.replace(output_path)
        await asyncio.to_thread(_crop_sheet_to_poses, output_path)
        _write_asset_meta(output_path, meta)
        return output_path
    finally:
        if tmp_path.exists():
            tmp_path.unlink()


async def regenerate_location_plate(
    config: Config,
    project_dir: Path,
    loc_id: str,
    semaphore: asyncio.Semaphore | None = None,
) -> Path:
    story_bible = _load_story_bible(project_dir)
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
        async with sem:
            await flux.generate_image(
                config,
                prompt,
                tmp_path,
                reference_image_path=style_ref,
                ref_type="style",
            )
        tmp_path.replace(output_path)
        _write_asset_meta(output_path, meta)
        return output_path
    finally:
        if tmp_path.exists():
            tmp_path.unlink()


async def _build_rag_index(config: Config, project_dir: Path, story_bible: StoryBible) -> int:
    """Part A: Build the Qdrant RAG index from scene texts."""
    console.print("[bold]Building RAG index...[/bold]")
    create_collection(config, project_dir)

    scene_texts = load_scene_texts(project_dir / "scenes")
    scene_lookup = {s.id: s for s in story_bible.scenes}

    all_chunks: list[dict] = []
    chunk_id = 0
    for scene_id, text in scene_texts.items():
        chunks = chunk_scene_text(text)
        scene = scene_lookup.get(scene_id)
        for chunk_text in chunks:
            all_chunks.append({
                "id": chunk_id,
                "scene_id": scene_id,
                "chapter": scene.chapter if scene else 0,
                "character_ids": scene.character_ids if scene else [],
                "location_id": scene.location_id if scene else "",
                "text": chunk_text,
            })
            chunk_id += 1

    if not all_chunks:
        console.print("[yellow]No scene texts found to index.[/yellow]")
        return 0

    for batch in _embedding_batches(all_chunks):
        texts = [c["text"] for c in batch]
        vectors = await embeddings.embed_texts(config, texts)
        upsert_chunks(config, batch, vectors, project_dir)

    console.print(f"[green]Indexed {len(all_chunks)} chunks from {len(scene_texts)} scenes.[/green]")
    return len(all_chunks)


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
    emit({"type": "log", "stage": "index", "level": "info",
          "message": "Generating character reference sheets..."})
    refs_dir = project_dir / "refs"

    # A visual style reference image is far stronger than text for locking style.
    # Without it, the model applies different stylistic conventions per character
    # type (human → concept art, cat → anime, creature → dark fantasy).
    style_ref = _find_style_ref(project_dir, config.style_template)
    if style_ref:
        console.print(f"[dim]Using style reference: {style_ref.name}[/dim]")
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

            if _asset_matches_meta(output_path, meta):
                # Migrate older sheets that pre-date cropped-pose references.
                if not (char_dir / "front.png").exists():
                    try:
                        await asyncio.to_thread(_crop_sheet_to_poses, output_path)
                    except Exception:
                        pass
                record_item_done(state, "index", cost=0.0)
                emit({"type": "log", "stage": "index", "level": "dim",
                      "message": f"Using existing ref sheet for {char.name}"})
                emit({"type": "stage_progress", "stage": "index",
                      "done": state.stages["index"].items_done,
                      "total": state.stages["index"].items_total})
                progress.advance(task)
                continue

            try:
                emit({"type": "log", "stage": "index", "level": "info",
                      "message": f"Generating ref sheet for {char.name}"})
                # Square 2x2 grid — each quadrant gives a full-body figure
                # ~512x512px of space, enough to avoid edge clipping.
                # Pass the style sample as a style reference to lock visual style
                # across all characters regardless of their subject type.
                await flux.generate_image(
                    config, prompt, output_path,
                    width=1024, height=1024,
                    reference_image_path=style_ref,
                    ref_type="style",
                )
                await asyncio.to_thread(_crop_sheet_to_poses, output_path)
                _write_asset_meta(output_path, meta)
                record_item_done(state, "index", cost=0.05)
                emit({"type": "stage_progress", "stage": "index",
                      "done": state.stages["index"].items_done,
                      "total": state.stages["index"].items_total})
            except Exception as e:
                cause = e.last_attempt.exception() if isinstance(e, RetryError) else e
                console.print(f"[red]Failed ref sheet for {char.name}: {cause}[/red]")
            progress.advance(task)


async def _generate_location_plates(
    config: Config, project_dir: Path, story_bible: StoryBible, state: PipelineState,
    loc_ids: list[str] | None = None,
    on_event: EventCallback | None = None,
) -> None:
    """Part C: Generate location background plates."""
    emit = on_event or _NOOP
    console.print("[bold]Generating location plates...[/bold]")
    emit({"type": "log", "stage": "index", "level": "info",
          "message": "Generating location plates..."})
    plates_dir = project_dir / "plates"
    plates_dir.mkdir(parents=True, exist_ok=True)

    locs_to_gen = [l for l in story_bible.locations if not loc_ids or l.id in loc_ids]

    with make_progress(on_event) as progress:
        task = progress.add_task("Location plates", total=len(locs_to_gen))
        for loc in locs_to_gen:
            output_path = plates_dir / f"{loc.id}.png"
            prompt = _location_plate_prompt(config, loc)
            style_ref = _find_style_ref(project_dir, config.style_template)
            meta = _location_plate_meta(config, project_dir, style_ref, loc, prompt)
            if _asset_matches_meta(output_path, meta):
                record_item_done(state, "index", cost=0.0)
                emit({"type": "log", "stage": "index", "level": "dim",
                      "message": f"Using existing location plate for {loc.name}"})
                emit({"type": "stage_progress", "stage": "index",
                      "done": state.stages["index"].items_done,
                      "total": state.stages["index"].items_total})
                progress.advance(task)
                continue
            try:
                emit({"type": "log", "stage": "index", "level": "info",
                      "message": f"Generating location plate for {loc.name}"})
                await flux.generate_image(
                    config,
                    prompt,
                    output_path,
                    reference_image_path=style_ref,
                    ref_type="style",
                )
                _write_asset_meta(output_path, meta)
                record_item_done(state, "index", cost=0.03)
                emit({"type": "stage_progress", "stage": "index",
                      "done": state.stages["index"].items_done,
                      "total": state.stages["index"].items_total})
            except Exception as e:
                cause = e.last_attempt.exception() if isinstance(e, RetryError) else e
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
    """Execute Stage 2: optionally build RAG index and generate reference images."""
    emit = on_event or _NOOP

    story_bible = _load_story_bible(project_dir)

    is_partial = bool(char_ids or loc_ids)
    should_build_rag = not is_partial and config.enable_rag_index
    should_generate_refs = not is_partial or char_ids is not None
    should_generate_plates = not is_partial or loc_ids is not None

    total_items = 0
    if should_build_rag:
        total_items += 1  # RAG index
    if should_generate_refs:
        total_items += len([c for c in story_bible.characters if not char_ids or c.id in char_ids])
    if should_generate_plates:
        total_items += len([l for l in story_bible.locations if not loc_ids or l.id in loc_ids])

    begin_stage(state, "index", total=total_items)
    emit({"type": "stage_begin", "stage": "index", "total": total_items})
    save_state(state, project_dir)

    try:
        if should_build_rag:
            emit({"type": "log", "stage": "index", "level": "info",
                  "message": "Building scene search index..."})
            await _build_rag_index(config, project_dir, story_bible)
            record_item_done(state, "index", cost=0.002)
            emit({"type": "stage_progress", "stage": "index",
                  "done": state.stages["index"].items_done,
                  "total": state.stages["index"].items_total})
        elif not is_partial:
            console.print("[dim]Skipping optional RAG index; enable_rag_index is false.[/dim]")
            emit({"type": "log", "stage": "index", "level": "dim",
                  "message": "Skipping optional RAG index; enable_rag_index is false."})

        if should_generate_refs:
            await _generate_character_refs(config, project_dir, story_bible, state, char_ids, on_event)
            emit({"type": "stage_progress", "stage": "index",
                  "done": state.stages["index"].items_done,
                  "total": state.stages["index"].items_total})

        if should_generate_plates:
            await _generate_location_plates(config, project_dir, story_bible, state, loc_ids, on_event)

        complete_stage(state, "index")
        emit({"type": "stage_complete", "stage": "index",
              "done": state.stages["index"].items_done,
              "total": state.stages["index"].items_total})
        save_state(state, project_dir)

        if not is_partial:
            console.print("[yellow]Stage 2 complete — awaiting review.[/yellow]")
            console.print("Review character refs in: refs/")
            console.print("Run [bold]pipeline approve --project . --stage index[/bold] to continue.")

    except Exception as e:
        fail_stage(state, "index", str(e))
        emit({"type": "stage_fail", "stage": "index", "message": str(e)})
        save_state(state, project_dir)
        raise
