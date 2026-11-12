"""Credit authorization for stages, checks, and durable command admission.

Queued work reserves at execution through job_execution, never at admission.

Stage runs: ``run_credited_stage`` owns the reserve → run → release dance.
Per-call debits land in the AI client as each API call returns (see
ai.client._settle_event_usage); the reservation is only an authorization hold
and is released after work and settlement; ambiguous settlement retains its hold.
"""

import asyncio
from collections.abc import Awaitable, Callable
from pathlib import Path
from weakref import WeakValueDictionary
from typing import Any

from fastapi import FastAPI, HTTPException

from novel_to_comic.ai import ai_request_context
from novel_to_comic.config import Config
from novel_to_comic.codex_dev import classify_operations, is_subscription
from .codex_admission import Operations, stage_operations
from novel_to_comic.state import PipelineState

from .credits import (
    assert_reservation_active,
    assert_sufficient_credits,
    estimate_adaptation_restart,
    estimate_stage_credit_reservation,
    release_reservation,
    reserve_credits,
)
from .async_credits import ledger_call, release_unstarted_hold
from .db import get_db
from .job_commands import JobCommand
from .generation_jobs import (
    GenerationJob,
    enqueue_generation_job,
    find_active_generation_job,
    prune_finished_generation_jobs,
)


class CreditReservationDenied(Exception):
    """A stage's credit reservation could not be placed.

    ``detail`` carries the structured 402 payload (when the cause was
    insufficient credits) so callers can surface balance/shortfall numbers.
    """

    def __init__(self, message: str, detail: dict | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.detail = detail

    @property
    def insufficient_credits(self) -> bool:
        return bool(self.detail and self.detail.get("error") == "insufficient_credits")

    @property
    def error_type(self) -> str:
        """Telemetry label: a balance shortfall, or the defect that blocked the hold."""
        if self.insufficient_credits:
            return "insufficient_credits"
        return type(self.__cause__).__name__ if self.__cause__ is not None else "reservation_failed"


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
    sponsor: str | None = None,
) -> str:
    """Reserve credits for a stage, run it inside an ai_request_context, release the hold.

    Raises CreditReservationDenied when the reservation cannot be placed
    (insufficient credits or ledger errors); the stage is not started.
    """
    classify_operations(stage_operations(config, stage))
    db = get_db()
    try:
        if sponsor is not None:
            # Canary-paid: nothing is held, authorized or debited.
            reservation_credits = 0
        elif fresh_adaptation:
            if stage != "adapt":
                raise ValueError("Only Adapt supports a fresh adaptation reservation")
            reservation_credits = estimate_adaptation_restart(config, project_dir, state)["reserved_credits"] or 0
        else:
            reservation_credits = estimate_stage_credit_reservation(config, project_dir, state, stage)
        reservation_id, job_id = await ledger_call(reserve_credits, db, user_id, project_id, stage, reservation_credits, cancel_cleanup=lambda result: release_unstarted_hold(db, result))
    except Exception as exc:
        # Only insufficient balance is an expected product outcome. Estimation
        # defects and ledger failures also settle through CreditReservationDenied,
        # so report their original exception before that boundary loses it.
        if not isinstance(exc, HTTPException) or exc.status_code != 402:
            from .telemetry import capture_exception

            capture_exception(exc, user_id=user_id, stage=stage)
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
        await ledger_call(assert_reservation_active, db, reservation_id)
        with ai_request_context(
            user_id=user_id,
            project_id=project_id,
            project_name=project_dir.name,
            workspace_id=str(project_dir.parent),
            stage=stage,
            job_id=job_id,
            sponsor=sponsor,
        ):
            await run()
        return job_id
    finally:
        if reservation_id:
            await ledger_call(release_reservation, db, reservation_id)


