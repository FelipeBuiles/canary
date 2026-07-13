"""Release-blocking security and readiness contracts."""

import asyncio
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from novel_to_comic.server import app as app_module
from novel_to_comic.server import sentry as sentry_module
from novel_to_comic.server.routers import billing


class _StreamingRequest:
    def __init__(self, chunks: list[bytes], content_length: int | None = None):
        self._chunks = chunks
        self.headers = {}
        if content_length is not None:
            self.headers["content-length"] = str(content_length)

    async def stream(self):
        for chunk in self._chunks:
            yield chunk


def test_stripe_webhook_payload_rejects_oversized_content_length(monkeypatch):
    monkeypatch.setenv("CANARY_STRIPE_WEBHOOK_MAX_KB", "1")
    request = _StreamingRequest([b"small"], content_length=1025)

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(billing._read_stripe_webhook_payload(request))

    assert exc_info.value.status_code == 413


def test_stripe_webhook_payload_rejects_oversized_chunked_body(monkeypatch):
    monkeypatch.setenv("CANARY_STRIPE_WEBHOOK_MAX_KB", "1")
    request = _StreamingRequest([b"a" * 700, b"b" * 400])

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(billing._read_stripe_webhook_payload(request))

    assert exc_info.value.status_code == 413


def test_stripe_webhook_payload_preserves_exact_raw_bytes(monkeypatch):
    monkeypatch.setenv("CANARY_STRIPE_WEBHOOK_MAX_KB", "1")
    request = _StreamingRequest([b'{"type":', b'"event"}'])

    payload = asyncio.run(billing._read_stripe_webhook_payload(request))

    assert payload == b'{"type":"event"}'


@pytest.mark.parametrize("payment_status", [None, "unpaid", "no_payment_required"])
def test_checkout_webhook_does_not_credit_unpaid_sessions(payment_status):
    session = {
        "id": "cs_test_unpaid",
        "payment_status": payment_status,
        "payment_intent": "pi_unpaid",
        "metadata": {"user_id": "user-1", "package": "starter"},
    }

    with patch.object(billing, "get_db") as get_db:
        billing._handle_checkout_completed(session)

    get_db.assert_not_called()


def test_checkout_webhook_does_not_credit_without_payment_intent():
    session = {
        "id": "cs_test_missing_intent",
        "payment_status": "paid",
        "metadata": {"user_id": "user-1", "package": "starter"},
    }

    with patch.object(billing, "get_db") as get_db:
        billing._handle_checkout_completed(session)

    get_db.assert_not_called()


def test_checkout_webhook_credits_paid_session_once():
    session = {
        "id": "cs_test_paid",
        "payment_status": "paid",
        "payment_intent": "pi_paid",
        "metadata": {"user_id": "user-1", "package": "starter"},
    }
    table = MagicMock()
    table.upsert.return_value.execute.return_value.data = [{"id": "ledger-1"}]
    db = MagicMock()
    db.table.return_value = table

    with patch.object(billing, "get_db", return_value=db):
        billing._handle_checkout_completed(session)

    table.upsert.assert_called_once_with(
        {
            "user_id": "user-1",
            "amount_credits": 1200,
            "status": "settled",
            "description": "Credit purchase — 1,200 credits",
            "stripe_payment_intent_id": "pi_paid",
        },
        on_conflict="stripe_payment_intent_id",
        ignore_duplicates=True,
    )
    table.upsert.return_value.execute.assert_called_once_with()


def test_checkout_webhook_duplicate_conflict_is_a_clean_noop():
    session = {
        "id": "cs_test_duplicate",
        "payment_status": "paid",
        "payment_intent": "pi_paid",
        "metadata": {"user_id": "user-1", "package": "starter"},
    }
    table = MagicMock()
    table.upsert.return_value.execute.return_value.data = []
    db = MagicMock()
    db.table.return_value = table

    with patch.object(billing, "get_db", return_value=db):
        billing._handle_checkout_completed(session)

    table.upsert.return_value.execute.assert_called_once_with()


