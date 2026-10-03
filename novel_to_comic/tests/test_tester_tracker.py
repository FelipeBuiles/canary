from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from novel_to_comic.server.routers import backoffice


def test_tracker_routes_require_operator_token(monkeypatch):
    monkeypatch.setenv("CANARY_OPS_TOKEN", "private-operator")
    app = FastAPI()
    app.include_router(backoffice.router)
    client = TestClient(app)
    with patch.object(backoffice, "get_db") as db:
        assert client.get("/tester-tracker").status_code == 401
        assert client.put("/tester-tracker/people/tester", json={"mode": "set", "expected_revision": 0}).status_code == 401
        db.assert_not_called()


def test_snapshot_only_reads_active_private_records():
    db = MagicMock()
    query = db.table.return_value.select.return_value.eq.return_value.order.return_value.order.return_value.range.return_value
    query.execute.return_value = SimpleNamespace(data=[{"collection": "people", "id": "one", "data": {"handle": "Writer"}, "revision": 2}])
    with patch.object(backoffice, "get_db", return_value=db):
        result = backoffice.read_tester_tracker()
    assert result["people"] == [{"id": "one", "data": {"handle": "Writer"}, "revision": 2}]
    assert result["sessions"] == []
    db.table.return_value.select.return_value.eq.assert_called_once_with("deleted", False)


def test_save_passes_revision_to_atomic_rpc_and_does_not_grant_credits():
    db = MagicMock()
    db.rpc.return_value.execute.return_value = SimpleNamespace(data=[{"id": "one", "data": {"credits": 100}, "revision": 3}])
    with patch.object(backoffice, "get_db", return_value=db), patch.object(backoffice, "grant_credits") as grant:
        result = backoffice.write_tester_tracker("people", "one", backoffice.TesterRecordWrite(mode="update", expected_revision=2, data={"credits": 100}))
    assert result["revision"] == 3
    assert db.rpc.call_args.args[1]["p_expected_revision"] == 2
    grant.assert_not_called()
    db.table.assert_not_called()


@pytest.mark.parametrize("message,status", [("tracker_revision_conflict", 409), ("tracker_record_missing", 404), ("database unavailable", 503)])
def test_save_errors_are_explicit(message, status):
    db = MagicMock()
    db.rpc.return_value.execute.side_effect = RuntimeError(message)
    with patch.object(backoffice, "get_db", return_value=db), pytest.raises(HTTPException) as error:
        backoffice.write_tester_tracker("notes", "one", backoffice.TesterRecordWrite(mode="update", expected_revision=1))
    assert error.value.status_code == status


@pytest.mark.parametrize("collection,record_id,data", [("users", "one", {}), ("people", "../one", {}), ("people", "one", {"credits": -1}), ("people", "one", {"context": "x" * 64001}), ("people", "one", {"id": "override"})])
def test_invalid_records_rejected_before_database(collection, record_id, data):
    with patch.object(backoffice, "get_db") as db, pytest.raises(HTTPException) as error:
        backoffice.write_tester_tracker(collection, record_id, backoffice.TesterRecordWrite(mode="set", expected_revision=0, data=data))
    assert error.value.status_code == 422
    db.assert_not_called()


def test_snapshot_paginates_past_postgrest_page_limit():
    db = MagicMock()
    query = db.table.return_value.select.return_value.eq.return_value.order.return_value.order.return_value.range.return_value
    row = {"collection": "notes", "id": "note", "data": {}, "revision": 1}
    query.execute.side_effect = [SimpleNamespace(data=[row] * 1000), SimpleNamespace(data=[{**row, "id": "last"}])]
    with patch.object(backoffice, "get_db", return_value=db):
        result = backoffice.read_tester_tracker()
    assert len(result["notes"]) == 1001
    assert result["notes"][-1]["id"] == "last"
