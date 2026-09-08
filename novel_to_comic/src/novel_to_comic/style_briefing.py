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
    character = first_character.name if first_character else "the story's focal subject"
    location = first_location.name if first_location else "the established story environment"
    scene = next(
        (scene.summary for scene in story_bible.scenes
         if (not first_character or first_character.id in scene.character_ids)
         and (not first_location or first_location.id == scene.location_id)),
        "",
    )
    context = f" Use this quiet story context: {scene}" if scene else ""
    return (
        f"A coherent three-panel micro-beat follows one figure — {character} — in "
        f"{location}.{context} Begin with the environment, show the figure at "
        "three-quarter or full length during one quiet characteristic action, then "
        "finish on an expressive detail. Directional light models the face and figure "
        "while the setting retains clear depth and material variety."
    )
