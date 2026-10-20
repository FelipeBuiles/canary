"""Active complete-page Draw stage."""

from __future__ import annotations

from pathlib import Path

from novel_to_comic.config import Config
from novel_to_comic.stage_runtime import StageRuntime
from novel_to_comic.state import PipelineState
from novel_to_comic.target_artifacts import TargetArtifacts

from novel_to_comic.stages import Stage, clean_cascade


async def run(config: Config, project_dir: Path, ctx: StageRuntime) -> None:
    from novel_to_comic.server.draw_submission import initialize_draw_stage
    plan = initialize_draw_stage(TargetArtifacts(project_dir), config)
    # The checkpoint stays running while the per-page durable commands execute.
    ctx.begin(total=len(plan.pages))


def estimate_cost(config: Config, project_dir: Path, state: PipelineState) -> float:
    from novel_to_comic.server.draw_submission import estimate_draw_stage_cost
    return estimate_draw_stage_cost(TargetArtifacts(project_dir), config)


STAGE = Stage(
    name="draw",
    run=run,
    outputs=lambda d: [d / "draw"],
    clean_paths=lambda d: clean_cascade(d, "draw"),
    estimate_cost=estimate_cost,
)
