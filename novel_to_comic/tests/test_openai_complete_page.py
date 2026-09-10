"""Public GPT Image 2.5 transport preserves frozen page contracts without retries."""
import asyncio
import io
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from PIL import Image

from novel_to_comic.config import Config
from novel_to_comic.models.draw import RetryProvenance
from novel_to_comic.page_drawing import (
    complete_page_adapter, compile_page_generation_request,
    current_page_capability_profile, select_book_edition,
)
from novel_to_comic.usage import UsageRecord
from tests.test_complete_page_draw import _page, _inventory, _reference_files


@pytest.mark.parametrize('variant', ['sunburst', 'flare'])
def test_public_image_page_preserves_references_and_sends_fixed_controls(tmp_path, variant):
    config = Config(draw_model=f'image-{variant}')
    profile = current_page_capability_profile(config)
    edition = select_book_edition(edition_id='test', profile=profile)
    compiled = compile_page_generation_request(
        _page(), edition, _inventory(), _reference_files(tmp_path), retry=RetryProvenance(attempt=1),
    )
    adapter = complete_page_adapter(config)
    prepared = adapter.prepare(compiled)
    image = io.BytesIO()
    Image.new('RGB', (1024, 1536)).save(image, format='PNG')
    response = httpx.Response(200, json={'data': [{'b64_json': 'test'}]}, request=httpx.Request('POST', 'http://gateway'))
    post = AsyncMock(return_value=response)
    usage = UsageRecord(provider='litellm', model=profile.model, operation='image', image_count=1, cost_usd=0.19, cost_source='provider')
    with (
        patch('novel_to_comic.ai.client._post_with_retry', post),
        patch('novel_to_comic.ai.client._decode_image_response', AsyncMock(return_value=image.getvalue())),
        patch('novel_to_comic.ai.client._extract_usage', return_value=usage),
        patch('novel_to_comic.ai.client._finalize_event_shielded', AsyncMock()),
    ):
        result = asyncio.run(adapter.generate(prepared))
    assert post.await_count == 1
    kwargs = post.call_args.kwargs
    assert kwargs['retry_ambiguous'] is False
    assert kwargs['data'] == {
        'model': f'image-{variant}', 'prompt': prepared.prompt, 'size': '1024x1536',
        'quality': 'high', 'output_format': 'png', 'n': 1, 'input_fidelity': 'high',
    }
    assert [entry[1][1] for entry in kwargs['files']] == list(prepared.reference_bytes)
    assert result.actual_provider_model == f'openai/gpt-image-2.5-{variant}'
    assert result.usage.provider == "openai"
    assert result.usage.cost_usd == 0.19


def test_variant_cannot_change_frozen_edition():
    sunburst = current_page_capability_profile(Config(draw_model='image-sunburst'))
    flare = current_page_capability_profile(Config(draw_model='image-flare'))
    edition = select_book_edition(edition_id='test', profile=sunburst)
    with pytest.raises(ValueError, match='fixed for the edition'):
        select_book_edition(edition_id='test', profile=flare, existing=edition)


@pytest.mark.parametrize('failure', ['timeout', 'wrong_size', 'wrong_model'])
def test_public_image_failure_never_resubmits(tmp_path, failure):
    config = Config(draw_model='image-sunburst')
    profile = current_page_capability_profile(config)
    compiled = compile_page_generation_request(
        _page(), select_book_edition(edition_id='test', profile=profile),
        _inventory(), _reference_files(tmp_path), retry=RetryProvenance(attempt=1),
    )
    adapter = complete_page_adapter(config)
    image = io.BytesIO()
    Image.new('RGB', (512, 512) if failure == 'wrong_size' else (1024, 1536)).save(image, format='PNG')
    response = httpx.Response(200, json={'model': 'gpt-image-2.5-flare' if failure == 'wrong_model' else profile.model,
        'data': [{'b64_json': 'test'}]}, request=httpx.Request('POST', 'http://gateway'))
    post = AsyncMock(side_effect=httpx.ReadTimeout('outcome unknown')) if failure == 'timeout' else AsyncMock(return_value=response)
    usage = UsageRecord(provider='openai', model=profile.model, operation='image', image_count=1, cost_usd=0.19, cost_source='provider')
    with (
        patch('novel_to_comic.ai.client._post_with_retry', post),
        patch('novel_to_comic.ai.client._decode_image_response', AsyncMock(return_value=image.getvalue())),
        patch('novel_to_comic.ai.client._extract_usage', return_value=usage),
        patch('novel_to_comic.ai.finalisation.finalise_image_failure', AsyncMock()),
        patch('novel_to_comic.server.credits.retain_ambiguous_job'),
        pytest.raises((ValueError, httpx.ReadTimeout)),
    ):
        asyncio.run(adapter.generate(adapter.prepare(compiled)))
    assert post.await_count == 1
    assert post.call_args.kwargs['retry_ambiguous'] is False


def test_unknown_billing_recovery_and_correction_keep_generation_pending(tmp_path):
    from types import SimpleNamespace
    from novel_to_comic.models.draw import CompletePageProviderResult
    from novel_to_comic.page_drawing import draw_complete_page, correct_complete_page
    from novel_to_comic.target_artifacts import TargetArtifacts

    config = Config(draw_model='image-sunburst')
    profile = current_page_capability_profile(config)
    compiled = compile_page_generation_request(
        _page(), select_book_edition(edition_id='test', profile=profile),
        _inventory(), _reference_files(tmp_path), retry=RetryProvenance(attempt=1),
    )
    adapter = complete_page_adapter(config)
    output = io.BytesIO()
    Image.new('RGB', (1024, 1536)).save(output, format='PNG')
    result = CompletePageProviderResult(artifact_kind='complete_page', image_bytes=output.getvalue(),
        media_type='image/png', width=1024, height=1536, latency_ms=1,
        actual_provider_model=profile.model,
        usage=UsageRecord(provider='openai', model=profile.model, operation='image', image_count=1))
    artifacts = TargetArtifacts(tmp_path / 'project')
    with patch.object(adapter, 'generate', AsyncMock(return_value=result)) as generate:
        first = asyncio.run(draw_complete_page(compiled, adapter=adapter, artifacts=artifacts, page=_page()))
        assert first.render.cost_usd is None
        assert artifacts.resumable_generation_request(7) is not None
        recovered = asyncio.run(draw_complete_page(compiled, adapter=adapter, artifacts=artifacts, page=_page()))
        assert recovered == first
        assert artifacts.resumable_generation_request(7) is not None
        assert generate.await_count == 1
    correction = SimpleNamespace(issue_ids=(), parent_render_revision=1)
    with (
        patch('novel_to_comic.page_review.ensure_correction_issues'),
        patch('novel_to_comic.page_drawing.draw_complete_page', AsyncMock(return_value=first)),
    ):
        asyncio.run(correct_complete_page(SimpleNamespace(request=SimpleNamespace(correction=correction)),
            issue=None, adapter=adapter, artifacts=artifacts, page=_page()))
    assert artifacts.resumable_generation_request(7) is not None
