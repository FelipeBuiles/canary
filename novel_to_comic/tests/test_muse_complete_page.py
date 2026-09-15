"""Muse complete-page Draw wiring preserves the fixed edition contract."""

import asyncio
import io
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from PIL import Image

from novel_to_comic.config import Config
from novel_to_comic.models.draw import RetryProvenance
from novel_to_comic.page_drawing import (
    complete_page_adapter,
    compile_page_generation_request,
    current_page_capability_profile,
    select_book_edition,
)
from novel_to_comic.usage import UsageRecord
from tests.test_complete_page_draw import _inventory, _page, _reference_files


def test_muse_page_draw_uses_the_openrouter_gateway_profile(tmp_path):
    config = Config(draw_model="image-muse")
    profile = current_page_capability_profile(config)
    assert profile.provider == "openrouter"
    assert profile.model == "meta/muse-image"
    assert profile.max_image_references == 10

    compiled = compile_page_generation_request(
        _page(), select_book_edition(edition_id="test", profile=profile),
        _inventory(), _reference_files(tmp_path), retry=RetryProvenance(attempt=1),
    )
    assert (profile.output_width, profile.output_height) == (1920, 1280)
    adapter = complete_page_adapter(config)
    prepared = adapter.prepare(compiled)
    output = io.BytesIO()
    Image.new("RGB", (1920, 1280)).save(output, format="PNG")
    response = httpx.Response(
        200, json={"data": [{"b64_json": "test"}]},
        request=httpx.Request("POST", "http://gateway"),
    )
    post = AsyncMock(return_value=response)
    usage = UsageRecord(
        provider="litellm", model="image-muse", operation="image",
        image_count=1, cost_usd=0.01, cost_source="provider",
    )
    with (
        patch("novel_to_comic.ai.client._post_with_retry", post),
        patch("novel_to_comic.ai.client._decode_image_response", AsyncMock(return_value=output.getvalue())),
        patch("novel_to_comic.ai.client._extract_usage", return_value=usage),
        patch("novel_to_comic.ai.client._finalize_event_shielded", AsyncMock()),
    ):
        result = asyncio.run(adapter.generate(prepared))

    assert post.await_count == 1
    assert post.call_args.kwargs["retry_ambiguous"] is False
    assert post.call_args.kwargs["data"] == {
        "model": "image-muse", "prompt": prepared.prompt,
        "size": "1920x1280", "n": 1,
    }
    assert result.actual_provider_model == "openrouter/meta/muse-image"
    assert result.usage.provider == "openrouter"


@pytest.mark.parametrize("source_format", ["JPEG", "WEBP"])
def test_muse_page_draw_normalizes_valid_non_png_output(tmp_path, source_format):
    config = Config(draw_model="image-muse")
    profile = current_page_capability_profile(config)
    compiled = compile_page_generation_request(
        _page(), select_book_edition(edition_id="test", profile=profile),
        _inventory(), _reference_files(tmp_path), retry=RetryProvenance(attempt=1),
    )
    adapter = complete_page_adapter(config)
    prepared = adapter.prepare(compiled)
    source = io.BytesIO()
    Image.new("RGB", (1920, 1280), "navy").save(source, format=source_format)
    response = httpx.Response(
        200,
        json={"data": [{"b64_json": "test"}]},
        request=httpx.Request("POST", "http://gateway"),
    )
    usage = UsageRecord(
        provider="litellm", model="image-muse", operation="image",
        image_count=1, cost_usd=0.01, cost_source="provider",
    )
    with (
        patch("novel_to_comic.ai.client._post_with_retry", AsyncMock(return_value=response)),
        patch("novel_to_comic.ai.client._decode_image_response", AsyncMock(return_value=source.getvalue())),
        patch("novel_to_comic.ai.client._extract_usage", return_value=usage),
        patch("novel_to_comic.ai.client._finalize_event_shielded", AsyncMock()),
    ):
        result = asyncio.run(adapter.generate(prepared))

    assert result.media_type == "image/png"
    assert result.image_bytes.startswith(b"\x89PNG\r\n\x1a\n")
    with Image.open(io.BytesIO(result.image_bytes)) as output:
        assert output.size == (1920, 1280)
