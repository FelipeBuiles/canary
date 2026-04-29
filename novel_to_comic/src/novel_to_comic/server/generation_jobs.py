"""In-memory queue for targeted image generation jobs."""

from __future__ import annotations

import asyncio
import inspect
import logging
import os
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Literal

from fastapi import FastAPI

from novel_to_comic.config import Config

GenerationJobStatus = Literal["queued", "running", "complete", "failed"]
GenerationJobRunner = Callable[[], Awaitable[None]]
logger = logging.getLogger("canary.generation")


def _bool_env(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _looks_like_timeout_cancellation(exc: BaseException, elapsed: float, timeout_seconds: int) -> bool:
    text = " ".join(str(part) for part in (type(exc).__name__, str(exc), *(str(arg) for arg in getattr(exc, "args", ()))))
    lowered = text.lower()
    return elapsed >= max(0, timeout_seconds - 2) and "cancel" in lowered


@dataclass
class GenerationJob:
    id: str
    project_name: str
    kind: str
    label: str
    payload: dict[str, Any]
    sequence: int
    runner: GenerationJobRunner
    semaphore: asyncio.Semaphore | None = None
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
    semaphore: asyncio.Semaphore | None = None,
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
        semaphore=semaphore,
    )
    app.state.generation_jobs[job.id] = job
    app.state.generation_queue.put_nowait(job)
    logger.info(
        "[bold blue]Job queued[/] project=[white]%s[/] kind=[cyan]%s[/] label=%s id=[dim]%s[/]",
        project_name,
        kind,
        label,
        job.id[:8],
    )
    return job


def generation_job_payload(app: FastAPI, job: GenerationJob) -> dict[str, Any]:
    queue_position: int | None = None
    if job.status == "queued":
        queued = sorted(
            (
                candidate
                for candidate in app.state.generation_jobs.values()
                if candidate.status == "queued"
                and candidate.project_name == job.project_name
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


def find_active_generation_job(
    app: FastAPI,
    project_name: str,
    kind: str,
    payload: dict[str, Any] | None = None,
) -> GenerationJob | None:
    for job in app.state.generation_jobs.values():
        if (
            job.project_name == project_name
            and job.kind == kind
            and job.status in ("queued", "running")
            and (payload is None or job.payload == payload)
        ):
            return job
    return None


async def generation_worker(app: FastAPI) -> None:
    timeout_seconds = max(1, int(getattr(app.state, "generation_job_timeout_seconds", 900)))

    async def _run_job(job: GenerationJob) -> None:
        result = job.runner()
        if not inspect.isawaitable(result):
            return
        await asyncio.wait_for(result, timeout=timeout_seconds)

    while True:
        job: GenerationJob = await app.state.generation_queue.get()
        started = time.perf_counter()
        try:
            if job.semaphore is None:
                job.status = "running"
                job.started_at = _now()
                logger.info(
                    "[bold cyan]Job start[/] project=[white]%s[/] kind=[cyan]%s[/] label=%s id=[dim]%s[/]",
                    job.project_name,
                    job.kind,
                    job.label,
                    job.id[:8],
                )
                await _run_job(job)
            else:
                async with job.semaphore:
                    job.status = "running"
                    job.started_at = _now()
                    logger.info(
                        "[bold cyan]Job start[/] project=[white]%s[/] kind=[cyan]%s[/] label=%s id=[dim]%s[/]",
                        job.project_name,
                        job.kind,
                        job.label,
                        job.id[:8],
                    )
                    await _run_job(job)
            job.status = "complete"
            logger.info(
                "[bold green]Job complete[/] project=[white]%s[/] kind=[cyan]%s[/] "
                "label=%s id=[dim]%s[/] elapsed=[bold]%.1fs[/]",
                job.project_name,
                job.kind,
                job.label,
                job.id[:8],
                time.perf_counter() - started,
            )
        except asyncio.TimeoutError:
            job.status = "failed"
            job.error = f"Generation timed out after {timeout_seconds}s"
            logger.error(
                "[bold red]Job timeout[/] project=[white]%s[/] kind=[cyan]%s[/] "
                "label=%s id=[dim]%s[/] elapsed=[bold]%.1fs[/] timeout=%ss",
                job.project_name,
                job.kind,
                job.label,
                job.id[:8],
                time.perf_counter() - started,
                timeout_seconds,
            )
        except Exception as exc:
            elapsed = time.perf_counter() - started
            job.status = "failed"
            if _looks_like_timeout_cancellation(exc, elapsed, timeout_seconds):
                job.error = f"Generation timed out after {timeout_seconds}s"
            else:
                job.error = str(exc) or type(exc).__name__
            logger.error(
                "[bold red]Job failed[/] project=[white]%s[/] kind=[cyan]%s[/] "
                "label=%s id=[dim]%s[/] elapsed=[bold]%.1fs[/] error=%s",
                job.project_name,
                job.kind,
                job.label,
                job.id[:8],
                elapsed,
                job.error,
                exc_info=_bool_env("CANARY_LOG_JOB_TRACEBACKS", default=False),
            )
        finally:
            job.finished_at = _now()
            app.state.generation_queue.task_done()


def generation_semaphore_for_config(app: FastAPI, config: Config) -> asyncio.Semaphore:
    if config.uses_gemini_image_provider():
        return app.state.generation_semaphore
    if config.dev_mode:
        concurrency = config.effective_image_concurrency()
        semaphores = app.state.light_generation_semaphores
        semaphore = semaphores.get(concurrency)
        if semaphore is None:
            semaphore = asyncio.Semaphore(concurrency)
            semaphores[concurrency] = semaphore
        return semaphore
    return app.state.generation_semaphore


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
