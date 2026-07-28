"""Book-wide visual production standards selected by the Style stage."""

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


def style_template_for_suggestion(suggestion: dict) -> str:
    """Return the complete selected style authority for samples and pages."""
    return page_style_template(
        str(suggestion.get("template") or ""),
        lettering=str(suggestion.get("lettering") or DEFAULT_LETTERING_STANDARD),
        page_framing=str(
            suggestion.get("page_framing") or DEFAULT_PAGE_FRAMING_STANDARD
        ),
    )
