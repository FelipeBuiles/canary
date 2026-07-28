"""Pipeline configuration loaded from config.yaml + .env."""

import logging
import os
from pathlib import Path
from typing import Literal, Optional

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, PrivateAttr

from novel_to_comic.image_models import (
    GATEWAY_IMAGE_BALANCED,
    GATEWAY_IMAGE_FAST,
    GATEWAY_IMAGE_QUALITY,
    GATEWAY_IMAGE_REVE as GATEWAY_IMAGE_REVE,
    IMAGE_MODEL_ALIASES,
    ImageRoute,
    describe_image_model,
)

_logger = logging.getLogger(__name__)


LANGUAGE_NAMES: dict[str, str] = {
    "en": "English",
    "es": "Spanish",
    "fr": "French",
}

QualityPreset = Literal["fast", "balanced", "quality"]
FailedRequestBillingPolicy = Literal["provider_usage_only", "never", "estimate_all"]

# Gateway aliases — one per (intent, preset) pair. Defined in litellm/config.yaml.
GATEWAY_EXTRACT_FAST = "extract-fast"
GATEWAY_EXTRACT_BALANCED = "extract-balanced"
GATEWAY_EXTRACT_QUALITY = "extract-quality"
GATEWAY_ADAPT_FAST = "adapt-fast"
GATEWAY_ADAPT_BALANCED = "adapt-balanced"
GATEWAY_ADAPT_QUALITY = "adapt-quality"
GATEWAY_PLAN_FAST = "plan-fast"
GATEWAY_PLAN_BALANCED = "plan-balanced"
GATEWAY_PLAN_QUALITY = "plan-quality"
GATEWAY_PROMPT_FAST = "prompt-fast"
GATEWAY_PROMPT_BALANCED = "prompt-balanced"
GATEWAY_PROMPT_QUALITY = "prompt-quality"
# Compatibility inventories derived from the route-description seam.
GPT_IMAGE_2_ALIASES: frozenset[str] = frozenset(
    alias
    for alias in IMAGE_MODEL_ALIASES
    if describe_image_model(alias).route is ImageRoute.GPT_IMAGE_2
)
REVE_ALIASES: frozenset[str] = frozenset(
    alias
    for alias in IMAGE_MODEL_ALIASES
    if describe_image_model(alias).route is ImageRoute.REVE
)
SEEDREAM_ALIASES: frozenset[str] = frozenset(
    alias
    for alias in IMAGE_MODEL_ALIASES
    if describe_image_model(alias).route is ImageRoute.SEEDREAM
)

# Default parallel image generations for Gemini/Vertex routes when
# image_concurrency is unset. Vertex preview image models carry tight RPM
# quotas; this cap plus the 429-aware backoff in ai/client keeps draws
# parallel without tripping the limiter.
GEMINI_IMAGE_CONCURRENCY_DEFAULT = 3

# Ticket 04 complete-page production profile. Draw capability selection is
# intentionally edition-wide. The gateway alias is transport-only; the frozen
# edition records the actual provider/model identity.
COMPLETE_PAGE_PROVIDER = "vertex-multimodal"
COMPLETE_PAGE_MODEL = "gemini-3.1-flash-image"
COMPLETE_PAGE_GATEWAY_MODEL = GATEWAY_IMAGE_BALANCED
COMPLETE_PAGE_PROFILE_ID = "nano-banana-2-complete-page-v1"
COMPLETE_PAGE_MAX_REFERENCES = 8
# Gemini's documented 2K dimensions for a 2:3 image.
COMPLETE_PAGE_OUTPUT_WIDTH = 1696
COMPLETE_PAGE_OUTPUT_HEIGHT = 2528
COMPLETE_PAGE_MAX_PROMPT_CHARACTERS = 32_000
COMPLETE_PAGE_MAX_ATTEMPTS = 3
COMPLETE_PAGE_BASE_COST_USD = "0.101"
COMPLETE_PAGE_REFERENCE_COST_USD = "0.00056"

