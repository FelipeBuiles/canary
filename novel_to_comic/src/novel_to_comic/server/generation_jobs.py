"""In-memory queue for targeted image generation jobs."""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
import os
import time
import uuid
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Literal

from fastapi import FastAPI

from novel_to_comic.config import Config
from novel_to_comic.image_failure import (
    ImageFailureClassification,
    classify_image_failure,
    user_message_for_image_failure,
)
from novel_to_comic.server.env import bool_env

GenerationJobStatus = Literal["queued", "running", "complete", "failed"]
GenerationJobRunner = Callable[[], Awaitable[None]]
logger = logging.getLogger("canary.generation")


_global_queue: asyncio.Queue | None = None
_global_jobs: dict[str, GenerationJob] = {}
_global_sequence: int = 1
_global_light_semaphores: dict[int, asyncio.Semaphore] = {}
_global_semaphore: asyncio.Semaphore | None = None


def get_global_queue() -> asyncio.Queue:
    global _global_queue
    if _global_queue is None:
        _global_queue = asyncio.Queue()
    return _global_queue


def get_global_semaphore() -> asyncio.Semaphore:
    global _global_semaphore
    if _global_semaphore is None:
        _global_semaphore = asyncio.Semaphore(1)
    return _global_semaphore


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
    user_id: str | None = None
    semaphore: asyncio.Semaphore | None = None
    status: GenerationJobStatus = "queued"
    queued_at: datetime = field(default_factory=_now)
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error: str | None = None
    classification: ImageFailureClassification | None = None
    user_message: str | None = None
    recoverable: bool | None = None
    phase: str | None = None
    on_cancel: Callable[[], None] | None = None


def enqueue_generation_job(
    app: FastAPI | None,
    project_name: str,
    kind: str,
    label: str,
    payload: dict[str, Any],
    runner: GenerationJobRunner,
    user_id: str | None = None,
    semaphore: asyncio.Semaphore | None = None,
    on_cancel: Callable[[], None] | None = None,
) -> GenerationJob:
    global _global_sequence
    sequence = _global_sequence
    _global_sequence += 1

    job = GenerationJob(
        id=uuid.uuid4().hex,
        project_name=project_name,
        kind=kind,
        label=label,
        payload=payload,
        sequence=sequence,
        runner=runner,
        user_id=user_id,
        semaphore=semaphore,
        on_cancel=on_cancel,
    )

    persist_generation_job(app, job)
    if app is not None:
        app.state.generation_jobs[job.id] = job
        app.state.generation_queue.put_nowait(job)
    else:
        _global_jobs[job.id] = job
        get_global_queue().put_nowait(job)

    logger.info(
        "[bold blue]Job queued[/] project=%s kind=%s label=%s id=[dim]%s[/]",
        project_name,
        kind,
        label,
        job.id[:8],
    )
    return job


