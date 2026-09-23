"""LiteLLM custom provider for fal.ai queue image-edit endpoints."""

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
try:
    from litellm.llms.custom_llm import CustomLLM, CustomLLMError
    from litellm.types.utils import ImageObject, ImageResponse
except ModuleNotFoundError:
    # Keep pure payload/endpoint helpers importable in the application test
    # environment, where the isolated LiteLLM proxy dependency is absent.
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

FAL_QUEUE_BASE = "https://queue.fal.run"
POLL_INTERVAL_S = 1.5
POLL_TIMEOUT_S = 300.0
GET_RETRY_COUNT = 2
GET_RETRYABLE_STATUS_CODES = frozenset({408, 425, 429, 500, 502, 503, 504})

logger = logging.getLogger(__name__)
_URI_RE = re.compile(r"(?:data:[^\s,]+,|https?://)\S+", re.IGNORECASE)


class FalQueueError(CustomLLMError):
    """A redacted provider error that LiteLLM can map to an HTTP status."""

    def __init__(
        self,
        *,
        status_code: int,
        phase: str,
        endpoint: str,
        request_id: str | None = None,
        detail: str | None = None,
    ) -> None:
        self.phase = phase
        self.endpoint = endpoint
        self.request_id = request_id
        self.detail = detail
        suffix = f"; detail={detail}" if detail else ""
        request = f"; request_id={request_id}" if request_id else ""
        super().__init__(
            status_code=status_code,
            message=f"FAL {phase} failed for {endpoint}{request}{suffix}",
        )