# Ticket 05 render analysis. Reading a rendered page's visible lettering is a
# vision-model task, kept in configuration so Draw never names a model inline.
GATEWAY_PAGE_OCR = "ocr-balanced"

# Reservation allowance for reading one page back. Analysis is a second billable
# provider call, so a page's credit hold has to cover it; the settled debit
# always comes from the usage the provider actually reported.
PAGE_OCR_ESTIMATED_COST_USD = "0.004"


def is_gpt_image_2(model: str) -> bool:
    """True if `model` is classified as the GPT Image 2 route."""
    return describe_image_model(model).route is ImageRoute.GPT_IMAGE_2


def is_reve_model(model: str) -> bool:
    """True if `model` is classified as a Reve route."""
    return describe_image_model(model).route is ImageRoute.REVE


def is_seedream_model(model: str) -> bool:
    """True if `model` is classified as a Seedream route."""
    return describe_image_model(model).route is ImageRoute.SEEDREAM


def image_model_aliases() -> tuple[str, ...]:
    """Production image model aliases safe to expose outside Labs."""
    return IMAGE_MODEL_ALIASES


def validate_image_model_alias(alias: str | None) -> str | None:
    """Return a normalized image alias, or raise for an unsupported alias."""
    normalized = (alias or "").strip()
    if not normalized:
        return None
    if normalized not in IMAGE_MODEL_ALIASES:
        raise ValueError(
            f"image_model_alias must be one of: {', '.join(IMAGE_MODEL_ALIASES)}"
        )
    return normalized


def config_for_image_model_alias(config: "Config", alias: str | None) -> "Config":
    """Return a one-shot config copy pinned to a validated image model alias."""
    normalized = validate_image_model_alias(alias)
    if normalized is None:
        return config
    copied = config.model_copy(update={"image_model": normalized})
    copied._one_shot_image_model_alias = normalized
    return copied


_QUALITY_PRESETS: dict[QualityPreset, dict[str, str]] = {
    "fast": {
        "extract": GATEWAY_EXTRACT_FAST,
        "adapt": GATEWAY_ADAPT_FAST,
        "plan": GATEWAY_PLAN_FAST,
        "prompt": GATEWAY_PROMPT_FAST,
        "image": GATEWAY_IMAGE_FAST,
    },
    "balanced": {
        "extract": GATEWAY_EXTRACT_BALANCED,
        "adapt": GATEWAY_ADAPT_BALANCED,
        "plan": GATEWAY_PLAN_BALANCED,
        "prompt": GATEWAY_PROMPT_BALANCED,
        "image": GATEWAY_IMAGE_BALANCED,
    },
    "quality": {
        "extract": GATEWAY_EXTRACT_QUALITY,
        "adapt": GATEWAY_ADAPT_QUALITY,
        "plan": GATEWAY_PLAN_QUALITY,
        "prompt": GATEWAY_PROMPT_QUALITY,
        "image": GATEWAY_IMAGE_QUALITY,
    },
}

_QUALITY_PRESET_FIELDS: dict[str, str] = {
    "extract": "extraction_model",
    "adapt": "adapt_model",
    "plan": "plan_model",
    "prompt": "prompt_model",
    "image": "image_model",
}

# Env var name → Config field name
_ENV_KEYS: dict[str, str] = {
    "GOOGLE_CLOUD_PROJECT": "google_cloud_project",
    "GOOGLE_CLOUD_LOCATION": "google_cloud_location",
    "LITELLM_BASE_URL": "litellm_base_url",
    "LITELLM_API_KEY": "litellm_api_key",
    "AI_BILL_FAILED_REQUESTS": "ai_bill_failed_requests",
    "CANARY_MOCK_MODEL_BASE_URL": "mock_model_base_url",
}


def mock_mode_active(config: "Config") -> bool:
    """Return whether the operator-authorized zero-cost replay mode is active.

    The project flag alone is deliberately insufficient: production project
    configuration must never be able to redirect model traffic or bypass the
    credit gate without an explicit server-level opt-in.
    """
    if not config.mock_mode:
        return False
    raw = os.environ.get("CANARY_MOCK_GENERATIONS_ENABLED", "false").strip().lower()
    return raw not in {"", "0", "false", "no", "off"}


