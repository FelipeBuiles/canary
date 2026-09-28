"""Durable dispatch tests. Set CANARY_TEST_QUEUE_DSN for real PostgreSQL checks."""
import asyncio
import fcntl
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

from novel_to_comic.config import Config
from novel_to_comic.server.admission import Admission, admission_middleware, mutation_conflicts
from novel_to_comic.server.durable_queue import DurableQueue, dispatch_lock
from novel_to_comic.server.generation_jobs import enqueue_generation_job, persist_generation_job
from novel_to_comic.server.job_commands import command, read_blob, save_blob


def make_app(root):
    return SimpleNamespace(state=SimpleNamespace(
        projects_dir=root, admission=Admission(root), generation_jobs={},
        running_tasks={}, style_tasks={}, event_queues={}, user_generation_semaphores={},
        credit_leases_ready=True, durable_queue_required=True,
        generation_job_timeout_seconds=5,
    ))


def enqueue(app, label):
    spec = command("fixture", app.state.projects_dir / "account" / "book", Config())
    spec = spec.model_copy(update={"stage": "draw", "user_id": "account", "project_id": "book"})
    return enqueue_generation_job(app, "account:book", "complete_page_draw", label,
                                  {"page_number": int(label)}, None, user_id="account", command=spec)


async def until(predicate, timeout=10):
    async with asyncio.timeout(timeout):
        while not predicate():
            await asyncio.sleep(0.02)


def test_blob_integrity_and_deduplication(tmp_path):
    digest = save_blob(tmp_path, b"immutable-input")
    assert save_blob(tmp_path, b"immutable-input") == digest
    assert read_blob(tmp_path, digest) == b"immutable-input"
    (tmp_path / ".jobs" / "inputs" / digest).write_bytes(b"changed")
    with pytest.raises(ValueError, match="changed"):
        read_blob(tmp_path, digest)
    with pytest.raises(ValueError, match="digest"):
        read_blob(tmp_path, "../../state.json")


def test_resource_conflicts_allow_independent_lettering_and_style_selection(tmp_path):
    app = make_app(tmp_path)
    app.state.generation_jobs["page"] = SimpleNamespace(project_name="account:book", kind="complete_page_draw",
                                                       status="running", payload={"page_number": 2})
    assert not mutation_conflicts(app, "account:book", "/pages/1/lettering")
    assert mutation_conflicts(app, "account:book", "/pages/2/lettering")
    assert mutation_conflicts(app, "account:book", "/styles/active")
    app.state.generation_jobs["page"].kind = "style_suggest"
    assert not mutation_conflicts(app, "account:book", "/styles/active")
    assert mutation_conflicts(app, "account:book", "/config")


def test_cover_drawn_after_cast_does_not_hold_back_checkpoint_approval(tmp_path):
    app = make_app(tmp_path)
    app.state.generation_jobs["cover"] = SimpleNamespace(project_name="account:book", kind="project_cover",
                                                        status="running", payload={})
    assert not mutation_conflicts(app, "account:book", "/approve/cast")
    assert mutation_conflicts(app, "account:book", "/config")
    app.state.generation_jobs["plate"] = SimpleNamespace(project_name="account:book", kind="location_plate_regen",
                                                        status="queued", payload={})
    assert mutation_conflicts(app, "account:book", "/approve/cast")


def test_stored_language_switch_waits_only_for_work_that_rewrites_lettering(tmp_path):
    app = make_app(tmp_path)
    app.state.generation_jobs["style"] = SimpleNamespace(project_name="account:book", kind="style_sample",
                                                        status="running", payload={})
    assert not mutation_conflicts(app, "account:book", "/lettering/locale")
    for kind in ("complete_page_draw", "lettering_translation", "pipeline_stage"):
        app.state.generation_jobs["style"].kind = kind
        assert mutation_conflicts(app, "account:book", "/lettering/locale")


