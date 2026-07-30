"""Characterization tests for application-level image model routes."""

from pathlib import Path

import pytest
import yaml

from novel_to_comic.image_models import (
    IMAGE_MODEL_ALIASES,
    ImageRoute,
    describe_image_model,
)


@pytest.mark.parametrize(
    ("alias", "route", "provider_model", "display_name"),
    [
        (
            "image-fast",
            ImageRoute.GEMINI_FLASH_LITE,
            "vertex-multimodal/gemini-3.1-flash-lite-image",
            "Fast — Gemini 3.1 Flash Lite Image",
        ),
        (
            "image-balanced",
            ImageRoute.GEMINI_PRO_IMAGE,
            "vertex-multimodal/gemini-3-pro-image",
            "Balanced — Gemini 3 Pro Image (Nano Banana Pro)",
        ),
        (
            "image-quality",
            ImageRoute.GPT_IMAGE_2,
            "openai/gpt-image-2",
            "Quality — GPT Image 2",
        ),
        ("image-reve", ImageRoute.REVE, "reve/create", "Reve"),
    ],
)
def test_production_alias_route_descriptions(
    alias: str,
    route: ImageRoute,
    provider_model: str,
    display_name: str,
):
    description = describe_image_model(alias)

    assert description.route is route
    assert description.provider_model == provider_model
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
        assert describe_image_model(alias).provider_model == provider_model


@pytest.mark.parametrize("model", ["reve/create", "reve/remix", "reve/custom"])
def test_literal_reve_models_are_classified(model: str):
    assert describe_image_model(model).route is ImageRoute.REVE


@pytest.mark.parametrize("model", ["gpt-image-2", "openai/gpt-image-2"])
def test_literal_gpt_image_2_models_are_classified(model: str):
    description = describe_image_model(model)

    assert description.route is ImageRoute.GPT_IMAGE_2
    assert description.display_name == "GPT Image 2"


@pytest.mark.parametrize(
    "model",
    ["fal-queue/bytedance/seedream/v5/pro/edit", "bytedance/seedream/v5/pro/edit"],
)
def test_literal_seedream_models_are_classified(model: str):
    assert describe_image_model(model).route is ImageRoute.SEEDREAM


def test_unknown_model_has_truthful_fallback_description():
    description = describe_image_model("custom/provider-model")

    assert description.route is ImageRoute.UNKNOWN
    assert description.display_name == "custom/provider-model"
    assert description.provider_model == "custom/provider-model"
