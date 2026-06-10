"""Stage 4: Scene text → Screenplay format

Converts prose scenes into observable-action screenplays suitable for
comic panel breakdown.
"""

import asyncio
from pathlib import Path

from rich.console import Console

from novel_to_comic import artifacts
from novel_to_comic.clients import text
from novel_to_comic.config import Config
from novel_to_comic.events import make_progress
from novel_to_comic.models.panel import Screenplay
from novel_to_comic.models.story_bible import StoryBible
from novel_to_comic.stage_runtime import StageRuntime
from novel_to_comic.text_utils import has_offscreen_marker
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
    )
    return has_offscreen_marker(text)


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

    # Surface location states so the LLM can stamp each beat with the active state.
    state_lines: list[str] = []
    if loc and loc.states:
        default_id = scene.location_state_id or (loc.states[0].id if loc.states else None)
        state_lines.append("Location states (tag beats with these ids when the state changes):")
        for state in loc.states:
            marker = " [default]" if state.id == default_id else ""
            description = f" — {state.description}" if state.description else ""
            state_lines.append(
                f"- {state.id}{marker}: {state.visual_anchor}{description}"
            )

    # Boundary cue: tell the LLM where the NEXT scene begins so it stops in time.
    boundary_lines: list[str] = []
    scenes_list = story_bible.scenes
    try:
        idx = next(i for i, s in enumerate(scenes_list) if s.id == scene_id)
    except StopIteration:
        idx = -1
    if 0 <= idx < len(scenes_list) - 1:
        next_scene = scenes_list[idx + 1]
        if next_scene.source_start_quote:
            boundary_lines.extend([
                "",
                "SCENE BOUNDARY:",
                f"The NEXT scene ({next_scene.id} — \"{next_scene.title}\") begins with: "
                f"\"{next_scene.source_start_quote}\"",
                "STOP adapting the moment you reach (or approach) this line. Do not include it.",
            ])

    parts = [
        f"SCENE: {scene.id} — {scene.title}",
        f"Type: {scene.scene_type} | Beat: {scene.narrative_beat}",
        loc_desc,
        *state_lines,
        "",
        "CHARACTERS IN SCENE:",
        *char_info,
        *boundary_lines,
        "",
        "SCENE TEXT:",
        scene_text,
    ]
    return "\n".join(parts)


def _enforce_scene_boundary(
    screenplay: Screenplay,
    story_bible: StoryBible,
) -> tuple[Screenplay, str | None]:
    """Drop beats that adapt content from the NEXT scene.

    The screenplay LLM occasionally overflows its assigned scene and starts
    adapting the next scene's prose, which causes every downstream stage to
    treat the bleed-over panels as belonging to the wrong location_id /
    location_state_id. We use the next scene's source_start_quote as a
    boundary marker: any beat whose source_text contains that marker (or any
    beat after such a beat in the same screenplay) is dropped.

    Returns (possibly-truncated screenplay, warning message or None).
    """
    scenes = story_bible.scenes
    try:
        idx = next(i for i, s in enumerate(scenes) if s.id == screenplay.scene_id)
    except StopIteration:
        return screenplay, None
    if idx >= len(scenes) - 1:
        return screenplay, None
    marker = (scenes[idx + 1].source_start_quote or "").strip()
    if len(marker) < 16:
        return screenplay, None
    marker_lower = marker.lower()
    boundary_idx: int | None = None
    for i, beat in enumerate(screenplay.beats):
        haystack = " ".join(
            part.lower()
            for part in (beat.source_text, beat.content, beat.direction)
            if part
        )
        if marker_lower in haystack:
            boundary_idx = i
            break
    if boundary_idx is None:
        return screenplay, None
    kept_beats = screenplay.beats[:boundary_idx]
    dropped = len(screenplay.beats) - boundary_idx
    warning = (
        f"{screenplay.scene_id}: trimmed {dropped} beat(s) that drifted into the next "
        f"scene's content (matched next-scene start quote)."
    )
    return screenplay.model_copy(update={"beats": kept_beats}), warning


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


def _transition_type_for_text(text: str) -> str:
    # Keyword table mirrors the examples in prompts/screenplay.txt: fades and
    # cuts are deliberate jumps (hard_cut); visual echoes are match cuts;
    # everything else is a gentle handoff.
    lower = text.lower()
    hard_markers = ("smash cut", "cut to", "scene change", "time jump", "jump cut", "fade")
    if any(marker in lower for marker in hard_markers):
        return "hard_cut"
    if any(marker in lower for marker in ("match cut", "parallel", "echo", "mirrors")):
        return "match_cut"
    return "smooth_continuation"


