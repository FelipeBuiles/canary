"""Pipeline configuration loaded from config.yaml + .env."""

import os
from pathlib import Path
from typing import Literal, Optional

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict


LANGUAGE_NAMES: dict[str, str] = {
    "en": "English",
    "es": "Spanish",
    "fr": "French",
}

# Env var name → Config field name
_ENV_KEYS: dict[str, str] = {
    "GEMINI_API_KEY": "gemini_api_key",
    "ANTHROPIC_API_KEY": "anthropic_api_key",
    "TOGETHER_API_KEY": "together_api_key",
    "OPENAI_API_KEY": "openai_api_key",
    "OPENROUTER_API_KEY": "openrouter_api_key",
    "GOOGLE_CLOUD_PROJECT": "google_cloud_project",
    "GOOGLE_CLOUD_LOCATION": "google_cloud_location",
}


class Config(BaseModel):
    """Pipeline configuration. Loaded from config.yaml in the project directory."""

    model_config = ConfigDict(validate_assignment=True)

    # API Keys — load from .env or environment variables instead of hardcoding here
    gemini_api_key: str = ""
    anthropic_api_key: str = ""
    together_api_key: str = ""
    openai_api_key: str = ""
    openrouter_api_key: str = ""

    # Google Gemini access. Vertex AI uses Application Default Credentials
    # instead of Gemini Developer API keys.
    google_use_vertex_ai: bool = True
    google_cloud_project: str = ""
    google_cloud_location: str = "global"

    # Model choices
    # NOTE: Gemini 2.5 Pro/Flash deprecated June 17 2026 — using 3.1/Flash-Lite
    extraction_model: str = "gemini-3.1-pro-preview"
    screenplay_model: str = "gemini-3.1-pro-preview"
    panel_model: str = "gemini-3.1-flash-lite-preview"
    prompt_model: str = "gemini-3.1-flash-lite-preview"
    embedding_model: str = "gemini-embedding-001"  # Google Vertex AI, 3072 dims
    image_provider: Literal["gemini", "openai", "openrouter", "together"] = "gemini"
    image_model: str = "gemini-3-pro-image-preview"   # Nano Banana Pro — Gemini 3 Pro Image (native)
    fallback_image_model: str = "gemini-3.1-flash-image-preview"  # Nano Banana 2 — faster dev image model

    # Output language for generated screenplay dialogue, panel text, and prompt artifacts.
    target_language: str = "en"

    # Dev/demo mode — lowers image generation resolution/steps and prefers the
    # faster Gemini Flash image model when the default production model is used.
    dev_mode: bool = False
    dev_image_scale: float = 0.5
    dev_image_steps: int = 8
    dev_image_concurrency: int = 5

    # Image generation
    # Width/height are used for Together AI models; Gemini native chooses its own resolution.
    image_width: int = 1024
    image_height: int = 1024
    image_steps: int = 28
    image_quality: str = "auto"  # OpenAI GPT Image quality: auto | low | medium | high
    flux_guidance_scale: float = 3.5
    continuity_mode: str = "hybrid"  # off | text_only | ref_only | hybrid

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
    #   Realistic:   "Cinematic photorealistic, natural lighting, film grain, shallow DOF."
    #   Comic:       "Bold graphic novel style, cel-shaded coloring, thick ink outlines."
    #   Painted:     "Oil painting, visible brushwork, rich saturated colour."
    style_template: str = (
        "High quality visual storytelling. Dramatic natural lighting, detailed environments. "
        "Faces rendered with natural individuality and subtle imperfection — never idealized or airbrushed. "
        "All facial expressions understated and restrained; emotion conveyed through the eyes and posture alone."
    )

    # Pipeline settings
    enable_rag_index: bool = False
    max_panels_per_scene: int = 8
    max_panels_per_page: int = 6    # how many panels appear on each assembled page
    max_words_per_bubble: int = 35
    parallel_batch_size: int = 5
    qdrant_host: str = "localhost"
    qdrant_port: int = 6333
    max_concurrent_requests: int = 5
    cost_limit_usd: Optional[float] = None

    # Assembly theme
    # "auto" detects from style_template keywords (noir/manga/vintage/painted/default)
    # Override: "default" | "noir" | "manga" | "vintage" | "painted"
    # Fine-grained control: edit project_dir/assembly/theme.css after first run
    comic_theme: str = "auto"

    def effective_image_model(self) -> str:
        if self.dev_mode and self.image_model == "gemini-3-pro-image-preview":
            return self.fallback_image_model or "gemini-3.1-flash-image-preview"
        return self.image_model

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

    def effective_image_concurrency(self, *, google_model: bool = False) -> int:
        if self.dev_mode:
            return max(1, self.dev_image_concurrency)
        if google_model:
            return 1
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
    config_path.write_text(f"""\
# novel-to-comic pipeline configuration
# Generated by `pipeline init`. Edit before running any stages.

# ---------------------------------------------------------------------------
# API Keys  — put these in .env instead of here (see .env.example)
# ---------------------------------------------------------------------------
# Google Gemini defaults to Vertex AI via Application Default Credentials.
# For local dev, run `gcloud auth application-default login`, or set
# GOOGLE_APPLICATION_CREDENTIALS to a service account JSON file.
#
# Non-Google providers still use API keys:
#   ANTHROPIC_API_KEY   — https://console.anthropic.com/
#   TOGETHER_API_KEY    — https://api.together.ai/settings/api-keys
#   OPENAI_API_KEY      — optional, only for OpenAI embeddings
#   OPENROUTER_API_KEY  — https://openrouter.ai/settings/keys
gemini_api_key: ""
anthropic_api_key: ""
together_api_key: ""
openai_api_key: ""
openrouter_api_key: ""

# Set false only if you intentionally want to use GEMINI_API_KEY instead of Vertex AI.
google_use_vertex_ai: {str(config.google_use_vertex_ai).lower()}
google_cloud_project: "{config.google_cloud_project}"
google_cloud_location: "{config.google_cloud_location}"

# ---------------------------------------------------------------------------
# Model choices
# ---------------------------------------------------------------------------
# Stage 1 – full-novel extraction (1M context window required)
extraction_model: "{config.extraction_model}"

# Stage 3 – screenplay adaptation (creative writing quality matters here)
screenplay_model: "{config.screenplay_model}"

# Stage 4 – panel breakdown (structured JSON from screenplay)
panel_model: "{config.panel_model}"

# Stage 5 – image prompt assembly (template filling)
prompt_model: "{config.prompt_model}"

# Optional experimental RAG index. Disabled by default because the current
# screenplay/prompt stages read scene files directly and do not query Qdrant.
enable_rag_index: {str(config.enable_rag_index).lower()}

# Embeddings for optional RAG index (Google gemini-embedding-001 = 3072 dims on Vertex AI)
# Switch to "text-embedding-3-small" for OpenAI (1536 dims, $0.02/M tokens)
# WARNING: changing this after building a RAG index requires rebuilding that index
embedding_model: "{config.embedding_model}"

# Image generation provider/model
# image_provider: gemini | openai | openrouter | together
image_provider: "{config.image_provider}"
#
# Nano Banana Pro  (Gemini 3 Pro Image, default): "gemini-3-pro-image-preview"
# Nano Banana 2    (Gemini 3.1 Flash Image):      "gemini-3.1-flash-image-preview"
# OpenAI:                                         "gpt-image-1"
# OpenRouter:                                     "black-forest-labs/flux-1-dev"
# Together AI:                                    "black-forest-labs/FLUX.1-kontext-pro"
image_model: "{config.image_model}"

# Dev-mode fallback used when image_model is the default Gemini Pro Image model.
# Leave blank to keep the configured image_model in dev_mode.
fallback_image_model: "{config.fallback_image_model}"

# Generated text language: en | es | fr
target_language: "{config.language_code()}"

# Dev/demo mode trades image fidelity for iteration speed.
# When enabled, generated images use scaled-down dimensions, fewer diffusion
# steps where supported, and Gemini Flash Image instead of Gemini Pro Image
# unless a custom image_model is explicitly configured.
dev_mode: {str(config.dev_mode).lower()}
dev_image_scale: {config.dev_image_scale}
dev_image_steps: {config.dev_image_steps}
dev_image_concurrency: {config.dev_image_concurrency}

# ---------------------------------------------------------------------------
# Image generation settings
# ---------------------------------------------------------------------------
image_width: {config.image_width}       # pixels — 1024 recommended for square panels
image_height: {config.image_height}     # pixels — same as width for 1:1 square panels
image_steps: {config.image_steps}       # inference steps — 28 is a good balance
image_quality: "{config.image_quality}"  # OpenAI GPT Image only: auto | low | medium | high
flux_guidance_scale: {config.flux_guidance_scale}  # 3.5–4.5 recommended for FLUX.2 Pro
continuity_mode: "{config.continuity_mode}"  # off | text_only | ref_only | hybrid
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
#     Cinematic photorealistic, natural film grain, shallow depth of field,
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
#     dramatic chiaroscuro lighting, textured canvas feel.
#
style_template: |
  {config.style_template}

# ---------------------------------------------------------------------------
# Pipeline settings
# ---------------------------------------------------------------------------
# Max panels produced per scene (3–8 recommended; action scenes can go higher)
max_panels_per_scene: {config.max_panels_per_scene}

# Max panels per comic page (4–6 recommended)
max_panels_per_page: {config.max_panels_per_page}

# Max words per speech bubble before the screenplay stage splits dialogue
max_words_per_bubble: {config.max_words_per_bubble}

# How many scenes to process in parallel (stages 3–5)
# Reduce if you hit rate limits
parallel_batch_size: {config.parallel_batch_size}

# How many image generation requests to fire simultaneously (stage 6)
# Together AI default rate limit: 10 req/s — keep this at 5 to be safe
max_concurrent_requests: {config.max_concurrent_requests}

# Qdrant vector store connection (used in stage 2)
qdrant_host: "{config.qdrant_host}"
qdrant_port: {config.qdrant_port}

# Hard cost cap in USD — pipeline pauses stage 6 if total_cost_usd exceeds this.
# Set to null to disable.
cost_limit_usd: {cost_limit}

# ---------------------------------------------------------------------------
# Assembly theme (stage 7)
# ---------------------------------------------------------------------------
# "auto" = detected from style_template keywords (noir/manga/vintage/painted/default)
# Set explicitly to override: default | noir | manga | vintage | painted
# For fine-grained control, edit assembly/theme.css after the first run.
# HTML previews are written to assembly/html/ — open in any browser to iterate.
comic_theme: "{config.comic_theme}"
""")
