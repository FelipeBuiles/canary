"""Error handling for the Stripe billing router.

The checkout endpoint used to let any stripe.error propagate as a bare 500
with no detail — the user just saw 'Internal Server Error' and ops saw
nothing. These tests pin the contract that Stripe errors map to informative
HTTP responses. Stripe itself is mocked so no key or network is needed.
"""
import asyncio
from types import SimpleNamespace
from unittest.mock import patch

import pytest
import stripe
from fastapi import HTTPException

from novel_to_comic.server.routers import billing


def test_authentication_error_maps_to_500_with_clear_message():
    """A bad/expired/missing STRIPE_SECRET_KEY surfaces as a clear 500."""
    exc = stripe.error.AuthenticationError("Expired API Key", http_status=401)
    wrapped = billing._wrap_stripe_error(exc)
    assert wrapped.status_code == 500
    assert "STRIPE_SECRET_KEY" in wrapped.detail


def test_rate_limit_maps_to_429():
    exc = stripe.error.RateLimitError("too fast", http_status=429)
    wrapped = billing._wrap_stripe_error(exc)
    assert wrapped.status_code == 429


def test_invalid_request_maps_to_502_with_user_message():
    exc = stripe.error.InvalidRequestError("bad param", param="currency")
    wrapped = billing._wrap_stripe_error(exc)
    assert wrapped.status_code == 502
    assert "bad param" in wrapped.detail


def test_generic_stripe_error_maps_to_502():
    exc = stripe.error.APIConnectionError("network down")
    wrapped = billing._wrap_stripe_error(exc)
    assert wrapped.status_code == 502
    assert "network down" in wrapped.detail


@pytest.mark.parametrize("package_id", list(billing.CREDIT_PACKAGES))
def test_checkout_wraps_stripe_errors(package_id):
    """Whatever Stripe raises must come back as a structured HTTPException,
    not an uncaught exception. Covers all four packages so a missing-key deploy
    is reported correctly regardless of which button the user clicked."""
    with patch.object(billing.stripe, "api_key", "sk_test_fake"), patch.object(
        billing.stripe.checkout.Session,
        "create",
        side_effect=stripe.error.AuthenticationError("Expired API Key", http_status=401),
    ):
        with pytest.raises(HTTPException) as ei:
            asyncio.run(
                billing.create_checkout(
                    request=_Request(),
                    body={"package": package_id},
                    user_id="u1",
                )
            )
    assert ei.value.status_code == 500
    assert "STRIPE_SECRET_KEY" in ei.value.detail


def test_checkout_rejects_unknown_package_before_calling_stripe():
    """An unknown package should 400 without ever touching the Stripe API."""
    with patch.object(
        billing.stripe.checkout.Session, "create", side_effect=AssertionError("must not call")
    ) as mock_create:
        with pytest.raises(HTTPException) as ei:
            asyncio.run(
                billing.create_checkout(
                    request=_Request(), body={"package": "bogus"}, user_id="u1"
                )
            )
    assert ei.value.status_code == 400
    mock_create.assert_not_called()


def test_checkout_always_requires_terms_consent(monkeypatch):
    """Legal consent must not disappear when an optional env var is unset."""
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_fake")
    monkeypatch.delenv("SCENEWRIGHT_TERMS_URL", raising=False)

    with patch.object(
        billing.stripe.checkout.Session,
        "create",
        return_value=SimpleNamespace(url="https://checkout.stripe.test/session"),
    ) as mock_create, patch.object(billing, "capture_server_event"):
        result = asyncio.run(
            billing.create_checkout(
                request=_Request(), body={"package": "starter"}, user_id="u1"
            )
        )

    assert result == {"url": "https://checkout.stripe.test/session"}
    kwargs = mock_create.call_args.kwargs
    assert kwargs["consent_collection"] == {"terms_of_service": "required"}
    assert "terms_of_service_url" not in kwargs


class _Request:
    """Minimal stand-in for starlette.Request — only headers are read."""

    def __init__(self, origin: str = "https://canary-web.fly.dev"):
        self.headers = {"origin": origin}
        self.state = SimpleNamespace(request_id="req-test")