def test_restore_distinguishes_unstarted_from_unknown(tmp_path):
    app = make_app(tmp_path)
    queue = DurableQueue(app, "postgresql://unused")
    app.state.durable_queue = queue
    # publish enforces readiness; use a live inert fixture task for admission.
    async def exercise():
        queue.worker = asyncio.create_task(asyncio.sleep(100))
        queue.ready = True
        import time
        queue.last_healthy = time.monotonic()
        first, second = enqueue(app, "1"), enqueue(app, "2")
        second.status = "running"
        persist_generation_job(app, second)
        restarted = make_app(tmp_path)
        recovery = DurableQueue(restarted, "postgresql://unused")
        recovery.restore()
        assert restarted.state.generation_jobs[first.id].status == "queued"
        unknown = restarted.state.generation_jobs[second.id]
        assert unknown.status == "failed" and unknown.phase == "outcome_unknown"
        assert unknown.recoverable is False
        with restarted.state.admission.journal() as db:
            payload = json.loads(db.execute("SELECT payload FROM jobs WHERE id=?", (second.id,)).fetchone()[0])
        assert payload["phase"] == "outcome_unknown"
        queue.worker.cancel()
        await asyncio.gather(queue.worker, return_exceptions=True)
    asyncio.run(exercise())


def test_hard_exit_releases_volume_owner_and_restores_job_states(tmp_path):
    child = subprocess.run(
        [sys.executable, "-c", """import asyncio
import fcntl
import os
import sys
import time
from pathlib import Path
from tests.test_durable_queue import make_app, enqueue
from novel_to_comic.server.durable_queue import DurableQueue
from novel_to_comic.server.generation_jobs import persist_generation_job

async def crash(root):
    app = make_app(root)
    queue = DurableQueue(app, "postgresql://unused")
    app.state.durable_queue = queue
    queue.worker = asyncio.create_task(asyncio.sleep(60))
    queue.ready = True
    queue.last_healthy = time.monotonic()
    enqueue(app, "1")
    started = enqueue(app, "2")
    started.status = "running"
    persist_generation_job(app, started)
    lock = (root / ".queue-owner.lock").open("a+b")
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    os._exit(73)

asyncio.run(crash(Path(sys.argv[1])))
""", str(tmp_path)],
        cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, timeout=10,
    )
    assert child.returncode == 73, child.stderr
    with (tmp_path / ".queue-owner.lock").open("a+b") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    recovered = make_app(tmp_path)
    DurableQueue(recovered, "postgresql://unused").restore()
    jobs = {job.label: job for job in recovered.state.generation_jobs.values()}
    assert jobs["1"].status == "queued"
    assert jobs["2"].status == "failed"
    assert jobs["2"].phase == "outcome_unknown"
    assert jobs["2"].recoverable is False


@pytest.mark.parametrize("provider", ["fal-queue", "openai"])
def test_page_dispatch_has_three_locks_without_changing_other_account_work(tmp_path, provider):
    from novel_to_comic.server.generation_jobs import GenerationJob

    pages = [GenerationJob(
        id=str(number), project_name="account:book", kind="complete_page_draw",
        label=str(number), payload={"page_number": number}, sequence=number, runner=None,
        user_id="account",
        command=SimpleNamespace(operation="page_draw", arguments={"request": {"provider": provider}}),
    ) for number in range(1, 5)]
    locks = [dispatch_lock("queue", page) for page in pages]
    assert len(set(locks[:3])) == 3
    assert locks[0] == locks[3]
    assert dispatch_lock("queue", SimpleNamespace(user_id="account", kind="pipeline_stage", command=None)) == "queue:account:account"


def test_cancel_queued_pages_preserves_running_work_and_survives_restore(tmp_path):
    from unittest.mock import AsyncMock

    app = make_app(tmp_path)
    queue = DurableQueue(app, "postgresql://unused")
    app.state.durable_queue = queue

    async def exercise():
        queue.worker = asyncio.create_task(asyncio.sleep(100))
        queue.ready = True
        import time
        queue.last_healthy = time.monotonic()
        waiting, running = enqueue(app, "1"), enqueue(app, "2")
        running.status = "running"
        persist_generation_job(app, running)
        with app.state.admission.journal() as db:
            db.execute("UPDATE operation_outbox SET dispatched=77 WHERE id=?", (waiting.id,))
        queue.backend.job_manager.cancel_job_by_id_async = AsyncMock(return_value=False)
        cancelled = await queue.cancel_queued_pages(project_name="account:book", user_id="account")
        assert cancelled == [waiting.id]
        queue.backend.job_manager.cancel_job_by_id_async.assert_awaited_once_with(77, abort=False)
        assert waiting.status == "cancelled" and waiting.started_at is None
        assert running.status == "running"
        assert await queue.cancel_queued_pages(project_name="account:book", user_id="account") == []
        restored = make_app(tmp_path)
        DurableQueue(restored, "postgresql://unused").restore()
        assert restored.state.generation_jobs[waiting.id].status == "cancelled"
        queue.worker.cancel()
        await asyncio.gather(queue.worker, return_exceptions=True)

    asyncio.run(exercise())


