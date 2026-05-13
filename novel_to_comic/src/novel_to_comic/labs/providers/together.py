"""together.ai provider for labs experiments.

Uses the OpenAI-compatible images endpoint.
"""

from __future__ import annotations

import asyncio
import base64
import logging
import os
import time
from typing import Any

import httpx

from .base import LabsImageInput, LabsImageResult, ProviderError

# 429 retry policy — together's "request rate limiting" surfaces both as
# transient bursts (worth retrying) and account-tier denials (`0 TPM`)
# which will keep failing. We retry a small number of times so legitimate
# burst-throttling clears on its own without making tier-denials painful.
RETRY_429_ATTEMPTS = 3
RETRY_429_BACKOFF_S = (3.0, 8.0)

log = logging.getLogger(__name__)

TOGETHER_BASE = "https://api.together.xyz/v1"
TOGETHER_KEY_ENV = "TOGETHER_API_KEY"


def _headers() -> dict[str, str]:
    key = os.environ.get(TOGETHER_KEY_ENV, "").strip()
    if not key:
        raise ProviderError(
            f"{TOGETHER_KEY_ENV} is not set — add it to your environment to use together.ai providers."
        )
    return {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }


class TogetherProvider:
    name = "together"

    async def generate(
        self,
        *,
        endpoint: str,
        inp: LabsImageInput,
        params: dict[str, Any] | None = None,
    ) -> LabsImageResult:
        body: dict[str, Any] = {
            "model": endpoint,
            "prompt": inp.composed_prompt(),
            "width": inp.width,
            "height": inp.height,
            "n": 1,
            "response_format": "b64_json",
        }
        body.update(params or {})

        started = time.perf_counter()
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = None
            for attempt in range(RETRY_429_ATTEMPTS):
                response = await client.post(
                    f"{TOGETHER_BASE}/images/generations",
                    headers=_headers(),
                    json=body,
                )
                if response.status_code != 429:
                    break
                if attempt == RETRY_429_ATTEMPTS - 1:
                    break
                # Back off; honour Retry-After if provided, otherwise use defaults.
                retry_after = response.headers.get("retry-after")
                try:
                    delay = float(retry_after) if retry_after else RETRY_429_BACKOFF_S[min(attempt, len(RETRY_429_BACKOFF_S) - 1)]
                except ValueError:
                    delay = RETRY_429_BACKOFF_S[min(attempt, len(RETRY_429_BACKOFF_S) - 1)]
                log.info("together rate-limited, retrying in %.1fs (attempt %d/%d)", delay, attempt + 1, RETRY_429_ATTEMPTS)
                await asyncio.sleep(delay)
            assert response is not None
            if response.status_code >= 400:
                raise ProviderError(
                    f"together.ai {endpoint} failed ({response.status_code}): {response.text[:400]}"
                )
            data = response.json()
        latency = int((time.perf_counter() - started) * 1000)

        images = data.get("data") or []
        if not images:
            raise ProviderError(f"together.ai response had no images: {data}")
        first = images[0]
        b64 = first.get("b64_json")
        url = first.get("url")
        if b64:
            image_bytes = base64.b64decode(b64)
        elif url:
            async with httpx.AsyncClient(timeout=60.0) as client:
                fetched = await client.get(url)
                if fetched.status_code >= 400:
                    raise ProviderError(f"together image download failed: {fetched.status_code}")
                image_bytes = fetched.content
        else:
            raise ProviderError(f"together image entry missing b64_json and url: {first}")

        return LabsImageResult(
            image_bytes=image_bytes,
            mime="image/png",
            latency_ms=latency,
            cost_usd=None,
            provider_model=endpoint,
            provider_request_id=str(data.get("id") or ""),
            raw_response={k: v for k, v in data.items() if k != "data"},
        )
