"""Stage 5: Panel JSON → compact structured image prompt specs.

Assembles panel-specific prompt specs from structured pipeline artifacts.  The
selected style is stored for review, but Stage 6 prepends the current active
style at generation time so style changes do not require rebuilding prompts.
"""

import asyncio
from pathlib import Path

from rich.console import Console
from rich.progress import Progress

from novel_to_comic.config import Config
from novel_to_comic.events import EventCallback, _NOOP, make_progress
from novel_to_comic.models.panel import PanelBreakdown
from novel_to_comic.models.prompt import ImagePrompt
from novel_to_comic.models.story_bible import StoryBible
from novel_to_comic.prompting import IMAGE_PROMPT_VERSION, build_image_prompt_spec
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


def _load_story_bible(project_dir: Path) -> StoryBible:
    return StoryBible.model_validate_json((project_dir / "story_bible.json").read_text())


async def _process_panel(
    config: Config,
    project_dir: Path,
    story_bible: StoryBible,
    panel_path: Path,
) -> ImagePrompt | None:
    """Generate an image prompt for a single panel."""
    panel = PanelBreakdown.model_validate_json(panel_path.read_text())
    prev_panel: PanelBreakdown | None = None
    if panel.panel_number > 1:
        prev_panel_path = project_dir / "panels" / panel.scene_id / f"panel_{panel.panel_number - 1:03d}.json"
        if prev_panel_path.exists():
            prev_panel = PanelBreakdown.model_validate_json(prev_panel_path.read_text())

    output_dir = project_dir / "prompts" / panel.scene_id
    output_path = output_dir / f"panel_{panel.panel_number:03d}.json"
    if output_path.exists():
        existing = ImagePrompt.model_validate_json(output_path.read_text())
        if getattr(existing, "prompt_version", 1) >= IMAGE_PROMPT_VERSION:
            return existing

    prompt = build_image_prompt_spec(config, project_dir, panel, story_bible, prev_panel)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path.write_text(prompt.model_dump_json(indent=2))
    return prompt


async def run(
    config: Config,
    project_dir: Path,
    state: PipelineState,
    scene_ids: list[str] | None = None,
    on_event: EventCallback | None = None,
) -> None:
    """Execute Stage 5: Generate image prompts for all panels."""
    emit = on_event or _NOOP

    story_bible = _load_story_bible(project_dir)

    # Collect all panel files
    panels_dir = project_dir / "panels"
    panel_files: list[Path] = []
    if not panels_dir.exists():
        console.print("[red]No panels found. Run stage 4 (panels) first.[/red]")
        emit({"type": "log", "stage": "prompts", "level": "error",
              "message": "No panels found. Run stage 4 (panels) first."})
        return
    target_scenes = set(scene_ids) if scene_ids else None
    for scene_dir in sorted(panels_dir.iterdir()):
        if not scene_dir.is_dir():
            continue
        if target_scenes and scene_dir.name not in target_scenes:
            continue
        for pf in sorted(scene_dir.glob("panel_*.json")):
            panel_files.append(pf)

    begin_stage(state, "prompts", total=len(panel_files))
    emit({"type": "stage_begin", "stage": "prompts", "total": len(panel_files)})
    save_state(state, project_dir)

    try:
        panel_files_sorted = sorted(
            panel_files,
            key=lambda pf: (
                pf.parent.name,
                int(pf.stem.split("_")[1]) if "_" in pf.stem else 0,
            ),
        )

        with make_progress(on_event) as progress:
            task = progress.add_task("Image prompts", total=len(panel_files))
            for batch_start in range(0, len(panel_files_sorted), config.parallel_batch_size):
                batch = panel_files_sorted[batch_start:batch_start + config.parallel_batch_size]
                coros = [_process_panel(config, project_dir, story_bible, pf) for pf in batch]
                results = await asyncio.gather(*coros, return_exceptions=True)
                for pf, result in zip(batch, results):
                    if isinstance(result, Exception):
                        console.print(f"[red]Failed {pf.name}: {result}[/red]")
                        emit({"type": "log", "stage": "prompts", "level": "error",
                              "message": f"Failed {pf.name}: {result}"})
                        record_item_failed(state, "prompts", str(pf))
                    else:
                        record_item_done(state, "prompts", cost=0.001)
                        emit({"type": "stage_progress", "stage": "prompts",
                              "done": state.stages["prompts"].items_done,
                              "total": state.stages["prompts"].items_total})
                    progress.advance(task)
                save_state(state, project_dir)

        complete_stage(state, "prompts")
        emit({"type": "stage_complete", "stage": "prompts",
              "done": state.stages["prompts"].items_done,
              "total": state.stages["prompts"].items_total})
        save_state(state, project_dir)
        console.print("[green]Stage 5 complete.[/green]")

    except Exception as e:
        fail_stage(state, "prompts", str(e))
        emit({"type": "stage_fail", "stage": "prompts", "message": str(e)})
        save_state(state, project_dir)
        raise
