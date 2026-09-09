"""Small deterministic helpers for Style proof-image briefs."""

from __future__ import annotations

import re
from dataclasses import dataclass

from novel_to_comic.models.story_bible import Character, Location, Scene, StoryBible


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


@dataclass(frozen=True)
class StyleSampleSelection:
    characters: tuple[Character, ...]
    location: Location | None
    scene: Scene | None


def style_sample_selection(story_bible: StoryBible) -> StyleSampleSelection:
    """Select one bounded scene roster, never subjects inferred from prose."""
    characters = {character.id: character for character in story_bible.characters}
    locations = {location.id: location for location in story_bible.locations}
    for scene in story_bible.scenes:
        ids = tuple(dict.fromkeys(scene.character_ids))
        if (
            1 <= len(ids) <= 4
            and all(character_id in characters for character_id in ids)
            and scene.location_id in locations
        ):
            return StyleSampleSelection(
                tuple(characters[character_id] for character_id in ids),
                locations[scene.location_id],
                scene,
            )
    return StyleSampleSelection(
        tuple(story_bible.characters[:1]),
        story_bible.locations[0] if story_bible.locations else None,
        None,
    )


def style_sample_fallback_brief(story_bible: StoryBible) -> str:
    selection = style_sample_selection(story_bible)
    names = ", ".join(character.name for character in selection.characters)
    subjects = f"the listed subjects ({names})" if names else "the environment alone"
    location = selection.location.name if selection.location else "the story environment"
    return (
        f"A coherent three-panel micro-beat shows {subjects} in {location}. "
        "Depict only the listed subjects, preserving each one's species and anatomy. "
        "Begin with the environment, show each subject at three-quarter or full length "
        "in a quiet moment, then finish on an expressive detail. Directional light "
        "models their forms while the setting retains clear depth and material variety."
    )
