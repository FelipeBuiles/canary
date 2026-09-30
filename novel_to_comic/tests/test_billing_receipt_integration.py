"""Billing boundary tests use fake Stripe/ledger services, never live payments."""
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from novel_to_comic.server.routers import billing, operator_billing
from novel_to_comic.server.checkout_receipts import offer_snapshot


def _paid_session():
    return {
        "id": "cs_test_purchase", "payment_intent": "pi_purchase",
        "mode": "payment", "status": "complete", "payment_status": "paid", "livemode": False,
        "amount_total": 1200, "currency": "usd",
        "metadata": {"user_id": "account", "package": "starter", **offer_snapshot(1200, 1200)},
    }


def test_fulfillment_uses_snapshot_and_database_deduplication(monkeypatch):
    db = MagicMock()
    db.table.return_value.upsert.return_value.execute.side_effect = [
        SimpleNamespace(data=[{"id": "grant"}]), SimpleNamespace(data=[]),
    ]
    monkeypatch.setattr(billing, "get_db", lambda: db)
    events = MagicMock()
    monkeypatch.setattr(billing, "capture_server_event", events)
    monkeypatch.setitem(billing.CREDIT_PACKAGES, "starter", {"credits": 9999, "price_cents": 9999, "label": "changed"})
    session = _paid_session()
    billing._handle_checkout_completed(session)
    billing._handle_checkout_completed(session)
    call = db.table.return_value.upsert.call_args
    assert call.args[0]["amount_credits"] == 1200
    assert call.args[0]["gross_amount_cents"] == 1200
    assert call.kwargs == {"on_conflict": "stripe_payment_intent_id", "ignore_duplicates": True}
    assert call.args[0]["stripe_mode"] == "test"
    assert call.args[0]["purchase_event_environment"]
    assert call.args[0]["purchase_event_release"]
    events.assert_not_called()


def test_invalid_paid_receipt_never_touches_ledger(monkeypatch):
    db = MagicMock()
    monkeypatch.setattr(billing, "get_db", db)
    session = _paid_session()
    session["amount_total"] = 1
    with pytest.raises(HTTPException) as caught:
        billing._handle_checkout_completed(session)
    assert caught.value.status_code == 400
    db.assert_not_called()


def test_webhook_database_failure_is_not_acknowledged(monkeypatch):
    db = MagicMock()
    db.table.return_value.upsert.return_value.execute.side_effect = TimeoutError("lost response")
    monkeypatch.setattr(billing, "get_db", lambda: db)
    with pytest.raises(TimeoutError):
        billing._handle_checkout_completed(_paid_session())


@pytest.fixture
def refund_services(monkeypatch):
    grant = {
        "id": "grant", "user_id": "account", "amount_credits": 1200,
        "gross_amount_cents": 1200, "currency": "usd", "status": "settled",
    }
    record = {
        "id": "refund-record", "ledger_grant_id": "grant", "user_id": "account",
        "stripe_payment_intent_id": "pi_purchase", "stripe_refund_id": None,
        "amount_cents": 1200, "credits_reversed": 1200,
        "operator": "original-operator", "status": "pending",
    }
    refund = {"id": "re_purchase", "payment_intent": "pi_purchase", "amount": 1200, "currency": "usd", "status": "pending"}
    db = MagicMock()
    db.table.return_value.select.return_value.eq.return_value.execute.return_value = SimpleNamespace(data=[grant])
    monkeypatch.setattr(operator_billing, "get_db", lambda: db)
    monkeypatch.setattr(operator_billing, "_find_refund", lambda *args: dict(record))
    monkeypatch.setattr(operator_billing, "_stripe", lambda: None)
    create = MagicMock(side_effect=lambda **kwargs: dict(refund))
    retrieve = MagicMock(side_effect=lambda refund_id: dict(refund))
    monkeypatch.setattr(operator_billing.stripe.Refund, "create", create)
    monkeypatch.setattr(operator_billing.stripe.Refund, "retrieve", retrieve)
    complete = MagicMock()
    events = MagicMock()
    monkeypatch.setattr(operator_billing, "_complete_ledger_reversal", complete)
    monkeypatch.setattr(operator_billing, "capture_server_event", events)
    body = operator_billing.RefundRequest(payment_intent_id="pi_purchase", operator="different-operator", reason="customer request")
    return SimpleNamespace(db=db, record=record, refund=refund, create=create, retrieve=retrieve, complete=complete, events=events, body=body)


