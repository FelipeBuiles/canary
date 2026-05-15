"""Prompt assembly — single path from PlannedPanel or ImagePrompt to rendered body.

Both the direct stage (s6_storyboard) and the edit route (stages.update_prompt)
used to call separate functions, risking drift in how the narration-caption
constraint note is applied.  This module is the single owner of that logic:
callers get one function for the build path and one for the re-render path, both
backed by the same constraint normalisation.
"""

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
)

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


__all__ = [
    "IMAGE_PROMPT_VERSION",
    "assemble_panel_prompt",
    "ensure_distilled_prompt",
    "rerender_prompt_body",
]
