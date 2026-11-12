"""Card-verified first-chapter grant: fake Stripe and ledger, never live calls."""
import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from novel_to_comic import cold_open
from novel_to_comic.server import card_grant, credits
from novel_to_comic.server.routers import billing


@pytest.fixture
def offer(monkeypatch):
    monkeypatch.setenv("CANARY_CARD_GRANT_CREDITS", "1200")
    for name in ("CANARY_CARD_GRANT_SEATS", "CANARY_CARD_GRANT_ENDS", "CANARY_CARD_GRANT_EXPIRY_DAYS",
                 "CANARY_CARD_GRANT_EXPIRE"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_x")
    events = MagicMock()
    monkeypatch.setattr(billing, "capture_server_event", events)
    return events


def _session(**overrides):
    return {"id": "cs_test_setup", "mode": "setup", "status": "complete", "livemode": False,
            "payment_status": "no_payment_required", "setup_intent": "seti_1",
            "metadata": {"user_id": "account", "purpose": card_grant.PURPOSE}, **overrides}


def _intent(monkeypatch, *, fingerprint="fp_card", funding="credit", status="succeeded"):
    retrieve = MagicMock(return_value={"id": "seti_1", "status": status, "payment_method": {
        "id": "pm_1", "card": {"fingerprint": fingerprint, "funding": funding}}})
    monkeypatch.setattr(billing.stripe.SetupIntent, "retrieve", retrieve)
    return retrieve


def _db(monkeypatch, verdict="granted"):
    db = MagicMock()
    db.rpc.return_value.execute.return_value = SimpleNamespace(data=verdict)
    monkeypatch.setattr(billing, "get_db", lambda: db)
    return db


def test_a_verified_card_is_granted_once_by_the_database(monkeypatch, offer):
    retrieve, db = _intent(monkeypatch), _db(monkeypatch)
    billing._handle_card_grant(_session())
    retrieve.assert_called_once_with("seti_1", expand=["payment_method"])
    name, args = db.rpc.call_args.args
    assert name == "claim_card_chapter_grant"
    assert args["p_user_id"] == "account" and args["p_card_fingerprint"] == "fp_card"
    assert args["p_setup_intent_id"] == "seti_1" and args["p_amount_credits"] == 1200 and args["p_seats"] == 100
    expires = datetime.fromisoformat(args["p_expires_at"]) - datetime.now(UTC)
    assert timedelta(days=29, hours=23) < expires <= timedelta(days=30)
    assert offer.call_args.args == ("card_grant_claimed",)
    assert offer.call_args.kwargs["properties"] == {"credits": 1200, "stripe_mode": "test"}


@pytest.mark.parametrize("verdict, event", [
    ("card_already_used", "card_grant_refused"), ("account_already_claimed", "card_grant_refused"),
    ("seats_taken", "card_grant_refused"), ("duplicate", None),
])
def test_the_database_verdict_decides_repeats(monkeypatch, offer, verdict, event):
    _intent(monkeypatch)
    _db(monkeypatch, verdict)
    billing._handle_card_grant(_session())
    if event is None:
        offer.assert_not_called()  # a webhook retry is not a new refusal
    else:
        assert offer.call_args.args == (event,)
        assert offer.call_args.kwargs["properties"]["reason"] == verdict


@pytest.mark.parametrize("intent, reason", [
    ({"funding": "prepaid"}, "prepaid_card"), ({"fingerprint": None}, "card_unverified"),
    ({"status": "requires_payment_method"}, "card_unverified"),
])
def test_prepaid_and_unverified_cards_get_nothing(monkeypatch, offer, intent, reason):
    _intent(monkeypatch, **intent)
    db = _db(monkeypatch)
    billing._handle_card_grant(_session())
    db.rpc.assert_not_called()
    assert offer.call_args.kwargs["properties"]["reason"] == reason


def test_a_closed_offer_or_incomplete_session_never_reaches_stripe_or_the_ledger(monkeypatch, offer):
    retrieve, db = _intent(monkeypatch), _db(monkeypatch)
    billing._handle_card_grant(_session(status="open"))
    billing._handle_card_grant(_session(setup_intent=None))
    monkeypatch.setenv("CANARY_CARD_GRANT_ENDS", "2020-01-01")
    billing._handle_card_grant(_session())
    assert offer.call_args.kwargs["properties"]["reason"] == "ended"
    retrieve.assert_not_called()
    db.rpc.assert_not_called()


def test_the_webhook_never_treats_a_card_verification_as_a_purchase(monkeypatch, offer):
    purchase, grant = MagicMock(), MagicMock()
    monkeypatch.setattr(billing, "_handle_checkout_completed", purchase)
    monkeypatch.setattr(billing, "_handle_card_grant", grant)
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "whsec_x")
    sessions = [_session(), _session(metadata={"user_id": "account"}), {"mode": "payment", "id": "cs_paid"}]

    async def body():
        yield b"{}"

    for session in sessions:
        monkeypatch.setattr(billing.stripe.Webhook, "construct_event", lambda *a, session=session: {
            "type": "checkout.session.completed", "data": {"object": session}})
        request = SimpleNamespace(headers={"stripe-signature": "sig"}, stream=body)
        assert asyncio.run(billing.stripe_webhook(request)) == {"status": "ok"}
    grant.assert_called_once_with(sessions[0])
    purchase.assert_called_once_with(sessions[2])