async def enqueue_credited_job(app: FastAPI, *, project_name: str, user_id: str,
    project_id: str | None, project_dir: Path, stage: str, kind: str, label: str,
    payload: dict[str, Any], debit_description: str, operations: Operations,
    command: JobCommand, semaphore: asyncio.Semaphore | None = None,
    estimate_credits: int = 0) -> tuple[GenerationJob, bool]:
    return await enqueue_reserved_generation_job(app, project_name=project_name, user_id=user_id,
        project_id=project_id, project_dir=project_dir, stage=stage, kind=kind, label=label,
        payload=payload, debit_description=debit_description, operations=operations,
        command=command, semaphore=semaphore, reservation_credits=estimate_credits)


async def enqueue_reserved_generation_job(app: FastAPI, *, project_name: str, user_id: str,
    project_id: str | None, project_dir: Path, stage: str, kind: str, label: str,
    payload: dict[str, Any], debit_description: str, reservation_credits: int,
    operations: Operations, command: JobCommand,
    semaphore: asyncio.Semaphore | None = None) -> tuple[GenerationJob, bool]:
    """Admit one command; execution acquires and settles its own credit hold."""
    import uuid
    funding = classify_operations(operations)
    if is_subscription(funding):
        reservation_credits = 0
    existing = find_active_generation_job(app, project_name, kind, payload)
    if existing is not None:
        return existing, False
    await ledger_call(assert_sufficient_credits, get_db(), user_id, reservation_credits, action=kind)
    # Another admission may have finished during the credit read.
    existing = find_active_generation_job(app, project_name, kind, payload)
    if existing is not None:
        return existing, False
    spec = JobCommand.model_validate({**command.model_dump(),
        "stage": stage, "user_id": user_id, "project_id": project_id,
        "reservation_credits": reservation_credits, "ledger_job_id": str(uuid.uuid4()),
        "debit_description": debit_description})
    prune_finished_generation_jobs(app)
    job = enqueue_generation_job(app, project_name=project_name, kind=kind, label=label,
        payload=payload, runner=None, user_id=user_id, command=spec, semaphore=semaphore)
    return job, True


_PAGE_CHECK_LOCKS: WeakValueDictionary = WeakValueDictionary()


def page_operation_lock(project_dir: Path, page_number: int) -> asyncio.Lock:
    """Serialize saved-pixel checks with rendering for the same page."""
    key = (str(project_dir.resolve()), page_number)
    return _PAGE_CHECK_LOCKS.setdefault(key, asyncio.Lock())


async def run_credited_call(*, user_id: str, project_id: str, project_dir: Path, stage: str,
                            estimated_cost_usd: float, work: Callable[[], Awaitable[Any]],
                            operations: Operations, **context: Any) -> Any:
    """Run one synchronous model call under a releasable credit hold."""
    from .credits import credit_estimate_for_provider_cost

    funding = classify_operations(operations)
    db = get_db()
    estimate = credit_estimate_for_provider_cost(estimated_cost_usd, stage, reserve=True, funding=funding)
    reservation, job_id = await ledger_call(reserve_credits, db, user_id, project_id, stage, estimate["reserved_credits"] or 0, cancel_cleanup=lambda result: release_unstarted_hold(db, result))
    try:
        await ledger_call(assert_reservation_active, db, reservation)
        with ai_request_context(user_id=user_id, project_id=project_id,
                                project_name=project_dir.name, stage=stage, job_id=job_id, **context):
            return await work()
    finally:
        if reservation:
            await ledger_call(release_reservation, db, reservation)


async def run_credited_page_check(*, user_id: str, project_id: str, project_dir: Path,
                                  page_number: int, estimated_cost_usd: float,
                                  work: Callable[[], Awaitable[Any]],
                                  operations: Operations,
                                  cached_work: Callable[[], Any] | None = None) -> Any:
    """Run a synchronous page-check endpoint under a releasable credit hold."""
    lock = page_operation_lock(project_dir, page_number)
    async with lock:
        if cached_work is not None:
            cached = cached_work()
            if cached is not None:
                return cached
        return await run_credited_call(
            user_id=user_id, project_id=project_id, project_dir=project_dir, stage="draw",
            estimated_cost_usd=estimated_cost_usd, work=work, operations=operations, page_number=page_number,
        )
