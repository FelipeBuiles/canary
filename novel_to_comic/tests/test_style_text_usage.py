"""Style retains paid text usage even when copy is rejected or falls back."""
import asyncio

import pytest

from novel_to_comic.ai.errors import AIStructuredResponseError
from novel_to_comic.config import Config
from novel_to_comic.stages import s2_style as style
from novel_to_comic.usage import ApiResult, UsageRecord
from tests.test_style_stage import _bible


def test_rejected_production_records_each_attempt_before_failure(monkeypatch):
    observed = []
    usages = [UsageRecord(provider="test", model="test", operation="text") for _ in range(4)]
    calls = []

    async def generate(**request):
        index = len(calls) * 2
        calls.append(request)
        return ApiResult({}, usage=usages[index], additional_usage=(usages[index + 1],))

    monkeypatch.setattr(style.text_client, "generate_json", generate)
    with style.style_text_usage(observed.append), pytest.raises(RuntimeError, match="required schema"):
        asyncio.run(style._design_production(Config(), _bible(), {"label": "Ink"}))
    assert observed == usages
    assert len(calls) == 2


def test_best_effort_proof_copy_keeps_usage_from_unparseable_response(monkeypatch, tmp_path):
    observed = []
    usage = UsageRecord(provider="test", model="test", operation="text")

    async def generate(**request):
        raise AIStructuredResponseError("Invalid JSON", usage_records=(usage,))

    monkeypatch.setattr(style.text_client, "generate_json", generate)
    with style.style_text_usage(observed.append):
        assert asyncio.run(style.generate_style_proof_copy(Config(), _bible(), tmp_path)) is None
    assert observed == [usage]


def test_standalone_production_failure_retains_prior_validation_attempt_usage(monkeypatch):
    usages = [UsageRecord(provider="test", model="test", operation="text") for _ in range(2)]
    calls = []

    async def generate(**request):
        calls.append(request)
        if len(calls) == 1:
            return ApiResult({}, usage=usages[0])
        raise AIStructuredResponseError("Invalid JSON", usage_records=(usages[1],))

    monkeypatch.setattr(style.text_client, "generate_json", generate)
    with pytest.raises(AIStructuredResponseError) as caught:
        asyncio.run(style._design_production(Config(), _bible(), {"label": "Ink"}))
    assert caught.value.usage_records == tuple(usages)
