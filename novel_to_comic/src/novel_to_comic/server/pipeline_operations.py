"""Application operations independent of HTTP routing."""

from __future__ import annotations
import asyncio
import logging
import shutil
import time
import traceback
import uuid
from pathlib import Path
from typing import NamedTuple
from fastapi import HTTPException, Request
from novel_to_comic.briefing import require_approved_brief
from novel_to_comic.stage_runtime import StageRuntime
from novel_to_comic.stages import REGISTRY
from novel_to_comic.state import (
    PART_STAGES,
    PipelineState,
    StageState,
    StageStatus,
    approve_stage,
    fail_stage,
    load_state,
    save_state,
)
from novel_to_comic.target_artifacts import (
    ArtifactInvalid,
    ArtifactMissing,
    TargetArtifacts,
)
from novel_to_comic.series import cast_inventory_keys, reopen_cast_for_new_inventory
from novel_to_comic.workspace import part_id_for_path, part_workspaces, series_root
from .credited_job import CreditReservationDenied, run_credited_stage
from .codex_admission import admit_stage_action
from .deps import event_key, project_key
from .event_channel import EventChannel
from .generation_jobs import generation_jobs_snapshot
from .metrics import increment, observe
from .telemetry import metric_count, metric_histogram
from .product_events import capture_server_event
from .lifecycle_events import capture as capture_lifecycle, stage_properties
from .telemetry import context_fields

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


def _wrap_on_event(queue: asyncio.Queue, observe=None):
    def handler(event: dict) -> None:
        queue.put_nowait(event)
        if observe is not None:
            observe(event)

    return handler


def _cold_open_observer(app, user_id: str, project_id: str | None, part_dir: Path, config):
    """Admit the Cold Open when Extract announces it has read the book's opening."""
    def observe(event: dict) -> None:
        if event.get("type") == "stage_snapshot" and "opening" in (event.get("snapshot") or {}):
            from .cold_open_jobs import start_cold_open

            start_cold_open(app, user_id=user_id, project_id=project_id, part_dir=part_dir, config=config)

    return observe


async def _run_stage(
    stage: str,
    config,
    project_dir,
    state,
    queue: asyncio.Queue,
    *_unused,
    user_id: str | None = None,
    observe=None,
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
            on_event=_wrap_on_event(queue, observe),
        )
        with ctx.image_previews():
            await stage_obj.run(config, project_dir, ctx)
    except Exception as exc:
        from novel_to_comic.text_utils import clean_exception_message

        message = clean_exception_message(exc)
        from .diagnostics import local_diagnostics_enabled, record_diagnostic

        error_detail = traceback.format_exc() if local_diagnostics_enabled() else None
        if state.stages[stage].status != StageStatus.FAILED:
            fail_stage(
                state,
                stage,
                message,
                detail=exc.detail if isinstance(exc, HTTPException) and isinstance(exc.detail, dict) else None,
                error_detail=error_detail,
            )
            save_state(state, project_dir)
            queue.put_nowait({"type": "stage_fail", "stage": stage, "message": message,
                              "error_code": state.stages[stage].error_code})
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
        from .telemetry import capture_exception

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
    if (
        expected is not None
        and not expected.exists()
        and state.stages[stage].status
        in {StageStatus.COMPLETE, StageStatus.AWAITING_REVIEW}
    ):
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
    approve_part: str | None = None,
    chain_sponsor: str | None = None,
    **_unused_kwargs,
) -> None:
    admit_stage_action(config, stage)
    # Set when this run is Canary-paid, so the stage it auto-chains is too.
    sponsor: str | None = None
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
                "adapt",
                config,
                project_dir,
                state,
                queue,
                user_id,
                project_id,
                rerun=False,
                request=request,
            )
            return
    if request is not None:
        from .generation_jobs import persist_generation_job

        for active in generation_jobs_snapshot(request.app):
            if (
                active.project_name == project_key(user_id, project_id)
                and active.kind == "pipeline_stage"
                and active.status == "running"
            ):
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
            for active in generation_jobs_snapshot(app):
                if active.id == run_id:
                    active.payload.update(run_id=run_id, stage_attempt_id=attempt_id)
                    persist_generation_job(app, active)

    async def execute():
        # The credited wrapper invokes this only after acquiring the hold.
        if rerun:
            await asyncio.to_thread(_clear_outputs_for_rerun, project_dir, stage)
            _reset_stage_and_downstream(state, stage)
        correlate()
        capture_lifecycle(
            app,
            "stage_started",
            attempt_id,
            user_id=user_id,
            project_id=project_id,
            properties={
                "stage": stage,
                "rerun": rerun,
                "run_id": run_id,
                "attempt_id": attempt_id,
            },
        )
        observe = (_cold_open_observer(app, user_id, project_id, project_dir, config)
                   if stage == "extract" and app is not None else None)
        await _run_stage(stage, config, project_dir, state, queue, user_id=user_id, observe=observe)

    try:
        if stage == "draw":
            if not rerun:
                await execute()
            else:
                correlate()
                capture_lifecycle(
                    app,
                    "stage_started",
                    attempt_id,
                    user_id=user_id,
                    project_id=project_id,
                    properties={
                        "stage": stage,
                        "rerun": True,
                        "run_id": run_id,
                        "attempt_id": attempt_id,
                    },
                )
            if queue_draw_pages or rerun:
                if request is None or project_id is None:
                    raise ValueError("queueing Draw pages requires an active request")
                from .page_operations import enqueue_all_undrawn_pages

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
                from .page_operations import _sync_draw_progress

                await asyncio.to_thread(_sync_draw_progress, project_dir, request.app)
            job_id = None
        else:
            from .cold_open_jobs import free_opening_sponsor

            # A free Extract auto-chains Brief. An account without credits would
            # fail there, so Canary pays for that one chained Brief as well.
            sponsor = (free_opening_sponsor(project_dir, state, project_id, stage, rerun=rerun, claim=True)
                       or (chain_sponsor if stage in STAGE_AUTO_CHAIN.get("extract", ()) and not rerun else None))
            job_id = await run_credited_stage(
                sponsor=sponsor,
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
            capture_server_event(
                "credit_blocked",
                user_id=user_id,
                project_id=project_id,
                properties={"stage": stage},
            )
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
        capture_lifecycle(
            app,
            "stage_failed",
            attempt_id,
            user_id=user_id,
            project_id=project_id,
            properties={
                "stage": stage,
                "outcome": "blocked" if denied.insufficient_credits else "failed",
                "error_type": denied.error_type,
                "run_id": run_id,
                "attempt_id": attempt_id,
            },
        )
        return
    except Exception as exc:
        capture_lifecycle(
            app,
            "stage_failed",
            attempt_id,
            user_id=user_id,
            project_id=project_id,
            properties={
                "stage": stage,
                "outcome": "failed",
                "error_type": type(exc).__name__,
                "run_id": run_id,
                "attempt_id": attempt_id,
            },
        )
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
        app,
        (
            "stage_dispatched"
            if stage == "draw" and outcome != "failed"
            else f"stage_{'failed' if outcome == 'failed' else 'succeeded'}"
        ),
        attempt_id,
        user_id=user_id,
        project_id=project_id,
        job_id=job_id,
        properties={
            **stage_properties(current, stage, outcome),
            "latency_ms": round((time.perf_counter() - started) * 1000),
            **(
                {"error_type": current.error_code or "stage_error"}
                if outcome == "failed"
                else {}
            ),
        },
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
        and current.status
        in {StageStatus.RUNNING, StageStatus.COMPLETE, StageStatus.AWAITING_REVIEW}
        and request is not None
        and project_id is not None
    ):
        from .cover_operations import enqueue_project_cover, needs_initial_project_cover

        if needs_initial_project_cover(
            request, project_key(user_id, project_id), project_dir
        ):
            try:
                await enqueue_project_cover(
                    request, project_id, (project_dir, config, state), user_id
                )
            except Exception:
                # A cover is auxiliary and queues only after Draw starts.
                logger.exception(
                    "Could not queue project cover after Draw project=%s", project_id
                )
    if (
        stage == "cast"
        and approve_part
        and current.status == StageStatus.AWAITING_REVIEW
    ):
        adapt_part = _approve_cast_after_run(
            config, project_dir, state, Path(approve_part)
        )
        if adapt_part is not None:
            # The part's Adapt reports on the part's own channel, as the approve endpoint's does.
            channel = (
                queue
                if request is None
                else request.app.state.event_queues.setdefault(
                    event_key(project_key(user_id, project_id), adapt_part),
                    EventChannel(),
                )
            )
            await _run_stage_with_credits(
                "adapt",
                config,
                adapt_part,
                load_state(adapt_part),
                channel,
                user_id,
                project_id,
                request=request,
            )
        return
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
            chain_sponsor=sponsor,
        )
        if state.stages[next_stage].status != StageStatus.COMPLETE:
            break


