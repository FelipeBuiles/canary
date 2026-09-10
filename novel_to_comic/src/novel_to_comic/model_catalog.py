"""Explicit account model choices shared by validation and the settings API."""
from novel_to_comic.config import Config
from novel_to_comic.codex_dev import selectable_models, selector_available, model_has_vision
from novel_to_comic.image_models import IMAGE_MODEL_ALIASES, describe_image_model

STAGE_FIELDS = {
    "extract": "extraction_model", "brief": "brief_model", "adapt": "adapt_model",
    "plan": "plan_model", "prompt": "prompt_model", "image": "image_model",
    "draw": "draw_model", "ocr": "page_ocr_model", "visual_review": "visual_review_model",
}
STAGE_LABELS = {
    "extract": "Novel extraction", "brief": "Creative brief", "adapt": "Adaptation",
    "plan": "Page planning", "prompt": "Style and cast text", "image": "Style and cast images",
    "draw": "Comic pages", "ocr": "Lettering checks", "visual_review": "Visual review",
}
TEXT_MODELS = (
    {"id": "gpt-5.6-terra", "label": "GPT-5.6 Terra", "provider": "OpenAI"},
    {"id": "gpt-5.6-luna", "label": "GPT-5.6 Luna", "provider": "OpenAI"},
    {"id": "gemini-3.8-flash", "label": "Gemini 3.8 Flash", "provider": "Google Vertex AI"},
    {"id": "deepseek-v4.1-flash", "label": "DeepSeek V4.1 Flash", "provider": "OpenRouter"},
    {"id": "glm-5.3-flash", "label": "GLM 5.3 Flash", "provider": "OpenRouter"},
)
DRAW_MODELS = ("image-gemini-pro", "image-sunburst", "image-flare")


FUNDING_GROUPS = (
    {"label": "Extraction and brief", "stages": ["extract", "brief"]},
    {"label": "Adaptation and planning", "stages": ["adapt", "plan"]},
    {"label": "Style text and images", "stages": ["prompt", "image"]},
    {"label": "Draw and lettering checks", "stages": ["draw", "ocr"]},
)


def codex_models() -> list[dict]:
    return [{
        "id": f"codex-dev/{kind}/{model}",
        "label": f"Codex · {model}" if kind == "text" else f"Codex images · {model}",
        "provider": "Codex subscription", "kind": kind,
        "vision": model_has_vision(model), "funding": "codex_subscription",
        "available": selector_available(),
        "description": "Codex reasoning model; built-in image generation uses the GPT Image 2 selector, not GPT Image 2.5." if kind == "image" else "Specific Codex reasoning model using your local subscription session.",
    } for model in selectable_models() for kind in ("text", "image")
        if kind == "text" or model_has_vision(model)]


def models() -> list[dict]:
    return [
        *codex_models(),
        *[dict(model, kind="text", vision=True, funding="api") for model in TEXT_MODELS],
        *[{
            "id": model, "label": describe_image_model(model).display_name,
            "provider": describe_image_model(model).provider_key,
            "kind": "image", "vision": True, "funding": "api",
        } for model in IMAGE_MODEL_ALIASES],
    ]


def allowed_models(stage: str) -> tuple[str, ...]:
    codex = tuple(model["id"] for model in codex_models() if model["kind"] == ("image" if stage in {"image", "draw"} else "text") and (stage not in {"ocr", "visual_review"} or model["vision"]))
    if stage == "draw":
        return (*DRAW_MODELS, *codex)
    if stage == "image":
        return (*IMAGE_MODEL_ALIASES, *codex)
    if stage in STAGE_FIELDS:
        return (*tuple(model["id"] for model in TEXT_MODELS), *codex)
    raise ValueError(f"Unknown model setting: {stage}")


def default_selections() -> dict[str, str]:
    config = Config()
    return {stage: getattr(config, field) for stage, field in STAGE_FIELDS.items()}


def validate_selections(selections: dict) -> dict[str, str]:
    if not isinstance(selections, dict):
        raise ValueError("selections must be an object")
    for stage, model in selections.items():
        if stage not in STAGE_FIELDS:
            raise ValueError(f"Unknown model setting: {stage}")
        if not isinstance(model, str) or model not in allowed_models(stage):
            raise ValueError(f"Unsupported model for {stage}: {model}")
    return dict(selections)
