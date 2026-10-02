"""Gemini 3.8 Flash is selectable through the Gemini API (AI Studio key) route."""
from pathlib import Path

import pytest
import yaml

from novel_to_comic.clients.text import provider_for_model
from novel_to_comic.model_catalog import allowed_models
from novel_to_comic.model_costs import get_pricing_resolver
from novel_to_comic.text_models import default_reasoning, text_wire

GATEWAY = Path(__file__).resolve().parents[2] / "litellm" / "config.yaml"


def _route(alias):
    return next(item for item in yaml.safe_load(GATEWAY.read_text())["model_list"]
                if item["model_name"] == alias)


def test_gemini_api_route_and_model_selection():
    route = _route("gemini-3.8-flash")
    assert route["litellm_params"]["model"] == "gemini/gemini-3.8-flash"
    assert route["litellm_params"]["api_key"] == "os.environ/GEMINI_API_KEY"
    assert provider_for_model("gemini-3.8-flash") == "gemini"
    wire = text_wire("gemini-3.8-flash")
    assert not wire.temperature and wire.effort == "medium"
    assert default_reasoning("gemini-3.8-flash") == "medium"
    for stage in ("extract", "brief", "adapt", "plan", "prompt", "ocr", "visual_review"):
        assert "gemini-3.8-flash" in allowed_models(stage)
    assert "gemini-3.8-flash" not in allowed_models("draw")


@pytest.mark.parametrize("model", ["gemini-3.8-flash", "gemini/gemini-3.8-flash"])
def test_gemini_estimate_uses_pinned_rates(model):
    resolver = get_pricing_resolver()
    quote = resolver.estimate_text_cost(model, 100_000, 100_000)
    assert quote.cost_usd == pytest.approx(0.075 + 0.375)
    assert resolver.model_output_token_limit(model) == 65_536
