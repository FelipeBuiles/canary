"""Eight-stage pipeline execution, events, invalidation, and approval."""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
import time
import traceback
import uuid
from pathlib import Path
from typing import NamedTuple, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse, StreamingResponse

from novel_to_comic.briefing import approve_brief, require_approved_brief
from novel_to_comic.models.story_bible import MissingVisualAnchor
from novel_to_comic.stage_runtime import StageRuntime
from novel_to_comic.stages import REGISTRY
from novel_to_comic.state import (
    PART_STAGES,
    STAGE_NAMES,
    PipelineState,
    StageState,
    StageStatus,
    approve_stage,
    fail_stage,
    is_series_stage,
    load_series_state,
    load_state,
    reset_stale_stages,
    save_state,
)
from novel_to_comic.target_artifacts import ArtifactInvalid, ArtifactMissing, TargetArtifacts
from novel_to_comic.series import cast_inventory_keys, reopen_cast_for_new_inventory
from novel_to_comic.workspace import part_id_for_path, part_workspaces, series_root

from ..auth import get_current_user
from ..credited_job import CreditReservationDenied, run_credited_stage
from ..codex_admission import admit_stage_action
from ..credits import (
    CreditEstimate,
    UnifiedCostResolver,
    assert_sufficient_credits,
    estimate_adaptation_restart,
    estimate_stage_credit_reservation,
)
from ..db import get_db
from ..deps import event_key, get_project, project_key
from ..generation_jobs import generation_job_payload, job_part_id
from ..admission import project_busy
from ..event_channel import EventChannel
from ..metrics import increment, observe
from ..telemetry import metric_count, metric_histogram
from ..product_events import capture_server_event
from ..lifecycle_events import capture as capture_lifecycle, stage_properties
from ..telemetry import context_fields
from ..ratelimit import cost_limit, limiter


router = APIRouter()
logger = logging.getLogger("canary.pipeline")


STAGE_AUTO_CHAIN: dict[str, list[str]] = {
    "extract": ["brief"],
    "adapt": ["plan"],
}

STATE_INVALIDATION: dict[str, tuple[str, ...]] = {
    # Re-extracting a part resets only that part; Style and Cast are series-wide.
    "extract": PART_STAGES,
    "brief": ("brief", "adapt", "plan", "draw", "finish"),
    "style": ("style", "cast", "adapt", "plan", "draw", "finish"),
    "cast": ("cast", "adapt", "plan", "draw", "finish"),
    "adapt": ("adapt", "plan", "draw", "finish"),
    "plan": ("plan", "draw", "finish"),
    "draw": ("draw", "finish"),
    "finish": ("finish",),
}


class StageScope(NamedTuple):
    """Where a stage runs, the state it mutates, and the view that gates it."""

    directory: Path
    config: object
    state: PipelineState
    gate: PipelineState
    part_dir: Path | None


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


def _previous_part_dir(part_dir: Path) -> Path | None:
    identifier = part_id_for_path(part_dir)
    if identifier is None:
        return None
    workspaces = part_workspaces(series_root(part_dir))
    index = next((i for i, item in enumerate(workspaces) if item.name == identifier), 0)
    return workspaces[index - 1] if index > 0 else None


def part_order_blocker(part_dir: Path | None, stage: str) -> str | None:
    """Parts extract and adapt in reading order; later stages are independent.

    Extraction needs the earlier parts' registry, and adaptation uses the
    previous part's adapted ending as continuity context.
    """
    if part_dir is None or stage not in {"extract", "adapt"}:
        return None
    previous = _previous_part_dir(part_dir)
    if previous is None:
        return None
    if load_state(previous).stages[stage].status != StageStatus.COMPLETE:
        label = "extracted" if stage == "extract" else "adapted"
        return f"The previous part must be {label} before this part."
    return None


def _wrap_on_event(queue: asyncio.Queue):
    def handler(event: dict) -> None:
        queue.put_nowait(event)

    return handler


