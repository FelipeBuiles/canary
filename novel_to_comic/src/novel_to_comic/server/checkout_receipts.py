"""Immutable credit-offer receipts carried by server-created Stripe sessions.

These values are authoritative only AFTER Stripe signature verification. Never
accept them from a browser checkout request. Historical fulfillment must not
consult the currently advertised package table.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

_SNAPSHOT_KEYS = frozenset({
    "credit_offer_schema", "credit_amount", "credit_price_cents", "credit_currency",
})
# Frozen terms for sessions created before offer snapshots existed. Unknown
# historical offers require reconciliation rather than guessing current terms.
_LEGACY_OFFERS = {
    "starter": (1200, 1200),
    "standard": (3000, 3000),
    "creator": (7500, 7000),
    "studio": (18000, 15000),
}


class InvalidCheckoutReceipt(ValueError):
    """A paid session lacks unambiguous, supported fulfillment evidence."""


@dataclass(frozen=True)
class CheckoutReceipt:
    user_id: str
    package_id: str
    credits: int
    gross_amount_cents: int
    currency: str
    offer_version: str
    session_id: str
    payment_intent_id: str


def _positive_integer(value: Any) -> int:
    if not isinstance(value, str) or not re.fullmatch(r"[1-9][0-9]{0,9}", value):
        raise InvalidCheckoutReceipt("Invalid offer amount")
    number = int(value)
    if number > 2_147_483_647:
        raise InvalidCheckoutReceipt("Offer amount exceeds ledger capacity")
    return number


def offer_snapshot(credits: int, price_cents: int) -> dict[str, str]:
    """Freeze trusted catalog terms when the server creates a Checkout Session."""
    if type(credits) is not int or type(price_cents) is not int:
        raise ValueError("Credit offers require integer amounts")
    _positive_integer(str(credits))
    _positive_integer(str(price_cents))
    return {
        "credit_offer_schema": "1",
        "credit_amount": str(credits),
        "credit_price_cents": str(price_cents),
        "credit_currency": "usd",
    }


def checkout_receipt(session: dict[str, Any]) -> CheckoutReceipt:
    """Validate signed payment evidence; never fabricate an amount or currency."""
    if (session.get("mode") != "payment"
            or session.get("status") != "complete"
            or session.get("payment_status") != "paid"):
        raise InvalidCheckoutReceipt("Checkout payment is not complete")
    metadata = session.get("metadata")
    if not isinstance(metadata, dict):
        raise InvalidCheckoutReceipt("Missing offer metadata")
    user_id = metadata.get("user_id")
    package_id = metadata.get("package")
    if not isinstance(user_id, str) or not user_id.strip() or len(user_id) > 128:
        raise InvalidCheckoutReceipt("Missing account identity")
    if not isinstance(package_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", package_id):
        raise InvalidCheckoutReceipt("Invalid package identity")
    version = metadata.get("offer_version", "legacy")
    if not isinstance(version, str) or not version.strip() or len(version) > 120:
        raise InvalidCheckoutReceipt("Invalid offer version")

    if _SNAPSHOT_KEYS.intersection(metadata):
        if metadata.get("credit_offer_schema") != "1" or not _SNAPSHOT_KEYS.issubset(metadata):
            raise InvalidCheckoutReceipt("Unsupported or incomplete offer snapshot")
        credits = _positive_integer(metadata["credit_amount"])
        price_cents = _positive_integer(metadata["credit_price_cents"])
        currency = metadata["credit_currency"]
        if currency != "usd":
            raise InvalidCheckoutReceipt("Unsupported offer currency")
    else:
        if version not in {"legacy", "public-credit-offer-v1"} or package_id not in _LEGACY_OFFERS:
            raise InvalidCheckoutReceipt("Unknown historical offer requires reconciliation")
        credits, price_cents = _LEGACY_OFFERS[package_id]
        currency = "usd"

    amount = session.get("amount_total")
    if type(amount) is not int or amount != price_cents or session.get("currency") != currency:
        raise InvalidCheckoutReceipt("Paid amount or currency does not match the offer")
    session_id, payment_intent_id = session.get("id"), session.get("payment_intent")
    for value, prefix in ((session_id, "cs_"), (payment_intent_id, "pi_")):
        if not isinstance(value, str) or not value.startswith(prefix) or len(value) <= len(prefix):
            raise InvalidCheckoutReceipt("Missing payment identity")
    return CheckoutReceipt(
        user_id=user_id, package_id=package_id, credits=credits,
        gross_amount_cents=amount, currency=currency, offer_version=version,
        session_id=session_id, payment_intent_id=payment_intent_id,
    )
