"""Shared types for labs image providers."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol


class ProviderError(RuntimeError):
    """Raised when a provider fails to produce an image."""


@dataclass
class LabsImageInput:
    """Single image generation request input.

    `reference_image_paths` are absolute paths to local files. Providers that
    require URLs are responsible for converting (e.g., to data URIs).
    `style_template` is treated as a pre-prepended preamble — providers may
    incorporate it as part of the prompt.
    """

    prompt: str
    style_template: str = ""
    width: int = 1024
    height: int = 1024
    reference_image_paths: list[Path] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)

    def composed_prompt(self) -> str:
        """Combine style template and per-panel prompt for providers that take a single string."""
        style = (self.style_template or "").strip()
        body = (self.prompt or "").strip()
        if style and body:
            return f"Style: {style}\n\n{body}"
        return body or style


@dataclass
class LabsImageResult:
    """Output of a single image generation."""

    image_bytes: bytes
    mime: str = "image/png"
    latency_ms: int = 0
    cost_usd: float | None = None
    cost_source: str | None = None
    provider_model: str | None = None
    provider_request_id: str | None = None
    raw_response: dict[str, Any] | None = None


class LabsProvider(Protocol):
    """Async interface that every labs provider implements."""

    name: str

    async def generate(
        self,
        *,
        endpoint: str,
        inp: LabsImageInput,
        params: dict[str, Any] | None = None,
    ) -> LabsImageResult: ...
