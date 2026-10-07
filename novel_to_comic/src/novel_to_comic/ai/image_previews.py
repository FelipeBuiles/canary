"""Transient image observations, independent of saved artwork and progress."""

from __future__ import annotations

import asyncio
import base64
import io
import json as jsonlib
import logging
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

import httpx
from PIL import Image

from novel_to_comic.ai.errors import AITransportError
from novel_to_comic.ai.admission import AdmissionRejected, cancelled_before_submission, stream as admitted_stream
from novel_to_comic.events import EventCallback
from novel_to_comic.image_models import PREVIEW_IMAGE_ALIASES


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _Observer:
    root: Path
    stage: str
    emit: EventCallback


_observer: ContextVar[_Observer | None] = ContextVar("image_preview_observer", default=None)
_target: ContextVar[str | None] = ContextVar("image_preview_target", default=None)


@contextmanager
def image_preview_events(project_dir: Path, stage: str, emit: EventCallback) -> Iterator[None]:
    # target -> (request_id, latest preview_index) for previews still shown.
    active: dict[str, tuple[str, int]] = {}

    def publish(event: dict) -> None:
        target = event["target"]
        if event["type"] == "image_preview":
            active[target] = (event["request_id"], event["preview_index"])
        elif event["type"] == "image_preview_clear":
            current = active.get(target)
            if current and (event.get("reset") or current[0] == event["request_id"]):
                del active[target]
        emit(event)

    from novel_to_comic.workspace import series_root

    # Asset targets are series-relative, matching the series file URLs the UI
    # renders, even when a part view started the job (Cast, Style samples).
    token = _observer.set(_Observer(series_root(project_dir).resolve(), stage, publish))
    succeeded = False
    try:
        yield
        succeeded = True
    finally:
        try:
            for target, (request_id, index) in active.items():
                event = {"type": "image_preview_clear", "stage": stage,
                         "target": target, "request_id": request_id}
                if succeeded and index >= 3:
                    # Completed pixels from a successful job: the saved file
                    # supersedes them, so the UI may hold them until it loads.
                    event["settled"] = True
                try:
                    emit(event)
                except Exception:
                    logger.debug("Image preview observer failed")
        finally:
            _observer.reset(token)


@contextmanager
def image_preview_target(output_path: Path) -> Iterator[None]:
    token = _target.set(str(output_path.resolve()))
    try:
        yield
    finally:
        _target.reset(token)


def _emit(kind: str, *, target: str, request_id: str, **fields: Any) -> None:
    observer = _observer.get()
    if observer is None:
        return
    if not target.startswith("page:"):
        try:
            target = str(Path(target).relative_to(observer.root))
        except ValueError:
            return
    try:
        observer.emit({"type": kind, "stage": observer.stage, "target": target,
                       "request_id": request_id, **fields})
    except Exception:
        logger.debug("Image preview observer failed", exc_info=True)


def _preview_url(encoded: str) -> str:
    if not isinstance(encoded, str) or len(encoded) > 12 * 1024 * 1024:
        raise ValueError("Invalid image preview")
    with Image.open(io.BytesIO(base64.b64decode(encoded, validate=True))) as image:
        image.thumbnail((768, 768))
        output = io.BytesIO()
        image.convert("RGB").save(output, format="WEBP", quality=80)
    return "data:image/webp;base64," + base64.b64encode(output.getvalue()).decode()


def _completed_preview_url(result: httpx.Response) -> str:
    return _preview_url(result.json()["data"][0]["b64_json"])


