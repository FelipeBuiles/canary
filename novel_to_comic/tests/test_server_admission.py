"""Failure boundaries at the HTTP admission and event fanout seams."""
import asyncio
from functools import wraps
from types import SimpleNamespace

import httpx
from fastapi import FastAPI

from novel_to_comic.server.admission import Admission, admission_middleware
from novel_to_comic.server.auth import get_current_user
from novel_to_comic.server.event_channel import EventChannel


def run_async(test):
    @wraps(test)
    def run(*args, **kwargs):
        return asyncio.run(test(*args, **kwargs))
    return run


def app_at(root):
    app = FastAPI()
    app.state.admission = Admission(root)
    app.state.running_tasks = {}
    app.state.style_tasks = {}
    app.state.generation_jobs = {}
    app.dependency_overrides[get_current_user] = lambda: "account"
    app.middleware("http")(admission_middleware)
    return app


@run_async
async def test_lost_response_replay_survives_restart_and_conflicting_input(tmp_path):
    calls = []

    def build():
        app = app_at(tmp_path)

        @app.post("/api/projects/book/cover")
        async def paid():
            calls.append("paid")
            return {"job": {"id": "accepted-once"}}

        return app

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=build()), base_url="http://test") as client:
        accepted = await client.post("/api/projects/book/cover", json={"force": True}, headers={"Idempotency-Key": "action"})
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=build()), base_url="http://test") as client:
        replay = await client.post("/api/projects/book/cover", json={"force": True}, headers={"Idempotency-Key": "action"})
        conflict = await client.post("/api/projects/book/cover", json={"force": False}, headers={"Idempotency-Key": "action"})
    assert replay.json() == accepted.json()
    assert replay.headers["Idempotency-Replayed"] == "true"
    assert conflict.status_code == 409
    assert calls == ["paid"]


@run_async
async def test_interrupted_request_is_never_redispatched(tmp_path):
    app = app_at(tmp_path)
    calls = []

    @app.post("/api/projects/book/cover")
    async def paid():
        calls.append("paid")
        raise RuntimeError("process interrupted after admission")

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test") as client:
        first = await client.post("/api/projects/book/cover", headers={"Idempotency-Key": "action"})
        retry = await client.post("/api/projects/book/cover", headers={"Idempotency-Key": "action"})
    assert first.status_code == 500
    assert retry.status_code == 409
    assert retry.json()["detail"]["code"] == "idempotency_indeterminate"
    assert calls == ["paid"]


@run_async
async def test_admission_serializes_delete_with_queue_publication_and_drain(tmp_path):
    app = app_at(tmp_path)
    entered, release = asyncio.Event(), asyncio.Event()
    deleted = []

    @app.post("/api/projects/book/cover")
    async def paid():
        entered.set()
        await release.wait()
        app.state.generation_jobs["job"] = SimpleNamespace(project_name="account:book", status="queued")
        return {"job": "job"}

    @app.delete("/api/projects/book")
    async def delete():
        deleted.append(True)
        return {"deleted": True}

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        pending = asyncio.create_task(client.post("/api/projects/book/cover", headers={"Idempotency-Key": "action"}))
        await entered.wait()
        deletion = asyncio.create_task(client.delete("/api/projects/book"))
        await asyncio.sleep(0)
        assert not deleted
        release.set()
        assert (await pending).status_code == 200
        assert (await deletion).status_code == 409
        app.state.admission.draining = True
        rejected = await client.post("/api/projects/book/cover", headers={"Idempotency-Key": "new-action"})
        replay = await client.post("/api/projects/book/cover", headers={"Idempotency-Key": "action"})
    assert rejected.status_code == 503
    assert replay.status_code == 200
    assert not deleted


@run_async
async def test_each_tab_receives_pipeline_events_and_reconnect_history():
    channel = EventChannel()
    first, second = channel.subscribe(), channel.subscribe()
    events = [{"type": "stage_start", "stage": "cast"}, {"type": "pipeline_done"}]
    for event in events:
        channel.put_nowait(event)
    assert [await first.get(), await first.get()] == events
    assert [await second.get(), await second.get()] == events
    channel.unsubscribe(first)
    reconnect = channel.subscribe()
    assert [await reconnect.get(), await reconnect.get()] == events


