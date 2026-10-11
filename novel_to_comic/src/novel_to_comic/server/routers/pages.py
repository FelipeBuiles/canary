"""Complete-page Draw and review-by-exception routes."""

from __future__ import annotations

from ..page_operations import (_generation_retry, _sync_draw_progress, enqueue_all_undrawn_pages, prepare_undrawn_pages)


from novel_to_comic.style_reference import require_style_reference
from novel_to_comic.server.codex_admission import visual_review_operations

import asyncio
import uuid
import hashlib
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from novel_to_comic.models.draw import (
    CorrectionChange,
    PageIssue,
    RetryProvenance,
)
from novel_to_comic.page_drawing import (
    complete_page_adapter,
    analyze_complete_page,
    compile_page_generation_request,
    correction_credit_estimate,
    ensure_current_page_edition,
    prepare_page_correction,
)
from novel_to_comic.narrative_review import draw_review_recheck_phases, require_draw_narrative_reviews
from novel_to_comic.page_previews import ensure_page_render_preview
from novel_to_comic.page_source import PageSourceStale, page_source_view
from novel_to_comic.lettering.page_read import page_read_adapter
from novel_to_comic.page_ocr import GatewayPageOCRAdapter  # noqa: F401  (tests patch it here)
from novel_to_comic.page_review import (
    accept_editorial_page_issue,
    dismiss_page_issue,
    record_page_issue,
    summarize_page_issues,
    revalidate_cached_page_render,
    analysis_is_current,
)
from novel_to_comic.stages.s5_plan import (
    approved_reference_files,
    approved_visual_inventory,
)
from novel_to_comic.target_artifacts import ArtifactInvalid, ArtifactMissing, TargetArtifacts

from ..auth import get_current_user
from novel_to_comic.codex_dev import classify_operations
from ..codex_admission import draw_operations, page_check_operations
from ..deps import event_key, get_project, project_key
from ..generation_jobs import generation_job_payload, generation_jobs_snapshot
from ..page_outcomes import record_page_outcome


from ..page_admission import enqueue_complete_page_draw

router = APIRouter()


class PageIssueCreate(BaseModel):
    issue_type: str
    classification: str = "editorial_issue"
    correction_kind: str = "render_fidelity"
    correction_owner: str = "draw"
    evidence: tuple[str, ...]
    requested_correction: str
    source_unit_ids: tuple[str, ...] = ()
    adapted_beat_ids: tuple[str, ...] = ()
    lettering_item_ids: tuple[str, ...] = ()
    detected_region_ids: tuple[str, ...] = ()
    entity_ids: tuple[str, ...] = ()
    appearance_state_ids: tuple[str, ...] = ()


class PageGenerationCreate(BaseModel):
    depiction: Literal["canonical", "less_graphic"] = "canonical"



def _hybrid_lettering(target):
    from novel_to_comic.lettering.service import is_hybrid
    return is_hybrid(target)


def _lettering_revision(target, number):
    try:
        return target.read_lettering(number).revision
    except (ArtifactMissing, ArtifactInvalid):
        return None

def _lettering_placement_review_needed(target, number, hybrid: bool) -> bool:
    """Flag drawn editable pages whose saved lettering was not checked against this art."""
    if not hybrid:
        return False
    provenance = _latest_provenance(target, number)
    if provenance is None or provenance.render.is_stale_for(target.read_page(number)):
        return False
    try:
        state = target.read_lettering(number)
    except (ArtifactMissing, ArtifactInvalid):
        return True
    from novel_to_comic.lettering.service import placement_review_needed
    return placement_review_needed(state, provenance.render)


def _redraw_inputs(project_dir):
    from novel_to_comic.stages.s5_plan import approved_visual_inventory

    inventory = {ref.id: ref for ref in approved_visual_inventory(project_dir).references}
    return approved_reference_files(project_dir), inventory


def _redraws(project_dir, target: TargetArtifacts) -> dict[int, dict]:
    """Drawn pages whose plan, Story Bible entries or Cast references changed after drawing."""
    from novel_to_comic.page_redraws import pages_needing_redraw

    try:
        return pages_needing_redraw(target, *_redraw_inputs(project_dir))
    except (ArtifactMissing, ArtifactInvalid, ValueError, OSError):
        return {}


def _page_redraw(project_dir, target: TargetArtifacts, page_number: int) -> dict | None:
    from novel_to_comic.page_redraws import redraw_reasons

    try:
        return redraw_reasons(target, page_number, *_redraw_inputs(project_dir))
    except (ArtifactMissing, ArtifactInvalid, ValueError, OSError):
        return None


def _latest_provenance(target: TargetArtifacts, page_number: int):
    revision = target.active_render_revision(page_number)
    return target.read_provenance(page_number, revision) if revision is not None else None


def _issues(target: TargetArtifacts, page_number: int):
    try:
        return target.read_issues(page_number)
    except ArtifactMissing:
        return ()


def _correctable_issue_ids(target: TargetArtifacts, page_number: int) -> tuple[str, ...]:
    from novel_to_comic.page_review import correctable_issue_ids

    active = _latest_provenance(target, page_number)
    return correctable_issue_ids(
        target, tuple(_issues(target, page_number)), active.render if active is not None else None,
    )


def _analysis_recovery(target: TargetArtifacts, page_number: int) -> dict:
    active = _latest_provenance(target, page_number)
    if active is None:
        return {"status": "undrawn", "requires_paid_call": False}
    render = active.render
    try:
        page = target.read_page(page_number)
        if render.is_stale_for(page):
            return {"status": "stale_render", "requires_paid_call": False}
        analysis = target.read_analysis(page_number, render.revision)
        if (analysis.render_image_sha256 == render.image_sha256
                and analysis.comic_page_sha256 == page.content_sha256
                and analysis_is_current(analysis.validator_version)):
            # An unfinished optional second look never makes the page unchecked;
            # the author retries it from the finding, at Canary's cost.
            return {"status": "checked", "requires_paid_call": False}
    except (ArtifactMissing, ArtifactInvalid):
        pass
    cached = any(path.exists() for path in (
        target.raw_ocr_path(page_number, render.revision),
        target.analysis_path(page_number, render.revision),
    )) or _readable_ocr_response(target, page_number, render.revision)
    return {"status": "cached_evidence" if cached else "requires_ocr",
            "requires_paid_call": not cached}


def _readable_ocr_response(target: TargetArtifacts, page_number: int, revision: int) -> bool:
    """A saved answer counts as free evidence only when it can be read."""
    from novel_to_comic.page_review import saved_ocr_draft

    try:
        return saved_ocr_draft(target.read_ocr_response(page_number, revision)) is not None
    except (ArtifactMissing, ArtifactInvalid):
        return False


def _visual_reviewed(target: TargetArtifacts, page_number: int) -> bool:
    """Whether the active art has a saved visual review. A status hint only:
    the page review panel still serves a result only for current inputs."""
    active = _latest_provenance(target, page_number)
    if active is None:
        return False
    try:
        reviews = target.read_visual_reviews(page_number, active.render.revision)
    except ArtifactInvalid:
        return False
    return any(review.render_image_sha256 == active.render.image_sha256 for review in reviews)


def _page_failure(target: TargetArtifacts, page_number: int):
    if _analysis_recovery(target, page_number)["status"] == "checked":
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




