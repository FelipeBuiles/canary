"""Eight-stage pipeline execution, events, invalidation, and approval."""

from __future__ import annotations

from ..pipeline_operations import (STAGE_AUTO_CHAIN, StageScope, _part_to_adapt_after, part_order_blocker)


import asyncio
import json
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse, StreamingResponse

from novel_to_comic.briefing import approve_brief, require_approved_brief
from novel_to_comic.models.story_bible import MissingVisualAnchor
from novel_to_comic.state import (
    STAGE_NAMES,
    StageState,
    StageStatus,
    approve_stage,
    hash_style_template,
    is_series_stage,
    load_series_state,
    load_state,
    reset_stale_stages,
    save_state,
)
from novel_to_comic.target_artifacts import ArtifactInvalid, ArtifactMissing, TargetArtifacts
from novel_to_comic.workspace import part_id_for_path, part_workspaces, series_root

from ..auth import get_current_user
from ..codex_admission import admit_stage_action
from ..credits import (
    CreditEstimate,
    UnifiedCostResolver,
    assert_sufficient_credits,
    estimate_adaptation_restart,
    estimate_stage_credit_reservation,
)
from ..db import get_db
from ..async_credits import ledger_call
from ..deps import event_key, get_project, project_key
from ..generation_jobs import generation_job_payload, generation_jobs_snapshot, job_part_id
from ..admission import project_busy
from ..event_channel import EventChannel
from ..product_events import capture_server_event
from ..lifecycle_events import capture as capture_lifecycle
from ..ratelimit import cost_limit, limiter


router = APIRouter()







def route_part_id(request) -> str | None:
    """The part a request addresses; direct callers without a route have none."""
    path_params = getattr(request, "path_params", None) or {}
    return path_params.get("part_id")


def _first_part_dir(root: Path) -> Path | None:
    workspaces = part_workspaces(root)
    return workspaces[0] if workspaces else None


def stage_scope(request: Request, project, stage: str) -> StageScope:
    """Series stages act on the series root; part stages need a part route.

    The gate view overlays the series stages on a part's own stages, so a
    series stage reached from the series route is gated by the first part.
    """
    directory, config, state = project
    root = series_root(directory)
    on_part_route = route_part_id(request) is not None or directory != root
    if directory == root and not part_workspaces(root):
        # A single-directory project is its own series and its only part.
        return StageScope(directory, config, state, state, directory)
    if is_series_stage(stage):
        first = None if on_part_route else _first_part_dir(root)
        gate = state if on_part_route else (load_state(first) if first else state)
        part_dir = directory if on_part_route else first
        return StageScope(root, config, load_series_state(root), gate, part_dir)
    if not on_part_route:
        raise HTTPException(409, {
            "code": "part_required",
            "message": f"The {stage} stage runs for one part. Choose a part first.",
        })
    return StageScope(directory, config, state, state, directory)
















def _enqueue_pipeline(app, pkey, user_id, project_id, project_dir, config, stage,
                      *, rerun=False, queue_pages=False, approve_part=None):
    from ..generation_jobs import enqueue_generation_job
    from ..job_commands import command
    descriptor = command("pipeline", project_dir, config, rerun=rerun, queue_pages=queue_pages,
                         approve_part=approve_part)
    descriptor = descriptor.model_copy(update={"stage": stage, "user_id": user_id, "project_id": project_id})
    return enqueue_generation_job(app, pkey, "pipeline_stage", stage,
                                  {"stage": stage}, None, user_id=user_id, command=descriptor)








def _any_part_adapted(project_dir: Path) -> bool:
    return any(
        TargetArtifacts(workspace).adaptation_path.exists()
        or load_state(workspace).stages["adapt"].status == StageStatus.RUNNING
        for workspace in part_workspaces(series_root(project_dir))
    )


def _require_previous_stage(state, stage: str) -> None:
    index = STAGE_NAMES.index(stage)
    if index == 0:
        return
    previous = STAGE_NAMES[index - 1]
    if state.stages[previous].status != StageStatus.COMPLETE:
        raise HTTPException(
            409,
            f"Stage '{previous}' must complete before '{stage}'.",
        )


