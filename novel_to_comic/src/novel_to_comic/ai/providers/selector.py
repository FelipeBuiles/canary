"""Image provider selection."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from novel_to_comic.ai.providers.base import ImageProvider
from novel_to_comic.ai.providers.litellm_http import LitellmHttpProvider
from novel_to_comic.ai.providers.reve_layout import ReveLayoutProvider
from novel_to_comic.config import Config, is_reve_model, mock_mode_active


def pick(model_alias: str, config: Config, layout: Any | None = None) -> ImageProvider:  # noqa: ARG001
    """Pick the provider for one image request.

    Layout-aware requests on Reve bypass the LiteLLM gateway: the gateway's
    OpenAI-compatible image endpoints cannot carry the compound-reference
    ``render_layout`` request or return its layout echo. Everything else —
    including flat Reve generation — goes through the gateway.
    """
    if config.mock_mode and not mock_mode_active(config):
        raise RuntimeError(
            "mock_mode is enabled but CANARY_MOCK_GENERATIONS_ENABLED is not; "
            "refusing to route an image request to a paid provider"
        )
    if config.mock_mode:
        return LitellmHttpProvider()
    regions = (
        layout.get("regions")
        if isinstance(layout, Mapping)
        else getattr(layout, "regions", None)
    )
    if regions and is_reve_model(model_alias):
        return ReveLayoutProvider()
    return LitellmHttpProvider()