class Config(BaseModel):
    """Pipeline configuration. Loaded from config.yaml in the project directory."""

    model_config = ConfigDict(validate_assignment=True)
    _one_shot_image_model_alias: str | None = PrivateAttr(default=None)

    # AI gateway settings — load from .env or environment variables instead of hardcoding here.
    litellm_base_url: str = "http://localhost:4000"
    litellm_api_key: str = "sk-local-canary"
    ai_bill_failed_requests: FailedRequestBillingPolicy = "provider_usage_only"

    # Hidden local demo/test mode. It is not exposed by the config API and is
    # inert unless CANARY_MOCK_GENERATIONS_ENABLED is also set by the operator.
    mock_mode: bool = False
    mock_model_base_url: str = "http://127.0.0.1:4010"

    # Google Gemini access. Vertex AI uses Application Default Credentials
    # instead of Gemini Developer API keys.
    google_use_vertex_ai: bool = True
    google_cloud_project: str = ""
    google_cloud_location: str = "global"

    # Model choices. Runtime AI calls use intent+preset gateway aliases.
    # Per-stage fields default to the "balanced" alias; quality_preset overrides them.
    extraction_model: str = GATEWAY_EXTRACT_BALANCED
    adapt_model: str = GATEWAY_ADAPT_BALANCED
    plan_model: str = GATEWAY_PLAN_BALANCED
    prompt_model: str = GATEWAY_PROMPT_BALANCED
    page_ocr_model: str = GATEWAY_PAGE_OCR
    image_provider: Literal["gemini", "openai", "openrouter", "together", "reve"] = "gemini"
    image_model: str = GATEWAY_IMAGE_QUALITY
    fallback_image_model: str = GATEWAY_IMAGE_FAST

    # Output language for generated book text and visual assets.
    target_language: str = "en"

    # Dev/demo mode — lowers image generation resolution/steps and prefers the
    # faster Gemini Flash image model when the default production model is used.
    dev_mode: bool = False

    # Quality preset: "fast" | "balanced" | "quality" | None
    # When set, overrides all four text model fields. dev_mode forces "fast".
    quality_preset: QualityPreset | None = None
    dev_image_scale: float = 0.5
    dev_image_steps: int = 8
    dev_image_concurrency: int = 5

    # Image generation
    # Width/height are used for Together AI models; Gemini native chooses its own resolution.
    image_width: int = 1024
    image_height: int = 1024
    image_steps: int = 28
    image_quality: str = "medium"  # OpenAI GPT Image quality: auto | low | medium | high
    flux_guidance_scale: float = 3.5

    # Max panel/cast images generated in parallel. None → per-provider default:
    # Gemini/Vertex routes use GEMINI_IMAGE_CONCURRENCY_DEFAULT, everything
    # else uses max_concurrent_requests. Set explicitly when your quota allows
    # more (or demands less).
    image_concurrency: int | None = None

    # Experimental LLM visual-brief pass. Production prompt assembly is
    # deterministic; this flag is retained for Labs/manual comparisons only.
    visual_brief_enabled: bool = False

    # LLM style-sample brief: compose the shared subject/setting prose for S2
    # style proof images (via prompt_model), cached per project so every
    # candidate style renders the identical scene. Falls back to a
    # deterministic first-character/first-location body when disabled or when
    # the call fails.
    style_sample_brief_enabled: bool = True

    # Negative prompt — only applied for Together AI / SDXL models (Gemini native ignores it)
    # Keep style-neutral: no photorealistic/cartoon terms here. Put those in config.yaml
    # when you want to push toward or away from a specific look.
    negative_prompt: str = (
        "ugly, deformed, blurry, bad anatomy, watermark, signature, text on image, "
        "overexposed, uncanny valley, extra limbs, cropped, low quality, jpeg artifacts, "
        "exaggerated expression, theatrical emotion, dramatic face, wide open mouth, "
        "raised eyebrows, airbrushed face, perfectly symmetrical face, idealized features, "
        "duplicate characters, same person twice, cloned figure, mirrored character, "
        "two identical people, repeated figure, copy of character"
    )

    # Style template (injected into every image prompt).
    # Default is intentionally generic — no art style, no medium, no rendering technique.
    # Override in config.yaml to get the look you want:
    #   Realistic:   "Cinematic photorealistic, natural lighting, shallow DOF."
    #   Comic:       "Bold graphic novel style, cel-shaded coloring, thick ink outlines."
    #   Painted:     "Oil painting, visible brushwork, rich saturated colour."
    style_template: str = (
        "High quality visual storytelling. Dramatic natural lighting, clean readable environments. "
        "Controlled surface detail without noisy grain, speckled dappling, repeated texture fields, or muddy micro-detail. "
        "Faces rendered with natural individuality and subtle imperfection — never idealized or airbrushed. "
        "All facial expressions understated and restrained; emotion conveyed through the eyes and posture alone."
    )

    # Pipeline settings
    parallel_batch_size: int = 5
    max_concurrent_requests: int = 5
    cost_limit_usd: Optional[float] = None

    def effective_image_model(self) -> str:
        if self._one_shot_image_model_alias is not None:
            return self._one_shot_image_model_alias
        # In dev_mode an explicit user override wins. Only fall back to
        # fallback_image_model when image_model is still at its default. Treat
        # the previous balanced default as a legacy default too, so existing
        # project configs retain their dev-mode behavior after this default
        # changes to the quality route.
        if self.dev_mode:
            if self.image_model in {
                Config.model_fields["image_model"].default,
                GATEWAY_IMAGE_BALANCED,
            }:
                return self.fallback_image_model or GATEWAY_IMAGE_FAST
            return self.image_model
        return self._effective_stage_model("image")

    def _effective_stage_model(self, stage: str) -> str:
        """Resolve the effective gateway alias for a pipeline stage.

        Priority: dev_mode -> "fast" preset, else quality_preset if set, else raw field.
        """
        if self.dev_mode:
            return _QUALITY_PRESETS["fast"][stage]
        if self.quality_preset is not None:
            preset_model = _QUALITY_PRESETS[self.quality_preset][stage]
            field_name = _QUALITY_PRESET_FIELDS[stage]
            raw_model = getattr(self, field_name)
            field_default = Config.model_fields[field_name].default
            if raw_model != field_default and raw_model != preset_model:
                _logger.warning(
                    "quality_preset=%r overrides explicitly configured %s=%r (using %r instead)",
                    self.quality_preset, field_name, raw_model, preset_model,
                )
            return preset_model
        return getattr(self, _QUALITY_PRESET_FIELDS[stage])

    def effective_extraction_model(self) -> str:
        return self._effective_stage_model("extract")

    def effective_adapt_model(self) -> str:
        return self._effective_stage_model("adapt")

    def effective_plan_model(self) -> str:
        return self._effective_stage_model("plan")

    def effective_prompt_model(self) -> str:
        return self._effective_stage_model("prompt")

    def effective_page_ocr_model(self) -> str:
        """Render analysis is fidelity checking, not creative work.

        It is deliberately outside the quality presets: a book generated with
        the quality preset must not read its own pages with a different, more
        forgiving model than a book generated with the fast preset.
        """
        return self.page_ocr_model

    def uses_gemini_image_provider(self) -> bool:
        return self.image_provider == "gemini"

    def language_code(self) -> str:
        return self.target_language if self.target_language in LANGUAGE_NAMES else "en"

    def language_name(self) -> str:
        return LANGUAGE_NAMES[self.language_code()]

    def generation_language_instruction(self) -> str:
        name = self.language_name()
        if self.language_code() == "en":
            return (
                "Generate all user-facing creative text in English. Preserve structured IDs, "
                "file names, enum values, and JSON keys exactly as specified."
            )
        return (
            f"Generate all user-facing creative text in {name}. Translate dialogue, narration, "
            "captions, action descriptions, panel descriptions, visual prompt text, and style text "
            f"into natural {name}. Preserve structured IDs, file names, enum values, character IDs, "
            "location IDs, and JSON keys exactly as specified. Character and place names should stay "
            "as written unless the source text already localizes them."
        )

    def effective_image_steps(self, steps: int | None = None) -> int:
        base = steps or self.image_steps
        return min(base, self.dev_image_steps) if self.dev_mode else base

    def effective_image_dimensions(self, width: int, height: int) -> tuple[int, int]:
        if not self.dev_mode:
            return width, height
        scale = min(max(self.dev_image_scale, 0.2), 1.0)

        def snap(value: int) -> int:
            return max(256, int(round((value * scale) / 64)) * 64)

        return snap(width), snap(height)

    def effective_image_concurrency(self) -> int:
        if self.dev_mode:
            return max(1, self.dev_image_concurrency)
        if self.image_concurrency is not None:
            return max(1, self.image_concurrency)
        model = self.effective_image_model().lower()
        if self.image_provider == "gemini" or "gemini" in model or "vertex" in model:
            return GEMINI_IMAGE_CONCURRENCY_DEFAULT
        return max(1, self.max_concurrent_requests)