def _aggregated_correction_retry(
    target: TargetArtifacts,
    *,
    page_number: int,
    issue_ids: tuple[str, ...],
) -> RetryProvenance:
    """Advance retry identity for one exact selected-issue set."""
    selected = frozenset(issue_ids)
    resumable = target.resumable_generation_request(page_number)
    if (resumable is not None and resumable.correction is not None
            and frozenset(resumable.correction.issue_ids) == selected):
        return resumable.retry
    prior_attempts = [
        target.read_request(page_number, revision)
        for revision in target.request_revisions(page_number)
    ]
    matching = [
        request
        for request in prior_attempts
        if request.correction is not None
        and frozenset(request.correction.issue_ids) == selected
    ]
    if not matching:
        return RetryProvenance(attempt=1)
    prior = max(matching, key=lambda request: request.retry.attempt)
    return RetryProvenance(
        attempt=prior.retry.attempt + 1,
        retries_request_sha256=prior.request_sha256,
    )


def _select_active_correction_job(jobs, *, pkey: str, page_number: int, request_sha256: str):
    """Share one identical in-flight request; reject anything else on the page.

    An identical frozen request already queued or running is shared, so submit
    retries never double-enqueue. Any other active draw job for the same page
    means changed instructions: reject as busy instead of absorbing or
    dropping the edited request into the running one.
    """
    busy = None
    for job in jobs:
        if job.project_name != pkey or job.kind != "complete_page_draw":
            continue
        if job.status not in {"queued", "running"}:
            continue
        if job.payload.get("page_number") != page_number:
            continue
        if job.payload.get("request_sha256") == request_sha256:
            return ("share", job)
        if busy is None:
            busy = job
    if busy is not None:
        return ("busy", busy)
    return ("free", None)












@router.get("/pages")
def list_pages(request: Request = None, project=Depends(get_project)):
    project_dir, _config, _state = project
    target = TargetArtifacts(project_dir)
    # Keep the typed error so the shared handler recognizes an expected
    # not-yet-generated artifact during stage loading/recovery.
    plan = target.read_plan()
    _sync_draw_progress(project_dir, request.app if request else None)
    hybrid = _hybrid_lettering(target)
    redraws = _redraws(project_dir, target)
    return {
        "redraws": [{"page_number": number, **reasons} for number, reasons in sorted(redraws.items())],
        # Draw waits until these reviews cover the saved script and plan again.
        "review_recheck": list(draw_review_recheck_phases(target)),
        "pages": [
            {
                "page": target.read_page(selected.page_number),
                "active_render": _latest_provenance(target, selected.page_number),
                "issues": _issues(target, selected.page_number),
                "correctable_issue_ids": _correctable_issue_ids(target, selected.page_number),
                "failure": _page_failure(target, selected.page_number),
                "analysis_recovery": _analysis_recovery(target, selected.page_number),
                "visual_reviewed": _visual_reviewed(target, selected.page_number),
                "lettering_mode": "hybrid" if hybrid else "baked",
                "lettering_revision": _lettering_revision(target, selected.page_number),
                "lettering_placement_review_needed": _lettering_placement_review_needed(
                    target, selected.page_number, hybrid
                ),
                "redraw": redraws.get(selected.page_number),
            }
            for selected in plan.pages
        ],
        "issue_summary": summarize_page_issues(target),
    }


@router.get("/pages/{page_number}")
def get_page(page_number: int, project=Depends(get_project)):
    project_dir, _config, _state = project
    target = TargetArtifacts(project_dir)
    try:
        page = target.read_page(page_number)
    except ArtifactMissing as exc:
        raise HTTPException(404, str(exc)) from exc
    revisions = target.provenance_revisions(page_number)
    return {
        "page": page,
        "active_render_revision": target.active_render_revision(page_number),
        "renders": [
            target.read_provenance(page_number, revision) for revision in revisions
        ],
        "analyses": [
            target.read_analysis(page_number, revision)
            for revision in revisions
            if target.analysis_path(page_number, revision).exists()
        ],
        "issues": _issues(target, page_number),
        "failure": _page_failure(target, page_number),
        "analysis_recovery": _analysis_recovery(target, page_number),
        "redraw": _page_redraw(project_dir, target, page_number),
    }


class PageRenderSelect(BaseModel):
    expected_revision: int = Field(ge=1)


@router.post("/pages/{page_number}/renders/{revision}/select", openapi_extra={'x-canary-action': {'spends': False, 'dispatches': False}})
def select_page_render(
    page_number: int, revision: int, body: PageRenderSelect, request: Request,
    project_id: str, project=Depends(get_project),
    user_id: str = Depends(get_current_user),
):
    """Choose saved artwork for reading, corrections and export; never generates."""
    from novel_to_comic.artifact_lock import production_lock

    project_dir, _config, _state = project
    pkey = project_key(user_id, project_id)
    with production_lock(project_dir):
        from ..admission import mutation_conflicts
        from novel_to_comic.workspace import part_id_for_path
        if mutation_conflicts(request.app, pkey, f"/pages/{page_number}/versions/{revision}/select", part_id_for_path(project_dir)):
            raise HTTPException(409, "Wait for the running stage before selecting a version.")
        jobs = generation_jobs_snapshot(request.app)
        decision, _ = _select_active_correction_job(
            jobs, pkey=pkey, page_number=page_number, request_sha256="",
        )
        if decision != "free":
            raise HTTPException(409, "Wait for this page's draw job before selecting a version.")
        target = TargetArtifacts(project_dir)
        try:
            if target.resumable_generation_request(page_number) is not None:
                raise HTTPException(409, "Recover the unfinished page generation before selecting a version.")
            target.select_render(page_number, revision, expected_revision=body.expected_revision)
        except ArtifactMissing as exc:
            raise HTTPException(404, str(exc)) from exc
        except (ArtifactInvalid, ValueError) as exc:
            raise HTTPException(409, str(exc)) from exc
    record_page_outcome(request.app, "render_selected", user_id=user_id, project_id=project_id,
                        target=target, page_number=page_number, render_revision=revision)
    return {"page_number": page_number, "active_render_revision": revision}


@router.get("/pages/{page_number}/source")
def read_page_source(page_number: int, project=Depends(get_project)):
    """Manuscript passages this page adapts; a provider-free artifact read."""
    project_dir, _config, _state = project
    try:
        return page_source_view(TargetArtifacts(project_dir), page_number)
    except ArtifactMissing as exc:
        raise HTTPException(404, str(exc)) from exc
    except ArtifactInvalid as exc:
        raise HTTPException(
            409, f"Saved story artifacts failed validation: {exc}. Re-run the owning stage and retry.",
        ) from exc
    except PageSourceStale as exc:
        raise HTTPException(409, str(exc)) from exc


@router.get("/pages/{page_number}/renders/{revision}")
def get_page_render(
    page_number: int,
    revision: int,
    project=Depends(get_project),
):
    project_dir, _config, _state = project
    path = TargetArtifacts(project_dir).render_path(page_number, revision)
    if not path.exists():
        raise HTTPException(404, "Page render not found")
    return FileResponse(
        path,
        media_type="image/png",
        # Restarting Adapt/Plan can reuse this page/revision URL for new art.
        # These URLs must revalidate; immutability applies only within an edition.
        headers={"Cache-Control": "private, no-cache"},
    )


def _render_correction_summary(
    target: TargetArtifacts, page_number: int, revision: int,
) -> dict:
    """Exact submitted correction behind one render, without prompt bulk.

    Resolves the frozen request that produced the render and projects only
    its correction block (edited instructions, annotation notes, manual
    note). Initial draws carry no correction and return null. Raises
    ArtifactMissing when the render or its frozen request record is absent.
    """
    provenance = target.read_provenance(page_number, revision)
    render = provenance.render
    frozen = None
    for request_revision in target.request_revisions(page_number):
        candidate = target.read_request(page_number, request_revision)
        if candidate.request_sha256 == render.request_sha256:
            frozen = candidate
            break
    if frozen is None:
        raise ArtifactMissing("page_request", target.request_path(page_number, revision))
    correction = frozen.correction
    return {
        "page_number": page_number,
        "render_revision": render.revision,
        "parent_render_revision": render.parent_revision,
        "request_sha256": render.request_sha256,
        "correction": (
            None
            if correction is None
            else {
                "mode": correction.mode,
                "changes": [
                    {
                        "id": change.id,
                        "issue_id": change.issue_id,
                        "instruction": change.instruction,
                        "annotations": [
                            annotation.model_dump(exclude_none=True)
                            for annotation in change.annotations
                        ],
                    }
                    for change in correction.changes
                ],
                "note": correction.note,
            }
        ),
    }