def _approve_cast_after_run(
    config, series_dir: Path, state, part_dir: Path
) -> Path | None:
    """Approve Cast when the run the author asked to continue left nothing to review.

    "Continue" after corrections re-runs only the identity review. When it
    passes, the author has nothing left to look at, so Cast is approved as the
    approve endpoint would, and the part whose Adapt that unblocks is returned
    for the same explicit auto-chain. Anything still blocking leaves Cast
    awaiting review, where the room shows why.
    """
    from novel_to_comic.stages.s3_cast import cast_approval_blocker

    try:
        if cast_approval_blocker(config, series_dir, state.stages["cast"]):
            return None
        require_approved_brief(TargetArtifacts(part_dir).read_brief())
        part_state = load_state(part_dir)
        adapt_part = _part_to_adapt_after(
            StageScope(series_dir, config, state, part_state, part_dir), "cast"
        )
        if adapt_part is not None:
            admit_stage_action(config, "adapt")
        approve_stage(state, "cast")
    except (
        ArtifactMissing,
        ArtifactInvalid,
        ValueError,
        FileNotFoundError,
        HTTPException,
    ) as exc:
        logger.info(
            "Cast left for review after its run project=%s reason=%s",
            series_dir.name,
            exc,
        )
        return None
    save_state(state, series_dir)
    from novel_to_comic import runware_prefetch

    runware_prefetch.start(config, series_dir)
    return adapt_part


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


def _ready_for_adapt(
    part_dir: Path,
    part_state: PipelineState | None = None,
    *,
    approving: str | None = None,
) -> bool:
    """Whether a part can start Adapt once the ``approving`` stage is approved."""
    part_state = part_state or load_state(part_dir)
    approved = {
        name: approving == name
        or part_state.stages[name].status == StageStatus.COMPLETE
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
        if scope.part_dir is not None and _ready_for_adapt(
            scope.part_dir, scope.gate, approving=stage
        ):
            return scope.part_dir
        return next(
            (
                part
                for part in part_workspaces(scope.directory)
                if part != scope.part_dir and _ready_for_adapt(part, approving=stage)
            ),
            None,
        )
    return None