async def post_image_request(
    url: str, *, headers: dict[str, str], json: dict | None = None,
    data: dict | None = None, files: list | None = None,
    target: str | None = None,
) -> httpx.Response:
    """One image submission; optional previews never authorize another call."""
    from novel_to_comic.ai import client

    params = data if files else json
    target = target or _target.get()
    request_id = headers.get("X-Canary-AI-Event-ID")
    if not request_id:
        from uuid import uuid4
        request_id = str(uuid4())
    if _observer.get() is not None and target is not None:
        # Also clear when a fallback switches to a provider without previews,
        # including a completed OpenAI result rejected by artifact validation.
        _emit("image_preview_clear", target=target, request_id=request_id, reset=True)
    if (_observer.get() is None or target is None or not params
            or params.get("model") not in PREVIEW_IMAGE_ALIASES):
        return await client._post_with_retry(
            url, headers=headers, json=json, data=data, files=files, retry_ambiguous=False,
        )

    # Reuse the client's safe connection/rate-limit budget. Once the gateway
    # has delivered any provider pixels, even an error cannot authorize retry.
    pacer = client._RetryPacer()
    while True:
        try:
            result, had_preview = await _stream_image_response(
                url, headers=headers, json=json, data=data, files=files,
                target=target, request_id=request_id,
            )
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout) as exc:
            pacer.record_exception(exc)
            await pacer.pause_or_raise(rate_limited=False)
        else:
            if result.status_code != 429 or had_preview:
                return result
            pacer.record_retryable_status(result)
            await pacer.pause_or_raise(
                rate_limited=True, retry_after=client._retry_after_seconds(result),
            )


async def _stream_image_response(
    url: str, *, headers: dict[str, str], json: dict | None,
    data: dict | None, files: list | None, target: str, request_id: str,
) -> tuple[httpx.Response, bool]:
    from novel_to_comic.ai import client

    had_preview = False
    try:
        async with admitted_stream(
            client._http, "POST", url, headers={**headers, "x-canary-image-previews": "3"},
            **({"data": data, "files": files} if files else {"json": json}),
        ) as (response, lease):
            if "text/event-stream" not in response.headers.get("content-type", ""):
                await response.aread()
                result = response
            else:
                result = None
                async for line in response.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    event = jsonlib.loads(line[5:])
                    if event.get("type") == "image_preview":
                        had_preview = True
                        index = event.get("index")
                        if type(index) is not int or not 0 <= index < 3:
                            continue
                        try:
                            # Decoding and re-encoding pixels must not stall
                            # the event loop that serves every other job.
                            image_url = await asyncio.to_thread(_preview_url, event.get("b64_json"))
                        except Exception:
                            # Malformed advisory pixels must not lose the paid final result.
                            logger.debug("Discarded an invalid image preview")
                            continue
                        _emit("image_preview", target=target, request_id=request_id,
                              preview_index=index, preview_total=3, image_url=image_url)
                    elif event.get("type") == "image_result":
                        result = httpx.Response(
                            event["status_code"], headers=event["headers"],
                            content=event["body"].encode(), request=response.request,
                        )
                        break
                if result is None:
                    raise httpx.ReadError("Image stream ended without its final result")
            if lease:
                lease.observe_response(result)
            if result.status_code >= 400:
                _emit("image_preview_clear", target=target, request_id=request_id)
            else:
                try:
                    image_url = await asyncio.to_thread(_completed_preview_url, result)
                except Exception:
                    logger.debug("Discarded invalid completed preview pixels")
                else:
                    # Show the completed pixels promptly, still as advisory
                    # artwork until the caller validates and saves the result.
                    _emit("image_preview", target=target, request_id=request_id,
                          preview_index=3, preview_total=3, image_url=image_url)
            if result.status_code >= 500 and not client._fal_definitely_unsubmitted(result):
                from novel_to_comic.ai.context import current_ai_request_context
                from novel_to_comic.server.credits import retain_ambiguous_job
                retain_ambiguous_job(current_ai_request_context().job_id)
            return result, had_preview
    except AdmissionRejected:
        _emit("image_preview_clear", target=target, request_id=request_id)
        raise
    except (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout):
        _emit("image_preview_clear", target=target, request_id=request_id)
        raise
    except (asyncio.CancelledError, Exception) as exc:
        _emit("image_preview_clear", target=target, request_id=request_id)
        if cancelled_before_submission(exc):
            raise
        from novel_to_comic.ai.context import current_ai_request_context
        from novel_to_comic.server.credits import retain_ambiguous_job
        retain_ambiguous_job(current_ai_request_context().job_id)
        if isinstance(exc, asyncio.CancelledError):
            raise
        raise AITransportError(
            "Image submission outcome is unknown; it was not automatically repeated.",
            phase="ambiguous_submission",
        ) from exc
