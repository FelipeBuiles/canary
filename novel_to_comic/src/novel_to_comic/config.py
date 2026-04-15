"""Pipeline configuration loaded from config.yaml + .env."""

import os
from pathlib import Path
from typing import Optional

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel

# Env var name → Config field name for all sensitive keys
_ENV_KEYS: dict[str, str] = {
    "GEMINI_API_KEY": "gemini_api_key",
    "ANTHROPIC_API_KEY": "anthropic_api_key",
    "TOGETHER_API_KEY": "together_api_key",
    "OPENAI_API_KEY": "openai_api_key",
}


class Config(BaseModel):
    """Pipeline configuration. Loaded from config.yaml in the project directory."""

    # API Keys — load from .env or environment variables instead of hardcoding here
    gemini_api_key: str = ""
    anthropic_api_key: str = ""
    together_api_key: str = ""
    openai_api_key: str = ""

    # Model choices
    # NOTE: Gemini 2.5 Pro/Flash deprecated June 17 2026 — using 3.1/Flash-Lite
    extraction_model: str = "gemini-3.1-pro-preview"
    screenplay_model: str = "gemini-3.1-pro-preview"
    panel_model: str = "gemini-3.1-flash-lite-preview"
    prompt_model: str = "gemini-3.1-flash-lite-preview"
    embedding_model: str = "gemini-embedding-2-preview"  # Google, 3072 dims, $0.00625/M tokens
    image_model: str = "gemini-3-pro-image-preview"   # Nano Banana Pro — Gemini 3 Pro Image (native)
    fallback_image_model: str = "gemini-3.1-flash-image-preview"  # Nano Banana 2 — faster, used on 429

    # Image generation
    # Width/height are used for Together AI models; Gemini native chooses its own resolution.
    image_width: int = 1024
    image_height: int = 1024
    image_steps: int = 28
    flux_guidance_scale: float = 3.5

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

    # Overlay env vars for API key fields.  Explicit shell exports beat .env.
    for env_name, field_name in _ENV_KEYS.items():
        val = os.environ.get(env_name, "").strip()
        if val:
            data[field_name] = val

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
# Leave blank. Keys are loaded from .env or shell environment variables:
#   GEMINI_API_KEY      — https://aistudio.google.com/apikey
#   ANTHROPIC_API_KEY   — https://console.anthropic.com/
#   TOGETHER_API_KEY    — https://api.together.ai/settings/api-keys
#   OPENAI_API_KEY      — optional, only for OpenAI embeddings
gemini_api_key: ""
anthropic_api_key: ""
together_api_key: ""
openai_api_key: ""

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

# Embeddings for RAG index (Google gemini-embedding-2-preview = 3072 dims, $0.00625/M tokens)
# Switch to "text-embedding-3-small" for OpenAI (1536 dims, $0.02/M tokens)
# WARNING: changing this after Stage 2 requires rebuilding the Qdrant index
embedding_model: "{config.embedding_model}"

# Image generation model
# Nano Banana Pro  (Gemini 3 Pro Image, default): "gemini-3-pro-image-preview"
# Nano Banana 2    (Gemini 3.1 Flash Image):      "gemini-3.1-flash-image-preview"
# Imagen 4 Ultra   (highest quality, low quota):  "imagen-4.0-ultra-generate-001"
# Imagen 4 Fast    (higher quota):                "imagen-4.0-fast-generate-001"
# Together AI:                                    "black-forest-labs/FLUX.1-kontext-pro"
image_model: "{config.image_model}"

# Fallback used automatically when image_model returns a 429 rate-limit error.
# Leave blank to disable.
fallback_image_model: "{config.fallback_image_model}"

# ---------------------------------------------------------------------------
# Image generation settings
# ---------------------------------------------------------------------------
image_width: {config.image_width}       # pixels — 1024 recommended for square panels
image_height: {config.image_height}     # pixels — same as width for 1:1 square panels
image_steps: {config.image_steps}       # inference steps — 28 is a good balance
flux_guidance_scale: {config.flux_guidance_scale}  # 3.5–4.5 recommended for FLUX.2 Pro
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