def _status_db(*, claimed=None, taken=0):
    db = MagicMock()
    table = db.table.return_value.select.return_value
    table.eq.return_value.limit.return_value.execute.return_value = SimpleNamespace(data=[claimed] if claimed else [])
    table.limit.return_value.execute.return_value = SimpleNamespace(count=taken, data=[])
    return db


def _printed_opening(account_dir, status="ready"):
    project = account_dir / "book"
    record = SimpleNamespace(status=status)
    (project / "cold_open").mkdir(parents=True)
    return record


def test_status_offers_the_grant_only_after_a_printed_opening(tmp_path, monkeypatch, offer):
    account = tmp_path / "account"
    account.mkdir()
    monkeypatch.setattr(cold_open, "read_record", lambda root: None)
    assert card_grant.status(_status_db(), "account", account)["reason"] == "opening_first"
    record = _printed_opening(account, "failed")
    monkeypatch.setattr(cold_open, "read_record", lambda root: record)
    assert card_grant.status(_status_db(), "account", account)["reason"] == "opening_first"
    record.status = "ready"
    state = card_grant.status(_status_db(), "account", account)
    assert state == {"enabled": True, "available": True, "claimed": False, "reason": None, "credits": 1200,
                     "expiry_days": 30, "expires_at": None, "expired": False}
    assert card_grant.status(_status_db(taken=100), "account", account)["reason"] == "seats_taken"
    claimed = {"amount_credits": 1200, "expires_at": "2026-12-12T00:00:00+00:00", "expired_at": None}
    state = card_grant.status(_status_db(claimed=claimed), "account", account)
    assert state["claimed"] and not state["available"] and state["expires_at"] == claimed["expires_at"]
    monkeypatch.setenv("CANARY_CARD_GRANT_ENDS", "not-a-date")
    assert card_grant.status(_status_db(), "account", account)["reason"] == "ended"  # a typo closes the offer
    monkeypatch.setenv("CANARY_CARD_GRANT_CREDITS", "0")
    assert card_grant.status(_status_db(), "account", account) == {
        "enabled": False, "available": False, "claimed": False}


def test_checkout_opens_setup_mode_only_for_an_eligible_account(tmp_path, monkeypatch, offer):
    monkeypatch.setenv("CANARY_ENV", "development")
    monkeypatch.delenv("SCENEWRIGHT_APP_URL", raising=False)
    monkeypatch.setattr(billing, "get_db", lambda: object())
    create = MagicMock(return_value=SimpleNamespace(url="https://checkout.stripe.test/setup", livemode=False))
    monkeypatch.setattr(billing.stripe.checkout.Session, "create", create)
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(projects_dir=tmp_path)),
                              headers={}, state=SimpleNamespace())
    checkout = billing.create_card_grant_checkout.__wrapped__

    monkeypatch.setattr(card_grant, "status", lambda *a: {"available": False, "reason": "opening_first"})
    with pytest.raises(HTTPException) as denied:
        asyncio.run(checkout(request, user_id="account"))
    assert denied.value.status_code == 409 and denied.value.detail["reason"] == "opening_first"
    create.assert_not_called()

    monkeypatch.setattr(card_grant, "status", lambda *a: {"available": True, "reason": None})
    assert asyncio.run(checkout(request, user_id="account")) == {"url": "https://checkout.stripe.test/setup"}
    kwargs = create.call_args.kwargs
    assert kwargs["mode"] == "setup" and kwargs["payment_method_types"] == ["card"]
    assert "line_items" not in kwargs and "customer" not in kwargs  # nothing to pay, no card kept on a customer
    assert kwargs["metadata"] == {"user_id": "account", "purpose": card_grant.PURPOSE}
    assert kwargs["success_url"].endswith("/credits?card_grant=success")


