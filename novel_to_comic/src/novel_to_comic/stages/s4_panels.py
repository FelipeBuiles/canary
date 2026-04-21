"""Stage 4: Screenplay → Panel breakdown JSON via Gemini Flash.

Takes each screenplay and determines panel composition: shot type,
camera angle, character positions, dialogue placement, etc.

Long screenplays (> BEATS_PER_CHUNK beats) are split into page groups
so the LLM can process each group at a manageable size without losing
dialogue or collapsing events. Panels are numbered consecutively across
all page groups for the scene.
"""

import asyncio
from math import ceil
from pathlib import Path

from rich.console import Console
from rich.progress import Progress

from novel_to_comic.clients import gemini
from novel_to_comic.config import Config
from novel_to_comic.events import EventCallback, _NOOP, make_progress
from novel_to_comic.models.panel import PanelBreakdown, Screenplay, ScreenplayBeat
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
PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "panel_breakdown.txt"

# Screenplays with more beats than this are split into multiple LLM calls.
# Each chunk maps to one "page group" of 4-8 panels. At 16 beats per chunk
# and ~3 speech bubbles per panel, roughly all dialogue is preserved.
BEATS_PER_CHUNK = 16


def _load_story_bible(project_dir: Path) -> StoryBible:
    return StoryBible.model_validate_json((project_dir / "story_bible.json").read_text())


def _chunk_beats(beats: list[ScreenplayBeat], chunk_size: int = BEATS_PER_CHUNK) -> list[list[ScreenplayBeat]]:
    """Split a beat list into chunks of at most chunk_size.

    Prefers to break after an action or transition beat rather than
    mid-dialogue so no exchange is cut across a page-group boundary.
    """
    if len(beats) <= chunk_size:
        return [beats]

    chunks: list[list[ScreenplayBeat]] = []
    i = 0
    while i < len(beats):
        end = min(i + chunk_size, len(beats))
        # Look up to 4 beats beyond the nominal end for a clean break point.
        if end < len(beats):
            for j in range(end, min(end + 4, len(beats))):
                if beats[j].type in ("action", "transition"):
                    end = j + 1
                    break
        chunks.append(beats[i:end])
        i = end
    return chunks


def _build_user_content(
    screenplay: Screenplay,
    story_bible: StoryBible,
    beats: list[ScreenplayBeat] | None = None,
    page_group: int | None = None,
    total_pages: int | None = None,
    prev_context: str | None = None,
    prev_panel_context: str | None = None,
) -> str:
    """Build user message with screenplay (or page group) and character context."""
    char_info = []
    for cid in screenplay.characters:
        char = next((c for c in story_bible.characters if c.id == cid), None)
        if char:
            char_info.append(f"- {char.name} ({cid})")

    loc = next((loc for loc in story_bible.locations if loc.id == screenplay.location_id), None)
    loc_desc = f"Location: {loc.name} — {loc.visual_anchor}" if loc else ""

    # Use only the beats for this chunk; fall back to the full screenplay.
    chunk_sp = screenplay.model_copy(update={"beats": beats}) if beats is not None else screenplay

    parts = [f"SCENE: {screenplay.scene_id}"]
    if page_group is not None and total_pages is not None and total_pages > 1:
        parts.append(
            f"PAGE GROUP: {page_group} of {total_pages} "
            f"— include a panel for EVERY dialogue beat below, do not skip lines"
        )
    if prev_context:
        parts.append(f"CONTINUING FROM: {prev_context}")
    if prev_panel_context:
        parts.append(f"VISUAL CONTINUITY FROM PREVIOUS PANEL: {prev_panel_context}")
    parts += [
        loc_desc,
        "",
        "CHARACTERS:",
        *char_info,
        "",
        "SCREENPLAY:",
        chunk_sp.model_dump_json(indent=2),
    ]
    return "\n".join(parts)


def _context_note(beat: ScreenplayBeat, story_bible: StoryBible) -> str:
    """One-line summary of a beat, used as the 'continuing from' note for the next chunk."""
    if beat.type == "dialogue" and beat.character_id:
        char = next((c for c in story_bible.characters if c.id == beat.character_id), None)
        name = char.name if char else beat.character_id
        return f'{name}: "{beat.content}"'
    if beat.type == "transition":
        transition_type = beat.transition_type or "unknown"
        return f"transition [{transition_type}]: {beat.content}"
    return beat.content


def _panel_context(panel: PanelBreakdown, story_bible: StoryBible) -> str:
    """One-line summary of a panel, used as continuity context for the next chunk."""
    bits: list[str] = []
    for char_id in panel.characters_present:
        char = next((c for c in story_bible.characters if c.id == char_id), None)
        name = char.name if char else char_id
        action = panel.character_actions.get(char_id, "")
        expression = panel.character_expressions.get(char_id, "")
        position = panel.character_positions.get(char_id, "")
        details = [part for part in (action, expression, position) if part]
        if details:
            bits.append(f"{name}: {', '.join(details)}")
    summary = "; ".join(bits) if bits else "scene continues"
    transition_type = panel.transition_type or "unknown"
    if panel.transition_note:
        return f"{summary}; transition type: {transition_type}; transition: {panel.transition_note}"
    return f"{summary}; transition type: {transition_type}"


