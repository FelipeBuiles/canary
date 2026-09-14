"""Couples credit guarantees with the two shapes of credited work.

Generation jobs reserve before publication and release after settlement or
cancellation. The common reserved lifecycle owns this guarantee for every
queued paid request.

Stage runs: ``run_credited_stage`` owns the reserve → run → release dance.
Per-call debits land in the AI client as each API call returns (see
ai.client._settle_event_usage); the reservation is only an authorization hold
and is released after work and settlement; ambiguous settlement retains its hold.
"""

import asyncio
from collections.abc import Awaitable, Callable
from functools import wraps
from pathlib import Path
from threading import RLock
from weakref import WeakValueDictionary
from typing import Any

from fastapi import FastAPI

from novel_to_comic.ai import ai_request_context
from novel_to_comic.config import Config
from novel_to_comic.codex_dev import classify_operations
from .codex_admission import Operations, stage_operations
from novel_to_comic.frozen_requests import (
    FrozenRequestError,
    execute_frozen_request,
    submit_frozen_request,
    update_frozen_request_status,
)
from novel_to_comic.provider_wire import ProviderWireRequest
from novel_to_comic.state import PipelineState
from novel_to_comic.usage import ApiResult

from .credits import (
    assert_reservation_active,
    debit_model_usage,
    estimate_adaptation_restart,
    estimate_stage_credit_reservation,
    release_reservation,
    reserve_credits,
)
from .db import get_db
from .generation_jobs import (
    GenerationJob,
    enqueue_generation_job,
    find_active_generation_job,
    prune_finished_generation_jobs,
)


_FROZEN_ENQUEUE_LOCK = RLock()


def _serialize_frozen_enqueue(function: Callable[..., Any]) -> Callable[..., Any]:
    @wraps(function)
    def wrapped(*args: Any, **kwargs: Any) -> Any:
        with _FROZEN_ENQUEUE_LOCK:
            return function(*args, **kwargs)

    return wrapped