def test_cancel_route_is_admitted_while_page_jobs_make_project_busy(tmp_path):
    from fastapi import Response
    from novel_to_comic.server.auth import get_current_user

    app = make_app(tmp_path)
    app.dependency_overrides = {get_current_user: lambda: "account"}
    app.state.generation_jobs["waiting"] = SimpleNamespace(
        project_name="account:book", kind="complete_page_draw", status="queued",
    )
    request = SimpleNamespace(
        url=SimpleNamespace(path="/api/projects/book/jobs/cancel-queued-pages", query=""),
        method="POST", app=app, headers={}, cookies={}, body=lambda: asyncio.sleep(0, result=b""),
    )

    async def next_handler(_request):
        return Response("ok", status_code=200)

    response = asyncio.run(admission_middleware(request, next_handler))
    assert response.status_code == 200


@pytest.mark.parametrize("scheduler_status", ["failed", "cancelled", "aborted"])
@pytest.mark.parametrize("starts_during_query", [False, True])
def test_failed_dispatch_reconciles_only_unstarted_operations(tmp_path, monkeypatch, scheduler_status, starts_during_query):
    from novel_to_comic.server.generation_jobs import GenerationJob

    app = make_app(tmp_path)
    queue = DurableQueue(app, "postgresql://unused")
    job = GenerationJob(id="waiting", project_name="account:book", kind="complete_page_draw",
                        label="55", payload={"page_number": 55}, sequence=1, runner=None)
    app.state.generation_jobs[job.id] = job
    persist_generation_job(app, job)
    with app.state.admission.journal() as db:
        db.execute("INSERT INTO operation_outbox VALUES(?,?,?)", (job.id, "{}", 63))

    async def query(sql, **arguments):
        assert arguments == {"ids": [63], "queue": queue.queue_name}
        assert "'failed','cancelled','aborted'" in sql
        if starts_during_query:
            job.status = "running"
        return [{"id": 63, "status": scheduler_status}]

    monkeypatch.setattr(queue.backend.connector, "execute_query_all_async", query)
    asyncio.run(queue.reconcile_failed_dispatches())
    if starts_during_query:
        assert job.status == "running"
    else:
        assert job.status == "failed"
        assert job.phase == "dispatch" and job.recoverable is True
        assert job.started_at is None and job.finished_at is not None
        with app.state.admission.journal() as db:
            saved = json.loads(db.execute("SELECT payload FROM jobs WHERE id=?", (job.id,)).fetchone()[0])
            assert db.execute("SELECT dispatched FROM operation_outbox WHERE id=?", (job.id,)).fetchone()[0] == 63
        assert saved["status"] == "failed"


@pytest.mark.skipif(not os.getenv("CANARY_TEST_QUEUE_DSN"), reason="requires isolated PostgreSQL")
def test_postgres_restart_fifo_and_no_ambiguous_redelivery(tmp_path, monkeypatch):
    from novel_to_comic.server import job_execution
    calls = []
    entered = asyncio.Event()
    release = asyncio.Event()
    async def provider_free(app, job):
        calls.append(job.label)
        if job.label == "1":
            entered.set()
            await release.wait()
    monkeypatch.setattr(job_execution, "execute_command", provider_free)

    async def exercise():
        app = make_app(tmp_path)
        queue = DurableQueue(app, os.environ["CANARY_TEST_QUEUE_DSN"])
        app.state.durable_queue = queue
        worker = asyncio.create_task(queue.run())
        await until(lambda: queue.healthy)
        first, second, third = enqueue(app, "1"), enqueue(app, "2"), enqueue(app, "3")
        await asyncio.wait_for(entered.wait(), 10)
        assert calls == ["1"]
        worker.cancel()
        await asyncio.wait_for(asyncio.gather(worker, return_exceptions=True), 10)
        assert first.status == "failed" and first.phase == "outcome_unknown"
        assert second.status == third.status == "queued"
        resumed = make_app(tmp_path)
        recovery = DurableQueue(resumed, os.environ["CANARY_TEST_QUEUE_DSN"])
        resumed.state.durable_queue = recovery
        worker2 = asyncio.create_task(recovery.run())
        try:
            await until(lambda: resumed.state.generation_jobs.get(third.id) is not None
                        and resumed.state.generation_jobs[third.id].status == "complete", timeout=45)
            assert calls == ["1", "2", "3"]
            # Even explicit duplicate dispatches cannot replay a terminal operation.
            await recovery.task.defer_async(operation_id=first.id)
            await recovery.task.defer_async(operation_id=second.id)
            await asyncio.sleep(1)
            assert calls == ["1", "2", "3"]
        finally:
            worker2.cancel()
            await asyncio.gather(worker2, return_exceptions=True)
    asyncio.run(exercise())


