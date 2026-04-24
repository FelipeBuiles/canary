"""Anthropic Claude API wrapper with async support and retry logic."""

import json
import logging

import anthropic
from tenacity import retry, stop_after_attempt, wait_exponential

from novel_to_comic.clients.api_logging import log_call_end, log_call_start, payload_summary
from novel_to_comic.config import Config

logger = logging.getLogger("canary.anthropic")


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
    resolved_model = model or config.screenplay_model
    call_id, started = log_call_start(
        logger,
        provider="anthropic",
        operation="generate",
        task="json",
        payload=payload_summary(system_prompt=system_prompt, user_content=user_content),
    )
    client = _get_client(config)
    try:
        message = await client.messages.create(
            model=resolved_model,
            max_tokens=max_tokens,
            system=system_prompt,
            messages=[{"role": "user", "content": user_content}],
            temperature=temperature,
        )
        if not message.content:
            raise ValueError(f"Empty response from Claude ({resolved_model})")
        text = message.content[0].text
        # Handle responses wrapped in markdown code fences
        if text.strip().startswith("```"):
            lines = text.strip().split("\n")
            lines = lines[1:-1]
            text = "\n".join(lines)
        parsed = json.loads(text)
        log_call_end(
            logger,
            call_id=call_id,
            started=started,
            provider="anthropic",
            operation="generate",
            task="json",
            ok=True,
            result={"response_chars": len(text), "response_type": type(parsed).__name__},
        )
        return parsed
    except Exception as e:
        log_call_end(
            logger,
            call_id=call_id,
            started=started,
            provider="anthropic",
            operation="generate",
            task="json",
            ok=False,
            error=e,
        )
        raise


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
    resolved_model = model or config.screenplay_model
    call_id, started = log_call_start(
        logger,
        provider="anthropic",
        operation="generate",
        task="text",
        payload=payload_summary(system_prompt=system_prompt, user_content=user_content),
    )
    client = _get_client(config)
    try:
        message = await client.messages.create(
            model=resolved_model,
            max_tokens=max_tokens,
            system=system_prompt,
            messages=[{"role": "user", "content": user_content}],
            temperature=temperature,
        )
        if not message.content:
            raise ValueError(f"Empty response from Claude ({resolved_model})")
        text = message.content[0].text
        log_call_end(
            logger,
            call_id=call_id,
            started=started,
            provider="anthropic",
            operation="generate",
            task="text",
            ok=True,
            result={"response_chars": len(text)},
        )
        return text
    except Exception as e:
        log_call_end(
            logger,
            call_id=call_id,
            started=started,
            provider="anthropic",
            operation="generate",
            task="text",
            ok=False,
            error=e,
        )
        raise
