"""Stripe Checkout and webhook for credit purchases."""

import logging
import os
from typing import Any

import stripe
from fastapi import APIRouter, Depends, HTTPException, Request

from ..auth import get_current_user
from ..branding import get_branding
from ..db import get_db

router = APIRouter()
logger = logging.getLogger("pulp.billing")

# Pricing set per docs/proposals/pricing-and-margin.md (PULP_MODEL_COST_MARKUP=2.0,
# PULP_CREDITS_PER_PROVIDER_USD=100). Bulk tiers discount via more credits per
# dollar, not lower per-credit pricing — same "credits never expire" model the
# indie-author audience expects. A typical 60k-word book is ~2,540 credits, so
# Standard covers one full book + regen headroom.
CREDIT_PACKAGES: dict[str, dict] = {
    "starter": {"label": "1,200 credits", "price_cents": 1200, "credits": 1200},
    "standard": {"label": "3,000 credits", "price_cents": 3000, "credits": 3000},
    "creator": {"label": "7,500 credits", "price_cents": 7000, "credits": 7500},
    "studio": {"label": "18,000 credits", "price_cents": 15000, "credits": 18000},
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


def _wrap_stripe_error(exc: Exception) -> HTTPException:
    """Turn a stripe.error.StripeError into a useful HTTPException.

    Without this, any Stripe failure (bad key, rate limit, invalid request)
    propagates as a generic 500 with no detail — the user just sees
    'Internal Server Error' and ops sees nothing in the response. Map the
    common cases to specific status codes so the cause is obvious.
    """
    if isinstance(exc, stripe.error.AuthenticationError):
        # Most common deploy cause: STRIPE_SECRET_KEY missing, expired, or wrong
        # mode (test vs live). Log the full detail; surface a short message.
        logger.exception("Stripe authentication failed — check STRIPE_SECRET_KEY")
        return HTTPException(500, "Stripe authentication failed — check STRIPE_SECRET_KEY")
    if isinstance(exc, stripe.error.PermissionError):
        logger.exception("Stripe permission error (key lacks required scope)")
        return HTTPException(500, "Stripe key lacks permission for this operation")
    if isinstance(exc, stripe.error.RateLimitError):
        return HTTPException(429, "Stripe rate limit reached — please retry shortly")
    if isinstance(exc, stripe.error.InvalidRequestError):
        logger.warning("Invalid Stripe request: %s", exc)
        return HTTPException(502, f"Stripe rejected the request: {exc.user_message or exc}")
    # APIConnectionError, SignatureVerificationError, generic StripeError, etc.
    logger.exception("Stripe call failed")
    return HTTPException(502, f"Stripe call failed: {exc.user_message or exc}")


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
    branding = get_branding()

    # Use the request origin for redirect URLs so this works in both dev and prod
    # without an extra env var.
    origin = request.headers.get("origin", "http://localhost:5173")

    try:
        session = stripe.checkout.Session.create(
            payment_method_types=["card"],
            line_items=[{
                "price_data": {
                    "currency": "usd",
                    "product_data": {"name": f"{branding.product_name} — {pkg['credits']} credits ({pkg['label']})"},
                    "unit_amount": pkg["price_cents"],
                },
                "quantity": 1,
            }],
            mode="payment",
            # Surface the ToS at the moment of payment and require explicit consent.
            # Stripe records the acceptance; this is the strongest consent signal we
            # collect (stronger than browsewrap text on signup).
            terms_of_service_url=branding.terms_url,
            consent_collection={"terms_of_service": "required"},
            success_url=f"{origin}/credits?success=true",
            cancel_url=f"{origin}/credits",
            metadata={"user_id": user_id, "package": package_id},
        )
    except stripe.error.StripeError as exc:
        raise _wrap_stripe_error(exc) from exc

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
