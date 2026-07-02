"""Rate limiting for the API surface (abuse / brute-force protection).

The credits system gates *cost*; rate limiting gates *abuse* — rapid project
creation, endpoint hammering, runaway clients. Keys on client IP, which reflects
the real caller when Uvicorn runs with ``--proxy-headers`` behind a
TLS-terminating proxy (Fly.io / nginx). Without ``--proxy-headers`` the key is
the direct peer (localhost in dev), so local development is unaffected.

Limits are env-configurable so they can be tuned without a code change:

- ``CANARY_RATE_LIMIT_CREATE`` (default ``10/minute``) — project creation / upload.
- ``CANARY_RATE_LIMIT_COST``   (default ``60/minute``) — credit-charged actions
  (run / regen). These are also credit-gated; the limiter is a backstop.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from fastapi import FastAPI
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi.util import get_remote_address

if TYPE_CHECKING:
    # Type-only imports — annotations are deferred via ``from __future__``.
    from fastapi import Request
    from starlette.responses import Response


def _client_key(request) -> str:
    # Fall back to a shared sentinel so requests with no resolvable client still
    # land in a rate-limited bucket rather than bypassing the limiter entirely.
    return get_remote_address(request) or "anonymous"


# A single shared limiter instance imported by every router. ``default_limits``
# is intentionally empty — limits are applied per-route via @limiter.limit(...).
limiter = Limiter(key_func=_client_key, default_limits=[])


def _rate_limit_handler(request: Request, exc: Exception) -> Response:
    # FastAPI/Starelle type the exception handler against the broad ``Exception``
    # base, but slowapi's ``_rate_limit_exceeded_handler`` expects the narrower
    # ``RateLimitExceeded``. Narrow back here before delegating.
    if not isinstance(exc, RateLimitExceeded):  # pragma: no cover - defensive
        raise exc
    return _rate_limit_exceeded_handler(request, exc)


def configure_rate_limiting(app: FastAPI) -> None:
    """Attach the shared limiter, the 429 handler, and the response-header
    middleware to a FastAPI app. The middleware is what stamps the
    ``X-RateLimit-*`` headers on responses; the limit itself is enforced by the
    route decorator raising ``RateLimitExceeded`` (caught by the handler)."""
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_handler)
    app.add_middleware(SlowAPIMiddleware)


def create_limit() -> str:
    """Per-IP limit for project creation (the upload / disk vector)."""
    return os.environ.get("CANARY_RATE_LIMIT_CREATE", "10/minute")


def cost_limit() -> str:
    """Per-IP limit for credit-charged actions (run / regen)."""
    return os.environ.get("CANARY_RATE_LIMIT_COST", "60/minute")
