"""Active complete-page Draw stage."""

from __future__ import annotations

from pathlib import Path

from novel_to_comic.config import PAGE_OCR_ESTIMATED_COST_USD, Config
from novel_to_comic.page_drawing import production_page_capability_profile
from novel_to_comic.stage_runtime import StageRuntime
from novel_to_comic.state import PipelineState
from novel_to_comic.target_artifacts import TargetArtifacts

from novel_to_comic.stages import Stage, clean_cascade


async def run(config: Config, project_dir: Path, ctx: StageRuntime) -> None:
    target = TargetArtifacts(project_dir)
    plan = target.read_plan()
    ctx.begin(total=len(plan.pages))
    # Complete-page provider work is queued and credited per page through the
    # Draw routes. The checkpoint remains running until every page has a render.
    from novel_to_comic.page_drawing import select_book_edition

    edition = select_book_edition(
        edition_id="book-edition-001",
        profile=production_page_capability_profile(),
    )
    target.write_book_edition(edition)


def estimate_cost(config: Config, project_dir: Path, state: PipelineState) -> float:
    target = TargetArtifacts(project_dir)
    if not target.plan_path.exists():
        return 0.0
    profile = production_page_capability_profile()
    # Every page is generated and then read back, and both are billable.
    from novel_to_comic.page_drawing import _selected_authorities
    from novel_to_comic.stages.s5_plan import approved_visual_inventory

    inventory = approved_visual_inventory(project_dir)
    total = 0.0
    for selected in target.read_plan().pages:
        page = target.read_page(selected.page_number)
        references = _selected_authorities(page, inventory)
        total += float(profile.price_per_page_usd)
        total += float(profile.price_per_reference_usd) * len(references)
        total += float(PAGE_OCR_ESTIMATED_COST_USD)
    return total


STAGE = Stage(
    name="draw",
    run=run,
    outputs=lambda d: [d / "draw"],
    clean_paths=lambda d: clean_cascade(d, "draw"),
    estimate_cost=estimate_cost,
)
