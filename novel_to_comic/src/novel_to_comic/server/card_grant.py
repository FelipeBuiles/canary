"""The card-verified first-chapter grant.

An author who has seen their free opening verifies a card in Stripe Checkout
(setup mode: nothing is charged, and the card is not attached to a customer)
and receives credits for a first chapter. One grant per card fingerprint and
per account, a seat cap, an end date, and an expiry on the unspent credits.
The database functions in ``docs/migrations/2026-11-12-card-chapter-grant.sql``
make the claim and the expiry atomic.

Off unless ``CANARY_CARD_GRANT_CREDITS`` is a positive number.
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path

from novel_to_comic import runtime_settings

logger = logging.getLogger("canary.card_grant")

PURPOSE = "card_chapter_grant"
DEFAULT_SEATS = 100
DEFAULT_EXPIRY_DAYS = 30


def _int(name: str, default: int) -> int:
    try:
        return max(0, int(runtime_settings.raw(name) or default))
    except ValueError:
        return default


def grant_credits() -> int:
    """``CANARY_CARD_GRANT_CREDITS``; 0 or unset turns the grant off."""
    return _int("CANARY_CARD_GRANT_CREDITS", 0)


def seats() -> int:
    return _int("CANARY_CARD_GRANT_SEATS", DEFAULT_SEATS)


def expiry_days() -> int:
    return max(1, _int("CANARY_CARD_GRANT_EXPIRY_DAYS", DEFAULT_EXPIRY_DAYS))


def ends_at() -> datetime | None:
    """``CANARY_CARD_GRANT_ENDS`` (ISO date or datetime, UTC): no claim from then on."""
    raw = runtime_settings.raw("CANARY_CARD_GRANT_ENDS")
    if not raw:
        return None
    try:
        value = datetime.fromisoformat(raw)
    except ValueError:
        # A date the operator mistyped must not leave the offer open forever.
        return datetime.min.replace(tzinfo=UTC)
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def open_now() -> bool:
    end = ends_at()
    return grant_credits() > 0 and seats() > 0 and (end is None or datetime.now(UTC) < end)


def saw_free_opening(account_dir: Path) -> bool:
    """Whether any of the account's projects has a printed Cold Open page."""
    from novel_to_comic import cold_open

    try:
        children = [child for child in Path(account_dir).iterdir() if child.is_dir()]
    except OSError:
        return False
    for child in children:
        try:
            record = cold_open.read_record(child)
        except Exception:
            continue
        if record is not None and record.status == "ready":
            return True
    return False


def claimed(db, user_id: str) -> dict | None:
    rows = (db.table("card_chapter_grants").select("amount_credits,expires_at,expired_at")
            .eq("user_id", user_id).limit(1).execute().data)
    return rows[0] if rows else None


def seats_left(db) -> int:
    result = db.table("card_chapter_grants").select("id", count="exact").limit(1).execute()
    return max(0, seats() - int(result.count or 0))


def status(db, user_id: str, account_dir: Path) -> dict:
    """What the credits page shows. ``available`` means the author may start a claim."""
    if grant_credits() <= 0:
        return {"enabled": False, "available": False, "claimed": False}
    grant = claimed(db, user_id)
    reason = None
    if grant is not None:
        reason = "claimed"
    elif not open_now():
        reason = "ended"
    elif seats_left(db) <= 0:
        reason = "seats_taken"
    elif not saw_free_opening(account_dir):
        reason = "opening_first"
    return {
        "enabled": True, "available": reason is None, "claimed": grant is not None, "reason": reason,
        "credits": grant["amount_credits"] if grant else grant_credits(),
        "expiry_days": expiry_days(),
        "expires_at": grant["expires_at"] if grant else None,
        "expired": bool(grant and grant.get("expired_at")),
    }


def claim(db, *, user_id: str, fingerprint: str, setup_intent_id: str) -> str:
    """Grant once for this card and account; returns the database's verdict."""
    result = db.rpc("claim_card_chapter_grant", {
        "p_user_id": user_id, "p_card_fingerprint": fingerprint, "p_setup_intent_id": setup_intent_id,
        "p_amount_credits": grant_credits(),
        "p_expires_at": (datetime.now(UTC) + timedelta(days=expiry_days())).isoformat(),
        "p_seats": seats(),
    }).execute()
    return str(result.data)


def first_purchase_bonus_percent() -> int:
    """``CANARY_FIRST_PURCHASE_BONUS_PERCENT``; 0 or unset gives no bonus."""
    return min(100, _int("CANARY_FIRST_PURCHASE_BONUS_PERCENT", 0))


def grant_first_purchase_bonus(db, *, user_id: str, purchased_credits: int) -> int:
    """Add bonus credits to a grant holder's first purchase; returns what was added.

    Only while the first-chapter grant is unexpired, and once per account: the
    ledger's unique marker makes webhook retries and later purchases no-ops.
    Bonus credits are ordinary credits and do not expire. Never raises: the
    purchase it follows is already settled.
    """
    percent = first_purchase_bonus_percent()
    bonus = purchased_credits * percent // 100
    if bonus <= 0:
        return 0
    try:
        grant = claimed(db, user_id)
        if grant is None or grant.get("expired_at"):
            return 0
        if datetime.fromisoformat(str(grant["expires_at"])) <= datetime.now(UTC):
            return 0
        inserted = db.table("credit_ledger").upsert(
            {
                "user_id": user_id, "amount_credits": bonus, "status": "settled",
                "description": f"First purchase bonus — {bonus:,} credits",
                "operation": "first_purchase_bonus",
                "usage_call_id": f"first-purchase-bonus:{user_id}",
            },
            on_conflict="usage_call_id", ignore_duplicates=True,
        ).execute().data
        return bonus if inserted else 0
    except Exception:
        logger.exception("First purchase bonus was not granted user=%s", user_id)
        return 0


def expire_due(db, user_id: str | None = None) -> None:
    """Take back the unspent part of expired grants. Best effort; never raises."""
    if grant_credits() <= 0 and runtime_settings.raw("CANARY_CARD_GRANT_EXPIRE").lower() not in {"1", "true", "yes", "on"}:
        return
    try:
        db.rpc("expire_card_chapter_grants", {"p_user_id": user_id}).execute()
    except Exception:
        logger.warning("Card grant expiry did not run user=%s", user_id, exc_info=True)
