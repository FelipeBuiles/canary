"""Author edits to the series Story Bible.

The author owns the Story Bible: extracted details are a starting point, and
characters, places and props can be edited, added, removed or merged, along
with their appearance states. Every edit carries the Bible revision it was
made against, so a stale editor never overwrites newer work.

Edits change the Story Bible only. A changed description makes that entity's
Cast references out of date (the author regenerates or keeps them); nothing is
regenerated or redrawn here. An entity or state that an adapted part already
cites cannot be removed or merged away, because adapted scripts and planned
pages name it; restarting those parts' adaptation is the way to change them.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any, Callable, Literal

from novel_to_comic import artifacts
from novel_to_comic.artifact_lock import production_lock
from novel_to_comic.extraction_sections import validate_references
from novel_to_comic.models.appearance import AppearanceState, StateActivation, StoryPosition
from novel_to_comic.models.story_bible import (
    Character,
    CharacterRelationship,
    ExcludedEntity,
    Location,
    Prop,
    StoryBible,
    blank_visual_anchors,
)
from novel_to_comic.target_artifacts import ArtifactInvalid, ArtifactMissing, TargetArtifacts
from novel_to_comic.workspace import part_workspaces, series_root

Kind = Literal["characters", "locations", "props"]
KIND_NAMES: dict[str, Literal["character", "location", "prop"]] = {
    "characters": "character", "locations": "location", "props": "prop",
}
_MODELS = {"characters": Character, "locations": Location, "props": Prop}
_ID_PREFIX = {"characters": "author_char", "locations": "author_loc", "props": "author_prop"}
EDITABLE_FIELDS: dict[str, frozenset[str]] = {
    "characters": frozenset({
        "name", "visual_anchor", "age_range", "gender", "distinguishing_features",
        "baseline_affect", "default_outfit", "relationships", "aliases", "cast_required",
    }),
    "locations": frozenset({"name", "visual_anchor", "time_of_day", "mood", "aliases"}),
    "props": frozenset({"name", "visual_anchor", "aliases"}),
}
# Details that never change what a reference image shows.
NON_VISUAL_FIELDS = frozenset({"name", "aliases", "relationships", "baseline_affect", "label", "cast_required"})
STATE_FIELDS = frozenset({
    "label", "visual_anchor", "visually_significant", "baseline_affect", "canonical_equivalent",
    "continuity_guard", "changed_facets", "replaces_identity",
})


class StaleStoryBible(ValueError):
    """The Story Bible changed since the editor loaded it."""


class EditRejected(ValueError):
    """The edit would break the Story Bible or adapted work; the message says why."""


class AnchorAlreadySet(EditRejected):
    """Only a blank visual anchor can be filled; existing anchors stay verbatim."""


class EntityCited(EditRejected):
    """Adapted parts name the entity or state, so it can't be removed or merged away."""

    def __init__(self, message: str, parts: list[str]):
        super().__init__(message)
        self.parts = parts


# ---------------------------------------------------------------------------
# What adapted parts already cite
# ---------------------------------------------------------------------------


def _adapted_part_records(root: Path):
    """Adapted parts with their script and (when planned) canonical pages."""
    try:
        manifest = TargetArtifacts(root).read_part_manifest()
        titles = {part.id: part.title for part in manifest.parts}
    except ArtifactMissing:
        titles = {}
    workspaces = part_workspaces(root) or [root]
    for workspace in workspaces:
        target = TargetArtifacts(workspace)
        try:
            adaptation = target.read_adaptation()
        except (ArtifactMissing, ArtifactInvalid):
            continue
        pages = []
        try:
            plan = target.read_plan()
            pages = [target.read_page(item.page_number) for item in plan.pages]
        except (ArtifactMissing, ArtifactInvalid):
            pass
        yield titles.get(workspace.name, workspace.name), adaptation, pages


