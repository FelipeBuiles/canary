"""Couples a credit check/debit with a generation-job lifecycle.

Each regen handler was doing the same dance: assert credits, create a job_id,
wrap the runner in ai_request_context + debit_model_usage, check for an active
duplicate, prune stale jobs, then enqueue.  This module owns that coupling so
handlers shrink to payload assembly + response formatting.
"""

import asyncio
import uuid as uuid_lib
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from fastapi import FastAPI

from novel_to_comic.ai import ai_request_context
from novel_to_comic.usage import ApiResult

from .credits import assert_sufficient_credits, debit_model_usage
from .db import get_db
from .generation_jobs import (
    GenerationJob,
    enqueue_generation_job,
    find_active_generation_job,
    prune_finished_generation_jobs,
)


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
