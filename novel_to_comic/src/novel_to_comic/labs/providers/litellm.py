"""LiteLLM-backed provider — reuses the existing pipeline image client.

Lets us register the production models (gemini-3-flash, gemini-3-pro,
gpt-image-2) in the labs registry so they can be A/B'd against new
candidates without duplicating the generation code.
"""

from __future__ import annotations

import logging
import os
import tempfile
import time
from pathlib import Path
from typing import Any

import httpx

from novel_to_comic.ai import generate_image as ai_generate_image
from novel_to_comic.ai.providers.base import RefImage, RefRole
from novel_to_comic.config import _ENV_KEYS, Config
from novel_to_comic.usage import calculate_cost_breakdown

from .base import LabsImageInput, LabsImageResult, ProviderError

log = logging.getLogger(__name__)


def _infer_ref_role(path: Path) -> RefRole:
    """Infer a reference image's role from its filename when no explicit role is available."""
    stem = path.stem.lower()
    if any(stem.startswith(p) for p in ("loc_", "location_", "setting_", "plate_")):
        return "location_plate"
    if any(stem.startswith(p) for p in ("style_", "art_style_", "art_")):
        return "style"
    if stem.startswith("prop_"):
        return "prop"
    if stem.startswith("panel_") and stem[len("panel_"):].isdigit():
        return "continuity"
    return "subject"


def _config_for_model(endpoint: str) -> Config:
    """Build a Config pointed at the requested gateway alias.

    We bypass the project config so the labs page is independent of any
    project's settings, but still pick up gateway credentials from the shell
    environment — otherwise LiteLLM rejects the unauthenticated request with
    a 400 "no_db_connection".
    """
    overlay: dict[str, Any] = {}
    for env_name, field_name in _ENV_KEYS.items():
        val = os.environ.get(env_name, "").strip()
        if val:
            overlay[field_name] = val
    overlay["image_model"] = endpoint
    return Config(**overlay)


class LitellmProvider:
    name = "litellm"

    async def generate(
        self,
        *,
        endpoint: str,
        inp: LabsImageInput,
        params: dict[str, Any] | None = None,
    ) -> LabsImageResult:
        config = _config_for_model(endpoint)
        params = params or {}

        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            output_path = Path(tmp.name)

        started = time.perf_counter()
        try:
            result = await ai_generate_image(
                config=config,
                model=endpoint,
                prompt=inp.composed_prompt(),
                output_path=output_path,
                width=inp.width,
                height=inp.height,
                steps=None,
                refs=[RefImage(path=p, role=_infer_ref_role(p)) for p in inp.reference_image_paths],
                feature="labs.generate",
            )
        except httpx.HTTPStatusError as exc:
            output_path.unlink(missing_ok=True)
            body = ""
            if exc.response is not None:
                try:
                    body = exc.response.text[:600]
                except Exception:
                    body = "<unreadable response body>"
            raise ProviderError(
                f"litellm {endpoint} returned {exc.response.status_code if exc.response else '?'}: {body or exc}"
            ) from exc
        except Exception as exc:
            output_path.unlink(missing_ok=True)
            # Some failures bubble up through helpers that wrap the original
            # HTTPStatusError — try to dig the response body out of the cause chain.
            body = ""
            cause: BaseException | None = exc
            while cause is not None:
                response = getattr(cause, "response", None)
                if isinstance(response, httpx.Response):
                    try:
                        body = response.text[:600]
                    except Exception:
                        body = "<unreadable response body>"
                    break
                cause = cause.__cause__
            detail = f": {body}" if body else ""
            raise ProviderError(f"litellm {endpoint} failed: {exc}{detail}") from exc

        image_bytes = output_path.read_bytes()
        output_path.unlink(missing_ok=True)
        latency = int((time.perf_counter() - started) * 1000)

        cost_usd: float | None = None
        cost_source: str | None = None
        provider_model: str | None = None
        usage = getattr(result, "usage", None)
        if usage is not None:
            breakdown = calculate_cost_breakdown(usage)
            cost_usd = breakdown.cost_usd
            cost_source = breakdown.source
            provider_model = breakdown.provider_model

        return LabsImageResult(
            image_bytes=image_bytes,
            mime="image/png",
            latency_ms=latency,
            cost_usd=cost_usd,
            cost_source=cost_source,
            provider_model=provider_model,
            provider_request_id=None,
            raw_response=None,
        )