@pytest.mark.parametrize("brief", ["shared scene brief", None])
def test_style_batch_waits_for_siblings_and_preserves_concurrent_state(tmp_path, monkeypatch, brief):
    from novel_to_comic.server import style_jobs
    from novel_to_comic.server.generation_jobs import GenerationJob
    from novel_to_comic.state import StageStatus, create_initial_state, load_state, save_state
    from tests.test_style_stage import _bible
    from unittest.mock import AsyncMock

    state = create_initial_state("book", "novel.txt")
    state.stages["style"].status = StageStatus.RUNNING
    save_state(state, tmp_path)
    candidates = [style_jobs.style.normalize_suggestion({"id": str(i), "label": f"Style {i}"}) for i in range(3)]
    monkeypatch.setattr(style_jobs.style, "generate_suggestions", AsyncMock(return_value=(candidates, None)))
    brief_author = AsyncMock(return_value=brief)
    monkeypatch.setattr(style_jobs.style, "ensure_style_sample_brief", brief_author)

    async def exercise():
        app = make_app(tmp_path)
        release = asyncio.Event()
        failed = asyncio.Event()
        async def image(config, bible, output, **kwargs):
            assert kwargs["brief"] == brief
            if kwargs["candidate_id"] == candidates[0]["id"]:
                failed.set()
                raise RuntimeError("proof failed")
            await release.wait()
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(b"proof")
        monkeypatch.setattr(style_jobs.style, "generate_sample_image", image)
        job = GenerationJob(id="batch", project_name="account:book", kind="style_suggest", label="Styles",
            payload={}, sequence=1, runner=None, command=command("style_suggest", tmp_path, Config(),
                bible=_bible().model_dump(mode="json"), lifecycle_owned=True))
        app.state.generation_jobs[job.id] = job
        task = asyncio.create_task(style_jobs.execute_style(app, job, tmp_path, Config()))
        await until(lambda: failed.is_set() or task.done(), timeout=2)
        if task.done():
            await task
        await asyncio.sleep(0)
        assert not task.done()
        edited = load_state(tmp_path)
        edited.stages["finish"].error = "concurrent lettering edit"
        save_state(edited, tmp_path)
        release.set()
        with pytest.raises(RuntimeError, match="1 style proof"):
            await task
        assert [p["status"] for p in job.payload["proofs"].values()] == ["failed", "complete", "complete"]
        final = load_state(tmp_path)
        assert final.stages["style"].status == StageStatus.FAILED
        assert final.stages["style"].items_done == 2
        assert final.stages["finish"].error == "concurrent lettering edit"
        brief_author.assert_awaited_once()
    asyncio.run(exercise())


def test_outbox_admission_rolls_back_job_when_command_insert_fails(tmp_path):
    app = make_app(tmp_path)
    queue = DurableQueue(app, "postgresql://unused")
    app.state.durable_queue = queue
    async def exercise():
        import time
        queue.worker = asyncio.create_task(asyncio.sleep(100))
        queue.ready = True
        queue.last_healthy = time.monotonic()
        with app.state.admission.journal() as db:
            db.execute("CREATE TRIGGER reject_command BEFORE INSERT ON operation_outbox BEGIN SELECT RAISE(ABORT, 'disk fixture'); END")
        try:
            with pytest.raises(Exception, match="disk fixture"):
                enqueue(app, "1")
            with app.state.admission.journal() as db:
                assert db.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 0
                assert db.execute("SELECT COUNT(*) FROM operation_outbox").fetchone()[0] == 0
            assert not app.state.generation_jobs
        finally:
            queue.worker.cancel()
            await asyncio.gather(queue.worker, return_exceptions=True)
    asyncio.run(exercise())


