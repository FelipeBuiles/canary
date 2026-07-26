"""Small deterministic helpers for Style proof-image briefs."""

from __future__ import annotations

import re

from novel_to_comic.models.story_bible import StoryBible


_BRIEF_LABEL_RE = re.compile(
    r"^(?:visual\s+brief|brief|prompt)\s*[:\-]\s*",
    re.IGNORECASE,
)


def normalize_prose_brief(raw: str) -> str | None:
    text = (raw or "").strip()
    if text.startswith("```"):
        lines = text.split("\n")
        body = (
            lines[1:-1]
            if len(lines) >= 3 and lines[-1].strip().startswith("```")
            else lines[1:]
        )
        text = "\n".join(body).strip()
    if text.startswith(("-", "*", "#", ">")):
        return None
    text = re.sub(r"\s+", " ", text).strip().strip('"').strip()
    text = _BRIEF_LABEL_RE.sub("", text).strip()
    if len(text) < 40 or len(text) > 2_000:
        return None
    return text


def style_sample_fallback_brief(story_bible: StoryBible) -> str:
    first_character = (
        story_bible.characters[0] if story_bible.characters else None
    )
    first_location = story_bible.locations[0] if story_bible.locations else None
    character = (
        (first_character.visual_anchor if first_character else "")
        or (first_character.name if first_character else "")
        or "a mysterious cloaked figure"
    )[:200]
    location = (
        (first_location.visual_anchor if first_location else "")
        or (first_location.name if first_location else "")
        or "a dramatic atmospheric setting"
    )[:200]
    return (
        f"A three-quarter view of one figure — {character} — in {location}. "
        "One frozen instant with the figure as the clear focal point and the "
        "setting giving depth behind them. Directional light models the face "
        "and figure, with bright accents and deep shadow both in frame."
    )
