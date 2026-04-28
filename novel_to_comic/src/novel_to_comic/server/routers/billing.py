"""Stripe Checkout and webhook for credit purchases."""

import logging
import os
from typing import Any

import stripe
from fastapi import APIRouter, Depends, HTTPException, Request

from ..auth import get_current_user
from ..db import get_db

router = APIRouter()
logger = logging.getLogger("pulp.billing")

CREDIT_PACKAGES: dict[str, dict] = {
    "10": {"label": "1,000 credits", "price_cents": 1000, "credits": 1000},
    "25": {"label": "2,750 credits", "price_cents": 2500, "credits": 2750},
    "50": {"label": "6,000 credits", "price_cents": 5000, "credits": 6000},
}


def _stripe() -> None:
    key = os.environ.get("STRIPE_SECRET_KEY", "")
    if not key:
        raise HTTPException(500, "STRIPE_SECRET_KEY is not configured")
    stripe.api_key = key


def _stripe_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _stripe_value(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_stripe_value(v) for v in value]
    try:
        data = object.__getattribute__(value, "_data")
    except Exception:
        return value
    if isinstance(data, dict):
        return {k: _stripe_value(v) for k, v in data.items()}
    return value


def _stripe_dict(value: Any) -> dict:
    normalized = _stripe_value(value)
    return normalized if isinstance(normalized, dict) else {}


@router.get("/packages")
def list_packages():
    """Return available credit packages — used by the frontend to render buy buttons."""
    return {"packages": [
        {"id": k, **{kk: vv for kk, vv in v.items()}}
        for k, v in CREDIT_PACKAGES.items()
    ]}


@router.post("/checkout")
async def create_checkout(
    request: Request,
    body: dict,
    user_id: str = Depends(get_current_user),
):
    package_id = body.get("package")
    if package_id not in CREDIT_PACKAGES:
        raise HTTPException(400, f"Unknown package '{package_id}'. Valid: {list(CREDIT_PACKAGES)}")

    pkg = CREDIT_PACKAGES[package_id]
    _stripe()

    # Use the request origin for redirect URLs so this works in both dev and prod
    # without an extra env var.
    origin = request.headers.get("origin", "http://localhost:5173")

    session = stripe.checkout.Session.create(
        payment_method_types=["card"],
        line_items=[{
            "price_data": {
                "currency": "usd",
                "product_data": {"name": f"Pulp — {pkg['credits']} credits ({pkg['label']})"},
                "unit_amount": pkg["price_cents"],
            },
            "quantity": 1,
        }],
        mode="payment",
        success_url=f"{origin}/credits?success=true",
        cancel_url=f"{origin}/credits",
        metadata={"user_id": user_id, "package": package_id},
    )

    return {"url": session.url}


@router.post("/webhook")
async def stripe_webhook(request: Request):
    """Receive Stripe events. Must use raw request body for signature verification."""
    payload = await request.body()
    sig = request.headers.get("stripe-signature", "")
    secret = os.environ.get("STRIPE_WEBHOOK_SECRET", "")
    if not secret:
        raise HTTPException(500, "STRIPE_WEBHOOK_SECRET is not configured")

    try:
        event = stripe.Webhook.construct_event(payload, sig, secret)
    except stripe.SignatureVerificationError:
        logger.warning("Stripe webhook signature verification failed")
        raise HTTPException(400, "Invalid signature")
    except Exception as exc:
        logger.warning("Stripe webhook parse error: %s", exc)
        raise HTTPException(400, "Invalid payload")

    if event["type"] == "checkout.session.completed":
        session = _stripe_dict(event["data"]["object"])
        _handle_checkout_completed(session)

    return {"status": "ok"}


def _handle_checkout_completed(session: dict) -> None:
    metadata = session.get("metadata") or {}
    user_id = metadata.get("user_id")
    package_id = metadata.get("package")

    if not user_id or package_id not in CREDIT_PACKAGES:
        logger.warning(
            "checkout.session.completed missing metadata — session %s", session.get("id")
        )
        return

    payment_intent_id = session.get("payment_intent")
    credits = CREDIT_PACKAGES[package_id]["credits"]
    db = get_db()

    # Idempotency: skip if we already processed this payment intent.
    if payment_intent_id:
        existing = (
            db.table("credit_ledger")
            .select("id")
            .eq("stripe_payment_intent_id", payment_intent_id)
            .execute()
        )
        if existing.data:
            logger.info("Duplicate webhook for payment_intent %s — skipping", payment_intent_id)
            return

    db.table("credit_ledger").insert({
        "user_id": user_id,
        "amount_credits": credits,
        "status": "settled",
        "description": f"Credit purchase — {CREDIT_PACKAGES[package_id]['label']}",
        "stripe_payment_intent_id": payment_intent_id,
    }).execute()

    logger.info("Added %d credits for user %s (payment_intent %s)", credits, user_id, payment_intent_id)