async def _run_stage(
    stage: str,
    config,
    project_dir,
    state,
    queue: asyncio.Queue,
    *_unused,
    user_id: str | None = None,
    **_unused_kwargs,
) -> None:
    stage_obj = REGISTRY.get(stage)
    if stage_obj is None:
        raise ValueError(f"Unknown stage: {stage}")
    started = time.perf_counter()
    try:
        ctx = StageRuntime(
            stage,
            state,
            project_dir,
            on_event=_wrap_on_event(queue),
        )
        await stage_obj.run(config, project_dir, ctx)
    except Exception as exc:
        from novel_to_comic.text_utils import clean_exception_message

        message = clean_exception_message(exc)
        from ..diagnostics import local_diagnostics_enabled, record_diagnostic

        error_detail = traceback.format_exc() if local_diagnostics_enabled() else None
        if state.stages[stage].status != StageStatus.FAILED:
            fail_stage(
                state,
                stage,
                message,
                error_detail=error_detail,
            )
            save_state(state, project_dir)
            queue.put_nowait(
                {"type": "stage_fail", "stage": stage, "message": message}
            )
        elif error_detail and not state.stages[stage].error_detail:
            state.stages[stage].error_detail = error_detail
            save_state(state, project_dir)
        record_diagnostic(
            project_dir,
            "stage_failed",
            stage=stage,
            message=message,
            error=exc,
            error_detail=error_detail,
        )
        from ..telemetry import capture_exception

        capture_exception(exc, user_id=user_id, stage=stage)
        logger.exception(
            "Stage failed project=%s stage=%s elapsed=%.1fs",
            project_dir.name,
            stage,
            time.perf_counter() - started,
        )


def _reset_missing_auto_chain_artifact(stage: str, project_dir, state) -> None:
    target = TargetArtifacts(project_dir)
    expected = {
        "brief": target.brief_path,
        "plan": target.plan_path,
    }.get(stage)
    if expected is not None and not expected.exists() and state.stages[
        stage
    ].status in {StageStatus.COMPLETE, StageStatus.AWAITING_REVIEW}:
        state.stages[stage] = StageState()
        save_state(state, project_dir)


