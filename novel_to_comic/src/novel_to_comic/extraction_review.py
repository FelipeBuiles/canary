"""Source-backed corrections inside Extract, before publishing its authorities.

The section reader can miss a boss, discover a physical fact late, or forget a
still-worn item in a later look. The existing final organization call reviews
the source as well as the scene summaries. It returns small, typed additions,
not a rewritten Bible. No saved book or earlier part is edited here.
"""

from __future__ import annotations

import hashlib
import json
import re

from pydantic import BaseModel, ConfigDict, Field

from novel_to_comic.models.appearance import AppearanceState, StateActivation, StoryPosition, Transition
from novel_to_comic.models.story_bible import Character, Location, Prop, StoryBible, blank_visual_anchors
from novel_to_comic.source_extraction import SourceSceneAnchor, align_scene_openings, build_source_document
from novel_to_comic.text_utils import clean


class SourceEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scene_id: str
    source_quote: str = Field(min_length=1, description=(
        "Verbatim source words that begin in this scene's passage; one short sentence is best."))


class CharacterAddition(Character):
    model_config = ConfigDict(extra="forbid")
    evidence: list[SourceEvidence] = Field(min_length=1, description=(
        "Depicted embodied action, including narrated recollection or footage; not a named mention."))


class PropAddition(Prop):
    model_config = ConfigDict(extra="forbid")
    evidence: list[SourceEvidence] = Field(min_length=1)


class LocationAddition(Location):
    model_config = ConfigDict(extra="forbid")
    evidence: list[SourceEvidence] = Field(min_length=1, description="Where the action is staged in this place.")


