"""Generation operation records and execution lifecycle. Dispatch uses Procrastinate."""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
import os
import time
import uuid
from collections import deque
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable, Literal

from fastapi import FastAPI

from novel_to_comic.config import Config
from novel_to_comic.state import hash_style_template
from .job_commands import JobCommand
from novel_to_comic.image_failure import (
    ImageFailureClassification,
    classify_image_failure,
    user_message_for_image_failure,
)
from novel_to_comic.server.env import bool_env

GenerationJobStatus = Literal["queued", "running", "complete", "failed", "cancelled"]
GenerationJobRunner = Callable[[], Awaitable[None]]
REFERENCE_JOB_KINDS = {"character_ref_regen", "location_plate_regen", "prop_ref_regen"}
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


# Complete-page providers whose pages may render in parallel for one account.
# Each call is one independent paid submission; provider rate limits answer
# with 429s, which are retried before anything is generated.
PARALLEL_PAGE_PROVIDERS = frozenset({"fal-queue", "openai", "openai-fal", "vertex-multimodal"})
PARALLEL_PAGES_PER_ACCOUNT = 12


def is_parallel_page_draw(job: GenerationJob) -> bool:
    """Use the frozen request, not mutable project settings, as routing authority."""
    return bool(
        job.kind == "complete_page_draw"
        and job.command is not None
        and job.command.operation == "page_draw"
        and job.command.arguments.get("request", {}).get("provider") in PARALLEL_PAGE_PROVIDERS
    )


# Text-only work with no image spend. It gets its own per-account lane so
# lettering stays interactive while an image job renders in another project.
LIGHT_JOB_KINDS = frozenset({"lettering_translation"})


# Text-only pipeline stages, so the next part can extract and brief while
# another part's pages render.
LIGHT_PIPELINE_STAGES = frozenset({"extract", "brief"})


def is_light_job(job: GenerationJob) -> bool:
    if job.kind == "pipeline_stage":
        stage = job.payload.get("stage") or (job.command.stage if job.command else "")
        return stage in LIGHT_PIPELINE_STAGES
    return job.kind in LIGHT_JOB_KINDS


def account_lane_key(job: GenerationJob) -> str:
    if is_parallel_page_draw(job):
        return f"page:{job.sequence % PARALLEL_PAGES_PER_ACCOUNT}"
    return "light" if is_light_job(job) else "exclusive"


class _AccountLane:
    """Parallel-provider pages may run together; all other account work is exclusive."""

    def __init__(self) -> None:
        self.condition = asyncio.Condition()
        self.waiters: deque[tuple[object, bool]] = deque()
        self.parallel = 0
        self.exclusive = False

    @asynccontextmanager
    async def enter(self, parallel: bool):
        token = object()
        admitted = False
        async with self.condition:
            self.waiters.append((token, parallel))
            try:
                while True:
                    ahead = list(self.waiters)
                    position = next(index for index, (waiting, _) in enumerate(ahead) if waiting is token)
                    earlier_exclusive = any(not sibling_parallel for _, sibling_parallel in ahead[:position])
                    if parallel:
                        admitted = (not self.exclusive and not earlier_exclusive
                                    and self.parallel < PARALLEL_PAGES_PER_ACCOUNT)
                    else:
                        admitted = position == 0 and not self.exclusive and self.parallel == 0
                    if admitted:
                        self.waiters.remove((token, parallel))
                        if parallel:
                            self.parallel += 1
                        else:
                            self.exclusive = True
                        break
                    await self.condition.wait()
            except BaseException:
                self.waiters.remove((token, parallel))
                self.condition.notify_all()
                raise
        try:
            yield
        finally:
            async with self.condition:
                if parallel:
                    self.parallel -= 1
                else:
                    self.exclusive = False
                self.condition.notify_all()


def _account_lane(app: FastAPI, user_id: str, *, light: bool = False) -> _AccountLane:
    lanes = getattr(app.state, "user_generation_lanes", None)
    if lanes is None:
        lanes = app.state.user_generation_lanes = {}
    return lanes.setdefault(f"{user_id}:light" if light else user_id, _AccountLane())


