"""Prompt assembly — single path from PlannedPanel or ImagePrompt to rendered body.

Both the direct stage (s6_storyboard) and the edit route (stages.update_prompt)
used to call separate functions, risking drift in how the narration-caption
constraint note is applied.  This module is the single owner of that logic:
callers get one function for the build path and one for the re-render path, both
backed by the same constraint normalisation.
"""

import logging
import re
from pathlib import Path

from novel_to_comic.config import Config
from novel_to_comic.models.layout_plan import PlannedPanel
from novel_to_comic.models.prompt import ImagePrompt
from novel_to_comic.models.story_bible import StoryBible
from novel_to_comic.prompting import (
    IMAGE_PROMPT_VERSION,
    _render_panel_prompt_body_parts,
    build_planned_panel_prompt_spec,
    ensure_distilled_prompt,
    visual_brief_source_spec,
)

logger = logging.getLogger(__name__)

_NARRATION_NOTE = (
    "narration caption will be lettered in post-production only; "
    "do not draw caption boxes, speech bubbles, labels, signs, or readable text"
)


def _apply_narration_constraint(constraints: str | None, has_narration_caption: bool) -> str | None:
    """Return constraints with the narration note present iff has_narration_caption.

    Idempotent — safe to call whether or not the note is already embedded
    in the stored constraints string.
    """
    base = (constraints or "").replace(f"; {_NARRATION_NOTE}", "").replace(_NARRATION_NOTE, "").strip("; ")
    if not has_narration_caption:
        return base or None
    return f"{base}; {_NARRATION_NOTE}" if base else _NARRATION_NOTE


def assemble_panel_prompt(
    config: Config,
    project_dir: Path,
    panel: PlannedPanel,
    story_bible: StoryBible,
    prev_panel: PlannedPanel | None = None,
) -> ImagePrompt:
    """Build an ImagePrompt from a PlannedPanel.

    Calls through to ``build_planned_panel_prompt_spec`` in prompting.py.
    The returned prompt has ``full_prompt`` set; call ``ensure_distilled_prompt``
    afterwards if a distilled version is needed before saving.
    """
    return build_planned_panel_prompt_spec(config, project_dir, panel, story_bible, prev_panel)


def prompt_is_current(prompt: ImagePrompt, panel: PlannedPanel) -> bool:
    """True when a stored ImagePrompt still matches its planned panel and schema."""
    return (
        getattr(prompt, "planned_panel_id", None) == panel.panel_id
        and getattr(prompt, "prompt_version", 1) >= IMAGE_PROMPT_VERSION
    )


def ensure_current_panel_prompt(
    config: Config,
    project_dir: Path,
    panel: PlannedPanel,
    story_bible: StoryBible,
    prev_panel: PlannedPanel | None = None,
) -> ImagePrompt:
    """Return the panel's stored ImagePrompt, rebuilding (and persisting) it
    when stale.

    Single owner of the "is this prompt up to date?" decision — the direct
    stage, the draw stage's pre-pass, and single-panel regeneration all call
    this instead of re-implementing the version/panel-id check.
    """
    from novel_to_comic.layout_planning import prompt_path_for_panel

    prompt_path = prompt_path_for_panel(project_dir, panel)
    if prompt_path.exists():
        try:
            existing = ImagePrompt.model_validate_json(prompt_path.read_text())
        except Exception:
            existing = None
        if existing is not None and prompt_is_current(existing, panel):
            return existing
    prompt = build_planned_panel_prompt_spec(config, project_dir, panel, story_bible, prev_panel)
    prompt_path.parent.mkdir(parents=True, exist_ok=True)
    prompt_path.write_text(prompt.model_dump_json(indent=2))
    return prompt


def rerender_prompt_body(prompt: ImagePrompt) -> str:
    """Re-render full_prompt from the stored prompt fields after an edit.

    Handles the narration-caption constraint note idempotently so the note
    never appears twice regardless of whether a previous build already embedded
    it in ``prompt.constraints``.
    """
    constraints = _apply_narration_constraint(
        getattr(prompt, "constraints", None),
        getattr(prompt, "has_narration_caption", False),
    )
    return _render_panel_prompt_body_parts(
        subjects=getattr(prompt, "subjects", []) or [],
        composition=getattr(prompt, "composition", None),
        setting=getattr(prompt, "setting", None),
        lighting=getattr(prompt, "lighting", None),
        mood=getattr(prompt, "mood", None),
        key_objects=getattr(prompt, "key_objects", []) or [],
        visual_requirements=getattr(prompt, "visual_requirements", []) or [],
        props=getattr(prompt, "props", []) or [],
        constraints=constraints,
    )


# ── LLM visual-brief pass ────────────────────────────────────────────────────
#
# The structured ImagePrompt is the source of truth, but image models respond
# best to flowing, art-direction prose — not labeled key:value clauses. This
# pass rewrites the structured spec into that prose with a cheap text model.
# On any failure the prompt simply keeps visual_brief=None and generation
# falls back to the deterministic distilled prompt.

