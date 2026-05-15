"""Stage 5b compatibility projection: LayoutPlan -> PanelBreakdown JSON.

This stage remains only to support existing storyboard-facing artifacts and UI
while the canonical structural source of truth has moved to layout_plan.
"""

from __future__ import annotations

from pathlib import Path

from rich.console import Console

from novel_to_comic.config import Config
from novel_to_comic.events import make_progress
from novel_to_comic.layout_planning import load_layout_plan, scene_panel_map, planned_panel_to_breakdown
from novel_to_comic.stage_runtime import StageRuntime

console = Console()


async def run(
    config: Config,
    project_dir: Path,
    ctx: StageRuntime,
    scene_ids: list[str] | None = None,
) -> None:
    """Project planned panels to legacy panel breakdown files."""
    plan = load_layout_plan(project_dir)
    panels_by_scene = scene_panel_map(plan)
    target_scene_ids = scene_ids or list(panels_by_scene.keys())
    if config.dev_mode and not scene_ids:
        target_scene_ids = target_scene_ids[:1]

    with ctx.execute(total=len(target_scene_ids)):
        with make_progress(None) as progress:
            task = progress.add_task("Panel projections", total=len(target_scene_ids))
            for scene_id in target_scene_ids:
                scene_dir = project_dir / "storyboard" / scene_id
                scene_dir.mkdir(parents=True, exist_ok=True)
                for old in scene_dir.glob("panel_*.json"):
                    old.unlink()
                (scene_dir / ".completed").unlink(missing_ok=True)

                planned_panels = panels_by_scene.get(scene_id, [])
                for panel in planned_panels:
                    breakdown = planned_panel_to_breakdown(panel)
                    out = scene_dir / f"panel_{panel.panel_number:03d}.json"
                    out.write_text(breakdown.model_dump_json(indent=2))
                if planned_panels:
                    (scene_dir / ".completed").touch()

                ctx.record_item_done()
                ctx.progress(ctx.stage_state.items_done, ctx.stage_state.items_total)
                if task is not None:
                    progress.advance(task)
                ctx.save()

        console.print("[green]Stage 5 complete.[/green] Projected layout plan into panels/.")


from novel_to_comic.stages import Stage  # noqa: E402

STAGE = Stage(
    name="storyboard",
    run=run,
    outputs=lambda d: [d / "storyboard"],
    clean_paths=lambda d: [
        d / "storyboard", d / "direct", d / "draw", d / "compose", d / "exports",
    ],
)