def test_queue_supervisor_reconnects_after_failure(tmp_path, monkeypatch):
    from novel_to_comic.server import durable_queue
    app = make_app(tmp_path)
    monkeypatch.setenv("CANARY_QUEUE_DATABASE_URL", "postgresql://fixture")
    attempts = []
    async def exercise():
        ready = asyncio.Event()
        class FakeQueue:
            def __init__(self, app, dsn):
                attempts.append(self)
            async def run(self):
                if len(attempts) == 1:
                    raise ConnectionError("temporary outage")
                ready.set()
                await asyncio.Event().wait()
        monkeypatch.setattr(durable_queue, "DurableQueue", FakeQueue)
        task = asyncio.create_task(durable_queue.initialize_queue(app))
        try:
            await asyncio.wait_for(ready.wait(), 3)
            assert app.state.durable_queue is attempts[1]
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
    asyncio.run(exercise())


def test_page_handler_reconstructs_frozen_bytes_and_ocr(tmp_path, monkeypatch):
    from unittest.mock import AsyncMock
    from novel_to_comic.server import job_execution
    from novel_to_comic import page_drawing
    from novel_to_comic.page_ocr import GatewayPageOCRAdapter
    from tests.test_complete_page_draw import _compile, _page

    compiled = _compile(tmp_path)
    captured = {}
    work = AsyncMock(return_value="saved")
    def execution(**kwargs):
        captured.update(kwargs)
        return work, None
    monkeypatch.setattr(page_drawing, "page_draw_execution", execution)
    monkeypatch.setattr(page_drawing, "complete_page_adapter", lambda config, **kwargs: "adapter")
    monkeypatch.setattr(job_execution.TargetArtifacts, "read_plan", lambda self: SimpleNamespace(pages=[_page()]))
    spec = command("page_draw", tmp_path, Config(),
        request=compiled.request.model_dump(mode="json"), page=_page().model_dump(mode="json"),
        references=[save_blob(tmp_path, data) for data in compiled.reference_bytes],
        edit_source=save_blob(tmp_path, compiled.edit_source_bytes), ocr=True)
    # Round trip the actual command, as a restarted worker does.
    spec = type(spec).model_validate_json(spec.model_dump_json())
    job = SimpleNamespace(command=spec, project_name="account:book")
    result, _ = asyncio.run(job_execution._operate(make_app(tmp_path), job, tmp_path, Config()))
    assert result == "saved"
    assert captured["compiled"] == compiled
    assert isinstance(captured["ocr"], GatewayPageOCRAdapter)
    assert captured["page"] == _page()
    work.assert_awaited_once()


def test_asset_request_survives_command_roundtrip():
    from pydantic import TypeAdapter
    from novel_to_comic.asset_generation import AbstractStyleProofInput, NonPanelRequest, compile_non_panel_request
    from novel_to_comic.generation_input import GenerationPromptInput
    from novel_to_comic.server.job_commands import snapshot
    from tests.test_asset_generation import _empty_plan
    config = Config(image_model="image-gemini-pro", style_template="Woodblock print")
    request = compile_non_panel_request(config, AbstractStyleProofInput(
        asset_identity="style_sample:1", selected_style_text=config.style_template,
        prompt=GenerationPromptInput(visual_brief="Indigo and ochre shapes", width=819, height=1024, generation_shape="portrait")),
        reference_plan=_empty_plan(config))
    restored = TypeAdapter(NonPanelRequest).validate_python(json.loads(json.dumps(snapshot(request))))
    assert restored.compiled_request_sha256 == request.compiled_request_sha256
    assert restored.execution_fingerprint == request.execution_fingerprint
    assert restored.input.asset_kind == request.input.asset_kind


