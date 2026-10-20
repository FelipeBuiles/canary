"""Render text-check status and execution against one immutable active render."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Callable
from novel_to_comic.models.page import ComicPage
from novel_to_comic.models.draw import PageRenderRevision
from .codex_admission import Operations
from novel_to_comic.target_artifacts import ArtifactMissing, ArtifactInvalid, TargetArtifacts
from novel_to_comic.page_review import OCRRequired, analysis_is_current, revalidate_cached_page_render
from novel_to_comic.page_drawing import analyze_complete_page
from novel_to_comic.lettering.page_read import page_read_adapter
from .codex_admission import page_check_operations

def active_provenance(target, page_number):
    revision = target.active_render_revision(page_number)
    return target.read_provenance(page_number, revision) if revision is not None else None


def render_check_status(target: TargetArtifacts, page_number: int) -> dict:
    """Describe reusable evidence without mutating artifacts or reading a provider.

    Invalid evidence is a failed check, never permission to purchase another
    read. A saved but unreadable provider answer is the explicit exception:
    it contains no observations to recover.
    """
    try:
        active = active_provenance(target, page_number)
        if active is None:
            return {"status": "undrawn", "requires_paid_call": False}
        render = active.render
        page = target.read_page(page_number)
        if render.is_stale_for(page):
            return {"status": "stale_render", "requires_paid_call": False}
        try:
            analysis = target.read_analysis(page_number, render.revision)
        except ArtifactMissing:
            analysis = None
        if analysis is not None:
            if analysis.render_image_sha256 != render.image_sha256:
                raise ValueError("saved OCR analysis belongs to different render bytes")
            if (analysis.comic_page_sha256 == page.content_sha256
                    and analysis_is_current(analysis.validator_version)):
                return {"status": "checked", "requires_paid_call": False}
        # A previous validator's analysis retains primary observations too.
        cached = analysis is not None
        try:
            raw = target.read_raw_ocr(page_number, render.revision)
        except ArtifactMissing:
            raw = None
        if raw is not None:
            if (raw.schema_version != 1 or raw.page_number != page_number
                    or raw.render_revision != render.revision
                    or raw.render_image_sha256 != render.image_sha256):
                raise ValueError("saved OCR observations belong to different render bytes")
            cached = True
        if not cached:
            try:
                response = target.read_ocr_response(page_number, render.revision)
            except ArtifactMissing:
                response = None
            if response is not None:
                if (response.page_number != page_number or response.render_revision != render.revision
                        or response.render_image_sha256 != render.image_sha256
                        or response.request_sha256 != render.request_sha256):
                    raise ValueError("saved OCR response belongs to different render lineage")
                from novel_to_comic.page_review import saved_ocr_draft
                cached = saved_ocr_draft(response) is not None
        return {"status": "cached_evidence" if cached else "requires_ocr",
                "requires_paid_call": not cached}
    except (ArtifactMissing, ArtifactInvalid, ValueError) as exc:
        return {"status": "failed", "phase": "analysis", "error": str(exc),
                "requires_paid_call": False}


async def run_render_check(*, target, project_dir, config, page_number, project_id, user_id,
                           allow_paid=True, expected_image_sha256=None, second_look_only=False):
    active = active_provenance(target, page_number)
    if active is None:
        raise ValueError("Page has no render to analyze")
    try:
        page = target.read_page(page_number)
        image = target.read_render(page_number, active.render.revision)
    except ArtifactMissing as exc:
        raise ValueError(str(exc)) from exc
    from .credited_job import run_credited_page_check
    from novel_to_comic.config import PAGE_OCR_ESTIMATED_COST_USD
    from novel_to_comic import textract_ocr
    # Saved primary observations are immutable; without them, reserve the read.
    primary_needed = render_check_status(target, page_number)["requires_paid_call"]
    if second_look_only and primary_needed:
        raise ValueError("This page needs a full text check before a second look")
    def cached_work():
        guard_active_render(target, page, active.render, image, expected_image_sha256)
        try:
            analysis = revalidate_cached_page_render(
                page=page, render=active.render, artifacts=target,
            )
            if (allow_paid and textract_ocr.enabled() and analysis.crop_verification is not None
                    and not analysis.crop_verification.complete):
                return None
        except ArtifactMissing as exc:
            if isinstance(exc, OCRRequired):
                if not allow_paid:
                    raise ValueError("Text check requires an explicitly approved OCR-only call")
                return None
            raise
        return analysis
    analysis = await run_credited_page_check(
        user_id=user_id, project_id=project_id, project_dir=project_dir,
        page_number=page_number, estimated_cost_usd=float(PAGE_OCR_ESTIMATED_COST_USD) if primary_needed else 0.0,
        cached_work=cached_work,
        operations=page_check_operations(config) if primary_needed else (),
        work=lambda: analyze_complete_page(
            page=page, render=active.render, image=image,
            ocr=page_read_adapter(config, target, page), artifacts=target,
            retry_crop_ocr=True,
        ),
    )
    target.clear_page_failure(page_number)
    from novel_to_comic.page_drawing import reconcile_recovered_page_generation
    reconcile_recovered_page_generation(artifacts=target, render=active.render)
    return analysis


def quote_render_check(target, page_number, config):
    """Quote the same primary-evidence decision used by the credited run."""
    from novel_to_comic.config import PAGE_OCR_ESTIMATED_COST_USD
    from novel_to_comic.codex_dev import classify_operations
    from .credits import credit_estimate_for_provider_cost

    _check_inputs(target, page_number)
    status = render_check_status(target, page_number)
    if status["status"] == "failed":
        raise ValueError(status["error"])
    paid = status["requires_paid_call"]
    return dict(credit_estimate_for_provider_cost(
        float(PAGE_OCR_ESTIMATED_COST_USD) if paid else 0.0, "draw", reserve=True,
        funding=classify_operations(page_check_operations(config) if paid else ()),
    ))


def guard_active_render(target, page, render, image, expected_image_sha256=None):
    """Refuse changed canonical inputs or artwork before any check can spend."""
    if render.is_stale_for(page):
        raise ValueError("page render is stale for the canonical ComicPage")
    if hashlib.sha256(image).hexdigest() != render.image_sha256:
        raise ValueError("Saved artwork bytes do not match render lineage")
    if expected_image_sha256 is not None and render.image_sha256 != expected_image_sha256:
        raise ValueError("Approved artwork changed; reload the text-check estimate")
    latest = active_provenance(target, page.page_number)
    current = target.read_page(page.page_number)
    if latest is None or latest.render != render or current.content_sha256 != page.content_sha256:
        raise ValueError("Active artwork changed; reload the text-check estimate")


def _check_inputs(target, page_number):
    active = active_provenance(target, page_number)
    if active is None:
        raise ValueError("Page has no render to review")
    page = target.read_page(page_number)
    image = target.read_render(page_number, active.render.revision)
    guard_active_render(target, page, active.render, image)
    return page, active.render, image


def _quote(cost, operations):
    from novel_to_comic.codex_dev import classify_operations
    from .credits import credit_estimate_for_provider_cost
    return credit_estimate_for_provider_cost(cost, "draw", reserve=True,
        funding=classify_operations(operations))


def prepare_render_check(target, page_number, config, *, kind, changes=None):
    """Prepare visual or change checks against the same immutable render guard."""
    from .codex_admission import visual_review_operations, correction_interpret_operations
    page, render, image = _check_inputs(target, page_number)
    if kind == "visual":
        from novel_to_comic.page_visual_review import compile_visual_review, review_page_visuals
        from novel_to_comic.config import PAGE_VISUAL_REVIEW_ESTIMATED_COST_USD
        compiled = compile_visual_review(target.project_dir, config, target, page)
        cost = float(PAGE_VISUAL_REVIEW_ESTIMATED_COST_USD)
        operations = visual_review_operations(config)
        def work():
            return review_page_visuals(config=config, page=page, render=render,
                image=image, compiled=compiled, artifacts=target,
                producing_request=target.producing_request(render))
    elif kind == "change":
        from novel_to_comic.correction_interpreter import (
            estimate_interpretation_cost, interpretation_prompt, interpret_changes,
        )
        from novel_to_comic.lettering.service import is_hybrid
        from novel_to_comic.stages.s5_plan import approved_visual_inventory
        if changes is None or not changes.changes:
            raise ValueError("Add a change before checking it.")
        if (changes.parent_render_revision, changes.comic_page_revision) != (render.revision, page.revision):
            raise ValueError("The page changed since this draft was written; reload it and try again.")
        inventory = approved_visual_inventory(target.project_dir)
        lettering_in_art = not is_hybrid(target)
        prompt = interpretation_prompt(page=page, inventory=inventory, changes=changes.changes,
            lettering_in_art=lettering_in_art)
        cost = estimate_interpretation_cost(config, prompt, len(changes.changes))
        operations = correction_interpret_operations(config)
        def work():
            return interpret_changes(config=config, page=page, inventory=inventory,
                image=image, changes=changes.changes, lettering_in_art=lettering_in_art)
    else:
        raise ValueError(f"Unknown render check kind: {kind}")
    return PreparedRenderCheck(target, page, render, image, cost, operations, work)


@dataclass(frozen=True)
class PreparedRenderCheck:
    target: TargetArtifacts
    page: ComicPage
    render: PageRenderRevision
    image: bytes
    cost: float
    operations: Operations
    work: Callable

    def quote(self):
        return _quote(self.cost, self.operations)

    async def run(self, *, user_id, project_id, allow_paid=True, expected_image_sha256=None):
        from .credited_job import run_credited_page_check
        if not allow_paid:
            raise ValueError("This check requires an explicitly approved call")
        def guard():
            guard_active_render(self.target, self.page, self.render, self.image, expected_image_sha256)
        return await run_credited_page_check(
            user_id=user_id, project_id=project_id, project_dir=self.target.project_dir,
            page_number=self.page.page_number, estimated_cost_usd=self.cost,
            operations=self.operations, cached_work=guard, work=self.work,
        )


def visual_reviewed(target: TargetArtifacts, page_number: int) -> bool:
    """Whether the active art has a saved visual review. A status hint only:
    the page review panel still serves a result only for current inputs."""
    active = active_provenance(target, page_number)
    if active is None:
        return False
    try:
        reviews = target.read_visual_reviews(page_number, active.render.revision)
    except ArtifactInvalid:
        return False
    return any(review.render_image_sha256 == active.render.image_sha256 for review in reviews)


def page_check_failure(target: TargetArtifacts, page_number: int):
    if render_check_status(target, page_number)["status"] == "checked":
        return None
    try:
        failure = target.read_page_failure(page_number)
    except ArtifactMissing:
        return None
    revisions = target.provenance_revisions(page_number)
    if revisions and not target.analysis_path(page_number, revisions[-1]).exists():
        return failure.model_copy(
            update={
                "phase": "analysis",
                "classification": "analysis_error",
                "recoverable": True,
                "user_message": (
                    "The page is already drawn, but its text check could not be "
                    "completed. Retry the text check without redrawing the page."
                ),
            }
        )
    return failure
