"""Shared image provider types."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Protocol

import httpx

from novel_to_comic.config import Config

RefRole = Literal["subject", "style", "continuity", "location_plate", "prop"]


@dataclass(frozen=True)
class RefImage:
    path: Path
    role: RefRole
    label: str | None = None


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
