"""Truthful application-level descriptions of image generation routes."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


GATEWAY_IMAGE_FAST = "image-fast"
GATEWAY_IMAGE_BALANCED = "image-balanced"
GATEWAY_IMAGE_QUALITY = "image-quality"
GATEWAY_IMAGE_REVE = "image-reve"

IMAGE_MODEL_ALIASES = (
    GATEWAY_IMAGE_FAST,
    GATEWAY_IMAGE_BALANCED,
    GATEWAY_IMAGE_QUALITY,
    GATEWAY_IMAGE_REVE,
)

_GEMINI_FLASH_LITE_MODEL = "vertex-multimodal/gemini-3.1-flash-lite-image"
_REVE_CREATE_MODEL = "reve/create"


class ImageRoute(str, Enum):
    """Stable application routes independent of mutable UI tier labels."""

    GEMINI_FLASH_LITE = "gemini_flash_lite"
    REVE = "reve"
    GPT_IMAGE_2 = "gpt_image_2"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class ImageModelDescription:
    """Display and provider identity for one effective image model string."""

    route: ImageRoute
    display_name: str
    provider_model: str


_ALIAS_DESCRIPTIONS: dict[str, ImageModelDescription] = {
    GATEWAY_IMAGE_FAST: ImageModelDescription(
        route=ImageRoute.GEMINI_FLASH_LITE,
        display_name="Fast — Gemini 3.1 Flash Lite Image",
        provider_model=_GEMINI_FLASH_LITE_MODEL,
    ),
    GATEWAY_IMAGE_BALANCED: ImageModelDescription(
        route=ImageRoute.GEMINI_FLASH_LITE,
        display_name="Balanced — Gemini 3.1 Flash Lite Image",
        provider_model=_GEMINI_FLASH_LITE_MODEL,
    ),
    GATEWAY_IMAGE_QUALITY: ImageModelDescription(
        route=ImageRoute.REVE,
        display_name="Quality — Reve",
        provider_model=_REVE_CREATE_MODEL,
    ),
    GATEWAY_IMAGE_REVE: ImageModelDescription(
        route=ImageRoute.REVE,
        display_name="Reve",
        provider_model=_REVE_CREATE_MODEL,
    ),
}


def describe_image_model(model: str) -> ImageModelDescription:
    """Classify an effective model string and return truthful display metadata."""
    normalized = (model or "").strip().lower()
    if normalized in _ALIAS_DESCRIPTIONS:
        return _ALIAS_DESCRIPTIONS[normalized]
    if normalized in {"gpt-image-2", "openai/gpt-image-2"}:
        return ImageModelDescription(
            route=ImageRoute.GPT_IMAGE_2,
            display_name="GPT Image 2",
            provider_model=normalized,
        )
    if normalized.startswith("reve/"):
        return ImageModelDescription(
            route=ImageRoute.REVE,
            display_name="Reve",
            provider_model=normalized,
        )
    if normalized == _GEMINI_FLASH_LITE_MODEL:
        return ImageModelDescription(
            route=ImageRoute.GEMINI_FLASH_LITE,
            display_name="Gemini 3.1 Flash Lite Image",
            provider_model=normalized,
        )
    return ImageModelDescription(
        route=ImageRoute.UNKNOWN,
        display_name=(model or "").strip(),
        provider_model=(model or "").strip(),
    )
