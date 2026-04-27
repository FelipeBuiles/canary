"""Shared implementation for OpenAI-compatible chat completion providers.

Both openai_text.py and openrouter_text.py delegate here — the only
differences between them are the base_url and api_key source.
"""

from __future__ import annotations

import json
import logging

from openai import AsyncOpenAI
from tenacity import retry, stop_after_attempt, wait_exponential

from novel_to_comic.clients.api_logging import log_call_end, log_call_start, payload_summary
from novel_to_comic.usage import ApiResult, UsageRecord


def _extract_usage(response, provider: str, model: str) -> UsageRecord | None:
    usage = getattr(response, "usage", None)
    if usage is None:
        return None
    return UsageRecord(
        provider=provider,
        model=model,
        operation="text",
        input_tokens=getattr(usage, "prompt_tokens", 0) or 0,
        output_tokens=getattr(usage, "completion_tokens", 0) or 0,
    )


@retry(wait=wait_exponential(min=2, max=60), stop=stop_after_attempt(3))
async def generate_json(
    *,
    client: AsyncOpenAI,
    provider: str,
    logger: logging.Logger,
    model: str,
    system_prompt: str,
    user_content: str,
    temperature: float = 0.7,
    max_output_tokens: int | None = None,
) -> ApiResult[dict]:
    call_id, started = log_call_start(
        logger,
        provider=provider,
        operation="generate",
        task="json",
        params={"model": model},
        payload=payload_summary(system_prompt=system_prompt, user_content=user_content),
    )
    kwargs: dict = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        "temperature": temperature,
        "response_format": {"type": "json_object"},
    }
    if max_output_tokens is not None:
        kwargs["max_completion_tokens"] = max_output_tokens
    try:
        response = await client.chat.completions.create(**kwargs)
        text = response.choices[0].message.content
        if not text:
            raise ValueError(f"Empty response from {provider} ({model})")
        if text.strip().startswith("```"):
            lines = text.strip().split("\n")
            text = "\n".join(lines[1:-1])
        parsed = json.loads(text)
        log_call_end(
            logger,
            call_id=call_id,
            started=started,
            provider=provider,
            operation="generate",
            task="json",
            ok=True,
            result={"response_chars": len(text), "response_type": type(parsed).__name__},
        )
        return ApiResult(value=parsed, usage=_extract_usage(response, provider, model))
    except Exception as e:
        log_call_end(
            logger,
            call_id=call_id,
            started=started,
            provider=provider,
            operation="generate",
            task="json",
            ok=False,
            error=e,
        )
        raise


@retry(wait=wait_exponential(min=2, max=60), stop=stop_after_attempt(3))
async def generate_text(
    *,
    client: AsyncOpenAI,
    provider: str,
    logger: logging.Logger,
    model: str,
    system_prompt: str,
    user_content: str,
    temperature: float = 0.7,
) -> ApiResult[str]:
    call_id, started = log_call_start(
        logger,
        provider=provider,
        operation="generate",
        task="text",
        params={"model": model},
        payload=payload_summary(system_prompt=system_prompt, user_content=user_content),
    )
    try:
        response = await client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            temperature=temperature,
        )
        text = response.choices[0].message.content
        if not text:
            raise ValueError(f"Empty response from {provider} ({model})")
        log_call_end(
            logger,
            call_id=call_id,
            started=started,
            provider=provider,
            operation="generate",
            task="text",
            ok=True,
            result={"response_chars": len(text)},
        )
        return ApiResult(value=text, usage=_extract_usage(response, provider, model))
    except Exception as e:
        log_call_end(
            logger,
            call_id=call_id,
            started=started,
            provider=provider,
            operation="generate",
            task="text",
            ok=False,
            error=e,
        )
        raise