async def _run_stage_with_credits(
    stage: str,
    config,
    project_dir,
    state,
    queue: asyncio.Queue,
    user_id: str,
    project_id: str | None,
    *_unused,
    rerun: bool = False,
    request: Request | None = None,
    queue_draw_pages: bool = False,
    **_unused_kwargs,
) -> None:
    admit_stage_action(config, stage)
    if stage == "plan" and not rerun:
        from novel_to_comic.stages.s4_adapt import published_adaptation_needs_repair

        if published_adaptation_needs_repair(project_dir):
            # No plan can satisfy an adaptation Adapt's current contract
            # rejects, and Continue on Plan is the only control the user has.
            # Route through Adapt's targeted repair; its completion auto-chains
            # Plan, which re-checks and runs normally.
            logger.info("Plan routed through Adapt repair project=%s", project_dir.name)
            state.stages["plan"] = StageState()
            save_state(state, project_dir)
            await _run_stage_with_credits(
                "adapt", config, project_dir, state, queue, user_id, project_id,
                rerun=False, request=request,
            )
            return
    if request is not None:
        from ..generation_jobs import persist_generation_job
        for active in request.app.state.generation_jobs.values():
            if active.project_name == project_key(user_id, project_id) and active.kind == "pipeline_stage" and active.status == "running":
                active.payload["stage"] = stage
                persist_generation_job(request.app, active)
    started = time.perf_counter()
    run_id = context_fields().get("operation_id") or str(uuid.uuid4())
    attempt_id = str(uuid.uuid4())
    app = request.app if request is not None else None
    inventory_before = (
        cast_inventory_keys(series_root(project_dir)) if stage == "extract" else None
    )

    def correlate():
        current = state.stages[stage]
        current.run_id, current.attempt_id = run_id, attempt_id
        current.telemetry_user_id, current.telemetry_project_id = user_id, project_id
        current.telemetry_draw_rerun = stage == "draw" and rerun
        current.telemetry_draw_jobs = []
        current.telemetry_terminal_outcome = None
        save_state(state, project_dir)
        if app is not None:
            for active in app.state.generation_jobs.values():
                if active.id == run_id:
                    active.payload.update(run_id=run_id, stage_attempt_id=attempt_id)
                    persist_generation_job(app, active)

    async def execute():
        # The credited wrapper invokes this only after acquiring the hold.
        if rerun:
            _clear_outputs_for_rerun(project_dir, stage)
            _reset_stage_and_downstream(state, stage)
        correlate()
        capture_lifecycle(
            app, "stage_started", attempt_id,
            user_id=user_id,
            project_id=project_id,
            properties={"stage": stage, "rerun": rerun, "run_id": run_id, "attempt_id": attempt_id},
        )
        await _run_stage(stage, config, project_dir, state, queue, user_id=user_id)

    try:
        if stage == "draw":
            if not rerun:
                await execute()
            else:
                correlate()
                capture_lifecycle(app, "stage_started", attempt_id, user_id=user_id, project_id=project_id,
                                  properties={"stage": stage, "rerun": True, "run_id": run_id, "attempt_id": attempt_id})
            if queue_draw_pages or rerun:
                if request is None or project_id is None:
                    raise ValueError("queueing Draw pages requires an active request")
                from .pages import enqueue_all_undrawn_pages

                draw_jobs = await enqueue_all_undrawn_pages(
                    request,
                    project_id=project_id,
                    user_id=user_id,
                    project_dir=project_dir,
                    config=config,
                    rerun=rerun,
                )
                state.stages[stage].telemetry_draw_jobs = [job.id for job in draw_jobs]
                save_state(state, project_dir)
                # Fast local/mock jobs can finish before cohort publication.
                from .pages import _sync_draw_progress
                _sync_draw_progress(project_dir, request.app)
            job_id = None
        else:
            job_id = await run_credited_stage(
                user_id=user_id,
                project_id=project_id,
                project_dir=project_dir,
                config=config,
                state=state,
                stage=stage,
                run=execute,
                fresh_adaptation=rerun and stage == "adapt",
            )
    except CreditReservationDenied as denied:
        # Estimation defects share this boundary; only a balance shortfall is a credit block.
        if denied.insufficient_credits:
            capture_server_event("credit_blocked", user_id=user_id, project_id=project_id, properties={"stage": stage})
        if not rerun:
            fail_stage(state, stage, denied.message, detail=denied.detail)
            save_state(state, project_dir)
        event = {
            "type": "stage_fail",
            "stage": stage,
            "message": denied.message,
        }
        if denied.detail:
            event.update(denied.detail)
        queue.put_nowait(event)
        capture_lifecycle(app, "stage_failed", attempt_id, user_id=user_id, project_id=project_id,
                          properties={"stage": stage, "outcome": "blocked" if denied.insufficient_credits else "failed",
                                      "error_type": denied.error_type,
                                      "run_id": run_id, "attempt_id": attempt_id})
        return
    except Exception as exc:
        capture_lifecycle(app, "stage_failed", attempt_id, user_id=user_id, project_id=project_id,
                          properties={"stage": stage, "outcome": "failed", "error_type": type(exc).__name__,
                                      "run_id": run_id, "attempt_id": attempt_id})
        raise

    current = state.stages[stage]
    if inventory_before is not None and current.status == StageStatus.COMPLETE:
        reopen_cast_for_new_inventory(series_root(project_dir), inventory_before)
    outcome = (
        "failed"
        if current.status == StageStatus.FAILED
        else (
            "awaiting_review"
            if current.status == StageStatus.AWAITING_REVIEW
            else "succeeded"
        )
    )
    if stage == "draw" and outcome != "failed":
        outcome = "dispatched"
    capture_lifecycle(
        app, ("stage_dispatched" if stage == "draw" and outcome != "failed" else f"stage_{'failed' if outcome == 'failed' else 'succeeded'}"), attempt_id,
        user_id=user_id,
        project_id=project_id,
        job_id=job_id,
        properties={**stage_properties(current, stage, outcome),
                    "latency_ms": round((time.perf_counter() - started) * 1000),
                    **({"error_type": current.error_code or "stage_error"} if outcome == "failed" else {})},
    )
    increment("canary_stage_runs_total", stage=stage, outcome=outcome)
    observe(
        "canary_stage_duration_seconds",
        time.perf_counter() - started,
        stage=stage,
        outcome=outcome,
    )
    metric_attributes = {"stage": stage, "outcome": outcome}
    metric_count("pipeline.stage_runs", attributes=metric_attributes)
    metric_histogram(
        "pipeline.stage_duration",
        (time.perf_counter() - started) * 1000,
        unit="ms",
        attributes=metric_attributes,
    )
    if (
        stage == "draw"
        and current.status in {StageStatus.RUNNING, StageStatus.COMPLETE, StageStatus.AWAITING_REVIEW}
        and request is not None
        and project_id is not None
    ):
        from .projects import enqueue_project_cover, needs_initial_project_cover

        if needs_initial_project_cover(request, project_key(user_id, project_id), project_dir):
            try:
                enqueue_project_cover(request, project_id, (project_dir, config, state), user_id)
            except Exception:
                # A cover is auxiliary and queues only after Draw starts.
                logger.exception("Could not queue project cover after Draw project=%s", project_id)
    if current.status != StageStatus.COMPLETE:
        return
    for next_stage in STAGE_AUTO_CHAIN.get(stage, ()):
        _reset_missing_auto_chain_artifact(next_stage, project_dir, state)
        if state.stages[next_stage].status != StageStatus.PENDING:
            continue
        await _run_stage_with_credits(
            next_stage,
            config,
            project_dir,
            state,
            queue,
            user_id,
            project_id,
            rerun=False,
            request=request,
        )
        if state.stages[next_stage].status != StageStatus.COMPLETE:
            break


