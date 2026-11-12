"""Operator settings that can change while the server runs.

One registry declares every such setting: its type, bounds and meaning. A
value comes from the ``app_settings`` table in Supabase when the operator has
stored one, else from the environment variable of the same name, else the
setting is unset and its reader applies its own default.

The table is read at most once a minute per process. When it cannot be read,
the last values read stay in force. If it has never been read in this process,
settings that give something away take their ``safe`` value (off) until it
can be. A server without Supabase, or without the table, uses the environment
alone. Secrets never belong here: they stay in the host's secret bundle.
"""

from __future__ import annotations

import logging
import os
import re
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

logger = logging.getLogger("canary.runtime_settings")

TABLE = "app_settings"
REFRESH_SECONDS = 60.0
RETRY_SECONDS = 60.0
MAX_TEXT_LENGTH = 2000

_TRUE = {"1", "true", "yes", "on"}
_FALSE = {"0", "false", "no", "off"}


@dataclass(frozen=True)
class Setting:
    key: str
    kind: str  # int | float | bool | date | text
    description: str
    minimum: float | None = None
    maximum: float | None = None
    #: Shown to the operator as what applies when nothing is stored or set.
    unset_means: str = "off"
    #: Raw value used while the table has never been readable in this process.
    safe: str | None = None
    #: False keeps the setting on the environment alone; the table is ignored.
    editable: bool = True
    #: Safe to return to browsers that are not signed in.
    public: bool = False
    pattern: str | None = None


_SETTINGS = (
    Setting("CANARY_COLD_OPEN_PER_ACCOUNT", "int", "Cold Opens each account may start; 0 turns the Cold Open off.",
            0, 20, unset_means="1 in production, unlimited elsewhere"),
    Setting("CANARY_SPONSORED_DAILY_USD", "float", "Provider US$ of Canary-paid work allowed per UTC day; 0 admits none.",
            0, 200, unset_means="10 in production, no ceiling elsewhere"),
    Setting("CANARY_SPONSORED_GRANT_ROUTES_ONLY", "bool", "Canary-paid work never uses the OpenAI or FAL routes.",
            unset_means="on in production, off elsewhere", editable=False),
    Setting("CANARY_RUNWARE_FIRST_ENABLED", "bool",
            "New image work starts on Runware. Changes which provider is paid; needs RUNWARE_API_KEY."),
    Setting("CANARY_RUNWARE_TEXT_FALLBACK_ENABLED", "bool",
            "A Vertex text call refused with 429 moves to Runware. Changes which provider is paid; needs RUNWARE_API_KEY."),
    Setting("CANARY_IMAGE_CASH_ROUTES_DISABLED", "bool",
            "No image, paid or free, falls back to OpenAI or FAL; it fails instead."),
    Setting("CANARY_FREE_OPENING_MAX_CHARS", "int",
            "Longest first upload, in characters, whose Extract and Brief Canary pays for; 0 is off.",
            0, 200_000, safe="0"),
    Setting("CANARY_FREE_OPENING_PER_IP_DAILY", "int", "New free openings one visitor address may claim per UTC day.",
            0, 100, unset_means="2"),
    Setting("CANARY_DISPOSABLE_EMAIL_DOMAINS", "text",
            "Extra throwaway email domains, comma-separated, refused for the free opening.", unset_means="built-in list only",
            pattern=r"[a-z0-9.,\- ]*"),
    Setting("CANARY_CARD_GRANT_CREDITS", "int", "Credits granted for a verified card; 0 turns the grant off.",
            0, 10_000, safe="0"),
    Setting("CANARY_CARD_GRANT_SEATS", "int", "Card grants available in total.", 0, 10_000, unset_means="100"),
    Setting("CANARY_CARD_GRANT_ENDS", "date", "No card grant is claimed from this UTC date on.", unset_means="no end date"),
    Setting("CANARY_CARD_GRANT_EXPIRY_DAYS", "int", "Days until unspent grant credits expire.", 1, 365, unset_means="30"),
    Setting("CANARY_CARD_GRANT_EXPIRE", "bool", "Keep expiring issued grants after the grant is turned off."),
    Setting("CANARY_FIRST_PURCHASE_BONUS_PERCENT", "int", "Bonus credits, as a percentage, on a grant holder's first purchase.",
            0, 200, safe="0"),
    Setting("CANARY_RATE_LIMIT_CARD_GRANT", "text", "Per-address limit on opening the card form.",
            unset_means="3/hour", editable=False),
    Setting("CANARY_TURNSTILE_SITE_KEY", "text",
            "Public Cloudflare Turnstile site key; set it only together with Supabase's CAPTCHA protection.",
            unset_means="no bot check", public=True, pattern=r"[0-9A-Za-z_\-]{0,100}"),
)
REGISTRY: dict[str, Setting] = {setting.key: setting for setting in _SETTINGS}


