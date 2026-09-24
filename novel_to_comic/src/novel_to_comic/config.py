"""Pipeline configuration loaded from config.yaml + .env."""

import os
from pathlib import Path
from typing import Literal, Optional

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field, PrivateAttr

from novel_to_comic.image_models import (
    GATEWAY_IMAGE_BALANCED,
    GATEWAY_IMAGE_FAST as GATEWAY_IMAGE_FAST,
    GATEWAY_IMAGE_QUALITY as GATEWAY_IMAGE_QUALITY,
    GATEWAY_IMAGE_SUNBURST,
    IMAGE_MODEL_ALIASES,
    ImageRoute,
    describe_image_model,
)


LANGUAGE_NAMES: dict[str, str] = {
    "en": "English",
    "es": "Spanish",
    "fr": "French",
}

FailedRequestBillingPolicy = Literal["provider_usage_only", "never", "estimate_all"]

# Concrete gateway model IDs; no implicit quality tiers or model escalation.
GATEWAY_SOL = "gpt-6-sol"
GATEWAY_LUNA = "gpt-6-luna"

# Compatibility inventories derived from the route-description seam.
GPT_IMAGE_2_ALIASES: frozenset[str] = frozenset(
    alias
    for alias in IMAGE_MODEL_ALIASES
    if describe_image_model(alias).route is ImageRoute.GPT_IMAGE_2
)
SEEDREAM_ALIASES: frozenset[str] = frozenset(
    alias
    for alias in IMAGE_MODEL_ALIASES
    if describe_image_model(alias).route is ImageRoute.SEEDREAM
)

# Retained Vertex edition metadata. New Draw editions select Sunburst through
# the operator catalog; old editions keep their frozen provider/model identity.
COMPLETE_PAGE_PROVIDER = "vertex-multimodal"
COMPLETE_PAGE_MODEL = "gemini-3-pro-image"
COMPLETE_PAGE_GATEWAY_MODEL = GATEWAY_IMAGE_SUNBURST
COMPLETE_PAGE_PROFILE_ID = "nano-banana-pro-complete-page-v1"
COMPLETE_PAGE_MAX_REFERENCES = 8
# The dimensions recorded by retained Gemini 3 Pro Image editions.
COMPLETE_PAGE_OUTPUT_WIDTH = 1696
COMPLETE_PAGE_OUTPUT_HEIGHT = 2528
COMPLETE_PAGE_MAX_PROMPT_CHARACTERS = 32_000
COMPLETE_PAGE_MAX_ATTEMPTS = 3
COMPLETE_PAGE_BASE_COST_USD = "0.134"
COMPLETE_PAGE_REFERENCE_COST_USD = "0.00112"

# Ticket 05 render analysis. Reading a rendered page's visible lettering is a
# vision-model task, kept in configuration so Draw never names a model inline.
GATEWAY_PAGE_OCR = GATEWAY_LUNA

# Reservation allowance for reading one page back. Analysis is a second billable
# provider call, so a page's credit hold has to cover it; the settled debit
# always comes from the usage the provider actually reported.
PAGE_OCR_ESTIMATED_COST_USD = "0.004"
# Optional page + approved-reference comparison allowance.
PAGE_VISUAL_REVIEW_ESTIMATED_COST_USD = "0.02"
# Conservative reservation allowances, not measured provider prices.
GPT25_PAGE_ESTIMATED_COST_USD = "0.25"
GPT25_REFERENCE_ESTIMATED_COST_USD = "0.01"
MUSE_PAGE_ESTIMATED_COST_USD = "0.01"


def is_gpt_image_2(model: str) -> bool:
    """True if `model` is classified as the GPT Image 2 route."""
    return describe_image_model(model).route is ImageRoute.GPT_IMAGE_2


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


