"""Stage 2: RAG index + character reference images + location plates.

Part A: Embed novel scene chunks into Qdrant.
Part B: Generate character reference sheets via FLUX.2 Pro.
Part C: Generate location background plates via FLUX.2 Pro.
"""

import asyncio
import json
from pathlib import Path

from rich.console import Console
from rich.progress import Progress
from tenacity import RetryError

from novel_to_comic.clients import embeddings, flux
from novel_to_comic.clients.flux import _is_imagen
from novel_to_comic.config import Config
from novel_to_comic.events import EventCallback, _NOOP
from novel_to_comic.models.story_bible import StoryBible
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


def _find_style_ref(project_dir: Path, style_template: str) -> Path | None:
    """Return the sample image that matches the active style template.

    Tries to match by comparing the template text against saved suggestions.
    Falls back to the first available sample if no exact match is found.
    Returns None if no samples exist (style command hasn't been run).
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

    # Fallback: first available sample regardless of which style is active
    for i in range(1, 20):
        candidate = project_dir / "samples" / f"style_{i}.png"
        if candidate.exists():
            return candidate

    return None


def _load_story_bible(project_dir: Path) -> StoryBible:
    bible_path = project_dir / "story_bible.json"
    return StoryBible.model_validate_json(bible_path.read_text())


async def _build_rag_index(config: Config, project_dir: Path, story_bible: StoryBible) -> int:
    """Part A: Build the Qdrant RAG index from scene texts."""
    console.print("[bold]Building RAG index...[/bold]")
    create_collection(config)

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

    # Embed in batches
    batch_size = 100
    for i in range(0, len(all_chunks), batch_size):
        batch = all_chunks[i:i + batch_size]
        texts = [c["text"] for c in batch]
        vectors = await embeddings.embed_texts(config, texts)
        upsert_chunks(config, batch, vectors)

    console.print(f"[green]Indexed {len(all_chunks)} chunks from {len(scene_texts)} scenes.[/green]")
    return len(all_chunks)


async def _generate_character_refs(
    config: Config, project_dir: Path, story_bible: StoryBible, state: PipelineState
) -> None:
    """Part B: Generate character reference sheets.

    Each character gets a single wide composite image (sheet.png) showing all
    four poses side by side. Generating all poses in one API call is the only
    reliable way to ensure style consistency — separate calls produce separate
    style interpretations regardless of reference conditioning.
    """
    console.print("[bold]Generating character reference images...[/bold]")
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

    with Progress() as progress:
        task = progress.add_task("Character refs", total=len(story_bible.characters))
        for char in story_bible.characters:
            char_dir = refs_dir / char.id
            char_dir.mkdir(parents=True, exist_ok=True)
            output_path = char_dir / "sheet.png"

            if output_path.exists():
                progress.advance(task)
                continue

            # All four views in one image guarantees identical style, identical face,
            # identical rendering. The model holds its interpretation of the character
            # consistent within a single generation — separate calls cannot.
            #
            # Keep instructions compact so the style template retains relative weight.
            # More instruction text = more style drift.
            prompt = (
                f"{config.style_template}\n\n"
                f"CHARACTER REFERENCE SHEET — {char.name}, {char.gender}.\n"
                f"{char.visual_anchor}\n\n"
                f"One square image divided into a 2x2 grid of four equal panels: "
                f"top-left: front-facing, arms at sides; "
                f"top-right: three-quarter turn, near shoulder forward; "
                f"bottom-left: side profile, only profile of face visible; "
                f"bottom-right: three-quarter with one hand raised in gesture. "
                f"All four figures are the SAME character — identical face, hair, build, and clothing. "
                f"Each figure is fully contained within its quadrant with white space around it — no figure touches or crosses the edge of the image. "
                f"Pure white background. Full body head to toe in each quadrant, no cropping. No text, no labels, no grid lines.\n\n"
                f"Render every figure in the style described above."
            )

            try:
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
                record_item_done(state, "index", cost=0.05)
                if _is_imagen(config.image_model) or _is_imagen(
                    getattr(config, "fallback_image_model", "")
                ):
                    await asyncio.sleep(3)
            except Exception as e:
                cause = e.last_attempt.exception() if isinstance(e, RetryError) else e
                console.print(f"[red]Failed ref sheet for {char.name}: {cause}[/red]")
            progress.advance(task)


async def _generate_location_plates(
    config: Config, project_dir: Path, story_bible: StoryBible, state: PipelineState
) -> None:
    """Part C: Generate location background plates."""
    console.print("[bold]Generating location plates...[/bold]")
    plates_dir = project_dir / "plates"
    plates_dir.mkdir(parents=True, exist_ok=True)

    with Progress() as progress:
        task = progress.add_task("Location plates", total=len(story_bible.locations))
        for loc in story_bible.locations:
            output_path = plates_dir / f"{loc.id}.png"
            if output_path.exists():
                progress.advance(task)
                continue
            prompt = (
                f"{config.style_template} {loc.visual_anchor} "
                f"Wide establishing shot, no characters present, detailed background, "
                f"cinematic composition. No text."
            )
            try:
                await flux.generate_image(config, prompt, output_path)
                record_item_done(state, "index", cost=0.03)
                if _is_imagen(config.image_model) or _is_imagen(
                    getattr(config, "fallback_image_model", "")
                ):
                    await asyncio.sleep(3)
            except Exception as e:
                cause = e.last_attempt.exception() if isinstance(e, RetryError) else e
                console.print(f"[red]Failed plate for {loc.name}: {cause}[/red]")
            progress.advance(task)


async def run(
    config: Config,
    project_dir: Path,
    state: PipelineState,
    on_event: EventCallback | None = None,
) -> None:
    """Execute Stage 2: Build RAG index and generate reference images."""
    emit = on_event or _NOOP

    story_bible = _load_story_bible(project_dir)
    total_items = (
        1  # RAG index
        + len(story_bible.characters)  # 1 reference sheet per character
        + len(story_bible.locations)   # 1 plate per location
    )
    begin_stage(state, "index", total=total_items)
    emit({"type": "stage_begin", "stage": "index", "total": total_items})
    save_state(state, project_dir)

    try:
        await _build_rag_index(config, project_dir, story_bible)
        record_item_done(state, "index", cost=0.002)
        emit({"type": "stage_progress", "stage": "index",
              "done": state.stages["index"].items_done,
              "total": state.stages["index"].items_total})

        await _generate_character_refs(config, project_dir, story_bible, state)
        emit({"type": "stage_progress", "stage": "index",
              "done": state.stages["index"].items_done,
              "total": state.stages["index"].items_total})

        await _generate_location_plates(config, project_dir, story_bible, state)

        complete_stage(state, "index")
        emit({"type": "stage_complete", "stage": "index",
              "done": state.stages["index"].items_done,
              "total": state.stages["index"].items_total})
        save_state(state, project_dir)

        console.print("[yellow]Stage 2 complete — awaiting review.[/yellow]")
        console.print("Review character refs in: refs/")
        console.print("Run [bold]pipeline approve --project . --stage index[/bold] to continue.")

    except Exception as e:
        fail_stage(state, "index", str(e))
        emit({"type": "stage_fail", "stage": "index", "message": str(e)})
        save_state(state, project_dir)
        raise
