"""Public GPT Image 2.5 transport preserves frozen page contracts without retries."""
import asyncio
import io
import json
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


def test_public_image_page_preserves_references_and_sends_fixed_controls(tmp_path):
    config = Config(draw_model='image-sunburst')
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
    expected = {
        'model': 'image-sunburst', 'prompt': prepared.prompt, 'size': '1024x1536', 'n': 1,
    }
    expected.update({'quality': 'high', 'output_format': 'png'})
    manifest = kwargs['data']['canary_wire_request']
    assert json.loads(manifest) == {
        'width': 1024, 'height': 1536,
        'controls': [['quality', 'high'], ['output_format', 'png'], ['n', 1]],
    }
    expected['canary_wire_request'] = manifest
    # Reproduce custom-provider filtering: only the manifest survives.
    from litellm_handlers.fal_provider import _build_payload
    payload = _build_payload(
        'openai/gpt-image-2.5/sunburst/edit', prepared.prompt, [],
        {'canary_wire_request': manifest},
    )
    assert payload['image_size'] == {'width': 1024, 'height': 1536}
    assert payload['quality'] == 'high'
    assert payload['output_format'] == 'png'
    assert payload['num_images'] == 1
    assert kwargs['data'] == expected
    assert [entry[1][1] for entry in kwargs['files']] == list(prepared.reference_bytes)
    assert result.actual_provider_model == f'fal-queue/{profile.model}'
    assert result.usage.provider == "fal-queue"
    assert result.usage.cost_usd == 0.19


def test_sunburst_page_profile_uses_fal_queue():
    profile = current_page_capability_profile(Config(draw_model='image-sunburst'))
    assert profile.provider == 'fal-queue'
    assert profile.model == 'openai/gpt-image-2.5/sunburst'


def test_retired_image_variant_cannot_be_selected():
    sunburst = current_page_capability_profile(Config(draw_model='image-sunburst'))
    edition = select_book_edition(edition_id='test', profile=sunburst)
    for retired in ('image-flare', 'image-muse'):
        with pytest.raises(ValueError, match='Unsupported complete-page model selection'):
            current_page_capability_profile(Config(draw_model=retired))
    with pytest.raises(ValueError, match='fixed for the edition'):
        select_book_edition(edition_id='other', profile=sunburst, existing=edition)


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
        usage=UsageRecord(provider='fal-queue', model=profile.model, operation='image', image_count=1))
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


def test_page_quote_uses_current_pricing_and_counts_correction_source(tmp_path):
    from dataclasses import replace
    from novel_to_comic.page_drawing import estimate_draw_api_cost, correction_credit_estimate
    from novel_to_comic.usage import estimate_image_cost

    config = Config(draw_model='image-sunburst')
    profile = current_page_capability_profile(config)
    compiled = compile_page_generation_request(
        _page(), select_book_edition(edition_id='test', profile=profile),
        _inventory(), _reference_files(tmp_path), retry=RetryProvenance(attempt=1),
    )
    frozen = compiled.request.model_dump_json()
    expected = estimate_image_cost(
        compiled.request.model, 1, quality='high', width=1024, height=1536,
        ref_count=len(compiled.request.references), prompt_text=compiled.request.prompt,
    )
    quote = estimate_draw_api_cost(config, float(compiled.request.estimated_cost_usd), compiled=compiled, ocr=False)
    assert quote == pytest.approx(expected)
    assert quote < float(compiled.request.estimated_cost_usd)
    correction = replace(compiled, edit_source_bytes=b'parent page')
    assert estimate_draw_api_cost(config, 0, compiled=correction, ocr=False) == pytest.approx(quote + .016)
    assert correction_credit_estimate(correction, config=config, reserve=True)['estimate_credits'] > 0
    assert compiled.request.model_dump_json() == frozen
    complete_page_adapter(config).prepare(compiled)


def test_sunburst_stage_and_batch_quotes_use_the_same_measured_page_cost(tmp_path):
    from types import SimpleNamespace
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from novel_to_comic.server.deps import get_project
    from novel_to_comic.server.routers.pages import router
    from novel_to_comic.stages.s7_page_draw import estimate_cost
    from novel_to_comic.target_artifacts import TargetArtifacts
    from novel_to_comic.page_drawing import correction_credit_estimate, estimate_draw_api_cost

    config = Config(draw_model='image-sunburst')
    page = _page()
    files = _reference_files(tmp_path)
    artifacts = TargetArtifacts(tmp_path)
    artifacts.write_page(page)
    edition = select_book_edition(edition_id='test', profile=current_page_capability_profile(config))
    artifacts.write_book_edition(edition)
    artifacts.plan_path.parent.mkdir(parents=True, exist_ok=True)
    artifacts.plan_path.write_text('{}')
    compiled = compile_page_generation_request(
        page, edition, _inventory(), files, retry=RetryProvenance(attempt=1),
        style_template=config.style_template, style_reference_path=tmp_path / "samples" / "style_1.png",
    )
    expected = dict(correction_credit_estimate(compiled, config=config, reserve=True))
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_project] = lambda: (tmp_path, config, None)
    with (
        patch.object(TargetArtifacts, 'read_plan', return_value=SimpleNamespace(pages=[page])),
        patch('novel_to_comic.server.routers.pages.approved_visual_inventory', return_value=_inventory()),
        patch('novel_to_comic.server.routers.pages.approved_reference_files', return_value=files),
        patch('novel_to_comic.stages.s5_plan.approved_visual_inventory', return_value=_inventory()),
        patch('novel_to_comic.stages.s5_plan.approved_reference_files', return_value=files),
    ):
        response = TestClient(app).get('/pages/generate/estimate')
        assert response.status_code == 200
        assert response.json() == expected
        assert estimate_cost(config, tmp_path, None) == pytest.approx(
            estimate_draw_api_cost(config, 0, compiled=compiled),
        )


@pytest.fixture(autouse=True)
def reviewed_story_precondition(monkeypatch):
    # This suite tests rendering/credit contracts with deliberately partial
    # upstream fixtures. Real missing/stale review admission is tested in
    # test_narrative_review.py.
    monkeypatch.setattr("novel_to_comic.server.routers.pages.require_draw_narrative_reviews", lambda target: None)
    monkeypatch.setattr("novel_to_comic.narrative_review.require_draw_narrative_reviews", lambda target: None)
