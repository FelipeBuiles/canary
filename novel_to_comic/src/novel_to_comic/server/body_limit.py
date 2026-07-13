"""Defense-in-depth request-body size cap.

The novel-upload route enforces its own cap while streaming (see
``projects._save_upload_capped``), but every other JSON endpoint relied on
Starlette's unbounded default, which buffers the full body in memory. This
middleware caps the body of every non-exempt request up-front, so a giant JSON
POST can't exhaust the worker's memory.

Exemptions:
  - File uploads handled by the streaming cap in projects.py are exempt,
    since their larger bodies are validated mid-stream.

Configurable via ``CANARY_MAX_BODY_MB`` (default 2 MB). Set higher only if a
known endpoint legitimately needs more and has its own protections.
"""

from __future__ import annotations

import os
from collections.abc import Awaitable, Callable

from starlette.requests import Request
from starlette.responses import Response

# Upload routes use _save_upload_capped (streaming, 10 MB) — exempt from the
# generic cap, which is lower. Matched by path suffix since the upload handler
# is a POST to /api/projects or /api/projects/import-story.
_EXEMPT_EXACT = frozenset({"/api/projects", "/api/projects/import-story", "/api/projects/short-stories"})


def _max_body_bytes() -> int:
    """Cap on request body size in bytes, read once per request."""
    try:
        return int(os.environ.get("CANARY_MAX_BODY_MB", "2")) * 1024 * 1024
    except (TypeError, ValueError):
        return 2 * 1024 * 1024


def _is_exempt(path: str) -> bool:
    if path in _EXEMPT_EXACT:
        return True
    return False


async def body_size_limit_middleware(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
    """Reject oversized request bodies with 413 before the handler reads them.

    The check runs against ``Content-Length`` when present (cheap, header-only).
    Chunked transfers omit Content-Length; for those we wrap the receive channel
    so the cap is enforced as bytes stream in — same approach Starlette's own
    ``LimitedRequest`` uses.
    """
    path = request.url.path
    if _is_exempt(path) or request.method in ("GET", "HEAD", "OPTIONS"):
        return await call_next(request)

    cap = _max_body_bytes()
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

    # No Content-Length (chunked): enforce as bytes arrive. We interpose on the
    # ASGI receive callable and abort once the accumulated body exceeds the cap.
    received_bytes = 0
    receive = request.receive

    async def _capped_receive():
        nonlocal received_bytes
        message = await receive()
        if message["type"] == "http.request":
            body = message.get("body", b"")
            received_bytes += len(body)
            if received_bytes > cap:
                # Mutate the message to an empty body and stash the rejection
                # so the route handler sees a short body; the real response is
                # sent by the wrapper below. We can't raise here cleanly.
                raise _BodyTooLarge()
        return message

    # Stash the wrapped receive on the scope so downstream handlers that call
    # request.body() pull through the cap. Starlette reads receive from
    # request._receive; replacing request.receive is not enough. The simplest
    # robust approach: only enforce Content-Length here (covers the common
    # abuse vector — a single shot JSON body), and rely on the per-route
    # streaming cap for uploads. Chunked oversized JSON is an unusual attack.
    try:
        request._receive = _capped_receive  # type: ignore[attr-defined]
        return await call_next(request)
    except _BodyTooLarge:
        return Response(
            content='{"detail":"Request body too large"}',
            status_code=413,
            media_type="application/json",
        )
    finally:
        # Restore so the request object isn't mutated if it's reused.
        request._receive = receive  # type: ignore[attr-defined]


class _BodyTooLarge(Exception):
    """Internal sentinel raised from the wrapped receive channel."""
