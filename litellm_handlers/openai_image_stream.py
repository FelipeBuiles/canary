"""LiteLLM custom provider for OpenAI GPT Image requests over streaming SSE.

LiteLLM's built-in image handlers cannot stream. Streaming makes OpenAI answer
an explicit rejection before any image work, and every failure carries the
phase it happened in, which is the evidence Canary's Draw fallback needs.
With ``partial_images=0``, OpenAI opens the event stream only when the image
is ready (observed 2026-09-28: ~17s for a medium 1024x1536 page, <1s before
``completed``), so the stream opening is not early proof of acceptance. The
handler submits exactly once and never repeats a request.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import json
import logging
import mimetypes
import os
import re
import time
from pathlib import Path
from typing import Any

import httpx
from litellm_handlers.image_previews import publish_partial_image, requested_partial_images
try:
    from litellm.llms.custom_llm import CustomLLM, CustomLLMError
    from litellm.types.utils import ImageObject, ImageResponse, ImageUsage, ImageUsageInputTokensDetails
except ModuleNotFoundError:
    # Keep the pure helpers importable in the application test environment,
    # where the isolated LiteLLM proxy dependency is absent.
    class CustomLLM:
        pass

    class CustomLLMError(Exception):
        def __init__(self, status_code: int, message: str):
            self.status_code = status_code
            self.message = message
            super().__init__(message)

    class ImageObject:
        def __init__(self, **kwargs: Any):
            self.__dict__.update(kwargs)

    class ImageResponse:
        pass

    class ImageUsageInputTokensDetails:
        def __init__(self, **kwargs: Any):
            self.__dict__.update(kwargs)

    class ImageUsage:
        def __init__(self, **kwargs: Any):
            self.__dict__.update(kwargs)


OPENAI_API_BASE = "https://api.openai.com/v1"
SUPPORTED_MODELS = frozenset({"gpt-image-2.5-sunburst", "gpt-image-2.5-flare"})
STREAM_TIMEOUT_S = 300.0
CONNECT_TIMEOUT_S = 10.0
# Controls the frozen manifest may carry; anything else is rejected, never
# forwarded or dropped silently.
_ALLOWED_CONTROLS = frozenset({"quality", "output_format", "n", "background"})
# Canary adapts literature whose canonical content can include nudity on
# artwork, injury or violence (e.g. a carved sphinx with a bare torso). OpenAI's
# default "auto" moderation declines such references outright. "low" is the
# least restrictive tier the Images API offers (there is no "off"); it is
# provider policy, like Vertex's safety-off settings, not a per-request control.
MODERATION = "low"

logger = logging.getLogger(__name__)
_URI_RE = re.compile(r"(?:data:[^\s,]+,|https?://)\S+", re.IGNORECASE)


class OpenAIImageStreamError(CustomLLMError):
    """A redacted, phase-tagged provider error.

    Phases the application relies on:
    - ``submit_connect``: no connection was made; OpenAI cannot have accepted it.
    - ``submit``: OpenAI answered with an error before opening the event
      stream; ``upstream_status`` says which.
    - ``submit_transport``: the request was sent but no response arrived.
    - ``stream``: OpenAI accepted the request, then the result was lost.
    - ``result``: the stream completed without a usable image.
    - ``request_validation``: the request never left the gateway.
    """

    def __init__(
        self,
        *,
        status_code: int,
        phase: str,
        model: str,
        upstream_status: int | None = None,
        request_id: str | None = None,
        detail: str | None = None,
    ) -> None:
        self.phase = phase
        self.model = model
        self.upstream_status = upstream_status
        self.request_id = request_id
        self.detail = detail
        upstream = f"; upstream_status={upstream_status}" if upstream_status is not None else ""
        request = f"; request_id={request_id}" if request_id else ""
        suffix = f"; detail={detail}" if detail else ""
        super().__init__(
            status_code=status_code,
            message=f"OpenAI image {phase} failed for {model}{upstream}{request}{suffix}",
        )


class OpenAIImageStreamLLM(CustomLLM):
    """Custom LiteLLM provider for streamed OpenAI image generations and edits."""

    def image_edit(
        self,
        model: str,
        image: list[Any],
        prompt: str | None,
        model_response: ImageResponse,
        api_key: str | None = None,
        api_base: str | None = None,  # noqa: ARG002
        optional_params: dict[str, Any] | None = None,
        logging_obj: Any | None = None,  # noqa: ARG002
        timeout: float | httpx.Timeout | None = None,
        client: Any | None = None,  # noqa: ARG002
        **kwargs: Any,  # noqa: ARG002
    ) -> ImageResponse:
        return asyncio.run(self._generate_async(
            model=model, image=image, prompt=prompt, model_response=model_response,
            api_key=api_key, optional_params=optional_params or {}, timeout=timeout,
        ))

    async def aimage_edit(
        self,
        model: str,
        image: list[Any],
        prompt: str | None,
        model_response: ImageResponse,
        api_key: str | None = None,
        api_base: str | None = None,  # noqa: ARG002
        optional_params: dict[str, Any] | None = None,
        logging_obj: Any | None = None,  # noqa: ARG002
        timeout: float | httpx.Timeout | None = None,
        client: Any | None = None,  # noqa: ARG002
        **kwargs: Any,  # noqa: ARG002
    ) -> ImageResponse:
        return await self._generate_async(
            model=model, image=image, prompt=prompt, model_response=model_response,
            api_key=api_key, optional_params=optional_params or {}, timeout=timeout,
        )

    async def aimage_generation(
        self,
        model: str,
        prompt: str,
        api_key: str | None,
        api_base: str | None,  # noqa: ARG002
        model_response: ImageResponse,
        optional_params: dict[str, Any],
        logging_obj: Any,  # noqa: ARG002
        timeout: float | httpx.Timeout | None = None,
        client: Any | None = None,  # noqa: ARG002
        **kwargs: Any,  # noqa: ARG002
    ) -> ImageResponse:
        return await self._generate_async(
            model=model, image=[], prompt=prompt, model_response=model_response,
            api_key=api_key, optional_params=optional_params or {}, timeout=timeout,
        )

    async def _generate_async(
        self,
        *,
        model: str,
        image: list[Any],
        prompt: str | None,
        model_response: ImageResponse,
        api_key: str | None,
        optional_params: dict[str, Any],
        timeout: float | httpx.Timeout | None,
    ) -> ImageResponse:
        upstream_model = upstream_model_name(model)
        fields = request_fields(upstream_model, prompt or "", optional_params)
        files = [image_part(item, index, model=upstream_model) for index, item in enumerate(image)]
        endpoint = "edits" if files else "generations"
        read_timeout = float(timeout) if isinstance(timeout, (int, float)) else STREAM_TIMEOUT_S
        completed, request_id = await _stream_request(
            endpoint=endpoint, model=upstream_model, fields=fields, files=files,
            api_key=api_key, read_timeout=read_timeout,
        )
        image_b64 = completed_image(completed, model=upstream_model, request_id=request_id)
        model_response.created = int(completed.get("created_at") or time.time())
        model_response.data = [ImageObject(b64_json=image_b64)]
        usage = completed_usage(completed)
        if usage is not None:
            model_response.usage = usage
        model_response._hidden_params["model"] = upstream_model
        model_response._hidden_params["custom_llm_provider"] = "openai-stream"
        model_response._hidden_params["provider_request_id"] = request_id
        # Canary prices this call from the returned token usage. Reporting a
        # gateway cost here would bypass that, and LiteLLM cannot price this
        # custom provider (it would report 0.0, which settles as free).
        model_response._hidden_params["response_cost"] = None
        model_response.provider_request_id = request_id
        model_response.model = f"openai/{upstream_model}"
        model_response.image_previews_requested = int(fields["partial_images"])
        return model_response


def upstream_model_name(model: str) -> str:
    cleaned = (model or "").strip().strip("/").removeprefix("openai-stream/").removeprefix("openai/")
    if cleaned not in SUPPORTED_MODELS:
        raise OpenAIImageStreamError(
            status_code=400, phase="request_validation", model=cleaned or "<missing>",
            detail="unsupported OpenAI image model",
        )
    return cleaned


def request_fields(model: str, prompt: str, params: dict[str, Any]) -> dict[str, str]:
    """The exact form fields sent upstream, from Canary's frozen manifest.

    LiteLLM removes standard image arguments (size, quality) for custom
    providers, so dimensions and controls travel in ``canary_wire_request``.
    """
    if not prompt:
        raise OpenAIImageStreamError(status_code=400, phase="request_validation", model=model,
                                     detail="prompt is required")
    wire = params.get("canary_wire_request")
    if not isinstance(wire, str):
        raise OpenAIImageStreamError(status_code=400, phase="request_validation", model=model,
                                     detail="missing frozen wire manifest")
    try:
        manifest = json.loads(wire)
        width, height = int(manifest["width"]), int(manifest["height"])
        controls = dict(manifest["controls"])
    except (KeyError, TypeError, ValueError) as exc:
        raise OpenAIImageStreamError(status_code=400, phase="request_validation", model=model,
                                     detail=f"invalid frozen wire manifest ({type(exc).__name__})") from None
    unknown = sorted(set(controls) - _ALLOWED_CONTROLS)
    if unknown:
        raise OpenAIImageStreamError(status_code=400, phase="request_validation", model=model,
                                     detail=f"unsupported controls {unknown}")
    if width <= 0 or height <= 0 or width % 16 or height % 16:
        raise OpenAIImageStreamError(status_code=400, phase="request_validation", model=model,
                                     detail=f"invalid size {width}x{height}")
    fields = {
        "model": model,
        "prompt": prompt,
        "size": f"{width}x{height}",
        "stream": "true",
        "partial_images": str(requested_partial_images()),
        "moderation": MODERATION,
    }
    for key, value in controls.items():
        fields[key] = str(value).lower() if isinstance(value, bool) else str(value)
    return fields


def image_part(item: Any, index: int, *, model: str) -> tuple[str, tuple[str, bytes, str]]:
    """One multipart reference. Unreadable references fail the request."""
    filename = f"reference-{index}.png"
    mime: str | None = None
    data: bytes | None = None
    if isinstance(item, tuple):
        if len(item) >= 1 and item[0]:
            filename = Path(str(item[0])).name
        if len(item) >= 2:
            data = _read_bytes(item[1])
        if len(item) >= 3 and item[2]:
            mime = str(item[2])
    else:
        name = getattr(item, "filename", None) or getattr(item, "name", None)
        if isinstance(name, str) and name:
            filename = Path(name).name
        content_type = getattr(item, "content_type", None)
        if content_type:
            mime = str(content_type)
        data = _read_bytes(item)
    if not data:
        raise OpenAIImageStreamError(
            status_code=400, phase="request_validation", model=model,
            detail=f"reference {index} has no readable image bytes",
        )
    mime = mime or mimetypes.guess_type(filename)[0] or "image/png"
    return ("image[]", (filename, data, mime))


def _read_bytes(value: Any) -> bytes | None:
    if isinstance(value, bytes):
        return value
    if isinstance(value, bytearray):
        return bytes(value)
    reader = getattr(value, "read", None)
    if not callable(reader):
        return None
    seeker = getattr(value, "seek", None)
    try:
        if callable(seeker):
            seeker(0)
        out = reader()
    finally:
        if callable(seeker):
            seeker(0)
    if isinstance(out, bytearray):
        return bytes(out)
    return out if isinstance(out, bytes) else None


def _headers(api_key: str | None) -> dict[str, str]:
    key = (api_key or os.environ.get("OPENAI_API_KEY") or "").strip()
    if not key:
        raise OpenAIImageStreamError(status_code=500, phase="request_validation", model="<config>",
                                     detail="OPENAI_API_KEY is not set")
    return {"Authorization": f"Bearer {key}", "Accept": "text/event-stream"}


async def _stream_request(
    *,
    endpoint: str,
    model: str,
    fields: dict[str, str],
    files: list[tuple[str, tuple[str, bytes, str]]],
    api_key: str | None,
    read_timeout: float,
) -> tuple[dict[str, Any], str | None]:
    url = f"{OPENAI_API_BASE}/images/{endpoint}"
    headers = _headers(api_key)
    request_id: str | None = None
    accepted = False
    timeout = httpx.Timeout(read_timeout, connect=CONNECT_TIMEOUT_S)
    try:
        async with httpx.AsyncClient(timeout=timeout) as http:
            request = (
                http.stream("POST", url, headers=headers, data=fields, files=files)
                if files else
                http.stream("POST", url, headers=headers, json=_json_body(fields))
            )
            async with request as response:
                request_id = response.headers.get("x-request-id")
                if response.status_code >= 400:
                    await response.aread()
                    detail = _response_detail(response)
                    logger.error("OpenAI image submit rejected model=%s status=%s request_id=%s detail=%s",
                                 model, response.status_code, request_id, detail or "<none>")
                    raise OpenAIImageStreamError(
                        status_code=response.status_code, phase="submit", model=model,
                        upstream_status=response.status_code, request_id=request_id, detail=detail,
                    )
                accepted = True
                logger.info("OpenAI image request accepted model=%s endpoint=%s request_id=%s refs=%d",
                            model, endpoint, request_id, len(files))
                completed = await _read_completed_event(response, model=model, request_id=request_id)
    except OpenAIImageStreamError:
        raise
    except asyncio.CancelledError:
        logger.warning("OpenAI image request cancelled model=%s request_id=%s accepted=%s",
                       model, request_id, accepted)
        raise
    except (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout) as exc:
        # No connection was established, so OpenAI cannot have accepted it.
        raise OpenAIImageStreamError(status_code=503, phase="submit_connect", model=model,
                                     detail=type(exc).__name__) from None
    except httpx.RequestError as exc:
        phase = "stream" if accepted else "submit_transport"
        logger.error("OpenAI image %s transport failure model=%s request_id=%s error=%s",
                     phase, model, request_id, type(exc).__name__)
        raise OpenAIImageStreamError(status_code=502, phase=phase, model=model,
                                     request_id=request_id, detail=type(exc).__name__) from None
    return completed, request_id


def _json_body(fields: dict[str, str]) -> dict[str, Any]:
    body: dict[str, Any] = dict(fields)
    body["stream"] = True
    body["partial_images"] = int(fields["partial_images"])
    if "n" in body:
        body["n"] = int(body["n"])
    return body


async def _read_completed_event(
    response: httpx.Response, *, model: str, request_id: str | None,
) -> dict[str, Any]:
    content_type = response.headers.get("content-type", "")
    if "text/event-stream" not in content_type:
        # A buffered JSON answer still carries the image; accept it as final.
        body = json.loads(await response.aread())
        data = (body.get("data") or [{}])[0] if isinstance(body, dict) else {}
        return {"type": "buffered", "b64_json": data.get("b64_json"),
                "usage": body.get("usage") if isinstance(body, dict) else None,
                "created_at": body.get("created") if isinstance(body, dict) else None}
    async for event in iter_sse_events(response.aiter_lines()):
        kind = str(event.get("type") or "")
        if kind in {"image_generation.partial_image", "image_edit.partial_image"}:
            publish_partial_image(event)
        if kind.endswith(".completed"):
            return event
        if kind == "error" or "error" in event:
            error = event.get("error") if isinstance(event.get("error"), dict) else event
            raise OpenAIImageStreamError(status_code=502, phase="stream", model=model, request_id=request_id,
                                         detail=_safe_payload_detail({"error": error}))
    raise OpenAIImageStreamError(status_code=502, phase="stream", model=model, request_id=request_id,
                                 detail="event stream ended without a completed event")


async def iter_sse_events(lines: Any):
    """Yield JSON payloads from an SSE line stream, one per event."""
    data: list[str] = []
    async for raw in lines:
        line = raw.rstrip("\r")
        if not line:
            if data:
                payload = "\n".join(data)
                data = []
                if payload.strip() == "[DONE]":
                    return
                try:
                    parsed = json.loads(payload)
                except json.JSONDecodeError:
                    continue
                if isinstance(parsed, dict):
                    yield parsed
            continue
        if line.startswith(":"):
            continue
        if line.startswith("data:"):
            data.append(line[5:].lstrip())
    if data:
        try:
            parsed = json.loads("\n".join(data))
        except json.JSONDecodeError:
            return
        if isinstance(parsed, dict):
            yield parsed


def completed_image(event: dict[str, Any], *, model: str, request_id: str | None) -> str:
    encoded = event.get("b64_json")
    if not isinstance(encoded, str) or not encoded:
        raise OpenAIImageStreamError(status_code=502, phase="result", model=model, request_id=request_id,
                                     detail="completed event has no image")
    try:
        base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error):
        raise OpenAIImageStreamError(status_code=502, phase="result", model=model, request_id=request_id,
                                     detail="completed event image is not base64") from None
    return encoded


def completed_usage(event: dict[str, Any]) -> ImageUsage | None:
    usage = event.get("usage")
    if not isinstance(usage, dict):
        return None
    details = usage.get("input_tokens_details") or {}
    input_tokens = int(usage.get("input_tokens") or 0)
    output_tokens = int(usage.get("output_tokens") or 0)
    return ImageUsage(
        input_tokens=input_tokens,
        input_tokens_details=ImageUsageInputTokensDetails(
            image_tokens=int(details.get("image_tokens") or 0),
            text_tokens=int(details.get("text_tokens") or 0),
        ),
        output_tokens=output_tokens,
        total_tokens=int(usage.get("total_tokens") or input_tokens + output_tokens),
    )


def _response_detail(response: httpx.Response) -> str | None:
    try:
        payload = response.json()
    except (TypeError, ValueError, json.JSONDecodeError):
        text = response.text.strip()
        return _redact_text(text) if text else None
    return _safe_payload_detail(payload)


def _safe_payload_detail(payload: Any) -> str | None:
    if not isinstance(payload, dict):
        return None
    values: list[str] = []
    error = payload.get("error")
    if isinstance(error, dict):
        for key in ("code", "type", "message"):
            value = error.get(key)
            if value is not None:
                values.append(f"{key}={_redact_text(str(value))}")
    elif error is not None:
        values.append(f"error={_redact_text(str(error))}")
    return "; ".join(values)[:600] or None


def _redact_text(value: str) -> str:
    text = " ".join(value.split())
    text = _URI_RE.sub("<redacted-uri>", text)
    return text[:400]


openai_image_stream_llm = OpenAIImageStreamLLM()