def citation_index(root: Path) -> tuple[dict[str, list[str]], dict[tuple[str, str], list[str]]]:
    """Which adapted parts name each entity, and each (entity, state), by title."""
    entities: dict[str, list[str]] = {}
    states: dict[tuple[str, str], list[str]] = {}

    def cite(mapping: dict, key, title: str) -> None:
        titles = mapping.setdefault(key, [])
        if title not in titles:
            titles.append(title)

    for title, adaptation, pages in _adapted_part_records(series_root(root)):
        for beat in adaptation.beats:
            for entity_id in beat.entity_ids:
                cite(entities, entity_id, title)
            for item in beat.lettering:
                if item.speaker_entity_id:
                    cite(entities, item.speaker_entity_id, title)
            for change in beat.appearance_changes:
                cite(entities, change.entity_id, title)
                for state_id in (change.from_state_id, change.to_state_id):
                    if state_id:
                        cite(states, (change.entity_id, state_id), title)
        for page in pages:
            for content in page.content:
                for entity_id in content.entity_ids:
                    cite(entities, entity_id, title)
                for entity_id, state_id in content.appearance_states.items():
                    cite(states, (entity_id, state_id), title)
    return entities, states


def entity_citations(root: Path, entity_id: str) -> list[str]:
    """Titles of adapted parts whose script or pages name ``entity_id``."""
    return citation_index(root)[0].get(entity_id, [])


def state_citations(root: Path, entity_id: str, state_id: str) -> list[str]:
    """Titles of adapted parts whose script or pages use one appearance state."""
    return citation_index(root)[1].get((entity_id, state_id), [])


def refuse_if_cited(root: Path, entity_id: str, state_id: str | None = None, *, action: str) -> None:
    parts = entity_citations(root, entity_id) if state_id is None else state_citations(root, entity_id, state_id)
    if parts:
        raise EntityCited(
            f"Can't {action}: " + ", ".join(parts) + (" uses" if len(parts) == 1 else " use")
            + " it. Restart those parts' adaptation first, or edit it instead.",
            parts,
        )


def editable_scene_ids(root: Path, bible: StoryBible) -> set[str]:
    """Scenes in parts whose Adapt hasn't started: rosters there can change."""
    from novel_to_comic.state import StageStatus, load_state

    root = series_root(root)
    locked: set[str] = set()
    for workspace in part_workspaces(root):
        state = load_state(workspace)
        if (state.stages["adapt"].status != StageStatus.PENDING
                or TargetArtifacts(workspace).adaptation_path.exists()):
            locked.add(workspace.name)
    if not part_workspaces(root) and TargetArtifacts(root).adaptation_path.exists():
        return set()
    return {scene.id for scene in bible.scenes if scene.part_id not in locked}


def pages_drawn_before_edits(workspace: Path) -> list[dict]:
    """A part's drawn pages whose artwork predates an edit to something on them.

    Each page's producing request froze the descriptions, continuity guards and
    reference images it was drawn with; a page is flagged when the current
    Story Bible or Cast reference differs. Advisory only: pages are never
    redrawn automatically.
    """
    from novel_to_comic.stages.s5_plan import approved_reference_files, approved_visual_inventory

    target = TargetArtifacts(workspace)
    try:
        plan = target.read_plan()
        root = series_root(workspace)
        inventory = {ref.id: ref for ref in approved_visual_inventory(root).references}
        files = approved_reference_files(root)
    except (ArtifactMissing, ArtifactInvalid, ValueError):
        return []
    digests: dict[str, str | None] = {}

    def current_digest(reference_id: str) -> str | None:
        if reference_id not in digests:
            source = files.get(reference_id)
            try:
                digests[reference_id] = hashlib.sha256(source.path.read_bytes()).hexdigest() if source else None
            except OSError:
                digests[reference_id] = None
        return digests[reference_id]

    flagged = []
    for item in plan.pages:
        try:
            revision = target.active_render_revision(item.page_number)
            if revision is None:
                continue
            request = target.producing_request(target.read_provenance(item.page_number, revision).render)
        except (ArtifactMissing, ArtifactInvalid, ValueError):
            continue
        changes = []
        for frozen in (*request.references, *request.written_identities):
            if frozen.entity_id is None:
                continue
            current = inventory.get(frozen.id)
            if current is None:
                reasons = ["removed"]
            else:
                reasons = [reason for reason, changed in (
                    ("description", current.visual_anchor != frozen.visual_anchor),
                    ("continuity", (current.continuity_guard or "") != frozen.continuity_guard),
                    ("reference image", current_digest(frozen.id) not in {None, getattr(frozen, "content_sha256", None)}),
                ) if changed]
            if reasons:
                changes.append({
                    "entity_id": frozen.entity_id, "appearance_state_id": frozen.appearance_state_id,
                    "label": current.label if current is not None else frozen.label, "reasons": reasons,
                })
        if changes:
            flagged.append({"page_number": item.page_number, "render_revision": revision, "changes": changes})
    return flagged


