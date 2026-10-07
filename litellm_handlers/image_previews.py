"""Relay previews around the proxy's existing authenticated image request.

The normal LiteLLM route still owns submission, errors, usage and the final
response. A request-local sink lets its native image handlers publish previews
before that response, without another provider call or credential path.
"""

from __future__ import annotations

import asyncio
import json
from contextvars import ContextVar
from typing import Any, Callable


PREVIEW_HEADER = b"x-canary-image-previews"
_detached_routes: set[asyncio.Task] = set()
_sink: ContextVar[Callable[[dict[str, Any]], None] | None] = ContextVar("image_preview_sink", default=None)


def requested_partial_images() -> int:
    return 3 if _sink.get() is not None else 0


def publish_partial_image(event: dict[str, Any]) -> None:
    sink = _sink.get()
    index = event.get("partial_image_index")
    encoded = event.get("b64_json")
    if (sink is not None and type(index) is int and 0 <= index < 3
            and isinstance(encoded, str) and 0 < len(encoded) <= 12 * 1024 * 1024):
        sink({"type": "image_preview", "index": index, "total": 3, "b64_json": encoded})


class ImagePreviewMiddleware:
    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        if (scope.get("type") != "http" or scope.get("method") != "POST"
                or scope.get("path") not in {"/v1/images/generations", "/v1/images/edits"}
                or dict(scope.get("headers", [])).get(PREVIEW_HEADER) != b"3"):
            await self.app(scope, receive, send)
            return

        queue: asyncio.Queue = asyncio.Queue(maxsize=4)
        detached = False

        def preview(event: dict) -> None:
            # A slow consumer can miss a preview; it must never delay paid work.
            if not detached and not queue.full():
                queue.put_nowait(("preview", event))

        async def capture(message: dict) -> None:
            # After the client leaves, the route still completes its paid
            # call and its own usage logging; only the delivery is dropped.
            if not detached:
                await queue.put(("response", message))

        async def run() -> None:
            token = _sink.set(preview)
            try:
                await self.app(scope, receive, capture)
            finally:
                _sink.reset(token)

        async def next_message() -> tuple[str, dict]:
            while True:
                if not queue.empty():
                    return queue.get_nowait()
                if task.done():
                    await task
                    raise RuntimeError("Image route ended without a response")
                pending = asyncio.ensure_future(queue.get())
                try:
                    await asyncio.wait({pending, task}, return_when=asyncio.FIRST_COMPLETED)
                finally:
                    if not pending.done():
                        pending.cancel()
                    await asyncio.gather(pending, return_exceptions=True)
                if not pending.cancelled():
                    return pending.result()
                # Otherwise any message the route queued stays in the queue.

        task = asyncio.create_task(run())
        streamed = False
        response_start: dict = {}
        body = bytearray()
        try:
            while True:
                kind, message = await next_message()
                if kind == "preview":
                    if response_start and not streamed:
                        continue  # The plain response has already started.
                    if not streamed:
                        await send({"type": "http.response.start", "status": 200, "headers": [
                            (b"content-type", b"text/event-stream"),
                            (b"cache-control", b"no-store"), (b"x-accel-buffering", b"no"),
                        ]})
                        streamed = True
                    await send({"type": "http.response.body", "body": _sse(message), "more_body": True})
                elif message["type"] == "http.response.start":
                    response_start = message
                    if not streamed:
                        await send(message)
                elif not streamed:
                    await send(message)
                    if message["type"] == "http.response.body" and not message.get("more_body", False):
                        break
                elif message["type"] == "http.response.body":
                    body.extend(message.get("body", b""))
                    if not message.get("more_body", False):
                        # Preserve the proxy's exact buffered body and headers,
                        # including an error that arrived after an early preview.
                        await send({"type": "http.response.body", "body": _sse({
                            "type": "image_result", "status_code": response_start["status"],
                            "headers": [[key.decode("latin-1"), value.decode("latin-1")]
                                        for key, value in response_start.get("headers", [])],
                            "body": body.decode("utf-8"),
                        }), "more_body": False})
                        break
            await task
        finally:
            if not task.done():
                # Never cancel a submitted image call because delivery failed:
                # that would discard a paid result and the gateway's usage log.
                detached = True
                while not queue.empty():
                    queue.get_nowait()
                _detached_routes.add(task)
                task.add_done_callback(_detached_routes.discard)


def _sse(event: dict) -> bytes:
    return f"data: {json.dumps(event)}\n\n".encode()
