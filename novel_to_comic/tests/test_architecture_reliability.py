"""Failure and concurrency regressions from the October architecture review."""

import asyncio
import hashlib
import io
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from fastapi import HTTPException

from novel_to_comic.server.async_credits import ledger_call
from novel_to_comic.server.job_journal import history
from novel_to_comic.server.storage_budget import housekeeping, ingestion, usage
from tests.queue_fixtures import create_app
from tests.test_server_admission import app_at


def test_slow_ledger_keeps_event_loop_responsive_and_limits_inflight_calls():
    entered, finish = threading.Event(), threading.Event()
    mutex = threading.Lock()
    active = peak = 0

    def blocked():
        nonlocal active, peak
        with mutex:
            active += 1
            peak = max(peak, active)
            if active == 8:
                entered.set()
        assert finish.wait(5)
        with mutex:
            active -= 1
        return True

    async def exercise():
        # Small CI runners have fewer than eight default executor threads.
        # Supply enough workers to test the ledger's own limit, plus its probe.
        asyncio.get_running_loop().set_default_executor(ThreadPoolExecutor(max_workers=12))
        tasks = [asyncio.create_task(ledger_call(blocked)) for _ in range(24)]
        try:
            assert await asyncio.to_thread(entered.wait, 3)
            # A heartbeat can run while all eight RPCs are blocked.
            heartbeat = asyncio.Event()
            asyncio.get_running_loop().call_soon(heartbeat.set)
            await asyncio.wait_for(heartbeat.wait(), 0.5)
            assert peak == 8
        finally:
            finish.set()
            assert all(await asyncio.gather(*tasks))

    asyncio.run(exercise())
    assert peak == 8 and active == 0


def test_cancel_during_reservation_waits_and_releases_committed_unstarted_hold():
    entered, finish = threading.Event(), threading.Event()
    cleanups = []

    def reserve():
        entered.set()
        assert finish.wait(3)
        return "new-hold", "ledger-job"

    async def exercise():
        task = asyncio.create_task(ledger_call(reserve, cancel_cleanup=cleanups.append))
        assert await asyncio.to_thread(entered.wait, 2)
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done() and not cleanups
        # Repeated cancellation must not detach committed money movement.
        task.cancel()
        finish.set()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(exercise())
    assert cleanups == [("new-hold", "ledger-job")]


def _record(identity, status="complete", **kwargs):
    now = datetime.now(timezone.utc).isoformat()
    return {
        "id": identity,
        "project_name": "owner:book",
        "kind": "project_cover",
        "label": "Cover",
        "payload": {},
        "status": status,
        "queued_at": now,
        "started_at": None,
        "finished_at": now if status == "complete" else None,
        "phase": status,
        "recoverable": False,
        **kwargs,
    }


def test_restore_does_not_parse_old_terminal_commands_and_memory_is_bounded(tmp_path):
    app = create_app(tmp_path)
    with app.state.admission.journal() as db:
        for n in range(1000):
            record = _record(f"old-{n}")
            db.execute(
                "INSERT INTO jobs VALUES(?,?,?)",
                (record["id"], "owner:book", json.dumps(record)),
            )
            db.execute(
                "INSERT INTO operation_outbox VALUES(?,?,?)",
                (record["id"], '{"version": 99, "operation": "retired"}', n),
            )
        invalid = _record("never-started", "queued")
        unknown = _record(
            "interrupted", "running", started_at=datetime.now(timezone.utc).isoformat()
        )
        for record in (invalid, unknown):
            db.execute(
                "INSERT INTO jobs VALUES(?,?,?)",
                (record["id"], "owner:book", json.dumps(record)),
            )
            db.execute(
                "INSERT INTO operation_outbox VALUES(?,?,?)",
                (record["id"], '{"operation": "retired"}', None),
            )
    asyncio.run(app.state.durable_queue.restore())
    assert len(app.state.generation_jobs) == 202
    failed = app.state.generation_jobs["never-started"]
    assert (
        failed.status == "failed"
        and failed.phase == "incompatible_command"
        and failed.recoverable
    )
    interrupted = app.state.generation_jobs["interrupted"]
    assert interrupted.phase == "outcome_unknown" and not interrupted.recoverable
    saved, next_cursor = history(app, "owner:book", limit=100)
    assert len(saved) == 100 and next_cursor is not None
    second, _ = history(app, "owner:book", before=next_cursor, limit=100)
    assert not {r["id"] for r in saved} & {r["id"] for r in second}
    # Updating an old observation does not move its pagination cursor.
    with app.state.admission.journal() as db:
        before = db.execute("SELECT rowid FROM jobs WHERE id=?", ("old-1",)).fetchone()
        db.execute(
            "INSERT INTO jobs VALUES(?,?,?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload",
            ("old-1", "owner:book", json.dumps(_record("old-1", label="Updated"))),
        )
        assert (
            db.execute("SELECT rowid FROM jobs WHERE id=?", ("old-1",)).fetchone()
            == before
        )


