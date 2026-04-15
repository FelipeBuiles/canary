"""Stage 3: Scene text → Screenplay format via Gemini Pro.

Converts prose scenes into observable-action screenplays suitable for
comic panel breakdown.
"""

import asyncio
from pathlib import Path

from rich.console import Console
from rich.progress import Progress

from novel_to_comic.clients import gemini
from novel_to_comic.config import Config
from novel_to_comic.events import EventCallback, _NOOP
from novel_to_comic.models.panel import Screenplay
from novel_to_comic.models.story_bible import StoryBible
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
PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "screenplay.txt"


def _load_story_bible(project_dir: Path) -> StoryBible:
    return StoryBible.model_validate_json((project_dir / "story_bible.json").read_text())


def _build_user_content(scene_text: str, story_bible: StoryBible, scene_id: str) -> str:
    """Build the user message with scene text and relevant Story Bible context."""
    scene = next((s for s in story_bible.scenes if s.id == scene_id), None)
    if not scene:
        return scene_text

    # Gather character descriptions
    char_info = []
    for cid in scene.character_ids:
        char = next((c for c in story_bible.characters if c.id == cid), None)
        if char:
            char_info.append(f"- {char.name} ({cid}): {char.visual_anchor}")

    # Gather location
    loc = next((loc for loc in story_bible.locations if loc.id == scene.location_id), None)
    loc_desc = f"Location: {loc.name} — {loc.visual_anchor}" if loc else ""

    parts = [
        f"SCENE: {scene.id} — {scene.title}",
        f"Type: {scene.scene_type} | Beat: {scene.narrative_beat}",
        loc_desc,
        "",
        "CHARACTERS IN SCENE:",
        *char_info,
        "",
        "SCENE TEXT:",
        scene_text,
    ]
    return "\n".join(parts)


async def _process_scene(
    config: Config,
    project_dir: Path,
    story_bible: StoryBible,
    scene_id: str,
    system_prompt: str,
    semaphore: asyncio.Semaphore,
) -> Screenplay | None:
    """Process a single scene into a screenplay."""
    scene_text_path = project_dir / "scenes" / f"{scene_id}.txt"
    if not scene_text_path.exists():
        return None

    output_path = project_dir / "screenplays" / f"{scene_id}.json"
    if output_path.exists():
        return Screenplay.model_validate_json(output_path.read_text())

    scene_text = scene_text_path.read_text()
    user_content = _build_user_content(scene_text, story_bible, scene_id)

    async with semaphore:
        result = await gemini.generate_json(
            config=config,
            model=config.screenplay_model,
            system_prompt=system_prompt,
            user_content=user_content,
        )

    # Some models wrap the response in a list — unwrap before validating.
    if isinstance(result, list):
        result = result[0]
    screenplay = Screenplay.model_validate(result)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(screenplay.model_dump_json(indent=2))
    return screenplay


async def run(
    config: Config,
    project_dir: Path,
    state: PipelineState,
    scene_ids: list[str] | None = None,
    on_event: EventCallback | None = None,
) -> None:
    """Execute Stage 3: Convert scenes to screenplays."""
    emit = on_event or _NOOP

    story_bible = _load_story_bible(project_dir)
    system_prompt = PROMPT_PATH.read_text()

    ids = scene_ids or [s.id for s in story_bible.scenes]
    begin_stage(state, "screenplay", total=len(ids))
    emit({"type": "stage_begin", "stage": "screenplay", "total": len(ids)})
    save_state(state, project_dir)

    semaphore = asyncio.Semaphore(config.parallel_batch_size)

    try:
        with Progress() as progress:
            task = progress.add_task("Screenplays", total=len(ids))
            for batch_start in range(0, len(ids), config.parallel_batch_size):
                batch = ids[batch_start:batch_start + config.parallel_batch_size]
                coros = [
                    _process_scene(config, project_dir, story_bible, sid, system_prompt, semaphore)
                    for sid in batch
                ]
                results = await asyncio.gather(*coros, return_exceptions=True)
                for sid, result in zip(batch, results):
                    if isinstance(result, Exception):
                        console.print(f"[red]Failed {sid}: {result}[/red]")
                        emit({"type": "log", "stage": "screenplay", "level": "error",
                              "message": f"Failed {sid}: {result}"})
                        record_item_failed(state, "screenplay", sid)
                    else:
                        record_item_done(state, "screenplay", cost=0.04)
                        emit({"type": "stage_progress", "stage": "screenplay",
                              "done": state.stages["screenplay"].items_done,
                              "total": state.stages["screenplay"].items_total})
                    progress.advance(task)
                save_state(state, project_dir)

        complete_stage(state, "screenplay")
        emit({"type": "stage_complete", "stage": "screenplay",
              "done": state.stages["screenplay"].items_done,
              "total": state.stages["screenplay"].items_total})
        save_state(state, project_dir)
        console.print("[green]Stage 3 complete.[/green]")

    except Exception as e:
        fail_stage(state, "screenplay", str(e))
        emit({"type": "stage_fail", "stage": "screenplay", "message": str(e)})
        save_state(state, project_dir)
        raise
