import asyncio
import logging
from types import SimpleNamespace

from novel_to_comic.server.generation_jobs import (
    GenerationJob,
    _looks_like_timeout_cancellation,
    generation_job_payload,
    generation_worker,
    user_generation_semaphore,
)


class _OneJobQueue:
    def __init__(self, job):
        self.job = job
        self.done_count = 0

    async def get(self):
        if self.done_count:
            await asyncio.sleep(3600)
        return self.job

    def task_done(self):
        self.done_count += 1


async def _failing_runner():
    raise ValueError("image prohibited")


def _run_single_job_worker(job):
    app = SimpleNamespace(
        state=SimpleNamespace(
            generation_job_timeout_seconds=5,
            generation_queue=_OneJobQueue(job),
        )
    )

    async def run():
        task = asyncio.create_task(generation_worker(app))
        while app.state.generation_queue.done_count == 0:
            await asyncio.sleep(0)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    asyncio.run(run())


def test_generation_job_failure_does_not_log_traceback_by_default(caplog, monkeypatch):
    monkeypatch.delenv("CANARY_LOG_JOB_TRACEBACKS", raising=False)
    job = GenerationJob(
        id="abc123456789",
        project_name="demo",
        kind="panel_regen",
        label="scene_001 / panel 001",
        payload={},
        sequence=1,
        runner=_failing_runner,
    )

    with caplog.at_level(logging.ERROR, logger="canary.generation"):
        _run_single_job_worker(job)

    assert job.status == "failed"
    assert job.error == "image prohibited"
    failed_records = [
        record for record in caplog.records if "Job failed" in record.getMessage()
    ]
    assert len(failed_records) == 1
    assert not failed_records[0].exc_info


def test_generation_job_payload_classifies_provider_block():
    async def blocked_runner():
        raise RuntimeError(
            "AI gateway request failed for complete_page_draw "
            "(model=gemini-3-pro-image, endpoint=/v1/images/edits): "
            "400 Bad Request — Vertex response did not contain image bytes: "
            "no candidates returned | prompt_feedback: "
            "block_reason=BlockedReason.OTHER"
        )

    job = GenerationJob(
        id="blocked-page-16",
        project_name="demo",
        kind="complete_page_draw",
        label="Page 16",
        payload={"page_number": 16},
        sequence=1,
        runner=blocked_runner,
    )

    _run_single_job_worker(job)

    payload = generation_job_payload(None, job)
    assert payload["status"] == "failed"
    assert payload["classification"] == "provider_blocked"
    assert payload["user_message"] == (
        "The image provider declined this scene but did not say which detail "
        "caused it. Your work is unchanged."
    )
    assert payload["recoverable"] is True


def test_generation_job_failure_traceback_can_be_enabled(caplog, monkeypatch):
    monkeypatch.setenv("CANARY_LOG_JOB_TRACEBACKS", "1")
    job = GenerationJob(
        id="abc123456789",
        project_name="demo",
        kind="panel_regen",
        label="scene_001 / panel 001",
        payload={},
        sequence=1,
        runner=_failing_runner,
    )

    with caplog.at_level(logging.ERROR, logger="canary.generation"):
        _run_single_job_worker(job)

    failed_records = [
        record for record in caplog.records if "Job failed" in record.getMessage()
    ]
    assert len(failed_records) == 1
    assert failed_records[0].exc_info is not None


def test_generation_job_recognizes_provider_cancel_after_worker_timeout():
    exc = RuntimeError("499 CANCELLED. The operation was cancelled.")

    assert _looks_like_timeout_cancellation(exc, elapsed=600.0, timeout_seconds=600)
    assert not _looks_like_timeout_cancellation(exc, elapsed=20.0, timeout_seconds=600)


def test_per_user_generation_semaphore_serializes_same_user(monkeypatch):
    monkeypatch.setenv("CANARY_MAX_ACTIVE_GENERATION_JOBS_PER_USER", "1")
    app = SimpleNamespace(
        state=SimpleNamespace(user_generation_semaphores={})
    )
    active = 0
    peak = 0

    async def work():
        nonlocal active, peak
        async with user_generation_semaphore(app, "user-1"):
            active += 1
            peak = max(peak, active)
            await asyncio.sleep(0.01)
            active -= 1

    async def run():
        await asyncio.gather(work(), work(), work())

    asyncio.run(run())

    assert peak == 1


def test_transport_ambiguity_survives_page_phase_annotation():
    from novel_to_comic.ai.errors import AITransportError
    async def runner():
        error = AITransportError("response lost", phase="ambiguous_submission")
        error.page_failure_phase = "generation"
        raise error
    job = GenerationJob(id="ambiguous", project_name="project", kind="page_generate",
                        label="page", payload={}, sequence=1, runner=runner)
    _run_single_job_worker(job)
    assert job.phase == "ambiguous_submission"
    assert generation_job_payload(None, job)["phase"] == "ambiguous_submission"
