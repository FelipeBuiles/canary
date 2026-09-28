"""DeepSeek V4.1 Flash is selectable through the Together gateway route."""
from pathlib import Path

import pytest
import yaml

from novel_to_comic.clients.text import provider_for_model
from novel_to_comic.model_catalog import allowed_models
from novel_to_comic.model_costs import get_pricing_resolver
from novel_to_comic.text_models import TEXT_MODELS

GATEWAY = Path(__file__).resolve().parents[2] / "litellm" / "config.yaml"


def _routes():
    return {item["model_name"]: item["litellm_params"]
            for item in yaml.safe_load(GATEWAY.read_text())["model_list"]}


def test_every_selectable_text_model_has_a_gateway_route():
    text_routes = {alias for alias in _routes() if not alias.startswith("image-")}
    assert text_routes == {model.id for model in TEXT_MODELS}


def test_deepseek_together_route_and_model_selection():
    route = _routes()["deepseek-v4.1-flash"]
    assert route["model"] == "together_ai/deepseek-ai/DeepSeek-V4.1-Flash"
    assert route["api_key"] == "os.environ/TOGETHER_API_KEY"
    assert route["extra_body"]["reasoning"] == {"enabled": False}
    assert "reasoning_effort" not in route
    assert provider_for_model("deepseek-v4.1-flash") == "together_ai"
    for stage in ("extract", "brief", "adapt", "plan", "prompt", "ocr", "visual_review"):
        assert "deepseek-v4.1-flash" in allowed_models(stage)
    assert "deepseek-v4.1-flash" not in allowed_models("draw")


@pytest.mark.parametrize("model", ["deepseek-v4.1-flash", "deepseek-ai/DeepSeek-V4.1-Flash"])
def test_deepseek_estimate_and_provider_reported_model_share_together_rates(model):
    resolver = get_pricing_resolver()
    quote = resolver.estimate_text_cost(model, 1_000_000, 1_000_000)
    assert quote.cost_usd == pytest.approx(1.5)
    assert resolver.model_output_token_limit(model) == 384_000