VISUAL_BRIEF_SYSTEM_PROMPT = (
    "You write the final prompt sent to an image-generation model (Reve, GPT Image, "
    "Gemini) for one comic-book panel. Rewrite the structured panel spec you receive "
    "as a single flowing visual brief of 90-160 words: vivid, concrete, present-tense "
    "prose, the way a film director describes one frozen frame.\n"
    "\n"
    "Rules:\n"
    "- Open with the framing (shot type and camera angle), then the subjects.\n"
    "- Introduce each character by name with their full physical description (age, "
    "build, hair, face, wardrobe) immediately, BEFORE their action, so appearance "
    "binds to the right character.\n"
    "- Preserve EVERY concrete visual fact in the spec: appearance, wardrobe, action, "
    "expression, position, props, objects, setting, lighting, mood, must-show details, "
    "caption space. Never invent characters, objects, text, or story beats that are "
    "not in the spec, and never drop one.\n"
    "- Exactly one frozen instant: no sequences, no before/after, no motion trails.\n"
    "- Give light its own concrete sentence: direction, color, quality, and where the "
    "shadows fall.\n"
    "- State spatial relationships explicitly: where each subject and object sits "
    "relative to the others and to the frame.\n"
    "- Respect every hard constraint in the spec (character count, no lettering, "
    "single instant) without quoting it as a rule — express it through the description.\n"
    "- Plain declarative prose only. No headings, labels, bullet points, markdown, "
    "quotation marks, or meta-commentary. Do not mention the spec or that this is a "
    "prompt.\n"
    "- Do not describe art style, medium, or rendering technique — the style template "
    "is appended separately and must not be contradicted.\n"
    "\n"
    "Output only the brief text."
)

_BRIEF_LABEL_RE = re.compile(r"^(?:visual\s+brief|brief|prompt)\s*[:\-]\s*", re.IGNORECASE)


def normalize_prose_brief(raw: str) -> str | None:
    """Clean LLM prose output into a single paragraph, or reject it.

    Shared by the panel visual-brief pass and the S2 style-sample brief.
    """
    text = (raw or "").strip()
    if text.startswith("```"):
        lines = text.split("\n")
        body_lines = lines[1:-1] if len(lines) >= 3 and lines[-1].strip().startswith("```") else lines[1:]
        text = "\n".join(body_lines).strip()
    if text.startswith(("-", "*", "#", ">")):
        return None
    text = re.sub(r"\s+", " ", text).strip().strip('"').strip()
    text = _BRIEF_LABEL_RE.sub("", text).strip()
    if len(text) < 40 or len(text) > 2000:
        return None
    return text


async def generate_visual_brief(config: Config, prompt: ImagePrompt) -> str | None:
    """One LLM call: structured panel spec → prose visual brief.

    Returns None (never raises) when the spec is empty, the call fails, or the
    output fails validation — callers fall back to the distilled prompt.
    """
    spec = visual_brief_source_spec(prompt)
    if not spec.strip():
        return None
    from novel_to_comic.clients import text

    try:
        result = await text.generate_text(
            config=config,
            model=config.effective_prompt_model(),
            system_prompt=VISUAL_BRIEF_SYSTEM_PROMPT,
            user_content=spec,
            temperature=0.4,
            max_output_tokens=4096,
            feature="prompt.visual_brief",
        )
    except Exception:
        logger.warning(
            "Visual brief generation failed for panel %s/%s; falling back to distilled prompt",
            getattr(prompt, "scene_id", "?"),
            getattr(prompt, "panel_number", "?"),
            exc_info=True,
        )
        return None
    brief = normalize_prose_brief(result.value)
    if brief is None:
        logger.warning(
            "Visual brief output rejected for panel %s/%s (malformed or out of bounds); "
            "falling back to distilled prompt",
            getattr(prompt, "scene_id", "?"),
            getattr(prompt, "panel_number", "?"),
        )
    return brief


async def ensure_visual_brief(config: Config, prompt: ImagePrompt) -> ImagePrompt:
    """Return prompt with visual_brief populated when possible.

    Returns the same object when the brief already exists, the pass is
    disabled, or generation fails — callers can use identity to decide
    whether to persist.
    """
    if not getattr(config, "visual_brief_enabled", True):
        return prompt
    if (getattr(prompt, "visual_brief", None) or "").strip():
        return prompt
    brief = await generate_visual_brief(config, prompt)
    if not brief:
        return prompt
    updated = prompt.model_copy(deep=True)
    updated.visual_brief = brief
    return updated


__all__ = [
    "IMAGE_PROMPT_VERSION",
    "VISUAL_BRIEF_SYSTEM_PROMPT",
    "assemble_panel_prompt",
    "ensure_current_panel_prompt",
    "ensure_distilled_prompt",
    "ensure_visual_brief",
    "prompt_is_current",
    "generate_visual_brief",
    "normalize_prose_brief",
    "rerender_prompt_body",
]
