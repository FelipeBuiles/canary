"""Stripe Checkout and webhook for credit purchases."""

import logging
import os
from typing import Any
from urllib.parse import urlparse

import stripe
from fastapi import APIRouter, Depends, HTTPException, Request
from starlette.concurrency import run_in_threadpool

from ..auth import get_current_user
from ..branding import get_branding
from ..checkout_receipts import InvalidCheckoutReceipt, checkout_receipt, offer_snapshot
from ..db import get_db
from ..product_events import capture_server_event

router = APIRouter()
logger = logging.getLogger("pulp.billing")

# Pricing set per docs/proposals/pricing-and-margin.md (PULP_MODEL_COST_MARKUP=2.0,
# PULP_CREDITS_PER_PROVIDER_USD=100). Bulk tiers discount via more credits per
# dollar. Credit packs do not guarantee a page count or a complete book;
# coverage depends on measured complete-page production and correction costs.
CREDIT_PACKAGES: dict[str, dict] = {
    "starter": {"label": "1,200 credits", "price_cents": 1200, "credits": 1200},
    "standard": {"label": "3,000 credits", "price_cents": 3000, "credits": 3000},
    "creator": {"label": "7,500 credits", "price_cents": 7000, "credits": 7500},
    "studio": {"label": "18,000 credits", "price_cents": 15000, "credits": 18000},
}


def _offer_version() -> str:
    return (
        os.environ.get("CANARY_OFFER_VERSION", "public-credit-offer-v1").strip()
        or "public-credit-offer-v1"
    )[:120]


def _stripe() -> None:
    key = os.environ.get("STRIPE_SECRET_KEY", "")
    if not key:
        raise HTTPException(500, "STRIPE_SECRET_KEY is not configured")
    stripe.api_key = key


def _stripe_icon_url() -> str:
    """Return the public Scenewright mark used by Stripe Checkout.

    Stripe fetches URL-hosted branding from its servers, so this must be a
    publicly reachable HTTPS URL in production. Keep it configurable for
    staging or a future dedicated billing asset.
    """
    return os.environ.get(
        "SCENEWRIGHT_STRIPE_ICON_URL",
        "https://app.scenewright.ink/favicon.svg",
    ).strip()


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


def _checkout_origin(request: Request) -> str:
    """Return the trusted application origin used in Stripe return URLs."""
    env = (os.environ.get("CANARY_ENV") or os.environ.get("ENV") or "dev").lower()
    configured = os.environ.get("SCENEWRIGHT_APP_URL", "").strip()
    if configured:
        parsed = urlparse(configured)
        if (
            parsed.scheme not in {"http", "https"}
            or (env == "production" and parsed.scheme != "https")
            or not parsed.netloc
            or parsed.username
            or parsed.password
            or parsed.path not in {"", "/"}
            or parsed.params
            or parsed.query
            or parsed.fragment
        ):
            raise HTTPException(500, "SCENEWRIGHT_APP_URL must be an absolute origin")
        return f"{parsed.scheme}://{parsed.netloc}"

    if env == "production":
        raise HTTPException(500, "SCENEWRIGHT_APP_URL is required in production")

    # Development is intentionally limited to known local Vite origins. Never
    # reflect an arbitrary Origin header into a third-party redirect URL.
    origin = request.headers.get("origin", "")
    if origin in {"http://localhost:5173", "http://127.0.0.1:5173"}:
        return origin
    return "http://localhost:5173"


@router.get("/packages")
def list_packages():
    """Return available credit packages — used by the frontend to render buy buttons."""
    return {
        "offer_version": _offer_version(),
        "packages": [
            {"id": k, **{kk: vv for kk, vv in v.items()}}
            for k, v in CREDIT_PACKAGES.items()
        ],
    }


