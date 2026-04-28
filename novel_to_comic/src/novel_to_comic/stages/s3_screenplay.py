"""Stage 3: Scene text → Screenplay format via Gemini Pro.

Converts prose scenes into observable-action screenplays suitable for
comic panel breakdown.
"""

import asyncio
from pathlib import Path

from rich.console import Console
from rich.progress import Progress

from novel_to_comic.clients import text
from novel_to_comic.config import Config
from novel_to_comic.events import EventCallback, _NOOP, make_progress
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
from novel_to_comic.usage import ApiResult, estimate_text_cost

console = Console()
PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "screenplay.txt"


def _is_offscreen_character(char) -> bool:
    text = " ".join(
        str(part)
        for part in (
            char.name,
            char.visual_anchor,
            char.default_outfit,
            char.age_range,
            char.gender,
            " ".join(char.distinguishing_features),
        )
    ).lower()
    return any(
        marker in text
        for marker in (
            "off-screen",
            "off screen",
            "off-panel",
            "off panel",
            "unseen speaker",
            "unseen voice",
            "voice-only",
            "voice only",
            "heard but not seen",
            "not physically shown",
            "never physically shown",
        )
    )


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
        if char and not _is_offscreen_character(char):
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


def _normalize_screenplay(screenplay: Screenplay, story_bible: StoryBible) -> Screenplay:
    # TODO: Add first-class off-screen speaker support instead of nulling voice-only speakers.
    offscreen_ids = {char.id for char in story_bible.characters if _is_offscreen_character(char)}
    if not offscreen_ids:
        return screenplay

    visible_characters = [cid for cid in screenplay.characters if cid not in offscreen_ids]
    beats = []
    for beat in screenplay.beats:
        if beat.character_id not in offscreen_ids:
            beats.append(beat)
            continue

        char = next((c for c in story_bible.characters if c.id == beat.character_id), None)
        speaker = char.name if char else beat.character_id
        direction = beat.direction or ""
        cue = f"off-screen voice: {speaker}"
        if cue not in direction:
            direction = f"{cue}. {direction}".strip()
        beats.append(beat.model_copy(update={"character_id": None, "direction": direction}))

    return screenplay.model_copy(update={"characters": visible_characters, "beats": beats})


def _transition_type_for_text(text: str) -> str | None:
    lower = text.lower()
    hard_markers = ("smash cut", "cut to", "scene change", "time jump", "jump cut")
    if any(marker in lower for marker in hard_markers):
        return "hard_cut"
    if any(marker in lower for marker in ("match cut", "parallel", "echo", "mirrors")):
        return "match_cut"
    if any(marker in lower for marker in ("fade", "soft cut", "continue", "continuing", "then")):
        return "smooth_continuation"
    return "smooth_continuation"


def _annotate_transition_beats(screenplay: Screenplay) -> Screenplay:
    beats = []
    for beat in screenplay.beats:
        if beat.type == "transition":
            beats.append(
                beat.model_copy(
                    update={
                        "transition_type": _transition_type_for_text(beat.content),
                    }
                )
            )
        else:
            beats.append(beat)
    return screenplay.model_copy(update={"beats": beats})


def _localized_system_prompt(config: Config, system_prompt: str) -> str:
    return f"{system_prompt.rstrip()}\n\nLANGUAGE REQUIREMENT:\n{config.generation_language_instruction()}"


async def _process_scene(
    config: Config,
    project_dir: Path,
    story_bible: StoryBible,
    scene_id: str,
    system_prompt: str,
    semaphore: asyncio.Semaphore,
) -> ApiResult[Screenplay | None]:
    """Process a single scene into a screenplay."""
    scene_text_path = project_dir / "scenes" / f"{scene_id}.txt"
    if not scene_text_path.exists():
        return None

    output_path = project_dir / "screenplays" / f"{scene_id}.json"
    if output_path.exists():
        return ApiResult(value=Screenplay.model_validate_json(output_path.read_text()), usage=None)

    scene_text = scene_text_path.read_text()
    user_content = _build_user_content(scene_text, story_bible, scene_id)

    async with semaphore:
        api_result = await text.generate_json(
            config=config,
            model=config.effective_screenplay_model(),
            system_prompt=_localized_system_prompt(config, system_prompt),
            user_content=user_content,
        )

    result = api_result.value
    # Some models wrap the response in a list — unwrap before validating.
    if isinstance(result, list):
        result = result[0]
    screenplay = _normalize_screenplay(Screenplay.model_validate(result), story_bible)
    screenplay = _annotate_transition_beats(screenplay)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(screenplay.model_dump_json(indent=2))
    return ApiResult(value=screenplay, usage=api_result.usage)


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
    if config.dev_mode and not scene_ids:
        ids = ids[:1]

    estimated = 0.0
    for sid in ids:
        if (project_dir / "screenplays" / f"{sid}.json").exists():
            continue
        scene_path = project_dir / "scenes" / f"{sid}.txt"
        scene_text = scene_path.read_text() if scene_path.exists() else "x" * 8000
        estimated += estimate_text_cost(
            config.effective_screenplay_model(),
            system_prompt + "\n" + scene_text,
        )
    begin_stage(state, "adapt", total=len(ids), estimated_cost_usd=estimated)
    emit({"type": "stage_begin", "stage": "adapt", "total": len(ids)})
    save_state(state, project_dir)

    semaphore = asyncio.Semaphore(config.parallel_batch_size)

    try:
        with make_progress(on_event) as progress:
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
                        emit({"type": "log", "stage": "adapt", "level": "error",
                              "message": f"Failed {sid}: {result}"})
                        record_item_failed(state, "adapt", sid)
                    else:
                        record_item_done(
                            state, "adapt",
                            usage=result.usage if result is not None else None,
                        )
                        emit({"type": "stage_progress", "stage": "adapt",
                              "done": state.stages["adapt"].items_done,
                              "total": state.stages["adapt"].items_total})
                    progress.advance(task)
                save_state(state, project_dir)

        if len(state.stages["adapt"].items_failed) > 0 and state.stages["adapt"].items_done == 0:
            raise RuntimeError(
                f"All {len(state.stages['adapt'].items_failed)} scenes failed during adapt stage"
            )

        complete_stage(state, "adapt")
        emit({"type": "stage_complete", "stage": "adapt",
              "done": state.stages["adapt"].items_done,
              "total": state.stages["adapt"].items_total})
        save_state(state, project_dir)
        console.print("[green]Stage 3 complete.[/green]")

    except Exception as e:
        fail_stage(state, "adapt", str(e))
        emit({"type": "stage_fail", "stage": "adapt", "message": str(e)})
        save_state(state, project_dir)
        raise