def _find_env_file(start: Path) -> Path | None:
    """Walk up the directory tree from start, returning the first .env found."""
    current = start.resolve()
    while True:
        candidate = current / ".env"
        if candidate.is_file():
            return candidate
        parent = current.parent
        if parent == current:  # filesystem root
            return None
        current = parent


def load_config(project_dir: Path) -> tuple["Config", Path | None]:
    """Load config from config.yaml, then overlay .env / shell env vars.

    Priority (highest wins):
      1. Shell environment variables
      2. Nearest .env file (walked up from project_dir)
      3. config.yaml values
      4. Pydantic field defaults

    Returns (config, env_file_path) so callers can report which .env was used.
    """
    env_file = _find_env_file(project_dir)
    if env_file:
        # override=True so .env always wins over stale shell exports.
        # Shell vars set in the current process still take precedence because
        # os.environ is read after load_dotenv; we apply them explicitly below.
        load_dotenv(env_file, override=True)

    config_path = project_dir / "config.yaml"
    data: dict = {}
    if config_path.exists():
        with open(config_path) as f:
            data = yaml.safe_load(f) or {}

    # Overlay env vars.  Explicit shell exports beat .env.
    for env_name, field_name in _ENV_KEYS.items():
        val = os.environ.get(env_name, "").strip()
        if val:
            data[field_name] = val

    use_vertex = os.environ.get("GOOGLE_GENAI_USE_VERTEXAI", "").strip()
    if use_vertex:
        data["google_use_vertex_ai"] = use_vertex.lower() in {"1", "true", "yes", "on"}

    return Config(**data), env_file


