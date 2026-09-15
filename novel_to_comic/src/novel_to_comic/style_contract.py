"""Book-wide visual production standards selected by the Style stage."""

from typing import Literal

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


def rendering_style_template(visual_style: str) -> str:
    """Extract art direction without page lettering or framing contracts."""
    rendering = visual_style or ""
    for marker in (LETTERING_MARKER, FRAMING_MARKER, "POST-PRODUCTION LETTERING PRESET —"):
        rendering = rendering.split(marker, 1)[0]
    return rendering.strip()


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
    template = page_style_template(
        str(suggestion.get("template") or ""),
        lettering=normalize_production_standard(suggestion.get("lettering"), kind="lettering"),
        page_framing=normalize_production_standard(suggestion.get("page_framing"), kind="page_framing"),
    )
    preset = suggestion.get("lettering_preset")
    if preset in {"literary", "classic", "pulp", "minimal"}:
        template += f"\n\nPOST-PRODUCTION LETTERING PRESET — {preset}"
    return template


POST_LETTERING_MARKER = "POST-PRODUCTION LETTERING PRESET —"


def page_art_style_template(visual_style: str) -> str:
    """Visual rendering and framing, never typesetting instructions."""
    rendering = rendering_style_template(visual_style).split(POST_LETTERING_MARKER)[0].strip()
    framing = (visual_style.split(FRAMING_MARKER, 1)[1].split(POST_LETTERING_MARKER)[0].strip()
               if FRAMING_MARKER in visual_style else DEFAULT_PAGE_FRAMING_STANDARD)
    return f"{rendering}\n\n{FRAMING_MARKER} {framing}"


def post_production_lettering_direction(template: str) -> str:
    if LETTERING_MARKER not in template:
        return DEFAULT_LETTERING_STANDARD
    return template.split(LETTERING_MARKER, 1)[1].split(FRAMING_MARKER)[0].split(POST_LETTERING_MARKER)[0].strip()
