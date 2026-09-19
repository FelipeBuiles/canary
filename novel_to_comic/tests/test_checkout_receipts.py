"""Paid receipts, not today's mutable storefront, determine fulfillment."""
from copy import deepcopy

import pytest

from novel_to_comic.server.checkout_receipts import (
    InvalidCheckoutReceipt, checkout_receipt, offer_snapshot,
)


def paid_session():
    return {
        "id": "cs_test_purchase", "payment_intent": "pi_purchase",
        "mode": "payment", "status": "complete", "payment_status": "paid",
        "amount_total": 1200, "currency": "usd",
        "metadata": {
            "user_id": "account", "package": "starter", "offer_version": "public-credit-offer-v1",
            **offer_snapshot(1200, 1200),
        },
    }


def test_snapshot_survives_retired_package_and_new_offer_version():
    session = paid_session()
    session["metadata"].update(package="retired-pack", offer_version="historical-v2")
    receipt = checkout_receipt(session)
    assert (receipt.credits, receipt.gross_amount_cents) == (1200, 1200)
    assert receipt.package_id == "retired-pack"


def test_snapshot_does_not_reprice_from_legacy_catalog():
    session = paid_session()
    session["metadata"].update(offer_snapshot(1750, 1300))
    session["amount_total"] = 1300
    assert checkout_receipt(session).credits == 1750


@pytest.mark.parametrize("field,value", [
    ("amount_total", 0), ("amount_total", 1199), ("amount_total", 1201),
    ("amount_total", True), ("amount_total", "1200"), ("amount_total", None),
    ("currency", "cad"), ("currency", None), ("mode", "subscription"),
    ("status", "open"), ("payment_status", "unpaid"),
    ("payment_intent", None), ("payment_intent", {}), ("id", None),
])
def test_ambiguous_or_wrong_payment_does_not_grant_credits(field, value):
    session = paid_session()
    session[field] = value
    with pytest.raises(InvalidCheckoutReceipt):
        checkout_receipt(session)


@pytest.mark.parametrize("field,value", [
    ("credit_amount", "0"), ("credit_amount", "-1"), ("credit_amount", "1.5"),
    ("credit_amount", "2147483648"), ("credit_amount", 1200),
    ("credit_price_cents", ""), ("credit_currency", "cad"),
    ("credit_offer_schema", "2"), ("user_id", None), ("package", []),
])
def test_malformed_snapshot_never_falls_back_to_current_or_legacy_terms(field, value):
    session = paid_session()
    session["metadata"][field] = value
    with pytest.raises(InvalidCheckoutReceipt):
        checkout_receipt(session)


@pytest.mark.parametrize("field", list(offer_snapshot(1200, 1200)))
def test_partial_snapshot_is_rejected(field):
    session = paid_session()
    session["metadata"].pop(field)
    with pytest.raises(InvalidCheckoutReceipt):
        checkout_receipt(session)


def test_known_in_flight_legacy_offer_has_frozen_terms():
    session = paid_session()
    session["metadata"] = {"user_id": "account", "package": "starter"}
    assert checkout_receipt(session).credits == 1200
    unknown = deepcopy(session)
    unknown["metadata"]["offer_version"] = "unknown-custom-offer"
    with pytest.raises(InvalidCheckoutReceipt):
        checkout_receipt(unknown)
    session["amount_total"] = 100
    with pytest.raises(InvalidCheckoutReceipt):
        checkout_receipt(session)
