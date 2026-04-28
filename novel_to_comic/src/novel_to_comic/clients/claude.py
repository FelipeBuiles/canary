"""Anthropic Claude API wrapper with async support and retry logic."""

import json
import logging

import anthropic
from tenacity import retry, stop_after_attempt, wait_exponential

from novel_to_comic.clients.api_logging import log_call_end, log_call_start, payload_summary
from novel_to_comic.config import Config
from novel_to_comic.usage import ApiResult, UsageRecord, estimate_text_usage

logger = logging.getLogger("canary.anthropic")


def _get_client(config: Config) -> anthropic.AsyncAnthropic:
    return anthropic.AsyncAnthropic(api_key=config.anthropic_api_key)


def _extract_claude_usage(message, model: str, call_id: str) -> UsageRecord | None:
    usage = getattr(message, "usage", None)
    if usage is None:
        return None
    return UsageRecord(
        call_id=call_id,
        provider="anthropic",
        model=model,
        operation="text",
        input_tokens=getattr(usage, "input_tokens", 0) or 0,
        output_tokens=getattr(usage, "output_tokens", 0) or 0,
    )


@retry(wait=wait_exponential(min=2, max=60), stop=stop_after_attempt(3))
async def generate_json(
    config: Config,
    model: str | None = None,
    system_prompt: str = "",
    user_content: str = "",
    temperature: float = 0.7,
    max_output_tokens: int | None = None,
) -> ApiResult[dict]:
    """Call Claude async and parse JSON from the response."""
    resolved_model = model or config.screenplay_model
    call_id, started = log_call_start(
        logger,
        provider="anthropic",
        operation="generate",
        task="json",
        params={"model": resolved_model},
        payload=payload_summary(system_prompt=system_prompt, user_content=user_content),
    )
    client = _get_client(config)
    try:
        message = await client.messages.create(
            model=resolved_model,
            max_tokens=max_output_tokens or 8192,
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
        usage = _extract_claude_usage(message, resolved_model, call_id) or estimate_text_usage(
            provider="anthropic",
            model=resolved_model,
            system_prompt=system_prompt,
            user_content=user_content,
            output_text=text,
            call_id=call_id,
        )
        return ApiResult(value=parsed, usage=usage)
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
    model: str | None = None,
    system_prompt: str = "",
    user_content: str = "",
    temperature: float = 0.7,
    max_output_tokens: int | None = None,
) -> ApiResult[str]:
    """Call Claude async and return raw text response."""
    resolved_model = model or config.screenplay_model
    call_id, started = log_call_start(
        logger,
        provider="anthropic",
        operation="generate",
        task="text",
        params={"model": resolved_model},
        payload=payload_summary(system_prompt=system_prompt, user_content=user_content),
    )
    client = _get_client(config)
    try:
        message = await client.messages.create(
            model=resolved_model,
            max_tokens=max_output_tokens or 8192,
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
        usage = _extract_claude_usage(message, resolved_model, call_id) or estimate_text_usage(
            provider="anthropic",
            model=resolved_model,
            system_prompt=system_prompt,
            user_content=user_content,
            output_text=text,
            call_id=call_id,
        )
        return ApiResult(value=text, usage=usage)
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
