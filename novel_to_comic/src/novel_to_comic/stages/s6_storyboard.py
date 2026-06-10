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
from novel_to_comic.events import make_progress
from novel_to_comic.layout_planning import load_layout_plan, prompt_path_for_panel, scene_panel_map
from novel_to_comic.models.prompt import ImagePrompt
from novel_to_comic.models.story_bible import StoryBible
from novel_to_comic.prompt_assembly import (
    ensure_current_panel_prompt,
    ensure_distilled_prompt,
    ensure_visual_brief,
)
from novel_to_comic.stage_runtime import StageRuntime

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
    prompt = ensure_current_panel_prompt(config, project_dir, panel, story_bible, prev_panel)
    updated = ensure_distilled_prompt(config, prompt)
    updated = await ensure_visual_brief(config, updated)
    if updated is not prompt:
        output_path.write_text(updated.model_dump_json(indent=2))
    return updated


async def run(
    config: Config,
    project_dir: Path,
    ctx: StageRuntime,
    scene_ids: list[str] | None = None,
) -> None:
    """Execute the direct stage: generate image prompts for all panels."""
    story_bible = artifacts.read_story_bible(project_dir)

    plan_path = artifacts.layout_plan_path(project_dir)
    if not plan_path.exists():
        console.print("[red]No layout plan found. Run stage 4 (layout-plan) first.[/red]")
        ctx.log("No layout plan found. Run stage 4 (layout-plan) first.", level="error")
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

    with ctx.execute(total=len(planned_panels)):
        with make_progress(ctx.on_event) as progress:
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
                        ctx.log(f"Failed {panel.panel_id}: {result}", level="error")
                        ctx.record_item_failed(panel.panel_id)
                    else:
                        ctx.record_item_done()
                        ctx.progress(ctx.stage_state.items_done, ctx.stage_state.items_total)
                    if task is not None:
                        progress.advance(task)
                ctx.save()

        console.print("[green]Direct stage complete.[/green]")


from novel_to_comic.stages import Stage, clean_cascade  # noqa: E402

STAGE = Stage(
    name="direct",
    run=run,
    outputs=lambda d: [d / "direct"],
    clean_paths=lambda d: clean_cascade(d, "direct"),
)
