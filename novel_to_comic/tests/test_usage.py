from types import SimpleNamespace

from pytest import approx, fixture

from novel_to_comic import usage as usage_module
from novel_to_comic.model_catalog import models
from novel_to_comic.model_costs import PricingResolver
from novel_to_comic.server.credits import debit_model_usage, provider_usd_to_credits
from novel_to_comic.usage import (
    UsageRecord,
    audit_pricing,
    calculate_cost,
    calculate_cost_breakdown,
    estimate_image_cost,
    estimate_text_cost,
    thinking_allowance,
)


@fixture
def synthetic_image_rates(monkeypatch):
    """Exercise generic pricing formulas without shipping retired tariffs."""
    from novel_to_comic import model_costs

    resolver = PricingResolver()
    resolver._overrides = {"aliases": {}, "model_overrides": {
        "test-token-image": {
            "input_cost_per_token": 5e-6, "output_cost_per_token": 3e-5,
            "output_cost_per_image": .03168,
            "image_output_tokens_by_quality": {"auto": 1056, "high": 4160},
        },
        "test-fixed-image": {"output_cost_per_image": .134},
        "test-cheap-image": {"output_cost_per_image": .01},
        "test-reference-image": {"output_cost_per_image": .0336, "input_cost_per_image": .00028},
        "test-megapixel-image": {"input_cost_per_megapixel": .015,
            "output_cost_first_megapixel": .03, "output_cost_per_extra_megapixel": .015},
    }}
    monkeypatch.setattr(model_costs, "_DEFAULT_RESOLVER", resolver)


def test_token_priced_image_model_uses_token_pricing(synthetic_image_rates):
    usage = UsageRecord(
        provider="openai",
        model="test-token-image",
        operation="image",
        input_tokens=1000,
        output_tokens=2000,
        image_count=1,
    )

    assert calculate_cost(usage) == 0.065


def test_image_alias_without_token_usage_uses_resolved_per_image_estimate(synthetic_image_rates):
    usage = UsageRecord(
        provider="openai",
        model="test-token-image",
        operation="image",
        image_count=1,
    )

    # Actual usage with no token data still falls through to output_cost_per_image.
    assert calculate_cost(usage) == 0.03168


def test_token_priced_image_alias_estimates_via_quality_token_table(synthetic_image_rates):
    # test-token-image is token-priced. The override yaml
    # supplies image_output_tokens_by_quality so estimates scale by quality.
    # 2 images × 1056 (auto/medium) × $0.00003 = $0.06336
    assert estimate_image_cost("test-token-image", 2) == approx(0.06336)
    # 2 images × 4160 (high) × $0.00003 = $0.2496
    assert estimate_image_cost("test-token-image", 2, quality="high") == approx(0.2496)


def test_fixed_image_alias_estimates_per_image_cost(synthetic_image_rates):
    # Synthetic fixed price: $0.134/image.
    assert estimate_image_cost("test-fixed-image", 2) == approx(0.268)


def test_fixed_image_pricing_does_not_bill_references(synthetic_image_rates):
    assert estimate_image_cost("test-cheap-image", 3, ref_count=10) == approx(0.03)


def test_fast_image_alias_estimates_reference_input_images(synthetic_image_rates):
    # Synthetic per-image price includes each reference input.
    assert estimate_image_cost("test-reference-image", 1, ref_count=0) == 0.0336
    assert estimate_image_cost("test-reference-image", 1, ref_count=4) == approx(0.03472)
    assert (
        provider_usd_to_credits(estimate_image_cost("test-reference-image", 1, ref_count=4)) == 4
    )


def test_per_megapixel_image_pricing_rounds_output_and_references(synthetic_image_rates):
    # test-megapixel-image bills the generated image as first MP + extra MP,
    # and each reference image by rounded megapixels.
    # output 1920x1080 = 2MP: $0.03 + $0.015
    # references 512x512 + 1600x900 = 1MP + 2MP: 3 * $0.015
    assert estimate_image_cost(
        "test-megapixel-image",
        1,
        width=1920,
        height=1080,
        ref_count=2,
        ref_image_sizes=[(512, 512), (1600, 900)],
    ) == approx(0.09)


