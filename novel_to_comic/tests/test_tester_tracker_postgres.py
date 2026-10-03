"""Tracker persistence and RLS on an explicitly disposable loopback database."""
import json
import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import urlsplit

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from novel_to_comic.server.routers import backoffice
from tests.test_credit_ledger_postgres import Ledger, _literal


@pytest.fixture
def tracker_db():
    url = os.environ.get("CREDIT_TEST_DATABASE_URL", "")
    if not url:
        pytest.skip("requires disposable PostgreSQL")
    target = urlsplit(url)
    assert target.hostname in {"127.0.0.1", "localhost"} and target.path == "/canary_test"
    assert os.environ.get("CANARY_DISPOSABLE_DATABASE") == "1"
    db = Ledger(url)
    record_id = str(uuid.uuid4())
    try:
        yield db, record_id
    finally:
        db.query(f"delete from public.operator_tester_records where id='{record_id}';")


def save(db, record_id, mode, data, revision):
    return json.loads(db.query(
        "set role service_role; select row_to_json(r) from public.write_operator_tester_record("
        f"'people', {_literal(record_id)}, {_literal(json.dumps(data))}::jsonb, {_literal(mode)}, {revision}) r;"
    ))


def test_private_record_persists_and_soft_delete_retains_data(tracker_db):
    db, record_id = tracker_db
    created = save(db, record_id, "set", {"handle": "Synthetic writer", "credits": None}, 0)
    assert created["revision"] == 1
    updated = save(db, record_id, "update", {"context": "Synthetic private story"}, 1)
    assert updated["data"]["handle"] == "Synthetic writer"
    # A separate PostgreSQL connection observes committed data.
    assert json.loads(db.query(f"select data from public.operator_tester_records where id='{record_id}';"))["context"] == "Synthetic private story"
    deleted = save(db, record_id, "delete", {}, 2)
    assert deleted["deleted"] and deleted["revision"] == 3
    assert deleted["data"]["context"] == "Synthetic private story"
    with pytest.raises(RuntimeError, match="tracker_record_missing"):
        save(db, record_id, "update", {"handle": "Wrong"}, 3)


@pytest.mark.parametrize("role", ["anon", "authenticated"])
def test_customer_roles_cannot_read_write_or_execute_rpc(tracker_db, role):
    db, record_id = tracker_db
    save(db, record_id, "set", {"context": "Synthetic private story"}, 0)
    for sql in [
        "select * from public.operator_tester_records;",
        f"insert into public.operator_tester_records(collection,id,data) values('people','{record_id}-other','{{}}');",
        f"select public.write_operator_tester_record('people','{record_id}','{{}}','delete',1);",
    ]:
        with pytest.raises(RuntimeError, match="permission denied"):
            db.query(f"set role {role}; {sql}")
    assert db.query("select relrowsecurity from pg_class where oid='public.operator_tester_records'::regclass;") == "t"


def test_concurrent_edits_have_one_winner(tracker_db):
    db, record_id = tracker_db
    save(db, record_id, "set", {"handle": "Synthetic writer"}, 0)
    barrier = Barrier(2)

    def edit(context):
        barrier.wait()
        try:
            return save(db, record_id, "update", {"context": context}, 1)["revision"]
        except RuntimeError as error:
            assert "tracker_revision_conflict" in str(error)
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(edit, ["one", "two"]))
    assert sorted(str(item) for item in results) == ["2", "conflict"]


def test_authenticated_operator_api_writes_real_transaction(tracker_db, monkeypatch):
    db, record_id = tracker_db

    class Database:
        def rpc(self, name, params):
            assert name == "write_operator_tester_record"
            return SimpleNamespace(execute=lambda: SimpleNamespace(data=[save(db, params["p_id"], params["p_mode"], params["p_data"], params["p_expected_revision"])]))

    monkeypatch.setenv("CANARY_OPS_TOKEN", "synthetic-operator-token")
    app = FastAPI()
    app.include_router(backoffice.router, prefix="/api/ops/backoffice")
    client = TestClient(app)
    path = f"/api/ops/backoffice/tester-tracker/people/{record_id}"
    payload = {"mode": "set", "data": {"handle": "Synthetic writer"}, "expected_revision": 0}
    with patch.object(backoffice, "get_db", return_value=Database()):
        assert client.put(path, json=payload).status_code == 401
        response = client.put(path, json=payload, headers={"X-Canary-Ops-Token": "synthetic-operator-token"})
        assert response.status_code == 200 and response.json()["revision"] == 1
        stale = client.put(path, json=payload, headers={"X-Canary-Ops-Token": "synthetic-operator-token"})
        assert stale.status_code == 409
    assert db.query(f"select data->>'handle' from public.operator_tester_records where id='{record_id}';") == "Synthetic writer"


def test_merged_record_size_is_bounded_in_database(tracker_db):
    db, record_id = tracker_db
    save(db, record_id, "set", {"context": "x" * 40000}, 0)
    with pytest.raises(RuntimeError, match="check constraint"):
        save(db, record_id, "update", {"other": "y" * 40000}, 1)
    assert db.query(f"select revision from public.operator_tester_records where id='{record_id}';") == "1"
