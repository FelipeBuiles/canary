import asyncio
import logging
from types import SimpleNamespace

import pytest

from novel_to_comic.server.generation_jobs import (
    GenerationJob,
    _looks_like_timeout_cancellation,
    generation_job_payload,
    generation_worker,
    user_generation_semaphore,
    _account_lane,
    is_parallel_page_draw,
)
from novel_to_comic.server.job_execution import PipelineStageFailed


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
        "caused it. Your work is unchanged. Review the whole page and try a simpler, "
        "more specific change. The provider may be reacting to existing page content, "
        "not just your note."
    )
    assert payload["recoverable"] is True


@pytest.mark.parametrize("error_type", [ValueError, PipelineStageFailed])
@pytest.mark.parametrize("message", [
    "Cast design must cover every character exactly once; rerun Cast.",
    "Cast design returned an invalid character roster; rerun Cast.",
])
def test_generation_job_payload_classifies_cast_roster_failure(message, error_type):
    async def failing_runner():
        raise error_type(message)

    job = GenerationJob(
        id="cast-roster-failure",
        project_name="demo",
        kind="pipeline_stage",
        label="Cast",
        payload={"stage": "cast"},
        sequence=1,
        runner=failing_runner,
    )

    _run_single_job_worker(job)

    payload = generation_job_payload(None, job)
    assert payload["status"] == "failed"
    assert payload["error"] == message
    assert payload["classification"] == "design_error"
    assert payload["user_message"] == (
        "Cast design returned an invalid character roster. "
        "Resume Cast to try the design again."
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


def test_page_lane_runs_twelve_pages_but_keeps_other_work_exclusive():
    app = SimpleNamespace(state=SimpleNamespace())
    lane = _account_lane(app, "user-1")
    release_pages = asyncio.Event()
    release_exclusive = asyncio.Event()
    active = 0
    peak = 0
    entered_pages = asyncio.Event()
    exclusive_entered = asyncio.Event()
    fourth_entered = asyncio.Event()

    async def page(number):
        nonlocal active, peak
        async with lane.enter(True):
            active += 1
            peak = max(peak, active)
            if active == 12:
                entered_pages.set()
            if number == 13:
                fourth_entered.set()
            await release_pages.wait()
            active -= 1

    async def exclusive():
        async with lane.enter(False):
            assert active == 0
            exclusive_entered.set()
            await release_exclusive.wait()

    async def exercise():
        first = [asyncio.create_task(page(number)) for number in range(1, 13)]
        await asyncio.wait_for(entered_pages.wait(), 1)
        other = asyncio.create_task(exclusive())
        await asyncio.sleep(0)
        fourth = asyncio.create_task(page(13))
        await asyncio.sleep(0)
        assert active == 12 and peak == 12
        assert not exclusive_entered.is_set() and not fourth_entered.is_set()
        release_pages.set()
        await asyncio.wait_for(exclusive_entered.wait(), 1)
        assert not fourth_entered.is_set()
        release_exclusive.set()
        await asyncio.wait_for(asyncio.gather(*first, other, fourth), 1)
        assert fourth_entered.is_set()

    asyncio.run(exercise())
    assert peak == 12


def test_parallel_routing_uses_frozen_page_provider():
    job = GenerationJob(
        id="page", project_name="account:book", kind="complete_page_draw",
        label="Page 1", payload={"page_number": 1}, sequence=1, runner=None,
        command=SimpleNamespace(operation="page_draw", arguments={"request": {"provider": "fal-queue"}}),
    )
    assert is_parallel_page_draw(job)
    job.command.arguments["request"]["provider"] = "openai"
    assert is_parallel_page_draw(job)
    job.command.arguments["request"]["provider"] = "vertex-multimodal"
    assert is_parallel_page_draw(job)
    for provider in ("openrouter", "codex-dev"):
        job.command.arguments["request"]["provider"] = provider
        assert not is_parallel_page_draw(job)
    job.command.arguments["request"]["provider"] = "openai"
    job.kind = "cast_reference"
    assert not is_parallel_page_draw(job)


def test_queued_fal_page_cancelled_while_waiting_never_enters_provider(tmp_path, monkeypatch):
    from novel_to_comic.config import Config
    from novel_to_comic.server.admission import Admission
    from novel_to_comic.server.job_commands import command
    from novel_to_comic.server import job_execution
    from novel_to_comic.server.generation_jobs import job_transition_lock, persist_generation_job, run_generation_job

    app = SimpleNamespace(state=SimpleNamespace(
        admission=Admission(tmp_path), generation_jobs={}, generation_job_timeout_seconds=5,
    ))
    from tests.test_complete_page_draw import _compile, _page
    spec = command("page_draw", tmp_path, Config(), request=_compile(tmp_path).request.model_dump(mode="json"),
                   page=_page().model_dump(mode="json"), references=[])
    spec = spec.model_copy(update={"stage": "draw", "user_id": "user-1"})
    job = GenerationJob(
        id="waiting-fal-page", project_name="user-1:book", kind="complete_page_draw",
        label="Page 1", payload={"page_number": 1}, sequence=1, runner=None,
        command=spec, user_id="user-1",
    )
    app.state.generation_jobs[job.id] = job
    called = False

    async def provider(*args):
        nonlocal called
        called = True

    monkeypatch.setattr(job_execution, "execute_command", provider)

    async def exercise():
        async with _account_lane(app, "user-1").enter(False):
            task = asyncio.create_task(run_generation_job(app, job))
            await asyncio.sleep(0)
            async with job_transition_lock(app, "user-1"):
                job.status = "cancelled"
                persist_generation_job(app, job)
        await task

    asyncio.run(exercise())
    assert job.status == "cancelled" and job.started_at is None
    assert not called


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


def test_text_only_translation_does_not_wait_behind_another_projects_image_job(tmp_path, monkeypatch):
    from novel_to_comic.config import Config
    from novel_to_comic.server.admission import Admission
    from novel_to_comic.server.durable_queue import dispatch_lock
    from novel_to_comic.server.generation_jobs import generation_job_payload, run_generation_job
    from novel_to_comic.server.job_commands import command
    from novel_to_comic.server import job_execution

    app = SimpleNamespace(state=SimpleNamespace(
        admission=Admission(tmp_path), generation_jobs={}, generation_job_timeout_seconds=5,
    ))

    def job(identity, project, kind, operation, sequence):
        # Scheduling tests substitute execution; commands must still be valid.
        from tests.test_cast_asset_routes import _bible
        if operation == "style_sample":
            arguments = {"bible": _bible().model_dump(mode="json"), "candidate": {}, "index": 1}
        else:
            from novel_to_comic.lettering.translation import PreparedTranslation
            from novel_to_comic.models.lettering import LetteringStyle, LetteringSettings
            from novel_to_comic.server.job_commands import snapshot
            prepared = PreparedTranslation(target_locale="es", snapshot_sha256="a" * 64,
                model="fixture", states=(), style=LetteringStyle(revision=1),
                settings=LetteringSettings(revision=1), batches=(), estimate={})
            arguments = {"prepared": snapshot(prepared)}
        spec = command(operation, tmp_path, Config(), **arguments).model_copy(update={"stage": "style", "user_id": "user-1"})
        created = GenerationJob(id=identity, project_name=f"user-1:{project}", kind=kind, label=identity,
                                payload={}, sequence=sequence, runner=None, command=spec, user_id="user-1")
        app.state.generation_jobs[identity] = created
        return created

    image = job("image", "carl", "style_sample", "style_sample", 1)
    translation = job("translation", "egg", "lettering_translation", "lettering_translation", 2)
    other_image = job("other-image", "egg", "style_sample", "style_sample", 3)
    assert dispatch_lock("q", translation) == "q:account:user-1:light"
    assert dispatch_lock("q", image) == "q:account:user-1"
    release = asyncio.Event()
    ran = []

    async def execute(_app, current):
        ran.append(current.id)
        if current.id == "image":
            await release.wait()

    monkeypatch.setattr(job_execution, "execute_command", execute)

    async def exercise():
        blocking = asyncio.create_task(run_generation_job(app, image))
        await asyncio.sleep(0.01)
        assert image.status == "running"
        assert generation_job_payload(app, translation)["waiting_for_other_project"] is False
        assert generation_job_payload(app, other_image)["waiting_for_other_project"] is True
        await asyncio.wait_for(run_generation_job(app, translation), 1)
        assert translation.status == "complete" and image.status == "running"
        waiting = asyncio.create_task(run_generation_job(app, other_image))
        await asyncio.sleep(0.01)
        assert other_image.status == "queued"
        release.set()
        await asyncio.wait_for(asyncio.gather(blocking, waiting), 1)

    asyncio.run(exercise())
    assert ran == ["image", "translation", "other-image"]
