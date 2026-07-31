"""Complete-page Draw and review-by-exception routes."""

from __future__ import annotations

import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel

from novel_to_comic.models.draw import PageIssue, RetryProvenance
from novel_to_comic.page_drawing import (
    GoogleVertexCompletePageTransport,
    VertexCompletePageAdapter,
    analyze_complete_page,
    compile_page_generation_request,
    ensure_current_page_edition,
    enqueue_complete_page_draw,
)
from novel_to_comic.page_ocr import GatewayPageOCRAdapter
from novel_to_comic.page_review import (
    accept_editorial_page_issue,
    build_correction_request,
    dismiss_page_issue,
    record_page_issue,
    summarize_page_issues,
)
from novel_to_comic.stages.s5_plan import (
    approved_reference_files,
    approved_visual_inventory,
)
from novel_to_comic.state import StageStatus, complete_stage, load_state, save_state
from novel_to_comic.target_artifacts import ArtifactMissing, TargetArtifacts

from ..auth import get_current_user
from ..deps import get_project, project_key
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


def _page_failure(target: TargetArtifacts, page_number: int):
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


def _correction_retry(
    target: TargetArtifacts,
    *,
    page_number: int,
    issue_id: str,
) -> RetryProvenance:
    prior_requests = [
        target.read_request(page_number, revision)
        for revision in target.request_revisions(page_number)
    ]
    prior_attempts = [
        request
        for request in prior_requests
        if request.correction is not None
        and request.correction.issue_id == issue_id
    ]
    if not prior_attempts:
        return RetryProvenance(attempt=1)
    prior = max(prior_attempts, key=lambda request: request.retry.attempt)
    return RetryProvenance(
        attempt=prior.retry.attempt + 1,
        retries_request_sha256=prior.request_sha256,
    )


def _active_correction_job(request: Request, *, pkey: str, issue_id: str):
    return next(
        (
            job
            for job in request.app.state.generation_jobs.values()
            if job.project_name == pkey
            and job.kind == "complete_page_draw"
            and job.payload.get("issue_id") == issue_id
            and job.status in {"queued", "running"}
        ),
        None,
    )


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


def enqueue_all_undrawn_pages(
    request: Request,
    *,
    project_id: str,
    user_id: str,
    project_dir,
    config,
):
    """Queue every planned page that does not already have a render."""

    target = TargetArtifacts(project_dir)
    plan = target.read_plan()
    edition = ensure_current_page_edition(
        target,
        target.read_book_edition(),
    )
    inventory = approved_visual_inventory(project_dir)
    reference_files = approved_reference_files(project_dir)
    adapter = VertexCompletePageAdapter(GoogleVertexCompletePageTransport(config))
    pkey = project_key(user_id, project_id)
    queue = request.app.state.event_queues.get(pkey)
    prepared = []
    jobs = []

    for selected in plan.pages:
        page_number = selected.page_number
        if target.provenance_revisions(page_number):
            continue
        page = target.read_page(page_number)
        compiled = compile_page_generation_request(
            page,
            edition,
            inventory,
            reference_files,
            retry=RetryProvenance(attempt=1),
            style_template=config.style_template,
        )
        # Validate the whole batch before reserving credits or queueing its
        # first page, so a later unsupported page cannot leave a partial batch.
        adapter.prepare(compiled)
        prepared.append((page_number, page, compiled))

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
    target = TargetArtifacts(project_dir)
    try:
        page = target.read_page(page_number)
        edition = target.read_book_edition()
        edition = ensure_current_page_edition(target, edition)
        compiled = compile_page_generation_request(
            page,
            edition,
            approved_visual_inventory(project_dir),
            approved_reference_files(project_dir),
            retry=RetryProvenance(attempt=1),
            depiction=generation.depiction if generation is not None else "canonical",
            style_template=config.style_template,
        )
    except (ArtifactMissing, ValueError) as exc:
        raise HTTPException(409, str(exc)) from exc
    revisions = target.provenance_revisions(page_number)
    if revisions:
        raise HTTPException(
            409,
            "Page already has a render; create an issue and request a correction.",
        )
    adapter = VertexCompletePageAdapter(GoogleVertexCompletePageTransport(config))
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


@router.post("/pages/{page_number}/analyze")
async def analyze_page(
    page_number: int,
    project=Depends(get_project),
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
        analysis = await analyze_complete_page(
            page=page,
            render=active.render,
            image=image,
            ocr=GatewayPageOCRAdapter(config, page_number=page_number),
            artifacts=target,
        )
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    target.clear_page_failure(page_number)
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


@router.post("/pages/{page_number}/issues/{issue_id}/correct")
def correct_page_issue(
    page_number: int,
    issue_id: str,
    request: Request,
    project_id: str,
    project=Depends(get_project),
    user_id: str = Depends(get_current_user),
):
    project_dir, config, _state = project
    target = TargetArtifacts(project_dir)
    issue = _find_issue(target, page_number, issue_id)
    pkey = project_key(user_id, project_id)
    active_job = _active_correction_job(request, pkey=pkey, issue_id=issue_id)
    if active_job is not None:
        return {
            "status": "queued",
            "job": generation_job_payload(request.app, active_job),
        }
    try:
        page = target.read_page(page_number)
        edition = target.read_book_edition()
        edition = ensure_current_page_edition(target, edition)
        parent = target.read_provenance(
            page_number,
            issue.render_revision,
        ).render
        correction = build_correction_request(
            issue=issue,
            page=page,
            parent=parent,
            profile=edition.capability_profile,
            artifacts=target,
        )
        compiled = compile_page_generation_request(
            page,
            edition,
            approved_visual_inventory(project_dir),
            approved_reference_files(project_dir),
            retry=_correction_retry(
                target,
                page_number=page_number,
                issue_id=issue_id,
            ),
            correction=correction,
            edit_source_bytes=target.read_render(
                page_number,
                issue.render_revision,
            ),
            style_template=config.style_template,
        )
    except (ArtifactMissing, ValueError) as exc:
        raise HTTPException(409, str(exc)) from exc
    adapter = VertexCompletePageAdapter(GoogleVertexCompletePageTransport(config))
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
        compiled=compiled,
        adapter=adapter,
        artifacts=target,
        page=page,
        ocr=GatewayPageOCRAdapter(config, page_number=page_number),
        parent_render_revision=issue.render_revision,
        issue=issue,
        on_success=_draw_success_callback(
            request,
            pkey=pkey,
            project_dir=project_dir,
        ),
    )
    return {"status": "queued", "job": generation_job_payload(request.app, job)}
