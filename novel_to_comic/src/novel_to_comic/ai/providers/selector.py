"""Image provider selection."""

from __future__ import annotations

from novel_to_comic.ai.providers.base import ImageProvider
from novel_to_comic.ai.providers.litellm_http import LitellmHttpProvider
from novel_to_comic.config import Config


def pick(model_alias: str, config: Config) -> ImageProvider:  # noqa: ARG001
    return LitellmHttpProvider()
