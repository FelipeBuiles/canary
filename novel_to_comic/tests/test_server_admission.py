"""Failure boundaries at the HTTP admission and event fanout seams."""
import asyncio
from functools import wraps
from types import SimpleNamespace

import httpx
import pytest
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
async def test_multipart_parser_rejections_return_a_client_error(tmp_path):
    app = app_at(tmp_path)
    calls = []
    path = "/api/projects/book/pages/2/corrections"

    @app.post(path)
    async def correction():
        calls.append(True)
        return {"ok": True}

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(path, files={"instructions": (None, "x" * (1024 * 1024 + 1))},
                                     headers={"Idempotency-Key": "oversized-field"})

    assert response.status_code == 400
    assert "maximum size" in response.json()["detail"]["message"]
    assert not calls


@pytest.mark.parametrize("suffix", ["corrections/preview", "corrections"])
@pytest.mark.parametrize("status", ["queued", "running"])
@pytest.mark.parametrize("kind, expected", [
    ("complete_page_draw", 200),
    ("pipeline_stage", 200),
    ("lettering_translation", 200),
])
@run_async
async def test_page_correction_flow_during_other_page_work(tmp_path, suffix, status, kind, expected):
    app = app_at(tmp_path)
    app.state.generation_jobs["other-page"] = SimpleNamespace(
        project_name="account:book", kind=kind, status=status,
        payload={"page_number": 3},
    )
    calls = []
    path = f"/api/projects/book/pages/2/{suffix}"

    @app.post(path)
    async def correction():
        calls.append(True)
        return {"ok": True}

    # Preview is free; only submission requires an action key.
    headers = {"Idempotency-Key": "correction"} if suffix == "corrections" else {}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(path, json={}, headers=headers)
    assert response.status_code == expected, response.text
    assert bool(calls) == (expected == 200)


@pytest.mark.parametrize("suffix", [
    "/regen-ref", "/regen-ref-instructed", "/regen-state-ref",
    "/regen-plate", "/regen-plate-instructed", "/regen-prop", "/regen-prop-instructed",
    "/characters/ada/states/winter/regenerate-instructed",
    "/locations/hall/states/night/regenerate", "/locations/hall/states/night/regenerate-instructed",
    "/styles/direction", "/styles/generate-samples", "/styles/validation", "/cover",
])
@pytest.mark.parametrize("part", ["", "/parts/part_0001"])
@run_async
async def test_review_jobs_can_queue_during_a_stage_and_replay_once(tmp_path, suffix, part):
    app = app_at(tmp_path)
    app.state.generation_jobs["cast"] = SimpleNamespace(
        project_name="account:book", kind="pipeline_stage", status="running", payload={"stage": "cast"},
    )
    calls = []
    path = f"/api/projects/book{part}{suffix}"

    @app.post(path)
    async def correction():
        calls.append(True)
        return {"status": "queued", "job": {"id": "fix"}}

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        for _ in range(2):
            result = await client.post(path, json={}, headers={"Idempotency-Key": "fix"})
            assert result.status_code == 200, result.text
            assert result.json()["status"] == "queued"
    assert calls == [True]


@pytest.mark.parametrize("suffix, expected", [
    ("/pages/2/issues", 200), ("/pages/2/issues/issue/accept", 200),
    ("/pages/2/issues/issue/dismiss", 200), ("/pages/3/issues", 409),
    ("/editorial/decisions", 200), ("/notes/preview", 200),
    ("/config", 409), ("/reset/cast", 409), ("/regen-extract", 409),
])
@run_async
async def test_review_records_only_conflict_with_their_own_writers(tmp_path, suffix, expected):
    app = app_at(tmp_path)
    app.state.generation_jobs["other-page"] = SimpleNamespace(
        project_name="account:book", kind="complete_page_draw", status="running", payload={"page_number": 3},
    )
    path = f"/api/projects/book{suffix}"

    @app.post(path)
    async def edit():
        return {"saved": True}

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        result = await client.post(path, json={}, headers={"Idempotency-Key": "edit"})
    assert result.status_code == expected, result.text


