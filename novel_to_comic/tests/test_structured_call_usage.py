"""Nested JSON retries retain every completed paid response."""
import asyncio

import pytest

from novel_to_comic.ai.errors import AIStructuredResponseError
from novel_to_comic.clients.structured_call import generate_validated_json
from novel_to_comic.config import Config
from novel_to_comic.usage import ApiResult, UsageRecord


@pytest.mark.parametrize("fail", [False, True])
def test_nested_attempts_keep_usage(fail):
    usages = [UsageRecord(provider="test", model="test", operation="text") for _ in range(4)]
    calls = 0

    async def generate(**kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            return ApiResult(value="bad", usage=usages[1], additional_usage=(usages[0],))
        if fail:
            raise AIStructuredResponseError("bad json", usage_records=usages[2:])
        return ApiResult(value="42", usage=usages[3], additional_usage=(usages[2],))

    async def run():
        return await generate_validated_json(
            Config(), model="test", system_prompt="json", user_content="json", parse=int,
            correction=lambda value, error: "correct", label="test", feature="test", generate=generate,
        )

    if fail:
        with pytest.raises(AIStructuredResponseError) as caught:
            asyncio.run(run())
        assert caught.value.usage_records == tuple(usages)
    else:
        result = asyncio.run(run())
        assert result.value == 42
        assert result.usage_records == usages
