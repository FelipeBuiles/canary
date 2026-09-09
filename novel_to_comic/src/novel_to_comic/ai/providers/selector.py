"""Image provider selection."""

from __future__ import annotations

from novel_to_comic.ai.providers.base import ImageProvider
from novel_to_comic.ai.providers.litellm_http import LitellmHttpProvider
from novel_to_comic.config import Config, mock_mode_active
from novel_to_comic.codex_dev import route_for
from novel_to_comic.provider_wire import ProviderWireError


def pick(model_alias: str, config: Config, *, provider_key: str) -> ImageProvider:
    """Pick the provider for one Style or Cast image request."""
    if config.mock_mode and not mock_mode_active(config):
        raise RuntimeError(
            "mock_mode is enabled but CANARY_MOCK_GENERATIONS_ENABLED is not; "
            "refusing to route an image request to a paid provider"
        )
    route = route_for("image", model_alias)
    if provider_key == "codex-dev":
        if route is None or config.mock_mode:
            raise ProviderWireError("Codex image wire requires an enabled, non-mock process route")
        from novel_to_comic.ai.providers.codex_dev import CodexDevImageProvider

        return CodexDevImageProvider()
    if route is not None:
        raise ProviderWireError("frozen API image wire cannot be redirected to Codex")
    return LitellmHttpProvider()
