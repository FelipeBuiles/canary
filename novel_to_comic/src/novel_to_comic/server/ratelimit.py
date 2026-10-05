"""Rate limiting for the API surface (abuse / brute-force protection).

The credits system gates *cost*; rate limiting gates *abuse* — rapid project
creation, endpoint hammering, runaway clients. Keys on client IP.

``X-Forwarded-For``'s leftmost entry is client-supplied, so it is never the key.
On Fly (``FLY_APP_NAME`` set), Fly's proxy sets ``Fly-Client-IP`` to the
connecting address. When that address is a trusted edge (Cloudflare by default,
``CANARY_TRUSTED_EDGE_CIDRS`` overrides), the edge's ``CF-Connecting-IP`` names
the visitor. Elsewhere the key is the direct peer (localhost in dev).

Limits are env-configurable so they can be tuned without a code change:

- ``CANARY_RATE_LIMIT_CREATE`` (default ``10/minute``) — project creation / upload.
- ``CANARY_RATE_LIMIT_COST``   (default ``60/minute``) — credit-charged actions
  (run / regen). These are also credit-gated; the limiter is a backstop.
- ``CANARY_RATE_LIMIT_EXPORT`` (default ``3/minute``) — PDF/CBZ export, which
  re-renders the whole book on each call and is not credit-charged.
"""

from __future__ import annotations

import ipaddress
import os
from functools import lru_cache
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


# https://www.cloudflare.com/ips/ (checked 2026-09-25).
CLOUDFLARE_CIDRS = (
    "173.245.48.0/20", "103.21.244.0/22", "103.22.200.0/22", "103.31.4.0/22",
    "141.101.64.0/18", "108.162.192.0/18", "190.93.240.0/20", "188.114.96.0/20",
    "197.234.240.0/22", "198.41.128.0/17", "162.158.0.0/15", "104.16.0.0/13",
    "104.24.0.0/14", "172.64.0.0/13", "131.0.72.0/22",
    "2400:cb00::/32", "2606:4700::/32", "2803:f800::/32", "2405:b500::/32",
    "2405:8100::/32", "2a06:98c0::/29", "2c0f:f248::/32",
)


@lru_cache(maxsize=4)
def _edge_networks(configured: str | None) -> tuple:
    cidrs = [c.strip() for c in configured.split(",") if c.strip()] if configured is not None else CLOUDFLARE_CIDRS
    return tuple(ipaddress.ip_network(cidr) for cidr in cidrs)


def _is_trusted_edge(address: str) -> bool:
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return False
    return any(ip in network for network in _edge_networks(os.environ.get("CANARY_TRUSTED_EDGE_CIDRS")))


def client_ip(request) -> str | None:
    """The visitor address that neither the visitor nor a bypassed edge can forge."""
    if os.environ.get("FLY_APP_NAME"):
        fly_client = (request.headers.get("fly-client-ip") or "").strip()
        if fly_client:
            edge_client = (request.headers.get("cf-connecting-ip") or "").strip()
            if edge_client and _is_trusted_edge(fly_client):
                return edge_client
            return fly_client
    return get_remote_address(request)


def _client_key(request) -> str:
    # Fall back to a shared sentinel so requests with no resolvable client still
    # land in a rate-limited bucket rather than bypassing the limiter entirely.
    return client_ip(request) or "anonymous"


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


def preview_limit() -> str:
    """Per-IP limit for reading a manuscript before creation (no storage, no spend)."""
    return os.environ.get("CANARY_RATE_LIMIT_PREVIEW", "30/minute")


def cost_limit() -> str:
    """Per-IP limit for credit-charged actions (run / regen)."""
    return os.environ.get("CANARY_RATE_LIMIT_COST", "60/minute")


def export_limit() -> str:
    """Per-IP limit for PDF/CBZ export (CPU + memory bound, no credit charge).

    Export re-runs Finish packaging on every call; without a cap a script
    looping export on a large project can saturate the single uvicorn worker.
    Default is intentionally low (3/min) since each call renders every page.
    """
    return os.environ.get("CANARY_RATE_LIMIT_EXPORT", "3/minute")
