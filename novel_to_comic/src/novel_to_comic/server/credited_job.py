"""Couples credit guarantees with the two shapes of credited work.

Generation jobs: each regen handler was doing the same dance — assert credits,
create a job_id, wrap the runner in ai_request_context + debit_model_usage,
check for an active duplicate, prune stale jobs, then enqueue.
``enqueue_credited_job`` owns that coupling so handlers shrink to payload
assembly + response formatting.

Stage runs: ``run_credited_stage`` owns the reserve → run → release dance.
Per-call debits land in the AI client as each API call returns (see
ai.client._settle_event_usage); the reservation is only an authorization hold
and is always released, so a crash mid-stage loses at most the in-flight call.
"""

import asyncio
import uuid as uuid_lib
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from fastapi import FastAPI

from novel_to_comic.ai import ai_request_context
from novel_to_comic.config import Config
from novel_to_comic.state import PipelineState
from novel_to_comic.usage import ApiResult

from .credits import (
    assert_sufficient_credits,
    debit_model_usage,
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
) -> None:
    """Reserve credits for a stage, run it inside an ai_request_context, release the hold.

    Raises CreditReservationDenied when the reservation cannot be placed
    (insufficient credits or ledger errors); the stage is not started.
    """
    db = get_db()
    try:
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
        with ai_request_context(
            user_id=user_id,
            project_id=project_id,
            project_name=project_dir.name,
            workspace_id=str(project_dir.parent),
            stage=stage,
            job_id=job_id,
        ):
            await run()
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
    semaphore: asyncio.Semaphore | None = None,
    estimate_credits: int = 0,
) -> tuple[GenerationJob, bool]:
    """Find or create a generation job backed by a credit guarantee.

    If ``estimate_credits`` is positive, raises 402 if the user cannot cover
    the estimate.  If a matching job is already active, returns it immediately
    (created=False).  Otherwise creates a new job whose runner calls ``work()``
    inside an ``ai_request_context`` and debits the resulting usage on success.

    Returns ``(job, created)`` so the caller can tell if this was a dedup hit.
    """
    if estimate_credits > 0:
        assert_sufficient_credits(get_db(), user_id, estimate_credits, action=kind)

    existing = find_active_generation_job(app, project_name=project_name, kind=kind, payload=payload)
    if existing:
        return existing, False

    job_id = str(uuid_lib.uuid4())

    async def _runner() -> None:
        with ai_request_context(
            user_id=user_id,
            project_id=project_id,
            project_name=project_dir.name,
            workspace_id=str(project_dir.parent),
            stage=stage,
            job_id=job_id,
        ):
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
                    scene_id = payload.get("scene_id")
                    panel_number = payload.get("panel_number")
                    if scene_id and panel_number is not None:
                        item_id = f"{scene_id}/panel_{panel_number:03d}"

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
        if result.usage:
            debit_model_usage(
                get_db(),
                user_id,
                project_id,
                result.usage,
                stage=stage,
                description=debit_description,
                job_id=job_id,
            )

    prune_finished_generation_jobs(app)
    job = enqueue_generation_job(
        app,
        project_name=project_name,
        kind=kind,
        label=label,
        payload=payload,
        runner=_runner,
        semaphore=semaphore,
    )
    return job, True
