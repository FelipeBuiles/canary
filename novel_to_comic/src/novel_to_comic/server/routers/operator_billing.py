"""Operator-only, recoverable exception refunds."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, cast

import stripe
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..db import get_db
from ..deployment_status import require_ops_token
from ..product_events import capture_server_event
from .billing import _stripe, _stripe_dict, _wrap_stripe_error

router = APIRouter(dependencies=[Depends(require_ops_token)])
logger = logging.getLogger("canary.operator_billing")


class RefundRequest(BaseModel):
    payment_intent_id: str = Field(min_length=3, max_length=255)
    operator: str = Field(min_length=2, max_length=120)
    reason: str = Field(min_length=5, max_length=1000)


def _rows(response: Any) -> list[dict[str, Any]]:
    return cast(list[dict[str, Any]], response.data or [])


def _refund_eligibility_error(
    grant: dict[str, Any], later_debits: list[dict[str, Any]]
) -> str | None:
    credits = grant.get("amount_credits")
    if (
        not isinstance(credits, int)
        or credits <= 0
        or grant.get("status") != "settled"
        or not grant.get("user_id")
        or not grant.get("id")
    ):
        return "The original credit grant is missing or ambiguous."
    if not isinstance(grant.get("gross_amount_cents"), int):
        return "The original payment amount is unavailable."
    if later_debits:
        return (
            "Credits may have been consumed after this purchase. "
            "Stop for manual ledger review."
        )
    return None


def _find_refund(db: Any, payment_intent_id: str) -> dict[str, Any] | None:
    response = (
        db.table("credit_refunds")
        .select("*")
        .eq("stripe_payment_intent_id", payment_intent_id)
        .limit(1)
        .execute()
    )
    rows = _rows(response)
    return rows[0] if rows else None


def _later_debits(db: Any, grant: dict[str, Any]) -> list[dict[str, Any]]:
    response = (
        db.table("credit_ledger")
        .select("id,amount_credits,status,created_at")
        .eq("user_id", grant["user_id"])
        .lt("amount_credits", 0)
        .gt("created_at", grant["created_at"])
        .neq("status", "released")
        .execute()
    )
    return _rows(response)


def _record_pending_refund(
    db: Any, request: RefundRequest, grant: dict[str, Any]
) -> dict[str, Any]:
    """Atomically prove eligibility and hold the refundable credits."""
    response = db.rpc(
        "prepare_credit_refund",
        {
            "p_payment_intent_id": request.payment_intent_id,
            "p_operator": request.operator,
            "p_reason": request.reason,
        },
    ).execute()
    rows = _rows(response)
    if not rows:
        raise HTTPException(503, "Could not persist the refund recovery hold.")
    record = rows[0]
    if record.get("ledger_grant_id") != grant["id"]:
        raise HTTPException(409, "Refund recovery record does not match the grant.")
    return record


def _complete_ledger_reversal(
    db: Any,
    *,
    record: dict[str, Any],
    grant: dict[str, Any],
    stripe_refund_id: str,
) -> None:
    del grant
    response = db.rpc(
        "complete_credit_refund",
        {
            "p_refund_record_id": record["id"],
            "p_stripe_refund_id": stripe_refund_id,
            "p_completed_at": datetime.now(timezone.utc).isoformat(),
        },
    ).execute()
    if not response.data:
        raise RuntimeError("Refund completion did not return a record")


def _verify_refund_identity(refund: dict, record: dict, grant: dict) -> str:
    """A refund ID alone proves neither its amount nor that money was returned."""
    refund_id = refund.get("id")
    payment_intent = refund.get("payment_intent")
    if isinstance(payment_intent, dict):
        payment_intent = payment_intent.get("id")
    if (
        not isinstance(refund_id, str) or not refund_id.startswith("re_")
        or (record.get("stripe_refund_id") and refund_id != record["stripe_refund_id"])
        or payment_intent != record["stripe_payment_intent_id"]
        or type(refund.get("amount")) is not int
        or refund["amount"] != record["amount_cents"]
        or refund.get("currency") != (grant.get("currency") or "usd")
    ):
        raise HTTPException(502, "Stripe refund does not match the persisted refund request. Reconciliation is required.")
    return refund_id


@router.post("/refunds")
def refund_unused_credit_grant(body: RefundRequest):
    """Refund one provably unused purchase and reverse its credits exactly once."""
    db = get_db()
    grants = _rows(
        db.table("credit_ledger")
        .select("*")
        .eq("stripe_payment_intent_id", body.payment_intent_id)
        .execute()
    )
    if not grants:
        raise HTTPException(404, "Original credit grant not found.")
    if len(grants) != 1:
        raise HTTPException(409, "Original credit grant ownership is ambiguous.")
    grant = grants[0]

    record = _find_refund(db, body.payment_intent_id)
    if record and record.get("status") == "completed":
        return {
            "status": "completed",
            "stripe_refund_id": record.get("stripe_refund_id"),
            "credits_reversed": record.get("credits_reversed"),
            "idempotent": True,
        }

    if record is None:
        error = _refund_eligibility_error(grant, _later_debits(db, grant))
        if error:
            raise HTTPException(409, error)
        try:
            record = _record_pending_refund(db, body, grant)
        except HTTPException:
            raise
        except Exception as exc:
            # A concurrent request may have won the unique payment-intent row.
            record = _find_refund(db, body.payment_intent_id)
            if record is None:
                raise HTTPException(
                    409,
                    "Refund eligibility changed during preparation. Review the ledger before retrying.",
                ) from exc

    if record.get("ledger_grant_id") != grant["id"] or record.get("user_id") != grant["user_id"]:
        raise HTTPException(409, "Refund recovery record does not match the grant.")
    _stripe()
    try:
        if record.get("stripe_refund_id"):
            # Pending/requires_action is not success. Inspect the SAME refund on
            # recovery, rather than completing blindly or issuing another one.
            refund = _stripe_dict(stripe.Refund.retrieve(record["stripe_refund_id"]))
        else:
            refund = _stripe_dict(stripe.Refund.create(
                payment_intent=record["stripe_payment_intent_id"],
                amount=record["amount_cents"],
                reason="requested_by_customer",
                metadata={
                    "operator": record["operator"],
                    "ledger_grant_id": record["ledger_grant_id"],
                },
                idempotency_key=f"canary-refund:{record['stripe_payment_intent_id']}",
            ))
    except stripe.error.StripeError as exc:
        raise _wrap_stripe_error(exc) from exc

    stripe_refund_id = _verify_refund_identity(refund, record, grant)
    succeeded = refund.get("status") == "succeeded"
    try:
        # Persist pending/failed IDs as well: future retries must inspect the
        # existing Stripe object. The existing negative reservation stays held.
        db.table("credit_refunds").update({
            "stripe_refund_id": stripe_refund_id,
            "status": "stripe_succeeded" if succeeded else "pending",
        }).eq("id", record["id"]).neq("status", "completed").execute()
    except Exception as exc:
        logger.exception("Stripe refund %s recovery record update failed", stripe_refund_id)
        raise HTTPException(
            503, "Stripe refund recorded remotely; local reconciliation is pending. Retry this operation.",
        ) from exc

    if not succeeded:
        if refund.get("status") in {"pending", "requires_action"}:
            raise HTTPException(409, "Stripe refund is pending; credits remain on hold. Retry to check this same refund after Stripe completes it.")
        raise HTTPException(409, "Stripe refund has not succeeded; credits remain on hold for manual reconciliation. No additional refund was issued.")

    try:
        _complete_ledger_reversal(
            db,
            record=record,
            grant=grant,
            stripe_refund_id=stripe_refund_id,
        )
    except Exception as exc:
        logger.exception("Stripe refund %s requires ledger reconciliation", stripe_refund_id)
        raise HTTPException(
            503, "Refund accepted; credit reconciliation is pending. Retry this operation.",
        ) from exc

    capture_server_event(
        "refund_completed",
        user_id=grant["user_id"],
        properties={
            "credits": record["credits_reversed"],
            "gross_amount_cents": record["amount_cents"],
            "currency": grant.get("currency") or "usd",
        },
    )
    return {
        "status": "completed",
        "stripe_refund_id": stripe_refund_id,
        "credits_reversed": record["credits_reversed"],
        "idempotent": False,
    }
