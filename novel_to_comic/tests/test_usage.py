from pytest import approx

from novel_to_comic.usage import UsageRecord, calculate_cost, calculate_cost_breakdown, estimate_image_cost
from novel_to_comic.server.credits import provider_usd_to_credits


def test_image_alias_with_token_usage_uses_resolved_provider_token_pricing():
    usage = UsageRecord(
        provider="openai",
        model="image-balanced",
        operation="image",
        input_tokens=1000,
        output_tokens=2000,
        image_count=1,
    )

    assert calculate_cost(usage) == 0.085


def test_token_priced_image_model_uses_token_pricing():
    usage = UsageRecord(
        provider="openai",
        model="gpt-image-2",
        operation="image",
        input_tokens=1000,
        output_tokens=2000,
        image_count=1,
    )

    assert calculate_cost(usage) == 0.085


def test_image_alias_without_token_usage_uses_resolved_per_image_estimate():
    usage = UsageRecord(
        provider="openai",
        model="image-balanced",
        operation="image",
        image_count=1,
    )

    # Actual usage with no token data still falls through to output_cost_per_image.
    assert calculate_cost(usage) == 0.19


def test_token_priced_image_alias_estimates_via_quality_token_table():
    # image-balanced → gpt-image-2, which is token-priced. The override yaml
    # supplies image_output_tokens_by_quality so estimates scale by quality.
    # 2 images × 1056 (auto/medium) × $0.00004 = $0.08448
    assert estimate_image_cost("image-balanced", 2) == approx(0.08448)
    # 2 images × 4160 (high) × $0.00004 = $0.3328
    assert estimate_image_cost("image-balanced", 2, quality="high") == approx(0.3328)


def test_fast_image_alias_estimates_reference_input_images():
    assert estimate_image_cost("image-fast", 1, ref_count=0) == 0.02
    assert estimate_image_cost("image-fast", 1, ref_count=4) == 0.07
    assert provider_usd_to_credits(estimate_image_cost("image-fast", 1, ref_count=4)) == 7


def test_provider_reported_cost_wins_over_cached_pricing():
    usage = UsageRecord(
        provider="openai",
        model="panel-balanced",
        provider_model="openai/gpt-5.4-mini",
        operation="text",
        input_tokens=1000,
        output_tokens=1000,
        cost_usd=0.123456,
        cost_source="litellm_response_cost",
    )

    breakdown = calculate_cost_breakdown(usage)
    assert breakdown.cost_usd == 0.123456
    assert breakdown.source == "litellm_response_cost"
    assert calculate_cost(usage) == 0.123456