def _annotate_transition_beats(screenplay: Screenplay) -> Screenplay:
    """Fill in transition_type ONLY where the screenplay model omitted it.

    The model is asked to classify its own transitions; the keyword heuristic
    is a fallback, not an override.
    """
    beats = []
    for beat in screenplay.beats:
        if beat.type == "transition" and not beat.transition_type:
            beats.append(
                beat.model_copy(
                    update={
                        "transition_type": _transition_type_for_text(
                            f"{beat.content} {beat.direction or ''}"
                        ),
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
    if not artifacts.scene_text_path(project_dir, scene_id).exists():
        return None

    if artifacts.screenplay_path(project_dir, scene_id).exists():
        return ApiResult(value=artifacts.read_screenplay(project_dir, scene_id), usage=None)

    scene_text = artifacts.read_scene_text(project_dir, scene_id)
    user_content = _build_user_content(scene_text, story_bible, scene_id)

    async with semaphore:
        api_result = await text.generate_json(
            config=config,
            model=config.effective_screenplay_model(),
            system_prompt=_localized_system_prompt(config, system_prompt),
            user_content=user_content,
            feature="adapt.screenplay",
        )

    result = api_result.value
    # Some models wrap the response in a list — unwrap before validating.
    if isinstance(result, list):
        result = result[0]
    screenplay = _normalize_screenplay(Screenplay.model_validate(result), story_bible)
    screenplay = _annotate_transition_beats(screenplay)
    screenplay, boundary_warning = _enforce_scene_boundary(screenplay, story_bible)
    if boundary_warning:
        console.print(f"[yellow]{boundary_warning}[/yellow]")
    artifacts.write_screenplay(project_dir, scene_id, screenplay)
    return ApiResult(value=screenplay, usage=api_result.usage)


async def run(
    config: Config,
    project_dir: Path,
    ctx: StageRuntime,
    scene_ids: list[str] | None = None,
) -> None:
    """Execute Stage 4: Convert scenes to screenplays."""
    story_bible = artifacts.read_story_bible(project_dir)
    system_prompt = PROMPT_PATH.read_text()

    ids = scene_ids or [s.id for s in story_bible.scenes]
    if config.dev_mode and not scene_ids:
        ids = ids[:1]

    estimated = 0.0
    for sid in ids:
        if artifacts.screenplay_path(project_dir, sid).exists():
            continue
        scene_path = artifacts.scene_text_path(project_dir, sid)
        scene_text = scene_path.read_text() if scene_path.exists() else "x" * 8000
        estimated += estimate_text_cost(
            config.effective_screenplay_model(),
            system_prompt + "\n" + scene_text,
        )

    semaphore = asyncio.Semaphore(config.parallel_batch_size)

    with ctx.execute(total=len(ids), estimated_cost_usd=estimated):
        with make_progress(ctx.on_event) as progress:
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
                        ctx.log(f"Failed {sid}: {result}", level="error")
                        ctx.record_item_failed(sid)
                    else:
                        ctx.record_item_done(
                            usage=result.usage if result is not None else None,
                        )
                        ctx.progress(ctx.stage_state.items_done, ctx.stage_state.items_total)
                    if task is not None:
                        progress.advance(task)
                ctx.save()

        if len(ctx.stage_state.items_failed) > 0 and ctx.stage_state.items_done == 0:
            raise RuntimeError(
                f"All {len(ctx.stage_state.items_failed)} scenes failed during adapt stage"
            )

        console.print("[green]Adapt stage complete.[/green]")


from novel_to_comic.stages import Stage, clean_cascade  # noqa: E402
from novel_to_comic.state import PipelineState  # noqa: E402


def estimate_cost(config: Config, project_dir: Path, state: PipelineState) -> float:
    story_bible = artifacts.read_story_bible_safe(project_dir)
    if story_bible is None:
        return 0.0

    system_prompt = ""
    if PROMPT_PATH.exists():
        try:
            system_prompt = PROMPT_PATH.read_text()
        except Exception:
            pass
            
    total = 0.0
    for scene in story_bible.scenes:
        if (project_dir / "screenplays" / f"{scene.id}.json").exists():
            continue
        scene_path = project_dir / "scenes" / f"{scene.id}.txt"
        scene_text = ""
        if scene_path.exists():
            try:
                scene_text = scene_path.read_text()
            except Exception:
                pass
        if not scene_text:
            scene_text = "x" * 8000
            
        total += estimate_text_cost(
            config.effective_screenplay_model(),
            system_prompt + "\n" + scene_text,
            output_chars=12000,
        )
    return total


STAGE = Stage(
    name="adapt",
    run=run,
    outputs=lambda d: [d / "screenplays"],
    clean_paths=lambda d: clean_cascade(d, "adapt"),
    estimate_cost=estimate_cost,
)
