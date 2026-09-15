"""Active complete-page Draw stage."""

from __future__ import annotations

from pathlib import Path

from novel_to_comic.config import Config
from novel_to_comic.page_drawing import current_page_capability_profile, ensure_current_page_edition
from novel_to_comic.stage_runtime import StageRuntime
from novel_to_comic.state import PipelineState
from novel_to_comic.target_artifacts import TargetArtifacts

from novel_to_comic.stages import Stage, clean_cascade


async def run(config: Config, project_dir: Path, ctx: StageRuntime) -> None:
    from novel_to_comic.codex_dev import classify_operations
    from novel_to_comic.server.codex_admission import draw_operations

    classify_operations(draw_operations(config))
    target = TargetArtifacts(project_dir)
    from novel_to_comic.narrative_review import require_draw_narrative_reviews
    require_draw_narrative_reviews(target)
    plan = target.read_plan()
    existing = (
        ensure_current_page_edition(target, target.read_book_edition(), config)
        if target.book_edition_path.exists() else None
    )
    # Complete-page provider work is queued and credited per page through the
    # Draw routes. The checkpoint remains running until every page has a render.
    from novel_to_comic.page_drawing import select_book_edition

    edition = select_book_edition(
        edition_id=existing.id if existing is not None else "book-edition-001",
        profile=current_page_capability_profile(config),
        existing=existing,
    )
    ctx.begin(total=len(plan.pages))
    if existing is None:
        target.write_book_edition(edition)


def estimate_cost(config: Config, project_dir: Path, state: PipelineState) -> float:
    from novel_to_comic.codex_dev import classify_operations
    from novel_to_comic.server.codex_admission import draw_operations

    classify_operations(draw_operations(config))
    target = TargetArtifacts(project_dir)
    profile = (
        ensure_current_page_edition(target, target.read_book_edition(), config).capability_profile
        if target.book_edition_path.exists() else current_page_capability_profile(config)
    )
    if not target.plan_path.exists():
        return 0.0
    # Drawing estimates artwork only; text review is an explicit optional action.
    from novel_to_comic.page_drawing import (
        compile_page_generation_request,
        estimate_draw_api_cost, select_book_edition,
    )
    from novel_to_comic.models.draw import RetryProvenance
    from novel_to_comic.stages.s5_plan import approved_reference_files, approved_visual_inventory

    inventory = approved_visual_inventory(project_dir)
    reference_files = approved_reference_files(project_dir)
    edition = select_book_edition(edition_id="estimate", profile=profile)
    total = 0.0
    for selected in target.read_plan().pages:
        page = target.read_page(selected.page_number)
        compiled = compile_page_generation_request(
            page, edition, inventory, reference_files,
            retry=RetryProvenance(attempt=1), style_template=config.style_template,
            reservations=target.page_reservations(page.page_number),
        )
        total += estimate_draw_api_cost(
            config,
            float(compiled.request.estimated_cost_usd), compiled=compiled,
        )
    return total


STAGE = Stage(
    name="draw",
    run=run,
    outputs=lambda d: [d / "draw"],
    clean_paths=lambda d: clean_cascade(d, "draw"),
    estimate_cost=estimate_cost,
)
