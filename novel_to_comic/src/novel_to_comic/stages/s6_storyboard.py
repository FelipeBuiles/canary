"""Stage 6: Panel JSON → compact structured image prompt specs.

Assembles panel-specific prompt specs from structured pipeline artifacts.  The
selected style is stored for review, but Stage 6 prepends the current active
style at generation time so style changes do not require rebuilding prompts.
"""

import asyncio
from pathlib import Path

from rich.console import Console

from novel_to_comic import artifacts
from novel_to_comic.config import Config
from novel_to_comic.events import EventCallback, _NOOP, make_progress
from novel_to_comic.layout_planning import load_layout_plan, prompt_path_for_panel, scene_panel_map
from novel_to_comic.models.prompt import ImagePrompt
from novel_to_comic.models.story_bible import StoryBible
from novel_to_comic.prompting import (
    IMAGE_PROMPT_VERSION,
    build_planned_panel_prompt_spec,
    ensure_distilled_prompt,
)
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


async def _process_panel(
    config: Config,
    project_dir: Path,
    story_bible: StoryBible,
    panel,
    prev_panel,
) -> ImagePrompt | None:
    """Generate an image prompt for a single planned panel."""
    output_path = prompt_path_for_panel(project_dir, panel)
    if output_path.exists():
        existing = ImagePrompt.model_validate_json(output_path.read_text())
        if (
            existing.prompt_version >= IMAGE_PROMPT_VERSION
            and existing.planned_panel_id == panel.panel_id
            and existing.distilled_prompt
        ):
            return existing

    prompt = build_planned_panel_prompt_spec(config, project_dir, panel, story_bible, prev_panel)
    prompt = ensure_distilled_prompt(config, prompt)
    output_path.parent.mkdir(parents=True, exist_ok=True)
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

    story_bible = artifacts.read_story_bible(project_dir)

    plan_path = artifacts.layout_plan_path(project_dir)
    if not plan_path.exists():
        console.print("[red]No layout plan found. Run stage 4 (layout-plan) first.[/red]")
        emit({"type": "log", "stage": "direct", "level": "error",
              "message": "No layout plan found. Run stage 4 (layout-plan) first."})
        return
    plan = load_layout_plan(project_dir)
    panels_by_scene = scene_panel_map(plan)
    all_scene_ids = sorted(panels_by_scene.keys())
    if scene_ids:
        target_scene_ids = [s for s in all_scene_ids if s in set(scene_ids)]
    elif config.dev_mode:
        target_scene_ids = all_scene_ids[:1]
    else:
        target_scene_ids = all_scene_ids
    planned_panels = []
    for scene_id in target_scene_ids:
        scene_panels = panels_by_scene[scene_id]
        for index, panel in enumerate(scene_panels):
            prev_panel = scene_panels[index - 1] if index > 0 else None
            planned_panels.append((panel, prev_panel))

    begin_stage(state, "direct", total=len(planned_panels))
    emit({"type": "stage_begin", "stage": "direct", "total": len(planned_panels)})
    save_state(state, project_dir)

    try:
        with make_progress(on_event) as progress:
            task = progress.add_task("Image prompts", total=len(planned_panels))
            for batch_start in range(0, len(planned_panels), config.parallel_batch_size):
                batch = planned_panels[batch_start:batch_start + config.parallel_batch_size]
                coros = [
                    _process_panel(config, project_dir, story_bible, panel, prev_panel)
                    for panel, prev_panel in batch
                ]
                results = await asyncio.gather(*coros, return_exceptions=True)
                for (panel, _prev_panel), result in zip(batch, results):
                    if isinstance(result, Exception):
                        console.print(f"[red]Failed {panel.panel_id}: {result}[/red]")
                        emit({"type": "log", "stage": "direct", "level": "error",
                              "message": f"Failed {panel.panel_id}: {result}"})
                        record_item_failed(state, "direct", panel.panel_id)
                    else:
                        record_item_done(state, "direct")
                        emit({"type": "stage_progress", "stage": "direct",
                              "done": state.stages["direct"].items_done,
                              "total": state.stages["direct"].items_total})
                    progress.advance(task)
                save_state(state, project_dir)

        complete_stage(state, "direct")
        emit({"type": "stage_complete", "stage": "direct",
              "done": state.stages["direct"].items_done,
              "total": state.stages["direct"].items_total})
        save_state(state, project_dir)
        console.print("[green]Stage 6 complete.[/green]")

    except Exception as e:
        fail_stage(state, "direct", str(e))
        emit({"type": "stage_fail", "stage": "direct", "message": str(e)})
        save_state(state, project_dir)
        raise


from novel_to_comic.stages import Stage  # noqa: E402

STAGE = Stage(
    name="direct",
    run=run,
    outputs=lambda d: [d / "direct"],
    clean_paths=lambda d: [d / "direct", d / "draw", d / "compose", d / "exports"],
)