def job_transition_lock(app: FastAPI, user_id: str) -> asyncio.Lock:
    locks = getattr(app.state, "job_transition_locks", None)
    if locks is None:
        locks = app.state.job_transition_locks = {}
    return locks.setdefault(user_id, asyncio.Lock())


@dataclass
class GenerationJob:
    id: str
    project_name: str
    kind: str
    label: str
    payload: dict[str, Any]
    sequence: int
    runner: GenerationJobRunner | None
    command: JobCommand | None = None
    user_id: str | None = None
    semaphore: asyncio.Semaphore | None = None
    status: GenerationJobStatus = "queued"
    queued_at: datetime = field(default_factory=_now)
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error: str | None = None
    classification: ImageFailureClassification | Literal["analysis_error", "design_error"] | None = None
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
    command: JobCommand | None = None,
) -> GenerationJob:
    global _global_sequence
    sequence = (max((job.sequence for job in app.state.generation_jobs.values()), default=0) + 1
                if app is not None else _global_sequence)
    _global_sequence += 1

    job = GenerationJob(
        id=uuid.uuid4().hex,
        project_name=project_name,
        kind=kind,
        label=label,
        payload=payload,
        sequence=sequence,
        runner=runner,
        command=command,
        user_id=user_id,
        semaphore=semaphore,
        on_cancel=on_cancel,
    )

    # Capture correlation at admission, not from mutable stage state at finish.
    if command is not None:
        from novel_to_comic.state import load_state
        try:
            current = load_state(Path(command.project_dir)).stages.get(command.stage)
            if current and current.run_id:
                job.payload = {**job.payload, "run_id": current.run_id, "stage_attempt_id": current.attempt_id}
        except (OSError, ValueError):
            pass
    durable = getattr(app.state, "durable_queue", None) if app is not None else None
    if durable is not None and getattr(app.state, "durable_queue_required", False) is True:
        durable.publish(job)
        app.state.generation_jobs[job.id] = job
        return job
    if app is not None and getattr(app.state, "durable_queue_required", False) is True:
        raise RuntimeError("Durable generation queue is unavailable")
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
    waiting_for_other_project = False
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
        # Explain waits caused by the same account's work in another project.
        waiting_for_other_project = bool(job.user_id) and any(
            candidate.status == "running" and candidate.user_id == job.user_id
            and candidate.project_name != job.project_name
            and account_lane_key(candidate) == account_lane_key(job)
            for candidate in jobs.values()
        )

    stage = (job.payload.get("stage") or job.command.stage) if job.command else (
        "style" if job.kind.startswith("style_") else "draw" if job.kind == "complete_page_draw" else "cast"
    )
    result = {
        "id": job.id,
        "project_name": job.project_name,
        "part_id": job_part_id(job),
        "kind": job.kind,
        "stage": "draw" if stage == "lettering" else stage,
        "label": job.label,
        "payload": job.payload,
        "status": job.status,
        "queue_position": queue_position,
        "waiting_for_other_project": waiting_for_other_project,
        "queued_at": _iso(job.queued_at),
        "started_at": _iso(job.started_at),
        "finished_at": _iso(job.finished_at),
        "error": job.error,
        "classification": job.classification,
        "user_message": job.user_message,
        "recoverable": job.recoverable,
        "phase": job.phase,
    }
    if job.kind in REFERENCE_JOB_KINDS and job.command is not None:
        result["reference_style_hash"] = hash_style_template(job.command.config["style_template"])
    return result


def job_part_id(job: GenerationJob) -> str | None:
    """The part a job works on, or ``None`` for series work (Style, Cast)."""
    from novel_to_comic.workspace import part_id_for_path

    command = getattr(job, "command", None)
    if command is not None:
        return part_id_for_path(command.project_dir)
    part = (getattr(job, "payload", None) or {}).get("part_id")
    return part if isinstance(part, str) else None


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


def execution_paused(app: FastAPI, job: GenerationJob) -> bool:
    """Durable operations wait, unstarted, while drained or without credit leases.

    A waiting operation stays queued: deployment can stop the process and the
    restarted worker resumes it. Fixture closures cannot survive a restart.
    """
    if job.command is None:
        return False
    admission = getattr(app.state, "admission", None)
    return bool(getattr(admission, "draining", False)) or not getattr(app.state, "credit_leases_ready", True)


