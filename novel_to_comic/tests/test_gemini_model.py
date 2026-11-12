"""Gemini 3.8 Flash selections use the credited Vertex AI route."""
from pathlib import Path

import pytest
import yaml

from novel_to_comic.clients.text import provider_for_model
from novel_to_comic.model_catalog import allowed_models
from novel_to_comic.model_costs import get_pricing_resolver
from novel_to_comic.text_models import TEXT_MODELS, default_reasoning, text_wire

GATEWAY = Path(__file__).resolve().parents[2] / "litellm" / "config.yaml"


def _route(alias):
    return next(item for item in yaml.safe_load(GATEWAY.read_text())["model_list"]
                if item["model_name"] == alias)


def test_gemini_vertex_route_and_model_selection():
    assert sum(model.id == "gemini-3.8-flash" for model in TEXT_MODELS) == 1
    route = _route("gemini-3.8-flash")
    assert route["litellm_params"]["model"] == "vertex_ai/gemini-3.8-flash"
    assert route["litellm_params"]["vertex_project"] == "os.environ/VERTEXAI_PROJECT"
    assert "api_key" not in route["litellm_params"]
    assert provider_for_model("gemini-3.8-flash") == "vertex_ai"
    wire = text_wire("gemini-3.8-flash")
    assert not wire.temperature and wire.effort == "low"
    assert default_reasoning("gemini-3.8-flash") == "low"
    for stage in ("extract", "brief", "adapt", "plan", "prompt", "ocr", "visual_review"):
        assert "gemini-3.8-flash" in allowed_models(stage)
    assert "gemini-3.8-flash" not in allowed_models("draw")


@pytest.mark.parametrize("model", ["gemini-3.8-flash", "vertex_ai/gemini-3.8-flash"])
def test_gemini_estimate_uses_pinned_rates(model):
    resolver = get_pricing_resolver()
    quote = resolver.estimate_text_cost(model, 100_000, 100_000)
    assert quote.cost_usd == pytest.approx(0.075 + 0.375)
    assert resolver.model_output_token_limit(model) == 65_536


def test_carbon_is_optional_json_text_in_labs_and_all_text_stages():
    from novel_to_comic.labs.stage_models import resolve_stage_reasoning, selectable_models
    from novel_to_comic.model_catalog import default_selections
    from novel_to_comic.text_models import reasoning_options

    route = _route("gemini-4-carbon")
    assert route["litellm_params"] == {
        "model": "vertex_ai/gemini-4-carbon",
        "vertex_project": "os.environ/VERTEXAI_PROJECT",
        "vertex_location": "os.environ/VERTEXAI_LOCATION",
        "thinkingConfig": {"thinkingLevel": "low", "includeThoughts": True},
    }
    assert provider_for_model("gemini-4-carbon") == "vertex_ai"
    wire = text_wire("gemini-4-carbon")
    assert wire.schema_instructions and wire.json_mode
    assert wire.vision
    assert not any((wire.temperature, wire.streaming))
    assert wire.max_output_tokens is None
    assert reasoning_options(wire.id) == ("low", "medium", "high")
    # Labs 20261013-143611-7df22e: Low matched Medium through Plan.
    assert default_reasoning(wire.id) == "low"
    assert default_reasoning(wire.id, "high") == "high"
    assert wire.native_vertex_thinking and wire.effort == "low"
    assert resolve_stage_reasoning({"extract": wire.id, "brief": wire.id}) == {"extract": "low", "brief": "low"}
    assert wire.id in {model["id"] for model in selectable_models()}
    for stage in ("extract", "brief", "adapt", "plan", "prompt", "ocr", "visual_review", "correction"):
        assert wire.id in allowed_models(stage)
    for stage in ("image", "draw"):
        assert wire.id not in allowed_models(stage)
    assert wire.id not in default_selections().values()
    # Image input verified through the gateway on 2026-10-13.
    assert route["model_info"]["supports_vision"] is True
    for capability in ("native_streaming", "prompt_caching"):
        assert route["model_info"][f"supports_{capability}"] is False
    assert route["model_info"]["supports_reasoning"] is True
    assert route["model_info"]["supports_response_schema"] is True
    assert "max_input_tokens" not in route["model_info"]
    assert "max_output_tokens" not in route["model_info"]


@pytest.mark.parametrize("model", ["gemini-4-carbon", "vertex_ai/gemini-4-carbon"])
def test_argon_provisional_pricing_registration(model):
    resolver = get_pricing_resolver()
    assert resolver.resolve_model("gemini-4-carbon") == "vertex_ai/gemini-4-carbon"
    assert resolver.estimate_text_cost(model, 1_000_000, 1_000_000).cost_usd == pytest.approx(12)
    assert _route("gemini-4-carbon")["model_info"]["cache_read_input_token_cost"] == 1e-7


def test_hydrogen_takes_carbon_settings_and_tuning_without_its_fallback():
    from novel_to_comic.gemini_tuning import tuned_request
    from novel_to_comic.model_catalog import default_selections
    from novel_to_comic.text_models import is_gemini_model, tuning_model

    route = _route("gemini-4-hydrogen")
    assert route["litellm_params"] == {
        "model": "vertex_ai/gemini-4-hydrogen",
        "vertex_project": "os.environ/VERTEXAI_PROJECT",
        "vertex_location": "os.environ/VERTEXAI_LOCATION",
        "thinkingConfig": {"thinkingLevel": "low", "includeThoughts": True},
    }
    def capabilities(alias):
        return {key: value for key, value in _route(alias)["model_info"].items() if "cost" not in key}

    assert capabilities("gemini-4-hydrogen") == capabilities("gemini-4-carbon")
    assert provider_for_model("gemini-4-hydrogen") == "vertex_ai"
    hydrogen, carbon = text_wire("gemini-4-hydrogen"), text_wire("gemini-4-carbon")
    differing = {name for name in hydrogen.__dataclass_fields__ if getattr(hydrogen, name) != getattr(carbon, name)}
    assert differing == {"id", "label", "tuning", "rate_limit_fallback"}
    # The approved Runware 429 switch covers Carbon only.
    assert hydrogen.rate_limit_fallback == ""
    assert tuning_model(hydrogen.id) == carbon.id and is_gemini_model(hydrogen.id)
    request = {"feature": "plan.map", "user_content": "Story.", "system_prompt": "Plan.",
               "json_schema": {"type": "object", "properties": {"ok": {"type": "boolean"}}}}
    assert tuned_request(hydrogen.id, request) == tuned_request(carbon.id, request)
    for stage in ("extract", "brief", "adapt", "plan", "prompt", "ocr", "visual_review", "correction"):
        assert hydrogen.id in allowed_models(stage)
    for stage in ("image", "draw"):
        assert hydrogen.id not in allowed_models(stage)
    assert hydrogen.id not in default_selections().values()


@pytest.mark.parametrize("model", ["gemini-4-hydrogen", "vertex_ai/gemini-4-hydrogen"])
def test_hydrogen_launch_pricing_registration(model):
    resolver = get_pricing_resolver()
    assert resolver.resolve_model("gemini-4-hydrogen") == "vertex_ai/gemini-4-hydrogen"
    assert resolver.estimate_text_cost(model, 1_000_000, 1_000_000).cost_usd == pytest.approx(9)
    assert _route("gemini-4-hydrogen")["model_info"]["cache_read_input_token_cost"] == 7.5e-8
