"""Pre-parser request-body limits for JSON and multipart endpoints."""

from __future__ import annotations

import os
from collections.abc import Awaitable, Callable

from fastapi.routing import APIRoute
from starlette.requests import Request
from starlette.responses import Response

from novel_to_comic.input_limits import InputLimits

_IMAGE_UPLOAD_BODY_BYTES = 11 * 1024 * 1024
_MULTIPART_ENVELOPE_BYTES = 1024 * 1024


def _max_body_bytes() -> int:
    """Cap on request body size in bytes, read once per request."""
    try:
        return int(os.environ.get("CANARY_MAX_BODY_MB", "2")) * 1024 * 1024
    except (TypeError, ValueError):
        return 2 * 1024 * 1024


def _is_source_upload(path: str, method: str) -> bool:
    parts = path.rstrip("/").split("/")
    # Creation and its read-only preview accept the same whole manuscript.
    return (
        method == "POST" and path.rstrip("/") in ("/api/projects", "/api/projects/source-preview")
    ) or (
        parts[1:3] == ["api", "projects"]
        and len(parts) > 3
        and bool(parts[3])
        and (
            (method == "POST" and len(parts) == 5 and parts[4] == "parts")
            or (
                method == "PUT" and len(parts) == 7
                and parts[4] == "parts" and bool(parts[5]) and parts[6] == "text"
            )
        )
    )


def form_part_cap_bytes(path: str, method: str) -> int:
    """Permit UTF-8 source text fields within the extracted-character budget."""
    if _is_source_upload(path, method):
        return InputLimits.from_env().extracted_characters * 4
    return 1024 * 1024


class SourceUploadRoute(APIRoute):
    """Use the source field budget before FastAPI's cached form parsing."""

    def get_route_handler(self) -> Callable[[Request], Awaitable[Response]]:
        original = super().get_route_handler()

        async def handle(request: Request) -> Response:
            if _is_source_upload(request.url.path, request.method):
                await request.form(max_part_size=form_part_cap_bytes(request.url.path, request.method))
            return await original(request)

        return handle


def _body_cap_bytes(path: str, method: str) -> int:
    """Return the pre-parser body cap for this endpoint."""
    if _is_source_upload(path, method):
        return InputLimits.from_env().upload_bytes + _MULTIPART_ENVELOPE_BYTES
    parts = path.rstrip("/").split("/")
    if (
        method == "POST"
        and len(parts) == 6
        and parts[1:3] == ["api", "projects"]
        and parts[4:] in (["styles", "direction"], ["cast", "reference-uploads"])
    ):
        return _IMAGE_UPLOAD_BODY_BYTES
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
    del body
    return await call_next(request)