# ---------------------------------------------------------------------------
# Pure edits
# ---------------------------------------------------------------------------


def _entities(bible: StoryBible, kind: str) -> list:
    if kind not in _MODELS:
        raise EditRejected(f"Unknown entity kind: {kind}")
    return getattr(bible, kind)


def _find(bible: StoryBible, kind: str, entity_id: str):
    entity = next((item for item in _entities(bible, kind) if item.id == entity_id), None)
    if entity is None:
        raise KeyError(entity_id)
    return entity


def _clean_names(values: list[str] | None, *, exclude: str = "") -> list[str]:
    seen: set[str] = set()
    result = []
    for value in values or []:
        name = " ".join(str(value).split())[:200]
        key = name.casefold()
        if name and key != exclude.casefold() and key not in seen:
            seen.add(key)
            result.append(name)
    return result


def _scene_order(bible: StoryBible) -> dict[str, int]:
    return {scene.id: index for index, scene in enumerate(bible.scenes)}


def edit_entity(bible: StoryBible, kind: str, entity_id: str, changes: dict[str, Any]) -> StoryBible:
    unknown = set(changes) - EDITABLE_FIELDS.get(kind, frozenset())
    if unknown:
        raise EditRejected("These details can't be edited here: " + ", ".join(sorted(unknown)))
    result = bible.model_copy(deep=True)
    entity = _find(result, kind, entity_id)
    payload = entity.model_dump()
    payload.update(changes)
    if not str(payload.get("name", "")).strip() or not str(payload.get("visual_anchor", "")).strip():
        raise EditRejected("A name and a physical description are required.")
    payload["name"] = " ".join(str(payload["name"]).split())
    payload["aliases"] = _clean_names(payload.get("aliases"), exclude=payload["name"])
    if kind == "characters" and "relationships" in changes:
        known = {c.id for c in result.characters}
        payload["relationships"] = [
            CharacterRelationship.model_validate(rel).model_dump() for rel in changes["relationships"]
        ]
        if any(rel["character_id"] not in known or rel["character_id"] == entity_id
               for rel in payload["relationships"]):
            raise EditRejected("Relationships must name another character in the Story Bible.")
    updated = _MODELS[kind].model_validate(payload)
    entities = _entities(result, kind)
    entities[entities.index(entity)] = updated
    return result


def _next_id(bible: StoryBible, kind: str) -> str:
    taken = {item.id for k in _MODELS for item in getattr(bible, k)}
    number = 1
    while f"{_ID_PREFIX[kind]}_{number:03d}" in taken:
        number += 1
    return f"{_ID_PREFIX[kind]}_{number:03d}"


