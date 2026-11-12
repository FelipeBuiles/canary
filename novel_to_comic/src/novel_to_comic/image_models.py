"""Truthful application-level descriptions of image generation routes."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


GATEWAY_IMAGE_FAST = "image-gemini-flash-lite"
GATEWAY_IMAGE_BALANCED = "image-gemini-pro"
GATEWAY_IMAGE_QUALITY = "image-gpt-2"
GATEWAY_IMAGE_SUNBURST = "image-sunburst"
GATEWAY_IMAGE_SUNBURST_OPENAI = "image-sunburst-openai"
GATEWAY_IMAGE_FLARE = "image-flare"
#: GPT Image 2.5 through Runware (startup grant). No partial previews.
GATEWAY_IMAGE_SUNBURST_RUNWARE = "image-sunburst-runware"
GATEWAY_IMAGE_FLARE_RUNWARE = "image-flare-runware"
#: GPT Image 2.6 direct on OpenAI; Labs comparison routes only.
GATEWAY_IMAGE_SUNBURST_26 = "image-sunburst-2.6"
GATEWAY_IMAGE_FLARE_26 = "image-flare-2.6"
GATEWAY_IMAGE_SUNBURST_26_RUNWARE = "image-sunburst-2.6-runware"
GATEWAY_IMAGE_FLARE_26_RUNWARE = "image-flare-2.6-runware"
#: MiniMax H3 Image through Runware; Labs comparison routes only.
GATEWAY_IMAGE_MINIMAX_H3_RUNWARE = "image-minimax-h3-runware"
GATEWAY_IMAGE_MINIMAX_H3_HIGHSPEED_RUNWARE = "image-minimax-h3-highspeed-runware"
GATEWAY_IMAGE_NANO_BANANA_21 = "image-nano-banana-2.1"
GATEWAY_IMAGE_MUSE = "image-muse"
GATEWAY_IMAGE_SEEDREAM_TEST = "image-seedream-v5-lite"

IMAGE_MODEL_ALIASES = (
    GATEWAY_IMAGE_SUNBURST,
    GATEWAY_IMAGE_NANO_BANANA_21,
)

#: Gateway routes whose handlers can stream advisory partial images. Their
#: billed preview tokens are priced in litellm_pricing_overrides.yaml.
PREVIEW_IMAGE_ALIASES = frozenset({
    GATEWAY_IMAGE_SUNBURST_OPENAI,
    GATEWAY_IMAGE_FLARE,
    GATEWAY_IMAGE_SUNBURST_26,
    GATEWAY_IMAGE_FLARE_26,
    GATEWAY_IMAGE_NANO_BANANA_21,
})

_GEMINI_FLASH_LITE_MODEL = "vertex-multimodal/gemini-3.1-flash-lite-image"
_GEMINI_PRO_IMAGE_MODEL = "vertex-multimodal/gemini-3-pro-image"
_GPT_IMAGE_2_MODEL = "openai/gpt-image-2"
# This is the gateway-side custom-provider route.  Its handler strips the
# transport prefix before calling OpenRouter with the actual model slug.
_MUSE_IMAGE_MODEL = "openrouter-image/meta/muse-image"
_SEEDREAM_V5_LITE_MODEL = "fal-queue/bytedance/seedream/v5/lite/edit"
_SEEDREAM_V5_PRO_MODEL = "fal-queue/bytedance/seedream/v5/pro/edit"

# Provider keys are intentionally open-ended strings rather than a closed enum.
# The model catalog can describe providers that are not active in the current
# production aliases, and adding a future provider does not change the quality
# alias contract.
IMAGE_PROVIDER_OPENAI = "openai"
IMAGE_PROVIDER_OPENROUTER = "openrouter"
IMAGE_PROVIDER_VERTEX_MULTIMODAL = "vertex-multimodal"
IMAGE_PROVIDER_FAL_QUEUE = "fal-queue"
#: Sunburst: OpenAI first, one FAL attempt as backup (``image_route_fallback``).
IMAGE_PROVIDER_OPENAI_FAL = "openai-fal"
#: Runware's REST API; references go by uploaded media UUID.
IMAGE_PROVIDER_RUNWARE = "runware"
#: Sunburst while the Runware grant lasts: Runware first, then OpenAI with
#: one FAL attempt (``image_route_fallback.run_runware_first``).
IMAGE_PROVIDER_RUNWARE_OPENAI_FAL = "runware-openai-fal"
IMAGE_PROVIDER_UNKNOWN = "unknown"


def runware_first_enabled() -> bool:
    """Operator switch: new Sunburst work starts on Runware.

    Frozen editions and wires keep the identity they were created with.
    """
    from novel_to_comic import runtime_settings

    return runtime_settings.raw("CANARY_RUNWARE_FIRST_ENABLED").lower() in {"1", "true"}


class ImageRoute(str, Enum):
    """Stable application routes independent of mutable UI tier labels."""

    NANO_BANANA_21 = "nano_banana_21"
    GEMINI_FLASH_LITE = "gemini_flash_lite"
    GEMINI_PRO_IMAGE = "gemini_pro_image"
    SEEDREAM = "seedream"
    GPT_IMAGE_2 = "gpt_image_2"
    MUSE_IMAGE = "muse_image"
    MINIMAX_H3 = "minimax_h3"
    CODEX_BUILTIN = "codex_builtin"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class ImageModelDescription:
    """Display, provider, and model identity for one effective model string."""

    route: ImageRoute
    display_name: str
    provider_model: str
    provider_key: str


_ALIAS_DESCRIPTIONS: dict[str, ImageModelDescription] = {
    GATEWAY_IMAGE_NANO_BANANA_21: ImageModelDescription(
        route=ImageRoute.NANO_BANANA_21, display_name="Nano Banana 2.1",
        provider_model="vertex-multimodal/gemini-nano-banana-2.1",
        provider_key=IMAGE_PROVIDER_VERTEX_MULTIMODAL,
    ),
    GATEWAY_IMAGE_FAST: ImageModelDescription(
        route=ImageRoute.GEMINI_FLASH_LITE,
        display_name="Gemini 3.1 Flash Lite Image",
        provider_model=_GEMINI_FLASH_LITE_MODEL,
        provider_key=IMAGE_PROVIDER_VERTEX_MULTIMODAL,
    ),
    GATEWAY_IMAGE_BALANCED: ImageModelDescription(
        route=ImageRoute.GEMINI_PRO_IMAGE,
        display_name="Gemini 3 Pro Image (Nano Banana Pro)",
        provider_model=_GEMINI_PRO_IMAGE_MODEL,
        provider_key=IMAGE_PROVIDER_VERTEX_MULTIMODAL,
    ),
    GATEWAY_IMAGE_QUALITY: ImageModelDescription(
        route=ImageRoute.GPT_IMAGE_2,
        display_name="GPT Image 2",
        provider_model=_GPT_IMAGE_2_MODEL,
        provider_key=IMAGE_PROVIDER_OPENAI,
    ),
    GATEWAY_IMAGE_SUNBURST: ImageModelDescription(
        route=ImageRoute.GPT_IMAGE_2,
        display_name="GPT Image 2.5 Sunburst",
        provider_model="gpt-image-2.5-sunburst",
        provider_key=IMAGE_PROVIDER_OPENAI_FAL,
    ),
    GATEWAY_IMAGE_FLARE: ImageModelDescription(
        route=ImageRoute.GPT_IMAGE_2,
        display_name="GPT Image 2.5 Flare",
        provider_model="openai/gpt-image-2.5-flare",
        provider_key=IMAGE_PROVIDER_OPENAI,
    ),
    GATEWAY_IMAGE_SUNBURST_26: ImageModelDescription(
        route=ImageRoute.GPT_IMAGE_2,
        display_name="GPT Image 2.6 Sunburst",
        provider_model="openai/gpt-image-2.6-sunburst",
        provider_key=IMAGE_PROVIDER_OPENAI,
    ),
    GATEWAY_IMAGE_FLARE_26: ImageModelDescription(
        route=ImageRoute.GPT_IMAGE_2,
        display_name="GPT Image 2.6 Flare",
        provider_model="openai/gpt-image-2.6-flare",
        provider_key=IMAGE_PROVIDER_OPENAI,
    ),
    GATEWAY_IMAGE_MINIMAX_H3_RUNWARE: ImageModelDescription(
        route=ImageRoute.MINIMAX_H3,
        display_name="MiniMax H3 Image",
        provider_model="runware/minimax-h3-image",
        provider_key=IMAGE_PROVIDER_RUNWARE,
    ),
    GATEWAY_IMAGE_MINIMAX_H3_HIGHSPEED_RUNWARE: ImageModelDescription(
        route=ImageRoute.MINIMAX_H3,
        display_name="MiniMax H3 Image Highspeed",
        provider_model="runware/minimax-h3-image-highspeed",
        provider_key=IMAGE_PROVIDER_RUNWARE,
    ),
    GATEWAY_IMAGE_MUSE: ImageModelDescription(
        route=ImageRoute.MUSE_IMAGE,
        display_name="Muse Image",
        provider_model=_MUSE_IMAGE_MODEL,
        provider_key=IMAGE_PROVIDER_OPENROUTER,
    ),
    GATEWAY_IMAGE_SEEDREAM_TEST: ImageModelDescription(
        route=ImageRoute.SEEDREAM,
        display_name="Seedream 5.0 Lite",
        provider_model=_SEEDREAM_V5_LITE_MODEL,
        provider_key=IMAGE_PROVIDER_FAL_QUEUE,
    ),
}


def describe_image_model(model: str) -> ImageModelDescription:
    """Classify an effective model string and return truthful display metadata."""
    normalized = (model or "").strip().lower()
    if normalized == GATEWAY_IMAGE_SUNBURST and runware_first_enabled():
        from dataclasses import replace

        return replace(_ALIAS_DESCRIPTIONS[normalized], provider_key=IMAGE_PROVIDER_RUNWARE_OPENAI_FAL)
    if normalized in _ALIAS_DESCRIPTIONS:
        return _ALIAS_DESCRIPTIONS[normalized]
    if normalized.removeprefix("openai/") in {
        "gpt-image-2",
        # Retained historical literals remain OpenAI-only routes; the
        # selectable image-sunburst alias is OpenAI first with FAL backup.
        "gpt-image-2.5-sunburst",
        "gpt-image-2.5-sunburst-2026-09-08",
        "gpt-image-2.5-flare",
        "gpt-image-2.5-flare-2026-09-08",
        "gpt-image-2.6-sunburst",
        "gpt-image-2.6-flare",
    }:
        return ImageModelDescription(
            route=ImageRoute.GPT_IMAGE_2,
            display_name=normalized.removeprefix("openai/").replace("gpt-image-", "GPT Image "),
            provider_model=normalized,
            provider_key=IMAGE_PROVIDER_OPENAI,
        )
    if normalized.removeprefix("fal-queue/") in {
        "gpt-image-2.5-sunburst",
        "gpt-image-2.5-sunburst-2026-09-08",
        "openai/gpt-image-2.5/sunburst",
        "openai/gpt-image-2.5/sunburst/text-to-image",
        "openai/gpt-image-2.5/sunburst/edit",
    }:
        return ImageModelDescription(
            route=ImageRoute.GPT_IMAGE_2,
            display_name="GPT Image 2.5 Sunburst",
            provider_model=normalized,
            provider_key=IMAGE_PROVIDER_FAL_QUEUE,
        )
    if normalized.removeprefix("openrouter-image/").removeprefix("openrouter/") == "meta/muse-image":
        return ImageModelDescription(
            route=ImageRoute.MUSE_IMAGE,
            display_name="Muse Image",
            provider_model=normalized,
            provider_key=IMAGE_PROVIDER_OPENROUTER,
        )
    if normalized in {"gemini-nano-banana-2.1", "vertex_ai/gemini-nano-banana-2.1",
                      "vertex-multimodal/gemini-nano-banana-2.1"}:
        return _ALIAS_DESCRIPTIONS[GATEWAY_IMAGE_NANO_BANANA_21]
    if normalized == _GEMINI_FLASH_LITE_MODEL:
        return ImageModelDescription(
            route=ImageRoute.GEMINI_FLASH_LITE,
            display_name="Gemini 3.1 Flash Lite Image",
            provider_model=normalized,
            provider_key=IMAGE_PROVIDER_VERTEX_MULTIMODAL,
        )
    if normalized == _GEMINI_PRO_IMAGE_MODEL:
        return ImageModelDescription(
            route=ImageRoute.GEMINI_PRO_IMAGE,
            display_name="Gemini 3 Pro Image (Nano Banana Pro)",
            provider_model=normalized,
            provider_key=IMAGE_PROVIDER_VERTEX_MULTIMODAL,
        )
    if normalized in {
        _SEEDREAM_V5_LITE_MODEL,
        _SEEDREAM_V5_PRO_MODEL,
        "bytedance/seedream/v5/pro/edit",
    } or "seedream" in normalized:
        return ImageModelDescription(
            route=ImageRoute.SEEDREAM,
            display_name="Seedream 5.0 Pro",
            provider_model=normalized,
            provider_key=IMAGE_PROVIDER_FAL_QUEUE,
        )
    return ImageModelDescription(
        route=ImageRoute.UNKNOWN,
        display_name=(model or "").strip(),
        provider_model=(model or "").strip(),
        provider_key=IMAGE_PROVIDER_UNKNOWN,
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
# - GEMINI_FLASH_LITE / GPT_IMAGE_2: the OpenAI-compatible ``prompt`` field has
#   no hard provider cap below the model context window, but a generous budget
#   keeps prompts focused. ``None`` means no compiler-applied character budget
#   (the route has no provider-side prefix slice that threatens protected
#   content).
_PROMPT_CHAR_LIMITS: dict[ImageRoute, int | None] = {
    ImageRoute.NANO_BANANA_21: None,
    ImageRoute.GEMINI_FLASH_LITE: None,
    ImageRoute.GEMINI_PRO_IMAGE: None,
    ImageRoute.SEEDREAM: None,
    ImageRoute.GPT_IMAGE_2: None,
    ImageRoute.MUSE_IMAGE: None,
    ImageRoute.MINIMAX_H3: None,
    ImageRoute.UNKNOWN: None,
}

#: Native aspect modes a route accepts. Used to represent the aspect intent
#: structurally rather than as prose. Empty tuple means the route has no
#: dedicated aspect parameter (it derives aspect from width/height only).
_NATIVE_ASPECTS: dict[ImageRoute, tuple[str, ...]] = {
    ImageRoute.NANO_BANANA_21: (),
    ImageRoute.GEMINI_FLASH_LITE: (),
    ImageRoute.GEMINI_PRO_IMAGE: (),
    ImageRoute.SEEDREAM: (),
    ImageRoute.GPT_IMAGE_2: (),
    ImageRoute.MUSE_IMAGE: (),
    ImageRoute.MINIMAX_H3: (),
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
    ImageRoute.NANO_BANANA_21: frozenset({"quality"}),
    ImageRoute.GEMINI_FLASH_LITE: frozenset({"quality"}),
    ImageRoute.GEMINI_PRO_IMAGE: frozenset({"quality"}),
    ImageRoute.SEEDREAM: frozenset({"quality"}),
    ImageRoute.GPT_IMAGE_2: frozenset({"quality"}),
    # OpenRouter's Muse catalog entry does not advertise a quality control;
    # leave the control out rather than implying that LiteLLM will honor it.
    ImageRoute.MUSE_IMAGE: frozenset(),
    # MiniMax H3 has no quality tier; size alone sets the cost.
    ImageRoute.MINIMAX_H3: frozenset(),
    ImageRoute.UNKNOWN: frozenset(),
}


def image_quality_for_model(model: str, quality: str | None) -> str | None:
    """Nano Banana uses native 1K; other models retain their configured quality.

    The Vertex adapter maps the wire's ``low`` quality to its native 1K tier.
    Select it before compilation so the frozen request records the resolution.
    """
    if describe_image_model(model).route == ImageRoute.NANO_BANANA_21:
        return "low"
    return quality


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

    ``provider_key`` selects the transport serializer. It is separate from the
    concrete ``provider_model`` so model versions can change without changing
    the wire dispatch.

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
    provider_key: str = IMAGE_PROVIDER_UNKNOWN

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


# Product reference caps; GPT Image 2.5 uses its documented 16-image limit.
_ROUTE_REFERENCE_CAPS: dict[ImageRoute, int] = {
    ImageRoute.NANO_BANANA_21: 14,
    ImageRoute.GEMINI_FLASH_LITE: 10,
    ImageRoute.GEMINI_PRO_IMAGE: 10,
    ImageRoute.SEEDREAM: 10,
    ImageRoute.GPT_IMAGE_2: 4,
    # OpenRouter documents Muse Image with up to ten reference images.
    ImageRoute.MUSE_IMAGE: 10,
    # Runware documents MiniMax H3 with up to sixteen reference images.
    ImageRoute.MINIMAX_H3: 16,
    ImageRoute.UNKNOWN: 10,
}


_ROUTE_PROVIDER_KEYS: dict[ImageRoute, str] = {
    ImageRoute.NANO_BANANA_21: IMAGE_PROVIDER_VERTEX_MULTIMODAL,
    ImageRoute.GEMINI_FLASH_LITE: IMAGE_PROVIDER_VERTEX_MULTIMODAL,
    ImageRoute.GEMINI_PRO_IMAGE: IMAGE_PROVIDER_VERTEX_MULTIMODAL,
    ImageRoute.SEEDREAM: IMAGE_PROVIDER_FAL_QUEUE,
    ImageRoute.GPT_IMAGE_2: IMAGE_PROVIDER_OPENAI,
    ImageRoute.MUSE_IMAGE: IMAGE_PROVIDER_OPENROUTER,
    ImageRoute.MINIMAX_H3: IMAGE_PROVIDER_RUNWARE,
    ImageRoute.UNKNOWN: IMAGE_PROVIDER_UNKNOWN,
}


def _profile_for_route(
    route: ImageRoute,
    *,
    provider_key: str | None = None,
) -> ImageModelProfile:
    return ImageModelProfile(
        route=route,
        max_references=_ROUTE_REFERENCE_CAPS[route],
        supported_roles=frozenset(_ALL_REFERENCE_ROLES),
        prompt_char_limit=_PROMPT_CHAR_LIMITS[route],
        native_aspect_modes=_NATIVE_ASPECTS[route],
        supported_controls=_SUPPORTED_CONTROLS[route],
        provider_key=provider_key or _ROUTE_PROVIDER_KEYS[route],
    )


def image_model_profile(model: str) -> ImageModelProfile:
    """Reference capabilities for an effective image model string.

    ``model`` follows the same classification rules as
    :func:`describe_image_model`. The profile is derived from the resolved
    route, so aliases and literal provider model strings resolve consistently.
    """
    from novel_to_comic.codex_dev import route_for

    if route_for("image", model) is not None:
        return ImageModelProfile(
            route=ImageRoute.CODEX_BUILTIN,
            max_references=5,
            supported_roles=frozenset(_ALL_REFERENCE_ROLES),
            prompt_char_limit=None,
            native_aspect_modes=(),
            supported_controls=frozenset(),
            provider_key="codex-dev",
        )
    description = describe_image_model(model)
    if "gpt-image-2.5-" in description.provider_model or "gpt-image-2.6-" in description.provider_model:
        from dataclasses import replace
        return replace(
            _profile_for_route(description.route, provider_key=description.provider_key),
            max_references=16,
        )
    return _profile_for_route(
        description.route,
        provider_key=description.provider_key,
    )


def image_model_profile_for_config(config) -> ImageModelProfile:
    """Reference capabilities for a ``Config``'s effective image model."""
    return image_model_profile(config.effective_image_model())
