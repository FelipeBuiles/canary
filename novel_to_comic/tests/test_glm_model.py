"""The selectable GLM model must use the exact paid OpenRouter route."""
from pathlib import Path

import pytest
import yaml

from novel_to_comic.clients.text import provider_for_model
from novel_to_comic.model_catalog import allowed_models
from novel_to_comic.model_costs import get_pricing_resolver


def test_glm_route_and_structured_output_routing():
    gateway = Path(__file__).resolve().parents[2] / "litellm" / "config.yaml"
    route = next(item["litellm_params"] for item in yaml.safe_load(gateway.read_text())["model_list"] if item["model_name"] == "glm-5.3-flash")
    assert route["model"] == "openrouter/z-ai/glm-5.3-flash"
    assert route["api_key"] == "os.environ/OPENROUTER_API_KEY"
    assert route["extra_body"]["provider"]["require_parameters"] is True
    assert route["extra_body"]["provider"]["ignore"] == ["wafer", "venice"]
    assert provider_for_model("glm-5.3-flash") == "openrouter"
    for stage in ("extract", "brief", "adapt", "plan", "prompt", "ocr", "visual_review"):
        assert "glm-5.3-flash" in allowed_models(stage)
    assert "glm-5.3-flash" not in allowed_models("draw")


def test_glm_standard_token_estimate():
    quote = get_pricing_resolver().estimate_text_cost("glm-5.3-flash", 1_000_000, 1_000_000)
    assert quote.cost_usd == pytest.approx(0.65)