@router.get("/pages/{page_number}/renders/{revision}/correction")
def read_render_correction(
    page_number: int,
    revision: int,
    project=Depends(get_project),
):
    """Serve the exact submitted correction behind one render revision."""
    from novel_to_comic.target_artifacts import ArtifactInvalid

    target = TargetArtifacts(project[0])
    try:
        return _render_correction_summary(target, page_number, revision)
    except ArtifactMissing as exc:
        raise HTTPException(404, str(exc)) from exc
    except ArtifactInvalid as exc:
        raise HTTPException(
            409,
            f"Saved page artifacts failed validation and the correction history cannot be trusted: {exc}. "
            "Re-run the owning stage and retry.",
        ) from exc


@router.get("/pages/{page_number}/renders/{revision}/preview/{rendition}")
def get_page_render_preview(
    page_number: int,
    revision: int,
    rendition: Literal["thumbnail", "reader"],
    project=Depends(get_project),
):
    """Serve an immutable screen rendition without exposing the PNG master."""

    project_dir, _config, _state = project
    artifacts = TargetArtifacts(project_dir)
    try:
        path = ensure_page_render_preview(
            artifacts,
            page_number=page_number,
            render_revision=revision,
            rendition=rendition,
        )
    except FileNotFoundError as exc:
        raise HTTPException(404, "Page render not found") from exc
    except (OSError, ValueError) as exc:
        raise HTTPException(422, "Page preview could not be created") from exc
    return FileResponse(
        path,
        media_type="image/webp",
        headers={"Cache-Control": "private, no-cache"},
    )


@router.get("/pages/generate/estimate")
def estimate_remaining_page_generation(project=Depends(get_project), request: Request = None,
                                      project_id: str = "", user_id: str = Depends(get_current_user)):
    """Quote only undrawn pages, rounding each independent credit hold."""
    from novel_to_comic.page_drawing import estimate_draw_api_cost
    from ..credits import credit_estimate_for_provider_cost

    project_dir, _config, _state = project
    funding = classify_operations(draw_operations(_config))
    estimate = credit_estimate_for_provider_cost(0, "draw", reserve=True, funding=funding)
    try:
        _target, _adapter, prepared = prepare_undrawn_pages(
            project_dir=project_dir, config=_config,
        )
        for _page_number, _page, compiled in prepared:
            part = credit_estimate_for_provider_cost(
                estimate_draw_api_cost(_config, compiled), "draw", reserve=True,
                funding=funding,
            )
            estimate["estimate_credits"] += part["estimate_credits"]
            estimate["reserved_credits"] += part["reserved_credits"]
    except (ArtifactMissing, ValueError) as exc:
        raise HTTPException(409, str(exc)) from exc
    if request is not None:
        from ..cover_operations import needs_initial_project_cover, _project_cover_credit_estimate
        if needs_initial_project_cover(request, project_key(user_id, project_id), project_dir):
            cover = _project_cover_credit_estimate(_config)
            estimate["estimate_credits"] += cover["estimate_credits"]
            estimate["reserved_credits"] += cover["estimate_credits"]
    return dict(estimate)


def _latest_render_is_stale(target: TargetArtifacts, page_number: int, revision: int) -> bool:
    """A re-planned page: its newest art belongs to an earlier ComicPage.

    A correction edits art of the same page revision, so such a page is drawn
    fresh from its current plan instead; the old art stays in its history.
    """
    try:
        return target.read_provenance(page_number, revision).render.is_stale_for(target.read_page(page_number))
    except (ArtifactMissing, ArtifactInvalid):
        return False


def _prepare_initial_generation(
    project, page_number: int, depiction: Literal["canonical", "less_graphic"], *, persist: bool = True,
):
    project_dir, config, _state = project
    classify_operations(draw_operations(config))
    target = TargetArtifacts(project_dir)
    resumable = target.resumable_generation_request(page_number)
    revisions = target.provenance_revisions(page_number)
    if revisions and (resumable is None or resumable.correction is not None) and not _latest_render_is_stale(
        target, page_number, revisions[-1],
    ) and _page_redraw(project_dir, target, page_number) is None:
        raise HTTPException(
            409,
            "Page already has a render; create an issue and request a correction.",
        )
    try:
        require_draw_narrative_reviews(target)
        page = target.read_page(page_number)
        edition = ensure_current_page_edition(target, target.read_book_edition(), config, persist=persist)
        compiled = compile_page_generation_request(
            page,
            edition,
            approved_visual_inventory(project_dir),
            approved_reference_files(project_dir),
            retry=_generation_retry(target, page_number),
            depiction=depiction,
            style_template=config.style_template,
            style_reference_path=require_style_reference(project_dir, config.style_template),
        )
        complete_page_adapter(config, request=compiled.request).prepare(compiled)
    except (ArtifactMissing, ValueError) as exc:
        raise HTTPException(409, str(exc)) from exc
    return target, page, compiled


class PageRedrawBatch(BaseModel):
    # The pages the author saw and confirmed; a changed set is refused.
    pages: list[int] = Field(min_length=1)


def _prepared_redraws(project_dir, config, target: TargetArtifacts):
    redraws = _redraws(project_dir, target)
    if not redraws:
        raise HTTPException(409, "Every drawn page matches its current plan and references.")
    try:
        _target, adapter, prepared = prepare_undrawn_pages(
            project_dir=project_dir, config=config, pages=frozenset(redraws),
        )
    except (ArtifactMissing, ValueError) as exc:
        raise HTTPException(409, str(exc)) from exc
    return redraws, adapter, prepared


@router.get("/pages/redraws/estimate")
def estimate_page_redraws(project=Depends(get_project)):
    """Quote fresh drawings of every page whose plan or references changed."""
    from novel_to_comic.page_drawing import estimate_draw_api_cost
    from ..credits import credit_estimate_for_provider_cost

    project_dir, config, _state = project
    redraws, _adapter, prepared = _prepared_redraws(project_dir, config, TargetArtifacts(project_dir))
    funding = classify_operations(draw_operations(config))
    estimate = credit_estimate_for_provider_cost(0, "draw", reserve=True, funding=funding)
    for _page_number, _page, compiled in prepared:
        part = credit_estimate_for_provider_cost(
            estimate_draw_api_cost(config, compiled), "draw", reserve=True, funding=funding,
        )
        estimate["estimate_credits"] += part["estimate_credits"]
        estimate["reserved_credits"] += part["reserved_credits"]
    return {**estimate, "pages": sorted(redraws)}


