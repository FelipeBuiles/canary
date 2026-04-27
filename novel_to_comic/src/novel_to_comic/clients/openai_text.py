"""OpenAI text API wrapper."""

from __future__ import annotations

import logging

from openai import AsyncOpenAI

from novel_to_comic.clients._openai_compat import generate_json as _gen_json
from novel_to_comic.clients._openai_compat import generate_text as _gen_text
from novel_to_comic.config import Config
from novel_to_comic.usage import ApiResult

logger = logging.getLogger("canary.openai_text")


def _get_client(config: Config) -> AsyncOpenAI:
    return AsyncOpenAI(api_key=config.openai_api_key)


async def generate_json(
    config: Config,
    model: str,
    system_prompt: str,
    user_content: str,
    temperature: float = 0.7,
    max_output_tokens: int | None = None,
) -> ApiResult[dict]:
    return await _gen_json(
        client=_get_client(config),
        provider="openai",
        logger=logger,
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
    return await _gen_text(
        client=_get_client(config),
        provider="openai",
        logger=logger,
        model=model,
        system_prompt=system_prompt,
        user_content=user_content,
        temperature=temperature,
    )