class InvalidSetting(ValueError):
    """The value is not one this setting accepts."""


class SettingsStoreUnavailable(RuntimeError):
    """No table to store an override in."""


def validate(key: str, value: str) -> str:
    """The stored form of ``value`` for ``key``; raises ``InvalidSetting`` with the reason."""
    setting = REGISTRY.get(key)
    if setting is None:
        raise InvalidSetting("Unknown setting.")
    if not setting.editable:
        raise InvalidSetting("This setting is changed in the host environment, not here.")
    text = str(value).strip()
    if not text:
        raise InvalidSetting("Enter a value, or remove the override instead.")
    if len(text) > MAX_TEXT_LENGTH:
        raise InvalidSetting("The value is too long.")
    if setting.kind == "bool":
        lowered = text.lower()
        if lowered not in _TRUE | _FALSE:
            raise InvalidSetting("Use true or false.")
        return "true" if lowered in _TRUE else "false"
    if setting.kind in {"int", "float"}:
        try:
            number = int(text) if setting.kind == "int" else float(text)
        except ValueError:
            raise InvalidSetting("Use a whole number." if setting.kind == "int" else "Use a number.") from None
        if number != number or number in (float("inf"), float("-inf")):
            raise InvalidSetting("Use a number.")
        if setting.minimum is not None and number < setting.minimum:
            raise InvalidSetting(f"The lowest allowed value is {setting.minimum:g}.")
        if setting.maximum is not None and number > setting.maximum:
            raise InvalidSetting(f"The highest allowed value is {setting.maximum:g}.")
        return str(number)
    if setting.kind == "date":
        try:
            datetime.fromisoformat(text)
        except ValueError:
            raise InvalidSetting("Use a date such as 2026-12-22.") from None
        return text
    if setting.pattern and not re.fullmatch(setting.pattern, text):
        raise InvalidSetting("The value contains characters this setting does not accept.")
    return text


# --- stored overrides ----------------------------------------------------

_lock = threading.Lock()
_overrides: dict[str, str] | None = None  # None until the table has been read once
_state = "unread"  # unread | loaded | absent | unavailable
_next_read = 0.0
_loader: Callable[[], dict[str, str] | None] | None = None


def _database():
    if not (os.environ.get("SUPABASE_URL", "").strip() and os.environ.get("SUPABASE_SECRET_KEY", "").strip()):
        return None
    from novel_to_comic.server.db import get_db

    return get_db()


def _table_missing(error: Exception) -> bool:
    code = str(getattr(error, "code", "") or "")
    return code in {"PGRST205", "42P01"} or "PGRST205" in str(error) or "42P01" in str(error)


def _load_from_database() -> dict[str, str] | None:
    """Stored overrides, or None where there is no table to read."""
    db = _database()
    if db is None:
        return None
    try:
        rows = db.table(TABLE).select("key,value").execute().data or []
    except Exception as error:
        if _table_missing(error):
            return None
        raise
    return {str(row["key"]): str(row["value"]) for row in rows if row.get("key") in REGISTRY}


