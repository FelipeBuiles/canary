"""Retired GLM routing and pricing stay outside the active configuration."""
from pathlib import Path

import pytest
import yaml

from novel_to_comic.clients.text import provider_for_model
from novel_to_comic.model_catalog import allowed_models
from novel_to_comic.model_costs import get_pricing_resolver


def test_glm_is_not_an_active_generation_route():
    gateway = Path(__file__).resolve().parents[2] / "litellm" / "config.yaml"
    aliases = {item["model_name"] for item in yaml.safe_load(gateway.read_text())["model_list"]}
    assert "glm-5.3-flash" not in aliases
    with pytest.raises(ValueError, match="Unknown text model"):
        provider_for_model("glm-5.3-flash")
    for stage in ("extract", "brief", "adapt", "plan", "prompt", "ocr", "visual_review"):
        assert "glm-5.3-flash" not in allowed_models(stage)
    assert "glm-5.3-flash" not in allowed_models("draw")


def test_retired_glm_token_estimate_has_unknown_pricing():
    quote = get_pricing_resolver().estimate_text_cost("glm-5.3-flash", 1_000_000, 1_000_000)
    assert quote.source == "unknown_pricing"
    assert quote.cost_usd == 0.0