@pytest.mark.parametrize("status", ["queued", "running"])
@pytest.mark.parametrize("suffix, kind, body, expected", [
    ("/config/", "complete_page_draw", {"dev_model_selections": {"draw": "image-sunburst"}}, 200),
    ("/config", "complete_page_draw", {"dev_model_selections": {}}, 200),
    ("/config/", "complete_page_draw", {"dev_model_selections": {}, "target_language": "fr"}, 409),
    ("/config/", "complete_page_draw", {"target_language": "fr"}, 409),
    ("/config/", "pipeline_stage", {"dev_model_selections": {"draw": "image-sunburst"}}, 409),
    ("/config/", "style_sample", {"dev_model_selections": {"draw": "image-sunburst"}}, 409),
    ("/config/", "lettering_translation", {"dev_model_selections": {"draw": "image-sunburst"}}, 409),
])
@run_async
async def test_model_choices_can_change_during_frozen_page_jobs_only(tmp_path, status, suffix, kind, body, expected):
    from fastapi import Request
    from novel_to_comic.config import Config
    from novel_to_comic.server.job_commands import command

    app = app_at(tmp_path)
    frozen = command("cover", tmp_path, Config(draw_model="codex-dev/image/gpt-6.1-sol"))
    app.state.generation_jobs["existing"] = SimpleNamespace(
        project_name="account:book", kind=kind, status=status,
        payload={"page_number": 3}, command=frozen,
    )
    saved = []
    path = f"/api/projects/book{suffix}"

    @app.patch(path)
    async def edit(request: Request):
        saved.append(await request.json())
        return {"saved": True}

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        result = await client.patch(path, json=body)
    assert result.status_code == expected, result.text
    assert saved == ([body] if expected == 200 else [])
    assert frozen.config["draw_model"] == "codex-dev/image/gpt-6.1-sol"


@run_async
async def test_lost_response_replay_survives_restart_and_conflicting_input(tmp_path):
    calls = []

    def build():
        app = app_at(tmp_path)

        @app.post("/api/projects/book/cover", openapi_extra={"x-canary-action": {"spends": True, "dispatches": False}})
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

    @app.post("/api/projects/book/cover", openapi_extra={"x-canary-action": {"spends": True, "dispatches": False}})
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

    @app.post("/api/projects/book/cover", openapi_extra={"x-canary-action": {"spends": True, "dispatches": False}})
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
    start, progress = {"type": "stage_start", "stage": "cast"}, {"type": "stage_progress", "stage": "cast", "done": 1}
    channel.put_nowait(start)
    channel.put_nowait(progress)
    channel.unsubscribe(first)
    reconnect = channel.subscribe()
    assert [await reconnect.get(), await reconnect.get()] == [start, progress]
    channel.put_nowait({"type": "pipeline_done"})
    assert [await second.get() for _ in range(3)] == [start, progress, {"type": "pipeline_done"}]


def test_subscriber_after_a_finished_run_replays_only_the_run_in_flight():
    # A cast run failed and finished; a later regen job keeps the project busy,
    # so the room subscribes again. Replaying the old stage_fail flipped the
    # room between running and failed on every reconnect.
    channel = EventChannel()
    for event in (
        {"type": "stage_begin", "stage": "cast"},
        {"type": "stage_fail", "stage": "cast", "message": "declined"},
        {"type": "pipeline_done"},
    ):
        channel.put_nowait(event)
    assert channel.subscribe().empty()
    later = {"type": "stage_begin", "stage": "adapt"}
    channel.put_nowait(later)
    assert channel.subscribe().get_nowait() == later


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
    restarted.state.projects_dir = tmp_path
    from novel_to_comic.server.durable_queue import DurableQueue
    asyncio.run(DurableQueue(restarted, "postgresql://unused").restore())
    from novel_to_comic.server.generation_jobs import generation_job_payload
    jobs = [generation_job_payload(restarted, job) for job in restarted.state.generation_jobs.values()]
    assert jobs[0]["id"] == queued.id
    assert jobs[0]["payload"] == {"char_id": "ada"}
    assert jobs[0]["status"] == "failed"
    assert jobs[0]["recoverable"] is True
    assert recovered_generation_jobs(restarted, "other:book") == []


@run_async
async def test_paid_submission_without_action_key_is_rejected(tmp_path):
    app = app_at(tmp_path)
    calls = []

    @app.post("/api/projects/book/cover", openapi_extra={"x-canary-action": {"spends": True, "dispatches": False}})
    async def paid():
        calls.append(True)
        return {"accepted": True}

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        result = await client.post("/api/projects/book/cover")
    assert result.status_code == 400
    assert result.json()["detail"]["code"] == "idempotency_key_required"
    assert calls == []


@run_async
async def test_status_reconciliation_waits_for_project_mutation(tmp_path):
    app = app_at(tmp_path)
    entered, release = asyncio.Event(), asyncio.Event()
    observed = []

    @app.post("/api/projects/book/cover", openapi_extra={"x-canary-action": {"spends": True, "dispatches": False}})
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


@run_async
async def test_cast_rejection_is_rechecked_after_restart_but_success_is_replayed(tmp_path):
    from fastapi import HTTPException
    from novel_to_comic.server.admission import _CAST_REVIEW_REJECTION
    ready = False
    effects = []

    def build():
        app = app_at(tmp_path)
        @app.post("/api/projects/book/approve/cast")
        async def approve():
            if not ready:
                raise HTTPException(409, _CAST_REVIEW_REJECTION)
            effects.append("approved")
            return {"status": "approved"}
        return app

    headers = {"Idempotency-Key": "same-browser-action"}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=build()), base_url="http://test") as client:
        assert (await client.post("/api/projects/book/approve/cast", headers=headers)).status_code == 409
    ready = True
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=build()), base_url="http://test") as client:
        accepted = await client.post("/api/projects/book/approve/cast", headers=headers)
        replay = await client.post("/api/projects/book/approve/cast", headers=headers)
    assert accepted.status_code == replay.status_code == 200
    assert "Idempotency-Replayed" not in accepted.headers
    assert replay.headers["Idempotency-Replayed"] == "true"
    assert effects == ["approved"]