class FalQueueLLM(CustomLLM):
    """Custom LiteLLM provider for fal.ai queue image endpoints."""

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
        return asyncio.run(self._image_edit_async(
            model=model,
            image=image,
            prompt=prompt,
            model_response=model_response,
            api_key=api_key,
            optional_params=optional_params or {},
            timeout=timeout,
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
        return await self._image_edit_async(
            model=model,
            image=image,
            prompt=prompt,
            model_response=model_response,
            api_key=api_key,
            optional_params=optional_params or {},
            timeout=timeout,
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
        return await self._image_edit_async(
            model=model,
            image=[],
            prompt=prompt,
            model_response=model_response,
            api_key=api_key,
            optional_params=optional_params or {},
            timeout=timeout,
        )

    async def _image_edit_async(
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
        endpoint = _fal_endpoint(model, has_images=bool(image))
        payload = _build_payload(endpoint, prompt or "", image, optional_params)
        request_timeout = timeout if timeout is not None else 300.0
        request_id: str | None = None
        try:
            async with httpx.AsyncClient(
                timeout=request_timeout,
                follow_redirects=True,
            ) as http:
                urls = await _submit(http, endpoint, payload, api_key)
                request_id = urls["request_id"]
                logger.info(
                    "FAL image request submitted endpoint=%s request_id=%s refs=%d",
                    endpoint,
                    request_id,
                    len(image),
                )
                await _poll(http, urls["status_url"], request_id, api_key, endpoint=endpoint)
                full = await _fetch_result(
                    http,
                    urls["response_url"],
                    api_key,
                    endpoint=endpoint,
                    request_id=request_id,
                )
                image_url = _extract_image_url(full, endpoint=endpoint, request_id=request_id)
                image_bytes = await _download(
                    http,
                    image_url,
                    endpoint=endpoint,
                    request_id=request_id,
                )
        except asyncio.CancelledError:
            logger.warning(
                "FAL image request cancelled endpoint=%s request_id=%s",
                endpoint,
                request_id,
            )
            raise
        except FalQueueError:
            logger.exception(
                "FAL image request failed endpoint=%s request_id=%s",
                endpoint,
                request_id,
            )
            raise
        except Exception:
            # Keep the original exception for LiteLLM's mapping, but leave a
            # useful, redacted breadcrumb in the gateway log. The submitted
            # request is never repeated from this handler.
            logger.exception(
                "FAL image request errored endpoint=%s request_id=%s",
                endpoint,
                request_id,
            )
            raise
        b64 = base64.b64encode(image_bytes).decode("ascii")
        model_response.created = int(time.time())
        model_response.data = [ImageObject(b64_json=b64)]
        model_response._hidden_params["model"] = endpoint
        model_response._hidden_params["custom_llm_provider"] = "fal-queue"
        model_response._hidden_params["provider_request_id"] = request_id
        model_response._hidden_params["response_cost"] = None
        return model_response


def _fal_endpoint(model: str, *, has_images: bool = False) -> str:
    cleaned = (model or "").strip().strip("/")
    cleaned = cleaned.removeprefix("fal-queue/")
    if cleaned not in {
        "gpt-image-2.5-sunburst",
        "gpt-image-2.5-sunburst-2026-09-08",
        "openai/gpt-image-2.5/sunburst",
    }:
        raise FalQueueError(status_code=400, phase="request_validation",
                            endpoint=cleaned or "<missing>", detail="unsupported FAL model")
    return f"openai/gpt-image-2.5/sunburst/{'edit' if has_images else 'text-to-image'}"


def _build_payload(endpoint: str, prompt: str, images: list[Any], params: dict[str, Any]) -> dict[str, Any]:
    # LiteLLM 1.101.0 removes standard Images arguments such as `quality`
    # from optional_params for custom providers. The frozen Canary manifest is
    # the authority for those controls and dimensions.
    wire = params.get("canary_wire_request")
    if isinstance(wire, str):
        try:
            manifest = json.loads(wire)
            controls = manifest["controls"]
            if not isinstance(controls, list):
                raise ValueError("controls must be a list")
            wire_controls = dict(controls)
            if not all(isinstance(key, str) for key in wire_controls):
                raise ValueError("control names must be strings")
            params = {
                **params,
                "canary_requested_width": manifest["width"],
                "canary_requested_height": manifest["height"],
                **wire_controls,
            }
        except (KeyError, TypeError, ValueError) as exc:
            raise FalQueueError(
                status_code=400,
                phase="request_validation",
                endpoint=endpoint,
                detail=f"invalid frozen wire manifest ({type(exc).__name__})",
            ) from None
    payload: dict[str, Any] = {"prompt": prompt}
    size = params.get("size")
    if not size:
        width = params.get("canary_requested_width")
        height = params.get("canary_requested_height")
        if width and height:
            size = f"{width}x{height}"
    image_size = _image_size(
        size,
        exact_dimensions="gpt-image-2.5" in endpoint.lower(),
    )
    if image_size:
        payload["image_size"] = image_size
    n = params.get("n")
    if isinstance(n, int) and n > 0:
        payload["num_images"] = min(n, 6)
    elif isinstance(n, str) and n.isdigit():
        payload["num_images"] = min(int(n), 6)
    refs = [_data_uri(item) for item in images]
    refs = [ref for ref in refs if ref]
    if refs:
        payload["image_urls"] = refs
    endpoint_l = endpoint.lower()
    for key in (
        "background", "max_images", "output_compression", "output_format",
        "quality", "seed", "sync_mode", "enable_safety_checker",
    ):
        value = params.get(key)
        if isinstance(value, str | int | float | bool):
            payload[key] = value
    return payload


def _image_size(size: Any, *, exact_dimensions: bool = False) -> str | dict[str, int] | None:
    if not isinstance(size, str) or "x" not in size:
        return None
    try:
        width_s, height_s = size.lower().split("x", 1)
        width = int(width_s)
        height = int(height_s)
    except (TypeError, ValueError):
        return None
    # GPT Image 2.5 on fal accepts custom dimensions (multiples of 16), so
    # preserve the exact 4:5 style-proof and 2:3 page contracts.
    if exact_dimensions and width % 16 == 0 and height % 16 == 0 and width * height >= 655_360:
        return {"width": width, "height": height}
    if width < 1920 or height < 1920:
        ratio = width / max(height, 1)
        if 0.9 <= ratio <= 1.1:
            return "square"
        if 1.2 <= ratio <= 1.45:
            return "landscape_4_3"
        if 1.65 <= ratio <= 1.9:
            return "landscape_16_9"
        if 0.69 <= ratio <= 0.83:
            return "portrait_4_3"
        if 0.52 <= ratio <= 0.61:
            return "portrait_16_9"
        return "auto_2K"
    return {"width": width, "height": height}


def _data_uri(item: Any) -> str | None:
    if isinstance(item, str) and item.startswith(("data:", "http://", "https://")):
        return item
    filename = "image.png"
    mime = "image/png"
    data: bytes | None = None
    if isinstance(item, tuple):
        if len(item) >= 1 and item[0]:
            filename = str(item[0])
        if len(item) >= 2:
            data = _read_bytes(item[1])
        if len(item) >= 3 and item[2]:
            mime = str(item[2])
    else:
        name = getattr(item, "filename", None) or getattr(item, "name", None)
        if name:
            filename = Path(str(name)).name
        content_type = getattr(item, "content_type", None)
        if content_type:
            mime = str(content_type)
        data = _read_bytes(item)
    if data is None:
        return None
    guessed, _ = mimetypes.guess_type(filename)
    mime = guessed or mime or "image/png"
    b64 = base64.b64encode(data).decode("ascii")
    return f"data:{mime};base64,{b64}"


def _read_bytes(value: Any) -> bytes | None:
    if value is None:
        return None
    if isinstance(value, bytes):
        return value
    if isinstance(value, bytearray):
        return bytes(value)
    if isinstance(value, str):
        path = Path(value)
        if path.exists():
            return path.read_bytes()
        return value.encode("utf-8")
    reader = getattr(value, "read", None)
    if callable(reader):
        try:
            seeker = getattr(value, "seek", None)
            if callable(seeker):
                seeker(0)
            out = reader()
            if isinstance(out, str):
                return out.encode("utf-8")
            if isinstance(out, bytearray):
                return bytes(out)
            return out
        finally:
            seeker = getattr(value, "seek", None)
            if callable(seeker):
                seeker(0)
    return None


def _headers(api_key: str | None) -> dict[str, str]:
    key = (api_key or os.environ.get("FAL_KEY") or "").strip()
    if not key:
        raise ValueError("FAL_KEY is not set")
    return {
        "Authorization": f"Key {key}",
        "Content-Type": "application/json",
    }


async def _submit(client: httpx.AsyncClient, endpoint: str, payload: dict[str, Any], api_key: str | None) -> dict[str, str]:
    try:
        response = await client.post(
            f"{FAL_QUEUE_BASE}/{endpoint}",
            headers=_headers(api_key),
            json=payload,
        )
    except (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout) as exc:
        # No HTTP connection was established, so FAL cannot have accepted a
        # paid request. Distinguish this from a lost response after submission.
        logger.exception("FAL queue submit could not connect endpoint=%s", endpoint)
        raise FalQueueError(
            status_code=503,
            phase="submit_connect",
            endpoint=endpoint,
            detail=type(exc).__name__,
        ) from None
    except httpx.RequestError:
        logger.exception("FAL queue submit transport error endpoint=%s", endpoint)
        raise
    if response.status_code >= 400:
        detail = _response_detail(response)
        logger.error(
            "FAL queue submit rejected endpoint=%s status=%s detail=%s",
            endpoint,
            response.status_code,
            detail or "<none>",
        )
        raise FalQueueError(
            status_code=response.status_code,
            phase="submit",
            endpoint=endpoint,
            detail=detail,
        )
    try:
        data = response.json()
    except (TypeError, ValueError) as exc:
        raise FalQueueError(
            status_code=502,
            phase="submit_response",
            endpoint=endpoint,
            detail=f"invalid JSON ({type(exc).__name__})",
        ) from None
    if not isinstance(data, dict):
        raise FalQueueError(
            status_code=502,
            phase="submit_response",
            endpoint=endpoint,
            detail=f"expected object, got {type(data).__name__}",
        )
    request_id = data.get("request_id")
    status_url = data.get("status_url")
    response_url = data.get("response_url")
    if not request_id or not status_url or not response_url:
        raise FalQueueError(
            status_code=502,
            phase="submit_response",
            endpoint=endpoint,
            detail=f"missing queue fields; response_keys={sorted(data)}",
        )
    return {
        "request_id": request_id,
        "status_url": status_url,
        "response_url": response_url,
    }


async def _poll(
    client: httpx.AsyncClient,
    status_url: str,
    request_id: str,
    api_key: str | None,
    *,
    endpoint: str = "<unknown>",
) -> None:
    deadline = time.monotonic() + POLL_TIMEOUT_S
    last_status: str | None = None
    while time.monotonic() < deadline:
        response = await _get_with_retry(
            client,
            status_url,
            headers=_headers(api_key),
            phase="status",
            endpoint=endpoint,
            request_id=request_id,
        )
        if response.status_code >= 400:
            raise FalQueueError(
                status_code=response.status_code,
                phase="status",
                endpoint=endpoint,
                request_id=request_id,
                detail=_response_detail(response),
            )
        try:
            data = response.json()
        except (TypeError, ValueError) as exc:
            raise FalQueueError(
                status_code=502,
                phase="status_response",
                endpoint=endpoint,
                request_id=request_id,
                detail=f"invalid JSON ({type(exc).__name__})",
            ) from None
        if not isinstance(data, dict):
            raise FalQueueError(
                status_code=502,
                phase="status_response",
                endpoint=endpoint,
                request_id=request_id,
                detail=f"expected object, got {type(data).__name__}",
            )
        status = (data.get("status") or "").upper()
        if status != last_status:
            logger.info(
                "FAL image request status endpoint=%s request_id=%s status=%s",
                endpoint,
                request_id,
                status or "UNKNOWN",
            )
            last_status = status
        if status == "COMPLETED":
            return
        if status in {"FAILED", "CANCELLED", "ERROR"}:
            detail = _safe_payload_detail(data)
            logger.error(
                "FAL image request ended endpoint=%s request_id=%s status=%s detail=%s",
                endpoint,
                request_id,
                status,
                detail or "<none>",
            )
            raise FalQueueError(
                status_code=502,
                phase=f"request_{status.lower()}",
                endpoint=endpoint,
                request_id=request_id,
                detail=detail,
            )
        await asyncio.sleep(POLL_INTERVAL_S)
    raise FalQueueError(
        status_code=504,
        phase="poll_timeout",
        endpoint=endpoint,
        request_id=request_id,
        detail=f"exceeded {POLL_TIMEOUT_S:.0f}s",
    )


async def _fetch_result(
    client: httpx.AsyncClient,
    response_url: str,
    api_key: str | None,
    *,
    endpoint: str = "<unknown>",
    request_id: str = "<unknown>",
) -> dict[str, Any]:
    response = await _get_with_retry(
        client,
        response_url,
        headers=_headers(api_key),
        phase="result",
        endpoint=endpoint,
        request_id=request_id,
    )
    if response.status_code >= 400:
        raise FalQueueError(
            status_code=response.status_code,
            phase="result",
            endpoint=endpoint,
            request_id=request_id,
            detail=_response_detail(response),
        )
    try:
        data = response.json()
    except (TypeError, ValueError) as exc:
        raise FalQueueError(
            status_code=502,
            phase="result_response",
            endpoint=endpoint,
            request_id=request_id,
            detail=f"invalid JSON ({type(exc).__name__})",
        ) from None
    if not isinstance(data, dict):
        raise FalQueueError(
            status_code=502,
            phase="result_response",
            endpoint=endpoint,
            request_id=request_id,
            detail=f"expected object, got {type(data).__name__}",
        )
    return data


def _extract_image_url(
    result: dict[str, Any], *, endpoint: str = "<unknown>", request_id: str = "<unknown>"
) -> str:
    if isinstance(result.get("data"), dict):
        result = result["data"]
    images = result.get("images") or result.get("image") or []
    if isinstance(images, dict):
        images = [images]
    if not images:
        raise FalQueueError(
            status_code=502,
            phase="result_response",
            endpoint=endpoint,
            request_id=request_id,
            detail=f"no images; response_keys={sorted(result)}",
        )
    first = images[0]
    if isinstance(first, str):
        return first
    url = first.get("url") if isinstance(first, dict) else None
    if not url:
        raise FalQueueError(
            status_code=502,
            phase="result_response",
            endpoint=endpoint,
            request_id=request_id,
            detail=f"image entry missing url; entry_type={type(first).__name__}",
        )
    return url


async def _download(
    client: httpx.AsyncClient,
    url: str,
    *,
    endpoint: str = "<unknown>",
    request_id: str = "<unknown>",
) -> bytes:
    if url.startswith("data:"):
        try:
            header, encoded = url.split(",", 1)
            if ";base64" not in header.lower():
                from urllib.parse import unquote_to_bytes

                return unquote_to_bytes(encoded)
            return base64.b64decode(encoded, validate=True)
        except (ValueError, binascii.Error) as exc:
            raise FalQueueError(
                status_code=502,
                phase="download",
                endpoint=endpoint,
                request_id=request_id,
                detail=f"invalid data URI ({type(exc).__name__})",
            ) from None
    response = await _get_with_retry(
        client,
        url,
        phase="download",
        endpoint=endpoint,
        request_id=request_id,
    )
    if response.status_code >= 400:
        raise FalQueueError(
            status_code=response.status_code,
            phase="download",
            endpoint=endpoint,
            request_id=request_id,
            detail=_response_detail(response),
        )
    return response.content


async def _get_with_retry(
    client: httpx.AsyncClient,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    phase: str,
    endpoint: str,
    request_id: str,
) -> httpx.Response:
    """Retry only idempotent queue/status/result reads after submission."""
    for attempt in range(GET_RETRY_COUNT + 1):
        try:
            response = await client.get(url, headers=headers)
        except httpx.RequestError as exc:
            if attempt >= GET_RETRY_COUNT:
                logger.error(
                    "FAL %s transport failed endpoint=%s request_id=%s attempts=%d error=%s",
                    phase,
                    endpoint,
                    request_id,
                    attempt + 1,
                    type(exc).__name__,
                )
                raise
            logger.warning(
                "FAL %s transport retry endpoint=%s request_id=%s attempt=%d/%d error=%s",
                phase,
                endpoint,
                request_id,
                attempt + 1,
                GET_RETRY_COUNT + 1,
                type(exc).__name__,
            )
            await asyncio.sleep(1.0)
            continue
        if (
            response.status_code not in GET_RETRYABLE_STATUS_CODES
            or attempt >= GET_RETRY_COUNT
        ):
            return response
        logger.warning(
            "FAL %s HTTP retry endpoint=%s request_id=%s status=%s attempt=%d/%d",
            phase,
            endpoint,
            request_id,
            response.status_code,
            attempt + 1,
            GET_RETRY_COUNT + 1,
        )
        await asyncio.sleep(1.0)
    raise AssertionError("FAL GET retry loop exhausted without a response")


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
        for key in ("code", "type", "status", "message", "detail", "reason"):
            value = error.get(key)
            if value is not None:
                values.append(f"{key}={_redact_text(str(value))}")
    elif error is not None:
        values.append(f"error={_redact_text(str(error))}")
    for key in ("code", "type", "message", "detail", "reason"):
        value = payload.get(key)
        if value is not None and not (key == "error" and error is not None):
            values.append(f"{key}={_redact_text(str(value))}")
    return "; ".join(values)[:600] or None


def _redact_text(value: str) -> str:
    text = " ".join(value.split())
    text = _URI_RE.sub("<redacted-uri>", text)
    return text[:400]


fal_queue_llm = FalQueueLLM()
