"""Text generation compatibility wrapper.

Runtime calls go through the internal LiteLLM-backed AI client. MODEL_REGISTRY
is retained for pricing audits and legacy model metadata during the migration.
"""

from __future__ import annotations

from collections.abc import Callable

from novel_to_comic.config import Config
from novel_to_comic.text_models import TEXT_MODELS
from novel_to_comic.usage import ApiResult
from novel_to_comic.ai import (
    generate_structured_object,
    generate_text as ai_generate_text,
)

# Derived from the selectable catalog; add models in text_models.py.
MODEL_REGISTRY: dict[str, str] = {model.id: model.provider_key for model in TEXT_MODELS}


def provider_for_model(model: str) -> str:
    """Return the provider for a known model, or raise."""
    provider = MODEL_REGISTRY.get(model)
    if provider is not None:
        return provider
    raise ValueError(
        f"Unknown text model {model!r}. "
        f"Add it to TEXT_MODELS in text_models.py with its provider."
    )


async def generate_json(
    config: Config,
    model: str,
    system_prompt: str,
    user_content: str | bytes,
    temperature: float = 0.7,
    max_output_tokens: int | None = None,
    json_schema: dict | None = None,
    feature: str = "text.generate_json",
    image_attachments: tuple[tuple[bytes, str], ...] = (),
    response_sink: Callable[[ApiResult[str]], None] | None = None,
    retry_invalid_json: bool = True,
    retry_transport: bool = True,
) -> ApiResult[dict]:
    """Generate structured JSON through the AI gateway."""
    return await generate_structured_object(
        config=config,
        model=model,
        system_prompt=system_prompt,
        user_content=user_content,
        temperature=temperature,
        max_output_tokens=max_output_tokens,
        json_schema=json_schema,
        feature=feature,
        image_attachments=image_attachments,
        response_sink=response_sink,
        retry_invalid_json=retry_invalid_json,
        retry_transport=retry_transport,
    )


async def generate_text(
    config: Config,
    model: str,
    system_prompt: str,
    user_content: str,
    temperature: float = 0.7,
    max_output_tokens: int | None = None,
    feature: str = "text.generate",
) -> ApiResult[str]:
    """Generate raw text through the AI gateway."""
    return await ai_generate_text(
        config=config,
        model=model,
        system_prompt=system_prompt,
        user_content=user_content,
        temperature=temperature,
        max_output_tokens=max_output_tokens,
        feature=feature,
    )