def test_provider_reported_cost_wins_over_cached_pricing():
    usage = UsageRecord(
        provider="openai",
        model="gpt-5.6-terra",
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


def test_pricing_snapshot_changes_when_overrides_change(tmp_path):
    cost_map = tmp_path / "prices.json"
    overrides = tmp_path / "overrides.yaml"
    cost_map.write_text('{"gpt-test": {"input_cost_per_token": 1e-6}}')
    overrides.write_text("aliases: {}\nmodel_overrides: {}\n")

    first = PricingResolver(
        cost_map_path=cost_map, overrides_path=overrides
    ).pricing_snapshot
    overrides.write_text(
        "aliases: {}\nmodel_overrides:\n  gpt-test:\n    output_cost_per_token: 2e-6\n"
    )
    second = PricingResolver(
        cost_map_path=cost_map, overrides_path=overrides
    ).pricing_snapshot

    assert first != second


def test_model_output_token_limit_resolves_alias_and_uses_fallback(tmp_path):
    cost_map = tmp_path / "prices.json"
    overrides = tmp_path / "overrides.yaml"
    cost_map.write_text('{"provider/model": {"max_output_tokens": 65536}}')
    overrides.write_text(
        "aliases:\n  gpt-5.6-terra: provider/model\nmodel_overrides: {}\n"
    )
    resolver = PricingResolver(
        cost_map_path=cost_map,
        overrides_path=overrides,
    )

    assert resolver.model_output_token_limit("gpt-5.6-terra") == 65_536
    assert resolver.model_output_token_limit("unknown", fallback=32_768) == 32_768


def test_audit_pricing_checks_all_selectable_models(monkeypatch):
    class _Resolver:
        def __init__(self):
            self.seen: list[str] = []

        def estimate_image_cost(self, model, count):
            self.seen.append(model)
            return SimpleNamespace(source="litellm_cost_map")

    resolver = _Resolver()
    monkeypatch.setattr(usage_module, "get_pricing_resolver", lambda: resolver)

    assert audit_pricing() == []

    expected_aliases = {model["id"] for model in models() if model["funding"] == "api"}
    assert expected_aliases.issubset(set(resolver.seen))


def test_committed_settlement_response_loss_preserves_incremental_zero():
    """Retry a committed tiny call without replacing its zero-credit audit row."""
    from unittest.mock import patch

    class Db:
        amount = None
        writes = 0
        responses = 0

        def rpc(self, name, params):
            return self

        def execute(self):
            if self.amount is None:
                # A previous call in this job already rounded the total up to 1.
                self.amount = 0
                self.writes += 1
            self.responses += 1
            if self.responses == 1:
                raise TimeoutError("committed, response lost")
            return SimpleNamespace(data=self.amount)

        def table(self, name):
            return self

        def upsert(self, payload, **kwargs):
            self.amount = payload["amount_credits"]
            self.writes += 1
            return self

    db = Db()
    usage = UsageRecord(provider="openai", model="gpt-5.6-terra", operation="text", input_tokens=1)
    with patch("novel_to_comic.server.credits.usage_to_credit_debit", return_value=(1, 0.001)):
        debit_model_usage(db, "user", None, usage, description="small call", job_id="job")
    assert db.amount == 0
    assert db.writes == 1


def test_unresolved_settlement_retains_authorization():
    import pytest
    from unittest.mock import MagicMock, patch
    from novel_to_comic.server import credits

    db = MagicMock()
    db.rpc.return_value.execute.side_effect = TimeoutError("outcome unknown")
    usage = UsageRecord(provider="openai", model="gpt-5.6-terra", operation="text", input_tokens=1)
    with patch.dict(credits._reservation_jobs, {"hold": "job"}), \
         patch.object(credits, "_unsettled_jobs", set()), \
         patch.object(credits, "usage_to_credit_debit", return_value=(1, 0.001)):
        with pytest.raises(TimeoutError):
            debit_model_usage(db, "user", None, usage, description="small call", job_id="job")
        credits.release_reservation(db, "hold")
    db.table.assert_not_called()


def test_subscription_usage_bypasses_tariffs_and_minimum_without_inventing_spend(synthetic_image_rates):
    from novel_to_comic.server.credits import usage_to_credit_debit
    from novel_to_comic.usage import usage_has_billable_activity

    usage = UsageRecord(
        provider="openai", model="test-token-image", operation="image",
        input_tokens=1000, output_tokens=2000, image_count=1,
        funding="codex_subscription",
    )
    assert usage.cost_usd is None
    assert calculate_cost_breakdown(usage).source == "codex_subscription"
    assert usage_to_credit_debit(usage) == (0, 0.0)
    assert not usage_has_billable_activity(usage)
    # Even contradictory provider dollars cannot cross the funding boundary.
    assert usage_to_credit_debit(usage.model_copy(update={"cost_usd": 100.0})) == (0, 0.0)
    assert calculate_cost(usage.model_copy(update={"funding": "api"})) == approx(0.065)


def test_api_zero_dollars_with_activity_retains_minimum():
    from novel_to_comic.server.credits import usage_to_credit_debit

    usage = UsageRecord(
        provider="openai", model="gpt-5.6-terra", operation="text",
        input_tokens=1, cost_usd=0,
    )
    assert usage_to_credit_debit(usage) == (1, 0.0)


def test_small_call_thinking_allowance_tracks_recorded_style_usage():
    # Recorded totals, 45 days to 2026-10-27: Argon Style briefs billed p95 160
    # output tokens and proof copy 66; Flash briefs reached 1,356 when they thought.
    brief = 200 + thinking_allowance("gemini-4-argon", 900, 200)
    copy = 100 + thinking_allowance("gemini-4-argon", 700, 100)
    assert 1_356 <= brief < 2_000
    assert 1_356 <= copy < brief
    flat = get_flat_estimate("gemini-4-argon", 900 * 4, 800)
    assert estimate_text_cost("gemini-4-argon", 900 * 4, output_chars=800) < flat / 2


def test_large_call_thinking_allowance_keeps_the_route_ceiling():
    assert thinking_allowance("gemini-4-argon", 12_000, 9_000) == 4_096
    assert thinking_allowance("claude-opus-5-5", 30_000, 8_000) == 4_096
    assert thinking_allowance("mimo-v2.6-pro", 900, 200) == 0


def get_flat_estimate(model: str, input_chars: int, output_chars: int) -> float:
    from novel_to_comic.model_costs import get_pricing_resolver
    from novel_to_comic.text_models import text_wire

    output = output_chars // 4 + text_wire(model).estimated_thinking_tokens
    return get_pricing_resolver().estimate_text_cost(model, input_chars // 4, output).cost_usd