def _require_adaptation_brief(project_dir) -> None:
    try:
        require_approved_brief(TargetArtifacts(project_dir).read_brief())
    except (ArtifactMissing, ValueError, FileNotFoundError) as exc:
        raise HTTPException(409, str(exc)) from exc


@router.get("/estimate")
async def estimate_stage_cost(
    request: Request,
    project_id: str,
    stage: str = Query(...),
    project=Depends(get_project),
    user_id: str = Depends(get_current_user),
    rerun: bool = False,
):
    if stage not in STAGE_NAMES:
        raise HTTPException(400, f"Unknown stage: {stage}. Valid: {STAGE_NAMES}")
    scope = stage_scope(request, project, stage)
    project_dir, config, state = scope.directory, scope.config, scope.state
    project = (project_dir, config, state)
    funding = admit_stage_action(config, stage)
    if stage == "adapt" and rerun:
        return {"stage": stage, **estimate_adaptation_restart(config, project_dir, state)}
    if stage == "draw":
        from .pages import estimate_remaining_page_generation

        return {"stage": stage, **estimate_remaining_page_generation(project, request, project_id, user_id)}
    chain = [stage, *STAGE_AUTO_CHAIN.get(stage, ())]
    try:
        parts = [
            UnifiedCostResolver.estimate_stage_cost(
                config,
                project_dir,
                state,
                name,
            )
            for name in chain
        ]
    except MissingVisualAnchor as exc:
        raise HTTPException(409, str(exc)) from exc
    free_opening = _free_opening_decision(request, project_dir, state, project_id, stage, rerun)
    if free_opening and free_opening["status"] == "free":
        # Canary pays for this Extract and the Brief it chains: quote the author nothing.
        parts = [{**part, "estimate_credits": 0, "reserved_credits": 0} for part in parts]
    return {
        "stage": stage,
        **({"free_opening": free_opening} if free_opening else {}),
        **({"archived_page_count": TargetArtifacts(project_dir).drawn_page_count()}
           if stage == "plan" and rerun else {}),
        **CreditEstimate(
            estimate_credits=sum(item["estimate_credits"] for item in parts),
            reserved_credits=sum(
                item["reserved_credits"] or 0 for item in parts
            ),
            reservation_multiplier=parts[0]["reservation_multiplier"],
            confidence=parts[0]["confidence"],
            funding=funding,
        ),
    }


def _free_opening_decision(request: Request, project_dir, state, project_id: str, stage: str, rerun: bool,
                           *, claim: bool = False) -> dict | None:
    from ..cold_open_jobs import free_opening_decision, free_opening_max_chars

    if stage != "extract" or rerun or not free_opening_max_chars():
        return None
    from ..auth import token_identity
    from ..free_opening_guard import Applicant
    from ..ratelimit import client_ip

    applicant = Applicant(*token_identity(request), client_ip(request))
    return free_opening_decision(project_dir, state, project_id, stage, claim=claim, applicant=applicant)


def _free_opening(request: Request, project_dir, state, project_id: str, stage: str, rerun: bool,
                  *, claim: bool = True) -> str | None:
    from novel_to_comic import cold_open

    decision = _free_opening_decision(request, project_dir, state, project_id, stage, rerun, claim=claim)
    return cold_open.SPONSOR if decision and decision["status"] == "free" else None


