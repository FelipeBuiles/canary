"""Image usage pricing uses measured modality and cache counts, never allowances."""
from unittest.mock import MagicMock, patch

import httpx
import pytest

from novel_to_comic.ai.client import _extract_usage
from novel_to_comic.usage import calculate_cost_breakdown
from novel_to_comic.server.credits import debit_model_usage


def _usage(details=None, **extra):
    return {'input_tokens': 1200, 'output_tokens': 2000,
            'input_tokens_details': details or {'text_tokens': 200, 'image_tokens': 1000}, **extra}


@pytest.mark.parametrize('alias', ['image-sunburst', 'image-flare'])
def test_real_image_usage_modality_cost(alias):
    record = _extract_usage({'usage': _usage()}, 'call', alias, 'image')
    assert calculate_cost_breakdown(record).cost_usd == pytest.approx(.069)


def test_cached_modalities_are_discounted_separately():
    record = _extract_usage({'usage': _usage({'text_tokens': 200, 'image_tokens': 1000,
        'cached_tokens': 550, 'cached_tokens_details': {'text_tokens': 50, 'image_tokens': 500}})},
        'call', 'image-sunburst', 'image')
    assert record.cached_text_tokens == 50
    assert record.cached_image_tokens == 500
    assert calculate_cost_breakdown(record).cost_usd == pytest.approx(.0658125)


def test_provider_dollars_override_calculation():
    record = _extract_usage({'usage': _usage()}, 'call', 'image-flare', 'image',
        httpx.Headers({'x-litellm-response-cost': '.12'}))
    assert calculate_cost_breakdown(record).cost_usd == .12


@pytest.mark.parametrize('payload', [{}, {'usage': {'input_tokens': 1200, 'output_tokens': 2000}},
    {'usage': _usage({'text_tokens': 200, 'image_tokens': 1000, 'cached_tokens': 550})}])
def test_missing_usage_or_cache_split_cannot_settle(payload):
    record = _extract_usage(payload, 'call', 'image-sunburst', 'image')
    assert record.cost_usd is None
    assert calculate_cost_breakdown(record).source == 'unknown_provider_usage'
    assert calculate_cost_breakdown(record).cost_usd is None
    db = MagicMock()
    with patch('novel_to_comic.server.credits.retain_ambiguous_job') as retain:
        with pytest.raises(RuntimeError, match='reconcile billing'):
            debit_model_usage(db, 'user', 'project', record, description='page', job_id='job')
    retain.assert_called_once_with('job')
    db.rpc.assert_not_called()


@pytest.mark.parametrize('width,height,quality', [(1025, 1536, 'high'), (1024, 1536, 'ultra')])
def test_invalid_generic_image_settings_are_rejected_before_transport(width, height, quality):
    from types import SimpleNamespace
    from novel_to_comic.ai.providers.litellm_http import _serialize_openai_image
    wire = SimpleNamespace(configured_provider_model='openai/gpt-image-2.5-sunburst',
        controls=(('quality', quality),), width=width, height=height)
    with pytest.raises(ValueError):
        _serialize_openai_image(wire)


def test_image_output_detail_excludes_nonimage_tokens():
    record = _extract_usage({'usage': _usage(output_tokens=2100,
        output_tokens_details={'image_tokens': 2000, 'text_tokens': 100})},
        'call', 'image-flare', 'image')
    assert calculate_cost_breakdown(record).cost_usd == pytest.approx(.069)


def test_measured_style_estimate_is_bounded_and_never_changes_settlement():
    from novel_to_comic.model_costs import get_pricing_resolver

    resolver = get_pricing_resolver()
    quote = resolver.estimate_image_cost("image-sunburst", 1, quality="medium",
        width=1024, height=1280, prompt_tokens=897, ref_count=1)
    assert quote.source == "measured_consumption_estimate"
    assert quote.cost_usd == pytest.approx(.034885)
    observed = _extract_usage({"usage": {
        "input_tokens": 2402, "output_tokens": 378,
        "input_tokens_details": {"text_tokens": 897, "image_tokens": 1505},
        "output_tokens_details": {"image_tokens": 378, "text_tokens": 0},
    }}, "observed", "image-sunburst", "image")
    assert calculate_cost_breakdown(observed).cost_usd == pytest.approx(.027865)
    assert .027865 < quote.cost_usd < .05


@pytest.mark.parametrize("model,quality,width,height", [
    ("image-flare", "medium", 1024, 1280),
    ("image-sunburst", "high", 1024, 1280),
    ("image-sunburst", "auto", 1024, 1280),
    ("image-sunburst", "medium", 768, 1024),
])
def test_unmeasured_image_settings_keep_conservative_allowance(model, quality, width, height):
    from novel_to_comic.model_costs import get_pricing_resolver

    quote = get_pricing_resolver().estimate_image_cost(model, 1, quality=quality, width=width, height=height)
    assert quote.source == "configured_reservation_allowance"
    assert quote.cost_usd == .25


def test_measured_draw_quote_covers_observed_usage_without_flat_allowance():
    from novel_to_comic.model_costs import get_pricing_resolver

    quote = get_pricing_resolver().estimate_image_cost(
        'image-sunburst', 1, quality='high', width=1024, height=1536,
        prompt_tokens=2022, ref_count=4,
    )
    assert quote.source == 'measured_consumption_estimate'
    assert quote.cost_usd == pytest.approx(.12661)
    assert .082855 < quote.cost_usd < .15
    flare = get_pricing_resolver().estimate_image_cost(
        'image-flare', 1, quality='high', width=1024, height=1536,
    )
    assert flare.source == 'configured_reservation_allowance'
    assert flare.cost_usd == .25
