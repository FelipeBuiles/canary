"""The selectable MiMo model must use the paid OpenRouter route."""
from pathlib import Path

import pytest
import yaml

from novel_to_comic.clients.text import provider_for_model
from novel_to_comic.model_catalog import allowed_models
from novel_to_comic.model_costs import get_pricing_resolver


def test_mimo_route_and_model_selection():
    gateway = Path(__file__).resolve().parents[2] / "litellm" / "config.yaml"
    route = next(
        item["litellm_params"]
        for item in yaml.safe_load(gateway.read_text())["model_list"]
        if item["model_name"] == "mimo-v2.6-pro"
    )
    assert route["model"] == "openrouter/xiaomi/mimo-v2.6-pro"
    assert route["api_key"] == "os.environ/OPENROUTER_API_KEY"
    assert route["extra_body"]["provider"]["require_parameters"] is True
    assert provider_for_model("mimo-v2.6-pro") == "openrouter"
    for stage in ("extract", "brief", "adapt", "plan", "prompt", "ocr", "visual_review"):
        assert "mimo-v2.6-pro" in allowed_models(stage)
    assert "mimo-v2.6-pro" not in allowed_models("draw")


def test_mimo_standard_token_estimate():
    quote = get_pricing_resolver().estimate_text_cost("mimo-v2.6-pro", 1_000_000, 1_000_000)
    assert quote.cost_usd == pytest.approx(1.305)