# Env var name → Config field name
_ENV_KEYS: dict[str, str] = {
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

    # Explicit local-development project choices override account defaults in the server.
    dev_model_selections: dict[str, str] = Field(default_factory=dict)

    # Model choices are overlaid from authenticated account preferences by the server.
    extraction_model: str = GATEWAY_LUNA
    # Bound source and output work per Extract request; split on source units.
    extraction_chunk_chars: int = Field(default=16000, ge=4000, le=64000)
    brief_model: str = GATEWAY_LUNA
    adapt_model: str = GATEWAY_SOL
    plan_model: str = GATEWAY_SOL
    # Explicit override of the input-derived cumulative Adapt/Plan call limit.
    narrative_max_calls: int | None = Field(default=None, ge=1)
    prompt_model: str = GATEWAY_LUNA
    page_ocr_model: str = GATEWAY_PAGE_OCR
    visual_review_model: str = GATEWAY_PAGE_OCR
    image_model: str = GATEWAY_IMAGE_SUNBURST
    draw_model: str = GATEWAY_IMAGE_SUNBURST

    # Output language for generated book text and visual assets.
    target_language: str = "en"
    # Creation choice. Existing editions retain their frozen capability profile.
    lettering_mode: Literal["editable", "integrated"] = "editable"

    # Local development mode uses a separate lightweight concurrency limit.
    dev_mode: bool = False

    dev_image_concurrency: int = 5

    # Image generation
    image_quality: str = "medium"  # OpenAI GPT Image quality: auto | low | medium | high

    # Max style/cast image generations in parallel. None uses the general limit.
    image_concurrency: int | None = None

    # LLM style-sample brief: compose the shared subject/setting prose for S2
    # style proof images (via prompt_model), cached per project so every
    # candidate style renders the identical scene. Falls back to a
    # deterministic first-character/first-location body when disabled or when
    # the call fails.
    style_sample_brief_enabled: bool = True

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
    max_concurrent_requests: int = 5  # Parallel Adapt/Plan text requests; image fallback when image_concurrency is unset
    cost_limit_usd: Optional[float] = None

    def effective_image_model(self) -> str:
        return self._one_shot_image_model_alias or self.image_model

    def effective_extraction_model(self) -> str:
        return self.extraction_model

    def effective_brief_model(self) -> str:
        return self.brief_model

    def effective_adapt_model(self) -> str:
        return self.adapt_model

    def effective_plan_model(self) -> str:
        return self.plan_model

    def effective_prompt_model(self) -> str:
        return self.prompt_model

    def effective_page_ocr_model(self) -> str:
        return self.page_ocr_model

    def effective_visual_review_model(self) -> str:
        return self.visual_review_model

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

    def effective_text_concurrency(self) -> int:
        """Parallel structured text requests (Adapt shards, reviews, Plan batches)."""
        return max(1, self.max_concurrent_requests)

    def effective_image_concurrency(self) -> int:
        if self.dev_mode:
            return max(1, self.dev_image_concurrency)
        if self.image_concurrency is not None:
            return max(1, self.image_concurrency)
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
        # Deployment environment wins over a project-adjacent .env file.
        load_dotenv(env_file, override=False)

    config_path = project_dir / "config.yaml"
    data: dict = {}
    if config_path.exists():
        with open(config_path) as f:
            data = yaml.safe_load(f) or {}

    for key in (
        "quality_preset", "extraction_model", "brief_model", "adapt_model", "plan_model",
        "prompt_model", "page_ocr_model", "visual_review_model", "image_model", "draw_model",
        "fallback_image_model", "image_provider", "google_use_vertex_ai",
        "google_cloud_project", "google_cloud_location", "flux_guidance_scale",
        "negative_prompt", "image_steps",
        "litellm_base_url", "litellm_api_key", "ai_bill_failed_requests",
        "mock_model_base_url",
    ):
        data.pop(key, None)

    # Overlay env vars.  Explicit shell exports beat .env.
    for env_name, field_name in _ENV_KEYS.items():
        val = os.environ.get(env_name, "").strip()
        if val:
            data[field_name] = val

    return Config(**data), env_file


def save_config(config: Config, project_dir: Path) -> None:
    """Persist only project-owned settings; operator defaults own model routing."""
    data = {
        "target_language": config.language_code(),
        "lettering_mode": config.lettering_mode,
        "dev_model_selections": config.dev_model_selections,
        "dev_mode": config.dev_mode,
        "dev_image_concurrency": config.dev_image_concurrency,
        "extraction_chunk_chars": config.extraction_chunk_chars,
        "narrative_max_calls": config.narrative_max_calls,
        "style_sample_brief_enabled": config.style_sample_brief_enabled,
        "image_quality": config.image_quality,
        "image_concurrency": config.image_concurrency,
        "style_template": config.style_template,
        "parallel_batch_size": config.parallel_batch_size,
        "max_concurrent_requests": config.max_concurrent_requests,
        "cost_limit_usd": config.cost_limit_usd,
    }
    if config.mock_mode:
        data["mock_mode"] = True
    header = (
        "# Project settings. Operator model defaults apply to every new job.\n"
        "# dev_model_selections is available only on a local development server.\n"
        "# API credentials and gateway configuration belong in the server environment.\n"
    )
    (project_dir / "config.yaml").write_text(
        header + yaml.safe_dump(data, sort_keys=False, allow_unicode=True)
    )
