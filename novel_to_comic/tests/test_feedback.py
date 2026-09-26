from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import UUID

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from novel_to_comic.server.routers import feedback

USER = "b039877c-3d9b-46ec-988f-183972a14945"


def test_feedback_rejects_blank_and_extra_private_payloads():
    with pytest.raises(ValidationError):
        feedback.Feedback(id=USER, category="feature", message="  ")
    with pytest.raises(ValidationError):
        feedback.Feedback(id=USER, category="feature", message="Add export options", prompt="private")


def test_feedback_refuses_other_accounts_project(monkeypatch):
    db = MagicMock()
    db.table.return_value.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value.data = []
    monkeypatch.setattr(feedback, "get_db", lambda: db)
    # Skip the rate limiter wrapper, exercising the authenticated handler directly.
    with pytest.raises(HTTPException) as exc:
        feedback.submit_feedback.__wrapped__(feedback.Feedback(id=USER, category="feature", message="Request", project_id=UUID(USER)),
            SimpleNamespace(state=SimpleNamespace(request_id=USER)), USER)
    assert exc.value.status_code == 404
    db.table.return_value.upsert.assert_not_called()


def test_feedback_text_stays_in_first_party_store(monkeypatch):
    db = MagicMock()
    db.table.return_value.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value.data = []
    monkeypatch.setattr(feedback, "get_db", lambda: db)
    capture = MagicMock()
    monkeypatch.setattr(feedback, "capture_server_event", capture)
    feedback.submit_feedback.__wrapped__(feedback.Feedback(id=USER, category="frustration", message="Private customer comment"),
        SimpleNamespace(state=SimpleNamespace(request_id=USER)), USER)
    assert db.table.return_value.upsert.call_args.args[0]["message"] == "Private customer comment"
    assert "Private" not in str(capture.call_args)
