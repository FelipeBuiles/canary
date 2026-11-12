"""One free opening per person, not per account.

The Cold Open grant is per account, and accounts are cheap. Before an account
without credits gets its Canary-paid Extract, the applicant must have a
verified, non-disposable email no other account has used (Gmail dots and
``+tags`` ignored), a manuscript opening no other account has had drawn free,
and an address that has not already claimed today's allowance.

Emails, addresses and openings are stored only as SHA-256 digests, in one
file on the projects volume. A refusal is silent to the author: the run is
simply priced like any other.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path

from novel_to_comic import runtime_settings, sponsored_budget

logger = logging.getLogger("canary.free_opening")

CLAIMS_FILE = ".free_opening_claims.json"
OPENING_FINGERPRINT_CHARS = 2000
DEFAULT_PER_IP_DAILY = 2
_GMAIL = frozenset({"gmail.com", "googlemail.com"})
# Common throwaway inboxes. ``CANARY_DISPOSABLE_EMAIL_DOMAINS`` adds more.
DISPOSABLE_DOMAINS = frozenset("""
0-mail.com 10minutemail.com 10minutemail.net 20minutemail.com 33mail.com anonaddy.com
burnermail.io discard.email discardmail.com dispostable.com dropmail.me emailondeck.com
fakeinbox.com fakemail.net getairmail.com getnada.com guerrillamail.biz guerrillamail.com
guerrillamail.de guerrillamail.info guerrillamail.net guerrillamail.org harakirimail.com
inboxbear.com inboxkitten.com mail-temp.com mail.tm mailcatch.com maildrop.cc mailinator.com
mailinator.net mailnesia.com mailsac.com minutemail.com mintemail.com mohmal.com moakt.com
mytemp.email nada.email sharklasers.com spam4.me spamgourmet.com temp-mail.io temp-mail.org
tempail.com tempinbox.com tempmail.com tempmail.dev tempmail.net tempmailo.com tempr.email
throwawaymail.com trashmail.com trashmail.de trashmail.net yopmail.com yopmail.fr yopmail.net
""".split())


@dataclass(frozen=True)
class Applicant:
    """Who is asking, as the verified request saw them."""

    email: str | None
    email_verified: bool
    ip: str | None


def per_ip_daily() -> int:
    """``CANARY_FREE_OPENING_PER_IP_DAILY``: new free openings one address may claim a day."""
    try:
        return max(0, int(runtime_settings.raw("CANARY_FREE_OPENING_PER_IP_DAILY") or DEFAULT_PER_IP_DAILY))
    except ValueError:
        return DEFAULT_PER_IP_DAILY


def normalize_email(email: str | None) -> str | None:
    """The mailbox an address delivers to, or None when it is not an address."""
    local, _, domain = (email or "").strip().lower().rpartition("@")
    domain = domain.strip(".")
    if not local or "." not in domain:
        return None
    local = local.split("+", 1)[0]
    if domain in _GMAIL:
        local, domain = local.replace(".", ""), "gmail.com"
    return f"{local}@{domain}" if local else None


def is_disposable(email: str) -> bool:
    domain = email.rpartition("@")[2]
    extra = {item.strip().lower() for item in runtime_settings.raw("CANARY_DISPOSABLE_EMAIL_DOMAINS").split(",")}
    blocked = DISPOSABLE_DOMAINS | (extra - {""})
    # A subdomain of a throwaway service is the same service.
    parts = domain.split(".")
    return any(".".join(parts[index:]) in blocked for index in range(len(parts) - 1))


def opening_fingerprint(text: str) -> str:
    """Digest of the opening's words, blind to case, spacing and punctuation."""
    words = " ".join(re.findall(r"\w+", text.lower()))
    return _digest(words[:OPENING_FINGERPRINT_CHARS])


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _read(volume: Path) -> dict:
    try:
        data = json.loads((volume / CLAIMS_FILE).read_text())
    except (OSError, ValueError):
        data = {}
    data = data if isinstance(data, dict) else {}
    claims = {key: dict(data.get(key) or {}) for key in ("emails", "openings")}
    ips = data.get("ips") or {}
    claims["ips"] = dict(ips.get("counts") or {}) if ips.get("day") == sponsored_budget._today() else {}
    return claims


def claim(volume: Path, account: str, applicant: Applicant, text: str, *, commit: bool) -> str | None:
    """Why this account may not have a free opening, or None when it may.

    ``commit`` records the claim; without it this only answers the question.
    """
    email = normalize_email(applicant.email) if applicant.email_verified else None
    if email is None:
        return "email_unverified"
    if is_disposable(email):
        return "email_disposable"
    if not text.strip():
        return "no_opening"
    email_key, opening_key = _digest(email), opening_fingerprint(text)
    ip_key = _digest(applicant.ip) if applicant.ip else None
    volume = Path(volume)
    with sponsored_budget._locked(volume):
        claims = _read(volume)
        if claims["emails"].get(email_key, account) != account:
            return "email_already_used"
        if claims["openings"].get(opening_key, account) != account:
            return "opening_already_drawn"
        # An unresolvable address shares one bucket instead of bypassing the limit.
        ip_key = ip_key or "unknown"
        if int(claims["ips"].get(ip_key, 0)) >= per_ip_daily():
            return "address_limit"
        if commit:
            claims["emails"][email_key] = claims["openings"][opening_key] = account
            claims["ips"][ip_key] = int(claims["ips"].get(ip_key, 0)) + 1
            (volume / CLAIMS_FILE).write_text(json.dumps({
                "emails": claims["emails"], "openings": claims["openings"],
                "ips": {"day": sponsored_budget._today(), "counts": claims["ips"]},
            }))
    return None