REVIEW_JOB_KINDS = frozenset({
    "character_ref_regen", "location_plate_regen", "prop_ref_regen",
    "style_sample", "style_validation", "project_cover", "complete_page_draw",
})


def project_work_precedes(app: FastAPI, job: GenerationJob) -> bool:
    """Fence corrections against project writers in the independent text lane.

    The account gate already serializes artwork and stages in its image lane.
    Extract/Brief and translation use a separate lane; a correction queued
    during them must wait too. Check both directions so a later text job cannot
    overtake an earlier correction. Different parts retain independent work.
    """
    for other in list(getattr(app.state, "generation_jobs", {}).values()):
        if (other is job or other.project_name != job.project_name
                or other.status not in {"queued", "running"}
                or is_light_job(other) == is_light_job(job)
                or not ({job.kind, other.kind} & REVIEW_JOB_KINDS)):
            continue
        part, other_part = job_part_id(job), job_part_id(other)
        if part is not None and other_part is not None and part != other_part:
            continue
        if other.status == "running" or other.sequence < job.sequence:
            return True
    return False


async def _start_when_open(app: FastAPI, job: GenerationJob) -> bool:
    """Mark the job running unless cancelled; False means it must not execute.

    The pause check and the running transition share one synchronous step, so
    a deployment-status snapshot taken after drain never misses a job that is
    about to start.
    """
    lock = job_transition_lock(app, job.user_id) if job.user_id else None
    while True:
        while (execution_paused(app, job) or project_work_precedes(app, job)) and job.status != "cancelled":
            await asyncio.sleep(1)
        async with lock if lock is not None else _no_lock():
            if job.status == "cancelled":
                return False
            if execution_paused(app, job) or project_work_precedes(app, job):
                continue
            job.status = "running"
            job.started_at = _now()
            persist_generation_job(app, job)
            return True


@asynccontextmanager
async def _no_lock():
    yield


async def _run_generation_job(app: FastAPI, job: GenerationJob) -> None:
    if job.status == "cancelled":
        return
    timeout_seconds = max(1, int(getattr(app.state, "generation_job_timeout_seconds", 900)))
    if job.kind in {"style_suggest", "pipeline_stage"} or (job.command and job.command.operation == "style_direction"):
        timeout_seconds = max(1, int(os.getenv("CANARY_BATCH_JOB_TIMEOUT_SECONDS", "7200")))
    started = time.perf_counter()
    try:
        # Wait before taking an account lane, so a waiting correction cannot
        # hold the lane needed by the work it depends on.
        while project_work_precedes(app, job) and job.status != "cancelled":
            await asyncio.sleep(0.1)
        semaphores: list[asyncio.Semaphore] = []
        if job.semaphore is not None and job.semaphore not in semaphores:
            semaphores.append(job.semaphore)

        async with AsyncExitStack() as stack:
            if job.user_id:
                lane = _account_lane(app, job.user_id, light=is_light_job(job))
                await stack.enter_async_context(lane.enter(is_parallel_page_draw(job)))
            for semaphore in semaphores:
                await stack.enter_async_context(semaphore)
            if not await _start_when_open(app, job):
                return
            # The execution deadline excludes time spent paused or queued.
            started = time.perf_counter()
            logger.debug(
                "[bold cyan]Job start[/] project=[white]%s[/] kind=[cyan]%s[/] label=%s id=[dim]%s[/]",
                job.project_name,
                job.kind,
                job.label,
                job.id[:8],
            )
            if job.command is not None:
                from .job_execution import execute_command
                await asyncio.wait_for(execute_command(app, job), timeout=timeout_seconds)
            else:
                result = job.runner()
                if inspect.isawaitable(result):
                    await asyncio.wait_for(result, timeout=timeout_seconds)
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
        if job.status == "cancelled":
            pass
        elif job.command is not None and job.started_at is None:
            job.status = "queued"
        else:
            if job.started_at is None and job.on_cancel is not None:
                job.on_cancel()
            job.status = "failed"
            job.error = "Generation interrupted by server shutdown."
            job.recoverable = False
            job.phase = "outcome_unknown"
            job.user_message = "Inspect saved output before explicitly retrying this interrupted operation."
        raise
    except asyncio.TimeoutError:
        job.phase = "outcome_unknown"
        job.status = "failed"
        job.error = f"Generation timed out after {timeout_seconds}s"
        job.classification = "timed_out"
        job.user_message = user_message_for_image_failure(job.classification)
        job.recoverable = False
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
        from .job_execution import PipelineStageFailed
        from .telemetry import capture_exception
        if not isinstance(exc, PipelineStageFailed):
            capture_exception(exc, user_id=job.user_id)
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
        # PipelineStageFailed preserves these text-model validation messages.
        if job.error.startswith((
            "Cast design must cover every character exactly once",
            "Cast design returned an invalid character roster",
        )):
            job.classification = "design_error"
            job.user_message = (
                "Cast design returned an invalid character roster. "
                "Resume Cast to try the design again."
            )
            job.recoverable = True
        from novel_to_comic.cast_instructions import PromptInstructionError

        if isinstance(exc, PromptInstructionError):
            # This bounded rewrite rejection is safe author-facing feedback,
            # not an image-provider failure to replace with generic prose.
            job.user_message = str(exc)
            job.recoverable = True
        if job.kind == "lettering_translation":
            job.user_message = "Lettering translation failed. Saved provider outputs are retained for inspection; completed calls may still be charged. " + job.error
            job.recoverable = False
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
        if job.status in {"complete", "failed", "cancelled"}:
            job.finished_at = _now()
        persist_generation_job(app, job)



