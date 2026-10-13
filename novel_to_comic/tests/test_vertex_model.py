"""Gemini text selections use Vertex billing and account for thinking."""
from pathlib import Path

import pytest
import yaml

from novel_to_comic.clients.text import provider_for_model
from novel_to_comic.model_catalog import allowed_models
from novel_to_comic.model_costs import get_pricing_resolver
from novel_to_comic.text_models import reasoning_options, text_wire


def test_gemini_selection_is_vertex_text_and_vision_only():
    gateway = Path(__file__).resolve().parents[2] / "litellm/config.yaml"
    route = next(item["litellm_params"] for item in yaml.safe_load(gateway.read_text())["model_list"]
                 if item["model_name"] == "gemini-3.8-flash")
    assert route["model"] == "vertex_ai/gemini-3.8-flash"
    assert route["vertex_project"] == "os.environ/VERTEXAI_PROJECT"
    assert route["vertex_location"] == "os.environ/VERTEXAI_LOCATION"
    assert "api_key" not in route
    assert provider_for_model("gemini-3.8-flash") == "vertex_ai"
    for stage in ("extract", "brief", "adapt", "plan", "prompt", "ocr", "visual_review"):
        assert "gemini-3.8-flash" in allowed_models(stage)
    assert "gemini-3.8-flash" not in allowed_models("draw")
    assert reasoning_options("gemini-3.8-flash") == ("low", "medium", "high")
    wire = text_wire("gemini-3.8-flash")
    assert wire.vision and wire.effort == "low"


@pytest.mark.parametrize("model", ["gemini-3.8-flash", "vertex_ai/gemini-3.8-flash"])
def test_gemini_global_prices_include_cached_input_and_model_output_limit(model):
    resolver = get_pricing_resolver()
    quote = resolver.estimate_text_cost(model, 1_000_000, 1_000_000)
    assert quote.cost_usd == pytest.approx(4.5)
    assert resolver.model_output_token_limit(model) == 65_536