def generation_job_payload(app: FastAPI | None, job: GenerationJob) -> dict[str, Any]:
    queue_position: int | None = None
    if job.status == "queued":
        jobs = app.state.generation_jobs if app is not None else _global_jobs
        queued = sorted(
            (
                candidate
                for candidate in jobs.values()
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
        "classification": job.classification,
        "user_message": job.user_message,
        "recoverable": job.recoverable,
        "phase": job.phase,
    }


def find_active_generation_job(
    app: FastAPI | None,
    project_name: str,
    kind: str,
    payload: dict[str, Any] | None = None,
) -> GenerationJob | None:
    # Author words are durable evidence, not a second asset identity. Plain and
    # instructed requests for the same asset must share one active-work slot.
    def identity(value: dict[str, Any]) -> dict[str, Any]:
        if kind in {"character_ref_regen", "location_plate_regen", "prop_ref_regen"}:
            return {key: item for key, item in value.items() if key not in {"instruction", "reference_assets"}}
        return value

    jobs = app.state.generation_jobs if app is not None else _global_jobs
    for job in jobs.values():
        if (
            job.project_name == project_name
            and job.kind == kind
            and job.status in ("queued", "running")
            and (payload is None or identity(job.payload) == identity(payload))
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
        if job.user_id:
            user_semaphore = user_generation_semaphore(app, job.user_id)
            if user_semaphore.locked():
                # Do not let one user's queued batch occupy every worker while
                # waiting for that same user's active slot. Requeue it behind
                # other users so the process remains fair.
                app.state.generation_queue.put_nowait(job)
                app.state.generation_queue.task_done()
                await asyncio.sleep(0.05)
                continue
        started = time.perf_counter()
        try:
            semaphores: list[asyncio.Semaphore] = []
            if job.user_id:
                semaphores.append(user_generation_semaphore(app, job.user_id))
            if job.semaphore is not None and job.semaphore not in semaphores:
                semaphores.append(job.semaphore)

            async with AsyncExitStack() as stack:
                for semaphore in semaphores:
                    await stack.enter_async_context(semaphore)
                job.status = "running"
                job.started_at = _now()
                persist_generation_job(app, job)
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
        except asyncio.CancelledError:
            if job.started_at is None and job.on_cancel is not None:
                job.on_cancel()
            job.status = "failed"
            job.error = "Generation interrupted by server shutdown."
            job.recoverable = True
            raise
        except asyncio.TimeoutError:
            job.status = "failed"
            job.error = f"Generation timed out after {timeout_seconds}s"
            job.classification = "timed_out"
            job.user_message = user_message_for_image_failure(job.classification)
            job.recoverable = True
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
                job.classification = "timed_out"
            else:
                job.error = str(exc) or type(exc).__name__
                job.classification = classify_image_failure(exc)
            job.user_message = user_message_for_image_failure(job.classification)
            job.recoverable = job.classification != "configuration_error"
            job.phase = (
                "ambiguous_submission" if getattr(exc, "phase", None) == "ambiguous_submission"
                else getattr(exc, "page_failure_phase", None)
            )
            if job.phase == "analysis":
                job.classification = "analysis_error"
                job.user_message = "Artwork saved; text checks incomplete. Recover the text check without redrawing."
                job.recoverable = True
            from novel_to_comic.cast_instructions import PromptInstructionError

            if isinstance(exc, PromptInstructionError):
                # This bounded rewrite rejection is safe author-facing feedback,
                # not an image-provider failure to replace with generic prose.
                job.user_message = str(exc)
                job.recoverable = True
            logger.error(
                "[bold red]Job failed[/] project=[white]%s[/] kind=[cyan]%s[/] "
                "label=%s id=[dim]%s[/] elapsed=[bold]%.1fs[/] error=%s",
                job.project_name,
                job.kind,
                job.label,
                job.id[:8],
                elapsed,
                job.error,
                exc_info=bool_env("CANARY_LOG_JOB_TRACEBACKS", default=False),
            )
        finally:
            job.finished_at = _now()
            persist_generation_job(app, job)
            app.state.generation_queue.task_done()


def persist_generation_job(app, job: GenerationJob) -> None:
    admission = getattr(app.state, "admission", None) if app is not None else None
    if admission is None:
        return
    payload = generation_job_payload(app, job)
    with admission.journal() as db:
        db.execute("CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, project TEXT NOT NULL, payload TEXT NOT NULL)")
        db.execute("INSERT OR REPLACE INTO jobs VALUES(?,?,?)",
                   (job.id, job.project_name, json.dumps(payload)))


def recovered_generation_jobs(app, pkey: str) -> list[dict]:
    admission = getattr(app.state, "admission", None)
    if admission is None:
        return []
    with admission.journal() as db:
        db.execute("CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, project TEXT NOT NULL, payload TEXT NOT NULL)")
        rows = db.execute("SELECT payload FROM jobs WHERE project=?", (pkey,)).fetchall()
    recovered = []
    for row in rows:
        payload = json.loads(row[0])
        if payload["id"] in app.state.generation_jobs:
            continue
        if payload["status"] in {"queued", "running"}:
            payload.update(
                status="failed", error="Server restarted before this job's outcome was recorded.",
                user_message="Inspect existing output before explicitly retrying this interrupted action.",
                classification="generation_error", recoverable=True, queue_position=None,
            )
        recovered.append(payload)
    return recovered


def _per_user_generation_limit() -> int:
    try:
        return max(
            1,
            int(os.environ.get("CANARY_MAX_ACTIVE_GENERATION_JOBS_PER_USER", "1")),
        )
    except (TypeError, ValueError):
        return 1


def user_generation_semaphore(app: FastAPI, user_id: str) -> asyncio.Semaphore:
    """Return the process-local active-job ceiling for one authenticated user."""
    semaphores = app.state.user_generation_semaphores
    semaphore = semaphores.get(user_id)
    if semaphore is None:
        semaphore = asyncio.Semaphore(_per_user_generation_limit())
        semaphores[user_id] = semaphore
    return semaphore


def generation_semaphore_for_config(app: FastAPI | None, config: Config) -> asyncio.Semaphore:
    if config.dev_mode:
        concurrency = config.effective_image_concurrency()
        semaphores = app.state.light_generation_semaphores if app is not None else _global_light_semaphores
        semaphore = semaphores.get(concurrency)
        if semaphore is None:
            semaphore = asyncio.Semaphore(concurrency)
            semaphores[concurrency] = semaphore
        return semaphore
    return app.state.generation_semaphore if app is not None else get_global_semaphore()


def prune_finished_generation_jobs(app: FastAPI | None, max_finished: int = 200) -> None:
    jobs = app.state.generation_jobs if app is not None else _global_jobs
    finished = sorted(
        (
            job
            for job in jobs.values()
            if job.status in ("complete", "failed")
        ),
        key=lambda job: job.finished_at or job.queued_at,
    )
    for job in finished[:-max_finished]:
        jobs.pop(job.id, None)