@router.post("/pages/redraws", openapi_extra={'x-canary-action': {'spends': True, 'dispatches': True}})
async def redraw_out_of_date_pages(
    body: PageRedrawBatch,
    request: Request,
    project_id: str,
    project=Depends(get_project),
    user_id: str = Depends(get_current_user),
):
    """Draw every out-of-date page fresh from its current plan and references.

    Old art stays in each page's history; nothing else is redrawn.
    """
    project_dir, config, _state = project
    target = TargetArtifacts(project_dir)
    redraws = await asyncio.to_thread(_redraws, project_dir, target)
    if set(body.pages) != set(redraws):
        raise HTTPException(409, "The pages that need redrawing changed. Refresh the estimate and confirm again.")
    replaced = {number: target.active_render_revision(number) for number in redraws}
    try:
        jobs = await enqueue_all_undrawn_pages(
            request, project_id=project_id, user_id=user_id, project_dir=project_dir,
            config=config, pages=frozenset(redraws),
        )
    except (ArtifactMissing, ValueError) as exc:
        raise HTTPException(409, str(exc)) from exc
    for job, number in zip(jobs, sorted(redraws)):
        if replaced[number] is not None:
            record_page_outcome(request.app, "redraw_requested", user_id=user_id, project_id=project_id,
                                target=target, page_number=number, render_revision=replaced[number],
                                identity=job.id, mode="canonical")
    return {"status": "queued", "jobs": [
        {"page_number": number, "job": generation_job_payload(request.app, job)}
        for job, number in zip(jobs, sorted(redraws))
    ]}


@router.get("/pages/{page_number}/generate/estimate")
def estimate_page_generation(
    page_number: int,
    depiction: Literal["canonical", "less_graphic"] = "canonical",
    project=Depends(get_project),
):
    """Compile the same request as Draw without submitting or reserving credits."""
    _target, _page, compiled = _prepare_initial_generation(project, page_number, depiction, persist=False)
    return dict(correction_credit_estimate(compiled, config=project[1], reserve=True))


@router.get("/pages/{page_number}/analyze/estimate")
def estimate_page_analysis(page_number: int, project=Depends(get_project)):
    from novel_to_comic.config import PAGE_OCR_ESTIMATED_COST_USD
    from ..credits import credit_estimate_for_provider_cost

    target = TargetArtifacts(project[0])
    active = _latest_provenance(target, page_number)
    if active is None:
        raise HTTPException(409, "Page has no render to analyze")
    try:
        target.read_page(page_number)
        if not target.render_path(page_number, active.render.revision).is_file():
            raise HTTPException(409, "Page render is unavailable")
    except ArtifactMissing as exc:
        raise HTTPException(409, str(exc)) from exc
    requires_call = _analysis_recovery(target, page_number)["requires_paid_call"]
    funding = classify_operations(page_check_operations(project[1]) if requires_call else ())
    return dict(credit_estimate_for_provider_cost(
        float(PAGE_OCR_ESTIMATED_COST_USD) if requires_call else 0.0,
        "draw", reserve=True,
        funding=funding,
    ))


@router.post("/pages/{page_number}/generate", openapi_extra={'x-canary-action': {'spends': True, 'dispatches': True}})
async def generate_page(
    page_number: int,
    request: Request,
    project_id: str,
    generation: PageGenerationCreate | None = None,
    project=Depends(get_project),
    user_id: str = Depends(get_current_user),
):
    project_dir, config, _state = project
    target, page, compiled = _prepare_initial_generation(
        project,
        page_number,
        generation.depiction if generation is not None else "canonical",
    )
    adapter = complete_page_adapter(config, request=compiled.request)
    replaced_revision = target.active_render_revision(page_number)
    pkey = project_key(user_id, project_id)
    queue = request.app.state.event_queues.get(event_key(pkey, project_dir))
    if queue is not None:
        queue.put_nowait(
            {"type": "page_start", "stage": "draw", "page_number": page_number}
        )
    job, created = await enqueue_complete_page_draw(
        request.app,
        project_name=pkey,
        user_id=user_id,
        project_id=project_id,
        project_dir=project_dir,
        config=config,
        compiled=compiled,
        adapter=adapter,
        artifacts=target,
        page=page,
        ocr=page_read_adapter(config, target, page),
    )
    if created and replaced_revision is not None:
        record_page_outcome(request.app, "redraw_requested", user_id=user_id, project_id=project_id,
                            target=target, page_number=page_number, render_revision=replaced_revision,
                            identity=job.id, mode=generation.depiction if generation is not None else "canonical")
    return {"status": "queued", "job": generation_job_payload(request.app, job)}


class PageCheckRecovery(BaseModel):
    allow_paid: bool = False
    renders: dict[int, str] = Field(default_factory=dict)
    # A separately confirmed retry is a new action, not a replay of the
    # interrupted batch. Admission still deduplicates each individual attempt.
    recovery_attempt_id: str | None = Field(default=None, min_length=1, max_length=64)


@router.get("/pages/checks/estimate")
def estimate_missing_page_checks(project=Depends(get_project)):
    from ..credits import credit_estimate_for_provider_cost
    from novel_to_comic.config import PAGE_OCR_ESTIMATED_COST_USD
    target = TargetArtifacts(project[0])
    pages = [
        {"page_number": selected.page_number, **_analysis_recovery(target, selected.page_number),
         "render_image_sha256": (
             active.render.image_sha256
             if (active := _latest_provenance(target, selected.page_number)) else None
         )}
        for selected in target.read_plan().pages
    ]
    paid = sum(item["requires_paid_call"] for item in pages)
    funding = classify_operations(page_check_operations(project[1]) if paid else ())
    estimate = dict(credit_estimate_for_provider_cost(
        float(PAGE_OCR_ESTIMATED_COST_USD), "draw", reserve=True,
        funding=funding,
    ))
    for key in ("estimate_credits", "reserved_credits"):
        if estimate.get(key) is not None:
            estimate[key] *= paid
    return {**estimate, "pages": pages, "paid_pages": paid}


@router.post("/pages/checks/recover", openapi_extra={'x-canary-action': {'spends': True, 'dispatches': False, 'paid_body_field': 'allow_paid'}})
async def recover_missing_page_checks(
    project_id: str, body: PageCheckRecovery,
    project=Depends(get_project), user_id: str = Depends(get_current_user),
):
    target = TargetArtifacts(project[0])
    if body.allow_paid:
        for selected in target.read_plan().pages:
            active = _latest_provenance(target, selected.page_number)
            if (
                active is not None
                and body.renders.get(selected.page_number) == active.render.image_sha256
                and _analysis_recovery(target, selected.page_number)["requires_paid_call"]
            ):
                classify_operations(page_check_operations(project[1]))
                break
    results = []
    for selected in target.read_plan().pages:
        number = selected.page_number
        recovery = _analysis_recovery(target, number)
        if body.allow_paid:
            active = _latest_provenance(target, number)
            if active is None or body.renders.get(number) != active.render.image_sha256:
                results.append({"page_number": number, "status": "selection_changed"})
                continue
        if recovery["status"] in {"undrawn", "stale_render"}:
            results.append({"page_number": number, **recovery})
            continue
        if recovery["requires_paid_call"] and not body.allow_paid:
            results.append({"page_number": number, **recovery})
            continue
        try:
            await analyze_page(
                number, project_id, project, user_id, allow_paid=body.allow_paid,
                expected_image_sha256=body.renders.get(number) if body.allow_paid else None,
            )
            results.append({"page_number": number, **_analysis_recovery(target, number)})
        except Exception as exc:
            results.append({"page_number": number, "status": "failed",
                            "error": str(exc.detail if isinstance(exc, HTTPException) else exc)})
    return {"pages": results}


