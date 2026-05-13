"""fal.ai provider for labs experiments.

Uses fal's queue API (https://queue.fal.run) over plain HTTP — no fal_client
dependency. Reference images are sent inline as data URIs so we do not need
fal's storage service.
"""

from __future__ import annotations

import asyncio
import base64
import logging
import mimetypes
import os
import time
from pathlib import Path
from typing import Any

import httpx

from .base import LabsImageInput, LabsImageResult, ProviderError

log = logging.getLogger(__name__)

FAL_QUEUE_BASE = "https://queue.fal.run"
FAL_KEY_ENV = "FAL_KEY"
POLL_INTERVAL_S = 1.5
POLL_TIMEOUT_S = 300.0


def _data_uri(path: Path) -> str:
    mime, _ = mimetypes.guess_type(path.name)
    mime = mime or "image/png"
    b64 = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{b64}"


def _headers() -> dict[str, str]:
    key = os.environ.get(FAL_KEY_ENV, "").strip()
    if not key:
        raise ProviderError(
            f"{FAL_KEY_ENV} is not set — add it to your environment to use fal.ai providers."
        )
    return {
        "Authorization": f"Key {key}",
        "Content-Type": "application/json",
    }


def _build_payload(endpoint: str, inp: LabsImageInput, params: dict[str, Any]) -> dict[str, Any]:
    """Build a payload tailored to the endpoint shape.

    fal endpoints share family conventions: most take `prompt`, `image_size`
    or `width`/`height`, and accept `image_urls` (multi) or `image_url`
    (single). We normalise to the common subset; per-endpoint overrides can
    flow through `params`.
    """
    prompt = inp.composed_prompt()
    refs = [_data_uri(p) for p in inp.reference_image_paths if p and p.exists()]

    payload: dict[str, Any] = {"prompt": prompt}
    payload["image_size"] = {"width": inp.width, "height": inp.height}

    if refs:
        endpoint_l = endpoint.lower()
        if endpoint_l.endswith("/multi") or "kontext/max/multi" in endpoint_l:
            payload["image_urls"] = refs
        elif "seedream" in endpoint_l or "nano-banana" in endpoint_l or "flux-2" in endpoint_l:
            payload["image_urls"] = refs
        else:
            payload["image_url"] = refs[0]

    payload.update(params or {})
    return payload


async def _submit(client: httpx.AsyncClient, endpoint: str, payload: dict[str, Any]) -> dict[str, str]:
    """Submit a queue request. Returns the URLs fal hands back for polling and fetching.

    fal's response contains `status_url` and `response_url` already pointing at the
    correct app prefix — for compound endpoints like
    `fal-ai/flux-pro/kontext/max/multi`, those URLs use only the `fal-ai/flux-pro`
    app segment, which is impossible to derive deterministically from the endpoint
    string. Always use the URLs from the response.
    """
    url = f"{FAL_QUEUE_BASE}/{endpoint}"
    response = await client.post(url, headers=_headers(), json=payload, timeout=60.0)
    if response.status_code >= 400:
        raise ProviderError(f"fal submit failed ({response.status_code}): {response.text[:400]}")
    data = response.json()
    request_id = data.get("request_id")
    status_url = data.get("status_url")
    response_url = data.get("response_url")
    if not request_id or not status_url or not response_url:
        raise ProviderError(f"fal submit missing request_id/status_url/response_url: {data}")
    return {
        "request_id": request_id,
        "status_url": status_url,
        "response_url": response_url,
    }


async def _poll(client: httpx.AsyncClient, status_url: str, request_id: str) -> dict[str, Any]:
    deadline = time.monotonic() + POLL_TIMEOUT_S
    while time.monotonic() < deadline:
        response = await client.get(status_url, headers=_headers(), timeout=30.0)
        if response.status_code >= 400:
            raise ProviderError(f"fal status failed ({response.status_code}): {response.text[:400]}")
        data = response.json()
        status = (data.get("status") or "").upper()
        if status == "COMPLETED":
            return data
        if status in ("FAILED", "CANCELLED", "ERROR"):
            raise ProviderError(f"fal request {request_id} ended {status}: {data}")
        await asyncio.sleep(POLL_INTERVAL_S)
    raise ProviderError(f"fal request {request_id} timed out after {POLL_TIMEOUT_S:.0f}s")


async def _fetch_result(client: httpx.AsyncClient, response_url: str) -> dict[str, Any]:
    response = await client.get(response_url, headers=_headers(), timeout=30.0)
    if response.status_code >= 400:
        raise ProviderError(f"fal result fetch failed ({response.status_code}): {response.text[:400]}")
    return response.json()


def _extract_image_url(result: dict[str, Any]) -> str:
    images = result.get("images") or result.get("image") or []
    if isinstance(images, dict):
        images = [images]
    if not images:
        raise ProviderError(f"fal result has no images: {result}")
    first = images[0]
    if isinstance(first, str):
        return first
    url = first.get("url") if isinstance(first, dict) else None
    if not url:
        raise ProviderError(f"fal image entry missing url: {first}")
    return url


async def _download(client: httpx.AsyncClient, url: str) -> tuple[bytes, str]:
    response = await client.get(url, timeout=60.0)
    if response.status_code >= 400:
        raise ProviderError(f"fal image download failed ({response.status_code}): {response.text[:200]}")
    mime = response.headers.get("content-type", "image/png").split(";")[0].strip() or "image/png"
    return response.content, mime


class FalProvider:
    name = "fal"

    async def generate(
        self,
        *,
        endpoint: str,
        inp: LabsImageInput,
        params: dict[str, Any] | None = None,
    ) -> LabsImageResult:
        started = time.perf_counter()
        payload = _build_payload(endpoint, inp, params or {})
        async with httpx.AsyncClient() as client:
            urls = await _submit(client, endpoint, payload)
            await _poll(client, urls["status_url"], urls["request_id"])
            full = await _fetch_result(client, urls["response_url"])
            image_url = _extract_image_url(full)
            image_bytes, mime = await _download(client, image_url)
        latency = int((time.perf_counter() - started) * 1000)
        return LabsImageResult(
            image_bytes=image_bytes,
            mime=mime,
            latency_ms=latency,
            cost_usd=None,
            provider_model=endpoint,
            provider_request_id=urls["request_id"],
            raw_response={k: v for k, v in full.items() if k != "images"},
        )