def _enqueue_pipeline(app, pkey, user_id, project_id, project_dir, config, stage,
                      *, rerun=False, queue_pages=False):
    from ..generation_jobs import enqueue_generation_job
    from ..job_commands import command
    descriptor = command("pipeline", project_dir, config, rerun=rerun, queue_pages=queue_pages)
    descriptor = descriptor.model_copy(update={"stage": stage, "user_id": user_id, "project_id": project_id})
    return enqueue_generation_job(app, pkey, "pipeline_stage", stage,
                                  {"stage": stage}, None, user_id=user_id, command=descriptor)


async def _run_job(
    pkey: str,
    user_id: str,
    request: Request,
    job,
    channel_key: str | None = None,
) -> None:
    try:
        from ..generation_jobs import user_generation_semaphore

        async with user_generation_semaphore(request.app, user_id):
            await job
    finally:
        queue = request.app.state.event_queues.get(channel_key or pkey)
        if queue is not None:
            queue.put_nowait({"type": "pipeline_done"})
        request.app.state.running_tasks.pop(pkey, None)


def _reset_stage_and_downstream(state, stage: str) -> None:
    for name in STATE_INVALIDATION[stage]:
        state.stages[name] = StageState()


def _clear_outputs_for_rerun(project_dir, stage: str) -> None:
    from novel_to_comic.artifact_lock import production_lock

    with production_lock(project_dir):
        if stage in {"adapt", "plan"}:
            TargetArtifacts(project_dir).archive_stage_work(stage)
            return
        if stage == "extract":
            from novel_to_comic.series import withdraw_for_reextraction

            # A part re-extracts by withdrawing only its own additions.
            withdraw_for_reextraction(project_dir)
        stage_obj = REGISTRY.get(stage)
        if stage_obj is None:
            return
        for path in stage_obj.clean_paths(project_dir):
            if path.is_dir():
                shutil.rmtree(path)
            elif path.exists():
                path.unlink()


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
    return {
        "stage": stage,
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


async def _start_stage(
    request: Request,
    project_id: str,
    stage: Optional[str],
    rerun: bool,
    project,
    user_id: str,
    queue_pages: bool = False,
    confirmed_archive_pages: int | None = None,
):
    if stage is None:
        raise HTTPException(400, "stage parameter is required")
    if stage not in STAGE_NAMES:
        raise HTTPException(400, f"Unknown stage: {stage}. Valid: {STAGE_NAMES}")
    scope = stage_scope(request, project, stage)
    project_dir, config, state = scope.directory, scope.config, scope.state
    admit_stage_action(config, stage)
    if stage == "draw":
        from .pages import prepare_undrawn_pages

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

    if stage != "draw":
        try:
            if rerun and stage == "adapt":
                required = estimate_adaptation_restart(config, project_dir, state)["reserved_credits"] or 0
            else:
                required = estimate_stage_credit_reservation(config, project_dir, state, stage)
        except MissingVisualAnchor as exc:
            raise HTTPException(409, str(exc)) from exc
        assert_sufficient_credits(get_db(), user_id, required, stage=stage)
    queue = EventChannel()
    request.app.state.event_queues[event_key(pkey, project_dir)] = queue
    if getattr(request.app.state, "durable_queue_required", False) is True:
        admitted = _enqueue_pipeline(request.app, pkey, user_id, project_id, project_dir,
                                     config, stage, rerun=rerun, queue_pages=queue_pages)
        return {"status": "started", "stage": stage, "job": generation_job_payload(request.app, admitted)}
    job = _run_stage_with_credits(
        stage,
        config,
        project_dir,
        state,
        queue,
        user_id,
        project_id,
        rerun=rerun,
        request=request,
        queue_draw_pages=stage == "draw" and queue_pages,
    )
    task = asyncio.create_task(_run_job(pkey, user_id, request, job, event_key(pkey, project_dir)))
    request.app.state.running_tasks[pkey] = task
    return {"status": "started", "stage": stage}


@router.post("/run")
@limiter.limit(cost_limit)
async def run_pipeline(
    request: Request,
    project_id: str,
    stage: Optional[str] = Query(None),
    rerun: bool = Query(False),
    queue_pages: bool = Query(False),
    confirmed_archive_pages: int | None = Query(None, ge=0),
    project=Depends(get_project),
    user_id: str = Depends(get_current_user),
):
    return await _start_stage(
        request,
        project_id,
        stage,
        rerun,
        project,
        user_id,
        queue_pages,
        confirmed_archive_pages,
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


@router.post("/regen-extract")
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


@router.post("/jobs/cancel-queued-pages")
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
    ids: list[str] | None = Query(None),
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
        for job in request.app.state.generation_jobs.values()
        if job.project_name == pkey and (ids is None or job.id in ids)
        and visible(job_part_id(job))
    ]
    jobs.sort(key=lambda job: job.sequence)
    from ..generation_jobs import recovered_generation_jobs

    recovered = [
        job for job in recovered_generation_jobs(request.app, pkey)
        if (ids is None or job["id"] in ids) and visible(job.get("part_id"))
    ]
    payloads = recovered + [generation_job_payload(request.app, job) for job in jobs]
    _mark_current_page_jobs(TargetArtifacts(project[0]), payloads, {
        job.id: job.command.arguments["request"]
        for job in jobs
        if job.command is not None and job.command.operation == "page_draw"
        and "request" in job.command.arguments
    })
    return {"jobs": payloads}


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


def _ready_for_adapt(
    part_dir: Path, part_state: PipelineState | None = None, *, approving: str | None = None,
) -> bool:
    """Whether a part can start Adapt once the ``approving`` stage is approved."""
    part_state = part_state or load_state(part_dir)
    approved = {
        name: approving == name or part_state.stages[name].status == StageStatus.COMPLETE
        for name in ("brief", "cast")
    }
    return (
        approved["brief"]
        and approved["cast"]
        and part_state.stages["adapt"].status == StageStatus.PENDING
        and part_order_blocker(part_dir, "adapt") is None
    )


def _part_to_adapt_after(scope: StageScope, stage: str) -> Path | None:
    """The part whose Adapt this approval unblocks, if any.

    Approving a part's Brief starts its Adapt when Cast is already approved.
    Approving Cast starts the addressed part, or else the earliest part that
    is waiting, so parts keep adapting in reading order.
    """
    if stage == "brief" and scope.part_dir is not None:
        ready = _ready_for_adapt(scope.part_dir, scope.gate, approving=stage)
        return scope.part_dir if ready else None
    if stage == "cast":
        if scope.part_dir is not None and _ready_for_adapt(scope.part_dir, scope.gate, approving=stage):
            return scope.part_dir
        return next((part for part in part_workspaces(scope.directory)
                     if part != scope.part_dir and _ready_for_adapt(part, approving=stage)), None)
    return None


@router.post("/approve/{stage}")
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
        running = request.app.state.running_tasks.get(pkey)
        if running is not None and not running.done():
            raise HTTPException(409, "A stage is already running for this project")
        queue = EventChannel()
        request.app.state.event_queues[event_key(pkey, adapt_part)] = queue
        if getattr(request.app.state, "durable_queue_required", False) is True:
            _enqueue_pipeline(request.app, pkey, user_id, project_id, adapt_part, config, "adapt")
        else:
            job = _run_stage_with_credits(
                "adapt",
                config,
                adapt_part,
                load_state(adapt_part),
                queue,
                user_id,
                project_id,
            )
            task = asyncio.create_task(_run_job(pkey, user_id, request, job, event_key(pkey, adapt_part)))
            request.app.state.running_tasks[pkey] = task
        response["auto_started"] = "adapt"
        response["auto_started_part"] = adapt_part.name
    return response


@router.post("/reset/{stage}")
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