def test_recoverable_job_status_survives_process_restart(tmp_path):
    from novel_to_comic.server.generation_jobs import (
        enqueue_generation_job, recovered_generation_jobs,
    )

    app = app_at(tmp_path)
    app.state.generation_queue = asyncio.Queue()

    async def work():
        raise AssertionError("Recovery must not execute paid work")

    queued = enqueue_generation_job(
        app, "account:book", "character_ref_regen", "Ada",
        {"char_id": "ada"}, work,
    )
    restarted = app_at(tmp_path)
    jobs = recovered_generation_jobs(restarted, "account:book")
    assert jobs[0]["id"] == queued.id
    assert jobs[0]["payload"] == {"char_id": "ada"}
    assert jobs[0]["status"] == "failed"
    assert jobs[0]["recoverable"] is True
    assert recovered_generation_jobs(restarted, "other:book") == []


@run_async
async def test_paid_submission_without_action_key_is_rejected(tmp_path):
    app = app_at(tmp_path)
    calls = []

    @app.post("/api/projects/book/cover")
    async def paid():
        calls.append(True)
        return {"accepted": True}

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        result = await client.post("/api/projects/book/cover")
    assert result.status_code == 400
    assert result.json()["detail"]["code"] == "idempotency_key_required"
    assert calls == []


@run_async
async def test_generation_completion_acknowledgement_waits_for_all_settlements(tmp_path, monkeypatch):
    from novel_to_comic.server import credited_job
    from novel_to_comic.usage import ApiResult, UsageRecord

    app = app_at(tmp_path)
    app.state.generation_queue = asyncio.Queue()
    events = []
    monkeypatch.setattr(credited_job, "get_db", lambda: object())
    monkeypatch.setattr(credited_job, "reserve_credits", lambda *args: ("hold", "ledger-job"))
    monkeypatch.setattr(credited_job, "assert_reservation_active", lambda *args: None)
    monkeypatch.setattr(credited_job, "release_reservation", lambda *args: events.append("released"))
    usage = UsageRecord(provider="fixture", model="model", operation="text", input_tokens=1, output_tokens=1)

    def debit(*args, **kwargs):
        events.append("settlement")
        if events.count("settlement") == 2:
            raise RuntimeError("second call settlement is ambiguous")

    monkeypatch.setattr(credited_job, "debit_model_usage", debit)

    async def work():
        return ApiResult(value="paid-render", usage=usage, additional_usage=(usage,))

    job, _ = credited_job.enqueue_reserved_generation_job(
        app, project_name="account:book", user_id="account", project_id="book",
        project_dir=tmp_path, stage="draw", kind="draw", label="Page",
        payload={}, work=work, debit_description="Page", reservation_credits=2,
        operations=(("complete_page", "image-balanced"),),
        on_settled=lambda result: events.append("complete"),
        on_terminal=lambda: events.append("terminal"),
    )
    try:
        await job.runner()
    except RuntimeError:
        pass
    assert events == ["settlement", "settlement", "released", "terminal"]


@run_async
async def test_status_reconciliation_waits_for_project_mutation(tmp_path):
    app = app_at(tmp_path)
    entered, release = asyncio.Event(), asyncio.Event()
    observed = []

    @app.post("/api/projects/book/cover")
    async def paid():
        entered.set()
        await release.wait()
        app.state.generation_jobs["job"] = SimpleNamespace(project_name="account:book", status="queued")
        return {"job": "job"}

    @app.get("/api/projects/book/status")
    async def status():
        observed.append("job" in app.state.generation_jobs)
        return {"running": observed[-1]}

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        mutation = asyncio.create_task(client.post("/api/projects/book/cover", headers={"Idempotency-Key": "action"}))
        await entered.wait()
        inspection = asyncio.create_task(client.get("/api/projects/book/status"))
        await asyncio.sleep(0.02)
        try:
            assert observed == []
        finally:
            release.set()
            await mutation
            result = await inspection
        assert result.status_code == 200
        assert result.json()["running"] is True