def test_only_definite_cast_preflight_receipts_can_be_rechecked():
    import json
    from novel_to_comic.server.admission import cast_approval_was_rejected, _CAST_REVIEW_REJECTION
    def encoded(detail):
        return json.dumps({"detail": detail}).encode()
    assert cast_approval_was_rejected("POST", "/approve/cast", 409,
        encoded({"code": "cast_approval_rejected", "message": "Missing appearance"}))
    assert not cast_approval_was_rejected("POST", "/approve/cast", 409,
        encoded({"code": "idempotency_indeterminate"}))
    assert not cast_approval_was_rejected("POST", "/approve/cast", 409, encoded("Unknown conflict"))
    assert not cast_approval_was_rejected("POST", "/cover", 409, encoded(_CAST_REVIEW_REJECTION))
    assert not cast_approval_was_rejected("POST", "/approve/cast", 200, encoded(_CAST_REVIEW_REJECTION))


@run_async
async def test_finish_preflight_recovers_legacy_interrupted_receipt_and_rechecks_inputs(tmp_path):
    app = app_at(tmp_path)
    calls = []
    with app.state.admission.journal() as db:
        db.execute("INSERT INTO requests(account,route,key,fingerprint) VALUES(?,?,?,?)",
                   ("account", "POST /api/projects/book/export/preflight", "old-check", "old-input"))

    @app.post("/api/projects/book/export/preflight", openapi_extra={"x-canary-action": {"spends": False, "dispatches": False, "replay": False}})
    async def check():
        calls.append("check")
        if len(calls) == 1:
            raise RuntimeError("check interrupted")
        return {"checked_version": len(calls)}

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test") as client:
        first = await client.post("/api/projects/book/export/preflight", headers={"Idempotency-Key": "old-check"})
        retry = await client.post("/api/projects/book/export/preflight", headers={"Idempotency-Key": "old-check"})
        refreshed = await client.post("/api/projects/book/export/preflight", headers={"Idempotency-Key": "old-check"})
    assert first.status_code == 500
    assert retry.json() == {"checked_version": 2}
    assert refreshed.json() == {"checked_version": 3}
    assert "Idempotency-Replayed" not in retry.headers


@run_async
async def test_finish_preflight_does_not_replay_obsolete_success(tmp_path):
    app = app_at(tmp_path)
    with app.state.admission.journal() as db:
        db.execute("INSERT INTO requests(account,route,key,fingerprint,status,body) VALUES(?,?,?,?,?,?)",
                   ("account", "POST /api/projects/book/export/preflight", "old-check", "old-input", 200, b'{"ready":true}'))

    @app.post("/api/projects/book/export/preflight", openapi_extra={"x-canary-action": {"spends": False, "dispatches": False, "replay": False}})
    async def check():
        return {"ready": False, "reason": "New edition needs checking"}

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/projects/book/export/preflight", headers={"Idempotency-Key": "old-check"})
    assert response.status_code == 200
    assert response.json()["ready"] is False


@run_async
async def test_page_check_cache_recovery_bypasses_receipts_but_paid_recovery_does_not(tmp_path):
    import hashlib
    import json
    app = app_at(tmp_path)
    route = '/api/projects/book/pages/checks/recover'
    calls = []
    paid_body = {'allow_paid': True, 'renders': {'1': 'hash'}}
    fingerprint = hashlib.sha256(b'\0' + json.dumps(paid_body, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    with app.state.admission.journal() as db:
        db.execute('INSERT INTO requests(account,route,key,fingerprint) VALUES(?,?,?,?)',
                   ('account', f'POST {route}', 'interrupted', fingerprint))

    @app.post(route, openapi_extra={"x-canary-action": {"spends": True, "dispatches": False, "paid_body_field": "allow_paid"}})
    async def recover():
        calls.append('cache')
        return {'version': len(calls)}

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        for version in (1, 2):
            response = await client.post(route, json={'allow_paid': False}, headers={'Idempotency-Key': 'interrupted'})
            assert response.json() == {'version': version}
        paid = await client.post(route, json=paid_body, headers={'Idempotency-Key': 'interrupted'})
        assert paid.status_code == 409
        assert paid.json()['detail']['code'] == 'idempotency_indeterminate'
        missing = await client.post(route, json=paid_body)
        assert missing.status_code == 400
    assert calls == ['cache', 'cache']
