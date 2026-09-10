"""Unmeasured image consumption must not become a made-up provider tariff."""
import pytest

from novel_to_comic.model_costs import PricingResolver


@pytest.mark.parametrize("variant", ["sunburst", "flare"])
def test_gpt25_uses_explicit_allowance_instead_of_gpt2_token_estimate(variant):
    resolver = PricingResolver()
    estimate = resolver.estimate_image_cost(
        f"image-{variant}", 2, ref_count=3, prompt_tokens=1000, quality="high",
    )
    assert estimate.cost_usd == pytest.approx(0.535)
    assert estimate.source == "configured_reservation_allowance"
    measured = resolver.calculate(
        model_alias=f"image-{variant}", operation="image", image_count=2,
        provider_cost_usd=0.123, provider_cost_source="provider_reported_cost",
    )
    assert measured.cost_usd == pytest.approx(0.123)
    assert measured.source == "provider_reported_cost"