def save_config(config: Config, project_dir: Path) -> None:
    """Write an annotated config.yaml to the project directory."""
    config_path = project_dir / "config.yaml"
    cost_limit = f"{config.cost_limit_usd}" if config.cost_limit_usd is not None else "~"  # YAML null
    style_template_block = config.style_template.replace("\n", "\n  ")
    config_path.write_text(f"""\
# novel-to-comic pipeline configuration
# Generated by `pipeline init`. Edit before running any stages.

# ---------------------------------------------------------------------------
# AI gateway and API keys  — put secrets in .env instead of here (see .env.example)
# ---------------------------------------------------------------------------
# Runtime AI calls should go through LiteLLM Proxy. Provider keys belong in the
# LiteLLM service environment during the gateway migration.
litellm_base_url: "{config.litellm_base_url}"
litellm_api_key: ""
ai_bill_failed_requests: "{config.ai_bill_failed_requests}"

# Legacy Google fields are retained for project metadata during the gateway migration.
google_use_vertex_ai: {str(config.google_use_vertex_ai).lower()}
google_cloud_project: "{config.google_cloud_project}"
google_cloud_location: "{config.google_cloud_location}"

# ---------------------------------------------------------------------------
# Model choices
# ---------------------------------------------------------------------------
# Quality preset: fast | balanced | quality | null
# When set, overrides all four text model fields below.
# dev_mode forces "fast" regardless of this setting.
# Set to null (or omit) to use individual model fields.
quality_preset: {"null" if config.quality_preset is None else f'"{config.quality_preset}"'}

# Stage 1 – full-novel extraction
extraction_model: "{config.extraction_model}"

# Book-level adaptation model
adapt_model: "{config.adapt_model}"

# Global page-planning model
plan_model: "{config.plan_model}"

# Cast asset prompt model
prompt_model: "{config.prompt_model}"

# Image generation provider/model. Runtime AI calls use gateway aliases.
# image_provider: gemini | openai | openrouter | together
image_provider: "{config.image_provider}"
image_model: "{config.image_model}"

# Dev-mode fallback used when image_model is the default gateway primary alias.
# Leave blank to keep the configured image_model in dev_mode.
fallback_image_model: "{config.fallback_image_model}"

# Generated text language: en | es | fr
target_language: "{config.language_code()}"

# Dev/demo mode trades image fidelity for iteration speed.
# When enabled, generated images use scaled-down dimensions, fewer diffusion
# steps where supported, and the fast Gemini Flash Lite alias instead of the
# balanced alias
# unless a custom image_model is explicitly configured.
dev_mode: {str(config.dev_mode).lower()}
mock_mode: {str(config.mock_mode).lower()}  # requires operator env gate; not shown in UI
dev_image_scale: {config.dev_image_scale}
dev_image_steps: {config.dev_image_steps}
dev_image_concurrency: {config.dev_image_concurrency}

# ---------------------------------------------------------------------------
# Image generation settings
# ---------------------------------------------------------------------------
image_width: {config.image_width}
image_height: {config.image_height}
image_steps: {config.image_steps}       # inference steps — 28 is a good balance
image_quality: "{config.image_quality}"  # OpenAI GPT Image only: auto | low | medium | high
flux_guidance_scale: {config.flux_guidance_scale}  # 3.5–4.5 recommended for FLUX.2 Pro
# image_concurrency: 3  # parallel image generations; unset → provider default
#                       # (Gemini/Vertex: 3, others: max_concurrent_requests)
negative_prompt: "{config.negative_prompt}"  # applied to Together AI models only

# ---------------------------------------------------------------------------
# Style template — THIS IS THE MOST IMPORTANT SETTING
# ---------------------------------------------------------------------------
# Injected verbatim at the start of every image prompt.
# The default is intentionally generic (no art style, no medium).
# Replace the whole block to define the visual identity of your comic.
#
# Realistic:
#   style_template: |
#     Cinematic photorealistic, natural lighting, shallow depth of field,
#     dramatic practical lighting, true-to-life skin texture. Faces with
#     natural asymmetry and lived-in features. Never illustrated or painted.
#
# Graphic novel / comic:
#   style_template: |
#     Bold graphic novel style, cel-shaded coloring, high contrast shadows,
#     thick ink outlines, limited colour palette, dynamic composition.
#
# Painted / painterly:
#   style_template: |
#     Oil painting, visible loose brushwork, rich saturated colour,
#     dramatic chiaroscuro lighting, clean readable surfaces.
#
style_template: |
  {style_template_block}

# ---------------------------------------------------------------------------
# Pipeline settings
# ---------------------------------------------------------------------------
# How many independent items to process in parallel
# Reduce if you hit rate limits
parallel_batch_size: {config.parallel_batch_size}

# How many image generation requests to fire simultaneously
# Together AI default rate limit: 10 req/s — keep this at 5 to be safe
max_concurrent_requests: {config.max_concurrent_requests}

# Hard cost cap in USD — pipeline pauses stage 6 if total_cost_usd exceeds this.
# Set to null to disable.
cost_limit_usd: {cost_limit}

# ---------------------------------------------------------------------------
""")
