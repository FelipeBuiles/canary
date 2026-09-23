"""Pre-parser request-body limits for JSON and multipart endpoints."""

from __future__ import annotations

import os
from collections.abc import Awaitable, Callable

from starlette.requests import Request
from starlette.responses import Response

from novel_to_comic.input_limits import InputLimits

_STYLE_DIRECTION_BODY_BYTES = 11 * 1024 * 1024
_MULTIPART_ENVELOPE_BYTES = 1024 * 1024


def _max_body_bytes() -> int:
    """Cap on request body size in bytes, read once per request."""
    try:
        return int(os.environ.get("CANARY_MAX_BODY_MB", "2")) * 1024 * 1024
    except (TypeError, ValueError):
        return 2 * 1024 * 1024


def _body_cap_bytes(path: str, method: str) -> int:
    """Return the pre-parser body cap for this endpoint."""
    if method == "POST" and path.rstrip("/") == "/api/projects":
        return InputLimits.from_env().upload_bytes + _MULTIPART_ENVELOPE_BYTES
    parts = path.rstrip("/").split("/")
    if (
        method == "POST"
        and len(parts) == 6
        and parts[1:3] == ["api", "projects"]
        and parts[4:] == ["styles", "direction"]
    ):
        return _STYLE_DIRECTION_BODY_BYTES
    return _max_body_bytes()


async def body_size_limit_middleware(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
    """Reject an oversized body before FastAPI parses it or resolves auth."""
    path = request.url.path
    if request.method in ("GET", "HEAD", "OPTIONS"):
        return await call_next(request)

    cap = _body_cap_bytes(path, request.method)
    content_length = request.headers.get("content-length")
    if content_length is not None:
        try:
            if int(content_length) > cap:
                return Response(
                    content='{"detail":"Request body too large"}',
                    status_code=413,
                    media_type="application/json",
                )
        except ValueError:
            pass  # Malformed Content-Length — let the framework handle it.

    # A client can omit or lie about Content-Length. Read at most cap bytes
    # before entering routing; BaseHTTPMiddleware replays the cached body to
    # FastAPI, including Stripe's exact signed webhook payload.
    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > cap:
            return Response(
                content='{"detail":"Request body too large"}',
                status_code=413,
                media_type="application/json",
            )
        body.extend(chunk)
    request._body = bytes(body)  # type: ignore[attr-defined]
    return await call_next(request)
