"""Book-wide visual production standards selected by the Style stage."""

import json
from typing import Literal

from novel_to_comic.rendering_fidelity import (
    RENDERING_FIDELITY_BLOCK,
    RENDERING_FIDELITY_MARKER,
)
from novel_to_comic.models.lettering import LetteringDesign

DEFAULT_LETTERING_STANDARD = (
    "Preserve every canonical lettering string and its capitalization exactly. Use one "
    "consistent humanist comic-lettering typeface family throughout the book: regular "
    "weight for dialogue and semibold for narration. Set dialogue in near-black on white "
    "balloons and narration in near-black on warm off-white caption boxes, all with the "
    "same clean solid near-black outline weight. Reserve display lettering for SFX only."
)
DEFAULT_PAGE_FRAMING_STANDARD = (
    "Use the same fixed outer page margin and straight solid panel-border weight on every "
    "page, with uniform interior gutters. Keep artwork inside that frame: no full bleed, "
    "scribbled borders, torn edges, or page-by-page changes to the framing system."
)
LETTERING_MARKER = "LETTERING STANDARD —"
FRAMING_MARKER = "PAGE FRAMING STANDARD —"
DESIGN_MARKER = "POST-PRODUCTION LETTERING DESIGN —"
CHARACTER_DESIGN_MARKER = "CHARACTER DESIGN —"


def rendering_style_template(visual_style: str) -> str:
    """Extract art direction without page lettering or framing contracts."""
    rendering = visual_style or ""
    for marker in (LETTERING_MARKER, FRAMING_MARKER, "POST-PRODUCTION LETTERING PRESET —",
                   DESIGN_MARKER, RENDERING_FIDELITY_MARKER):
        rendering = rendering.split(marker, 1)[0]
    return rendering.strip()


def figure_free_style_template(visual_style: str) -> str:
    """The selected style without its character proportion system.

    Plates, props and form or formation sheets show no figure. Proportion
    direction such as squared jaws or heroic torsos made form sheets invent a
    human face for an entity whose anchor gives it none.
    """
    if CHARACTER_DESIGN_MARKER not in (visual_style or ""):
        return visual_style or ""
    before, after = visual_style.split(CHARACTER_DESIGN_MARKER, 1)
    remainder = after.split("\n\n", 1)[1] if "\n\n" in after else ""
    return "\n\n".join(part for part in (before.strip(), remainder.strip()) if part)


def page_style_template(
    visual_style: str,
    *,
    lettering: str = DEFAULT_LETTERING_STANDARD,
    page_framing: str = DEFAULT_PAGE_FRAMING_STANDARD,
) -> str:
    """Join visual art direction to the book-wide production invariants."""
    visual_style = (visual_style or "").strip()
    sections = [visual_style]
    if LETTERING_MARKER not in visual_style:
        sections.append(
            f"{LETTERING_MARKER} "
            f"{(lettering or DEFAULT_LETTERING_STANDARD).strip()}"
        )
    if FRAMING_MARKER not in visual_style:
        sections.append(
            f"{FRAMING_MARKER} "
            f"{(page_framing or DEFAULT_PAGE_FRAMING_STANDARD).strip()}"
        )
    return "\n\n".join(section for section in sections if section).strip()


def normalize_production_standard(
    value: object, *, kind: Literal["lettering", "page_framing"],
) -> str:
    """Normalize production prose without leaking structured Python reprs."""
    default = DEFAULT_LETTERING_STANDARD if kind == "lettering" else DEFAULT_PAGE_FRAMING_STANDARD
    if isinstance(value, str):
        return value.strip() or default
    if isinstance(value, dict):
        parts = [
            f"{str(key).replace('_', ' ')}: {item.strip()}"
            for key, item in value.items()
            if isinstance(item, str) and item.strip()
        ]
        return "; ".join(parts) or default
    return default


def style_template_for_suggestion(suggestion: dict) -> str:
    """Return the complete selected style authority for samples and pages."""
    visual_style = str(suggestion.get("template") or "")
    character_design = str(suggestion.get("character_design") or "").strip()
    if character_design:
        family = str(suggestion.get("proportion_family") or "").strip()
        rendering_direction = {
            "stylized": "Clearly stylized illustration, not photographic rendering.",
            "graphic": "Deliberate graphic abstraction and designed shapes, not photographic anatomy.",
            "realistic_illustration": "Observational drawing or painting, visibly illustrated rather than photographed.",
            "photographic": "Lens-based photographic rendering with naturalistic anatomy and materials.",
        }.get(suggestion.get("visual_logic"), "")
        if rendering_direction:
            visual_style += "\n\nRENDERING APPROACH — " + rendering_direction
        visual_style += (
            f"\n\n{CHARACTER_DESIGN_MARKER} " + (f"{family}: " if family else "") + character_design
            + " Preserve this proportion and shape system consistently across all subjects "
            "and panels, adapted to each subject's species, age and identifying traits."
        )
    template = page_style_template(
        visual_style,
        lettering=normalize_production_standard(suggestion.get("lettering"), kind="lettering"),
        page_framing=normalize_production_standard(suggestion.get("page_framing"), kind="page_framing"),
    )
    preset = suggestion.get("lettering_preset")
    if preset in {"literary", "classic", "pulp", "minimal"}:
        template += f"\n\nPOST-PRODUCTION LETTERING PRESET — {preset}"
    if suggestion.get("lettering_design") is not None:
        design = LetteringDesign.model_validate(suggestion["lettering_design"])
        template += f"\n\n{DESIGN_MARKER} " + json.dumps(
            design.model_dump(mode="json"), sort_keys=True, separators=(",", ":"),
        )
    return template


POST_LETTERING_MARKER = "POST-PRODUCTION LETTERING PRESET —"


def page_art_style_template(visual_style: str) -> str:
    """Visual rendering and framing, never typesetting instructions."""
    visual_style = visual_style.split(DESIGN_MARKER, 1)[0]
    rendering = rendering_style_template(visual_style).split(POST_LETTERING_MARKER)[0].strip()
    framing = (visual_style.split(FRAMING_MARKER, 1)[1].split(POST_LETTERING_MARKER)[0].strip()
               if FRAMING_MARKER in visual_style else DEFAULT_PAGE_FRAMING_STANDARD)
    # The same policy as Style/Cast, included in the frozen hybrid page prompt.
    # Strip only our production suffix on repeated projection, never art prose.
    framing = framing.split(RENDERING_FIDELITY_MARKER, 1)[0].strip()
    return f"{rendering}\n\n{FRAMING_MARKER} {framing}\n\n{RENDERING_FIDELITY_BLOCK}"


def post_production_lettering_direction(template: str) -> str:
    template = template.split(DESIGN_MARKER, 1)[0]
    if LETTERING_MARKER not in template:
        return DEFAULT_LETTERING_STANDARD
    return template.split(LETTERING_MARKER, 1)[1].split(FRAMING_MARKER)[0].split(POST_LETTERING_MARKER)[0].strip()


def lettering_design_from_template(template: str) -> LetteringDesign | None:
    """Decode the selected software-only design; corrupt designs are not ignored."""
    if DESIGN_MARKER not in template:
        return None
    return LetteringDesign.model_validate_json(template.split(DESIGN_MARKER, 1)[1].strip())
