"""Text generation compatibility wrapper.

Runtime calls go through the internal LiteLLM-backed AI client. MODEL_REGISTRY
is retained for pricing audits and legacy model metadata during the migration.
"""

from __future__ import annotations

from novel_to_comic.config import Config
from novel_to_comic.usage import ApiResult
from novel_to_comic.ai import generate_structured_object, generate_text as ai_generate_text

# ── Model → provider registry ────────────────────────────────────────────────
# Add new models here.  Do NOT add heuristic prefix-matching.

_TEXT_PROVIDERS = ("gemini", "anthropic", "openai", "openrouter")

MODEL_REGISTRY: dict[str, str] = {
    # Google Gemini
    "gemini-3.1-pro-preview": "gemini",
    "gemini-3.5-flash": "gemini",
    "gemini-3.1-flash-preview": "gemini",
    "gemini-3.1-flash-lite-preview": "gemini",
    "gemini-2.5-pro": "gemini",
    "gemini-2.5-flash": "gemini",
    "gemini-2.5-flash-lite": "gemini",
    # Anthropic Claude
    "claude-opus-4-7": "anthropic",
    "claude-sonnet-4-6": "anthropic",
    "claude-haiku-4-5": "anthropic",
    # OpenAI
    "gpt-5.4": "openai",
    "gpt-5.4-mini": "openai",
    # Gateway aliases (intent-preset)
    "extract-fast": "litellm",
    "extract-balanced": "litellm",
    "extract-quality": "litellm",
    "screenplay-fast": "litellm",
    "screenplay-balanced": "litellm",
    "screenplay-quality": "litellm",
    "panel-fast": "litellm",
    "panel-balanced": "litellm",
    "panel-quality": "litellm",
    "prompt-fast": "litellm",
    "prompt-balanced": "litellm",
    "prompt-quality": "litellm",
}


def provider_for_model(model: str) -> str:
    """Return the provider for a known model, or raise."""
    provider = MODEL_REGISTRY.get(model)
    if provider is not None:
        return provider
    raise ValueError(
        f"Unknown text model {model!r}. "
        f"Add it to MODEL_REGISTRY in clients/text.py with its provider."
    )


async def generate_json(
    config: Config,
    model: str,
    system_prompt: str,
    user_content: str | bytes,
    temperature: float = 0.7,
    max_output_tokens: int | None = None,
    feature: str = "text.generate_json",
) -> ApiResult[dict]:
    """Generate structured JSON through the AI gateway."""
    return await generate_structured_object(
        config=config,
        model=model,
        system_prompt=system_prompt,
        user_content=user_content,
        temperature=temperature,
        max_output_tokens=max_output_tokens,
        feature=feature,
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
