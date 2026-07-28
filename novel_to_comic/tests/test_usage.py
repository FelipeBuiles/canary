from types import SimpleNamespace

from pytest import approx

from novel_to_comic import usage as usage_module
from novel_to_comic.config import _QUALITY_PRESETS
from novel_to_comic.model_costs import PricingResolver
from novel_to_comic.server.credits import debit_model_usage, provider_usd_to_credits
from novel_to_comic.usage import (
    UsageRecord,
    audit_pricing,
    calculate_cost,
    calculate_cost_breakdown,
    estimate_image_cost,
)


def test_image_alias_with_token_usage_uses_resolved_provider_token_pricing():
    usage = UsageRecord(
        provider="openai",
        model="gpt-image-2",
        operation="image",
        input_tokens=1000,
        output_tokens=2000,
        image_count=1,
    )

    assert calculate_cost(usage) == 0.065


def test_token_priced_image_model_uses_token_pricing():
    usage = UsageRecord(
        provider="openai",
        model="gpt-image-2",
        operation="image",
        input_tokens=1000,
        output_tokens=2000,
        image_count=1,
    )

    assert calculate_cost(usage) == 0.065


def test_image_alias_without_token_usage_uses_resolved_per_image_estimate():
    usage = UsageRecord(
        provider="openai",
        model="gpt-image-2",
        operation="image",
        image_count=1,
    )

    # Actual usage with no token data still falls through to output_cost_per_image.
    assert calculate_cost(usage) == 0.03168


def test_token_priced_image_alias_estimates_via_quality_token_table():
    # gpt-image-2 is token-priced. The override yaml
    # supplies image_output_tokens_by_quality so estimates scale by quality.
    # 2 images × 1056 (auto/medium) × $0.00003 = $0.06336
    assert estimate_image_cost("gpt-image-2", 2) == approx(0.06336)
    # 2 images × 4160 (high) × $0.00003 = $0.2496
    assert estimate_image_cost("gpt-image-2", 2, quality="high") == approx(0.2496)


def test_balanced_image_alias_estimates_nano_banana_2_cost():
    # image-balanced -> Nano Banana 2 at the complete-page 2K tier: $0.101/image.
    assert estimate_image_cost("image-balanced", 2) == approx(0.202)


def test_fast_image_alias_estimates_reference_input_images():
    # image-fast -> nano banana 2 lite (gemini-3.1-flash-lite-image): $0.0336/image.
    assert estimate_image_cost("image-fast", 1, ref_count=0) == 0.0336
    assert estimate_image_cost("image-fast", 1, ref_count=4) == approx(0.03472)
    assert (
        provider_usd_to_credits(estimate_image_cost("image-fast", 1, ref_count=4)) == 4
    )


def test_per_megapixel_image_pricing_rounds_output_and_references():
    # fal-ai/flux-2-pro/edit bills the generated image as first MP + extra MP,
    # and each reference image by rounded megapixels.
    # output 1920x1080 = 2MP: $0.03 + $0.015
    # references 512x512 + 1600x900 = 1MP + 2MP: 3 * $0.015
    assert estimate_image_cost(
        "fal-ai/flux-2-pro/edit",
        1,
        width=1920,
        height=1080,
        ref_count=2,
        ref_image_sizes=[(512, 512), (1600, 900)],
    ) == approx(0.09)


def test_provider_reported_cost_wins_over_cached_pricing():
    usage = UsageRecord(
        provider="openai",
        model="plan-balanced",
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
        "aliases:\n  adapt-balanced: provider/model\nmodel_overrides: {}\n"
    )
    resolver = PricingResolver(
        cost_map_path=cost_map,
        overrides_path=overrides,
    )

    assert resolver.model_output_token_limit("adapt-balanced") == 65_536
    assert resolver.model_output_token_limit("unknown", fallback=32_768) == 32_768


def test_audit_pricing_checks_all_quality_preset_aliases(monkeypatch):
    class _Resolver:
        def __init__(self):
            self.seen: list[str] = []

        def estimate_image_cost(self, model, count):
            self.seen.append(model)
            return SimpleNamespace(source="litellm_cost_map")

    resolver = _Resolver()
    monkeypatch.setattr(usage_module, "get_pricing_resolver", lambda: resolver)

    assert audit_pricing() == []

    expected_aliases = {
        alias for preset in _QUALITY_PRESETS.values() for alias in preset.values()
    }
    assert expected_aliases.issubset(set(resolver.seen))


def test_debit_model_usage_persists_pricing_snapshot():
    class _Table:
        def __init__(self):
            self.payload = None
            self.on_conflict = None

        def upsert(self, payload, *, on_conflict):
            self.payload = payload
            self.on_conflict = on_conflict
            return self

        def execute(self):
            return SimpleNamespace(data=[])

    class _Db:
        def __init__(self):
            self.table_obj = _Table()

        def table(self, name):
            assert name == "credit_ledger"
            return self.table_obj

    db = _Db()
    usage = UsageRecord(
        provider="openai",
        model="plan-balanced",
        provider_model="openai/gpt-5.4-mini",
        operation="text",
        input_tokens=1000,
        output_tokens=1000,
    )

    debit_model_usage(
        db,
        "user_1",
        "project_1",
        usage,
        stage="plan",
        description="Model call",
        job_id="00000000-0000-0000-0000-000000000001",
    )

    assert db.table_obj.on_conflict == "usage_call_id"
    assert db.table_obj.payload["pricing_snapshot"]


def test_debit_model_usage_prefers_atomic_job_level_settlement():
    class _Rpc:
        def execute(self):
            return SimpleNamespace(data=1)

    class _Db:
        def __init__(self):
            self.name = None
            self.params = None

        def rpc(self, name, params):
            self.name = name
            self.params = params
            return _Rpc()

        def table(self, _name):  # pragma: no cover - assertion helper
            raise AssertionError("atomic RPC should own the insert")

    db = _Db()
    usage = UsageRecord(
        provider="gemini",
        model="prompt-balanced",
        provider_model="vertex_ai/gemini-3.1-flash-lite",
        operation="text",
        input_tokens=800,
        output_tokens=200,
    )

    debit_model_usage(
        db,
        "user_1",
        "project_1",
        usage,
        stage="style",
        description="Model call: style.suggest",
        job_id="00000000-0000-0000-0000-000000000001",
    )

    assert db.name == "settle_model_usage_credits"
    assert db.params["p_usage_call_id"] == usage.call_id
    assert db.params["p_cost_usd"] > 0
    assert db.params["p_credits_per_usd"] > 0