async def _start_stage(
    request: Request,
    project_id: str,
    stage: Optional[str],
    rerun: bool,
    project,
    user_id: str,
    queue_pages: bool = False,
    confirmed_archive_pages: int | None = None,
    then_approve: bool = False,
):
    if stage is None:
        raise HTTPException(400, "stage parameter is required")
    if stage not in STAGE_NAMES:
        raise HTTPException(400, f"Unknown stage: {stage}. Valid: {STAGE_NAMES}")
    scope = stage_scope(request, project, stage)
    project_dir, config, state = scope.directory, scope.config, scope.state
    admit_stage_action(config, stage)
    if stage == "draw":
        from ..page_operations import prepare_undrawn_pages

        try:
            await asyncio.to_thread(
                prepare_undrawn_pages, project_dir=project_dir, config=config, rerun=rerun,
            )
        except (ArtifactMissing, ValueError) as exc:
            raise HTTPException(409, {
                "code": "draw_preflight_rejected", "message": str(exc),
            }) from exc
    pkey = project_key(user_id, project_id)
    # Another part's drawing never blocks this part's (or the series') work.
    if project_busy(request.app, pkey, part_id_for_path(project_dir), series=is_series_stage(stage)):
        raise HTTPException(409, "Wait for all project jobs to finish before running a stage.")

    if rerun and is_series_stage(stage) and _any_part_adapted(project_dir):
        raise HTTPException(409, {
            "code": "series_look_locked",
            "message": (f"{stage.title()} can't be redone from scratch once a part has an "
                        "adaptation; correct individual references in Cast instead."),
        })

    if stage == "plan" and rerun:
        count = TargetArtifacts(project_dir).drawn_page_count()
        if confirmed_archive_pages != count:
            raise HTTPException(409, f"Confirm restarting Plan: {count} drawn pages and downstream work will be archived. Refresh the estimate and confirm again.")

    if stage == "adapt":
        _require_adaptation_brief(project_dir)

    order_blocker = part_order_blocker(scope.part_dir if not is_series_stage(stage) else None, stage)
    if order_blocker:
        raise HTTPException(409, {"code": "part_order", "message": order_blocker})
    if stage == "extract" and rerun and part_id_for_path(project_dir) is not None:
        from novel_to_comic.series import edit_blocker

        locked = edit_blocker(project_dir, part_id_for_path(project_dir))
        if locked:
            raise HTTPException(409, {"code": "part_locked", "message": locked})

    if not rerun or stage == "adapt":
        _require_previous_stage(scope.gate, stage)

    if stage in {"cast", "adapt", "plan", "draw", "finish"}:
        from .styles import is_style_selected

        if not is_style_selected(project_dir, config):
            raise HTTPException(403, "Style must be selected first.")

    approve_part = None
    if then_approve:
        if stage != "cast" or rerun or scope.part_dir is None:
            raise HTTPException(400, "then_approve continues a part from a Cast run only.")
        approve_part = str(scope.part_dir)

    # A Canary-paid first Extract needs no balance. The grant is claimed here,
    # where the request shows who is asking; the job only honors it.
    if stage != "draw" and _free_opening(request, project_dir, state, project_id, stage, rerun) is None:
        try:
            if rerun and stage == "adapt":
                required = estimate_adaptation_restart(config, project_dir, state)["reserved_credits"] or 0
            else:
                required = estimate_stage_credit_reservation(config, project_dir, state, stage)
        except MissingVisualAnchor as exc:
            raise HTTPException(409, str(exc)) from exc
        await ledger_call(assert_sufficient_credits, get_db(), user_id, required, stage=stage)
    queue = EventChannel()
    request.app.state.event_queues[event_key(pkey, project_dir)] = queue
    admitted = _enqueue_pipeline(request.app, pkey, user_id, project_id, project_dir,
                                 config, stage, rerun=rerun, queue_pages=queue_pages,
                                 approve_part=approve_part)
    return {"status": "started", "stage": stage, "job": generation_job_payload(request.app, admitted)}


@router.post("/run", openapi_extra={'x-canary-action': {'spends': True, 'dispatches': True}})
@limiter.limit(cost_limit)
async def run_pipeline(
    request: Request,
    project_id: str,
    stage: Optional[str] = Query(None),
    rerun: bool = Query(False),
    queue_pages: bool = Query(False),
    confirmed_archive_pages: int | None = Query(None, ge=0),
    then_approve: bool = Query(False),
    project=Depends(get_project),
    user_id: str = Depends(get_current_user),
):
    """``then_approve`` (Cast only): approve Cast and start Adapt if the run leaves nothing to review."""
    return await _start_stage(
        request,
        project_id,
        stage,
        rerun,
        project,
        user_id,
        queue_pages,
        confirmed_archive_pages,
        then_approve,
    )