@router.post("/pages/{page_number}/analyze", openapi_extra={'x-canary-action': {'spends': True, 'dispatches': False}})
async def analyze_page(
    page_number: int,
    project_id: str,
    project=Depends(get_project),
    user_id: str = Depends(get_current_user),
    allow_paid: bool = True,
    expected_image_sha256: str | None = None,
    second_look_only: bool = False,
):
    """Read an existing render back without regenerating the page.

    Analysis runs automatically after every draw, but it is a second provider
    call that can fail on its own. Recovering must not cost another page: this
    re-reads the render already on disk. ``second_look_only`` retries just the
    Canary-funded close-up reads and refuses any work needing a primary read.
    """

    project_dir, config, _state = project
    target = TargetArtifacts(project_dir)
    active = _latest_provenance(target, page_number)
    if active is None:
        raise HTTPException(409, "Page has no render to analyze")
    try:
        page = target.read_page(page_number)
        image = target.read_render(page_number, active.render.revision)
    except ArtifactMissing as exc:
        raise HTTPException(409, str(exc)) from exc
    try:
        from ..credited_job import run_credited_page_check
        from novel_to_comic.config import PAGE_OCR_ESTIMATED_COST_USD
        from novel_to_comic import textract_ocr
        # Saved primary observations are immutable; without them, reserve the read.
        primary_needed = not target.raw_ocr_path(page_number, active.render.revision).is_file()
        if second_look_only and primary_needed:
            raise HTTPException(409, "This page needs a full text check before a second look")
        def cached_work():
            if hashlib.sha256(image).hexdigest() != active.render.image_sha256:
                raise HTTPException(409, "Saved artwork bytes do not match render lineage")
            if expected_image_sha256 is not None and active.render.image_sha256 != expected_image_sha256:
                raise HTTPException(409, "Approved artwork changed; reload the text-check estimate")
            latest = _latest_provenance(target, page_number)
            if latest is None or latest.render != active.render:
                raise HTTPException(409, "Active artwork changed; reload the text-check estimate")
            try:
                analysis = revalidate_cached_page_render(
                    page=page, render=active.render, artifacts=target,
                )
                if (allow_paid and textract_ocr.enabled() and analysis.crop_verification is not None
                        and not analysis.crop_verification.complete):
                    return None
            except ArtifactMissing as exc:
                if exc.name == "raw_ocr":
                    if not allow_paid:
                        raise HTTPException(409, "Text check requires an explicitly approved OCR-only call")
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
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    target.clear_page_failure(page_number)
    from novel_to_comic.page_drawing import reconcile_recovered_page_generation
    reconcile_recovered_page_generation(artifacts=target, render=active.render)
    return analysis


@router.post("/pages/{page_number}/issues", openapi_extra={'x-canary-action': {'spends': False, 'dispatches': False}})
def create_page_issue(
    page_number: int,
    body: PageIssueCreate,
    request: Request,
    project_id: str,
    project=Depends(get_project),
    user_id: str = Depends(get_current_user),
):
    project_dir, _config, _state = project
    target = TargetArtifacts(project_dir)
    active = _latest_provenance(target, page_number)
    if active is None:
        raise HTTPException(409, "Page has no render to review")
    try:
        issue = PageIssue.model_validate(
            {
                "id": f"page-issue-{uuid.uuid4().hex}",
                **body.model_dump(),
                "page_number": page_number,
                "render_revision": active.render.revision,
                "status": "open",
            }
        )
        recorded = record_page_issue(target, issue)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    record_page_outcome(request.app, "issue_reported", user_id=user_id, project_id=project_id,
                        target=target, page_number=page_number, render_revision=issue.render_revision,
                        identity=issue.id, category=issue.issue_type)
    return recorded


def _find_issue(target: TargetArtifacts, page_number: int, issue_id: str) -> PageIssue:
    issue = next(
        (item for item in _issues(target, page_number) if item.id == issue_id),
        None,
    )
    if issue is None:
        raise HTTPException(404, "Page issue not found")
    return issue


@router.post("/pages/{page_number}/issues/{issue_id}/accept", openapi_extra={'x-canary-action': {'spends': False, 'dispatches': False}})
def accept_page_issue(
    page_number: int,
    issue_id: str,
    request: Request,
    project_id: str,
    project=Depends(get_project),
    user_id: str = Depends(get_current_user),
):
    project_dir, _config, _state = project
    target = TargetArtifacts(project_dir)
    try:
        result = accept_editorial_page_issue(
            target,
            issue_id=issue_id,
            page_number=page_number,
        )
    except (ArtifactMissing, ValueError) as exc:
        raise HTTPException(409, str(exc)) from exc
    _record_issue_outcome(request, "issue_accepted", user_id=user_id, project_id=project_id,
                          target=target, page_number=page_number, issue_id=issue_id)
    return result


def _record_issue_outcome(request: Request, outcome: str, *, user_id: str, project_id: str,
                          target: TargetArtifacts, page_number: int, issue_id: str) -> None:
    issue = next((item for item in _issues(target, page_number) if item.id == issue_id), None)
    record_page_outcome(request.app, outcome, user_id=user_id, project_id=project_id, target=target,
                        page_number=page_number, identity=issue_id,
                        render_revision=issue.render_revision if issue else None,
                        category=issue.issue_type if issue else None)


@router.post("/pages/{page_number}/issues/{issue_id}/dismiss", openapi_extra={'x-canary-action': {'spends': False, 'dispatches': False}})
def dismiss_recorded_page_issue(
    page_number: int,
    issue_id: str,
    request: Request,
    project_id: str,
    project=Depends(get_project),
    user_id: str = Depends(get_current_user),
):
    project_dir, _config, _state = project
    try:
        result = dismiss_page_issue(
            TargetArtifacts(project_dir),
            issue_id=issue_id,
            page_number=page_number,
            reason=("Author withdrew this manual correction request; no visual fix is claimed."
                    if _find_issue(TargetArtifacts(project_dir), page_number, issue_id).issue_type == "manual_change"
                    else "Dismissed by the author as not a problem."),
        )
    except (ArtifactMissing, ValueError) as exc:
        raise HTTPException(409, str(exc)) from exc
    _record_issue_outcome(request, "issue_dismissed", user_id=user_id, project_id=project_id,
                          target=TargetArtifacts(project_dir), page_number=page_number, issue_id=issue_id)
    return result


class PageCorrectionCreate(BaseModel):
    """One explicit author-edited correction set for a single full-page job."""

    changes: tuple[CorrectionChange, ...] = Field(default=(), max_length=24)
    note: str = Field(default="", max_length=1000)
    context_source_unit_ids: tuple[str, ...] = ()
    parent_render_revision: int = Field(ge=1)
    comic_page_revision: int = Field(ge=1)


def _reference_entries(project_dir, references, style_template: str | None = None) -> list[dict]:
    """Reference display metadata with servable image paths, without spending.

    ``image_path`` is project-relative for the existing generic files route
    (``/api/projects/{project}/files/{image_path}``); it is null when the
    approved bytes are missing so the UI never renders a dead thumbnail.
    ``kind`` groups the display: the selected style proof, or the Story Bible
    entity type. The style proof's anchor is a provider instruction, not a
    description, so it is never shown. Accepts frozen-request dicts and
    compiled-request models alike.
    """
    from pathlib import Path as _Path

    from novel_to_comic.models.draw import STYLE_PROOF_REFERENCE_ID

    def _field(reference, name):
        if isinstance(reference, dict):
            return reference.get(name)
        return getattr(reference, name, None)

    try:
        files = approved_reference_files(project_dir)
    except Exception:
        files = {}
    # Cast references live in the series root, beside every part.
    from novel_to_comic.workspace import series_root

    root = series_root(_Path(project_dir)).resolve()

    def servable(path) -> str | None:
        try:
            candidate = _Path(path).resolve()
        except Exception:
            return None
        return candidate.relative_to(root).as_posix() if candidate.is_relative_to(root) and candidate.is_file() else None

    images: dict[str, str | None] = {reference_id: servable(source.path) for reference_id, source in files.items()}
    if style_template is not None:
        from novel_to_comic.style_reference import find_style_reference

        style_path = find_style_reference(_Path(project_dir), style_template)
        images[STYLE_PROOF_REFERENCE_ID] = servable(style_path) if style_path is not None else None
    from novel_to_comic import artifacts as project_artifacts

    bible = project_artifacts.read_story_bible_safe(project_dir)
    kinds = {} if bible is None else {
        **{item.id: "character" for item in bible.characters},
        **{item.id: "location" for item in bible.locations},
        **{item.id: "prop" for item in bible.props},
    }
    entries = []
    from novel_to_comic.reference_sheets import reference_display_members
    references = [member for reference in references for member in reference_display_members(reference)]
    for reference in references:
        reference_id = _field(reference, "id")
        label = _field(reference, "label") or ""
        entity = _field(reference, "entity_id") or ""
        style = reference_id == STYLE_PROOF_REFERENCE_ID
        entries.append(
            {
                "order": _field(reference, "order"),
                "id": reference_id,
                "entity_id": entity,
                "appearance_state_id": _field(reference, "appearance_state_id"),
                "kind": "style" if style else kinds.get(entity),
                "label": label,
                "display_label": "Selected style" if style else label or entity or reference_id,
                "visual_anchor": None if style else _field(reference, "visual_anchor"),
                "media_type": _field(reference, "media_type"),
                "image_path": images.get(reference_id) if reference_id else None,
            }
        )
    return entries