def test_production_readiness_requires_queue_even_when_other_checks_pass(tmp_path, monkeypatch):
    from novel_to_comic.server import app as app_module
    app = app_module.create_app(tmp_path, dev=True)
    monkeypatch.setattr(app_module, "_readiness_result", lambda: (True, {"litellm": "ok"}))
    endpoint = next(route.endpoint for route in app.routes if route.path == "/api/health/ready")
    response = endpoint()
    assert response.status_code == 503
    assert json.loads(response.body)["checks"]["generation_queue"] != "ok"
    assert app.state.durable_queue_required is True
    assert app.state.durable_queue is None


def test_draw_batch_preparation_keeps_heartbeat_alive_and_announces_only_queued_pages(tmp_path, monkeypatch):
    import threading
    from novel_to_comic.server.routers import pages
    entered, release = threading.Event(), threading.Event()
    target = SimpleNamespace(read_book_edition=lambda: object())
    def prepare(**kwargs):
        entered.set()
        assert release.wait(2), "Preparation blocked the event loop heartbeat"
        return target, object(), [(1, SimpleNamespace(page_number=1), object())]
    monkeypatch.setattr(pages, "prepare_undrawn_pages", prepare)
    monkeypatch.setattr(pages, "ensure_current_page_edition", lambda *args: None)
    app = make_app(tmp_path)
    events = asyncio.Queue()
    app.state.event_queues["account:book"] = events
    def reject(*args, **kwargs):
        raise RuntimeError("publication failed")
    monkeypatch.setattr(pages, "enqueue_complete_page_draw", reject)
    async def exercise():
        task = asyncio.create_task(pages.enqueue_all_undrawn_pages(
            SimpleNamespace(app=app), project_id="book", user_id="account", project_dir=tmp_path, config=Config()))
        await until(entered.is_set)
        # This coroutine stands in for the queue heartbeat. It must run while
        # preparation waits, rather than only after the entire batch returns.
        release.set()
        with pytest.raises(RuntimeError, match="publication failed"):
            await task
        assert events.empty()  # No phantom page_start before durable publication.
    asyncio.run(exercise())


def test_draw_dispatch_failure_persists_stage_failure(tmp_path, monkeypatch):
    from novel_to_comic.server import job_execution
    from novel_to_comic.server.routers import pipeline
    from novel_to_comic.state import create_initial_state, save_state, load_state, begin_stage, StageStatus
    state = create_initial_state("book", "novel.txt")
    save_state(state, tmp_path)
    async def initialize_then_fail(stage, config, directory, state, *args, **kwargs):
        begin_stage(state, "draw", 63)
        save_state(state, directory)
        raise RuntimeError("Durable generation queue is unavailable")
    monkeypatch.setattr(pipeline, "_run_stage_with_credits", initialize_then_fail)
    spec = command("pipeline", tmp_path, Config(), queue_pages=True).model_copy(update={"stage": "draw"})
    job = SimpleNamespace(command=spec, project_name="account:book", payload={"stage": "draw"})
    app = make_app(tmp_path)
    with pytest.raises(RuntimeError, match="queue is unavailable"):
        asyncio.run(job_execution._pipeline(app, job, tmp_path, Config()))
    final = load_state(tmp_path).stages["draw"]
    assert final.status == StageStatus.FAILED
    assert final.items_done == 0 and final.items_total == 63
    assert final.error == "Durable generation queue is unavailable"


def test_failed_stage_raises_stage_specific_error(tmp_path, monkeypatch):
    from novel_to_comic.server import job_execution
    from novel_to_comic.server.routers import pipeline
    from novel_to_comic.state import create_initial_state, save_state, fail_stage
    save_state(create_initial_state("book", "novel.txt"), tmp_path)
    async def settle_failed(stage, config, directory, state, *args, **kwargs):
        fail_stage(state, "cast", "Cast rejected the reference sheet")
    monkeypatch.setattr(pipeline, "_run_stage_with_credits", settle_failed)
    spec = command("pipeline", tmp_path, Config()).model_copy(update={"stage": "cast"})
    job = SimpleNamespace(command=spec, project_name="account:book", payload={"stage": "cast"})
    with pytest.raises(job_execution.PipelineStageFailed, match="reference sheet"):
        asyncio.run(job_execution._pipeline(make_app(tmp_path), job, tmp_path, Config()))