@router.post("/checkout")
async def create_checkout(
    request: Request,
    body: dict,
    user_id: str = Depends(get_current_user),
):
    package_id = body.get("package")
    if not isinstance(package_id, str) or package_id not in CREDIT_PACKAGES:
        raise HTTPException(400, "Unknown credit package")

    pkg = CREDIT_PACKAGES[package_id]
    _stripe()
    branding = get_branding()

    origin = _checkout_origin(request)

    try:
        # Require payment-time consent for every credit purchase. Stripe records
        # the acceptance on the Checkout Session and renders the Terms and Privacy
        # links configured in the Stripe Dashboard's public business settings.
        kwargs: dict[str, Any] = dict(
            payment_method_types=["card"],
            line_items=[{
                "price_data": {
                    "currency": "usd",
                    "product_data": {
                        "name": f"{branding.product_name} {package_id.title()} — {pkg['credits']:,} credits",
                        "description": "One-time credit pack. Credits never expire.",
                    },
                    "unit_amount": pkg["price_cents"],
                },
                "quantity": 1,
            }],
            mode="payment",
            consent_collection={"terms_of_service": "required"},
            branding_settings={
                "display_name": branding.product_name,
                "background_color": "#fcfaed",
                "button_color": "#b51822",
                "font_family": "be_vietnam_pro",
                "border_style": "rectangular",
                "icon": {
                    "type": "url",
                    "url": _stripe_icon_url(),
                },
            },
            custom_text={
                "submit": {
                    "message": "Your credits are added after Stripe confirms your payment.",
                },
                "after_submit": {
                    "message": "Return to Scenewright to see your updated credit balance.",
                },
            },
            success_url=f"{origin}/credits?success=true",
            cancel_url=f"{origin}/credits?cancelled=true&package={package_id}",
            metadata={
                "user_id": user_id,
                "package": package_id,
                "offer_version": _offer_version(),
                **offer_snapshot(pkg["credits"], pkg["price_cents"]),
            },
        )
        session = await run_in_threadpool(stripe.checkout.Session.create, **kwargs)
    except stripe.error.StripeError as exc:
        raise _wrap_stripe_error(exc) from exc

    capture_server_event(
        "checkout_started",
        user_id=user_id,
        request_id=getattr(request.state, "request_id", None),
        properties={
            "package_id": package_id,
            "gross_amount_cents": pkg["price_cents"],
            "currency": "usd",
            "stripe_mode": "live" if getattr(session, "livemode", None) is True else "test" if getattr(session, "livemode", None) is False else "unknown",
        },
    )
    return {"url": session.url}


@router.post("/webhook")
async def stripe_webhook(request: Request):
    """Receive Stripe events. Must use raw request body for signature verification."""
    payload = await _read_stripe_webhook_payload(request)
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

    if event["type"] in {"checkout.session.completed", "checkout.session.async_payment_succeeded"}:
        session = _stripe_dict(event["data"]["object"])
        await run_in_threadpool(_handle_checkout_completed, session)

    return {"status": "ok"}


def _stripe_webhook_max_bytes() -> int:
    """Maximum raw Stripe payload size; defaults to a generous 256 KiB."""
    try:
        return max(
            1,
            int(os.environ.get("CANARY_STRIPE_WEBHOOK_MAX_KB", "256")),
        ) * 1024
    except (TypeError, ValueError):
        return 256 * 1024


async def _read_stripe_webhook_payload(request: Request) -> bytes:
    """Read exact signature bytes without allowing an unbounded public body."""
    cap = _stripe_webhook_max_bytes()
    content_length = request.headers.get("content-length")
    if content_length is not None:
        try:
            if int(content_length) > cap:
                raise HTTPException(413, "Stripe webhook payload too large")
        except ValueError:
            pass

    payload = bytearray()
    async for chunk in request.stream():
        payload.extend(chunk)
        if len(payload) > cap:
            raise HTTPException(413, "Stripe webhook payload too large")
    return bytes(payload)


def _handle_checkout_completed(session: dict) -> None:
    if session.get("payment_status") != "paid":
        logger.warning(
            "Ignoring unpaid checkout event — session %s status=%r",
            session.get("id"), session.get("payment_status"),
        )
        return
    try:
        receipt = checkout_receipt(session)
    except InvalidCheckoutReceipt as exc:
        # Do not acknowledge a paid but unfulfillable receipt as successful.
        # Stripe delivery retries and operator logs retain the recovery signal.
        logger.error("Checkout requires reconciliation session=%s reason=%s", session.get("id"), exc)
        raise HTTPException(400, "Checkout payment requires manual reconciliation") from exc
    db = get_db()

    # The unique payment-intent constraint atomically decides which concurrent
    # delivery wins, including completed + async_payment_succeeded duplicates.
    response = db.table("credit_ledger").upsert(
        {
            "user_id": receipt.user_id,
            "amount_credits": receipt.credits,
            "status": "settled",
            "description": f"Credit purchase — {receipt.credits:,} credits",
            "stripe_payment_intent_id": receipt.payment_intent_id,
            "stripe_checkout_session_id": receipt.session_id,
            "credit_package_id": receipt.package_id,
            "gross_amount_cents": receipt.gross_amount_cents,
            "currency": receipt.currency,
            "offer_version": receipt.offer_version,
            "purchase_event_environment": os.environ.get("CANARY_ENV", "development"),
            "purchase_event_release": os.environ.get("CANARY_VERSION", "unknown"),
            "stripe_mode": "live" if session.get("livemode") is True else "test" if session.get("livemode") is False else "unknown",
        },
        on_conflict="stripe_payment_intent_id",
        ignore_duplicates=True,
    ).execute()

    if response.data:
        # The ledger INSERT trigger commits the purchase outbox event atomically.
        # Never emit a second best-effort event here, including webhook retries.
        logger.info("Added %d credits for user %s (payment_intent %s)", receipt.credits, receipt.user_id, receipt.payment_intent_id)
    else:
        logger.info("Duplicate webhook for payment_intent %s — skipping", receipt.payment_intent_id)