def test_every_project_mutation_declares_readiness_requirements(tmp_path):
    app = create_app(tmp_path)
    for path, methods in app.openapi()["paths"].items():
        if not path.startswith("/api/projects"):
            continue
        for method, schema in methods.items():
            if method in {"post", "put", "patch", "delete"}:
                assert schema.get("x-canary-action") is not None, (method, path)
                from novel_to_comic.server.action_policy import ActionPolicy
                rules = schema["x-canary-action"]
                assert {"spends", "dispatches"} <= rules.keys()
                ActionPolicy(**rules)  # Reject unsupported metadata.


@pytest.mark.parametrize(
    "endpoint", ["/api/projects", "/api/projects/", "/api/projects/import-story"]
)
def test_drain_gates_creation_without_readiness_dependency(tmp_path, endpoint):
    app = app_at(tmp_path)
    calls = []

    @app.post(
        endpoint,
        openapi_extra={"x-canary-action": {"spends": False, "dispatches": False}},
    )
    async def create():
        calls.append(True)
        return {"created": True}

    app.state.admission.set_draining(True)

    async def exercise():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(endpoint)
            assert response.status_code == 503
            assert response.json()["detail"]["admitted"] is False

    asyncio.run(exercise())
    assert not calls


def test_free_edit_survives_dependency_outage_paid_rejection_keeps_key_usable(tmp_path):
    app = app_at(tmp_path)
    from types import SimpleNamespace

    app.state.credit_leases_ready = False
    app.state.durable_queue = SimpleNamespace(healthy=False)

    @app.put(
        "/api/projects/book/local-edit",
        openapi_extra={"x-canary-action": {"spends": False, "dispatches": False}},
    )
    async def free():
        return {"saved": True}

    @app.post(
        "/api/projects/book/cover",
        openapi_extra={"x-canary-action": {"spends": True, "dispatches": True}},
    )
    async def paid():
        return {"accepted": True}

    async def exercise():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            assert (
                await client.put("/api/projects/book/local-edit")
            ).status_code == 200
            for _ in range(2):
                result = await client.post(
                    "/api/projects/book/cover",
                    headers={"Idempotency-Key": "same-action"},
                )
                assert (
                    result.status_code == 503
                    and result.json()["detail"]["admitted"] is False
                )
            with app.state.admission.journal() as db:
                assert db.execute("SELECT count(*) FROM requests").fetchone()[0] == 0

    asyncio.run(exercise())


def test_account_budget_serializes_uploads_across_different_projects(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("CANARY_ACCOUNT_STORAGE_BYTES", "100")
    account = tmp_path / "owner"
    projects = [account / "first", account / "second"]
    for project in projects:
        project.mkdir(parents=True)
    ready = threading.Barrier(2)

    def upload(project):
        ready.wait()
        try:
            with ingestion(project, 60):
                (project / "source.txt").write_bytes(b"x" * 60)
            return "saved"
        except HTTPException as exc:
            assert exc.status_code == 413 and exc.detail["admitted"] is False
            return "full"

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(upload, projects)) == ["full", "saved"]
    assert usage(account)["used_bytes"] == 60


def test_failed_part_mutation_removes_retained_upload(tmp_path):
    from novel_to_comic.server.routers.parts import _commit_text
    from starlette.datastructures import UploadFile

    project = tmp_path / "owner" / "book"
    project.mkdir(parents=True)

    def reject(*args):
        raise ValueError("Adapt started during parse")

    file = UploadFile(io.BytesIO(b"New manuscript"), filename="story.txt", size=14)
    with pytest.raises(ValueError, match="Adapt started"):
        _commit_text(project, file, None, reject)
    assert not list((project / "input" / "parts").glob("*"))


