"""Text generation: routes to the correct provider using a strict model registry.

Every known model is explicitly mapped to its provider. If a model is not in
the registry the call fails with a clear error — no guessing.
"""

from __future__ import annotations

from novel_to_comic.config import Config
from novel_to_comic.usage import ApiResult

# ── Model → provider registry ────────────────────────────────────────────────
# Add new models here.  Do NOT add heuristic prefix-matching.

_TEXT_PROVIDERS = ("gemini", "anthropic", "openai", "openrouter")

MODEL_REGISTRY: dict[str, str] = {
    # Google Gemini
    "gemini-3.1-pro-preview": "gemini",
    "gemini-3.1-flash-lite-preview": "gemini",
    "gemini-2.5-pro": "gemini",
    "gemini-2.5-flash": "gemini",
    "gemini-2.5-flash-lite": "gemini",
    # Anthropic Claude
    "claude-opus-4-6": "anthropic",
    "claude-sonnet-4-6": "anthropic",
    # OpenAI
    "gpt-5.4": "openai",
    "gpt-5.4-mini": "openai",
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
) -> ApiResult[dict]:
    """Generate structured JSON using the appropriate text provider."""
    provider = provider_for_model(model)
    client = _load_client(provider)

    return await client.generate_json(
        config=config,
        model=model,
        system_prompt=system_prompt,
        user_content=user_content,
        temperature=temperature,
        max_output_tokens=max_output_tokens,
    )


async def generate_text(
    config: Config,
    model: str,
    system_prompt: str,
    user_content: str,
    temperature: float = 0.7,
) -> ApiResult[str]:
    """Generate raw text using the appropriate text provider."""
    provider = provider_for_model(model)
    client = _load_client(provider)

    return await client.generate_text(
        config=config,
        model=model,
        system_prompt=system_prompt,
        user_content=user_content,
        temperature=temperature,
    )


def _load_client(provider: str):
    """Lazy-import the correct client module."""
    if provider == "gemini":
        from novel_to_comic.clients import gemini
        return gemini
    if provider == "anthropic":
        from novel_to_comic.clients import claude
        return claude
    if provider == "openai":
        from novel_to_comic.clients import openai_text
        return openai_text
    if provider == "openrouter":
        from novel_to_comic.clients import openrouter_text
        return openrouter_text
    raise ValueError(f"Unknown text provider: {provider!r}")
