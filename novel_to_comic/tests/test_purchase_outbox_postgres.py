"""Isolated real-Postgres purchase outbox + intercepted delivery regressions.

Use CREDIT_TEST_DATABASE_URL only for a disposable database with Canary schema.
No Stripe or PostHog requests are made.
"""

import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pytest

from novel_to_comic.server import analytics_delivery
from tests.test_credit_ledger_postgres import Ledger, _literal
from tests.test_credit_ledger_postgres import ledger as ledger_fixture


@pytest.fixture
def ledger():
    yield from ledger_fixture.__wrapped__()


@pytest.fixture
def purchase_db(ledger):
    db, user = ledger

    def insert(payment="pi_fixture", mode="test"):
        return db.query(f"""insert into public.credit_ledger(
            user_id,amount_credits,status,stripe_payment_intent_id,stripe_checkout_session_id,
            credit_package_id,gross_amount_cents,currency,stripe_mode,purchase_event_environment,purchase_event_release)
            values ('{user}',1200,'settled',{_literal(payment)},{_literal("cs_" + payment)},
            'starter',1200,'usd',{_literal(mode)},'fixture','fixture-release')
            on conflict (stripe_payment_intent_id) do nothing returning id;""")

    try:
        yield db, user, insert
    finally:
        db.query(f"delete from public.product_events where user_id='{user}';")


def pending(db, user):
    return json.loads(
        db.query(
            f"select coalesce(json_agg(t),'[]') from (select * from public.product_events where user_id='{user}' and posthog_exported_at is null) t;"
        )
    )


def test_atomic_purchase_and_concurrent_duplicate_delivery(purchase_db):
    db, user, insert = purchase_db

    def delivery(_):
        try:
            insert()
        except RuntimeError as exc:
            # Existing separate checkout-session uniqueness can race the payment
            # intent arbiter. Stripe retries an unacknowledged delivery safely.
            if "credit_ledger_checkout_session_idx" not in str(exc):
                raise
            insert()

    with ThreadPoolExecutor(2) as pool:
        list(pool.map(delivery, range(2)))
    assert (
        db.query(
            f"select sum(amount_credits) from public.credit_ledger where user_id='{user}';"
        )
        == "1205"
    )
    # Read using a new connection object, representing a restarted app process.
    rows = pending(Ledger(db.url), user)
    assert len(rows) == 1
    row = rows[0]
    assert row["user_id"] == user and row["event_name"] == "credits_purchased"
    assert row["properties_json"] == dict(
        schema_version=1,
        environment="fixture",
        release="fixture-release",
        stripe_mode="test",
        package_id="starter",
        credits=1200,
        gross_amount_cents=1200,
        currency="usd",
    )
    grant = db.query(
        "select id from public.credit_ledger where stripe_payment_intent_id='pi_fixture';"
    )
    assert row["id"] == db.query(f"select md5('credits_purchased:{grant}')::uuid;")
    assert "pi_fixture" not in json.dumps(row) and "cs_" not in json.dumps(row)


def test_event_insert_failure_rolls_back_entitlement_and_recovers(purchase_db):
    db, user, insert = purchase_db
    db.query(
        "alter table public.product_events add constraint fixture_reject_purchase check (event_name <> 'credits_purchased') not valid;"
    )
    try:
        with pytest.raises(RuntimeError):
            insert("pi_rollback")
        assert (
            db.query(
                "select count(*) from public.credit_ledger where stripe_payment_intent_id='pi_rollback';"
            )
            == "0"
        )
        assert pending(db, user) == []
    finally:
        db.query(
            "alter table public.product_events drop constraint fixture_reject_purchase;"
        )
    insert("pi_rollback")
    assert len(pending(db, user)) == 1


@pytest.mark.parametrize("mode", ["test", "live", "unknown"])
def test_purchase_mode_and_account_are_frozen(purchase_db, mode):
    db, user, insert = purchase_db
    insert("pi_mode_" + mode, mode)
    row = pending(db, user)[0]
    assert row["properties_json"]["stripe_mode"] == mode
    assert analytics_delivery.wire_event(row)["distinct_id"] == user