def test_checkout_origin_uses_configured_url_in_production(monkeypatch):
    monkeypatch.setenv("CANARY_ENV", "production")
    monkeypatch.setenv("SCENEWRIGHT_APP_URL", "https://app.scenewright.ink/")
    request = MagicMock()
    request.headers = {"origin": "https://attacker.example"}

    assert billing._checkout_origin(request) == "https://app.scenewright.ink"


def test_checkout_origin_fails_closed_without_production_url(monkeypatch):
    monkeypatch.setenv("CANARY_ENV", "production")
    monkeypatch.delenv("SCENEWRIGHT_APP_URL", raising=False)
    request = MagicMock()
    request.headers = {"origin": "https://attacker.example"}

    with pytest.raises(HTTPException) as exc_info:
        billing._checkout_origin(request)

    assert exc_info.value.status_code == 500


def test_checkout_origin_requires_https_in_production(monkeypatch):
    monkeypatch.setenv("CANARY_ENV", "production")
    monkeypatch.setenv("SCENEWRIGHT_APP_URL", "http://app.scenewright.ink")
    request = MagicMock()
    request.headers = {}

    with pytest.raises(HTTPException) as exc_info:
        billing._checkout_origin(request)

    assert exc_info.value.status_code == 500


def test_invalid_sentry_dsn_does_not_crash_startup(monkeypatch):
    monkeypatch.setenv("SENTRY_DSN", "not-a-valid-dsn")
    monkeypatch.setattr(sentry_module, "_CONFIGURED", False)

    with patch("sentry_sdk.init", side_effect=ValueError("bad dsn")):
        assert sentry_module.configure_sentry() is False


def test_readiness_fails_closed_when_production_config_is_missing(monkeypatch):
    monkeypatch.setenv("CANARY_ENV", "production")
    for name in (
        "SUPABASE_URL",
        "SUPABASE_SECRET_KEY",
        "LITELLM_BASE_URL",
        "LITELLM_API_KEY",
    ):
        monkeypatch.delenv(name, raising=False)

    ok, checks = app_module._readiness_result()

    assert ok is False
    assert checks == {
        "supabase": "error: missing configuration",
        "litellm": "error: missing configuration",
    }


def test_readiness_allows_missing_dependencies_in_development(monkeypatch):
    monkeypatch.setenv("CANARY_ENV", "dev")
    for name in (
        "SUPABASE_URL",
        "SUPABASE_SECRET_KEY",
        "LITELLM_BASE_URL",
        "LITELLM_API_KEY",
    ):
        monkeypatch.delenv(name, raising=False)

    ok, checks = app_module._readiness_result()

    assert ok is True
    assert checks == {"supabase": "skipped", "litellm": "skipped"}


def test_readiness_endpoint_uses_http_503_on_failure(tmp_path: Path):
    app = app_module.create_app(tmp_path, dev=True)
    endpoint = next(
        route.endpoint for route in app.routes if route.path == "/api/health/ready"
    )

    with patch.object(
        app_module,
        "_readiness_result",
        return_value=(False, {"supabase": "error: TimeoutError", "litellm": "ok"}),
    ):
        response = endpoint()

    assert response.status_code == 503


def test_readiness_endpoint_uses_http_200_on_success(tmp_path: Path):
    app = app_module.create_app(tmp_path, dev=True)
    endpoint = next(
        route.endpoint for route in app.routes if route.path == "/api/health/ready"
    )

    with patch.object(
        app_module,
        "_readiness_result",
        return_value=(True, {"supabase": "ok", "litellm": "ok"}),
    ):
        response = endpoint()

    assert response.status_code == 200


def test_credit_view_uses_callers_rls_context():
    schema = (
        Path(__file__).resolve().parents[2] / "docs" / "supabase-schema.sql"
    ).read_text(encoding="utf-8")

    assert "create or replace view public.user_credits" in schema
    assert "with (security_invoker = true)" in schema
