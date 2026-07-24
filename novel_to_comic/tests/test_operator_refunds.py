from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from novel_to_comic.server.routers import operator_billing


def _grant():
    return {
        "id": "grant-1",
        "user_id": "user-1",
        "amount_credits": 1200,
        "status": "settled",
        "gross_amount_cents": 1200,
        "currency": "usd",
        "created_at": "2026-07-24T10:00:00Z",
        "stripe_payment_intent_id": "pi_123",
    }


def test_refund_eligibility_stops_when_later_debits_exist():
    error = operator_billing._refund_eligibility_error(
        _grant(),
        [{"id": "debit-1", "amount_credits": -1}],
    )

    assert error is not None
    assert "manual ledger review" in error


def test_refund_eligibility_accepts_unconsumed_complete_grant():
    assert operator_billing._refund_eligibility_error(_grant(), []) is None


def test_completed_refund_retry_is_a_noop():
    ledger = MagicMock()
    ledger.select.return_value = ledger
    ledger.eq.return_value = ledger
    ledger.execute.return_value = SimpleNamespace(data=[_grant()])

    refunds = MagicMock()
    refunds.select.return_value = refunds
    refunds.eq.return_value = refunds
    refunds.limit.return_value = refunds
    refunds.execute.return_value = SimpleNamespace(
        data=[
            {
                "id": "refund-record",
                "status": "completed",
                "stripe_refund_id": "re_123",
                "credits_reversed": 1200,
            }
        ]
    )

    db = MagicMock()
    db.table.side_effect = lambda name: {
        "credit_ledger": ledger,
        "credit_refunds": refunds,
    }[name]

    with (
        patch.object(operator_billing, "get_db", return_value=db),
        patch.object(
            operator_billing.stripe.Refund,
            "create",
            side_effect=AssertionError("Stripe must not be called"),
        ),
    ):
        result = operator_billing.refund_unused_credit_grant(
            operator_billing.RefundRequest(
                payment_intent_id="pi_123",
                operator="operator@example.com",
                reason="Approved unused-credit exception",
            )
        )

    assert result == {
        "status": "completed",
        "stripe_refund_id": "re_123",
        "credits_reversed": 1200,
        "idempotent": True,
    }


def test_schema_protects_refund_records_and_ledger_idempotency():
    from pathlib import Path

    schema = (Path(__file__).parents[2] / "docs" / "supabase-schema.sql").read_text()

    assert "create table if not exists public.credit_refunds" in schema
    assert "stripe_payment_intent_id  text        not null unique" in schema
    assert "credit_ledger_stripe_refund_id_idx" in schema
    assert "create or replace function public.prepare_credit_refund" in schema
    assert "pg_advisory_xact_lock" in schema
    assert "'refund_hold'" in schema
    assert "create or replace function public.complete_credit_refund" in schema
    assert "revoke all on public.credit_refunds from public, anon, authenticated" in schema