@pytest.mark.parametrize("settled", [False, True])
def test_job_failure_does_not_report_settled_stage_wrapper(tmp_path, monkeypatch, settled):
    from novel_to_comic.server import generation_jobs, telemetry
    from novel_to_comic.server.job_execution import PipelineStageFailed
    captured = []
    monkeypatch.setattr(telemetry, "capture_exception", lambda exc, **kwargs: captured.append(exc))
    error = PipelineStageFailed("Plan failed") if settled else RuntimeError("orchestration failed")
    def runner():
        raise error
    job = generation_jobs.GenerationJob(id="job-1", project_name="account:book", kind="pipeline_stage",
                                        label="Plan", payload={}, sequence=1, runner=runner)
    asyncio.run(generation_jobs._run_generation_job(make_app(tmp_path), job))
    assert job.status == "failed" and job.error == str(error)
    assert captured == ([] if settled else [error])


@pytest.mark.parametrize("failure_boundary", ["estimate_stage_credit_reservation", "reserve_credits"])
@pytest.mark.parametrize("failure_kind", ["connection", "estimation", "maintenance", "balance"])
def test_reservation_failure_reports_original_unexpected_cause_once(
    tmp_path, monkeypatch, failure_boundary, failure_kind,
):
    from fastapi import HTTPException
    from novel_to_comic.server import credited_job, generation_jobs, job_execution, telemetry
    from novel_to_comic.server.routers import pipeline
    from novel_to_comic.state import StageStatus, create_initial_state, load_state, save_state

    errors = {
        "connection": ConnectionError("Billing database unavailable"),
        "estimation": ValueError("Invalid reservation estimate"),
        "maintenance": HTTPException(503, {"error": "credit_reservation_reconciliation", "message": "Ledger needs maintenance"}),
        "balance": HTTPException(402, {"error": "insufficient_credits", "message": "Insufficient credits"}),
    }
    error = errors[failure_kind]
    save_state(create_initial_state("book", "novel.txt"), tmp_path)
    app = make_app(tmp_path)
    captured = []
    monkeypatch.setattr(telemetry, "capture_exception", lambda exc, **fields: captured.append((exc, fields)))
    monkeypatch.setattr(credited_job, "get_db", lambda: object())
    monkeypatch.setattr(credited_job, "estimate_stage_credit_reservation", lambda *args: 10)
    monkeypatch.setattr(pipeline, "capture_server_event", lambda *args, **kwargs: None)

    def fail(*args, **kwargs):
        raise error

    async def unexpected_stage(*args, **kwargs):
        pytest.fail("A denied reservation must not start generation")

    monkeypatch.setattr(credited_job, failure_boundary, fail)
    monkeypatch.setattr(pipeline, "_run_stage", unexpected_stage)
    spec = command("pipeline", tmp_path, Config()).model_copy(
        update={"stage": "extract", "user_id": "account", "project_id": "book"},
    )
    pipeline_job = SimpleNamespace(command=spec, project_name="account:book", payload={"stage": "extract"})

    async def runner():
        await job_execution._pipeline(app, pipeline_job, tmp_path, Config())

    job = generation_jobs.GenerationJob(
        id="reservation-failure", project_name="account:book", kind="pipeline_stage",
        label="Extract", payload={}, sequence=1, runner=runner,
    )
    asyncio.run(generation_jobs._run_generation_job(app, job))
    expected_message = error.detail["message"] if isinstance(error, HTTPException) else str(error)
    assert job.status == "failed" and job.error == expected_message
    state = load_state(tmp_path)
    assert state.stages["extract"].status == StageStatus.FAILED
    assert state.stages["extract"].error == expected_message
    assert captured == ([] if failure_kind == "balance" else [(error, {"user_id": "account", "stage": "extract"})])