class CreditReservationDenied(Exception):
    """A stage's credit reservation could not be placed.

    ``detail`` carries the structured 402 payload (when the cause was
    insufficient credits) so callers can surface balance/shortfall numbers.
    """

    def __init__(self, message: str, detail: dict | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.detail = detail


async def run_credited_stage(
    *,
    user_id: str,
    project_id: str | None,
    project_dir: Path,
    config: Config,
    state: PipelineState,
    stage: str,
    run: Callable[[], Awaitable[None]],
    fresh_adaptation: bool = False,
) -> str:
    """Reserve credits for a stage, run it inside an ai_request_context, release the hold.

    Raises CreditReservationDenied when the reservation cannot be placed
    (insufficient credits or ledger errors); the stage is not started.
    """
    classify_operations(stage_operations(config, stage))
    db = get_db()
    try:
        if fresh_adaptation:
            if stage != "adapt":
                raise ValueError("Only Adapt supports a fresh adaptation reservation")
            reservation_credits = estimate_adaptation_restart(config, project_dir, state)["reserved_credits"] or 0
        else:
            reservation_credits = estimate_stage_credit_reservation(config, project_dir, state, stage)
        reservation_id, job_id = reserve_credits(db, user_id, project_id, stage, reservation_credits)
    except Exception as exc:
        detail = getattr(exc, "detail", None)
        if isinstance(detail, str):
            message = detail
        elif isinstance(detail, dict):
            message = str(detail.get("message") or detail.get("error") or exc)
        else:
            message = str(exc)
        raise CreditReservationDenied(
            message, detail if isinstance(detail, dict) else None
        ) from exc

    try:
        assert_reservation_active(db, reservation_id)
        with ai_request_context(
            user_id=user_id,
            project_id=project_id,
            project_name=project_dir.name,
            workspace_id=str(project_dir.parent),
            stage=stage,
            job_id=job_id,
        ):
            await run()
        return job_id
    finally:
        if reservation_id:
            release_reservation(db, reservation_id)


def enqueue_credited_job(
    app: FastAPI,
    *,
    project_name: str,
    user_id: str,
    project_id: str | None,
    project_dir: Path,
    stage: str,
    kind: str,
    label: str,
    payload: dict[str, Any],
    work: Callable[[], Awaitable[ApiResult[Any]]],
    debit_description: str,
    operations: Operations,
    semaphore: asyncio.Semaphore | None = None,
    estimate_credits: int = 0,
) -> tuple[GenerationJob, bool]:
    """Find or create a generation job backed by a credit guarantee.

    Atomically reserves the estimate before queue publication. If a matching
    job is already active, returns it without another hold. The runner executes
    under the reservation's billing context and settles every returned usage.

    Returns ``(job, created)`` so the caller can tell if this was a dedup hit.
    """
    async def _work() -> ApiResult[Any]:
        result = await work()
        # Remove successfully regenerated item from items_failed if it exists
        try:
            from novel_to_comic.state import load_state, save_state
            state_obj = load_state(project_dir)
            stage_state = state_obj.stages.get(stage)
            if stage_state:
                item_id = None
                if stage == "cast":
                    if kind == "character_ref_regen":
                        item_id = payload.get("char_id")
                    elif kind == "location_plate_regen":
                        item_id = payload.get("loc_id")
                    elif kind == "prop_ref_regen":
                        item_id = payload.get("prop_id")
                elif stage == "draw":
                    page_number = payload.get("page_number")
                    if page_number is not None:
                        item_id = f"page_{int(page_number):03d}"

                if item_id and item_id in stage_state.items_failed:
                    stage_state.items_failed.remove(item_id)
                    stage_state.items_done = min(stage_state.items_total, stage_state.items_done + 1)
                    save_state(state_obj, project_dir)
        except Exception:
            import logging
            logging.getLogger("canary.credited_job").exception(
                "Failed to remove regenerated item from items_failed for stage %s",
                stage
            )
        return result

    return enqueue_reserved_generation_job(
        app, project_name=project_name, user_id=user_id,
        project_id=project_id, project_dir=project_dir, stage=stage,
        kind=kind, label=label, payload=payload, work=_work,
        debit_description=debit_description, semaphore=semaphore,
        reservation_credits=estimate_credits,
        operations=operations,
    )


@_serialize_frozen_enqueue
def enqueue_reserved_generation_job(
    app: FastAPI,
    *,
    project_name: str,
    user_id: str,
    project_id: str | None,
    project_dir: Path,
    stage: str,
    kind: str,
    label: str,
    payload: dict[str, Any],
    work: Callable[[], Awaitable[ApiResult[Any] | None]],
    debit_description: str,
    reservation_credits: int,
    operations: Operations,
    semaphore: asyncio.Semaphore | None = None,
    existing_hold: tuple[str | None, str] | None = None,
    on_terminal: Callable[[], None] | None = None,
    on_settled: Callable[[ApiResult[Any]], None] | None = None,
) -> tuple[GenerationJob, bool]:
    """Queue one request with a hold spanning execution, failure, or cancellation."""
    funding = classify_operations(operations)
    if funding == "codex_subscription":
        reservation_credits = 0
        if existing_hold is not None and existing_hold[0] is not None:
            raise ValueError("Subscription jobs cannot inherit an API credit hold")

    existing = find_active_generation_job(
        app,
        project_name=project_name,
        kind=kind,
        payload=payload,
    )
    if existing is not None:
        try:
            if existing_hold is not None and existing_hold[0] is not None:
                release_reservation(get_db(), existing_hold[0])
        finally:
            if on_terminal is not None:
                on_terminal()
        return existing, False

    db = get_db()
    reservation_id, ledger_job_id = existing_hold if existing_hold is not None else reserve_credits(
        db, user_id, project_id, stage, reservation_credits,
    )
    cleaned_up = False

    def _cleanup() -> None:
        nonlocal cleaned_up
        if cleaned_up:
            return
        cleaned_up = True
        try:
            if reservation_id is not None:
                release_reservation(db, reservation_id)
        finally:
            if on_terminal is not None:
                on_terminal()

    async def _runner() -> None:
        try:
            assert_reservation_active(db, reservation_id)
            with ai_request_context(
                user_id=user_id,
                project_id=project_id,
                project_name=project_dir.name,
                workspace_id=str(project_dir.parent),
                stage=stage,
                job_id=ledger_job_id,
                page_number=payload.get("page_number"),
                is_correction=bool(payload.get("issue_ids") or payload.get("issue_id")),
            ):
                result = await work()
            # Some multi-call operations settle each provider call themselves.
            if result is None:
                return
            # Every provider call this job made is settled under the same
            # ledger job, which keeps one audit row per call while rounding
            # whole credits once for the job as a whole.
            for usage in (result.usage, *result.additional_usage):
                if usage is None:
                    continue
                debit_model_usage(
                    get_db(),
                    user_id,
                    project_id,
                    usage,
                    stage=stage,
                    description=debit_description,
                    job_id=ledger_job_id,
                )
            if on_settled is not None:
                on_settled(result)
        finally:
            _cleanup()

    try:
        prune_finished_generation_jobs(app)
        job = enqueue_generation_job(
            app,
            project_name=project_name,
            kind=kind,
            label=label,
            payload=payload,
            runner=_runner,
            user_id=user_id,
            semaphore=semaphore,
            on_cancel=_cleanup,
        )
    except BaseException:
        _cleanup()
        raise
    return job, True


@_serialize_frozen_enqueue
def enqueue_frozen_generation_job(
    app: FastAPI,
    *,
    project_name: str,
    user_id: str,
    project_id: str | None,
    project_dir: Path,
    config: Config,
    stage: str,
    kind: str,
    label: str,
    payload: dict[str, Any],
    wire: ProviderWireRequest,
    output_path: Path,
    debit_description: str,
    operations: Operations,
    idempotency_key: str | None = None,
    feature: str = "image.frozen_request",
    semaphore: asyncio.Semaphore | None = None,
    estimate_credits: int = 0,
    request_context: dict[str, Any] | None = None,
    on_complete: Callable[[ApiResult[Any], Any], Awaitable[None] | None] | None = None,
    on_failure: Callable[[BaseException, Any], Awaitable[None] | None] | None = None,
) -> tuple[GenerationJob, bool]:
    """Freeze a wire request before publishing a credited image job.

    The job payload carries only the frozen request id and the caller's
    diagnostic payload.  Its runner loads the persisted manifest at execution
    time; it never receives a prompt builder, reference plan, or mutable asset
    path as a source of provider input.
    """
    classify_operations(operations)
    try:
        output_path.resolve(strict=False).relative_to(project_dir.resolve())
    except ValueError as exc:
        raise FrozenRequestError("frozen generation output must stay project-scoped") from exc

    try:
        output_key = str(output_path.resolve().relative_to(project_dir.resolve()))
    except ValueError:
        output_key = output_path.name
    effective_idempotency_key = idempotency_key or (
        f"{kind}:{output_key}:{wire.execution_fingerprint}"
    )

    frozen = submit_frozen_request(
        project_dir,
        wire,
        idempotency_key=effective_idempotency_key,
        request_context=request_context,
    )
    job_payload = {
        **payload,
        "frozen_request_id": frozen.request_id,
        "execution_fingerprint": frozen.execution_fingerprint,
    }

    existing_job = find_active_generation_job(
        app, project_name=project_name, kind=kind, payload=job_payload,
    )
    if existing_job is not None:
        return existing_job, False

    if frozen.status in {"complete", "retained", "failed"} and frozen.job_id:
        existing_jobs = app.state.generation_jobs
        recorded_job = existing_jobs.get(frozen.job_id)
        if recorded_job is not None:
            if (
                recorded_job.project_name != project_name
                or recorded_job.kind != kind
                or recorded_job.payload != job_payload
            ):
                raise FrozenRequestError("frozen request job id belongs to another job")
            return recorded_job, False

        # Finished requests remain idempotent even after the in-memory queue
        # prunes their GenerationJob object.  Return a read-only completion
        # record instead of charging the same provider request again.
        from datetime import UTC, datetime

        from .generation_jobs import GenerationJob

        async def _already_finished() -> ApiResult[Any]:
            return ApiResult(value=output_path)

        completed = GenerationJob(
            id=frozen.job_id,
            project_name=project_name,
            kind=kind,
            label=label,
            payload=job_payload,
            sequence=0,
            runner=_already_finished,
            status="complete" if frozen.status in {"complete", "retained"} else "failed",
            finished_at=datetime.now(UTC),
        )
        existing_jobs[completed.id] = completed
        return completed, False

    async def _work() -> ApiResult[Any]:
        try:
            result = await execute_frozen_request(
                project_dir=project_dir,
                request_id=frozen.request_id,
                config=config,
                output_path=output_path,
                feature=feature,
            )
        except BaseException as exc:
            if on_failure is not None:
                try:
                    callback_result = on_failure(exc, frozen)
                    if callback_result is not None:
                        await callback_result
                except Exception:
                    import logging
                    logging.getLogger("canary.credited_job").exception(
                        "Panel failure provenance persistence failed"
                    )
            raise
        if on_complete is not None:
            try:
                callback_result = on_complete(result, frozen)
                if callback_result is not None:
                    await callback_result
            except Exception:
                import logging
                logging.getLogger("canary.credited_job").exception(
                    "Panel result provenance persistence failed"
                )
        return result

    job, created = enqueue_credited_job(
        app,
        project_name=project_name,
        user_id=user_id,
        project_id=project_id,
        project_dir=project_dir,
        stage=stage,
        kind=kind,
        label=label,
        payload=job_payload,
        work=_work,
        debit_description=debit_description,
        semaphore=semaphore,
        estimate_credits=estimate_credits,
        operations=operations,
    )
    if created:
        update_frozen_request_status(
            project_dir, frozen.request_id, "queued", job_id=job.id,
        )
    return job, created


_PAGE_CHECK_LOCKS: WeakValueDictionary = WeakValueDictionary()


def page_operation_lock(project_dir: Path, page_number: int) -> asyncio.Lock:
    """Serialize saved-pixel checks with rendering for the same page."""
    key = (str(project_dir.resolve()), page_number)
    return _PAGE_CHECK_LOCKS.setdefault(key, asyncio.Lock())


async def run_credited_page_check(*, user_id: str, project_id: str, project_dir: Path,
                                  page_number: int, estimated_cost_usd: float,
                                  work: Callable[[], Awaitable[Any]],
                                  operations: Operations,
                                  cached_work: Callable[[], Any] | None = None) -> Any:
    """Run a synchronous page-check endpoint under a releasable credit hold."""
    from .credits import credit_estimate_for_provider_cost

    lock = page_operation_lock(project_dir, page_number)
    async with lock:
        if cached_work is not None:
            cached = cached_work()
            if cached is not None:
                return cached
        funding = classify_operations(operations)
        db = get_db()
        estimate = credit_estimate_for_provider_cost(estimated_cost_usd, 'draw', reserve=True, funding=funding)
        reservation, job_id = reserve_credits(db, user_id, project_id, 'draw', estimate["reserved_credits"] or 0)
        try:
            assert_reservation_active(db, reservation)
            with ai_request_context(user_id=user_id, project_id=project_id,
                                    project_name=project_dir.name, stage='draw', job_id=job_id,
                                    page_number=page_number):
                return await work()
        finally:
            if reservation:
                release_reservation(db, reservation)
