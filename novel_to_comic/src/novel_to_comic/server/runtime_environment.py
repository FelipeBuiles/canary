"""Runtime and Stripe-mode metadata for operator-facing surfaces."""

from __future__ import annotations

import os
from typing import Any, Literal

StripeMode = Literal["sandbox", "live", "unconfigured", "unknown"]


def app_environment() -> str:
    """Return a safe, human-readable deployment label."""
    raw = (os.environ.get("CANARY_ENV") or os.environ.get("ENV") or "local").strip().lower()
    if raw in {"prod", "production", "live"}:
        return "production"
    if raw in {"stage", "staging", "preview"}:
        return "staging"
    return raw or "local"


def stripe_mode() -> StripeMode:
    """Infer Stripe's account mode from the server-only secret key prefix.

    The key is never returned. An unknown prefix is deliberately reported as
    unknown instead of guessing from the deployment name.
    """
    key = os.environ.get("STRIPE_SECRET_KEY", "").strip()
    if not key:
        return "unconfigured"
    if key.startswith(("sk_test_", "rk_test_")):
        return "sandbox"
    if key.startswith(("sk_live_", "rk_live_")):
        return "live"
    return "unknown"


def stripe_environment_snapshot() -> dict[str, Any]:
    """Describe the active application/Stripe pairing without leaking secrets."""
    environment = app_environment()
    mode = stripe_mode()
    expected_mode = "live" if environment == "production" else "sandbox"
    configured = mode not in {"unconfigured", "unknown"}
    matches = mode == expected_mode if configured else None

    if mode == "unconfigured":
        warning = "Stripe secret key is not configured on this server."
    elif mode == "unknown":
        warning = "Stripe key mode could not be identified from its prefix."
    elif matches is False:
        warning = (
            f"This is a {environment} server but Stripe is in {mode} mode. "
            "Check the secret key before handling payments."
        )
    elif mode == "live":
        warning = "Live Stripe mode is active. Payment and refund actions affect real money."
    else:
        warning = "Stripe sandbox mode is active. Payment actions stay in test data."

    return {
        "app_environment": environment,
        "stripe_mode": mode,
        "stripe_key_configured": bool(os.environ.get("STRIPE_SECRET_KEY", "").strip()),
        "webhook_configured": bool(os.environ.get("STRIPE_WEBHOOK_SECRET", "").strip()),
        "expected_stripe_mode": expected_mode,
        "mode_matches_app": matches,
        "live_money_warning": warning,
        "safe_for_real_customers": environment == "production" and mode == "live",
    }