@router.get("/restart-archives")
def list_restart_archives(project=Depends(get_project)):
    return {"archives": TargetArtifacts(project[0]).restart_archives()}


@router.get("/restart-archives/{archive_id}/file")
def read_restart_archive_file(archive_id: str, path: str, project=Depends(get_project)):
    try:
        saved = TargetArtifacts(project[0]).restart_archive_file(archive_id, path)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    return FileResponse(saved, headers={"Cache-Control": "private, max-age=60"})


@router.post("/regen-extract", openapi_extra={'x-canary-action': {'spends': True, 'dispatches': True}})
@limiter.limit(cost_limit)
async def regen_extract(
    request: Request,
    project_id: str,
    project=Depends(get_project),
    user_id: str = Depends(get_current_user),
):
    """Re-read the novel and rebuild the Story Bible from scratch.

    Identical to ``POST /run?stage=extract&rerun=1``. The Story station calls it
    under its own name so re-extraction stays one action in the UI rather than a
    flag the caller has to remember.
    """
    return await _start_stage(request, project_id, "extract", True, project, user_id)


@router.get("/events")
async def event_stream(
    request: Request,
    project_id: str,
    user_id: str = Depends(get_current_user),
):
    pkey = project_key(user_id, project_id)
    own_key = event_key(pkey, part_id=route_part_id(request))
    # A part's view also follows series work (Style, Cast) on the series stream.
    keys = [own_key] if own_key == pkey else [own_key, pkey]
    channels = {key: request.app.state.event_queues.get(key) for key in keys}
    channels = {key: channel for key, channel in channels.items() if channel is not None}
    if not channels:
        raise HTTPException(404, "No active run for this project; reload project status.")
    queues = {key: channel.subscribe() for key, channel in channels.items()}

    async def generator():
        waiting: dict[asyncio.Future, str] = {}
        try:
            while True:
                if await request.is_disconnected():
                    break
                for key, queue in queues.items():
                    if key not in waiting.values():
                        waiting[asyncio.ensure_future(queue.get())] = key
                done, _ = await asyncio.wait(waiting, timeout=30, return_when=asyncio.FIRST_COMPLETED)
                if not done:
                    yield ": keepalive\n\n"
                    continue
                finished = False
                for future in done:
                    key = waiting.pop(future)
                    event = future.result()
                    yield f"data: {json.dumps(event)}\n\n"
                    finished = finished or (event.get("type") == "pipeline_done" and (key == own_key or len(queues) == 1))
                if finished:
                    break
        finally:
            for future in waiting:
                future.cancel()
            for key, queue in queues.items():
                channels[key].unsubscribe(queue)

    return StreamingResponse(generator(), media_type="text/event-stream")


@router.post("/jobs/cancel-queued-pages", openapi_extra={'x-canary-action': {'spends': False, 'dispatches': False}})
async def cancel_queued_page_jobs(
    request: Request,
    project_id: str,
    project=Depends(get_project),
    user_id: str = Depends(get_current_user),
):
    """Stop waiting page draws without interrupting submitted provider work."""
    queue = getattr(request.app.state, "durable_queue", None)
    if queue is None:
        raise HTTPException(503, "The generation queue is unavailable; no jobs were cancelled.")
    ids = await queue.cancel_queued_pages(
        project_name=project_key(user_id, project_id), user_id=user_id,
    )
    return {"cancelled_job_ids": ids}