def _prepare_explicit_correction(
    *, target: TargetArtifacts, page_number: int, body: PageCorrectionCreate, config, persist: bool = True,
):
    """Run the shared no-spend validation+compile; maps failures to HTTP."""
    from novel_to_comic.page_review import (
        InvalidCorrectionError,
        StaleCorrectionError,
        deterministic_manual_issue_id,
    )
    from novel_to_comic.target_artifacts import ArtifactInvalid

    try:
        require_draw_narrative_reviews(target)
        page = target.read_page(page_number)
        edition = ensure_current_page_edition(target, target.read_book_edition(), config, persist=persist)
        provenance = _latest_provenance(target, page_number)
        resumable = target.resumable_generation_request(page_number)
        if (resumable is not None and resumable.correction is not None
                and resumable.correction.parent_render_revision == body.parent_render_revision):
            # Publication can have succeeded before OCR/settlement failed.
            # Recompile against the original correction parent, not the new
            # unpaid/unconfirmed publication, to preserve the frozen identity.
            provenance = target.read_provenance(page_number, body.parent_render_revision)
        if provenance is None:
            raise StaleCorrectionError("a rendered page is required before correcting findings")
        if body.parent_render_revision != provenance.render.revision:
            raise StaleCorrectionError(
                f"correction targets render {body.parent_render_revision}, "
                f"but current render is {provenance.render.revision}"
            )
        # The requested canonical revision plus the exact active parent
        # revision gate staleness here; the builder additionally verifies the
        # authoritative page SHA and the exact parent render bytes.
        if body.comic_page_revision != page.revision:
            raise StaleCorrectionError("correction targets a superseded ComicPage revision")
        # Retry lineage covers the full deterministic id set (linked issues
        # plus manual changes), so preview, submit, and retries share one
        # identity for one author selection.
        full_issue_ids = tuple(dict.fromkeys(
            change.issue_id
            if change.issue_id is not None
            else deterministic_manual_issue_id(
                page_number=page_number,
                parent_revision=provenance.render.revision,
                change_id=change.id,
            )
            for change in body.changes
        ))
        prepared = prepare_page_correction(
            page=page,
            edition=edition,
            inventory=approved_visual_inventory(target.project_dir),
            reference_files=approved_reference_files(target.project_dir),
            retry=_aggregated_correction_retry(
                target, page_number=page_number, issue_ids=full_issue_ids,
            ),
            parent=provenance.render,
            changes=tuple(body.changes),
            note=body.note,
            context_source_unit_ids=tuple(body.context_source_unit_ids),
            artifacts=target,
            style_template=config.style_template,
            style_reference_path=require_style_reference(target.project_dir, config.style_template),
        )
        complete_page_adapter(config, request=prepared.compiled.request).prepare(prepared.compiled)
        return prepared
    except StaleCorrectionError as exc:
        raise HTTPException(409, str(exc)) from exc
    except InvalidCorrectionError as exc:
        raise HTTPException(422, str(exc)) from exc
    except ArtifactInvalid as exc:
        raise HTTPException(
            409,
            f"Saved page artifacts failed validation and the correction cannot proceed: {exc}. "
            "Re-run the owning stage and retry.",
        ) from exc
    except ArtifactMissing as exc:
        raise HTTPException(409, str(exc)) from exc
    except ValueError as exc:
        message = str(exc)
        # Prompt/reference overflow is fixable client-side (select less);
        # missing bytes or edition conflicts behave like other 409s here.
        status = 422 if "exceed" in message else 409
        raise HTTPException(status, message) from exc


def _correction_preview_payload(*, target: TargetArtifacts, page_number: int, prepared, config) -> dict:
    correction = prepared.correction
    compiled = prepared.compiled
    context = prepared.context
    try:
        stored = target.read_issues(page_number)
    except ArtifactMissing:
        stored = ()
    stored_ids = {issue.id for issue in stored}
    selected = set(correction.issue_ids)
    unselected = sorted(
        issue.id for issue in stored
        if issue.status in {"open", "revised"} and issue.id not in selected
    )
    warnings = [
        "Canonical lettering is fixed to the approved script; wording changes need story edits, not image correction.",
    ]
    if unselected:
        warnings.append(
            f"{len(unselected)} open issue(s) were not selected and will remain after this revision."
        )
    if context.truncated:
        omitted = ", ".join(context.omitted_source_unit_ids) or "some passages"
        warnings.append(
            "Novel source passages were truncated to the correction context budget "
            f"(omitted: {omitted}). Selected changes, notes, annotations, and "
            "explicitly selected passages are never truncated."
        )
    if correction.mode == "region_targeted":
        warnings.append(
            "Region-targeted edit anchored to detected render geometry; unaffected areas stay fixed."
        )
    pending_manual = [
        change.id for change in correction.changes
        if change.issue_id is not None and change.issue_id not in stored_ids
    ]
    if pending_manual:
        warnings.append(
            "Manual changes are recorded as tracked issues only when the correction is submitted; "
            "previewing never alters the issue history."
        )
    if not correction.issue_ids and not pending_manual:
        warnings.append(
            "Note-only correction: no tracked issue will be resolved by this revision."
        )
    return {
        "page_number": page_number,
        "parent_render_revision": correction.parent_render_revision,
        "comic_page_revision": correction.comic_page_revision,
        "selected_issue_ids": list(correction.issue_ids),
        "unselected_open_issue_ids": unselected,
        "changes": [
            {
                "id": change.id,
                "issue_id": change.issue_id,
                "instruction": change.instruction,
                "annotations": [
                    annotation.model_dump(exclude_none=True)
                    for annotation in change.annotations
                ],
            }
            for change in correction.changes
        ],
        "pending_manual_change_ids": pending_manual,
        "note": correction.note,
        "mode": correction.mode,
        "instruction": correction.instruction,
        "context": {
            "adaptation_revision": context.adaptation_revision,
            "adaptation_sha256": context.adaptation_sha256,
            "treatment_spine": list(context.treatment_spine),
            "beat_ids": list(context.beat_ids),
            "beat_count": len(context.beat_ids),
            "appearance_chronology": list(context.appearance_chronology),
            "continuity": list(context.beat_transitions),
            "source_unit_ids": list(context.source_unit_ids),
            "selected_source_unit_ids": list(context.selected_source_unit_ids),
            "omitted_source_unit_ids": list(context.omitted_source_unit_ids),
            "context_digest": context.digest,
            "truncated": context.truncated,
        },
        "references": _reference_entries(target.project_dir, compiled.request.references, config.style_template),
        "profile": {
            "id": compiled.request.profile_id,
            "provider": compiled.request.provider,
            "model": compiled.request.model,
        },
        "lettering_count": len(compiled.request.lettering),
        "prompt_characters": len(compiled.request.prompt),
        "request_sha256": compiled.request.request_sha256,
        "warnings": warnings,
        "estimate": dict(correction_credit_estimate(compiled, config=config, reserve=True)),
    }
