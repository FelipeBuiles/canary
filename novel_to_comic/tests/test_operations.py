"""Operational reads cannot change paid-work authorities or leak customer text."""
import json
from datetime import datetime, timezone
from types import SimpleNamespace

from novel_to_comic.server.admission import Admission
from novel_to_comic.server.operations import exception_snapshot

NOW = datetime(2026, 9, 10, 12, tzinfo=timezone.utc)
OLD = "2026-09-10T10:00:00+00:00"


class Database:
    def __init__(self, tables):
        self.tables = tables

    def table(self, name):
        return Query(self.tables.get(name, []))


class Query:
    def __init__(self, rows):
        self.rows = rows

    def select(self, *_): return self
    def order(self, *_): return self
    def eq(self, key, value):
        self.rows = [r for r in self.rows if r.get(key) == value]
        return self
    def range(self, start, end):
        self.rows = self.rows[start:end + 1]
        return self
    def execute(self): return SimpleNamespace(data=self.rows)


def app_at(root):
    return SimpleNamespace(state=SimpleNamespace(projects_dir=root, admission=Admission(root),
        generation_jobs={}, running_tasks={}, style_tasks={}))


def test_persistent_drain_and_explicit_resume(tmp_path):
    admission = Admission(tmp_path)
    admission.set_draining(True)
    assert Admission(tmp_path).draining
    admission.set_draining(False)
    assert not Admission(tmp_path).draining
    admission.draining = True  # normal lifespan shutdown is not maintenance intent
    assert not Admission(tmp_path).draining


def test_interrupted_journal_and_credit_evidence_is_private_read_only(tmp_path, monkeypatch):
    monkeypatch.setenv("CANARY_OPS_STORAGE_FREE_BYTES", "1")
    app = app_at(tmp_path)
    with app.state.admission.journal() as journal:
        journal.execute("INSERT INTO requests VALUES(?,?,?,?,?,?)", ("private-email", "POST /api/projects/book/cover", "secret-key", "hash", None, None))
        journal.execute("CREATE TABLE jobs (id TEXT PRIMARY KEY, project TEXT, payload TEXT)")
        journal.execute("INSERT INTO jobs VALUES(?,?,?)", ("job-1", "private-email:book", json.dumps({"status": "running", "label": "SECRET MANUSCRIPT", "error": "API_KEY"})))
    db = Database({"credit_ledger": [dict(id="hold-1", job_id="job-1", project_id="book", status="reserved", reservation_started_at=OLD, reservation_expires_at=OLD),
        dict(id="unstarted", status="reserved", reservation_started_at=None, reservation_expires_at=OLD)]})
    result = exception_snapshot(app, db=db, now=NOW)
    assert result["complete"]
    kinds = {o["kind"] for o in result["observations"]}
    assert {"interrupted_job", "indeterminate_action", "credit_reconciliation"} <= kinds
    serialized = json.dumps(result)
    assert all(secret not in serialized for secret in ("private-email", "secret-key", "SECRET MANUSCRIPT", "API_KEY", "unstarted"))
    assert all(o["safe_action"] and o["diagnostic_url"] for o in result["observations"])
    assert result == exception_snapshot(app, db=db, now=NOW)
    with app.state.admission.journal() as journal:
        assert journal.execute("SELECT status FROM requests").fetchone()[0] is None


def test_slow_progress_not_stalled_and_old_progress_is(tmp_path):
    folder = tmp_path / "account" / "private-title"
    folder.mkdir(parents=True)
    state = {"stages": {"draw": {"status": "running", "started_at": OLD, "last_progress_at": "2026-09-10T11:59:00+00:00"}}}
    (folder / "state.json").write_text(json.dumps(state))
    db = Database({"projects": [dict(id="project", user_id="account", name="private-title")]})
    app = app_at(tmp_path)
    assert not any(o["kind"] == "stalled_stage" for o in exception_snapshot(app, db=db, now=NOW)["observations"])
    state["stages"]["draw"]["last_progress_at"] = OLD
    (folder / "state.json").write_text(json.dumps(state))
    result = exception_snapshot(app, db=db, now=NOW)
    assert any(o["kind"] == "stalled_stage" and o["project_id"] != "project" for o in result["observations"])
    assert "private-title" not in json.dumps(result)


def test_missing_evidence_never_looks_like_complete_recovery(tmp_path):
    class Broken:
        def table(self, name): raise RuntimeError("credential:secret")
    result = exception_snapshot(app_at(tmp_path), db=Broken(), now=NOW)
    assert not result["complete"]
    assert "credential" not in json.dumps(result)
    assert any(o["kind"] == "evidence_unavailable" for o in result["observations"])


