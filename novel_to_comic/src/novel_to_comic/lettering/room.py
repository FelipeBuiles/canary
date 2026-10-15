"""Room for editable lettering in a panel's framing; provider-free.

Editable lettering lands on finished art, so the art must leave somewhere to
put it. Plan and Draw share these rules for editable editions only; an
integrated edition paints its copy and frames panels however Plan chose.
The room is continuous scene (wall, ceiling, sky, floor), never a blank area.
"""

from __future__ import annotations

# Shots where faces fill the panel and leave no dead space.
TIGHT_SHOTS = frozenset({"extreme_close_up", "close_up", "medium_close_up"})
# More copy than this needs a medium or wider shot: a close-up keeps about
# two short balloons clear of the faces.
WIDE_FRAMING_WORDS = 25


def panel_words(content) -> int:
    return sum(len(item.text.split()) for item in content.lettering)


def needs_wider_framing(content) -> bool:
    """Wordy panels Plan framed tight; Draw opens them to a medium shot."""
    camera = content.camera
    return (
        camera is not None and camera.shot in TIGHT_SHOTS
        and panel_words(content) > WIDE_FRAMING_WORDS
    )


def framing_notes(page) -> list[str]:
    """Per-panel Draw framing for an editable page's lettered panels."""
    notes = []
    for content in sorted(page.content, key=lambda part: part.order):
        if not content.lettering:
            continue
        if needs_wider_framing(content):
            notes.append(
                f"Panel {content.order}: frame as a MEDIUM shot or wider even where the staging says "
                "close-up, so heads and key action fill no more than the lower two-thirds; keep the "
                "same acting and expressions."
            )
        else:
            notes.append(
                f"Panel {content.order}: keep faces, hands and key props out of the top quarter; "
                "continue the scene there (wall, ceiling, sky, background)."
            )
    return notes
