"""Complete-page Draw and review-by-exception routes."""

from __future__ import annotations

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
    current_page_capability_profile,
    select_book_edition,
    analyze_complete_page,
    compile_page_generation_request,
    correction_credit_estimate,
    ensure_current_page_edition,
    enqueue_complete_page_draw,
    prepare_page_correction,
)
from novel_to_comic.page_previews import ensure_page_render_preview
from novel_to_comic.page_ocr import GatewayPageOCRAdapter
from novel_to_comic.page_review import (
    accept_editorial_page_issue,
    dismiss_page_issue,
    record_page_issue,
    summarize_page_issues,
    revalidate_cached_page_render,
    DRAW_VALIDATOR_VERSION,
)
from novel_to_comic.stages.s5_plan import (
    approved_reference_files,
    approved_visual_inventory,
)
from novel_to_comic.state import StageStatus, complete_stage, load_state, save_state
from novel_to_comic.target_artifacts import ArtifactInvalid, ArtifactMissing, TargetArtifacts

from ..auth import get_current_user
from novel_to_comic.codex_dev import classify_operations
from ..codex_admission import draw_operations, page_check_operations
from ..deps import get_project, get_project_dir, project_key
from ..generation_jobs import generation_job_payload


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


def _latest_provenance(target: TargetArtifacts, page_number: int):
    revisions = target.provenance_revisions(page_number)
    if not revisions:
        return None
    return target.read_provenance(page_number, revisions[-1])


def _issues(target: TargetArtifacts, page_number: int):
    try:
        return target.read_issues(page_number)
    except ArtifactMissing:
        return ()


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
                and analysis.validator_version == DRAW_VALIDATOR_VERSION):
            return {"status": "checked", "requires_paid_call": False}
    except (ArtifactMissing, ArtifactInvalid):
        pass
    cached = any(path.exists() for path in (
        target.raw_ocr_path(page_number, render.revision),
        target.ocr_response_path(page_number, render.revision),
        target.analysis_path(page_number, render.revision),
    ))
    return {"status": "cached_evidence" if cached else "requires_ocr",
            "requires_paid_call": not cached}


def _producing_request(target: TargetArtifacts, render):
    for revision in reversed(target.request_revisions(render.page_number)):
        request = target.read_request(render.page_number, revision)
        if request.request_sha256 == render.request_sha256:
            return request
    raise ValueError("Saved render lacks its producing request")


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


def _generation_retry(target: TargetArtifacts, page_number: int) -> RetryProvenance:
    """Resume an incomplete durable paid result before allocating a retry."""
    resumable = target.resumable_generation_request(page_number)
    if resumable is not None and resumable.correction is None:
        return resumable.retry

    prior_requests = [
        target.read_request(page_number, revision)
        for revision in target.request_revisions(page_number)
    ]
    prior_attempts = [request for request in prior_requests if request.correction is None]
    if not prior_attempts:
        return RetryProvenance(attempt=1)
    prior = max(prior_attempts, key=lambda request: request.retry.attempt)
    return RetryProvenance(
        attempt=prior.retry.attempt + 1,
        retries_request_sha256=prior.request_sha256,
    )


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


def _sync_draw_progress(project_dir) -> None:
    """Reconcile Draw's stage state with the renders actually on disk.

    Progress is recomputed from artifacts rather than incremented, so a state
    write that loses a race with a concurrent job is corrected by the next call
    instead of leaving Draw stuck in RUNNING with every page already drawn.
    """

    target = TargetArtifacts(project_dir)
    try:
        plan = target.read_plan()
    except ArtifactMissing:
        return
    state = load_state(project_dir)
    draw_state = state.stages["draw"]
    rendered = sum(
        bool(target.provenance_revisions(page.page_number)) for page in plan.pages
    )
    if draw_state.items_done == rendered and (
        rendered < len(plan.pages) or draw_state.status != StageStatus.RUNNING
    ):
        return
    draw_state.items_done = rendered
    if rendered == len(plan.pages) and draw_state.status == StageStatus.RUNNING:
        complete_stage(state, "draw")
    save_state(state, project_dir)


def _draw_success_callback(
    request: Request,
    *,
    pkey: str,
    project_dir,
):
    def callback(provenance) -> None:
        _sync_draw_progress(project_dir)
        queue = request.app.state.event_queues.get(pkey)
        if queue is not None:
            queue.put_nowait(
                {
                    "type": "page_done",
                    "stage": "draw",
                    "page_number": provenance.render.page_number,
                    "revision": provenance.render.revision,
                    "status": "ok",
                    "duration_ms": provenance.render.latency_ms,
                    "error": None,
                }
            )

    return callback