def test_resume_requires_ready_dependencies_and_ops_auth(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from novel_to_comic.server import app as module
    monkeypatch.setenv("CANARY_OPS_TOKEN", "secret")
    app = module.create_app(tmp_path, dev=True)
    client = TestClient(app)
    app.state.admission.set_draining(True)
    monkeypatch.setattr(module, "_readiness_result", lambda: (False, {}))
    assert client.post("/api/ops/resume", headers={"X-Canary-Ops-Token": "secret"}).status_code == 503
    assert Admission(tmp_path).draining
    assert client.get("/api/ops/exceptions").status_code == 401
    monkeypatch.setattr(module, "_readiness_result", lambda: (True, {}))
    assert client.post("/api/ops/resume", headers={"X-Canary-Ops-Token": "secret"}).status_code == 200
    assert not Admission(tmp_path).draining


def test_dependency_outage_keeps_liveness_and_closes_admission(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from novel_to_comic.server import app as module
    from novel_to_comic.server.auth import get_current_user
    monkeypatch.setattr(module, "_audit_pricing_at_startup", lambda: None)
    monkeypatch.setattr(module, "_refresh_pricing_if_stale", lambda: None)
    monkeypatch.setattr(module, "_readiness_result", lambda: (True, {}))
    monkeypatch.setattr("novel_to_comic.server.db.get_db", lambda: object())
    def unavailable(_): raise RuntimeError("database offline")
    monkeypatch.setattr("novel_to_comic.server.credits.start_reservation_leases", unavailable)
    monkeypatch.setattr("novel_to_comic.server.credits.stop_reservation_leases", lambda: None)
    app = module.create_app(tmp_path, dev=True)
    app.dependency_overrides[get_current_user] = lambda: "account"
    with TestClient(app) as client:
        assert client.get("/api/health").status_code == 200
        assert client.get("/api/health/ready").status_code == 503
        result = client.post("/api/projects/book/cover", headers={"Idempotency-Key": "test"})
        assert result.status_code == 503
        assert result.json()["detail"]["code"] == "credits_unavailable"
        with app.state.admission.journal() as db:
            assert db.execute("SELECT count(*) FROM requests").fetchone()[0] == 0
    assert not Admission(tmp_path).draining


def test_saved_output_marker_survives_publication_without_alerting_live_work(tmp_path):
    folder = tmp_path / "account" / "title" / "draw" / "pages" / "page_001"
    folder.mkdir(parents=True)
    (tmp_path / "account" / "title" / "state.json").write_text('{"stages":{}}')
    pending = folder / "provenance_001.pending"
    pending.write_text("private paid output")
    app = app_at(tmp_path)
    db = Database({"projects": [dict(id="project", user_id="account", name="title")]})
    def saved():
        return [o for o in exception_snapshot(app, db=db, now=NOW)["observations"] if o["kind"] == "saved_output_recovery"]
    first = saved()
    assert len(first) == 1
    pending.rename(pending.with_suffix(".unfinished"))
    assert saved() == first
    app.state.running_tasks["account:project"] = SimpleNamespace(done=lambda: False)
    assert not saved()


def test_terminal_usage_retains_ambiguous_submission_evidence(tmp_path):
    from novel_to_comic.ai.client import _error_json
    from novel_to_comic.ai.errors import AITransportError
    error = AITransportError("secret raw exception", phase="ambiguous_submission")
    evidence = _error_json(error)
    assert evidence["phase"] == "ambiguous_submission"
    assert "secret" not in json.dumps(evidence)
    db = Database({"ai_usage_events": [dict(id="call", project_id="project", status="failed", **{"error_json->>phase": evidence["phase"]})]})
    result = exception_snapshot(app_at(tmp_path), db=db, now=NOW)
    assert any(o["kind"] == "ambiguous_provider_call" and o["action_id"] == "call" for o in result["observations"])


def test_lease_readiness_tracks_renewal_failure_and_recovery(monkeypatch):
    from novel_to_comic.server import credits
    monkeypatch.setattr(credits, "_lease_last_success", None)
    class LeaseDB:
        failing = False
        def rpc(self, *args): return self
        def execute(self):
            if self.failing:
                raise RuntimeError("lease RPC down")
    db = LeaseDB()
    credits.renew_reservation_leases(db)
    assert credits.reservation_leases_healthy()
    db.failing = True
    import pytest
    with pytest.raises(RuntimeError):
        credits.renew_reservation_leases(db)
    assert not credits.reservation_leases_healthy()
    db.failing = False
    credits.renew_reservation_leases(db)
    assert credits.reservation_leases_healthy()