def use_loader(loader: Callable[[], dict[str, str] | None] | None) -> None:
    """Replace how overrides are read (tests), and forget what was read."""
    global _loader
    _loader = loader
    reset()


def reset() -> None:
    """Forget what was read; the next lookup reads the table again."""
    global _overrides, _state, _next_read
    with _lock:
        _overrides, _state, _next_read = None, "unread", 0.0


def _current() -> tuple[dict[str, str], str]:
    global _overrides, _state, _next_read
    now = time.monotonic()
    with _lock:
        if now < _next_read:
            return _overrides or {}, _state
        try:
            loaded = (_loader or _load_from_database)()
        except Exception:
            # Keep the last values; without any, the give-away settings go safe.
            if _overrides is None:
                _state = "unavailable"
            _next_read = now + RETRY_SECONDS
            logger.warning("Runtime settings could not be read; using %s.",
                           "the last values read" if _overrides is not None else "safe values", exc_info=True)
            return _overrides or {}, _state
        if loaded is None:
            _overrides, _state = None, "absent"
        else:
            _overrides, _state = loaded, "loaded"
        _next_read = now + REFRESH_SECONDS
        return _overrides or {}, _state


def _resolve(setting: Setting) -> tuple[str, str]:
    environment = os.environ.get(setting.key, "").strip()
    if setting.editable:
        overrides, state = _current()
        stored = overrides.get(setting.key, "").strip()
        if stored:
            try:
                return validate(setting.key, stored), "database"
            except InvalidSetting:
                logger.error("Stored value for %s is invalid and was ignored.", setting.key)
        if state == "unavailable" and setting.safe is not None:
            return setting.safe, "safe"
    return (environment, "environment") if environment else ("", "unset")


def raw(key: str) -> str:
    """The value in force for ``key`` as text; empty when nothing is stored or set."""
    return _resolve(REGISTRY[key])[0]


def effective() -> list[dict]:
    """Every setting with the value in force and where it came from, for the operator."""
    _, state = _current()
    return [
        {
            "key": setting.key, "kind": setting.kind, "description": setting.description,
            "minimum": setting.minimum, "maximum": setting.maximum, "unset_means": setting.unset_means,
            "editable": setting.editable and state in {"loaded", "unavailable"},
            "value": value, "source": source,
            "environment_value": os.environ.get(setting.key, "").strip(),
        }
        for setting in _SETTINGS
        for value, source in [_resolve(setting)]
    ]


def store_state() -> str:
    """``loaded``, ``absent`` (no table or no Supabase) or ``unavailable`` (read failed)."""
    return _current()[1]


def public_values() -> dict[str, str]:
    return {setting.key: raw(setting.key) for setting in _SETTINGS if setting.public}


def set_override(key: str, value: str, *, updated_by: str = "ops_token") -> str:
    """Store ``value`` for ``key``; it applies here now and elsewhere within a minute."""
    stored = validate(key, value)
    db = _database()
    if db is None or store_state() == "absent":
        raise SettingsStoreUnavailable("The settings table is not installed on this server.")
    db.table(TABLE).upsert({"key": key, "value": stored, "updated_by": updated_by}, on_conflict="key").execute()
    logger.warning("Runtime setting %s set to %r by %s.", key, stored, updated_by)
    reset()
    return stored


def clear_override(key: str) -> None:
    """Remove the stored value so the environment or the default applies again."""
    if key not in REGISTRY:
        raise InvalidSetting("Unknown setting.")
    db = _database()
    if db is None or store_state() == "absent":
        raise SettingsStoreUnavailable("The settings table is not installed on this server.")
    db.table(TABLE).delete().eq("key", key).execute()
    logger.warning("Runtime setting %s override removed.", key)
    reset()