def prepare_undrawn_pages(*, project_dir, config, rerun: bool = False):
    """Preflight every selected page without writing an edition or placing holds."""
    classify_operations(draw_operations(config))
    target = TargetArtifacts(project_dir)
    edition = (
        ensure_current_page_edition(target, target.read_book_edition())
        if target.book_edition_path.exists()
        else select_book_edition(
            edition_id="book-edition-001", profile=current_page_capability_profile(),
        )
    )
    inventory = approved_visual_inventory(project_dir)
    reference_files = approved_reference_files(project_dir)
    adapter = complete_page_adapter(config)
    prepared = []
    for selected in target.read_plan().pages:
        page_number = selected.page_number
        if target.provenance_revisions(page_number) and not rerun:
            continue
        page = target.read_page(page_number)
        compiled = compile_page_generation_request(
            page, edition, inventory, reference_files,
            retry=_generation_retry(target, page_number),
            style_template=config.style_template,
        )
        adapter.prepare(compiled)
        prepared.append((page_number, page, compiled))
    return target, adapter, prepared


def enqueue_all_undrawn_pages(
    request: Request,
    *,
    project_id: str,
    user_id: str,
    project_dir,
    config,
    rerun: bool = False,
):
    """Queue missing pages, or explicit replacement revisions without deletion."""
    target, adapter, prepared = prepare_undrawn_pages(
        project_dir=project_dir, config=config, rerun=rerun,
    )
    # Estimation can select an ephemeral first edition; submission requires
    # Draw initialization to have durably pinned it first.
    ensure_current_page_edition(target, target.read_book_edition())
    # No reservation or publication occurs until the entire batch is prepared.
    pkey = project_key(user_id, project_id)
    queue = request.app.state.event_queues.get(pkey)
    jobs = []

    for page_number, page, compiled in prepared:
        if queue is not None:
            queue.put_nowait(
                {"type": "page_start", "stage": "draw", "page_number": page_number}
            )
        job, _created = enqueue_complete_page_draw(
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
            ocr=GatewayPageOCRAdapter(config, page_number=page_number),
            on_success=_draw_success_callback(
                request,
                pkey=pkey,
                project_dir=project_dir,
            ),
        )
        jobs.append(job)

    return tuple(jobs)


