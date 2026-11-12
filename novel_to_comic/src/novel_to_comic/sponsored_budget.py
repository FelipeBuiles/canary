"""Limits on Canary-paid work (``AIRequestContext.sponsor``).

Two operator locks, both independent of any account's credits:

* a daily ceiling on what sponsored calls cost, summed across every account on
  the volume, checked when sponsored work is admitted;
* grant routes only: a sponsored image never moves on to a route billed in
  cash (OpenAI, FAL). It fails instead.

Unset, production enforces both and other environments enforce neither, so
local and staging work is never refused. ``CANARY_IMAGE_CASH_ROUTES_DISABLED``
closes the cash routes to all image work, paid as well as sponsored.
"""
from __future__ import annotations

import fcntl
import json
import logging
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from novel_to_comic import runtime_settings

logger = logging.getLogger("canary.sponsored")

LEDGER_FILE = ".sponsored_spend.json"
DEFAULT_DAILY_CEILING_USD = 10.0


class SponsoredRouteUnavailable(RuntimeError):
    """The work would have needed a route that bills in cash, which is closed to it."""


def _production() -> bool:
    from novel_to_comic.server.runtime_environment import app_environment

    return app_environment() == "production"


def daily_ceiling_usd() -> float | None:
    """``CANARY_SPONSORED_DAILY_USD``; 0 admits nothing, None means no ceiling."""
    raw = runtime_settings.raw("CANARY_SPONSORED_DAILY_USD")
    if not raw:
        return DEFAULT_DAILY_CEILING_USD if _production() else None
    try:
        return max(0.0, float(raw))
    except ValueError:
        return DEFAULT_DAILY_CEILING_USD


def grant_routes_only() -> bool:
    """``CANARY_SPONSORED_GRANT_ROUTES_ONLY``; on in production unless set to 0."""
    raw = runtime_settings.raw("CANARY_SPONSORED_GRANT_ROUTES_ONLY").lower()
    if not raw:
        return _production()
    return raw not in {"0", "false", "no", "off"}


def cash_routes_disabled() -> bool:
    """``CANARY_IMAGE_CASH_ROUTES_DISABLED``: no image, sponsored or paid, uses OpenAI or FAL.

    For a period when every image must run on the grant route (Runware
    first). Off unless set, in every environment.
    """
    return runtime_settings.raw("CANARY_IMAGE_CASH_ROUTES_DISABLED").lower() in {"1", "true", "yes", "on"}


def refuse_cash_route(route: str) -> None:
    """Stop work before it submits to ``route`` when cash routes are closed to it."""
    from novel_to_comic.ai.context import current_ai_request_context

    if cash_routes_disabled():
        logger.error("The %s route is disabled (CANARY_IMAGE_CASH_ROUTES_DISABLED)", route)
        raise SponsoredRouteUnavailable(
            f"The {route} image route is switched off and the grant route was unavailable."
        )
    sponsor = current_ai_request_context().sponsor
    if sponsor is not None and grant_routes_only():
        logger.error("Sponsored work refused the %s route sponsor=%s", route, sponsor)
        raise SponsoredRouteUnavailable(
            f"Canary-paid work does not run on the {route} route; the grant route was unavailable."
        )


def volume_for_workspace(workspace_id: str | Path) -> Path:
    """The projects volume above an AI request's ``workspace_id``.

    A series-level job's workspace is the account directory; a part stage's is
    the series' ``parts`` directory.
    """
    from novel_to_comic.workspace import PARTS_DIRNAME

    path = Path(workspace_id)
    account = path.parent.parent if path.name == PARTS_DIRNAME else path
    return account.parent


def _today() -> str:
    return datetime.now(UTC).date().isoformat()


@contextmanager
def _locked(volume: Path):
    volume.mkdir(parents=True, exist_ok=True)
    with open(volume / (LEDGER_FILE + ".lock"), "w") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def _read(volume: Path) -> dict:
    try:
        data = json.loads((volume / LEDGER_FILE).read_text())
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) and data.get("day") == _today() else {}


def spent_today_usd(volume: Path) -> float:
    try:
        return float(_read(Path(volume)).get("usd", 0.0))
    except (TypeError, ValueError):
        return 0.0


def has_room(volume: Path) -> bool:
    """Whether new sponsored work may start today. A job already running finishes."""
    ceiling = daily_ceiling_usd()
    return ceiling is None or spent_today_usd(volume) < ceiling


def record_spend(volume: Path, usd: float | None) -> None:
    """Add one sponsored call's cost to today's total. Never raises."""
    if not usd or usd <= 0:
        return
    try:
        volume = Path(volume)
        with _locked(volume):
            total = round(spent_today_usd(volume) + usd, 6)
            (volume / LEDGER_FILE).write_text(json.dumps({"day": _today(), "usd": total}))
    except Exception:
        logger.exception("Sponsored spend was not recorded usd=%s", usd)