def test_expired_grants_are_swept_before_a_balance_is_read(monkeypatch):
    db = MagicMock()
    db.table.return_value.select.return_value.eq.return_value.execute.return_value = SimpleNamespace(
        data=[{"balance_credits": 40}])
    for name in ("CANARY_CARD_GRANT_CREDITS", "CANARY_CARD_GRANT_EXPIRE"):
        monkeypatch.delenv(name, raising=False)
    assert credits.get_balance_credits(db, "account") == 40
    db.rpc.assert_not_called()  # the feature is off: no call to a function that may not exist
    monkeypatch.setenv("CANARY_CARD_GRANT_EXPIRE", "1")  # the offer is closed but grants still expire
    db.rpc.return_value.execute.side_effect = RuntimeError("database unavailable")
    assert credits.get_balance_credits(db, "account") == 40  # a failed sweep never blocks the balance
    db.rpc.assert_called_once_with("expire_card_chapter_grants", {"p_user_id": "account"})


def _bonus_db(*, grant, inserted=True):
    db = MagicMock()
    grants, ledger = MagicMock(), MagicMock()
    grants.select.return_value.eq.return_value.limit.return_value.execute.return_value = SimpleNamespace(
        data=[grant] if grant else [])
    ledger.upsert.return_value.execute.return_value = SimpleNamespace(data=[{"id": "bonus"}] if inserted else [])
    db.table.side_effect = lambda name: grants if name == "card_chapter_grants" else ledger
    return db, ledger


def test_a_grant_holder_s_first_purchase_gets_bonus_credits_once(monkeypatch):
    live = {"amount_credits": 1200, "expired_at": None,
            "expires_at": (datetime.now(UTC) + timedelta(days=3)).isoformat()}
    bonus = lambda db: card_grant.grant_first_purchase_bonus(db, user_id="account", purchased_credits=1200)  # noqa: E731
    monkeypatch.delenv("CANARY_FIRST_PURCHASE_BONUS_PERCENT", raising=False)
    db, ledger = _bonus_db(grant=live)
    assert bonus(db) == 0  # off unless the operator sets a percentage
    db.table.assert_not_called()
    monkeypatch.setenv("CANARY_FIRST_PURCHASE_BONUS_PERCENT", "50")
    assert bonus(db) == 600
    row = ledger.upsert.call_args
    assert row.args[0]["amount_credits"] == 600 and row.args[0]["usage_call_id"] == "first-purchase-bonus:account"
    assert "stripe_payment_intent_id" not in row.args[0]  # never mistaken for a purchase
    assert row.kwargs == {"on_conflict": "usage_call_id", "ignore_duplicates": True}
    assert bonus(_bonus_db(grant=live, inserted=False)[0]) == 0  # a retry or a second purchase
    assert bonus(_bonus_db(grant=None)[0]) == 0  # no first-chapter grant
    assert bonus(_bonus_db(grant={**live, "expired_at": "2026-11-01T00:00:00+00:00"})[0]) == 0
    lapsed = {**live, "expires_at": (datetime.now(UTC) - timedelta(minutes=1)).isoformat()}
    db, ledger = _bonus_db(grant=lapsed)
    assert bonus(db) == 0
    ledger.upsert.assert_not_called()
    broken = MagicMock()
    broken.table.side_effect = RuntimeError("database unavailable")
    assert bonus(broken) == 0  # the settled purchase is never failed by its bonus
