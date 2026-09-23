"""Explicit account model choices shared by validation and the settings API."""
from novel_to_comic.config import Config
from novel_to_comic.codex_dev import selectable_models, selector_available, model_has_vision, process_setting, validate_local_runtime, CodexRoutingError
from novel_to_comic.image_models import IMAGE_MODEL_ALIASES, describe_image_model

# Keep controls in pipeline order. Style/Cast share settings; Draw has three
# distinct model jobs rather than three additional pipeline stages.
STAGE_FIELDS = {
    "extract": "extraction_model", "brief": "brief_model",
    "prompt": "prompt_model", "image": "image_model",
    "adapt": "adapt_model", "plan": "plan_model",
    "draw": "draw_model", "ocr": "page_ocr_model", "visual_review": "visual_review_model",
}
STAGE_LABELS = {
    "extract": "1. Extract — story analysis",
    "brief": "2. Brief — creative direction",
    "prompt": "3–4. Style & Cast — text",
    "image": "3–4. Style & Cast — images",
    "adapt": "5. Adapt — script & dialogue",
    "plan": "6. Plan — page layouts",
    "draw": "7. Draw — page artwork",
    "ocr": "7. Draw — lettering checks",
    "visual_review": "7. Draw — visual review",
}
STAGE_DESCRIPTIONS = {
    "extract": "Reads the manuscript and identifies scenes, characters, places, and appearance changes.",
    "brief": "Proposes the creative brief that guides how the story becomes a comic.",
    "prompt": "Shared by Style and Cast: suggests visual styles, writes sample briefs, and rewrites asset instructions.",
    "image": "Shared by Style and Cast: generates style samples, character references, location images, props, and covers.",
    "adapt": "Writes the comic adaptation: narrative treatment, pacing, captions, and exact dialogue.",
    "plan": "Turns the adaptation into pages and panels, placing characters, actions, and lettering.",
    "draw": "Generates each complete comic page with artwork and the lettering written by Adapt.",
    "ocr": "After a page is drawn, reads its lettering to check for missing or incorrect text.",
    "visual_review": "Reviews drawn pages against approved references for visual issues such as character or costume changes.",
}
TEXT_MODELS = (
    {"id": "gpt-6-sol", "label": "GPT-6 Sol", "provider": "OpenAI"},
    {"id": "gpt-6-luna", "label": "GPT-6 Luna", "provider": "OpenAI"},
    {"id": "claude-fable-5-1", "label": "Claude Fable 5.1", "provider": "Anthropic"},
    {"id": "claude-opus-5", "label": "Claude Opus 5", "provider": "Anthropic"},
    {"id": "mimo-v2.6-pro", "label": "MiMo V2.6 Pro", "provider": "OpenRouter"},
)
DRAW_MODELS = ("image-sunburst",)


def codex_models() -> list[dict]:
    if process_setting("CANARY_ENV") != "development":
        return []
    try:
        validate_local_runtime()
    except CodexRoutingError:
        return []
    return [{
        "id": f"codex-dev/{kind}/{model}",
        "label": f"Codex · {model}" if kind == "text" else f"Codex images · {model}",
        "provider": "Codex subscription", "kind": kind,
        "vision": model_has_vision(model), "funding": "codex_subscription",
        "available": selector_available(),
        "description": "Codex reasoning model; built-in image generation uses the GPT Image 2 selector, not GPT Image 2.5." if kind == "image" else "Specific Codex reasoning model using your local subscription session.",
    } for model in selectable_models() for kind in ("text", "image")
        if kind == "text" or model_has_vision(model)]


def models(*, include_codex: bool = True) -> list[dict]:
    return [
        *(codex_models() if include_codex else []),
        *[dict(model, kind="text", vision=True, funding="api") for model in TEXT_MODELS],
        *[{
            "id": model, "label": describe_image_model(model).display_name,
            "provider": describe_image_model(model).provider_key,
            "kind": "image", "vision": True, "funding": "api",
        } for model in IMAGE_MODEL_ALIASES],
    ]


def allowed_models(stage: str, *, include_codex: bool = True) -> tuple[str, ...]:
    codex = tuple(model["id"] for model in codex_models() if model["kind"] == ("image" if stage in {"image", "draw"} else "text") and (stage not in {"ocr", "visual_review"} or model["vision"])) if include_codex else ()
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
