"""Shared image provider types."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Protocol

import httpx

from novel_to_comic.config import Config

RefRole = Literal["subject", "style", "continuity", "location_plate", "prop"]

# Canonical upload order for reference images. Subject refs go first so
# character identity gets the strongest positional weight; contextual refs
# (style sample, location plate) come last. Every consumer of a RefImage list
# — ref selection in s7_draw, multipart upload in litellm_http, and the
# <img>N</img> index rendering in prompting.render_generation_prompt — MUST
# derive ordering from order_refs_for_upload so prompt indices always match
# the uploaded files.
UPLOAD_REF_PRIORITY: dict[str, int] = {
    "subject": 0,
    "prop": 1,
    "continuity": 2,
    "style": 3,
    "location_plate": 4,
}


@dataclass(frozen=True)
class RefImage:
    path: Path
    role: RefRole
    label: str | None = None


def order_refs_for_upload(refs: list[RefImage]) -> list[RefImage]:
    """Return refs in the canonical upload order (stable within each role)."""
    return sorted(refs, key=lambda ref: UPLOAD_REF_PRIORITY.get(ref.role, 99))


@dataclass
class ProviderRawResult:
    image_bytes: bytes
    mime: str = "image/png"
    latency_ms: int = 0
    provider_request_id: str | None = None
    raw_response: dict[str, Any] | None = None
    response_headers: httpx.Headers | None = None
    provider_cost_usd: float | None = None
    request_params: dict[str, Any] | None = None


class ImageProvider(Protocol):
    name: str

    def request_params(
        self,
        *,
        model_alias: str,
        width: int,
        height: int,
        config: Config,
    ) -> dict[str, Any]: ...

    async def generate(
        self,
        *,
        model_alias: str,
        prompt: str,
        refs: list[RefImage],
        width: int,
        height: int,
        params: dict[str, Any] | None,
        config: Config,
        event_id: str,
        metadata: dict[str, Any],
    ) -> ProviderRawResult: ...