@pytest.mark.parametrize("sibling_queued", [False, True])
def test_restore_closes_the_style_stage_a_hard_stop_left_running(tmp_path, sibling_queued):
    """An interrupted Style batch must not leave the room 'generating' forever."""
    from novel_to_comic.server.generation_jobs import GenerationJob
    from novel_to_comic.state import StageStatus, begin_stage, create_initial_state, load_state, save_state

    project = tmp_path / "account" / "book"
    project.mkdir(parents=True)
    state = create_initial_state("book", "novel.txt")
    begin_stage(state, "style", total=6)
    save_state(state, project)
    app = make_app(tmp_path)
    DurableQueue(app, "postgresql://unused")  # creates the journal schema

    def style_job(job_id, status):
        spec = command("style_suggest", project, Config(), lifecycle_owned=True, bible={})
        spec = spec.model_copy(update={"stage": "style", "user_id": "account", "project_id": "book"})
        job = GenerationJob(id=job_id, project_name="account:book", kind="style_suggest", label="Styles",
                            payload={"proofs": {"1": {"status": "complete"}, "2": {"status": "running"}}},
                            sequence=1, runner=None, command=spec, status=status)
        job.user_id = "account"
        with app.state.admission.journal() as db:
            db.execute("INSERT INTO operation_outbox (id, command) VALUES (?, ?)", (job.id, spec.model_dump_json()))
        persist_generation_job(app, job)

    style_job("interrupted", "running")
    if sibling_queued:
        style_job("waiting", "queued")
    DurableQueue(make_app(tmp_path), "postgresql://unused").restore()
    style = load_state(project).stages["style"]
    if sibling_queued:
        assert style.status == StageStatus.RUNNING
    else:
        assert style.status == StageStatus.FAILED
        assert style.items_done == 1


def test_page_replan_is_a_paid_whole_project_mutation():
    # One planning call, so it needs a receipt; it rewrites the book plan, so it
    # waits for every running job instead of running beside page draws.
    from novel_to_comic.server.admission import _PAID, _TARGETED

    assert _PAID.fullmatch("/pages/16/replan")
    assert not _TARGETED.fullmatch("/pages/16/replan")


def admit_live(app, label):
    """Admit one durable operation through an inert live queue fixture."""
    import time

    queue = DurableQueue(app, "postgresql://unused")
    app.state.durable_queue = queue
    queue.worker = asyncio.create_task(asyncio.sleep(100))
    queue.ready, queue.last_healthy = True, time.monotonic()
    return queue, enqueue(app, label)


@pytest.mark.parametrize("pause", ["drain", "credit_leases"])
def test_paused_operation_stays_unstarted_until_admission_reopens(tmp_path, monkeypatch, pause):
    from novel_to_comic.server import generation_jobs, job_execution

    app = make_app(tmp_path)
    executed = []

    async def execute_command(_app, job):
        executed.append(job.id)

    monkeypatch.setattr(job_execution, "execute_command", execute_command)

    async def exercise():
        queue, job = admit_live(app, "1")
        if pause == "drain":
            app.state.admission.set_draining(True)
        else:
            app.state.credit_leases_ready = False
        running = asyncio.create_task(generation_jobs.run_generation_job(app, job))
        await asyncio.sleep(1.2)
        # Unstarted work is safe to preserve across a deployment restart.
        assert job.status == "queued" and job.started_at is None and not executed
        if pause == "drain":
            app.state.admission.set_draining(False)
        else:
            app.state.credit_leases_ready = True
        await asyncio.wait_for(running, 5)
        queue.worker.cancel()
        await asyncio.gather(queue.worker, return_exceptions=True)
        return job

    job = asyncio.run(exercise())
    assert executed == [job.id]
    assert job.status == "complete"


def test_shutdown_while_drained_leaves_operation_queued_for_restart(tmp_path, monkeypatch):
    from novel_to_comic.server import generation_jobs, job_execution

    app = make_app(tmp_path)
    monkeypatch.setattr(job_execution, "execute_command", lambda *_: pytest.fail("must not execute"))

    async def exercise():
        queue, job = admit_live(app, "1")
        app.state.admission.set_draining(True)
        running = asyncio.create_task(generation_jobs.run_generation_job(app, job))
        await asyncio.sleep(0.1)
        running.cancel()
        queue.worker.cancel()
        await asyncio.gather(running, queue.worker, return_exceptions=True)
        return job

    job = asyncio.run(exercise())
    assert job.status == "queued" and job.started_at is None
    restarted = make_app(tmp_path)
    DurableQueue(restarted, "postgresql://unused").restore()
    assert restarted.state.generation_jobs[job.id].status == "queued"