async def run_generation_job(app: FastAPI, job: GenerationJob) -> None:
    from .telemetry import (
        ai_span,
        log_event,
        metric_count,
        metric_histogram,
        operation_span,
    )
    spec = job.command
    carrier = {"traceparent": spec.traceparent} if spec and spec.traceparent else {}
    with operation_span("job.execute", carrier=carrier, operation_id=job.id,
                        request_id=spec.request_id if spec else None,
                        browser_session_id=spec.browser_session_id if spec else None,
                        project_id=spec.project_id if spec else None,
                        posthogDistinctId=job.user_id, operation=spec.operation if spec else job.kind,
                        stage=spec.stage if spec else None) as span, \
            ai_span(f"job.{spec.operation if spec else job.kind}", stage=spec.stage if spec else None,
                    page_number=job.payload.get("page_number")) as job_span:
        try:
            await _run_generation_job(app, job)
        finally:
            if job.status in {"complete", "failed", "cancelled"}:
                job_span.set(status=job.status, run_id=job.payload.get("run_id"),
                             stage_attempt_id=job.payload.get("stage_attempt_id"))
                if span is not None:
                    span.set_attribute("status", job.status)
                    if job.status == "failed":
                        from opentelemetry.trace import Status, StatusCode
                        span.set_status(Status(StatusCode.ERROR))
                fields = {"status": job.status, "phase": job.phase,
                          "queue_ms": max(0, (job.started_at - job.queued_at).total_seconds() * 1000)
                          if job.started_at and job.queued_at else None,
                          "latency_ms": max(0, (job.finished_at - job.started_at).total_seconds() * 1000)
                          if job.finished_at and job.started_at else None}
                metric_attributes = {
                    "operation": spec.operation if spec else job.kind,
                    "status": job.status,
                }
                metric_count("jobs.processed", attributes=metric_attributes)
                if fields["latency_ms"] is not None:
                    metric_histogram(
                        "jobs.duration",
                        fields["latency_ms"],
                        unit="ms",
                        attributes=metric_attributes,
                    )
                if fields["queue_ms"] is not None:
                    metric_histogram(
                        "jobs.queue_wait",
                        fields["queue_ms"],
                        unit="ms",
                        attributes=metric_attributes,
                    )
                log_event("job.completed", level=logging.ERROR if job.status == "failed" else logging.INFO, **fields)
                # Terminal analytics is persisted with the job below, including
                # dispatch/restart paths which do not enter this runner.