def _localized_system_prompt(config: Config, system_prompt: str) -> str:
    return f"{system_prompt.rstrip()}\n\nLANGUAGE REQUIREMENT:\n{config.generation_language_instruction()}"


async def _process_scene(
    config: Config,
    project_dir: Path,
    story_bible: StoryBible,
    scene_id: str,
    system_prompt: str,
    semaphore: asyncio.Semaphore,
) -> list[PanelBreakdown] | None:
    """Break a single screenplay into panels, splitting long screenplays into page groups."""
    screenplay_path = project_dir / "screenplays" / f"{scene_id}.json"
    if not screenplay_path.exists():
        return None

    panels_dir = project_dir / "panels" / scene_id
    completed_marker = panels_dir / ".completed"
    # Only skip if the .completed marker exists — a partial run leaves panel files
    # but no marker, so we re-run rather than accepting truncated data.
    if panels_dir.exists() and completed_marker.exists():
        return [
            PanelBreakdown.model_validate_json(p.read_text())
            for p in sorted(panels_dir.glob("panel_*.json"))
        ]

    screenplay = Screenplay.model_validate_json(screenplay_path.read_text())
    chunks = _chunk_beats(screenplay.beats)
    total_chunks = len(chunks)

    if total_chunks > 1:
        console.print(
            f"  [dim]{scene_id}: {len(screenplay.beats)} beats → "
            f"{total_chunks} page groups[/dim]"
        )

    all_panels: list[PanelBreakdown] = []
    panels_dir.mkdir(parents=True, exist_ok=True)
    prev_context: str | None = None
    prev_panel_context: str | None = None

    for chunk_idx, chunk_beats in enumerate(chunks):
        user_content = _build_user_content(
            screenplay,
            story_bible,
            beats=chunk_beats if total_chunks > 1 else None,
            page_group=chunk_idx + 1 if total_chunks > 1 else None,
            total_pages=total_chunks if total_chunks > 1 else None,
            prev_context=prev_context,
            prev_panel_context=prev_panel_context,
        )

        async with semaphore:
            result = await gemini.generate_json(
                config=config,
                model=config.panel_model,
                system_prompt=_localized_system_prompt(config, system_prompt),
                user_content=user_content,
            )

        raw_panels = result.get("panels", result if isinstance(result, list) else [])
        if not raw_panels:
            console.print(
                f"[yellow]Warning: No panels for {scene_id} "
                f"page group {chunk_idx + 1}/{total_chunks}[/yellow]"
            )
            # Still advance prev_context so the next chunk has continuity
        else:
            panel_offset = len(all_panels)
            for i, raw in enumerate(raw_panels):
                raw["scene_id"] = scene_id
                raw["panel_number"] = panel_offset + i + 1
                panel = PanelBreakdown.model_validate(raw)
                all_panels.append(panel)
            prev_panel_context = _panel_context(all_panels[-1], story_bible)

        prev_context = _context_note(chunk_beats[-1], story_bible)

    if not all_panels:
        console.print(f"[yellow]Warning: No panels returned for {scene_id}[/yellow]")
        return []

    # Write all panels to disk only after every chunk succeeds.
    for panel in all_panels:
        out = panels_dir / f"panel_{panel.panel_number:03d}.json"
        out.write_text(panel.model_dump_json(indent=2))

    # Mark the scene complete so partial runs are detected on retry.
    completed_marker.touch()
    return all_panels


async def run(
    config: Config,
    project_dir: Path,
    state: PipelineState,
    scene_ids: list[str] | None = None,
    on_event: EventCallback | None = None,
) -> None:
    """Execute Stage 4: Break screenplays into panel JSON."""
    emit = on_event or _NOOP

    story_bible = _load_story_bible(project_dir)
    system_prompt = PROMPT_PATH.read_text()

    ids = scene_ids or [s.id for s in story_bible.scenes]
    begin_stage(state, "panels", total=len(ids))
    emit({"type": "stage_begin", "stage": "panels", "total": len(ids)})
    save_state(state, project_dir)

    semaphore = asyncio.Semaphore(config.parallel_batch_size)

    try:
        with make_progress(on_event) as progress:
            task = progress.add_task("Panel breakdowns", total=len(ids))
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
                        emit({"type": "log", "stage": "panels", "level": "error",
                              "message": f"Failed {sid}: {result}"})
                        record_item_failed(state, "panels", sid)
                    else:
                        count = len(result) if result else 0
                        # Cost scales with the number of LLM calls made (≈1 per 6 panels).
                        num_calls = max(1, ceil(count / 6))
                        record_item_done(state, "panels", cost=0.005 * num_calls)
                        console.print(f"  {sid}: {count} panels")
                        emit({"type": "stage_progress", "stage": "panels",
                              "done": state.stages["panels"].items_done,
                              "total": state.stages["panels"].items_total})
                    progress.advance(task)
                save_state(state, project_dir)

        complete_stage(state, "panels")
        emit({"type": "stage_complete", "stage": "panels",
              "done": state.stages["panels"].items_done,
              "total": state.stages["panels"].items_total})
        save_state(state, project_dir)
        console.print("[green]Stage 4 complete.[/green]")

    except Exception as e:
        fail_stage(state, "panels", str(e))
        emit({"type": "stage_fail", "stage": "panels", "message": str(e)})
        save_state(state, project_dir)
        raise