def test_housekeeping_preserves_unknown_inputs_receipts_and_author_archives(tmp_path):
    app = create_app(tmp_path)
    app.state.admission.set_draining(True)
    project = tmp_path / "owner" / "book"
    inputs = project / ".jobs" / "inputs"
    inputs.mkdir(parents=True)
    keep = hashlib.sha256(b"unknown paid reference").hexdigest()
    orphan = hashlib.sha256(b"orphan").hexdigest()
    archived = hashlib.sha256(b"archived reference").hexdigest()
    for name in (keep, orphan, archived):
        (inputs / name).write_bytes(b"input")
    (project / "author-archive.json").write_text(
        json.dumps({"reference": str(inputs / archived)})
    )
    old = (datetime.now(timezone.utc) - timedelta(days=40)).isoformat()
    with app.state.admission.journal() as db:
        for identity, status, digest in [
            ("unknown", "failed", keep),
            ("done", "complete", orphan),
        ]:
            record = _record(
                identity,
                status,
                finished_at=old,
                phase="outcome_unknown" if status == "failed" else "complete",
            )
            db.execute(
                "INSERT INTO jobs VALUES(?,?,?)",
                (identity, "owner:book", json.dumps(record)),
            )
            db.execute(
                "INSERT INTO operation_outbox VALUES(?,?,?)",
                (identity, json.dumps({"references": [digest]}), 1),
            )
        db.execute(
            "INSERT INTO requests VALUES(?,?,?,?,?,?)",
            ("owner", "POST cover", "receipt", "fingerprint", 200, b'{"ok": true}'),
        )
    assert housekeeping(app)["removed_items"] == 1
    assert (
        (inputs / keep).exists()
        and (inputs / archived).exists()
        and not (inputs / orphan).exists()
    )
    with app.state.admission.journal() as db:
        assert db.execute("SELECT count(*) FROM requests").fetchone()[0] == 1
        assert db.execute("SELECT count(*) FROM jobs").fetchone()[0] == 2
        assert db.execute("SELECT id FROM operation_outbox").fetchall() == [
            ("unknown",)
        ]
    (project / "broken-authority.json").write_text("{")
    (inputs / orphan).write_bytes(b"input")
    assert housekeeping(app)["removed_items"] == 0 and (inputs / orphan).exists()


def test_matching_export_package_rejects_changed_base_art(tmp_path):
    from novel_to_comic.page_finishing import finish_book, open_verified_package
    from tests.test_page_finishing import _write_valid_book, FinishProductionSpec

    target, _ = _write_valid_book(tmp_path)
    finish_book(
        target,
        production=FinishProductionSpec(
            canvas_width=120, canvas_height=180, bleed_px=10
        ),
    )
    stream, _, _ = open_verified_package(target, "pdf")
    stream.close()
    target.render_path(1, 1).write_bytes(b"changed paid output")
    with pytest.raises(ValueError):
        open_verified_package(target, "pdf")


@pytest.mark.parametrize("method", ["upload", "import"])
def test_initialization_failure_removes_new_project_and_retained_source(
    tmp_path, monkeypatch, method
):
    from types import SimpleNamespace
    from starlette.datastructures import UploadFile
    from novel_to_comic.config import Config
    from novel_to_comic.server import account_models
    from novel_to_comic.server.routers import projects

    monkeypatch.setattr(projects, "_count_user_projects", lambda user: 0)
    monkeypatch.setattr(account_models, "creation_config", lambda *args: Config())
    monkeypatch.setattr(
        projects.sample_library,
        "find",
        lambda code: ({"code": "test-story"}, "The story begins."),
    )

    def fail(*args, **kwargs):
        raise ValueError("initialization failed after source save")

    monkeypatch.setattr(projects, "initialize_series", fail)
    request = SimpleNamespace(state=SimpleNamespace())
    with pytest.raises(ValueError, match="after source save"):
        if method == "upload":
            asyncio.run(
                projects.create_project.__wrapped__(
                    request,
                    file=UploadFile(
                        io.BytesIO(b"The story begins."), filename="story.txt"
                    ),
                    name="Book",
                    config_overrides=None,
                    projects_dir=tmp_path,
                    user_id="owner",
                )
            )
        else:
            asyncio.run(
                projects.import_short_story.__wrapped__(
                    request,
                    projects.ImportStoryRequest(name="Book", url_or_code="test-story"),
                    projects_dir=tmp_path,
                    user_id="owner",
                )
            )
    assert not (tmp_path / "owner" / "book").exists()
