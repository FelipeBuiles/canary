"""Procrastinate dispatch with a transactional, volume-local operation outbox.

The outbox and artifact volume have exactly one owner (enforced by flock). This
is intentionally not a distributed filesystem worker. Procrastinate owns FIFO
resource scheduling and worker heartbeats; the outbox owns operation outcomes.
A redelivered dispatch never re-executes an operation whose execution began.
"""
from __future__ import annotations

import asyncio
import fcntl
import hashlib
import json
from pathlib import Path
import logging
import os
import time
from datetime import datetime, timezone

from .job_commands import JobCommand

logger = logging.getLogger("canary.queue")


def dispatch_lock(queue_name: str, job) -> str:
    from .generation_jobs import account_lane_key

    lane = account_lane_key(job)
    return f"{queue_name}:account:{job.user_id}" + ("" if lane == "exclusive" else f":{lane}")


class DurableQueue:
    def __init__(self, app, dsn: str):
        import procrastinate

        self.app = app
        self.queue_name = "canary-" + hashlib.sha256(str(app.state.projects_dir.resolve()).encode()).hexdigest()[:16]
        self.backend = procrastinate.App(connector=procrastinate.PsycopgConnector(
            conninfo=dsn, min_size=1, max_size=6, timeout=5,
            kwargs={"connect_timeout": 5},
        ))
        self.task = self.backend.task(name="canary.operation.v1", queue=self.queue_name,
                                      retry=False, pass_context=True)(self.execute)
        self.ready = False
        self.last_healthy = 0.0
        self.worker = None
        self.owner = None
        self.failure = None
        with app.state.admission.journal() as db:
            db.execute("CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, project TEXT NOT NULL, payload TEXT NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS operation_outbox (id TEXT PRIMARY KEY, command TEXT NOT NULL, dispatched INTEGER)")
            db.execute("CREATE INDEX IF NOT EXISTS pending_dispatches ON operation_outbox(dispatched) WHERE dispatched IS NULL")

    @property
    def healthy(self):
        return self.ready and self.worker is not None and not self.worker.done() and time.monotonic() - self.last_healthy < 15

    def publish(self, job):
        from .generation_jobs import generation_job_payload

        if not self.healthy:
            raise RuntimeError("Durable generation queue is unavailable")
        if job.command is None:
            raise ValueError(f"Operation {job.kind} has no durable command")
        # One commit admits both the operation and its dispatch intent. A crash
        # after this commit cannot lose an accepted command.
        with self.app.state.admission.journal() as db:
            db.execute("CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, project TEXT NOT NULL, payload TEXT NOT NULL)")
            db.execute("INSERT INTO jobs VALUES(?,?,?)", (job.id, job.project_name, json.dumps(generation_job_payload(self.app, job))))
            db.execute("INSERT INTO operation_outbox(id,command) VALUES(?,?)", (job.id, job.command.model_dump_json()))

    def restore(self):
        from .generation_jobs import GenerationJob, persist_generation_job

        with self.app.state.admission.journal() as db:
            rows = db.execute("SELECT j.payload,o.command FROM jobs j JOIN operation_outbox o ON o.id=j.id ORDER BY o.rowid").fetchall()
        for sequence, (raw, command_json) in enumerate(rows, 1):
            p = json.loads(raw)
            job = GenerationJob(id=p["id"], project_name=p["project_name"], kind=p["kind"], label=p["label"],
                                payload=p["payload"], sequence=sequence, runner=None,
                                command=JobCommand.model_validate_json(command_json), status=p["status"])
            job.user_id = job.command.user_id
            for key in ("queued_at", "started_at", "finished_at"):
                if p.get(key):
                    setattr(job, key, datetime.fromisoformat(p[key]))
            for key in ("error", "classification", "user_message", "recoverable", "phase"):
                setattr(job, key, p.get(key))
            if job.status == "running":
                job.status = "failed"
                job.phase = "outcome_unknown"
                job.error = "Execution interrupted before its outcome was recorded."
                job.user_message = "Inspect saved output and provider evidence before explicitly retrying."
                job.recoverable = False
                job.finished_at = datetime.now(timezone.utc)
                persist_generation_job(self.app, job)
            self.app.state.generation_jobs[job.id] = job
        self._settle_interrupted_styles()

    def _settle_interrupted_styles(self):
        """Close the Style stage of work a hard stop interrupted (see settle_interrupted_style)."""
        from .project_paths import project_directory
        from .style_jobs import STYLE_OPERATIONS, settle_interrupted_style

        jobs = [job for job in self.app.state.generation_jobs.values() if job.command.operation in STYLE_OPERATIONS]
        waiting = {job.command.project_dir for job in jobs if job.status == "queued"}
        for job in jobs:
            if job.status != "failed" or job.phase != "outcome_unknown" or job.command.project_dir in waiting:
                continue
            directory = Path(job.command.project_dir)
            if directory != project_directory(self.app.state.projects_dir, job.command.user_id, directory.name):
                continue
            settle_interrupted_style(job, directory)

    async def execute(self, context, *, operation_id: str):
        from .generation_jobs import run_generation_job

        job = self.app.state.generation_jobs.get(operation_id)
        if job is None or job.status != "queued":
            # Includes redelivery after outcome persistence or a lost worker.
            return
        # Drain and missing credit leases hold this dispatch unstarted inside
        # run_generation_job. (The task has retry=False, so JobRetry would fail it.)
        try:
            await run_generation_job(self.app, job)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.failure = exc
            self.ready = False
            raise

    async def cancel_queued_pages(self, *, project_name: str, user_id: str) -> list[str]:
        """Cancel only page operations that have not begun a provider call."""
        from .generation_jobs import job_transition_lock, persist_generation_job

        cancelled = []
        async with job_transition_lock(self.app, user_id):
            jobs = [job for job in self.app.state.generation_jobs.values()
                    if job.project_name == project_name and job.kind == "complete_page_draw"
                    and job.status == "queued" and job.started_at is None]
            with self.app.state.admission.journal() as db:
                dispatches = dict(db.execute(
                    "SELECT id,dispatched FROM operation_outbox WHERE id IN ("
                    + ",".join("?" for _ in jobs) + ")", tuple(job.id for job in jobs)
                )) if jobs else {}
            for job in jobs:
                dispatch_id = dispatches.get(job.id)
                if dispatch_id is not None:
                    # False means a worker already claimed the dispatch. It is
                    # still safe to cancel while our domain job is queued: the
                    # worker checks status under this same lock before execution.
                    await self.backend.job_manager.cancel_job_by_id_async(int(dispatch_id), abort=False)
                job.status = "cancelled"
                job.finished_at = datetime.now(timezone.utc)
                job.phase = "cancelled"
                job.user_message = "Cancelled before the image request started. No generation charge was made."
                job.recoverable = True
                persist_generation_job(self.app, job)
                cancelled.append(job.id)
        return cancelled

    async def run(self):
        root = self.app.state.projects_dir
        root.mkdir(parents=True, exist_ok=True)
        self.owner = (root / ".queue-owner.lock").open("a+b")
        try:
            fcntl.flock(self.owner.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self.owner.close()
            raise RuntimeError("Another server owns this artifact volume") from None
        try:
            self.restore()
            async with self.backend.open_async():
                # Schema creation is an explicit deployment action, never an
                # implicit production migration inside a request or worker.
                await self.backend.connector.execute_query_one_async("SELECT EXISTS(SELECT 1 FROM procrastinate_jobs)")
                self.worker = asyncio.create_task(self.backend.run_worker_async(
                    queues=[self.queue_name], concurrency=max(1, int(os.getenv("CANARY_GENERATION_WORKERS", "5"))),
                    install_signal_handlers=False, listen_notify=False, fetch_job_polling_interval=0.5,
                ))
                try:
                    while True:
                        if self.failure is not None:
                            raise RuntimeError("Operation persistence failed") from self.failure
                        if self.worker.done():
                            await self.worker
                            raise RuntimeError("Generation worker exited unexpectedly")
                        await self.dispatch()
                        from .telemetry import metric_gauge
                        # Snapshot first: worker threads may add jobs mid-count.
                        jobs = list(self.app.state.generation_jobs.values())
                        metric_gauge("jobs.queue_depth", sum(job.status == "queued" for job in jobs))
                        self.last_healthy = time.monotonic()
                        self.ready = True
                        await asyncio.sleep(1)
                finally:
                    self.ready = False
                    self.worker.cancel()
                    await asyncio.gather(self.worker, return_exceptions=True)

        finally:
            self.ready = False
            if self.worker is not None:
                self.worker.cancel()
                await asyncio.gather(self.worker, return_exceptions=True)
            if self.owner is not None:
                self.owner.close()

    async def dispatch(self):
        from procrastinate.exceptions import AlreadyEnqueued

        # Drain closes admission and holds unstarted work; accepted work keeps
        # its dispatch so it resumes after resume or process replacement.
        if not self.app.state.credit_leases_ready:
            return
        with self.app.state.admission.journal() as db:
            rows = db.execute("SELECT id,dispatched FROM operation_outbox WHERE dispatched IS NULL ORDER BY rowid").fetchall()
        for operation_id, dispatched in rows:
            job = self.app.state.generation_jobs.get(operation_id)
            if job is None or job.status != "queued" or dispatched is not None:
                continue
            try:
                # Procrastinate's account lock otherwise serializes every page.
                # Stable page lanes bound parallel Draw dispatch; the in-process
                # account gate keeps other operations exclusive with them.
                dispatch_id = await self.task.configure(
                    lock=dispatch_lock(self.queue_name, job), queueing_lock=f"{self.queue_name}:operation:{job.id}",
                ).defer_async(operation_id=job.id)
            except AlreadyEnqueued:
                continue
            with self.app.state.admission.journal() as db:
                db.execute("UPDATE operation_outbox SET dispatched=? WHERE id=?", (dispatch_id, job.id))
        # A dispatch that died before entering our handler is safe to redeliver;
        # running operations have already been fenced to outcome_unknown by
        # restore(). Re-delivering them only acknowledges their terminal state.
        for stalled in await self.backend.job_manager.get_stalled_jobs(queue=self.queue_name):
            operation = self.app.state.generation_jobs.get(stalled.task_kwargs.get("operation_id"))
            if operation is not None and operation.status == "running":
                continue  # Never steal an operation from this live process.
            await self.backend.job_manager.retry_job(stalled)
        await self.reconcile_failed_dispatches()

    async def reconcile_failed_dispatches(self):
        """A dead dispatch must not leave an unstarted operation queued forever."""
        from .generation_jobs import persist_generation_job

        with self.app.state.admission.journal() as db:
            dispatched = dict(db.execute(
                "SELECT id,dispatched FROM operation_outbox WHERE dispatched IS NOT NULL"
            ))
        pending = {
            dispatch_id: operation_id for operation_id, dispatch_id in dispatched.items()
            if (job := self.app.state.generation_jobs.get(operation_id)) is not None
            and job.status == "queued" and job.started_at is None
        }
        if not pending:
            return
        rows = await self.backend.connector.execute_query_all_async(
            "SELECT id,status FROM procrastinate_jobs WHERE id = ANY(%(ids)s) "
            "AND queue_name = %(queue)s AND status IN ('failed','cancelled','aborted')",
            ids=list(pending), queue=self.queue_name,
        )
        for row in rows:
            job = self.app.state.generation_jobs.get(pending[row["id"]])
            # Execution can start while the scheduler query is in flight.
            if job is None or job.status != "queued" or job.started_at is not None:
                continue
            job.status = "failed"
            job.phase = "dispatch"
            job.classification = "generation_error"
            job.recoverable = True
            job.error = f"Queue dispatch {row['id']} ended as {row['status']} before generation started."
            job.user_message = "This page never started drawing because its queued task stopped. Try again."
            job.finished_at = datetime.now(timezone.utc)
            persist_generation_job(self.app, job)
            logger.warning("Reconciled unstarted operation %s: %s", job.id, job.error)


async def initialize_queue(app):
    dsn = os.getenv("CANARY_QUEUE_DATABASE_URL", "")
    if not dsn:
        logger.error("CANARY_QUEUE_DATABASE_URL is required; generation admission is closed")
        return
    delay = 1
    while True:
        try:
            queue = DurableQueue(app, dsn)
            app.state.durable_queue = queue
            await queue.run()
            raise RuntimeError("Durable queue exited unexpectedly")
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Durable queue stopped; admission closed. Reconnecting in %ss", delay)
            await asyncio.sleep(delay)
            delay = min(delay * 2, 30)
