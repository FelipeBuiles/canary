"""What one part's extraction added to the series Story Bible.

A part's extraction only ever appends: its scenes and acts, entities it
introduced, new appearance states and activations on existing entities, and
new relationships. Recording exactly those additions lets the newest part's
text be replaced or deleted without disturbing earlier parts or the author's
later edits to entities that existed before it.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

from novel_to_comic.models.story_bible import StoryBible

EntityKind = Literal["character", "location", "prop"]
_KINDS: tuple[tuple[EntityKind, str], ...] = (
    ("character", "characters"), ("location", "locations"), ("prop", "props"),
)


class EntityRef(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    kind: EntityKind
    entity_id: str


class StateRef(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    kind: EntityKind
    entity_id: str
    state_id: str


class RelationshipRef(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    character_id: str
    target_id: str
    relationship: str


class ExtractionDelta(BaseModel):
    """The additions one part's extraction made to the series Story Bible."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    version: Literal[1] = 1
    part_id: str
    scene_ids: tuple[str, ...] = ()
    entities: tuple[EntityRef, ...] = ()
    states: tuple[StateRef, ...] = ()
    relationships: tuple[RelationshipRef, ...] = ()
    # Names a later extraction proposed that the author had removed earlier.
    suppressed_names: tuple[str, ...] = ()


def compute_delta(
    before: StoryBible | None,
    after: StoryBible,
    part_id: str,
    *,
    suppressed_names: tuple[str, ...] = (),
) -> ExtractionDelta:
    """Diff the registry an extraction started from against its result."""

    prior_scenes = {scene.id for scene in before.scenes} if before else set()
    entities: list[EntityRef] = []
    states: list[StateRef] = []
    relationships: list[RelationshipRef] = []
    for kind, field in _KINDS:
        known = {entity.id: entity for entity in getattr(before, field)} if before else {}
        for entity in getattr(after, field):
            existing = known.get(entity.id)
            if existing is None:
                entities.append(EntityRef(kind=kind, entity_id=entity.id))
                continue
            known_states = {state.id for state in existing.appearance_states}
            states.extend(
                StateRef(kind=kind, entity_id=entity.id, state_id=state.id)
                for state in entity.appearance_states if state.id not in known_states
            )
            if kind == "character":
                known_relationships = {
                    (rel.character_id, rel.relationship) for rel in existing.relationships
                }
                relationships.extend(
                    RelationshipRef(character_id=entity.id, target_id=rel.character_id,
                                    relationship=rel.relationship)
                    for rel in entity.relationships
                    if (rel.character_id, rel.relationship) not in known_relationships
                )
    return ExtractionDelta(
        part_id=part_id,
        scene_ids=tuple(scene.id for scene in after.scenes if scene.id not in prior_scenes),
        entities=tuple(entities),
        states=tuple(states),
        relationships=tuple(relationships),
        suppressed_names=suppressed_names,
    )


def remove_delta(bible: StoryBible, delta: ExtractionDelta) -> StoryBible:
    """Return ``bible`` without one part's extraction additions.

    Removing the part's scenes also removes every appearance activation and
    roster entry that pointed at them. Entities the part introduced disappear
    along with any references other entities hold to them.
    """

    result = bible.model_copy(deep=True)
    removed_scenes = set(delta.scene_ids)
    removed_entities = {(ref.kind, ref.entity_id) for ref in delta.entities}
    removed_ids = {entity_id for _, entity_id in removed_entities}
    removed_states = {(ref.kind, ref.entity_id, ref.state_id) for ref in delta.states}
    removed_relationships = {
        (ref.character_id, ref.target_id, ref.relationship) for ref in delta.relationships
    }

    result.scenes = [scene for scene in result.scenes if scene.id not in removed_scenes]
    result.sequences = [sequence for sequence in result.sequences if sequence.part_id != delta.part_id]
    for kind, field in _KINDS:
        kept = []
        for entity in getattr(result, field):
            if (kind, entity.id) in removed_entities:
                continue
            entity.appearance_states = [
                state for state in entity.appearance_states
                if (kind, entity.id, state.id) not in removed_states
            ]
            entity.appearance_timeline = [
                activation for activation in entity.appearance_timeline
                if activation.at.scene_id not in removed_scenes
                and (kind, entity.id, activation.state_id) not in removed_states
            ]
            if kind == "character":
                entity.relationships = [
                    rel for rel in entity.relationships
                    if rel.character_id not in removed_ids
                    and (entity.id, rel.character_id, rel.relationship) not in removed_relationships
                ]
            kept.append(entity)
        setattr(result, field, kept)
    for scene in result.scenes:
        scene.character_ids = [cid for cid in scene.character_ids if cid not in removed_ids]
    # An entity that outlives the part keeps a first appearance it still has.
    for character in result.characters:
        if character.first_appearance_scene in removed_scenes:
            character.first_appearance_scene = next(
                scene.id for scene in result.scenes if character.id in scene.character_ids
            )
    for prop in result.props:
        if prop.first_appearance_scene in removed_scenes:
            prop.first_appearance_scene = None
    result.total_scenes = len(result.scenes)
    return result


def removal_conflicts(bible: StoryBible, delta: ExtractionDelta) -> list[str]:
    """Names of characters added later that appear only in this part's scenes.

    Removing the part would leave them with no scene at all, so the author has
    to move or remove them first; they are never dropped silently.
    """

    removed_scenes = set(delta.scene_ids)
    introduced = {ref.entity_id for ref in delta.entities}
    conflicts = []
    for character in bible.characters:
        if character.id in introduced:
            continue
        appearances = [scene.id for scene in bible.scenes if character.id in scene.character_ids]
        if appearances and set(appearances) <= removed_scenes:
            conflicts.append(character.name)
    return conflicts
