"""Small deterministic helpers for Style proof-image briefs."""

from __future__ import annotations

import re
from collections import Counter
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


# Scene metadata is free text; these are the extractor's common values.
_SPOILER_BEATS = frozenset({
    "climax", "resolution", "falling_action", "twist", "cliffhanger", "crisis", "denouement",
})
_TURN_BEATS = frozenset({"inciting_incident", "rising_action"})
_SCENE_TYPE_DRAMA = {"action": 2, "emotional": 2, "dialogue": 1}
# Proofs come from the opening of the story.
_OPENING_MIN_SCENES = 8


def _beat(scene: Scene) -> str:
    return re.sub(r"[\s-]+", "_", (scene.narrative_beat or "").strip().lower())


def style_sample_selection(story_bible: StoryBible) -> StyleSampleSelection:
    """Select one bounded scene roster, never subjects inferred from prose.

    A proof sells a style only when its page has drama: prefer an early
    action or emotional scene with the lead character on a turning beat,
    never the climax. Deterministic, so every candidate shares one scene.
    """
    characters = {character.id: character for character in story_bible.characters}
    locations = {location.id: location for location in story_bible.locations}
    narrative = [scene for scene in story_bible.scenes if scene.scene_type != "non_narrative"]
    # The first part's opening: later parts can spoil it and show subjects in
    # appearance states the proof's default anchors do not describe.
    narrative = [scene for scene in narrative if scene.part_id == narrative[0].part_id] if narrative else []
    appearances = Counter(character_id for scene in narrative for character_id in set(scene.character_ids))
    lead = max(appearances, key=lambda character_id: appearances[character_id], default=None)

    def eligible(scene: Scene) -> bool:
        ids = tuple(dict.fromkeys(scene.character_ids))
        return (
            1 <= len(ids) <= 4
            and all(character_id in characters for character_id in ids)
            and scene.location_id in locations
        )

    opening = narrative[:max(_OPENING_MIN_SCENES, -(-len(narrative) // 3))]
    pool = [scene for scene in opening if eligible(scene)] or [
        scene for scene in story_bible.scenes if eligible(scene)
    ]
    if pool:
        scene = max(enumerate(pool), key=lambda item: (
            _beat(item[1]) not in _SPOILER_BEATS,
            lead in item[1].character_ids,
            _SCENE_TYPE_DRAMA.get(item[1].scene_type, 0),
            _beat(item[1]) in _TURN_BEATS,
            -item[0],
        ))[1]
        return StyleSampleSelection(
            tuple(characters[character_id] for character_id in dict.fromkeys(scene.character_ids)),
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
        f"A coherent three-panel moment shows {subjects} in {location}. "
        "Depict only the listed subjects, preserving each one's species and anatomy. "
        "Begin with the environment in clear foreground and background planes, show "
        "each subject at three-quarter or full length as something starts to happen, "
        "then finish on one subject's face, large in frame, reacting with a single "
        "readable emotion. A directional key light models that face while the setting "
        "retains clear depth and material variety."
    )