@pytest.mark.parametrize("status", ["pending", "requires_action", "failed", "canceled", None, "unexpected"])
def test_non_succeeded_refund_never_finalizes_ledger(refund_services, status):
    services = refund_services
    services.refund["status"] = status
    with pytest.raises(HTTPException) as caught:
        operator_billing.refund_unused_credit_grant(services.body)
    assert caught.value.status_code == 409
    services.complete.assert_not_called()
    services.events.assert_not_called()
    update = services.db.table.return_value.update.call_args.args[0]
    assert update == {"stripe_refund_id": "re_purchase", "status": "pending"}


def test_refund_retry_inspects_existing_object_and_only_then_completes(refund_services):
    services = refund_services
    services.record["stripe_refund_id"] = "re_purchase"
    with pytest.raises(HTTPException):
        operator_billing.refund_unused_credit_grant(services.body)
    services.complete.assert_not_called()
    services.refund["status"] = "succeeded"
    result = operator_billing.refund_unused_credit_grant(services.body)
    assert result["status"] == "completed"
    assert result["credits_reversed"] == 1200
    services.create.assert_not_called()
    assert services.retrieve.call_count == 2
    services.complete.assert_called_once()
    services.events.assert_called_once()


def test_refund_create_uses_persisted_idempotent_parameters(refund_services):
    services = refund_services
    with pytest.raises(HTTPException):
        operator_billing.refund_unused_credit_grant(services.body)
    params = services.create.call_args.kwargs
    assert params["metadata"]["operator"] == "original-operator"
    assert params["idempotency_key"] == "canary-refund:pi_purchase"
    assert params["amount"] == services.record["amount_cents"]


@pytest.mark.parametrize("field,value", [("amount", 1), ("amount", True), ("currency", "cad"), ("payment_intent", "pi_other"), ("id", None)])
def test_wrong_refund_evidence_cannot_reverse_credits(refund_services, field, value):
    services = refund_services
    services.refund.update(status="succeeded")
    services.refund[field] = value
    with pytest.raises(HTTPException) as caught:
        operator_billing.refund_unused_credit_grant(services.body)
    assert caught.value.status_code == 502
    services.complete.assert_not_called()


def test_refund_success_local_failure_preserves_recovery(refund_services):
    services = refund_services
    services.refund["status"] = "succeeded"
    services.complete.side_effect = TimeoutError("lost local response")
    with pytest.raises(HTTPException) as caught:
        operator_billing.refund_unused_credit_grant(services.body)
    assert caught.value.status_code == 503
    services.events.assert_not_called()
    assert services.db.table.return_value.update.call_args.args[0]["stripe_refund_id"] == "re_purchase"


@pytest.mark.parametrize("livemode, expected", [(True, "live"), (False, "test"), (None, "unknown")])
def test_purchase_mode_never_guessed_from_account_or_session_name(monkeypatch, livemode, expected):
    db = MagicMock()
    monkeypatch.setattr(billing, "get_db", lambda: db)
    monkeypatch.setenv("CANARY_ENV", "production")
    monkeypatch.setenv("CANARY_VERSION", "fixture-release")
    session = _paid_session()
    session["livemode"] = livemode
    billing._handle_checkout_completed(session)
    payload = db.table.return_value.upsert.call_args.args[0]
    assert payload["stripe_mode"] == expected
    assert payload["user_id"] == "account"
    assert payload["purchase_event_environment"] == "production"
    assert payload["purchase_event_release"] == "fixture-release"