def add_entity(
    bible: StoryBible, kind: str, details: dict[str, Any], scene_ids: list[str], editable: set[str],
) -> tuple[StoryBible, str]:
    """Add an author-created entity and place it in the chosen scenes."""
    result = bible.model_copy(deep=True)
    unknown = set(details) - EDITABLE_FIELDS.get(kind, frozenset())
    if unknown:
        raise EditRejected("These details can't be set here: " + ", ".join(sorted(unknown)))
    order = _scene_order(result)
    chosen = sorted(dict.fromkeys(scene_ids), key=lambda sid: order.get(sid, len(order)))
    if any(sid not in order for sid in chosen):
        raise EditRejected("Choose scenes from the Story Bible.")
    if any(sid not in editable for sid in chosen):
        raise EditRejected("Scenes in parts that are already adapted can't change.")
    if kind == "characters" and not chosen:
        raise EditRejected("Choose at least one scene the character appears in.")
    entity_id = _next_id(result, kind)
    payload = {"id": entity_id, "origin": "author", **details}
    payload["name"] = " ".join(str(payload.get("name", "")).split())
    if not payload["name"] or not str(payload.get("visual_anchor", "")).strip():
        raise EditRejected("A name and a physical description are required.")
    payload["aliases"] = _clean_names(payload.get("aliases"), exclude=payload["name"])
    if kind == "characters":
        payload.setdefault("age_range", "")
        payload.setdefault("gender", "")
        payload.setdefault("default_outfit", "")
        payload.setdefault("distinguishing_features", [])
        payload["first_appearance_scene"] = chosen[0]
    elif kind == "locations":
        payload.setdefault("mood", "")
    elif kind == "props" and chosen:
        payload["first_appearance_scene"] = chosen[0]
    entity = _MODELS[kind].model_validate(payload)
    _entities(result, kind).append(entity)
    for scene in result.scenes:
        if scene.id not in chosen:
            continue
        if kind == "characters" and entity_id not in scene.character_ids:
            scene.character_ids.append(entity_id)
        elif kind == "locations":
            scene.location_id = entity_id
    # Re-adding a name the author removed earlier lifts that removal.
    names = {payload["name"].casefold(), *(alias.casefold() for alias in entity.aliases)}
    result.excluded_entities = [
        entry for entry in result.excluded_entities
        if not (entry.kind == KIND_NAMES[kind]
                and names & {entry.name.casefold(), *(alias.casefold() for alias in entry.aliases)})
    ]
    return result, entity_id


def remove_entity(bible: StoryBible, kind: str, entity_id: str) -> StoryBible:
    """Remove an uncited entity and keep later extractions from recreating it."""
    result = bible.model_copy(deep=True)
    entity = _find(result, kind, entity_id)
    if kind == "locations" and any(scene.location_id == entity_id for scene in result.scenes):
        raise EditRejected(f"Scenes take place at {entity.name}. Merge it into another place instead.")
    _entities(result, kind).remove(entity)
    if kind == "characters":
        for scene in result.scenes:
            scene.character_ids = [cid for cid in scene.character_ids if cid != entity_id]
        for character in result.characters:
            character.relationships = [r for r in character.relationships if r.character_id != entity_id]
    result.excluded_entities.append(
        ExcludedEntity(kind=KIND_NAMES[kind], name=entity.name, aliases=list(entity.aliases))
    )
    return result


def _merge_states(target, source, order: dict[str, int]) -> None:
    """Carry the absorbed entity's distinct states and their activations over."""
    existing = {state.id for state in target.appearance_states}
    renamed: dict[str, str] = {}
    for state in source.appearance_states:
        new_id = state.id
        suffix = 2
        while new_id in existing:
            new_id = f"{state.id}_{suffix}"
            suffix += 1
        renamed[state.id] = new_id
        existing.add(new_id)
        target.appearance_states.append(state.model_copy(update={"id": new_id}))
    positions = {(a.at.scene_id, a.at.beat) for a in target.appearance_timeline}
    for activation in source.appearance_timeline:
        if (activation.at.scene_id, activation.at.beat) in positions:
            continue
        target.appearance_timeline.append(activation.model_copy(update={"state_id": renamed[activation.state_id]}))
    target.appearance_timeline.sort(key=lambda a: (order.get(a.at.scene_id, len(order)), a.at.beat or 0))


