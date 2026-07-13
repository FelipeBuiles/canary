"""Sentry error-tracking bootstrap.

Activated by setting ``SENTRY_DSN``. No DSN → complete no-op (and never raises),
so dev/test runs are unaffected. The ``before_send`` hook scrubs auth headers and
the session cookie so bearer tokens never leave the process.

Performance tracing is left off by default (``SENTRY_TRACES_SAMPLE_RATE=0``) —
traces are handled by Langfuse/OTel (see telemetry.py) to avoid double-sending.
Error capture is the only thing Sentry owns.
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger("canary.sentry")

_CONFIGURED = False

# Headers/cookies that must never appear in a Sentry event payload.
_SENSITIVE_HEADERS = {
    "authorization",
    "cookie",
    "pulp_session",
    "x-api-key",
    "x-supabase-key",
    "set-cookie",
}


def _scrub_event(event: dict, _hint: dict) -> dict:
    """Strip auth headers/cookies from the captured request before it ships."""
    try:
        request = event.get("request")
        if isinstance(request, dict):
            headers = request.get("headers")
            if isinstance(headers, dict):
                for key in list(headers):
                    if key.lower() in _SENSITIVE_HEADERS:
                        headers[key] = "[Filtered]"
            # The session cookie value may also be captured directly.
            cookies = request.get("cookies")
            if isinstance(cookies, dict):
                for key in list(cookies):
                    if key == "pulp_session":
                        cookies[key] = "[Filtered]"
    except Exception:  # noqa: BLE001 - scrubbing must never drop the event
        pass
    return event


def configure_sentry() -> bool:
    """Initialise Sentry from SENTRY_DSN. Returns False when not configured."""
    global _CONFIGURED
    if _CONFIGURED:
        return True

    dsn = os.environ.get("SENTRY_DSN", "").strip()
    if not dsn:
        return False

    try:
        import sentry_sdk
    except Exception as exc:  # noqa: BLE001 - optional dependency
        logger.warning("SENTRY_DSN set but sentry-sdk unavailable: %s", exc)
        return False

    try:
        sample_rate = float(os.environ.get("SENTRY_TRACES_SAMPLE_RATE", "0.0"))
    except ValueError:
        logger.warning("Invalid SENTRY_TRACES_SAMPLE_RATE; defaulting to 0.0")
        sample_rate = 0.0

    try:
        sentry_sdk.init(
            dsn=dsn,
            environment=os.environ.get("CANARY_ENV", "dev"),
            release=os.environ.get("CANARY_VERSION", "0.1.0"),
            traces_sample_rate=sample_rate,
            # Never send PII — user_id (UUID) is enough context; emails/IP stay local.
            send_default_pii=False,
            before_send=_scrub_event,
        )
    except Exception as exc:  # noqa: BLE001 - observability must not prevent boot
        logger.error("Sentry initialization failed; continuing without it: %s", exc)
        return False
    _CONFIGURED = True
    logger.info(
        "[bold blue]Sentry enabled[/] env=%s release=%s",
        os.environ.get("CANARY_ENV", "dev"),
        os.environ.get("CANARY_VERSION", "0.1.0"),
    )
    return True
