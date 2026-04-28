"""Stage 5 compatibility projection: LayoutPlan -> PanelBreakdown JSON.

This stage remains only to support existing storyboard-facing artifacts and UI
while the canonical structural source of truth has moved to layout_plan.
"""

from __future__ import annotations

from pathlib import Path

from rich.console import Console

from novel_to_comic.config import Config
from novel_to_comic.events import EventCallback, _NOOP, make_progress
from novel_to_comic.layout_planning import load_layout_plan, scene_panel_map, planned_panel_to_breakdown
from novel_to_comic.state import (
    PipelineState,
    begin_stage,
    complete_stage,
    fail_stage,
    record_item_done,
    save_state,
)

console = Console()


async def run(
    config: Config,
    project_dir: Path,
    state: PipelineState,
    scene_ids: list[str] | None = None,
    on_event: EventCallback | None = None,
) -> None:
    """Project planned panels to legacy panel breakdown files."""
    emit = on_event or _NOOP
    plan = load_layout_plan(project_dir)
    panels_by_scene = scene_panel_map(plan)
    target_scene_ids = scene_ids or list(panels_by_scene.keys())
    if config.dev_mode and not scene_ids:
        target_scene_ids = target_scene_ids[:1]

    begin_stage(state, "storyboard", total=len(target_scene_ids))
    emit({"type": "stage_begin", "stage": "storyboard", "total": len(target_scene_ids)})
    save_state(state, project_dir)

    try:
        with make_progress(on_event) as progress:
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

                record_item_done(state, "storyboard")
                emit(
                    {
                        "type": "stage_progress",
                        "stage": "storyboard",
                        "done": state.stages["storyboard"].items_done,
                        "total": state.stages["storyboard"].items_total,
                    }
                )
                progress.advance(task)
                save_state(state, project_dir)

        complete_stage(state, "storyboard")
        emit(
            {
                "type": "stage_complete",
                "stage": "storyboard",
                "done": state.stages["storyboard"].items_done,
                "total": state.stages["storyboard"].items_total,
            }
        )
        save_state(state, project_dir)
        console.print("[green]Stage 5 complete.[/green] Projected layout plan into panels/.")

    except Exception as exc:
        fail_stage(state, "storyboard", str(exc))
        emit({"type": "stage_fail", "stage": "storyboard", "message": str(exc)})
        save_state(state, project_dir)
        raise