def merge_entities(bible: StoryBible, kind: str, source_id: str, target_id: str) -> StoryBible:
    """Fold ``source_id`` into ``target_id``; the absorbed name becomes an alias."""
    if source_id == target_id:
        raise EditRejected("Choose two different entries to merge.")
    result = bible.model_copy(deep=True)
    source = _find(result, kind, source_id)
    target = _find(result, kind, target_id)
    order = _scene_order(result)
    target.aliases = _clean_names([*target.aliases, source.name, *source.aliases], exclude=target.name)
    _merge_states(target, source, order)
    if kind == "characters":
        for scene in result.scenes:
            scene.character_ids = list(dict.fromkeys(
                target_id if cid == source_id else cid for cid in scene.character_ids
            ))
        relationships = [*target.relationships, *source.relationships]
        target.relationships = []
        for rel in relationships:
            if rel.character_id in {source_id, target_id}:
                continue
            if all(existing != rel for existing in target.relationships):
                target.relationships.append(rel)
        for character in result.characters:
            if character.id == target_id:
                continue
            remapped = []
            for rel in character.relationships:
                rel = rel.model_copy(update={"character_id": target_id}) if rel.character_id == source_id else rel
                if rel not in remapped:
                    remapped.append(rel)
            character.relationships = remapped
        firsts = [target.first_appearance_scene, source.first_appearance_scene]
        target.first_appearance_scene = min(firsts, key=lambda sid: order.get(sid, len(order)))
    elif kind == "locations":
        for scene in result.scenes:
            if scene.location_id == source_id:
                scene.location_id = target_id
    else:
        firsts = [sid for sid in (target.first_appearance_scene, source.first_appearance_scene) if sid]
        target.first_appearance_scene = min(firsts, key=lambda sid: order.get(sid, len(order))) if firsts else None
    _entities(result, kind).remove(source)
    return result


def add_state(bible: StoryBible, kind: str, entity_id: str, details: dict[str, Any],
              starts_at_scene: str | None) -> tuple[StoryBible, str]:
    result = bible.model_copy(deep=True)
    entity = _find(result, kind, entity_id)
    unknown = set(details) - STATE_FIELDS
    if unknown:
        raise EditRejected("These state details can't be set here: " + ", ".join(sorted(unknown)))
    if not str(details.get("label", "")).strip() or not str(details.get("visual_anchor", "")).strip():
        raise EditRejected("A look needs a label and a physical description.")
    taken = {state.id for state in entity.appearance_states}
    base = re.sub(r"[^a-z0-9]+", "_", str(details["label"]).casefold()).strip("_")[:40] or "look"
    state_id, suffix = base, 2
    while state_id in taken:
        state_id, suffix = f"{base}_{suffix}", suffix + 1
    # A look exists because it looks different, so it gets its own reference.
    state = AppearanceState.model_validate({"visually_significant": True, **details, "id": state_id})
    entity.appearance_states.append(state)
    if starts_at_scene:
        order = _scene_order(result)
        if starts_at_scene not in order:
            raise EditRejected("Choose the scene where this look begins.")
        if any(a.at.scene_id == starts_at_scene and a.at.beat is None for a in entity.appearance_timeline):
            raise EditRejected("Another look already begins at that scene.")
        entity.appearance_timeline.append(StateActivation(state_id=state_id, at=StoryPosition(scene_id=starts_at_scene)))
        entity.appearance_timeline.sort(key=lambda a: (order.get(a.at.scene_id, len(order)), a.at.beat or 0))
    return result, state_id


def edit_state(bible: StoryBible, kind: str, entity_id: str, state_id: str, changes: dict[str, Any]) -> StoryBible:
    unknown = set(changes) - STATE_FIELDS
    if unknown:
        raise EditRejected("These state details can't be edited here: " + ", ".join(sorted(unknown)))
    result = bible.model_copy(deep=True)
    entity = _find(result, kind, entity_id)
    state = next((item for item in entity.appearance_states if item.id == state_id), None)
    if state is None:
        raise KeyError(state_id)
    updated = AppearanceState.model_validate({**state.model_dump(), **changes, "id": state_id})
    entity.appearance_states[entity.appearance_states.index(state)] = updated
    return result


