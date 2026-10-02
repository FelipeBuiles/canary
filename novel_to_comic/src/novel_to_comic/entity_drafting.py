"""Draft an author-added entity's details from the source text.

The author names a character, place or prop that extraction missed. The model
reads only the passages that mention it, earliest first, and proposes details
in the shape extraction uses. Nothing is saved: the draft fills the add form,
and the author reviews it before adding the entity.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from pydantic import BaseModel, Field

from novel_to_comic import artifacts
from novel_to_comic.clients import text
from novel_to_comic.config import Config
from novel_to_comic.target_artifacts import ArtifactInvalid, ArtifactMissing, TargetArtifacts
from novel_to_comic.usage import estimate_text_cost
from novel_to_comic.workspace import part_workspace, series_root

PASSAGE_WINDOW = 700
PASSAGE_BUDGET = 14_000


class CharacterDraft(BaseModel):
    visual_anchor: str = Field(description=(
        "Comma-separated physical identity tags of the character's earliest typical look: anatomy, "
        "appearance, usual clothing, accessories. Evidence-grounded only; no emotion, expression, "
        "pose, action or situational state."
    ))
    age_range: str
    gender: str
    distinguishing_features: list[str] = Field(description="Permanent identity details true for the whole story.")
    default_outfit: str = Field(description="Typical clothing of the earliest look.")
    baseline_affect: str | None = Field(default=None, description="Stable low-intensity demeanor, or null.")


class LocationDraft(BaseModel):
    visual_anchor: str = Field(description=(
        "Comma-separated physical environment tags of how the place looks at its first appearance. "
        "Source-supported details only."
    ))
    time_of_day: str | None = None
    mood: str


class PropDraft(BaseModel):
    visual_anchor: str = Field(description=(
        "40-60 words describing only the object's physical appearance: material, size, color, texture, "
        "shape, condition, ending with how it is typically held or displayed."
    ))


DRAFT_MODELS: dict[str, type[BaseModel]] = {
    "characters": CharacterDraft, "locations": LocationDraft, "props": PropDraft,
}

DRAFT_SYSTEM = """You describe one entity from a novel for a comic adaptation's Story Bible.
You receive the entity's kind, its name, and source passages that mention it, in reading order.
Return JSON matching the schema. Ground every detail in the passages; when they say nothing about
a field, give a neutral, compatible value rather than inventing specifics. Describe the earliest
look in the story: later changes are appearance states the author adds separately. Physical
descriptions are what a viewer sees, never emotion, expression, pose or action."""


class NoMentions(ValueError):
    """The name does not appear in any part's source text."""


def _patterns(names: list[str]) -> re.Pattern[str]:
    alternatives = sorted({" ".join(name.split()) for name in names if name.strip()}, key=len, reverse=True)
    if not alternatives:
        raise NoMentions("Give the entity a name first.")
    return re.compile(r"(?<!\w)(?:" + "|".join(re.escape(name) for name in alternatives) + r")(?!\w)", re.IGNORECASE)


def mention_passages(root: Path, names: list[str]) -> tuple[list[str], list[str]]:
    """Source passages that mention any of ``names``, and the scenes they fall in.

    Passages run in reading order across parts and stop at a size budget, so
    the earliest appearances (where the base look is described) always fit.
    """
    root = series_root(root)
    pattern = _patterns(names)
    bible = artifacts.read_story_bible(root)
    try:
        part_ids = [part.id for part in TargetArtifacts(root).read_part_manifest().parts]
        workspaces = [(part_id, part_workspace(root, part_id)) for part_id in part_ids]
    except ArtifactMissing:
        workspaces = [(None, root)]
    passages: list[str] = []
    scene_ids: list[str] = []
    used = 0
    for part_id, workspace in workspaces:
        try:
            source = TargetArtifacts(workspace).read_source().text
        except (ArtifactMissing, ArtifactInvalid):
            continue
        scenes = sorted(
            (scene for scene in bible.scenes
             if (part_id is None or scene.part_id == part_id) and scene.source_start_offset is not None),
            key=lambda scene: scene.source_start_offset,
        )
        windows: list[list[int]] = []
        for match in pattern.finditer(source):
            current = next((s.id for s in reversed(scenes) if s.source_start_offset <= match.start()), None)
            if current and current not in scene_ids:
                scene_ids.append(current)
            start, end = max(0, match.start() - PASSAGE_WINDOW), min(len(source), match.end() + PASSAGE_WINDOW)
            if windows and start <= windows[-1][1]:
                windows[-1][1] = max(windows[-1][1], end)
            else:
                windows.append([start, end])
        for start, end in windows:
            if used >= PASSAGE_BUDGET:
                break
            passage = source[start:min(end, start + PASSAGE_BUDGET - used)].strip()
            passages.append(passage)
            used += len(passage)
    if not passages:
        raise NoMentions("The source never mentions that name; fill in the details yourself.")
    return passages, scene_ids


def _request(kind: str, name: str, passages: list[str], note: str) -> str:
    return json.dumps({
        "kind": kind.removesuffix("s"),
        "name": name,
        "author_note": note or None,
        "passages": passages,
    }, ensure_ascii=False)


def draft_cost(config: Config, kind: str, name: str, passages: list[str], note: str = "") -> float:
    return estimate_text_cost(
        config.effective_extraction_model(), DRAFT_SYSTEM + _request(kind, name, passages, note), output_chars=1500,
    )


async def draft_entity(config: Config, kind: str, name: str, passages: list[str], note: str = "") -> dict:
    """Ask the model for draft details; raises ValueError on an unusable answer."""
    model = DRAFT_MODELS[kind]
    result = await text.generate_json(
        config=config, model=config.effective_extraction_model(), system_prompt=DRAFT_SYSTEM,
        user_content=_request(kind, name, passages, note), temperature=0.2, max_output_tokens=1200,
        json_schema=model.model_json_schema(), feature="story_bible.draft_entity",
        retry_invalid_json=False, retry_transport=False,
    )
    try:
        return model.model_validate(result.value).model_dump()
    except ValueError:
        raise ValueError("The draft came back incomplete; try again or fill in the details yourself.") from None
