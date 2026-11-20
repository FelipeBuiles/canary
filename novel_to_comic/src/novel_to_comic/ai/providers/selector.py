"""Image provider selection."""

from __future__ import annotations

from typing import TYPE_CHECKING

from novel_to_comic.config import Config, mock_mode_active
from novel_to_comic.codex_dev import route_for
from novel_to_comic.provider_wire import ProviderWireError

if TYPE_CHECKING:
    from novel_to_comic.ai.providers.codex_dev import CodexDevImageProvider

CODEX_PROVIDER_KEY = "codex-dev"


def codex_provider(model_alias: str, config: Config) -> "CodexDevImageProvider":
    """The Codex provider for a Style or Cast wire frozen to Codex."""
    _refuse_unsafe_mock(config)
    if route_for("image", model_alias) is None or config.mock_mode:
        raise ProviderWireError("Codex image wire requires an enabled, non-mock process route")
    from novel_to_comic.ai.providers.codex_dev import CodexDevImageProvider

    return CodexDevImageProvider()


def require_gateway_route(model_alias: str, config: Config) -> None:
    """Refuse to send a Style or Cast wire frozen to the API anywhere else."""
    _refuse_unsafe_mock(config)
    if route_for("image", model_alias) is not None:
        raise ProviderWireError("frozen API image wire cannot be redirected to Codex")


def _refuse_unsafe_mock(config: Config) -> None:
    if config.mock_mode and not mock_mode_active(config):
        raise RuntimeError(
            "mock_mode is enabled but CANARY_MOCK_GENERATIONS_ENABLED is not; "
            "refusing to route an image request to a paid provider"
        )