async def generation_worker(app: FastAPI) -> None:
    """Provider-free fixture runner. Application lifespan uses DurableQueue."""
    while True:
        job = await app.state.generation_queue.get()
        try:
            await run_generation_job(app, job)
        finally:
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
        if job.status in {"complete", "failed", "cancelled"}:
            from .lifecycle_events import enqueue
            project_id = job.command.project_id if job.command else None
            enqueue(db, "operation_completed", job.id, user_id=job.user_id,
                    project_id=project_id, job_id=job.id,
                    properties={"operation": job.command.operation if job.command else job.kind, "operation_id": job.id, "run_id": job.payload.get("run_id") or job.id, "attempt_id": job.id,
                                "stage_attempt_id": job.payload.get("stage_attempt_id"),
                                "stage": payload["stage"], "status": job.status,
                                "outcome": "outcome_unknown" if job.phase == "outcome_unknown" else job.status,
                                "phase": job.phase,
                                "queue_ms": max(0, (job.started_at - job.queued_at).total_seconds() * 1000) if job.started_at else None,
                                "latency_ms": max(0, (job.finished_at - job.started_at).total_seconds() * 1000) if job.finished_at and job.started_at else None})
            if job.kind == "pipeline_stage" and job.status in {"failed", "cancelled"} and job.payload.get("stage_attempt_id"):
                enqueue(db, "stage_failed", job.payload["stage_attempt_id"], user_id=job.user_id,
                        project_id=project_id, job_id=job.id,
                        properties={"stage": payload["stage"], "run_id": job.payload.get("run_id") or job.id,
                                    "attempt_id": job.payload["stage_attempt_id"],
                                    "outcome": "outcome_unknown" if job.phase == "outcome_unknown" else job.status})
    if job.command and job.command.stage == "draw" and job.status in {"complete", "failed", "cancelled"}:
        from .routers.pages import _sync_draw_progress
        try:
            _sync_draw_progress(Path(job.command.project_dir), app)
        except Exception as exc:  # analytics reconciliation cannot fail the job
            logger.warning("Draw terminal reconciliation deferred type=%s", type(exc).__name__)


def recovered_generation_jobs(app, pkey: str) -> list[dict]:
    admission = getattr(app.state, "admission", None)
    if admission is None:
        return []
    with admission.journal() as db:
        db.execute("CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, project TEXT NOT NULL, payload TEXT NOT NULL)")
        has_outbox = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='operation_outbox'").fetchone()
        rows = db.execute("SELECT payload FROM jobs WHERE project=?", (pkey,)).fetchall()
        durable_ids = {row[0] for row in db.execute("SELECT id FROM operation_outbox")} if has_outbox else set()
        payloads = [json.loads(row[0]) for row in rows]
        for payload in payloads:
            if payload["id"] in app.state.generation_jobs or payload["kind"] not in REFERENCE_JOB_KINDS or not has_outbox:
                continue
            # Read only recovered reference commands; page commands can contain
            # large frozen inputs, and live jobs already hold their own config.
            row = db.execute("SELECT command FROM operation_outbox WHERE id=?", (payload["id"],)).fetchone()
            if row is not None:
                config = json.loads(row[0])["config"]
                payload["reference_style_hash"] = hash_style_template(config["style_template"])
    recovered = []
    for payload in payloads:
        if payload["id"] in app.state.generation_jobs:
            continue
        if payload["status"] == "queued" and payload["id"] in durable_ids:
            payload["queue_position"] = None
        elif payload["status"] in {"queued", "running"}:
            payload.update(
                status="failed", error="Server restarted before this job's outcome was recorded.",
                user_message="Inspect existing output before explicitly retrying this interrupted action.",
                classification="generation_error", recoverable=payload["status"] == "queued",
                phase="outcome_unknown" if payload["status"] == "running" else None, queue_position=None,
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
            if job.status in ("complete", "failed", "cancelled")
        ),
        key=lambda job: job.finished_at or job.queued_at,
    )
    for job in finished[:-max_finished]:
        jobs.pop(job.id, None)