@router.get("/generation-jobs")
@router.get("/jobs")
def get_generation_jobs(
    request: Request,
    project_id: str,
    ids: list[str] | None = Query(None, max_length=200),
    before: int | None = Query(None, ge=1),
    limit: int = Query(100, ge=1, le=200),
    project=Depends(get_project),
    user_id: str = Depends(get_current_user),
):
    pkey = project_key(user_id, project_id)
    # A part sees its own jobs plus series work (Style, Cast); the series
    # route sees every job in the project.
    part = route_part_id(request)

    def visible(job_part: str | None) -> bool:
        return part is None or job_part in {None, part}

    jobs = [
        job
        for job in generation_jobs_snapshot(request.app)
        if job.project_name == pkey and (ids is None or job.id in ids)
        and visible(job_part_id(job))
    ]
    jobs.sort(key=lambda job: job.sequence)
    from ..job_journal import history
    records, next_cursor = history(request.app, pkey, ids=ids, part=part, before=before, limit=limit)
    live = {job.id: generation_job_payload(request.app, job) for job in jobs}
    payloads = [live.pop(record["id"], record) for record in records]
    payloads.extend(value for value in live.values() if value["status"] in {"queued", "running"})
    _mark_current_page_jobs(TargetArtifacts(project[0]), payloads, {
        job.id: job.command.arguments["request"]
        for job in jobs
        if job.command is not None and job.command.operation == "page_draw"
        and "request" in job.command.arguments
    })
    return {"jobs": payloads, "next_cursor": next_cursor, "current_reference_style_hash": hash_style_template(project[1].style_template)}


def _mark_current_page_jobs(
    target: TargetArtifacts, jobs: list[dict], admitted_requests: dict[str, dict] | None = None,
) -> None:
    """Keep job history, but bind page status to the actual frozen page input."""
    from novel_to_comic.models.draw import FrozenPageGenerationRequest

    current_requests: dict[int, set[str]] = {}
    for job in jobs:
        if job["kind"] != "complete_page_draw":
            continue
        payload = job.get("payload", {})
        page_number = payload.get("page_number")
        job["is_current_page"] = False
        if not isinstance(page_number, int) or page_number < 1:
            continue
        if page_number not in current_requests:
            hashes: set[str] = set()
            current_requests[page_number] = hashes
            try:
                page = target.read_page(page_number)
            except (ArtifactMissing, ArtifactInvalid):
                continue
            for revision in target.request_revisions(page_number):
                try:
                    frozen = target.read_request(page_number, revision)
                except (ArtifactMissing, ArtifactInvalid):
                    continue
                if not frozen.is_stale_for(page):
                    hashes.add(frozen.request_sha256)
        admitted = (admitted_requests or {}).get(job["id"])
        if admitted is not None:
            # Queued commands already own immutable inputs; the request artifact
            # is only written when execution starts. Do not hide the waiting jobs.
            try:
                frozen = FrozenPageGenerationRequest.model_validate(admitted)
                page = target.read_page(page_number)
            except (ValueError, ArtifactMissing, ArtifactInvalid):
                continue
            job["is_current_page"] = (
                frozen.page_number == page_number
                and frozen.request_sha256 == payload.get("request_sha256")
                and not frozen.is_stale_for(page)
            )
        else:
            job["is_current_page"] = payload.get("request_sha256") in current_requests[page_number]






