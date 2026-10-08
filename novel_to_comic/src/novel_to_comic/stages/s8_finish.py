"""Active provider-free Finish stage."""

from __future__ import annotations

import asyncio
from pathlib import Path

from novel_to_comic.config import Config
from novel_to_comic.page_finishing import finish_book
from novel_to_comic.stage_runtime import StageRuntime
from novel_to_comic.target_artifacts import TargetArtifacts

from novel_to_comic.stages import Stage, clean_cascade


async def run(
    config: Config,
    project_dir: Path,
    ctx: StageRuntime,
    *,
    formats: tuple[str, ...] = ("pdf", "cbz"),
    clear_derived_outputs: bool = True,
):
    with ctx.execute(total=1, estimated_cost_usd=0):
        result = await asyncio.to_thread(finish_book,
            TargetArtifacts(project_dir),
            formats=formats,
            clear_derived_outputs=clear_derived_outputs,
        )
        ctx.record_item_done()
        ctx.progress(1, 1)
    return result


STAGE = Stage(
    name="finish",
    run=run,
    outputs=lambda d: [TargetArtifacts(d).preflight_path, d / "exports"],
    clean_paths=lambda d: clean_cascade(d, "finish"),
    estimate_cost=lambda _config, _project_dir, _state: 0.0,
)