class CharacterDetails(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    distinguishing_features: list[str] = []
    aliases: list[str] = []
    cast_required: bool = False
    appearance_states: list[AppearanceState] = []
    appearance_timeline: list[StateActivation] = []
    evidence: list[SourceEvidence] = Field(min_length=1)


class CreatureGroup(BaseModel):
    model_config = ConfigDict(extra="forbid")
    character: CharacterAddition
    member_ids: list[str] = Field(min_length=1, description=(
        "Characters marked interchangeable or group, introduced in this part, with identical physical "
        "identity and no individual appearance states. Never merge named companions."))


class SceneDetails(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    character_ids: list[str] = Field(default_factory=list, description="Missing staged participants to ADD.")
    remove_transient_object_ids: list[str] = Field(default_factory=list, description=(
        "Living actors incorrectly stored as objects, now covered by the Character roster. "
        "Keep corpses, pelts and substances as objects."))
    non_narrative: bool = False
    location_id: str | None = Field(default=None, description=(
        "Corrected setting when the scene's action is staged somewhere other than its location; "
        "null keeps the current setting."))
    evidence: list[SourceEvidence] = Field(min_length=1)


class PartEndLook(BaseModel):
    model_config = ConfigDict(extra="forbid")
    character_id: str
    state_id: str | None = Field(description=(
        "The character's body look at this part's last scene: an existing or newly added "
        "appearance state ID, or null for the character's own base look."))
    since: StoryPosition | None = Field(default=None, description=(
        "Where that look begins in this part, when it differs from latest_state_id; "
        "null when the latest look still holds at the end."))
    evidence: list[SourceEvidence] = Field(min_length=1, description="Source words showing that look at the end.")


class AccessoryAbsence(BaseModel):
    model_config = ConfigDict(extra="forbid")
    at: StoryPosition
    until: StoryPosition
    evidence: list[SourceEvidence] = Field(min_length=1)


class PersistentAccessory(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(description="Unique accessory interval ID, not a Character or state ID.")
    character_id: str
    label: str
    visual_anchor: str = Field(min_length=1, description=(
        "Only this item's visible physical tags, comma-separated; never touch, temperature, smell "
        "or magical effect. For a lost item, what shows instead (\"bare feet\")."))
    removes_tags: list[str] = Field(default_factory=list, description=(
        "Exact comma-separated tags of the character's current look that this change takes away, "
        "such as lost, removed or replaced clothing. Empty when the item only adds."))
    at: StoryPosition
    until: StoryPosition | None = Field(default=None, description=(
        "Explicit removal position, or null when still worn. Do not assume removal at a section boundary."))
    visually_significant: bool = Field(default=True, description=(
        "True when the item is prominent in a full-figure drawing or changes the silhouette: "
        "a cloak, coat, armor, crown, helmet, shirt worn outside. False for small or covered "
        "items such as a ring, a toe ring or an undershirt."))
    evidence: list[SourceEvidence] = Field(min_length=1)
    absent_intervals: list[AccessoryAbsence] = Field(default_factory=list, description=(
        "Source-supported intervals where the item is not visible, such as a framed sequence "
        "before acquisition or a covering garment. Never infer absence from a bare-base return alone."))


class ExtractionReview(BaseModel):
    model_config = ConfigDict(extra="forbid")
    characters: list[CharacterAddition] = []
    character_details: list[CharacterDetails] = []
    creature_groups: list[CreatureGroup] = []
    props: list[PropAddition] = []
    locations: list[LocationAddition] = []
    scene_details: list[SceneDetails] = []
    persistent_accessories: list[PersistentAccessory] = []
    part_end_looks: list[PartEndLook] = []


SOURCE_REVIEW_INSTRUCTIONS = """
Review the source against the extraction before finalizing it. source_review is
a selective correction list; use empty arrays where the extraction is already
complete. Do not return the entire registry or manufacture detail to fill fields.
Read the actual source, not just summaries. Check acting/fought creatures and
principal bosses, named equipped companions in depicted footage, stated physical
identity (a first-person narrator often states height or build in passing),
persistent worn items and body marks, clothing that is lost or taken off,
temporary transformations and where they end, group members with their own role
or distinctive gear, each scene's actual setting, interchangeable creature
copies, and non-story author notes or recommendations. Recurrence is not a
requirement for an important antagonist or visual companion. Ordinary incidental
people need no ongoing arc.

characters adds missing staged identities, using review_id_prefix for new IDs.
Use identity_kind='group' for an interchangeable collective creature design;
retain counts and distinct actions in scene summaries. Named animals and creatures
with different looks or persistent individual states remain separate Characters,
as does a group member with its own stated role or class and distinctive gear
(the engineer who drives, the one in a helmet): add it and put it on the rosters.
character_details adds stated stable physical facts or genuinely missing looks
and activations to an exact existing ID; never rewrite anchors or guards. Do not
invent height, hair, face or build where the author supplies none. Species anatomy
does not license copying another individual's personal face or outfit.
Add newly revealed proper names as aliases of the established identity; a later
name is not a new person. Generic occupations are not shared personal aliases.
creature_groups replaces only physically identical entries already marked
interchangeable or group from this part with one shared group design. Preserve
individual identities, including named animals, even when their descriptions match.
props adds missing plot-critical detachable items with source-supported forms.
A brand, tattoo or scar is part of the body: record it as a persistent accessory
(or a look), never as a prop. locations adds a missing place where action is
staged; scene_details.location_id moves a scene whose action happens elsewhere
(a fight outside a door, a chase that has left the alley).
scene_details adds missing roster IDs and removes only live-creature objects now
represented by those Characters. Mark non_narrative only for source matter with
no staged story action; never stage a promotional recommendation or author's note.

persistent_accessories records a missed equipped crown, jewelry or worn item from
its actual acquisition through explicit removal (until=null if not removed).
Code composes it with every later body/wardrobe look, including minor states and
returns to the base; do not retype the character's whole state catalog for this.
For a carried registry item omitted from a newly emitted look, start at that
look and use visually_significant=false when its existing reference remains
valid. Use absent_intervals for source-supported earlier-lived-time frames or
concealment, so a later worn item never leaks into an earlier depicted life.
Lost, removed or replaced clothing is an interval too: list the exact tags it
takes away in removes_tags and what shows instead in visual_anchor ("bare feet"),
from the moment it is lost until it is restored (until=null if never).
Add a detachable prop too when its independent identity matters. Existing complete
equipped states need no redundant accessory interval. Every correction has short
verbatim evidence from the relevant supplied scene passage. Evidence for a new
Character must describe staged action, not a photograph, biography or off-screen
mention. All correction positions and evidence belong to this source part.

part_end_looks is required for every character whose look changes in this part
or who carries a changed look into it (end_look_required lists them when
supplied): give the body look they are in at this part's last scene (null for their own base look),
where that look begins, and evidence. A transformation that has ended by the
last scene ends there; report the return. Worn items are tracked separately.
"""


def constrain_review_schema(schema: dict, *, bible: StoryBible | None = None,
                            scene_ids: list[str] | None = None, prefix: str = "audit_") -> None:
    """Bound generated references to real registries and local scenes on the first call."""
    definitions = schema["$defs"]
    new_id = {"type": "string", "pattern": f"^{re.escape(prefix)}[A-Za-z0-9_-]+$"}

    eligible = [c.id for c in bible.characters if c.first_appearance_scene in (scene_ids or [])
                and c.origin == "extracted" and c.identity_kind in {"interchangeable", "group"}] if bible else []
    total_ids = ((len(bible.characters) + len(bible.locations) if bible else 0)
                 + len(scene_ids or []) + len(eligible))

    def ids(values, name):
        if not values:
            return {"type": "string"}
        constraint = ({"pattern": "^(?:" + "|".join(re.escape(v) for v in values) + ")$"}
                      if total_ids > 900 or sum(map(len, values)) > 15000 else {"enum": values})
        definitions[name] = {"type": "string", **constraint}
        return {"$ref": f"#/$defs/{name}"}

    characters = ids([c.id for c in bible.characters], "ReviewCharacterId") if bible is not None else {"type": "string"}
    local_scenes = ids(scene_ids, "ReviewSceneId")
    definitions["LocationAddition"]["properties"]["id"] = dict(new_id)
    definitions["LocationAddition"]["properties"].pop("origin", None)
    definitions["LocationAddition"]["required"] = [
        f for f in definitions["LocationAddition"].get("required", []) if f != "origin"]
    places = ids([location.id for location in bible.locations], "ReviewLocationId") if bible is not None else {"type": "string"}
    definitions["SceneDetails"]["properties"]["location_id"] = {
        "anyOf": [places, dict(new_id), {"type": "null"}], "default": None,
        "description": definitions["SceneDetails"]["properties"]["location_id"].get("description", "")}
    for name in ("CharacterAddition", "PropAddition"):
        definitions[name]["properties"]["id"] = dict(new_id)
        definitions[name]["properties"].pop("origin", None)
        definitions[name]["required"] = [f for f in definitions[name].get("required", []) if f != "origin"]
        first = dict(local_scenes)
        definitions[name]["properties"]["first_appearance_scene"] = (
            {"anyOf": [first, {"type": "null"}]} if name == "PropAddition" else first)
    definitions["CharacterDetails"]["properties"]["id"] = characters
    if bible is not None:
        # Keep explicitly required individuals (notably named companions)
        # outside the model's merge choices on the first response.
        definitions["CreatureGroup"]["properties"]["member_ids"]["items"] = ids(eligible, "ReviewGroupMemberId")
        if not eligible:
            definitions["ExtractionReview"]["properties"]["creature_groups"]["maxItems"] = 0
    reference = {"anyOf": [characters, dict(new_id)]}
    definitions["SceneDetails"]["properties"]["id"] = dict(local_scenes)
    definitions["SceneDetails"]["properties"]["character_ids"]["items"] = reference
    definitions["SourceEvidence"]["properties"]["scene_id"] = dict(local_scenes)
    definitions["PersistentAccessory"]["properties"]["character_id"] = reference
    definitions["CharacterRelationship"]["properties"]["character_id"] = reference
    definitions["PartEndLook"]["properties"]["character_id"] = reference
    # StoryPosition is shared by newly authored state and equipment intervals.
    definitions["StoryPosition"]["properties"]["scene_id"] = dict(local_scenes)
    if "StorySequence" in definitions and scene_ids:
        definitions["StorySequence"]["properties"]["scenes"]["items"] = dict(local_scenes)


WORN_PREFIX = "worn_"


def end_look_candidates(bible: StoryBible, part_id: str) -> list[dict]:
    """Characters whose look changes in this part, or who carry a changed look into it.

    Their look at the part's end is a required review answer: an open-ended
    "check for missed looks" left transformations running into the next part.
    """
    order = {scene.id: index for index, scene in enumerate(bible.scenes)}
    local = [scene for scene in bible.scenes if scene.part_id == part_id]
    if not local:
        return []
    local_ids = {scene.id for scene in local}
    rostered = {cid for scene in local for cid in scene.character_ids}
    end = order[local[-1].id]
    candidates = []
    for character in bible.characters:
        states = {state.id: state for state in character.appearance_states}
        # Composed worn-item looks are outfit, tracked by their own intervals.
        timeline = [a for a in character.appearance_timeline if order.get(a.at.scene_id, end + 1) <= end
                    and not a.state_id.startswith(WORN_PREFIX)]
        latest = max(timeline, key=lambda a: (order[a.at.scene_id], a.at.beat or 0), default=None)
        changed_here = any(a.at.scene_id in local_ids for a in timeline)
        carried = (latest is not None and character.id in rostered
                   and not states[latest.state_id].canonical_equivalent)
        if changed_here or carried:
            candidates.append({
                "character_id": character.id, "name": character.name,
                "latest_state_id": latest.state_id if latest else None,
                "latest_state_label": states[latest.state_id].label if latest else None,
                "latest_since": latest.at.model_dump(mode="json") if latest else None,
            })
    return candidates


def apply_source_review(bible: StoryBible, review: ExtractionReview, text: str, *,
                        part_id: str, protected_character_ids: frozenset[str] = frozenset(),
                        new_id_prefix: str = "audit_",
                        protected_state_keys: frozenset[tuple[str, str]] | None = None,
                        require_end_looks: bool = False) -> StoryBible:
    """Apply a grounded review to an in-memory extraction, preserving prior parts.

    ``require_end_looks`` is set where the review is the part's final pass; a
    section parse has no review and its part has not ended.
    """
    from novel_to_comic.extraction_sections import validate_references
    from novel_to_comic.stages.s1_extract import _check_character_looks, _unresolved_openings

    result = bible.model_copy(deep=True)
    review = review.model_copy(deep=True)
    if not any(review.model_dump().values()) and not (require_end_looks and end_look_candidates(result, part_id)):
        excluded = {scene.id for scene in result.scenes if scene.scene_type == "non_narrative"}
        for sequence in result.sequences:
            sequence.scenes = [sid for sid in sequence.scenes if sid not in excluded]
        return result
    local = [scene for scene in result.scenes if scene.part_id == part_id]
    if unresolved := align_scene_openings(local, text):
        # The typed error carries the exact source sentence to the repair prompt;
        # a bare ValueError gives the model nothing to correct.
        by_id = {scene.id: scene.source_start_quote for scene in local}
        raise _unresolved_openings({scene_id: by_id[scene_id] for scene_id in unresolved}, text)
    scenes = {scene.id: scene for scene in local}
    source = build_source_document(text, [SourceSceneAnchor(id=scene.id, title=scene.title,
        opening_quote=scene.source_start_quote, start_offset=scene.source_start_offset) for scene in local])
    units = {unit.id: unit for unit in source.units}
    spans = {scene.id: (units[scene.first_unit_id].start_offset, units[scene.last_unit_id].end_offset)
             for scene in source.scenes}
    order = {scene.id: index for index, scene in enumerate(result.scenes)}

    def begins_in(scene_id: str, quote: str) -> bool:
        # A quote may run past the scene's last sentence; it must begin inside it.
        start, end = spans[scene_id]
        passage = clean(text[start:end])
        position = clean(text[start:end + len(quote) + 200]).find(quote)
        return 0 <= position < len(passage)

    def evidence(entries):
        for entry in entries:
            quote = clean(entry.source_quote)
            if entry.scene_id in spans and quote and begins_in(entry.scene_id, quote):
                continue
            if entry.scene_id not in spans:
                raise ValueError(f"Source review evidence must name a scene from this part: {entry.scene_id}.")
            start, end = spans[entry.scene_id]
            sentences = [unit for unit in source.units if start <= unit.start_offset < end]
            owners = [scene_id for scene_id in spans if quote and begins_in(scene_id, quote)]
            where = (f"Those words are in scene {owners[0]}; cite that scene or quote words from {entry.scene_id}. "
                     if owners else "Those words are not verbatim source text. ")
            raise ValueError(
                f"Source review evidence for scene {entry.scene_id} must quote that scene. {where}"
                f"Scene {entry.scene_id} runs from {json.dumps(clean(sentences[0].text), ensure_ascii=False)} "
                f"to {json.dumps(clean(sentences[-1].text), ensure_ascii=False)}.")

    def add(entity, kind):
        evidence(entity.evidence)
        if not re.fullmatch(re.escape(new_id_prefix) + r"[A-Za-z0-9_-]+", entity.id):
            raise ValueError(f"Source review new IDs must use prefix {new_id_prefix}: {entity.id}")
        entries = getattr(result, kind)
        if entity.id in {item.id for item in entries}:
            raise ValueError(f"Source review additions must have a new ID: {entity.id}")
        first = getattr(entity, "first_appearance_scene", None)
        if first is not None and first not in scenes:
            raise ValueError(f"First appearance must belong to this source part: {entity.id}")
        model = {"characters": Character, "props": Prop, "locations": Location}[kind]
        entries.append(model.model_validate(entity.model_dump(exclude={"evidence", "origin"})))
        if kind == "characters":
            for entry in entity.evidence:
                if scenes[entry.scene_id].scene_type == "non_narrative":
                    raise ValueError("A missing actor needs staged narrative evidence.")
                scenes[entry.scene_id].character_ids.append(entity.id)

    for character in review.characters:
        add(character, "characters")
    for prop in review.props:
        add(prop, "props")
    for location in review.locations:
        add(location, "locations")
    characters = {character.id: character for character in result.characters}
    for details in review.character_details:
        evidence(details.evidence)
        if details.id not in characters:
            raise ValueError(f"Source review must use a defined Character ID: {details.id}")
        target = characters[details.id]
        target.distinguishing_features = list(dict.fromkeys([*target.distinguishing_features,
                                                           *details.distinguishing_features]))
        target.aliases = list(dict.fromkeys([*target.aliases, *details.aliases]))
        target.cast_required |= details.cast_required
        known = {state.id: state for state in target.appearance_states}
        for state in details.appearance_states:
            if state.id in known and state != known[state.id]:
                raise ValueError(f"Preserve state definition verbatim: {target.id}/{state.id}")
            if state.id not in known:
                target.appearance_states.append(state.model_copy(deep=True))
                known[state.id] = state
        if any(activation.at.scene_id not in scenes or (activation.at.beat is not None and activation.at.beat < 1)
               for activation in details.appearance_timeline):
            raise ValueError("Source review activations must belong to this source part.")
        target.appearance_timeline.extend(details.appearance_timeline)
        target.appearance_timeline.sort(key=lambda a: (order[a.at.scene_id], a.at.beat or 0))

    remapped = {}
    for group in review.creature_groups:
        members = [characters.get(identifier) for identifier in group.member_ids]
        if (group.character.identity_kind != "group" or any(member is None for member in members)
                or any(identifier in protected_character_ids or identifier in remapped for identifier in group.member_ids)
                or any(member.origin != "extracted" or member.first_appearance_scene not in scenes
                       or member.identity_kind not in {"interchangeable", "group"}
                       for member in members)):
            raise ValueError("Creature groups may replace only interchangeable Characters introduced in this part.")
        signatures = {(member.visual_anchor, tuple(member.distinguishing_features), member.default_outfit,
                       member.age_range, member.gender) for member in members}
        if len(signatures) != 1 or any(member.appearance_states or member.appearance_timeline for member in members):
            raise ValueError("Preserve creature variants with distinct physical identities or individual states.")
        add(group.character, "characters")
        target = result.characters[-1]
        target.first_appearance_scene = min([target.first_appearance_scene,
                                             *(m.first_appearance_scene for m in members)], key=order.__getitem__)
        target.cast_required |= any(member.cast_required for member in members)
        target.aliases = list(dict.fromkeys([*target.aliases, *(m.name for m in members),
                                           *(alias for member in members for alias in member.aliases)]))
        target.relationships.extend(relation.model_copy(deep=True) for member in members for relation in member.relationships)
        remapped.update({identifier: target.id for identifier in group.member_ids})
        characters[target.id] = target
    if remapped:
        result.characters = [c for c in result.characters if c.id not in remapped]
        for scene in result.scenes:
            scene.character_ids = list(dict.fromkeys(remapped.get(cid, cid) for cid in scene.character_ids))
        for character in result.characters:
            for relationship in character.relationships:
                relationship.character_id = remapped.get(relationship.character_id, relationship.character_id)
            character.relationships = [r for r in character.relationships if r.character_id != character.id]

    known_ids = {character.id for character in result.characters}
    for details in review.scene_details:
        evidence(details.evidence)
        if details.id not in scenes or any(e.scene_id != details.id for e in details.evidence):
            raise ValueError("Scene corrections need evidence from that exact local scene.")
        scene = scenes[details.id]
        roster = [remapped.get(cid, cid) for cid in details.character_ids]
        if set(roster) - known_ids:
            raise ValueError(f"Source review must define missing roster Characters in {details.id}.")
        scene.character_ids = list(dict.fromkeys([*scene.character_ids, *roster]))
        removed = set(details.remove_transient_object_ids)
        additions = [*review.characters, *(group.character for group in review.creature_groups)]
        replacements = set(roster) | {entity.id for entity in additions
                                      if any(e.scene_id == details.id for e in entity.evidence)}
        # Addition evidence already establishes membership; do not make the
        # provider repeat that same roster decision solely to remove an object.
        if removed - {obj.id for obj in scene.transient_objects} or (removed and not replacements):
            raise ValueError("Remove only this scene's live-creature objects with replacement Character participants.")
        scene.transient_objects = [obj for obj in scene.transient_objects if obj.id not in removed]
        if details.location_id is not None:
            if details.location_id not in {location.id for location in result.locations}:
                raise ValueError(f"Define the corrected setting {details.location_id} in locations.")
            scene.location_id = details.location_id
        if details.non_narrative:
            if scene.character_ids or scene.transient_objects:
                raise ValueError("Never classify staged action or objects as non-story material.")
            scene.scene_type, scene.location_id, scene.narrative_beat = "non_narrative", None, ""

    for location in review.locations:
        if not any(scene.location_id == location.id for scene in result.scenes):
            raise ValueError(f"New location {location.id} is no scene's setting; move its scenes "
                             "there with scene_details.location_id.")
    _settle_end_looks(result, review.part_end_looks, part_id, remapped, evidence, required=require_end_looks)

    for accessory in review.persistent_accessories:
        evidence(accessory.evidence)
        for absence in accessory.absent_intervals:
            evidence(absence.evidence)
        accessory.character_id = remapped.get(accessory.character_id, accessory.character_id)
        if accessory.character_id not in known_ids:
            raise ValueError("Persistent accessories need a defined Character identity.")
    _carry_accessories(result, review.persistent_accessories, part_id, protected_character_ids, protected_state_keys)
    _mark_carried_looks(result, part_id, protected_character_ids, protected_state_keys)
    for scene in result.scenes:
        scene.character_ids = list(dict.fromkeys(scene.character_ids))
    added_ids = {c.id for c in review.characters} | {g.character.id for g in review.creature_groups}
    for character in result.characters:
        if character.id in added_ids:
            character.first_appearance_scene = next(s.id for s in result.scenes if character.id in s.character_ids)
    for sequence in result.sequences:
        sequence.scenes = [sid for sid in sequence.scenes
                           if sid not in scenes or scenes[sid].scene_type != "non_narrative"]
    _check_character_looks([character.model_dump() for character in result.characters])
    if blank := blank_visual_anchors(result):
        raise ValueError("Source review needs physical descriptions for: " + ", ".join(blank))
    validate_references(result)
    return result


BASE_RETURN_STATE = "audit_base_return"


def _base_return(character) -> str:
    """The character's canonical-equivalent look, created once when missing."""
    existing = next((state for state in character.appearance_states if state.canonical_equivalent), None)
    if existing is not None:
        return existing.id
    if any(state.id == BASE_RETURN_STATE for state in character.appearance_states):
        raise ValueError("Base-return state ID conflicts with an existing look.")
    character.appearance_states.append(AppearanceState(
        id=BASE_RETURN_STATE, label="Return to base look",
        visual_anchor=character.visual_anchor, canonical_equivalent=True))
    return BASE_RETURN_STATE


def _settle_end_looks(bible, looks, part_id, remapped, evidence, *, required: bool) -> None:
    """Close each changed look at the part's end, as the review reports it."""
    order = {scene.id: index for index, scene in enumerate(bible.scenes)}
    local = [scene.id for scene in bible.scenes if scene.part_id == part_id]
    if not local or not (looks or required):
        return
    required = {entry["character_id"]: entry for entry in end_look_candidates(bible, part_id)} if required else {}
    characters = {character.id: character for character in bible.characters}
    reported = {}
    for look in looks:
        evidence(look.evidence)
        character_id = remapped.get(look.character_id, look.character_id)
        if character_id not in characters or character_id in reported:
            raise ValueError(f"Report one part-end look per defined Character: {character_id}.")
        reported[character_id] = look
    if missing := [entry for key, entry in required.items() if key not in reported]:
        raise ValueError("Report part_end_looks for: " + "; ".join(
            f"{entry['name']} ({entry['character_id']}), latest look "
            f"{entry['latest_state_id'] or 'base'} from {(entry['latest_since'] or {}).get('scene_id', 'the start')}"
            for entry in missing) + ". Give the look at this part's last scene; null for the base look.")
    end = order[local[-1]]
    for character_id, look in reported.items():
        character = characters[character_id]
        states = {state.id: state for state in character.appearance_states}
        if look.state_id is not None and look.state_id not in states:
            raise ValueError(f"Unknown part-end look {look.state_id!r} for {character_id}; "
                             f"known looks: {sorted(states)}.")
        timeline = [a for a in character.appearance_timeline if order[a.at.scene_id] <= end
                    and not a.state_id.startswith(WORN_PREFIX)]
        latest = max(timeline, key=lambda a: (order[a.at.scene_id], a.at.beat or 0), default=None)
        current = states[latest.state_id] if latest else None
        wanted = states[look.state_id] if look.state_id is not None else None
        if (wanted is None or wanted.canonical_equivalent) and (current is None or current.canonical_equivalent):
            continue
        if wanted is not None and current is not None and wanted.id == current.id:
            continue
        since = look.since
        if since is None or since.scene_id not in local or (since.beat is not None and since.beat < 1):
            raise ValueError(f"{character.name}'s look at the part's end differs from "
                             f"{current.id if current else 'base'}; give since, the local position where it begins.")
        if latest and (order[since.scene_id], since.beat or 0) <= (order[latest.at.scene_id], latest.at.beat or 0):
            raise ValueError(f"{character.name}'s part-end look must begin after its latest change "
                             f"({latest.state_id} at {latest.at.scene_id}).")
        state_id = wanted.id if wanted is not None else _base_return(character)
        label = states[state_id].label if state_id in states else "Return to base look"
        character.appearance_timeline.append(StateActivation(
            state_id=state_id, at=since, transition=Transition(label=label, depicted_at=since)))
        character.appearance_timeline.sort(key=lambda a: (order[a.at.scene_id], a.at.beat or 0))


def _mark_carried_looks(bible, part_id, protected_character_ids, protected_state_keys) -> None:
    """A principal's look at the part's end carries into the next part: give it a reference."""
    order = {scene.id: index for index, scene in enumerate(bible.scenes)}
    local = [scene.id for scene in bible.scenes if scene.part_id == part_id]
    if not local:
        return
    end = order[local[-1]]
    for character in bible.characters:
        if not character.cast_required:
            continue
        timeline = [a for a in character.appearance_timeline if order[a.at.scene_id] <= end]
        latest = max(timeline, key=lambda a: (order[a.at.scene_id], a.at.beat or 0), default=None)
        state = next((s for s in character.appearance_states if latest and s.id == latest.state_id), None)
        protected = state is not None and ((character.id, state.id) in protected_state_keys
                                           if protected_state_keys is not None
                                           else character.id in protected_character_ids)
        if state is not None and not state.canonical_equivalent and not protected:
            state.visually_significant = True


def _tags(anchor: str) -> list[str]:
    """Comma-separated anchor tags without sentence punctuation."""
    return [tag for tag in (part.strip().rstrip(".;").strip() for part in anchor.split(",")) if tag]


def _items_label(items) -> str:
    names = [item.label for item in items]
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


def _carry_accessories(bible, accessories, part_id, protected_character_ids, protected_state_keys):
    """Compile explicit equipment intervals into complete appearance authorities.

    Existing anchors and guards are copied verbatim into new composed looks.
    A return to a bare base cannot remove still-equipped clothing. Earlier parts
    and their image authorities remain untouched.
    """
    order = {scene.id: index for index, scene in enumerate(bible.scenes)}
    local = {scene.id for scene in bible.scenes if scene.part_id == part_id}

    def position(at):
        if at.scene_id not in local or (at.beat is not None and at.beat < 1):
            raise ValueError("Accessory positions must be local scenes with null or positive beats.")
        return order[at.scene_id], at.beat or 0

    for character in bible.characters:
        intervals = [item for item in accessories if item.character_id == character.id]
        if not intervals:
            continue
        if len({item.id for item in intervals}) != len(intervals):
            raise ValueError("Accessory interval IDs must be unique per Character.")
        for item in intervals:
            if item.until is not None and position(item.until) <= position(item.at):
                raise ValueError("Accessory removal must follow acquisition.")
            previous_end = None
            for absence in sorted(item.absent_intervals, key=lambda gap: position(gap.at)):
                start, end = position(absence.at), position(absence.until)
                if (end <= start or start < position(item.at)
                        or (item.until is not None and end > position(item.until))
                        or (previous_end is not None and start < previous_end)):
                    raise ValueError("Accessory absence intervals must be ordered, disjoint and inside its worn interval.")
                previous_end = end
        catalog = {state.id: state for state in character.appearance_states}
        original = list(character.appearance_timeline)
        body_events = {(order[a.at.scene_id], a.at.beat or 0): a for a in original}
        if len(body_events) != len(original):
            raise ValueError("Appearance activations must have distinct positions before equipment composition.")
        for item in intervals:
            if not item.removes_tags:
                continue
            # A loss names tags of the look it is taken from, exactly.
            key = position(item.at)
            body = max((k for k in body_events if k <= key), default=None)
            anchor = catalog[body_events[body].state_id].visual_anchor if body is not None else character.visual_anchor
            worn = [tag for other in intervals if other is not item and position(other.at) <= key
                    and (other.until is None or key < position(other.until)) for tag in _tags(other.visual_anchor)]
            available = {tag.casefold() for tag in [*_tags(anchor), *worn]}
            if unknown := [tag for tag in item.removes_tags if tag.strip().rstrip(".;").strip().casefold() not in available]:
                raise ValueError(f"removes_tags {unknown} for {item.id} must be exact tags of {character.name}'s "
                                 f"look at {item.at.scene_id}: {[*_tags(anchor), *worn]}.")
        equipment_events = {position(item.at): item.at for item in intervals}
        equipment_events.update({position(item.until): item.until for item in intervals if item.until is not None})
        equipment_events.update({position(at): at for item in intervals for gap in item.absent_intervals
                                 for at in (gap.at, gap.until)})
        events = {**{key: activation.at for key, activation in body_events.items()}, **equipment_events}
        composed = {}
        timeline = []
        current = None
        for key, at in sorted(events.items()):
            activation = body_events.get(key)
            if activation is not None:
                current = catalog[activation.state_id]
            active = [item for item in intervals if position(item.at) <= key
                      and (item.until is None or key < position(item.until))
                      and not any(position(gap.at) <= key < position(gap.until) for gap in item.absent_intervals)]
            if not active:
                if activation is not None:
                    timeline.append(activation)
                elif current is not None:
                    timeline.append(StateActivation(state_id=current.id, at=at,
                        transition=Transition(label="Worn-item visibility change", depicted_at=at)))
                else:
                    state_id = _base_return(character)
                    catalog = {state.id: state for state in character.appearance_states}
                    timeline.append(StateActivation(state_id=state_id, at=at,
                        transition=Transition(label="Worn-item visibility change", depicted_at=at)))
                continue
            signature = (current.id if current and not current.canonical_equivalent else None,
                         tuple(item.id for item in active))
            if signature not in composed:
                digest = hashlib.sha256(json.dumps(signature).encode()).hexdigest()[:12]
                state_id = f"{WORN_PREFIX}{digest}"
                if state_id in catalog:
                    raise ValueError("Equipment state ID conflicts with an existing appearance authority.")
                original_anchor = current.visual_anchor if current else character.visual_anchor
                removed = {tag.strip().rstrip(".;").strip().casefold() for item in active for tag in item.removes_tags}
                base_tags = _tags(original_anchor)
                kept = [tag for tag in base_tags if tag.casefold() not in removed]
                known_tags = {tag.casefold() for tag in base_tags}
                additional_tags = []
                for item in active:
                    for tag in _tags(item.visual_anchor):
                        if tag.casefold() not in known_tags and tag.casefold() not in removed:
                            additional_tags.append(tag)
                            known_tags.add(tag.casefold())
                if not additional_tags and len(kept) == len(base_tags):
                    # Already complete look: no duplicate state/image just to
                    # restate its worn item in an audit interval.
                    if activation is not None:
                        timeline.append(activation)
                    continue
                original_guard = current.continuity_guard if current else None
                guards = [original_guard] if original_guard else []
                # Only what can be seen is enforced; a ring inside a shoe is not.
                guards.extend(f"Keep the {item.label} visible: {', '.join(_tags(item.visual_anchor))}."
                              for item in active if item.visually_significant and not item.removes_tags)
                guards.extend(f"Never draw {', '.join(item.removes_tags)} ({item.label})."
                              for item in active if item.removes_tags)
                state = AppearanceState(id=state_id,
                    label=f"{current.label}, {_items_label(active)}" if current else _items_label(active),
                    visual_anchor=", ".join([original_anchor if len(kept) == len(base_tags) else ", ".join(kept),
                                             *additional_tags]),
                    baseline_affect=current.baseline_affect if current else character.baseline_affect,
                    visually_significant=(current.visually_significant if current and not (
                        current.changed_facets and set(current.changed_facets) <= {"damage"}) else False)
                        or any(item.visually_significant and position(item.at) == key for item in active),
                    changed_facets=tuple(dict.fromkeys([*(current.changed_facets if current else ()), "clothing"])),
                    replaces_identity=current.replaces_identity if current else False,
                    continuity_guard=" ".join(guards))
                character.appearance_states.append(state)
                catalog[state_id] = state
                composed[signature] = state_id
            elif current and current.continuity_guard:
                state = catalog[composed[signature]]
                if current.continuity_guard not in (state.continuity_guard or ""):
                    state.continuity_guard = f"{state.continuity_guard} {current.continuity_guard}"
            transition = activation.transition if activation is not None else Transition(
                label=_items_label([item for item in active if position(item.at) == key])
                if any(position(item.at) == key for item in active) else "Worn-item visibility change",
                depicted_at=at)
            timeline.append(StateActivation(state_id=composed[signature], at=at, transition=transition))
        character.appearance_timeline = timeline
        # Unactivated intermediate looks from this unpublished part do not need
        # duplicate images. Keep their anchors/guards as authored; earlier series
        # authorities are never demoted.
        activated = {activation.state_id for activation in timeline}
        for state in character.appearance_states:
            protected = ((character.id, state.id) in protected_state_keys if protected_state_keys is not None
                         else character.id in protected_character_ids)
            if state.id not in activated and not protected:
                state.visually_significant = False