def test_vendor_outage_lost_ack_and_restart_eventual_delivery(purchase_db, monkeypatch):
    db, user, insert = purchase_db
    insert("pi_delivery")
    monkeypatch.setenv("POSTHOG_HOST", "https://us.i.posthog.com")
    monkeypatch.setenv("POSTHOG_PROJECT_TOKEN", "fixture-only")
    monkeypatch.setattr(
        analytics_delivery, "_pending", lambda: pending(Ledger(db.url), user)
    )

    def ack(ids):
        db.query(
            f"update public.product_events set posthog_exported_at=now() where id in ({','.join(_literal(i) for i in ids)});"
        )

    monkeypatch.setattr(analytics_delivery, "_ack", ack)
    received = {}
    attempts = []

    class Vendor:
        failure = "outage"

        async def post(self, url, json):
            batch = json["batch"]
            attempts.extend(batch)
            if self.failure == "outage":
                raise TimeoutError("vendor unavailable")
            for item in batch:
                received[item["properties"]["$insert_id"]] = item
            if self.failure == "lost-response":
                raise TimeoutError("vendor accepted; response lost")
            return SimpleNamespace(raise_for_status=lambda: None)

    vendor = Vendor()
    with pytest.raises(TimeoutError):
        asyncio.run(analytics_delivery.deliver_once(vendor))
    assert len(pending(db, user)) == 1 and not received
    vendor.failure = "lost-response"
    with pytest.raises(TimeoutError):
        asyncio.run(analytics_delivery.deliver_once(vendor))
    assert len(pending(db, user)) == 1 and len(received) == 1
    vendor.failure = None
    # A fresh client and fresh DB connections deliver the committed event after restart.
    restarted = Vendor()
    restarted.failure = None
    assert asyncio.run(analytics_delivery.deliver_once(restarted)) == 1
    assert pending(db, user) == [] and len(received) == 1
    assert len({item["properties"]["$insert_id"] for item in attempts}) == 1
    assert asyncio.run(analytics_delivery.deliver_once(restarted)) == 0


def test_migration_rerun_does_not_backfill_historical_purchases(purchase_db):
    db, user, insert = purchase_db
    db.query("alter table public.credit_ledger disable trigger settled_purchase_event;")
    try:
        insert("pi_before_migration")
    finally:
        db.query(
            "alter table public.credit_ledger enable trigger settled_purchase_event;"
        )
    migration = (Path(__file__).resolve().parents[2] / "docs/migrations/2026-09-30-purchase-event-outbox.sql").read_text()
    db.query(migration)
    db.query(migration)
    assert pending(db, user) == []
    insert("pi_after_migration")
    assert len(pending(db, user)) == 1


def test_webhook_commit_response_loss_and_restarted_retry(purchase_db, monkeypatch):
    from novel_to_comic.server.routers import billing
    from tests.test_billing_receipt_integration import _paid_session

    db, user, _ = purchase_db
    session = _paid_session()
    session["metadata"]["user_id"] = user

    class Database:
        def __init__(self, lose_response=False):
            self.lose_response = lose_response

        def table(self, name):
            assert name == "credit_ledger"
            return self

        def upsert(self, payload, **kwargs):
            self.payload = payload
            assert kwargs == {
                "on_conflict": "stripe_payment_intent_id",
                "ignore_duplicates": True,
            }
            return self

        def execute(self):
            columns = ",".join(self.payload)
            values = ",".join(_literal(value) for value in self.payload.values())
            result = db.query(
                f"insert into public.credit_ledger ({columns}) values ({values}) on conflict (stripe_payment_intent_id) do nothing returning id;"
            )
            if self.lose_response:
                raise TimeoutError("committed settlement; webhook response lost")
            return SimpleNamespace(data=[{"id": result}] if result else [])

    monkeypatch.setenv("CANARY_ENV", "fixture")
    monkeypatch.setattr(billing, "get_db", lambda: Database(lose_response=True))
    with pytest.raises(TimeoutError):
        billing._handle_checkout_completed(session)
    original = pending(db, user)
    assert len(original) == 1
    monkeypatch.setattr(billing, "get_db", lambda: Database())
    billing._handle_checkout_completed(session)
    assert pending(db, user) == original
    assert (
        db.query(
            f"select sum(amount_credits) from public.credit_ledger where user_id='{user}';"
        )
        == "1205"
    )


def test_migration_before_old_writer_release_does_not_double_emit(purchase_db):
    db, user, _ = purchase_db
    db.query(
        f"insert into public.credit_ledger(user_id,amount_credits,stripe_payment_intent_id,stripe_checkout_session_id) values ('{user}',1200,'pi_old_writer','cs_old_writer');"
    )
    assert pending(db, user) == []