@router.get("/pages")
def list_pages(project=Depends(get_project)):
    project_dir, _config, _state = project
    target = TargetArtifacts(project_dir)
    try:
        plan = target.read_plan()
    except ArtifactMissing as exc:
        raise HTTPException(404, str(exc)) from exc
    _sync_draw_progress(project_dir)
    return {
        "pages": [
            {
                "page": target.read_page(selected.page_number),
                "active_render": _latest_provenance(target, selected.page_number),
                "issues": _issues(target, selected.page_number),
                "failure": _page_failure(target, selected.page_number),
                "analysis_recovery": _analysis_recovery(target, selected.page_number),
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
    }


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
        # A render revision is immutable — a correction writes a new revision
        # rather than overwriting this file. Caching it hard is what lets the
        # book reader page through a whole book with no network at all, off
        # the bytes the Panels grid already fetched. Private: project renders
        # are per-user and must not land in a shared proxy cache.
        headers={"Cache-Control": "private, max-age=31536000, immutable"},
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
        headers={"Cache-Control": "private, max-age=31536000, immutable"},
    )


@router.get("/pages/generate/estimate")
def estimate_remaining_page_generation(project=Depends(get_project)):
    """Quote only undrawn pages, rounding each independent credit hold."""
    from novel_to_comic.config import PAGE_OCR_ESTIMATED_COST_USD
    from ..credits import credit_estimate_for_provider_cost

    project_dir, _config, _state = project
    funding = classify_operations(draw_operations(_config))
    estimate = credit_estimate_for_provider_cost(0, "draw", reserve=True, funding=funding)
    try:
        _target, _adapter, prepared = prepare_undrawn_pages(
            project_dir=project_dir, config=_config,
        )
        for _page_number, _page, compiled in prepared:
            page_cost = float(compiled.request.estimated_cost_usd)
            part = credit_estimate_for_provider_cost(
                page_cost + float(PAGE_OCR_ESTIMATED_COST_USD), "draw", reserve=True,
                funding=funding,
            )
            estimate["estimate_credits"] += part["estimate_credits"]
            estimate["reserved_credits"] += part["reserved_credits"]
    except (ArtifactMissing, ValueError) as exc:
        raise HTTPException(409, str(exc)) from exc
    return dict(estimate)


def _prepare_initial_generation(
    project, page_number: int, depiction: Literal["canonical", "less_graphic"],
):
    project_dir, config, _state = project
    classify_operations(draw_operations(config))
    target = TargetArtifacts(project_dir)
    resumable = target.resumable_generation_request(page_number)
    if target.provenance_revisions(page_number) and (
        resumable is None or resumable.correction is not None
    ):
        raise HTTPException(
            409,
            "Page already has a render; create an issue and request a correction.",
        )
    try:
        page = target.read_page(page_number)
        edition = ensure_current_page_edition(target, target.read_book_edition())
        compiled = compile_page_generation_request(
            page,
            edition,
            approved_visual_inventory(project_dir),
            approved_reference_files(project_dir),
            retry=_generation_retry(target, page_number),
            depiction=depiction,
            style_template=config.style_template,
        )
        complete_page_adapter(config).prepare(compiled)
    except (ArtifactMissing, ValueError) as exc:
        raise HTTPException(409, str(exc)) from exc
    return target, page, compiled


@router.get("/pages/{page_number}/generate/estimate")
def estimate_page_generation(
    page_number: int,
    depiction: Literal["canonical", "less_graphic"] = "canonical",
    project=Depends(get_project),
):
    """Compile the same request as Draw without submitting or reserving credits."""
    _target, _page, compiled = _prepare_initial_generation(project, page_number, depiction)
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


@router.post("/pages/{page_number}/generate")
def generate_page(
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
    adapter = complete_page_adapter(config)
    pkey = project_key(user_id, project_id)
    queue = request.app.state.event_queues.get(pkey)
    if queue is not None:
        queue.put_nowait(
            {"type": "page_start", "stage": "draw", "page_number": page_number}
        )
    job, _created = enqueue_complete_page_draw(
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
        ocr=GatewayPageOCRAdapter(config, page_number=page_number),
        on_success=_draw_success_callback(
            request,
            pkey=pkey,
            project_dir=project_dir,
        ),
    )
    return {"status": "queued", "job": generation_job_payload(request.app, job)}


class PageCheckRecovery(BaseModel):
    allow_paid: bool = False
    renders: dict[int, str] = Field(default_factory=dict)


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


@router.post("/pages/checks/recover")
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
            results.append({"page_number": number, "status": "checked"})
        except Exception as exc:
            results.append({"page_number": number, "status": "failed",
                            "error": str(exc.detail if isinstance(exc, HTTPException) else exc)})
    return {"pages": results}


@router.post("/pages/{page_number}/analyze")
async def analyze_page(
    page_number: int,
    project_id: str,
    project=Depends(get_project),
    user_id: str = Depends(get_current_user),
    allow_paid: bool = True,
    expected_image_sha256: str | None = None,
):
    """Read an existing render back without regenerating the page.

    Analysis runs automatically after every draw, but it is a second provider
    call that can fail on its own. Recovering must not cost another page: this
    re-reads the render already on disk.
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
            except ArtifactMissing as exc:
                if exc.name == "raw_ocr":
                    if not allow_paid:
                        raise HTTPException(409, "Text check requires an explicitly approved OCR-only call")
                    return None
                raise
            return analysis
        analysis = await run_credited_page_check(
            user_id=user_id, project_id=project_id, project_dir=project_dir,
            page_number=page_number, estimated_cost_usd=float(PAGE_OCR_ESTIMATED_COST_USD),
            cached_work=cached_work,
            operations=page_check_operations(config),
            work=lambda: analyze_complete_page(
                page=page, render=active.render, image=image,
                ocr=GatewayPageOCRAdapter(config, page_number=page_number), artifacts=target,
            ),
        )
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    target.clear_page_failure(page_number)
    from novel_to_comic.page_drawing import reconcile_recovered_page_generation
    reconcile_recovered_page_generation(artifacts=target, render=active.render)
    return analysis


@router.post("/pages/{page_number}/issues")
def create_page_issue(
    page_number: int,
    body: PageIssueCreate,
    project=Depends(get_project),
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
        return record_page_issue(target, issue)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


def _find_issue(target: TargetArtifacts, page_number: int, issue_id: str) -> PageIssue:
    issue = next(
        (item for item in _issues(target, page_number) if item.id == issue_id),
        None,
    )
    if issue is None:
        raise HTTPException(404, "Page issue not found")
    return issue


@router.post("/pages/{page_number}/issues/{issue_id}/accept")
def accept_page_issue(
    page_number: int,
    issue_id: str,
    project=Depends(get_project),
):
    project_dir, _config, _state = project
    try:
        return accept_editorial_page_issue(
            TargetArtifacts(project_dir),
            issue_id=issue_id,
            page_number=page_number,
        )
    except (ArtifactMissing, ValueError) as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post("/pages/{page_number}/issues/{issue_id}/dismiss")
def dismiss_automated_page_issue(
    page_number: int,
    issue_id: str,
    project=Depends(get_project),
):
    project_dir, _config, _state = project
    try:
        return dismiss_page_issue(
            TargetArtifacts(project_dir),
            issue_id=issue_id,
            page_number=page_number,
            reason="Dismissed after visual review as a validator false positive.",
        )
    except (ArtifactMissing, ValueError) as exc:
        raise HTTPException(409, str(exc)) from exc


class PageCorrectionCreate(BaseModel):
    """One explicit author-edited correction set for a single full-page job."""

    changes: tuple[CorrectionChange, ...] = Field(default=(), max_length=24)
    note: str = Field(default="", max_length=1000)
    context_source_unit_ids: tuple[str, ...] = ()
    parent_render_revision: int = Field(ge=1)
    comic_page_revision: int = Field(ge=1)


def _reference_entries(project_dir, references) -> list[dict]:
    """Reference display metadata with servable image paths, without spending.

    ``image_path`` is project-relative for the existing generic files route
    (``/api/projects/{project}/files/{image_path}``); it is null when the
    approved bytes are missing so the UI never renders a dead thumbnail.
    Accepts frozen-request dicts and compiled-request models alike.
    """
    from pathlib import Path as _Path

    def _field(reference, name):
        if isinstance(reference, dict):
            return reference.get(name)
        return getattr(reference, name, None)

    try:
        files = approved_reference_files(project_dir)
    except Exception:
        files = {}
    root = _Path(project_dir).resolve()
    images: dict[str, str | None] = {}
    for reference_id, source in files.items():
        try:
            candidate = _Path(source.path).resolve()
        except Exception:
            images[reference_id] = None
            continue
        images[reference_id] = (
            candidate.relative_to(root).as_posix()
            if candidate.is_relative_to(root) and candidate.is_file()
            else None
        )
    entries = []
    for reference in references:
        reference_id = _field(reference, "id")
        label = _field(reference, "label") or ""
        entity = _field(reference, "entity_id") or ""
        entries.append(
            {
                "order": _field(reference, "order"),
                "id": reference_id,
                "entity_id": entity,
                "appearance_state_id": _field(reference, "appearance_state_id"),
                "label": label,
                "display_label": label or entity or reference_id,
                "visual_anchor": _field(reference, "visual_anchor"),
                "media_type": _field(reference, "media_type"),
                "image_path": images.get(reference_id) if reference_id else None,
            }
        )
    return entries
def _prepare_explicit_correction(
    *, target: TargetArtifacts, page_number: int, body: PageCorrectionCreate, config,
):
    """Run the shared no-spend validation+compile; maps failures to HTTP."""
    from novel_to_comic.page_review import (
        InvalidCorrectionError,
        StaleCorrectionError,
        deterministic_manual_issue_id,
    )
    from novel_to_comic.target_artifacts import ArtifactInvalid

    try:
        page = target.read_page(page_number)
        edition = ensure_current_page_edition(target, target.read_book_edition())
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
        )
        complete_page_adapter(config).prepare(prepared.compiled)
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
        "references": _reference_entries(target.project_dir, compiled.request.references),
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
@router.post("/pages/{page_number}/corrections/preview")
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
        target=target, page_number=page_number, body=body, config=config,
    )
    return _correction_preview_payload(target=target, page_number=page_number, prepared=prepared, config=config)


@router.post("/pages/{page_number}/corrections")
def submit_page_correction(
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
        request.app.state.generation_jobs.values(),
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
    adapter = complete_page_adapter(config)
    queue = request.app.state.event_queues.get(pkey)
    if queue is not None:
        queue.put_nowait(
            {"type": "page_start", "stage": "draw", "page_number": page_number}
        )
    job, _created = enqueue_complete_page_draw(
        request.app,
        project_name=pkey,
        user_id=user_id,
        project_id=project_id,
        project_dir=project_dir,
        config=config,
        compiled=compiled,
        adapter=adapter,
        artifacts=target,
        page=target.read_page(page_number),
        ocr=GatewayPageOCRAdapter(config, page_number=page_number),
        parent_render_revision=correction.parent_render_revision,
        issue=primary_issue,
        on_success=_draw_success_callback(
            request,
            pkey=pkey,
            project_dir=project_dir,
        ),
    )
    return {
        "status": "queued",
        "job": generation_job_payload(request.app, job),
        "selected_issue_ids": list(correction.issue_ids),
    }


@router.get("/provider-usage")
def project_provider_usage(
    project_id: str,
    project_dir=Depends(get_project_dir),
    user_id: str = Depends(get_current_user),
):
    """Provider costs, including failed calls, separate from charged credits."""
    from ..db import get_db
    from novel_to_comic.project_usage import page_usage_links, summarize_provider_usage

    events = []
    try:
        for start in range(0, 100_000, 1000):
            batch = (get_db().table("ai_usage_events")
                     .select("id,stage,feature,status,cost_usd,cost_source,funding,metadata_json")
                     .eq("user_id", user_id).eq("project_id", project_id)
                     .order("id").range(start, start + 999).execute().data or [])
            events.extend(batch)
            if len(batch) < 1000:
                break
        else:
            raise HTTPException(503, "Provider usage exceeds the supported report size.")
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(503, "Provider usage is unavailable; no zero-cost total can be inferred.") from exc
    from novel_to_comic.target_artifacts import ArtifactInvalid
    try:
        links = page_usage_links(TargetArtifacts(project_dir))
        link_error = None
    except (ArtifactMissing, ArtifactInvalid) as exc:
        links = {}
        link_error = str(exc)
    report = summarize_provider_usage(events, links)
    report["artifact_link_error"] = link_error
    if link_error:
        report["complete"] = False
    return report

@router.get("/pages/{page_number}/visual-review/estimate")
def visual_review_estimate(page_number: int, project=Depends(get_project)):
    from novel_to_comic.config import PAGE_VISUAL_REVIEW_ESTIMATED_COST_USD
    from ..credits import credit_estimate_for_provider_cost
    project_dir, config, _state = project
    target = TargetArtifacts(project_dir)
    if _latest_provenance(target, page_number) is None:
        raise HTTPException(409, "Page has no render to review")
    try:
        compiled = compile_page_generation_request(
            target.read_page(page_number),
            ensure_current_page_edition(target, target.read_book_edition()),
            approved_visual_inventory(project_dir),
            approved_reference_files(project_dir),
            retry=RetryProvenance(attempt=1),
            style_template=config.style_template,
        )
        complete_page_adapter(config).prepare(compiled)
    except (ArtifactMissing, ValueError) as exc:
        raise HTTPException(409, str(exc)) from exc
    return credit_estimate_for_provider_cost(
        float(PAGE_VISUAL_REVIEW_ESTIMATED_COST_USD), 'draw', reserve=True,
        funding=classify_operations(page_check_operations(project[1])),
    )

@router.post("/pages/{page_number}/visual-review")
async def visual_review_page(page_number: int, project_id: str,
                             project=Depends(get_project), user_id: str = Depends(get_current_user)):
    from ..credited_job import run_credited_page_check
    from novel_to_comic.page_visual_review import review_page_visuals
    from novel_to_comic.config import PAGE_VISUAL_REVIEW_ESTIMATED_COST_USD
    from novel_to_comic.target_artifacts import ArtifactInvalid

    project_dir, config, _state = project
    target = TargetArtifacts(project_dir)
    active = _latest_provenance(target, page_number)
    if active is None:
        raise HTTPException(409, "Page has no render to review")
    try:
        page = target.read_page(page_number)
        compiled = compile_page_generation_request(
            page, ensure_current_page_edition(target, target.read_book_edition()), approved_visual_inventory(project_dir),
            approved_reference_files(project_dir), retry=RetryProvenance(attempt=1), style_template=config.style_template,
        )
        complete_page_adapter(config).prepare(compiled)
        result = await run_credited_page_check(
            user_id=user_id, project_id=project_id, project_dir=project_dir, page_number=page_number,
            estimated_cost_usd=float(PAGE_VISUAL_REVIEW_ESTIMATED_COST_USD),
            operations=page_check_operations(config),
            work=lambda: review_page_visuals(config=config, page=page, render=active.render,
                image=target.read_render(page_number, active.render.revision), compiled=compiled, artifacts=target,
                producing_request=_producing_request(target, active.render)),
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
        compiled = compile_page_generation_request(
            page, ensure_current_page_edition(target, target.read_book_edition()), approved_visual_inventory(project_dir),
            approved_reference_files(project_dir), retry=RetryProvenance(attempt=1),
            style_template=config.style_template,
        )
        complete_page_adapter(config).prepare(compiled)
        try:
            report = validated_saved_visual_review(
                page=page, render=active.render, image=image, compiled=compiled,
                config=config, artifacts=target,
                producing_request=_producing_request(target, active.render),
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
            project_dir, reference_display_for_render(target, page_number, active.render),
        ),
    }
