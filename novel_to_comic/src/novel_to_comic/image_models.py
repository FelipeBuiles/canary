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


# Slice 04 — verified reference capabilities needed before reference selection.
#
# The reference plan (novel_to_comic.image_references) is the ONLY layer that
# applies the route's hard cap and role restrictions. No later prompt or
# provider layer may select, cap, or reorder references, so these capability
# numbers must be the final word on how many references can be uploaded.
#
# Deliberately scoped: prompt-length, aspect, and generation-control fields are
# added in later slices (05/06). Only what reference selection needs lives here.

# Reference roles a route can accept. Mirrors the provider RefRole literal so
# prompt-domain code can ask capability questions without importing HTTP types.
_ALL_REFERENCE_ROLES: tuple[str, ...] = (
    "subject",
    "prop",
    "continuity",
    "style",
    "location_plate",
)


@dataclass(frozen=True, slots=True)
class ImageModelProfile:
    """Verified reference capabilities for one image route.

    ``max_references`` is the route's HARD reference cap: the reference plan
    must never select more references than this. ``supported_roles`` is the set
    of reference roles the route accepts; roles outside it are dropped with
    ``unsupported_role`` before final ordering.

    Construct via :func:`image_model_profile` (or :func:`image_model_profile_for`),
    never inline — the numbers live in one place so characterization tests can
    pin them.
    """

    route: ImageRoute
    max_references: int
    supported_roles: frozenset[str]

    @property
    def accepts_contextual_refs(self) -> bool:
        """True when non-subject roles (style/location/prop/continuity) are
        usable at all on this route. Some routes keep everything text-only."""
        return any(r != "subject" for r in self.supported_roles)


# Hard reference caps per route. Reve accepts at most 4 reference images; the
# Gemini Flash Lite route accepts many more (the contents-list has headroom),
# and GPT Image 2 processes every supplied image at high fidelity so it keeps
# references to identity only.
_ROUTE_REFERENCE_CAPS: dict[ImageRoute, int] = {
    ImageRoute.REVE: 4,
    ImageRoute.GEMINI_FLASH_LITE: 10,
    ImageRoute.GPT_IMAGE_2: 4,
    ImageRoute.UNKNOWN: 10,
}


def _profile_for_route(route: ImageRoute) -> ImageModelProfile:
    if route is ImageRoute.GPT_IMAGE_2:
        # GPT Image 2 treats every supplied image as edit conditioning; keep it
        # to identity only (subjects + props). Style samples and location plates
        # leak texture/noise and repeated backgrounds.
        return ImageModelProfile(
            route=route,
            max_references=_ROUTE_REFERENCE_CAPS[route],
            supported_roles=frozenset({"subject", "prop"}),
        )
    return ImageModelProfile(
        route=route,
        max_references=_ROUTE_REFERENCE_CAPS[route],
        supported_roles=frozenset(_ALL_REFERENCE_ROLES),
    )


def image_model_profile(model: str) -> ImageModelProfile:
    """Reference capabilities for an effective image model string.

    ``model`` follows the same classification rules as
    :func:`describe_image_model`. The profile is derived from the resolved
    route, so aliases and literal provider model strings resolve consistently.
    """
    return _profile_for_route(describe_image_model(model).route)


def image_model_profile_for_config(config) -> ImageModelProfile:
    """Reference capabilities for a ``Config``'s effective image model."""
    return image_model_profile(config.effective_image_model())
