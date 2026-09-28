import os
import time

import pytest

from novel_to_comic.server import app as server_app


def test_every_model_the_pipeline_uses_has_pricing():
    """A gateway alias without pricing refuses to boot in production.

    Adding a model to MODEL_REGISTRY without its `aliases` entry in
    litellm_pricing_overrides.yaml is a deploy-time failure, so the audit that
    detects it runs in the suite rather than only at startup.
    """
    from novel_to_comic.usage import audit_pricing

    assert audit_pricing() == []


def test_pricing_audit_requires_api_prices_only(monkeypatch):
    from novel_to_comic import model_catalog
    from novel_to_comic.usage import audit_pricing

    monkeypatch.setattr(model_catalog, "models", lambda: [
        {"id": "codex-dev/text/gpt-5.5", "funding": "codex_subscription"},
        {"id": "missing-api-price", "funding": "api"},
    ])
    assert audit_pricing() == ["missing-api-price"]


def test_pricing_audit_raises_in_production(monkeypatch):
    monkeypatch.setattr(server_app, "audit_pricing", lambda: ["missing-model"])
    monkeypatch.setenv("CANARY_ENV", "production")

    with pytest.raises(RuntimeError, match="missing-model"):
        server_app._audit_pricing_at_startup()


def test_pricing_audit_warns_in_development(monkeypatch, caplog):
    monkeypatch.setattr(server_app, "audit_pricing", lambda: ["missing-model"])
    monkeypatch.setenv("CANARY_ENV", "dev")

    with caplog.at_level("WARNING", logger=server_app.__name__):
        server_app._audit_pricing_at_startup()

    assert "missing-model" in caplog.text


def test_stale_pricing_cache_refreshes(monkeypatch, tmp_path):
    cache_path = tmp_path / "litellm_model_prices.cached.json"
    cache_path.write_text("{}")
    old = time.time() - (8 * 86400)
    os.utime(cache_path, (old, old))
    calls = []

    def _refresh(*, output_path, timeout_seconds):
        calls.append((output_path, timeout_seconds))
        return {"output_path": str(output_path)}

    monkeypatch.setenv("PULP_PRICING_REFRESH_DAYS", "7")
    monkeypatch.setattr(server_app, "refresh_litellm_cost_cache", _refresh)

    server_app._refresh_pricing_if_stale(cache_path)

    assert calls == [(cache_path, 10)]


def test_fresh_pricing_cache_skips_refresh(monkeypatch, tmp_path):
    cache_path = tmp_path / "litellm_model_prices.cached.json"
    cache_path.write_text("{}")
    calls = []

    monkeypatch.setenv("PULP_PRICING_REFRESH_DAYS", "7")
    monkeypatch.setattr(server_app, "refresh_litellm_cost_cache", lambda **kwargs: calls.append(kwargs))

    server_app._refresh_pricing_if_stale(cache_path)

    assert calls == []


def test_pricing_overrides_cover_only_active_gateway_routes():
    from pathlib import Path
    import yaml
    from novel_to_comic.model_costs import DEFAULT_OVERRIDES_PATH

    overrides = yaml.safe_load(DEFAULT_OVERRIDES_PATH.read_text())
    root = Path(__file__).resolve().parents[2]
    routes = yaml.safe_load((root / "litellm/config.yaml").read_text())["model_list"]
    assert set(overrides["aliases"]) == {route["model_name"] for route in routes}
    # An override may use the exact provider target or its unprefixed model id.
    targets = set(overrides["aliases"].values())
    candidates = targets | {target.split("/", 1)[1] for target in targets}
    assert set(overrides["model_overrides"]) <= candidates
    assert {key for key, value in overrides["model_overrides"].items()
            if value["mode"] == "image_generation"} == {
        "gpt-image-2.5-sunburst", "openai/gpt-image-2.5/sunburst",
    }