@router.post("/approve/{stage}", openapi_extra={'x-canary-action': {'spends': True, 'dispatches': True, 'paid_stages': ['brief', 'cast']}})
async def approve(
    stage: str,
    project_id: str,
    request: Request,
    project=Depends(get_project),
    user_id: str = Depends(get_current_user),
):
    if stage not in STAGE_NAMES:
        raise HTTPException(400, f"Unknown stage: {stage}")
    scope = stage_scope(request, project, stage)
    project_dir, config, state = scope.directory, scope.config, scope.state
    if stage == "cast":
        from novel_to_comic.stages.s3_cast import cast_approval_blocker
        blocker = cast_approval_blocker(config, project_dir, state.stages["cast"])
        if blocker:
            raise HTTPException(409, {"code": "cast_approval_rejected", "message": blocker})
    if stage == "draw":
        from novel_to_comic.page_review import summarize_page_issues

        target = TargetArtifacts(project_dir)
        plan = target.read_plan()
        missing_pages = [
            page.page_number
            for page in plan.pages
            if not target.provenance_revisions(page.page_number)
        ]
        if missing_pages:
            raise HTTPException(
                409,
                {
                    "error": "missing_page_renders",
                    "page_numbers": missing_pages,
                },
            )
        summary = summarize_page_issues(TargetArtifacts(project_dir))
        if summary.blocking_issue_ids:
            raise HTTPException(
                409,
                {
                    "error": "page_invariants_block_continue",
                    "issue_ids": summary.blocking_issue_ids,
                },
            )
    adapt_part = _part_to_adapt_after(scope, stage)
    if adapt_part is not None:
        admit_stage_action(config, "adapt")
    try:
        if stage == "brief":
            target = TargetArtifacts(project_dir)
            brief = target.read_brief()
            target.write_brief(
                approve_brief(brief, expected_revision=brief.revision)
            )
        elif stage == "cast":
            if scope.part_dir is None:
                raise ValueError("Approve a part's Brief before approving Cast.")
            require_approved_brief(TargetArtifacts(scope.part_dir).read_brief())
        approve_stage(state, stage)
    except (ArtifactMissing, ValueError, FileNotFoundError) as exc:
        raise HTTPException(409, str(exc)) from exc
    save_state(state, project_dir)
    if stage == "cast":
        from novel_to_comic import runware_prefetch

        runware_prefetch.start(config, project_dir)
    capture_server_event(
        "stage_approved",
        user_id=user_id,
        project_id=project_id,
        properties={"stage": stage},
    )
    if stage == "draw":
        current = state.stages[stage]
        capture_lifecycle(request.app, "output_accepted", current.attempt_id or f"{project_id}:draw:{current.finished_at}",
                          user_id=user_id, project_id=project_id,
                          properties={"stage": "draw", "scope": "edition", "run_id": current.run_id,
                                      "attempt_id": current.attempt_id})
    response = {"status": "approved", "stage": stage}
    if adapt_part is not None:
        pkey = project_key(user_id, project_id)
        queue = EventChannel()
        request.app.state.event_queues[event_key(pkey, adapt_part)] = queue
        _enqueue_pipeline(request.app, pkey, user_id, project_id, adapt_part, config, "adapt")
        response["auto_started"] = "adapt"
        response["auto_started_part"] = adapt_part.name
    return response


@router.post("/reset/{stage}", openapi_extra={'x-canary-action': {'spends': False, 'dispatches': False}})
def reset_stage(
    stage: str,
    project_id: str,
    project=Depends(get_project),
    user_id: str = Depends(get_current_user),
    request: Request = None,
):
    if stage not in STAGE_NAMES:
        raise HTTPException(400, f"Unknown stage: {stage}")
    scope = stage_scope(request, project, stage)
    project_dir, state = scope.directory, scope.state
    if state.stages[stage].status != StageStatus.FAILED:
        raise HTTPException(409, f"Stage '{stage}' is not failed.")
    reset = [stage]
    state.stages[stage] = StageState()
    reset.extend(name for name in reset_stale_stages(state) if name != stage)
    save_state(state, project_dir)
    return {"status": "reset", "reset": reset}


@router.get("/stage-error/{stage}")
def get_stage_error(
    stage: str,
    project_id: str,
    project=Depends(get_project),
    request: Request = None,
):
    if stage not in STAGE_NAMES:
        raise HTTPException(400, f"Unknown stage: {stage}")
    state = stage_scope(request, project, stage).state
    stage_state = state.stages[stage]
    if stage_state.status != StageStatus.FAILED:
        raise HTTPException(404, f"Stage '{stage}' is not failed.")
    from ..diagnostics import local_diagnostics_enabled

    return {
        "stage": stage,
        "error": stage_state.error or "Unknown error",
        "error_detail": stage_state.error_detail if local_diagnostics_enabled() else None,
        "items_failed": stage_state.items_failed,
    }