@router.post("/pages/{page_number}/corrections/preview", openapi_extra={'x-canary-action': {'spends': False, 'dispatches': False}})
def preview_page_correction(
    page_number: int,
    body: PageCorrectionCreate,
    project=Depends(get_project),
):
    """Validate, compile, and estimate one correction set without spending."""
    project_dir, config, _state = project
    classify_operations(draw_operations(config))
    target = TargetArtifacts(project_dir)
    prepared = _prepare_explicit_correction(
        target=target, page_number=page_number, body=body, config=config, persist=False,
    )
    return _correction_preview_payload(target=target, page_number=page_number, prepared=prepared, config=config)


@router.post("/pages/{page_number}/corrections", openapi_extra={'x-canary-action': {'spends': True, 'dispatches': True}})
async def submit_page_correction(
    page_number: int,
    body: PageCorrectionCreate,
    request: Request,
    project_id: str,
    project=Depends(get_project),
    user_id: str = Depends(get_current_user),
):
    """Enqueue one full-page job for the edited changes and author note."""
    project_dir, config, _state = project
    classify_operations(draw_operations(config))
    target = TargetArtifacts(project_dir)
    prepared = _prepare_explicit_correction(
        target=target, page_number=page_number, body=body, config=config,
    )
    correction = prepared.correction
    compiled = prepared.compiled
    pkey = project_key(user_id, project_id)
    decision, active_job = _select_active_correction_job(
        generation_jobs_snapshot(request.app),
        pkey=pkey,
        page_number=page_number,
        request_sha256=compiled.request.request_sha256,
    )
    if decision == "share":
        return {
            "status": "queued",
            "job": generation_job_payload(request.app, active_job),
            "selected_issue_ids": list(correction.issue_ids),
        }
    if decision == "busy":
        raise HTTPException(
            409,
            f"Page {page_number} has an active draw job; wait for it to finish "
            "before submitting changed instructions.",
        )
    # Manual issues do not exist until the reserved job creates them; linked
    # issues were validated above, so only a missing (manual) first issue is
    # tolerated here.
    primary_issue: PageIssue | None = None
    if correction.issue_ids:
        try:
            primary_issue = _find_issue(target, page_number, correction.issue_ids[0])
        except HTTPException as exc:
            if exc.status_code != 404:
                raise
            primary_issue = None
    adapter = complete_page_adapter(config, request=compiled.request)
    queue = request.app.state.event_queues.get(event_key(pkey, project_dir))
    if queue is not None:
        queue.put_nowait(
            {"type": "page_start", "stage": "draw", "page_number": page_number}
        )
    job, created = await enqueue_complete_page_draw(
        request.app,
        project_name=pkey,
        user_id=user_id,
        project_id=project_id,
        project_dir=project_dir,
        config=config,
        compiled=compiled,
        adapter=adapter,
        artifacts=target,
        page=(page := target.read_page(page_number)),
        ocr=page_read_adapter(config, target, page),
        parent_render_revision=correction.parent_render_revision,
        issue=primary_issue,
    )
    if created:
        record_page_outcome(request.app, "correction_submitted", user_id=user_id, project_id=project_id,
                            target=target, page_number=page_number,
                            render_revision=correction.parent_render_revision, identity=job.id,
                            category=primary_issue.issue_type if primary_issue else "manual",
                            mode=correction.mode)
    return {
        "status": "queued",
        "job": generation_job_payload(request.app, job),
        "selected_issue_ids": list(correction.issue_ids),
    }


@router.get("/pages/{page_number}/visual-review/estimate")
def visual_review_estimate(page_number: int, project=Depends(get_project)):
    from novel_to_comic.config import PAGE_VISUAL_REVIEW_ESTIMATED_COST_USD
    from novel_to_comic.page_visual_review import compile_visual_review
    from ..credits import credit_estimate_for_provider_cost
    project_dir, config, _state = project
    target = TargetArtifacts(project_dir)
    if _latest_provenance(target, page_number) is None:
        raise HTTPException(409, "Page has no render to review")
    try:
        compile_visual_review(project_dir, config, target, target.read_page(page_number))
    except (ArtifactMissing, ValueError) as exc:
        raise HTTPException(409, str(exc)) from exc
    return credit_estimate_for_provider_cost(
        float(PAGE_VISUAL_REVIEW_ESTIMATED_COST_USD), 'draw', reserve=True,
        funding=classify_operations(page_check_operations(project[1])),
    )

@router.post("/pages/{page_number}/visual-review", openapi_extra={'x-canary-action': {'spends': True, 'dispatches': False}})
async def visual_review_page(page_number: int, project_id: str, request: Request,
                             project=Depends(get_project), user_id: str = Depends(get_current_user)):
    from ..credited_job import run_credited_page_check
    from novel_to_comic.page_visual_review import compile_visual_review, review_page_visuals
    from novel_to_comic.config import PAGE_VISUAL_REVIEW_ESTIMATED_COST_USD
    from novel_to_comic.target_artifacts import ArtifactInvalid

    project_dir, config, _state = project
    target = TargetArtifacts(project_dir)
    active = _latest_provenance(target, page_number)
    if active is None:
        raise HTTPException(409, "Page has no render to review")
    record_page_outcome(request.app, "visual_review_requested", user_id=user_id, project_id=project_id,
                        target=target, page_number=page_number, render_revision=active.render.revision)
    try:
        page = target.read_page(page_number)
        compiled = compile_visual_review(project_dir, config, target, page)
        result = await run_credited_page_check(
            user_id=user_id, project_id=project_id, project_dir=project_dir, page_number=page_number,
            estimated_cost_usd=float(PAGE_VISUAL_REVIEW_ESTIMATED_COST_USD),
            operations=visual_review_operations(config),
            work=lambda: review_page_visuals(config=config, page=page, render=active.render,
                image=target.read_render(page_number, active.render.revision), compiled=compiled, artifacts=target,
                producing_request=target.producing_request(active.render)),
        )
        return result.value
    except ArtifactInvalid as exc:
        raise HTTPException(
            409,
            f"Saved page artifacts failed validation and the visual review cannot proceed: {exc}. "
            "Re-run the owning stage and retry.",
        ) from exc
    except (ArtifactMissing, ValueError) as exc:
        raise HTTPException(409, str(exc)) from exc

