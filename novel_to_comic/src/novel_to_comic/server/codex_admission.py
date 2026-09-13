"""Provider manifests for route validation and API cost estimates.

A manifest may freely mix local Codex and API operations. Routing authority
lives in codex_dev; the returned label describes whether API spend is present.
"""
from __future__ import annotations

from novel_to_comic.codex_dev import Funding, classify_operations
from novel_to_comic.config import Config

Operations = tuple[tuple[str, str], ...]


def image_operations(config: Config) -> Operations:
    return (("image", config.effective_image_model()),)


def prompt_image_operations(config: Config) -> Operations:
    return (("text", config.effective_prompt_model()), *image_operations(config))


def style_sample_operations(config: Config, *, validation: bool = False) -> Operations:
    if not validation and config.style_sample_brief_enabled:
        return prompt_image_operations(config)
    return image_operations(config)


def page_check_operations(config: Config) -> Operations:
    # Runtime supports image attachments for structured text calls. The actual
    # transport still validates each attachment before creating a subprocess.
    return (("text", config.effective_page_ocr_model()),)


def visual_review_operations(config: Config) -> Operations:
    return (("text", config.effective_visual_review_model()),)


def draw_operations(config: Config, *, ocr: bool = True) -> Operations:
    return (("complete_page", config.draw_model), *(page_check_operations(config) if ocr else ()))


def stage_operations(config: Config, stage: str) -> Operations:
    if stage == "brief":
        return (("text", config.effective_brief_model()),)
    if stage == "extract":
        return (("text", config.effective_extraction_model()),)
    if stage == "adapt":
        return (("text", config.effective_adapt_model()),)
    if stage == "plan":
        return (("text", config.effective_plan_model()),)
    if stage == "style":
        return prompt_image_operations(config)
    if stage == "cast":
        return image_operations(config)
    if stage == "draw":
        return draw_operations(config)
    if stage == "finish":
        return ()
    raise ValueError(f"Unknown stage for provider admission: {stage}")


def action_operations(config: Config, stage: str) -> Operations:
    """Include server autochains even when downstream artifacts do not exist."""
    stages = {"extract": ("extract", "brief"), "adapt": ("adapt", "plan")}.get(stage, (stage,))
    return tuple(operation for item in stages for operation in stage_operations(config, item))


def admit_stage_action(config: Config, stage: str) -> Funding:
    return classify_operations(action_operations(config, stage))
