"""Characterization tests for application-level image model routes."""

from pathlib import Path

import pytest
import yaml

from novel_to_comic.image_models import (
    GATEWAY_IMAGE_SEEDREAM_TEST,
    IMAGE_MODEL_ALIASES,
    ImageRoute,
    describe_image_model,
)


@pytest.mark.parametrize(
    ("alias", "route", "provider_model", "provider_key", "display_name"),
    [
        (
            "image-gemini-flash-lite",
            ImageRoute.GEMINI_FLASH_LITE,
            "vertex-multimodal/gemini-3.1-flash-lite-image",
            "vertex-multimodal",
            "Gemini 3.1 Flash Lite Image",
        ),
        (
            "image-gemini-pro",
            ImageRoute.GEMINI_PRO_IMAGE,
            "vertex-multimodal/gemini-3-pro-image",
            "vertex-multimodal",
            "Gemini 3 Pro Image (Nano Banana Pro)",
        ),
        (
            "image-gpt-2",
            ImageRoute.GPT_IMAGE_2,
            "openai/gpt-image-2",
            "openai",
            "GPT Image 2",
        ),
        (
            "image-sunburst",
            ImageRoute.GPT_IMAGE_2,
            "gpt-image-2.5-sunburst",
            "openai-fal",
            "GPT Image 2.5 Sunburst",
        ),
        (
            "image-flare",
            ImageRoute.GPT_IMAGE_2,
            "openai/gpt-image-2.5-flare",
            "openai",
            "GPT Image 2.5 Flare",
        ),
        (
            "image-muse",
            ImageRoute.MUSE_IMAGE,
            "openrouter-image/meta/muse-image",
            "openrouter",
            "Muse Image",
        ),
    ],
)
def test_production_alias_route_descriptions(
    alias: str,
    route: ImageRoute,
    provider_model: str,
    provider_key: str,
    display_name: str,
):
    description = describe_image_model(alias)

    assert description.route is route
    assert description.provider_model == provider_model
    assert description.provider_key == provider_key
    assert description.display_name == display_name


def test_production_alias_descriptions_match_litellm_config():
    gateway_config = Path(__file__).resolve().parents[2] / "litellm" / "config.yaml"
    data = yaml.safe_load(gateway_config.read_text())
    configured_models = {
        item["model_name"]: item["litellm_params"]["model"]
        for item in data["model_list"]
        if item.get("model_name") in IMAGE_MODEL_ALIASES
    }

    assert set(configured_models) == set(IMAGE_MODEL_ALIASES)
    for alias, provider_model in configured_models.items():
        if describe_image_model(alias).provider_key == "openai-fal":
            continue  # Multi-route; its deployments are checked below.
        assert describe_image_model(alias).provider_model == provider_model


def test_sunburst_routes_match_their_gateway_deployments():
    from novel_to_comic.image_route_fallback import FAL_SUNBURST_GATEWAY_MODEL, OPENAI_SUNBURST_GATEWAY_MODEL

    gateway_config = Path(__file__).resolve().parents[2] / "litellm" / "config.yaml"
    deployments = {
        item["model_name"]: item["litellm_params"]["model"]
        for item in yaml.safe_load(gateway_config.read_text())["model_list"]
    }
    # The app alias names the OpenAI-first pair; each route is one deployment.
    assert deployments[OPENAI_SUNBURST_GATEWAY_MODEL] == "openai-stream/gpt-image-2.5-sunburst"
    assert deployments[FAL_SUNBURST_GATEWAY_MODEL] == "fal-queue/openai/gpt-image-2.5/sunburst"


def test_labs_seedream_gateway_alias_resolves_to_fal_provider():
    description = describe_image_model(GATEWAY_IMAGE_SEEDREAM_TEST)

    assert description.route is ImageRoute.SEEDREAM
    assert description.provider_key == "fal-queue"
    assert description.provider_model == "fal-queue/bytedance/seedream/v5/lite/edit"


@pytest.mark.parametrize("model", ["reve/create", "reve/remix", "reve/custom"])
def test_removed_reve_models_are_unknown(model: str):
    assert describe_image_model(model).route is ImageRoute.UNKNOWN


@pytest.mark.parametrize("model", ["gpt-image-2", "openai/gpt-image-2"])
def test_literal_gpt_image_2_models_are_classified(model: str):
    description = describe_image_model(model)

    assert description.route is ImageRoute.GPT_IMAGE_2
    assert description.provider_key == "openai"
    assert description.display_name == "GPT Image 2"


@pytest.mark.parametrize(
    "model",
    ["meta/muse-image", "openrouter/meta/muse-image", "openrouter-image/meta/muse-image"],
)
def test_literal_muse_models_are_classified(model: str):
    description = describe_image_model(model)

    assert description.route is ImageRoute.MUSE_IMAGE
    assert description.provider_key == "openrouter"
    assert description.display_name == "Muse Image"


@pytest.mark.parametrize(
    "model",
    ["fal-queue/bytedance/seedream/v5/pro/edit", "bytedance/seedream/v5/pro/edit"],
)
def test_literal_seedream_models_are_classified(model: str):
    assert describe_image_model(model).route is ImageRoute.SEEDREAM


def test_unknown_model_has_truthful_fallback_description():
    description = describe_image_model("custom/provider-model")

    assert description.route is ImageRoute.UNKNOWN
    assert description.provider_key == "unknown"
    assert description.display_name == "custom/provider-model"
    assert description.provider_model == "custom/provider-model"


def test_nano_banana_alias_and_provider_literals_have_documented_capabilities():
    from novel_to_comic.image_models import image_model_profile

    for model in ("image-nano-banana-2.1", "gemini-nano-banana-2.1",
                  "vertex_ai/gemini-nano-banana-2.1", "vertex-multimodal/gemini-nano-banana-2.1"):
        description = describe_image_model(model)
        profile = image_model_profile(model)
        assert description.display_name == "Nano Banana 2.1"
        assert profile.route == ImageRoute.NANO_BANANA_21
        assert profile.max_references == 14
        assert profile.supported_controls == frozenset({"quality"})
        assert profile.provider_key == "vertex-multimodal"