@router.get("/pages/{page_number}/visual-review")
def read_saved_visual_review(page_number: int, project=Depends(get_project)):
    """Return the saved visual report only when it matches the current inputs.

    Generation stays behind the explicit POST route; this read never places a
    credit hold or calls a provider. The digest is recomputed from the live
    canonical page, exact render bytes, approved references, and review model,
    so a stale file is never served as current: the report is null until a
    matching paid review lands. References (with servable image paths) are
    returned regardless so the panel can render thumbnails immediately. Each
    finding links to its persisted issue; unavailable links must not seed a
    draft.
    """
    from novel_to_comic.page_visual_review import (
        compile_visual_review,
        finding_issue_links,
        reference_display_for_render,
        validated_saved_visual_review,
    )

    project_dir, config, _state = project
    target = TargetArtifacts(project_dir)
    try:
        active = _latest_provenance(target, page_number)
        if active is None:
            raise HTTPException(409, "Page has no render to review")
        page = target.read_page(page_number)
        image = target.read_render(page_number, active.render.revision)
        compiled = compile_visual_review(project_dir, config, target, page)
        try:
            report = validated_saved_visual_review(
                page=page, render=active.render, image=image, compiled=compiled,
                config=config, artifacts=target,
                producing_request=target.producing_request(active.render),
            )
        except ValueError:
            # Inputs no longer reproduce any saved digest: nothing is current.
            report = None
    except HTTPException:
        raise
    except ArtifactInvalid as exc:
        raise HTTPException(
            409,
            f"Saved page artifacts failed validation and the saved review cannot be trusted: {exc}. "
            "Re-run the owning stage and retry.",
        ) from exc
    except (ArtifactMissing, ValueError) as exc:
        raise HTTPException(409, str(exc)) from exc
    try:
        stored = target.read_issues(page_number)
    except (ArtifactMissing, ArtifactInvalid):
        stored = ()
    return {
        "cached": True,
        "page_number": page_number,
        "render_revision": active.render.revision,
        "render_image_sha256": active.render.image_sha256,
        "report": report,
        "finding_issues": list(finding_issue_links(report, stored)) if report is not None else [],
        "references": _reference_entries(
            project_dir, reference_display_for_render(target, page_number, active.render), config.style_template,
        ),
    }


def _replan_operations(config):
    return (("text", config.effective_plan_model()),)


def _replan_cost(target: TargetArtifacts, project_dir, config, page_number: int) -> float:
    from novel_to_comic.page_planning import estimate_page_replan_cost

    return estimate_page_replan_cost(
        target, approved_visual_inventory(project_dir), page_number, model=config.effective_plan_model(),
    )


@router.get("/pages/{page_number}/replan/estimate")
def replan_page_estimate(page_number: int, project=Depends(get_project)):
    """Price one page's plan repair; 409 when its plan has nothing to repair."""
    from ..credits import credit_estimate_for_provider_cost

    project_dir, config, _state = project
    try:
        cost = _replan_cost(TargetArtifacts(project_dir), project_dir, config, page_number)
    except (ArtifactMissing, ArtifactInvalid, ValueError) as exc:
        raise HTTPException(409, str(exc)) from exc
    return credit_estimate_for_provider_cost(
        cost, "plan", reserve=True, funding=classify_operations(_replan_operations(config)),
    )


@router.post("/pages/{page_number}/replan", openapi_extra={'x-canary-action': {'spends': True, 'dispatches': False}})
async def replan_one_page(page_number: int, project_id: str, request: Request,
                          project=Depends(get_project), user_id: str = Depends(get_current_user)):
    """Rewrite one page's plan to clear its validation failures.

    The page keeps its beats and lettering; its current artwork becomes stale
    and is redrawn separately from Pages.
    """
    from ..credited_job import run_credited_page_check
    from novel_to_comic.clients.text import generate_json
    from novel_to_comic.generation_checkpoints import checkpointed_generator
    from novel_to_comic.page_planning import PlanInvariantError, replan_page

    project_dir, config, _state = project
    target = TargetArtifacts(project_dir)
    model = config.effective_plan_model()
    record_page_outcome(request.app, "replan_requested", user_id=user_id, project_id=project_id,
                        target=target, page_number=page_number)

    async def generate(**kwargs):
        return await generate_json(config=config, model=model, temperature=0.25, **kwargs)

    try:
        cost = _replan_cost(target, project_dir, config, page_number)
        revised = await run_credited_page_check(
            user_id=user_id, project_id=project_id, project_dir=project_dir, page_number=page_number,
            estimated_cost_usd=cost, operations=_replan_operations(config),
            work=lambda: replan_page(
                target, approved_visual_inventory(project_dir), page_number,
                generate=checkpointed_generator(generate, artifacts=target, stage="plan", model=model),
                model=model,
            ),
        )
    except PlanInvariantError as exc:
        raise HTTPException(409, {
            "code": "page_replan_rejected",
            "message": "The revised page plan still has problems; the current plan is unchanged.",
            "failures": [failure.message for failure in exc.validation.invariant_failures],
        }) from exc
    except (ArtifactMissing, ArtifactInvalid, ValueError) as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"page_number": page_number, "revision": revised.revision}


def _review_recheck_reviewers(config):
    """Each review runs with its owning stage's model, temperature and concurrency."""
    from novel_to_comic.clients.text import generate_json

    def reviewer(model: str, temperature: float, concurrency: int):
        async def generate(**kwargs):
            return await generate_json(config=config, model=model, temperature=temperature, **kwargs)
        return generate, model, concurrency

    return {
        "adapt": reviewer(config.effective_adapt_model(), 0.6, config.effective_text_concurrency("adapt")),
        "plan": reviewer(config.effective_plan_model(), 0.25, config.effective_text_concurrency()),
    }


def _review_recheck_operations(config):
    return (("text", config.effective_adapt_model()), ("text", config.effective_plan_model()))


@router.get("/pages/review-recheck/estimate")
def review_recheck_estimate(project=Depends(get_project)):
    """Price a fresh review of the saved script and plan; 409 when both are current."""
    from novel_to_comic.narrative_review import draw_review_recheck_phases, estimate_draw_review_recheck
    from ..credits import credit_estimate_for_provider_cost

    project_dir, config, _state = project
    target = TargetArtifacts(project_dir)
    phases = draw_review_recheck_phases(target)
    if not phases:
        raise HTTPException(409, "The script and plan reviews already cover the saved work.")
    cost = estimate_draw_review_recheck(
        target, {"adapt": config.effective_adapt_model(), "plan": config.effective_plan_model()},
    )
    return {
        **credit_estimate_for_provider_cost(
            cost, "plan", reserve=True, funding=classify_operations(_review_recheck_operations(config)),
        ),
        "phases": list(phases),
    }


@router.post("/pages/review-recheck", openapi_extra={'x-canary-action': {'spends': True, 'dispatches': False}})
async def recheck_reviews(project_id: str, project=Depends(get_project),
                          user_id: str = Depends(get_current_user)):
    """Review the saved script and plan again so drawing can continue.

    Neither is rewritten. Reviews written under an earlier review contract
    otherwise leave a project with drawn pages no way back to drawing.
    """
    from ..credited_job import run_credited_call
    from novel_to_comic.narrative_review import estimate_draw_review_recheck, recheck_draw_reviews

    project_dir, config, _state = project
    target = TargetArtifacts(project_dir)
    try:
        cost = estimate_draw_review_recheck(
            target, {"adapt": config.effective_adapt_model(), "plan": config.effective_plan_model()},
        )
        failures = await run_credited_call(
            user_id=user_id, project_id=project_id, project_dir=project_dir, stage="plan",
            estimated_cost_usd=cost, operations=_review_recheck_operations(config),
            work=lambda: recheck_draw_reviews(target, reviewers=_review_recheck_reviewers(config)),
        )
    except (ArtifactMissing, ArtifactInvalid, ValueError) as exc:
        raise HTTPException(409, str(exc)) from exc
    if failures:
        # A finding's first evidence line names the problem; its message is generic.
        found = " ".join(dict.fromkeys(
            failure.evidence[0] if failure.evidence and failure.code != "narrative_review_invalid" else failure.message
            for failure in failures[:3]
        ))
        raise HTTPException(409, {
            "code": "review_recheck_failed",
            "message": f"The review found a problem, so drawing stays paused. {found}",
        })
    return {"status": "current"}


# Independent presentation endpoints, not a ninth pipeline stage.
from .lettering import router as lettering_router  # noqa: E402
router.include_router(lettering_router)
