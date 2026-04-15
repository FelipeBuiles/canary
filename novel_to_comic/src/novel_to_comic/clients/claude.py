"""Anthropic Claude API wrapper with async support and retry logic."""

import json

import anthropic
from tenacity import retry, stop_after_attempt, wait_exponential

from novel_to_comic.config import Config


def _get_client(config: Config) -> anthropic.AsyncAnthropic:
    return anthropic.AsyncAnthropic(api_key=config.anthropic_api_key)


@retry(wait=wait_exponential(min=2, max=60), stop=stop_after_attempt(3))
async def generate_json(
    config: Config,
    system_prompt: str,
    user_content: str,
    model: str | None = None,
    max_tokens: int = 8192,
    temperature: float = 0.7,
) -> dict:
    """Call Claude async and parse JSON from the response."""
    client = _get_client(config)
    message = await client.messages.create(
        model=model or config.screenplay_model,
        max_tokens=max_tokens,
        system=system_prompt,
        messages=[{"role": "user", "content": user_content}],
        temperature=temperature,
    )
    if not message.content:
        raise ValueError(f"Empty response from Claude ({model or config.screenplay_model})")
    text = message.content[0].text
    # Handle responses wrapped in markdown code fences
    if text.strip().startswith("```"):
        lines = text.strip().split("\n")
        lines = lines[1:-1]
        text = "\n".join(lines)
    return json.loads(text)


@retry(wait=wait_exponential(min=2, max=60), stop=stop_after_attempt(3))
async def generate_text(
    config: Config,
    system_prompt: str,
    user_content: str,
    model: str | None = None,
    max_tokens: int = 8192,
    temperature: float = 0.7,
) -> str:
    """Call Claude async and return raw text response."""
    client = _get_client(config)
    message = await client.messages.create(
        model=model or config.screenplay_model,
        max_tokens=max_tokens,
        system=system_prompt,
        messages=[{"role": "user", "content": user_content}],
        temperature=temperature,
    )
    if not message.content:
        raise ValueError(f"Empty response from Claude ({model or config.screenplay_model})")
    return message.content[0].text
