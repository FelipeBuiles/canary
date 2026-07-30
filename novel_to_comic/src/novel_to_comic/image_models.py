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
_GEMINI_PRO_IMAGE_MODEL = "vertex-multimodal/gemini-3-pro-image"
_GPT_IMAGE_2_MODEL = "openai/gpt-image-2"
_SEEDREAM_V5_PRO_MODEL = "fal-queue/bytedance/seedream/v5/pro/edit"
_REVE_CREATE_MODEL = "reve/create"


class ImageRoute(str, Enum):
    """Stable application routes independent of mutable UI tier labels."""

    GEMINI_FLASH_LITE = "gemini_flash_lite"
    GEMINI_PRO_IMAGE = "gemini_pro_image"
    SEEDREAM = "seedream"
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
        route=ImageRoute.GEMINI_PRO_IMAGE,
        display_name="Balanced — Gemini 3 Pro Image (Nano Banana Pro)",
        provider_model=_GEMINI_PRO_IMAGE_MODEL,
    ),
    GATEWAY_IMAGE_QUALITY: ImageModelDescription(
        route=ImageRoute.GPT_IMAGE_2,
        display_name="Quality — GPT Image 2",
        provider_model=_GPT_IMAGE_2_MODEL,
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
    if normalized == _GEMINI_PRO_IMAGE_MODEL:
        return ImageModelDescription(
            route=ImageRoute.GEMINI_PRO_IMAGE,
            display_name="Gemini 3 Pro Image (Nano Banana Pro)",
            provider_model=normalized,
        )
    if normalized in {
        _SEEDREAM_V5_PRO_MODEL,
        "bytedance/seedream/v5/pro/edit",
    } or "seedream" in normalized:
        return ImageModelDescription(
            route=ImageRoute.SEEDREAM,
            display_name="Seedream 5.0 Pro",
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
# Slice 06 extends the profile with verified prompt-character limits, native
# aspect modes, and supported generation controls. The compiler budgets and
# trims prompt sections against ``prompt_char_limit`` and rejects unsupported
# controls; no provider may prefix-slice protected material later.

# Reference roles a route can accept. Mirrors the provider RefRole literal so
# prompt-domain code can ask capability questions without importing HTTP types.
_ALL_REFERENCE_ROLES: tuple[str, ...] = (
    "subject",
    "prop",
    "continuity",
    "style",
    "location_plate",
)

#: Verified generation controls the application understands. Each route enables
#: a subset; controls outside ``supported_controls`` are rejected by the
#: compiler before they reach transport (no phantom parameter that is silently
#: dropped or, worse, implies a parameter the provider never receives).
_ALL_CONTROLS: tuple[str, ...] = (
    "quality",
    "seed",
    "negative_prompt",
    "guidance_scale",
    "steps_override",
)

#: Verified prompt-character limits per route.
#
# - REVE: the v2 ``prompt`` field is capped at 4000 chars. The compiler budgets
#   against this so protected material never enters a provider-side slice.
# - GEMINI_FLASH_LITE / GPT_IMAGE_2: the OpenAI-compatible ``prompt`` field has
#   no hard provider cap below the model context window, but a generous budget
#   keeps prompts focused. ``None`` means no compiler-applied character budget
#   (the route has no provider-side prefix slice that threatens protected
#   content).
_PROMPT_CHAR_LIMITS: dict[ImageRoute, int | None] = {
    ImageRoute.REVE: 4000,
    ImageRoute.GEMINI_FLASH_LITE: None,
    ImageRoute.GEMINI_PRO_IMAGE: None,
    ImageRoute.SEEDREAM: None,
    ImageRoute.GPT_IMAGE_2: None,
    ImageRoute.UNKNOWN: None,
}

#: Native aspect modes a route accepts. Used to represent the aspect intent
#: structurally rather than as prose. Empty tuple means the route has no
#: dedicated aspect parameter (it derives aspect from width/height only).
_NATIVE_ASPECTS: dict[ImageRoute, tuple[str, ...]] = {
    ImageRoute.REVE: (
        "4:1", "3:1", "21:9", "2:1", "17:9", "16:9", "3:2", "4:3",
        "5:4", "1:1", "4:5", "3:4", "2:3", "9:16", "1:2", "1:3", "1:4",
    ),
    ImageRoute.GEMINI_FLASH_LITE: (),
    ImageRoute.GEMINI_PRO_IMAGE: (),
    ImageRoute.SEEDREAM: (),
    ImageRoute.GPT_IMAGE_2: (),
    ImageRoute.UNKNOWN: (),
}

#: Verified per-route control support.
#
# - quality: the OpenAI-compatible ``quality`` parameter (litellm_http forwards
#   ``config.image_quality`` for GEMINI_FLASH_LITE / GPT_IMAGE_2).
# - seed / negative_prompt / guidance_scale / steps_override: no production
#   route forwards these today, so they are unsupported (phantom) until a route
#   is verified to send them.
_SUPPORTED_CONTROLS: dict[ImageRoute, frozenset[str]] = {
    ImageRoute.REVE: frozenset(),
    ImageRoute.GEMINI_FLASH_LITE: frozenset({"quality"}),
    ImageRoute.GEMINI_PRO_IMAGE: frozenset({"quality"}),
    ImageRoute.SEEDREAM: frozenset({"quality"}),
    ImageRoute.GPT_IMAGE_2: frozenset({"quality"}),
    ImageRoute.UNKNOWN: frozenset(),
}


@dataclass(frozen=True, slots=True)
class ImageModelProfile:
    """Verified reference, prompt-budget, aspect, and control capabilities.

    Reference fields (Slice 04):
        ``max_references`` is the route's HARD reference cap; the reference plan
        must never select more. ``supported_roles`` is the set of reference
        roles the route accepts.

    Prompt-budget fields (Slice 06):
        ``prompt_char_limit`` is the verified character budget the compiler
        enforces. Protected anchors, active-state locks, reference instructions,
        and system constraints are non-truncatable; lower-priority scene prose
        is compressed first. ``None`` means no provider-side prefix slice
        threatens protected content (no compiler budget applied).

    Native-aspect fields (Slice 06):
        ``native_aspect_modes`` is the route's dedicated aspect parameter
        vocabulary. Empty tuple means the route derives aspect from
        width/height only.

    Control fields (Slice 06):
        ``supported_controls`` is the verified subset of generation controls the
        route actually forwards. Controls outside it are phantom: the compiler
        rejects them before transport so no UI/config knob implies a provider
        parameter that is never sent.

    Construct via :func:`image_model_profile` (or :func:`image_model_profile_for`),
    never inline — the numbers live in one place so characterization tests can
    pin them.
    """

    route: ImageRoute
    max_references: int
    supported_roles: frozenset[str]
    prompt_char_limit: int | None
    native_aspect_modes: tuple[str, ...]
    supported_controls: frozenset[str]

    @property
    def accepts_contextual_refs(self) -> bool:
        """True when non-subject roles (style/location/prop/continuity) are
        usable at all on this route. Some routes keep everything text-only."""
        return any(r != "subject" for r in self.supported_roles)

    def supports_control(self, name: str) -> bool:
        """True when the route forwards this generation control to the provider."""
        return name in self.supported_controls

    def native_aspect_for(self, aspect_ratio: float | None) -> str | None:
        """Map a numeric aspect ratio to the closest native aspect mode.

        Returns ``None`` when the route has no dedicated aspect parameter or
        no mode is close enough. Used to represent aspect structurally instead
        of as prose added by a handler.
        """
        if not self.native_aspect_modes or aspect_ratio is None or aspect_ratio <= 0:
            return None
        def _ratio(mode: str) -> float:
            w_s, h_s = mode.split(":")
            return int(w_s) / int(h_s)
        return min(
            self.native_aspect_modes,
            key=lambda m: abs(_ratio(m) - aspect_ratio),
        )


# Hard product reference caps per route. Reve v2 accepts at most 8 reference
# images, but Canary keeps its production selector at four to reduce
# conditioning noise; the Gemini Flash Lite route accepts many more
# (the contents-list has headroom),
# and GPT Image 2 processes every supplied image at high fidelity, so Canary
# keeps a conservative four-reference budget. Context-specific selectors may
# further narrow roles (for example, panel generation keeps style text-only).
_ROUTE_REFERENCE_CAPS: dict[ImageRoute, int] = {
    ImageRoute.REVE: 4,
    ImageRoute.GEMINI_FLASH_LITE: 10,
    ImageRoute.GEMINI_PRO_IMAGE: 10,
    ImageRoute.SEEDREAM: 10,
    ImageRoute.GPT_IMAGE_2: 4,
    ImageRoute.UNKNOWN: 10,
}


def _profile_for_route(route: ImageRoute) -> ImageModelProfile:
    return ImageModelProfile(
        route=route,
        max_references=_ROUTE_REFERENCE_CAPS[route],
        supported_roles=frozenset(_ALL_REFERENCE_ROLES),
        prompt_char_limit=_PROMPT_CHAR_LIMITS[route],
        native_aspect_modes=_NATIVE_ASPECTS[route],
        supported_controls=_SUPPORTED_CONTROLS[route],
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