def remove_state(bible: StoryBible, kind: str, entity_id: str, state_id: str) -> StoryBible:
    result = bible.model_copy(deep=True)
    entity = _find(result, kind, entity_id)
    if not any(item.id == state_id for item in entity.appearance_states):
        raise KeyError(state_id)
    entity.appearance_states = [item for item in entity.appearance_states if item.id != state_id]
    entity.appearance_timeline = [a for a in entity.appearance_timeline if a.state_id != state_id]
    return result


def restore_excluded(bible: StoryBible, kind: str, name: str) -> StoryBible:
    result = bible.model_copy(deep=True)
    before = len(result.excluded_entities)
    result.excluded_entities = [
        entry for entry in result.excluded_entities
        if not (entry.kind == KIND_NAMES.get(kind) and entry.name.casefold() == name.casefold())
    ]
    if len(result.excluded_entities) == before:
        raise KeyError(name)
    return result


# ---------------------------------------------------------------------------
# Persisted edits
# ---------------------------------------------------------------------------


def apply_edit(root: Path, expected_revision: int,
               edit: Callable[[StoryBible], StoryBible | tuple[StoryBible, Any]],
               *, on_saved: Callable[[StoryBible, StoryBible], None] | None = None):
    """Apply one revision-checked edit under the series lock.

    Returns the saved Story Bible and whatever extra value ``edit`` produced.
    New entities or states reopen Cast so they get references before use.
    ``on_saved`` runs under the same lock with the Bible before and after.
    """
    from novel_to_comic.series import reopen_cast_for_new_inventory, cast_inventory_keys

    root = series_root(root)
    with production_lock(root):
        bible = artifacts.read_story_bible(root)
        if bible.revision != expected_revision:
            raise StaleStoryBible(
                f"The Story Bible changed (revision {bible.revision}); reload it and edit again."
            )
        before = cast_inventory_keys(root)
        outcome = edit(bible)
        updated, extra = outcome if isinstance(outcome, tuple) else (outcome, None)
        updated.total_scenes = len(updated.scenes)
        try:
            validate_references(updated)
        except ValueError as exc:
            raise EditRejected(str(exc)) from exc
        # Plan needs a written look for every entry, so no edit may blank one.
        if introduced := sorted(set(blank_visual_anchors(updated)) - set(blank_visual_anchors(bible))):
            raise EditRejected("Add a visual anchor for: " + ", ".join(introduced))
        updated.revision = bible.revision + 1
        artifacts.write_story_bible(root, updated)
        if on_saved is not None:
            on_saved(bible, updated)
        reopen_cast_for_new_inventory(root, before)
    return updated, extra


def fill_blank_anchor(root: Path, entity_id: str, state_id: str | None, anchor: str) -> StoryBible:
    """Give a blank visual anchor its first description, under the series lock.

    The blank itself is the precondition, so no editor revision is needed; the
    revision still advances so an open editor reloads before its next save.
    Only that text changes: no reference, Cast inventory or stage moves.
    """
    anchor = anchor.strip()
    if not anchor:
        raise EditRejected("Describe how this entry looks.")
    root = series_root(root)
    with production_lock(root):
        bible = artifacts.read_story_bible(root)
        entity = next((item for kind in _MODELS for item in getattr(bible, kind) if item.id == entity_id), None)
        if entity is None:
            raise KeyError(entity_id)
        target = entity
        if state_id is not None:
            target = next((state for state in entity.appearance_states if state.id == state_id), None)
            if target is None:
                raise KeyError(f"{entity_id}:{state_id}")
        if target.visual_anchor.strip():
            raise AnchorAlreadySet(
                "This entry already has a visual anchor; existing anchors are preserved verbatim."
            )
        target.visual_anchor = anchor
        bible.revision += 1
        artifacts.write_story_bible(root, bible)
    return bible
