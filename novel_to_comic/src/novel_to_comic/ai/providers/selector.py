"""Image provider selection."""

from __future__ import annotations

from novel_to_comic.ai.providers.base import ImageProvider
from novel_to_comic.ai.providers.litellm_http import LitellmHttpProvider
from novel_to_comic.config import Config, mock_mode_active


def pick(model_alias: str, config: Config) -> ImageProvider:
    """Pick the provider for one Style or Cast image request."""
    if config.mock_mode and not mock_mode_active(config):
        raise RuntimeError(
            "mock_mode is enabled but CANARY_MOCK_GENERATIONS_ENABLED is not; "
            "refusing to route an image request to a paid provider"
        )
    if config.mock_mode:
        return LitellmHttpProvider()
    return LitellmHttpProvider()
