"""In-memory queue for targeted image generation jobs."""

from __future__ import annotations

import asyncio
import inspect
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Literal

from fastapi import FastAPI

GenerationJobStatus = Literal["queued", "running", "complete", "failed"]
GenerationJobRunner = Callable[[], Awaitable[None]]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


@dataclass
class GenerationJob:
    id: str
    project_name: str
    kind: str
    label: str
    payload: dict[str, Any]
    sequence: int
    runner: GenerationJobRunner
    status: GenerationJobStatus = "queued"
    queued_at: datetime = field(default_factory=_now)
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error: str | None = None


def enqueue_generation_job(
    app: FastAPI,
    project_name: str,
    kind: str,
    label: str,
    payload: dict[str, Any],
    runner: GenerationJobRunner,
) -> GenerationJob:
    sequence = app.state.generation_job_sequence
    app.state.generation_job_sequence += 1
    job = GenerationJob(
        id=uuid.uuid4().hex,
        project_name=project_name,
        kind=kind,
        label=label,
        payload=payload,
        sequence=sequence,
        runner=runner,
    )
    app.state.generation_jobs[job.id] = job
    app.state.generation_queue.put_nowait(job)
    return job


def generation_job_payload(app: FastAPI, job: GenerationJob) -> dict[str, Any]:
    queue_position: int | None = None
    if job.status == "queued":
        queued = sorted(
            (
                candidate
                for candidate in app.state.generation_jobs.values()
                if candidate.status == "queued"
            ),
            key=lambda candidate: candidate.sequence,
        )
        queue_position = next(
            (index + 1 for index, candidate in enumerate(queued) if candidate.id == job.id),
            None,
        )

    return {
        "id": job.id,
        "project_name": job.project_name,
        "kind": job.kind,
        "label": job.label,
        "payload": job.payload,
        "status": job.status,
        "queue_position": queue_position,
        "queued_at": _iso(job.queued_at),
        "started_at": _iso(job.started_at),
        "finished_at": _iso(job.finished_at),
        "error": job.error,
    }


async def generation_worker(app: FastAPI) -> None:
    while True:
        job: GenerationJob = await app.state.generation_queue.get()
        job.status = "running"
        job.started_at = _now()
        try:
            result = job.runner()
            if inspect.isawaitable(result):
                await result
            job.status = "complete"
        except Exception as exc:
            job.status = "failed"
            job.error = str(exc) or type(exc).__name__
        finally:
            job.finished_at = _now()
            app.state.generation_queue.task_done()


def prune_finished_generation_jobs(app: FastAPI, max_finished: int = 200) -> None:
    finished = sorted(
        (
            job
            for job in app.state.generation_jobs.values()
            if job.status in ("complete", "failed")
        ),
        key=lambda job: job.finished_at or job.queued_at,
    )
    for job in finished[:-max_finished]:
        app.state.generation_jobs.pop(job.id, None)
