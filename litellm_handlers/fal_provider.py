"""LiteLLM custom provider for fal.ai queue image-edit endpoints."""

from __future__ import annotations

import asyncio
import base64
import mimetypes
import os
import time
from pathlib import Path
from typing import Any

import httpx
from litellm.llms.custom_llm import CustomLLM
from litellm.types.utils import ImageObject, ImageResponse

FAL_QUEUE_BASE = "https://queue.fal.run"
POLL_INTERVAL_S = 1.5
POLL_TIMEOUT_S = 300.0


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
        endpoint = _fal_endpoint(model)
        payload = _build_payload(endpoint, prompt or "", image, optional_params)
        request_timeout = timeout if timeout is not None else 300.0
        async with httpx.AsyncClient(timeout=request_timeout) as http:
            urls = await _submit(http, endpoint, payload, api_key)
            await _poll(http, urls["status_url"], urls["request_id"], api_key)
            full = await _fetch_result(http, urls["response_url"], api_key)
            image_url = _extract_image_url(full)
            image_bytes = await _download(http, image_url)
        b64 = base64.b64encode(image_bytes).decode("ascii")
        model_response.created = int(time.time())
        model_response.data = [ImageObject(b64_json=b64)]
        model_response._hidden_params["model"] = f"fal-ai/{endpoint}"
        model_response._hidden_params["custom_llm_provider"] = "fal-queue"
        model_response._hidden_params["response_cost"] = None
        return model_response


def _fal_endpoint(model: str) -> str:
    cleaned = (model or "").strip().strip("/")
    if cleaned.startswith("fal-ai/"):
        return cleaned
    return f"fal-ai/{cleaned}"


def _build_payload(endpoint: str, prompt: str, images: list[Any], params: dict[str, Any]) -> dict[str, Any]:
    payload: dict[str, Any] = {"prompt": prompt}
    size = params.get("size")
    image_size = _image_size(size)
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
    if "seedream" in endpoint_l or "nano-banana" in endpoint_l or "flux-2" in endpoint_l:
        payload["image_urls"] = refs
    for key in ("max_images", "seed", "sync_mode", "enable_safety_checker"):
        value = params.get(key)
        if isinstance(value, str | int | float | bool):
            payload[key] = value
    return payload


def _image_size(size: Any) -> str | dict[str, int] | None:
    if not isinstance(size, str) or "x" not in size:
        return None
    try:
        width_s, height_s = size.lower().split("x", 1)
        width = int(width_s)
        height = int(height_s)
    except (TypeError, ValueError):
        return None
    # Seedream rejects small custom dimensions. Preserve aspect intent through
    # fal's supported presets instead of forwarding LiteLLM's 1024x1024 default.
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
    response = await client.post(f"{FAL_QUEUE_BASE}/{endpoint}", headers=_headers(api_key), json=payload)
    if response.status_code >= 400:
        raise ValueError(f"fal submit failed ({response.status_code}): {response.text[:600]}")
    data = response.json()
    request_id = data.get("request_id")
    status_url = data.get("status_url")
    response_url = data.get("response_url")
    if not request_id or not status_url or not response_url:
        raise ValueError(f"fal submit missing request_id/status_url/response_url: {data}")
    return {
        "request_id": request_id,
        "status_url": status_url,
        "response_url": response_url,
    }


async def _poll(client: httpx.AsyncClient, status_url: str, request_id: str, api_key: str | None) -> None:
    deadline = time.monotonic() + POLL_TIMEOUT_S
    while time.monotonic() < deadline:
        response = await client.get(status_url, headers=_headers(api_key))
        if response.status_code >= 400:
            raise ValueError(f"fal status failed ({response.status_code}): {response.text[:600]}")
        data = response.json()
        status = (data.get("status") or "").upper()
        if status == "COMPLETED":
            return
        if status in {"FAILED", "CANCELLED", "ERROR"}:
            raise ValueError(f"fal request {request_id} ended {status}: {data}")
        await asyncio.sleep(POLL_INTERVAL_S)
    raise TimeoutError(f"fal request {request_id} timed out after {POLL_TIMEOUT_S:.0f}s")


async def _fetch_result(client: httpx.AsyncClient, response_url: str, api_key: str | None) -> dict[str, Any]:
    response = await client.get(response_url, headers=_headers(api_key))
    if response.status_code >= 400:
        raise ValueError(f"fal result fetch failed ({response.status_code}): {response.text[:600]}")
    return response.json()


def _extract_image_url(result: dict[str, Any]) -> str:
    images = result.get("images") or result.get("image") or []
    if isinstance(images, dict):
        images = [images]
    if not images:
        raise ValueError(f"fal result has no images: {result}")
    first = images[0]
    if isinstance(first, str):
        return first
    url = first.get("url") if isinstance(first, dict) else None
    if not url:
        raise ValueError(f"fal image entry missing url: {first}")
    return url


async def _download(client: httpx.AsyncClient, url: str) -> bytes:
    response = await client.get(url)
    if response.status_code >= 400:
        raise ValueError(f"fal image download failed ({response.status_code}): {response.text[:300]}")
    return response.content


fal_queue_llm = FalQueueLLM()
