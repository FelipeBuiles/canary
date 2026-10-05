"""Bounded, resumable extraction with deterministic entity continuity.

The final organization response also checks this part against its source.
Source-backed additions are merged locally before publication; established
anchors and prior-part authorities are never rewritten by it.
"""

from __future__ import annotations

import json
import math
import re
import time
from collections import Counter

from pydantic import BaseModel, ConfigDict, Field

from novel_to_comic.ai.context import ai_source_context
from novel_to_comic.clients.structured_call import StructuredCallError, generate_validated_json
from novel_to_comic.clients.text import generate_json
from novel_to_comic.generation_checkpoints import checkpointed_generator, discard_checkpointed_response
from novel_to_comic.extraction_schema import extraction_schema
from novel_to_comic.extraction_review import (
    ExtractionReview, SOURCE_REVIEW_INSTRUCTIONS, apply_source_review, constrain_review_schema, end_look_candidates,
)
from novel_to_comic.models.story_bible import StorySequence, StoryBible
from novel_to_comic.source_extraction import source_units
from novel_to_comic.target_artifacts import TargetArtifacts
from novel_to_comic.usage import estimate_text_cost
from novel_to_comic.workspace import FIRST_PART_ID

# Reasoning models spend part of this cap before emitting JSON; 16k truncated
# (finish_reason=length) a section in production. Billing follows actual usage.
SECTION_OUTPUT_TOKENS = 32000
SECTION_INSTRUCTIONS = """
Extract only the supplied source_section, including its ending. Scenes remain
in source-text order. Code numbers chapters from detected headings; when the
source has none, carry previous_chapter. A section boundary is not a chapter.
The response schema omits sequences; a separate call organizes them.
Use id_prefix for every NEW entity and scene. Reuse exact registry IDs when the
source refers to that individual or place by name, alias, description or role.
A shared demographic or generic description alone does not identify someone.
If the source introduces a genuinely new individual, define a new character;
never assign an unrelated registry ID just to avoid a new entry.

Known entity definitions are optional when their IDs are referenced by scenes
or participation. An unchanged recurring entry is just {"id":"..."}. For an
existing entity with changes, emit id, newly revealed aliases, new appearance_states and local
appearance_timeline, plus new relationships and distinguishing_features for
characters. Newly stated stable physical facts (height, build, hair or face)
belong in distinguishing_features even when they become known after this
character's first section. A mark, scar, tattoo, brand, injury or garment the
character gains in this section is a change: give it an appearance state from
that point, never a distinguishing feature. Code appends them without rewriting the established
anchor or fabricating a physical change. Set cast_required=true when this
section establishes a principal antagonist, companion or plot-critical creature;
use false otherwise. Code never demotes an existing required Cast identity.
Use [] for arrays
with no changes. Code supplies established names, anchors, first appearances
and state definitions verbatim. Never retype those fields. Reuse existing state
IDs in activations without returning their definitions. Do not repeat earlier
transitions or reset a carried state at a section boundary.
For new entities, use the full new-entity shape in the response schema. Include
important one-scene actors and plot objects; later sections may establish
recurrence. All timeline positions and participation scene IDs belong to THIS
section, even when the entity or state was defined earlier.

Start the first scene at the first source unit, including continuation from the
previous section. When previous_scene is supplied and the section opens in the
middle of it (same time, place and situation), set continues_previous_scene=true:
code joins your first scene to it, so summarize only this section's part of it.
Copy required_first_scene_source_start_quote verbatim into
scenes[0].source_start_quote. The unit may include a title, byline, copyright,
epigraph or chapter heading. It belongs to the first story scene's source span;
do not invent a separate comic scene, character or location for front matter.
Include the opening story events and background in the summary. Cover every
source event through the ending. Return only active entities and changes, not
copies of the whole registry. Code supplies counts and inherited book metadata.
"""
# Sent only when the author has removed entities from the Story Bible.
EXCLUSION_INSTRUCTIONS = """
The author removed the entities listed in excluded_entities. Never create a new
entity for any of those names or aliases; leave such mentions out of rosters.
"""
SEQUENCE_PROMPT = """Finalize this extraction against its source, then group its scenes into sequences.
source_text is the only source; scenes supplies derived passage boundaries and summaries.
The registry is continuity context. Review this part's source for omissions using
source_review; never rewrite the supplied authorities or earlier parts.
Return JSON with title, author, style_notes (string or null), sequences and source_review.
A sequence is a consecutive run of scenes that pursues one goal, conflict or
situation and ends on a turn. Use as many sequences as the source supports,
usually two to six. The source may be one stretch of a longer book: never shape
it into acts or give it a climax or resolution the text does not have.
Each sequence has number (1, 2, 3... in reading order), title, scenes (ordered
scene IDs, at least one) and turn (what has changed when it ends). Each narrative
scene occurs exactly once, in supplied order across the sequences. Exclude
non_narrative matter. Use the actual source opening for title/author; never
invent an author if unstated.
""" + SOURCE_REVIEW_INSTRUCTIONS


class BookOrganization(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str
    author: str
    style_notes: str | None = None
    sequences: list[StorySequence]
    source_review: ExtractionReview = Field(default_factory=ExtractionReview)


def check_sequences(sequences: list[StorySequence], expected: list[str]) -> None:
    """Sequences number 1..n and partition the narrative scenes in order."""
    flattened = [scene for sequence in sequences for scene in sequence.scenes]
    numbers = [sequence.number for sequence in sequences]
    if numbers != list(range(1, len(sequences) + 1)) or flattened != expected:
        missing = list((Counter(expected) - Counter(flattened)).elements())
        raise ValueError(
            "Sequences must be numbered 1..n and partition all narrative scenes exactly "
            f"once in order; numbers={numbers}, missing={missing}"
        )


def organization_schema(scene_ids: list[str] | None = None, *,
                        bible: StoryBible | None = None, prefix: str = "audit_") -> dict:
    """Organize supplied scenes without generating part ownership or unknown IDs."""
    schema = BookOrganization.model_json_schema()
    sequence = schema["$defs"]["StorySequence"]
    sequence["properties"].pop("part_id")
    sequence["required"] = [field for field in sequence["required"] if field != "part_id"]
    sequence["properties"]["scenes"]["minItems"] = 1
    if scene_ids:
        constraint = ({"enum": scene_ids} if len(scene_ids) <= 900 and sum(map(len, scene_ids)) <= 15000
                      else {"pattern": "^(?:" + "|".join(re.escape(value) for value in scene_ids) + ")$"})
        sequence["properties"]["scenes"]["items"] = {"type": "string", **constraint}
    constrain_review_schema(schema, bible=bible, scene_ids=scene_ids, prefix=prefix)
    return schema


class RegistryAnchorConflict(ValueError):
    """Keep stable retry feedback, with full identity details on terminal failure."""

    def __init__(self, known, incoming) -> None:
        self.entity_id = known.id
        self.known_name, self.incoming_name = known.name, incoming.name
        self.known_anchor, self.incoming_anchor = known.visual_anchor, incoming.visual_anchor
        super().__init__(f"Preserve base visual_anchor verbatim for {known.id}")

    def diagnostic(self) -> str:
        return (
            f"{self}. Registry ID {self.entity_id!r} belongs to {self.known_name!r}, "
            f"with visual_anchor {json.dumps(self.known_anchor, ensure_ascii=False)}. "
            f"The response declares {self.incoming_name!r} with visual_anchor "
            f"{json.dumps(self.incoming_anchor, ensure_ascii=False)}. "
            "Check the entity ID against the registry; keep established anchors verbatim "
            "and represent source-supported physical changes in appearance_states."
        )


# A line holding only a scene-break ornament ("* * *", "#", "~~~").
_SCENE_BREAK = re.compile(r"^[ \t]*(?:[*#~•·][ \t]*){1,7}$|^[ \t]*[-–—_]{3,}[ \t]*$", re.MULTILINE)
# How far a cut may move from its equal-share position to reach a better break.
CUT_WINDOW = 0.25


def cut_strengths(text: str, units) -> list[int]:
    """How natural a section cut before each unit is.

    Every section starts a scene, so a cut is a scene boundary the model must
    honour. 3 = chapter heading or scene-break ornament, 2 = paragraph end,
    1 = sentence only. Wrapped (PDF-like) text marks a paragraph end with a
    short final line; unwrapped text with any line break.
    """
    from novel_to_comic.chapter_detection import detect_chapters

    breaks = sorted({chapter.start_offset for chapter in detect_chapters(text)[1:]}
                    | {match.start() for match in _SCENE_BREAK.finditer(text)})
    widths = sorted(len(line.rstrip()) for line in text.splitlines() if line.strip())
    typical = widths[int(len(widths) * 0.9)] if widths else 0
    wrapped = 0 < typical < 200
    strengths = [3]
    for previous, unit in zip(units, units[1:]):
        gap = previous.text[len(previous.text.rstrip()):]
        body_end = previous.end_offset - len(gap)
        last_line = text[text.rfind("\n", 0, body_end) + 1:body_end]
        # Headings open the unit; a break up to a heading's length in still opens it.
        if any(unit.start_offset <= offset <= unit.start_offset + 80 for offset in breaks) or (
                any(previous.start_offset <= offset < body_end for offset in breaks)
                and _SCENE_BREAK.fullmatch(last_line)):
            strengths.append(3)
        elif "\n" in gap and ("\n\n" in gap.replace(" ", "") or not wrapped or len(last_line) < 0.75 * typical):
            strengths.append(2)
        else:
            strengths.append(1)
    return strengths


def split_source(text: str, limit: int) -> list[str]:
    """Partition without lost/duplicated characters or mid-sentence cuts.

    Sections are balanced around equal shares of the source. Greedy filling
    left runt tails (a few sentences) whose sparse context invited the model to
    extract other supplied text instead of the section.

    Each section's first scene starts at its first unit, so a cut is also a
    scene boundary. Within a window around each equal share, the cut moves to
    the strongest break available — a chapter or scene break, then a paragraph
    end — rather than splitting an action beat mid-paragraph.

    A single source unit larger than the budget is rejected before generation;
    silently splitting it would violate the immutable-source contract.
    """
    units = source_units(text)
    if not units:
        raise ValueError("Source text cannot be empty")
    for unit in units:
        if len(unit.text) > limit:
            raise ValueError(
                f"Source unit {unit.id} exceeds the extraction section limit "
                f"({len(unit.text):,} > {limit:,} characters). Check the source's "
                "sentence formatting or increase extraction_chunk_chars before rerunning."
            )
    count = max(1, math.ceil(len(text) / limit))
    strengths = cut_strengths(text, units)
    share = len(text) / count
    cuts = [0]
    for section in range(1, count):
        start = units[cuts[-1]].start_offset
        target = len(text) * section / count
        remaining = count - section
        feasible = [index for index in range(cuts[-1] + 1, len(units))
                    if units[index].start_offset - start <= limit
                    and len(text) - units[index].start_offset <= limit * remaining]
        if not feasible:
            break
        # Without a break in the window, cut at the sentence nearest the equal share.
        nearest = min(feasible, key=lambda index: abs(units[index].start_offset - target))
        window = [index for index in feasible
                  if abs(units[index].start_offset - target) <= CUT_WINDOW * share]
        cuts.append(max(window, key=lambda index: (strengths[index], -abs(units[index].start_offset - target)))
                    if window else nearest)
    bounds = [units[index].start_offset for index in cuts] + [len(text)]
    return [text[start:end] for start, end in zip(bounds, bounds[1:])]


def registry_context(bible: StoryBible | None) -> dict:
    if bible is None:
        return {}
    registry = {}
    for kind in ("characters", "locations", "props"):
        entries = []
        for entity in getattr(bible, kind):
            entry = entity.model_dump(exclude={"appearance_timeline", "origin"})
            # The last activation carries the current look across section boundaries.
            entry["carried_state_id"] = (
                entity.appearance_timeline[-1].state_id
                if entity.appearance_timeline else None
            )
            entries.append(entry)
        registry[kind] = entries
    if bible.excluded_entities:
        registry["excluded_entities"] = [
            entity.model_dump(mode="json", exclude={"removed"}) for entity in bible.excluded_entities
        ]
    return registry


def _registry_name_ids(entities) -> dict[str, set[str]]:
    names: dict[str, set[str]] = {}
    for entity in entities:
        for name in _names(entity):
            names.setdefault(name, set()).add(entity.id)
    return names


def _object_entries(value: object) -> list[dict]:
    # Ignore malformed entries only while resolving references. They remain in
    # the payload for the ordinary schema boundary to reject.
    return [entry for entry in value if isinstance(entry, dict)] if isinstance(value, list) else []


def _rewrite_entity_references(result: dict, characters: dict[str, str], locations: dict[str, str]) -> None:
    """Rewrite typed entity references without changing source or state text."""
    for scene in _object_entries(result.get("scenes")):
        if isinstance(scene.get("character_ids"), list):
            scene["character_ids"] = [characters.get(cid, cid) if isinstance(cid, str) else cid
                                      for cid in scene["character_ids"]]
        if isinstance(scene.get("location_id"), str):
            scene["location_id"] = locations.get(scene["location_id"], scene["location_id"])
    for evidence in _object_entries(result.get("character_participation")):
        if isinstance(evidence.get("character_id"), str):
            cid = evidence["character_id"]
            evidence["character_id"] = characters.get(cid, cid)
    for character in _object_entries(result.get("characters")):
        for relationship in _object_entries(character.get("relationships")):
            if isinstance(relationship.get("character_id"), str):
                cid = relationship["character_id"]
                relationship["character_id"] = characters.get(cid, cid)


def resolve_correction_references(raw: object, previous: object) -> object:
    """Reconcile stale IDs only when a repair kept one exact physical identity.

    Both declarations must exist in this section's response chain. Unknown
    entities are never synthesized, and conflicting or ambiguous declarations
    remain validation errors. Participation and scene validation still run.
    """
    current = raw[0] if isinstance(raw, list) and raw else raw
    prior = previous[0] if isinstance(previous, list) and previous else previous
    if not isinstance(current, dict) or not isinstance(prior, dict):
        return raw

    def identities(payload):
        by_id: dict[str, set[tuple[str, str]]] = {}
        by_identity: dict[tuple[str, str], set[str]] = {}
        for character in _object_entries(payload.get("characters")):
            cid, name, anchor = (character.get(field) for field in ("id", "name", "visual_anchor"))
            if not all(isinstance(value, str) and value.strip() for value in (cid, name, anchor)):
                continue
            identity = (name.casefold().strip(), anchor)
            by_id.setdefault(cid, set()).add(identity)
            by_identity.setdefault(identity, set()).add(cid)
        return by_id, by_identity

    prior_by_id, prior_by_identity = identities(prior)
    current_by_id, current_by_identity = identities(current)
    defined = {entry.get("id") for entry in _object_entries(current.get("characters"))
               if isinstance(entry.get("id"), str)}
    referenced = {entry["character_id"] for entry in _object_entries(current.get("character_participation"))
                  if isinstance(entry.get("character_id"), str)}
    for scene in _object_entries(current.get("scenes")):
        if isinstance(scene.get("character_ids"), list):
            referenced.update(cid for cid in scene["character_ids"] if isinstance(cid, str))
    mapping: dict[str, str] = {}
    for cid in referenced - defined:
        candidates = prior_by_id.get(cid, set())
        if len(candidates) != 1:
            continue
        identity = next(iter(candidates))
        targets = current_by_identity.get(identity, set())
        if len(prior_by_identity[identity]) != 1 or len(targets) != 1:
            continue
        target = next(iter(targets))
        if len(current_by_id[target]) == 1:
            mapping[cid] = target
    if not mapping:
        return raw
    result = json.loads(json.dumps(current))
    _rewrite_entity_references(result, mapping, {})
    return result


def _resolve_registry_ids(result: dict, previous: StoryBible) -> None:
    """Resolve unambiguous repeats without changing established physical facts.

    A new ID with an exact registry name/alias and no contrary anchor tags is a
    redundant identity declaration. Keep the registry's complete anchor verbatim,
    even if the model only copied some of its tags. No fuzzy matching, state
    merging, or guessing between multiple registry identities happens here.
    """
    remapped: dict[str, dict[str, str]] = {}
    for kind in ("characters", "locations", "props"):
        registry = {entity.id: entity for entity in getattr(previous, kind)}
        names = _registry_name_ids(registry.values())
        mapping: dict[str, str] = {}
        remapped[kind] = mapping
        entries = result.get(kind, [])
        if not isinstance(entries, list):
            continue
        counts = Counter(entry.get("id") for entry in entries
                         if isinstance(entry, dict) and isinstance(entry.get("id"), str))
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            entity_id, name = entry.get("id"), entry.get("name")
            if (not isinstance(entity_id, str) or entity_id in registry or counts[entity_id] != 1
                    or not isinstance(name, str)):
                continue
            matches = names.get(name.casefold().strip(), set())
            if len(matches) != 1:
                continue
            target = registry[next(iter(matches))]
            if "visual_anchor" in entry:
                anchor = entry["visual_anchor"]
                if not isinstance(anchor, str):
                    continue
                tags = {tag.strip() for tag in anchor.split(",") if tag.strip()}
                known_tags = {tag.strip() for tag in target.visual_anchor.split(",") if tag.strip()}
                if not tags or not tags <= known_tags:
                    continue
            mapping[entity_id] = target.id
            entry["id"] = target.id
            entry["visual_anchor"] = target.visual_anchor

    # Rewrite only typed references. Scene IDs, quotes, state IDs, descriptions,
    # and continuity guards are source/model authorities and are left verbatim.
    _rewrite_entity_references(result, remapped["characters"], remapped["locations"])


def _reference_only(entry: dict) -> bool:
    return set(entry) <= {"id", "appearance_states", "appearance_timeline", "aliases", "relationships",
                          "distinguishing_features", "cast_required"} and all(
        value is False if field == "cast_required" else value == []
        for field, value in entry.items() if field != "id"
    )


def _coalesce_entity_entries(result: dict, previous: StoryBible | None) -> None:
    """Remove exact repetitions and empty registry echoes without losing facts."""
    for kind in ("characters", "locations", "props"):
        entries = result.get(kind)
        if not isinstance(entries, list):
            continue
        known_ids = {entity.id for entity in getattr(previous, kind)} if previous else set()
        unique = []
        for entry in entries:
            if entry not in unique:
                unique.append(entry)
        result[kind] = [entry for entry in unique if not (
            isinstance(entry, dict) and entry.get("id") in known_ids and _reference_only(entry)
            and any(isinstance(other, dict) and other.get("id") == entry["id"]
                    and not _reference_only(other) for other in unique)
        )]


def hydrate_section(raw: object, previous: StoryBible | None) -> object:
    """Supply immutable known fields locally, leaving new facts model-authored.

    Explicitly supplied conflicting values remain visible to validation. This
    is not a repair that overwrites a model decision with a convenient default.
    """
    result = json.loads(json.dumps(raw[0] if isinstance(raw, list) else raw))
    if not isinstance(result, dict):
        return result
    # Counts are derived; sequences are organized separately. The provider
    # schema does not make the model reproduce either owned field.
    result.setdefault("sequences", [])
    _coalesce_entity_entries(result, previous)
    if previous is None:
        return result
    _resolve_registry_ids(result, previous)
    for field in ("title", "author", "style_notes"):
        result.setdefault(field, getattr(previous, field))
    referenced_characters = {
        cid for scene in result.get("scenes", []) for cid in scene.get("character_ids", [])
    } | {entry.get("character_id") for entry in result.get("character_participation", [])}
    referenced_locations = {scene.get("location_id") for scene in result.get("scenes", [])}
    for kind in ("characters", "locations", "props"):
        registry = {entity.id: entity for entity in getattr(previous, kind)}
        entries = result.get(kind, [])
        if not isinstance(entries, list):
            continue
        # The registry is the authority for known IDs, not the model's redundant
        # local definitions. Resolve actual references before participation checks.
        # Never import scenes from earlier sections or synthesize unknown entities.
        referenced = (referenced_characters if kind == "characters" else
                      referenced_locations if kind == "locations" else set())
        supplied = {entry.get("id") for entry in entries if isinstance(entry, dict)}
        entries.extend({"id": entity_id} for entity_id in registry
                       if entity_id in referenced and entity_id not in supplied)
        result[kind] = entries
        if kind == "characters":
            # An unused ID-only registry echo is not a new visual candidate.
            # The established character remains in the accumulated book.
            entries = [entry for entry in entries if not (
                isinstance(entry, dict) and _reference_only(entry)
                and entry["id"] in registry and entry["id"] not in referenced_characters
            )]
            result[kind] = entries
        for index, entry in enumerate(entries):
            if not isinstance(entry, dict) or entry.get("id") not in registry:
                continue
            known = registry[entry["id"]].model_dump(mode="json")
            known["appearance_timeline"] = []  # past transitions are not new work
            states = entry.get("appearance_states", [])
            if not isinstance(states, list) or any(not isinstance(s, dict) for s in states):
                continue  # let the ordinary boundary report malformed input
            supplied_ids = {state.get("id") for state in states}
            combined_states = [state for state in known["appearance_states"]
                               if state["id"] not in supplied_ids] + states
            entries[index] = {**known, **entry, "appearance_states": combined_states}
    return result


def merge_section(previous: StoryBible | None, section: StoryBible, prefix: str) -> StoryBible:
    """Validate references and append authorities without LLM rewriting."""
    merged = previous.model_copy(deep=True) if previous else section.model_copy(deep=True)
    prior_scene_ids = {s.id for s in previous.scenes} if previous else set()
    local_ids = [s.id for s in section.scenes]
    if not local_ids or len(set(local_ids)) != len(local_ids):
        raise ValueError("Section must contain scenes with unique IDs")
    if any(not s.startswith(prefix) or s in prior_scene_ids for s in local_ids):
        raise ValueError(f"New scene IDs must use section prefix {prefix}")
    if previous:
        merged.scenes.extend(section.scenes)
    for kind in ("characters", "locations", "props"):
        existing = {e.id: e for e in getattr(previous, kind)} if previous else {}
        incoming = getattr(section, kind)
        if len({e.id for e in incoming}) != len(incoming):
            raise ValueError(f"Duplicate {kind} IDs in section")
        targets = {e.id: e for e in getattr(merged, kind)}
        names = _registry_name_ids(existing.values())
        for entity in incoming:
            if entity.id not in existing:
                if not entity.id.startswith(prefix):
                    raise ValueError(f"New entity {entity.id} must use prefix {prefix}")
                if matches := names.get(entity.name.casefold().strip()):
                    authorities = [{"id": existing[eid].id, "name": existing[eid].name,
                                    "visual_anchor": existing[eid].visual_anchor} for eid in sorted(matches)]
                    raise ValueError(
                        f"Reuse the registry ID for {entity.name}. Incoming {kind} ID: {entity.id}. "
                        f"Registry matches: {json.dumps(authorities, ensure_ascii=False)}. "
                        "Use the correct registered ID and update this section's references to it. "
                        "Preserve its visual_anchor verbatim; describe source-supported physical "
                        "changes in appearance_states, not a replacement base anchor. If this is "
                        "a genuinely different entity, give it a distinct source-grounded name. "
                        "Never guess between ambiguous registry matches."
                    )
                if previous:
                    getattr(merged, kind).append(entity.model_copy(deep=True))
            else:
                target = targets[entity.id]
                if entity.visual_anchor != target.visual_anchor:
                    raise RegistryAnchorConflict(target, entity)
                states = {s.id: s for s in target.appearance_states}
                for state in entity.appearance_states:
                    if state.id in states and state != states[state.id]:
                        raise ValueError(f"Preserve state definition verbatim: {entity.id}/{state.id}")
                    if state.id not in states:
                        target.appearance_states.append(state.model_copy(deep=True))
                target.appearance_timeline.extend(entity.appearance_timeline)
                for alias in entity.aliases:
                    if alias not in target.aliases:
                        target.aliases.append(alias)
                if kind == "characters":
                    for feature in entity.distinguishing_features:
                        if feature not in target.distinguishing_features:
                            target.distinguishing_features.append(feature)
                    target.cast_required = target.cast_required or entity.cast_required
                    for relationship in entity.relationships:
                        if relationship not in target.relationships:
                            target.relationships.append(relationship.model_copy(deep=True))
            for activation in entity.appearance_timeline:
                if activation.at.scene_id not in local_ids:
                    raise ValueError(f"{entity.id} must emit only local timeline activations")
    merged.total_scenes = len(merged.scenes)
    if previous is None:
        # Sequences are organized after all sections; earlier parts keep theirs.
        merged.sequences = []
    validate_references(merged)
    return merged


def assign_chapters(scenes, text: str, previous_chapter: int | None) -> None:
    """Number each scene by the chapter heading that precedes its start.

    Headings are detected in code, so a model never carries chapter numbers
    across sections. A heading's stated number is kept; an unnumbered or
    restarted heading continues the book-wide count. Text before a later
    part's first heading continues the previous part's chapter. Source with
    no headings keeps the extraction's own numbering.
    """
    from novel_to_comic.chapter_detection import detect_chapters, heading_number

    chapters = detect_chapters(text)
    if not chapters or (len(chapters) == 1 and chapters[0].title == "Full text"):
        return
    numbers, last = [], previous_chapter or 0
    for chapter in chapters:
        stated = heading_number(chapter.title)
        last = stated if stated is not None and stated >= last else last + 1
        numbers.append(last)
    first_heading = chapters[0].opening_characters
    for scene in scenes:
        # A heading inside the scene's opening sentence ("[ PART 1 ]\n[ 2 ]\n...") opens it.
        offset = (scene.source_start_offset or 0) + len(scene.source_start_quote)
        if offset <= first_heading and previous_chapter:
            scene.chapter = previous_chapter
            continue
        index = max(index for index, chapter in enumerate(chapters)
                    if chapter.start_offset < offset or index == 0)
        scene.chapter = numbers[index]


def join_continued_scene(bible: StoryBible, previous_id: str, continuation_id: str) -> StoryBible:
    """Fold a section's opening scene into the scene it continues.

    A section cut is a scene boundary only when the story changes there. The
    continuation's beats follow the previous scene's last referenced beat, so
    every appearance activation keeps its order.
    """
    result = bible.model_copy(deep=True)
    scenes = {scene.id: scene for scene in result.scenes}
    previous, continuation = scenes[previous_id], scenes[continuation_id]
    entities = [*result.characters, *result.locations, *result.props]
    positions = [position for entity in entities for activation in entity.appearance_timeline
                 for position in (activation.at, activation.transition.depicted_at if activation.transition else None)
                 if position is not None]
    positions = list({id(position): position for position in positions}.values())
    offset = max([position.beat or 0 for position in positions if position.scene_id == previous_id]
                 + [beat for item in previous.transient_objects for beat in item.appears_in_beats], default=0)

    def moved(position):
        if position is not None and position.scene_id == continuation_id:
            position.scene_id = previous_id
            position.beat = offset + (position.beat or 0) + 1

    for position in positions:
        moved(position)
    for entity in entities:
        if getattr(entity, "first_appearance_scene", None) == continuation_id:
            entity.first_appearance_scene = previous_id
    previous.summary = f"{previous.summary} {continuation.summary}".strip()
    previous.character_ids = list(dict.fromkeys([*previous.character_ids, *continuation.character_ids]))
    previous.location_id = previous.location_id or continuation.location_id
    for item in continuation.transient_objects:
        previous.transient_objects.append(item.model_copy(update={
            "appears_in_beats": [offset + beat + 1 for beat in item.appears_in_beats]}))
    result.scenes = [scene for scene in result.scenes if scene.id != continuation_id]
    result.total_scenes = len(result.scenes)
    validate_references(result)
    return result


def validate_references(bible: StoryBible) -> None:
    scenes = {s.id: i for i, s in enumerate(bible.scenes)}
    characters = {c.id for c in bible.characters}
    locations = {loc.id for loc in bible.locations}
    for scene in bible.scenes:
        missing_location = scene.location_id if scene.location_id is not None and scene.location_id not in locations else None
        missing_characters = sorted(set(scene.character_ids) - characters)
        if missing_location is not None or missing_characters:
            raise ValueError(
                f"Unknown entity reference in {scene.id}. "
                f"Undefined location ID: {missing_location!r}; character IDs: {missing_characters}. "
                "Reuse exact registry IDs or define new entities in this section. "
                "A source passage without a physical setting needs no invented location."
            )
    for kind in ("characters", "locations", "props"):
        for entity in getattr(bible, kind):
            first = getattr(entity, "first_appearance_scene", None)
            if first is not None and first not in scenes:
                raise ValueError(f"Unknown first appearance for {entity.id}")
            if kind == "characters":
                unknown_targets = sorted({r.character_id for r in entity.relationships
                                          if r.character_id not in characters})
                if unknown_targets:
                    raise ValueError(
                        f"Unknown relationship target for {entity.id}: {unknown_targets}. "
                        "Use exact registry IDs for known characters. Relationships may target "
                        "only established registry characters or defined visual participants. "
                        "Remove links to background-only people, preserving their story facts "
                        "in scene summaries; never invent visual participation to justify a link."
                    )
            states = {s.id for s in entity.appearance_states}
            if len(states) != len(entity.appearance_states):
                raise ValueError(f"Duplicate appearance state for {entity.id}")
            positions = []
            for activation in entity.appearance_timeline:
                if activation.state_id not in states or activation.at.scene_id not in scenes:
                    raise ValueError(
                        f"Unknown appearance reference for {entity.id}: "
                        f"state_id={activation.state_id!r}, scene_id={activation.at.scene_id!r}. "
                        f"Known entity state IDs: {sorted(states)}; "
                        f"scene exists: {activation.at.scene_id in scenes}. "
                        "Use a declared state or author its complete appearance_states definition "
                        "for a source-supported physical change; do not invent a state for an absence."
                    )
                if activation.transition and activation.transition.depicted_at:
                    if activation.transition.depicted_at.scene_id not in scenes:
                        raise ValueError(f"Unknown transition scene for {entity.id}")
                positions.append((scenes[activation.at.scene_id], activation.at.beat or 0))
            if positions != sorted(set(positions)):
                raise ValueError(f"Appearance timeline must be ordered and unique for {entity.id}")


def organization_content(bible: StoryBible, source_text: str, part_id: str | None = None,
                         *, review_prefix: str = "audit_") -> str:
    scenes = [s for s in bible.scenes if part_id is None or s.part_id == part_id]
    return json.dumps({
        "source_text": source_text, "review_id_prefix": review_prefix,
        "registry": registry_context(bible),
        "end_look_required": end_look_candidates(bible, part_id) if part_id else [],
        "title": bible.title, "author": bible.author,
        "scenes": [{"id": s.id, "title": s.title, "summary": s.summary,
                    "source_start_offset": s.source_start_offset,
                    "source_end_offset": scenes[index + 1].source_start_offset if index + 1 < len(scenes) else len(source_text),
                    "scene_type": s.scene_type, "character_ids": s.character_ids,
                    "transient_objects": [obj.model_dump(mode="json") for obj in s.transient_objects]}
                   for index, s in enumerate(scenes)],
    }, ensure_ascii=False)


def section_instructions(registry: StoryBible | None) -> str:
    """Section rules, plus the removed-entities rule when the author removed any."""
    if registry is not None and registry.excluded_entities:
        return SECTION_INSTRUCTIONS + EXCLUSION_INSTRUCTIONS
    return SECTION_INSTRUCTIONS


CONTINUATION_DESCRIPTION = (
    "True when this section opens mid-scene: its first passage continues previous_scene "
    "without a change of time, place or situation. Code then folds scenes[0] into that scene. "
    "False when the section opens a new scene.")


def section_schema(registry: StoryBible | None, prefix: str, *, continuable: bool = False) -> dict:
    """The section response schema, offering continuation when a previous scene exists."""
    schema = extraction_schema(registry=registry, prefix=prefix)
    if continuable:
        schema["properties"]["continues_previous_scene"] = {
            "type": "boolean", "description": CONTINUATION_DESCRIPTION}
        schema["required"] = [*schema.get("required", []), "continues_previous_scene"]
    return schema


def section_prefix(part_number: int, index: int) -> str:
    """New-ID prefix for a section; later parts never reuse part 1's prefixes."""
    return f"part{index:04d}_" if part_number == 1 else f"p{part_number:04d}s{index:04d}_"


async def extract_sections(
    config, project_dir, ctx, novel_text, system_prompt, *,
    registry: StoryBible | None = None, part_id: str = FIRST_PART_ID,
    part_number: int = 1, first_ordinal: int = 1,
) -> StoryBible:
    """Extract one part's text in sections, continuing ``registry`` when given.

    A later part starts from the series Story Bible: recurring entities keep
    their IDs and the part's scenes, sequences and new entities are appended.
    """
    # Local import keeps the existing extraction boundary authoritative.
    from novel_to_comic.stages.s1_extract import _extract_with_retry

    sections = split_source(novel_text, config.extraction_chunk_chars)
    units = source_units(novel_text, first_ordinal=first_ordinal)
    ctx.set_progress_total(len(sections) + 2)  # sections, organization, publication

    async def recorded_generate(*, execution_mode, **kwargs):
        # Config contains credentials and is neither request JSON nor cache data.
        result = await generate_json(config=config, **kwargs)
        for usage in (*result.additional_usage, result.usage):
            if usage is not None:
                ctx.record_api_usage(usage)
        return result

    target = TargetArtifacts(project_dir)
    cached_generate = checkpointed_generator(
        recorded_generate, artifacts=target, stage="extract",
        model=config.effective_extraction_model(),
    )
    generation_requests: list[dict] = []

    async def generate(*, config, **kwargs):
        request = {"execution_mode": "mock" if config.mock_mode else "live", **kwargs}
        generation_requests.append(request)
        return await cached_generate(**request)

    def archive_failed_responses():
        # Only a fully rejected validation chain is discarded. Intermediate
        # responses on a successful chain must stay: their feedback leads to
        # the accepted correction's exact cache key on resume.
        for request in generation_requests:
            discard_checkpointed_response(
                artifacts=target, stage="extract", model=config.effective_extraction_model(),
                request=request,
            )

    bible = registry.model_copy(deep=True) if registry is not None else None
    section_offset = 0
    for index, section in enumerate(sections, 1):
        generation_requests.clear()
        started = time.monotonic()
        prefix = section_prefix(part_number, index)
        ctx.log(f"Extracting source section {index}/{len(sections)} ({len(section):,} characters)...")
        ctx.activity(detail=f"Source section {index}/{len(sections)}", force=True)
        section_units = tuple(unit for unit in units
                              if section_offset <= unit.start_offset < section_offset + len(section))
        first_unit = section_units[0]
        first_scene_quote = first_unit.text.strip()
        # Within a part, the cut may fall inside a scene. The previous scene is
        # offered so the model can continue it rather than open a new one.
        previous_scene = next((scene for scene in reversed(bible.scenes) if scene.part_id == part_id),
                              None) if bible and index > 1 else None
        content = json.dumps({
            # No separate book-opening excerpt: section 1 begins with it, later
            # sections inherit title/author, and a second source-like passage
            # was extracted in place of short sections.
            "section": index, "section_count": len(sections), "id_prefix": prefix,
            "previous_chapter": bible.scenes[-1].chapter if bible else None,
            "required_first_scene_source_start_quote": first_scene_quote,
            **({"previous_scene": {"id": previous_scene.id, "title": previous_scene.title,
                                   "summary": previous_scene.summary,
                                   "location_id": previous_scene.location_id,
                                   "character_ids": previous_scene.character_ids}}
               if previous_scene else {}),
            "registry": registry_context(bible), "source_section": section,
        }, ensure_ascii=False)
        continues = False

        def prepare(raw):
            nonlocal continues
            response = raw[0] if isinstance(raw, list) and raw else raw
            if isinstance(response, dict):
                continues = previous_scene is not None and response.get("continues_previous_scene") is True
            return hydrate_section(raw, bible)

        def validate(value):
            if not value.scenes or value.scenes[0].source_start_quote != first_scene_quote:
                received = value.scenes[0].source_start_quote if value.scenes else None
                raise ValueError(
                    "The section's first scene must start at its first source unit "
                    f"({first_unit.id}). Set scenes[0].source_start_quote to this exact JSON string: "
                    f"{json.dumps(first_scene_quote, ensure_ascii=False)}. "
                    f"Received: {json.dumps(received, ensure_ascii=False)}. "
                    "Include the opening story events and background; front matter belongs "
                    "to the first scene's source span, without inventing a separate comic scene."
                )
            merge_section(bible, value, prefix)

        scope = tuple(unit.id for unit in section_units)
        with ai_source_context(f"section_{index:04d}", scope):
            try:
                result = await _extract_with_retry(
                    config, system_prompt + section_instructions(bible), section,
                    user_content=content, generate=generate, validate=validate,
                    prepare=prepare,
                    on_validation_failure=archive_failed_responses,
                    max_output_tokens=SECTION_OUTPUT_TOKENS,
                    json_schema=section_schema(bible, prefix, continuable=previous_scene is not None),
                    registry=bible,
                )
            except Exception:
                # Completed sections are checkpointed; say where a rerun picks up.
                if index > 1:
                    ctx.log(f"Sections 1–{index - 1} are saved. Running Extract again resumes at "
                            f"section {index} of {len(sections)}.")
                raise
        # Persist deterministic offsets so repeated sentences in earlier sections
        # cannot pull these scene boundaries backwards during publication.
        search_from = 0
        for scene in result.value.scenes:
            position = section.index(scene.source_start_quote, search_from)
            scene.source_start_offset = section_offset + position
            scene.part_id = part_id
            search_from = position + len(scene.source_start_quote)
        bible = merge_section(bible, result.value, prefix)
        if continues:
            assert previous_scene is not None
            bible = join_continued_scene(bible, previous_scene.id, result.value.scenes[0].id)
            ctx.log(f"Section {index} continues scene {previous_scene.id}.")
        section_offset += len(section)
        ctx.record_item_done()
        ctx.progress(index, len(sections) + 2)
        ctx.log(f"Source section {index}/{len(sections)} ready in {time.monotonic() - started:.1f}s.")

    assert bible is not None
    prior_scenes = [scene for scene in bible.scenes if scene.part_id != part_id]
    assign_chapters([scene for scene in bible.scenes if scene.part_id == part_id], novel_text,
                    prior_scenes[-1].chapter if prior_scenes else None)
    supplied = [s.id for s in bible.scenes if s.part_id == part_id]
    protected = frozenset(c.id for c in registry.characters) if registry else frozenset()
    protected_states = frozenset((c.id, state.id) for c in registry.characters
                                 for state in c.appearance_states) if registry else frozenset()
    review_prefix = f"p{part_number:04d}audit_"
    reviewed = bible

    def parse_organization(raw):
        nonlocal reviewed
        value = BookOrganization.model_validate(raw)
        candidate = apply_source_review(bible, value.source_review, novel_text,
                                        part_id=part_id, protected_character_ids=protected,
                                        new_id_prefix=review_prefix, protected_state_keys=protected_states,
                                        require_end_looks=True)
        expected = [s.id for s in candidate.scenes if s.part_id == part_id and s.scene_type != "non_narrative"]
        excluded = {s.id for s in candidate.scenes if s.part_id == part_id and s.scene_type == "non_narrative"}
        # A correctly classified audit span need not cost another call merely
        # because the model also copied its ID into a sequence.
        for sequence in value.sequences:
            sequence.scenes = [sid for sid in sequence.scenes if sid not in excluded]
        # Order is the authority; code owns the numbering.
        value.sequences = [sequence.model_copy(update={"number": number}) for number, sequence
                           in enumerate((s for s in value.sequences if s.scenes), 1)]
        check_sequences(value.sequences, expected)
        reviewed = candidate
        return value

    content = organization_content(bible, novel_text, part_id, review_prefix=review_prefix)
    ctx.log("Checking source fidelity and organizing sequences...")
    generation_requests.clear()
    try:
        outcome = await generate_validated_json(
            config, model=config.effective_extraction_model(), system_prompt=SEQUENCE_PROMPT,
            user_content=content, parse=parse_organization,
            correction=lambda raw, error: f"{content}\nPrevious JSON: {json.dumps(raw)}\nFix: {error}",
            label="Extraction source review and sequences", feature="extract.sequences",
            max_output_tokens=SECTION_OUTPUT_TOKENS, generate=generate,
            json_schema=organization_schema(supplied, bible=bible, prefix=review_prefix),
        )
    except StructuredCallError:
        archive_failed_responses()
        raise
    bible = reviewed
    if registry is None:
        bible.title = outcome.value.title
        bible.author = outcome.value.author
        bible.style_notes = outcome.value.style_notes
    # The series keeps the title and author established by its first part.
    bible.sequences = [sequence for sequence in bible.sequences if sequence.part_id != part_id] + [
        sequence.model_copy(update={"part_id": part_id}) for sequence in outcome.value.sequences
    ]
    ctx.record_item_done()
    ctx.progress(len(sections) + 1, len(sections) + 2)
    return bible


def estimate_sections(
    config, novel_text: str, system_prompt: str, *, registry: StoryBible | None = None,
) -> float:
    """Price the clean call graph, including growing continuity context.

    Future registries and summaries are unknown at admission; explicit allowances
    keep their repeated inputs in the estimate rather than quoting one request.
    A later part also repeats the series registry it starts from in every call.
    """
    sections = split_source(novel_text, config.extraction_chunk_chars)
    model = config.effective_extraction_model()
    starting_registry = len(json.dumps(registry_context(registry), ensure_ascii=False)) if registry else 0
    schema_chars = len(json.dumps(extraction_schema(registry=registry, prefix=section_prefix(1, 1))))
    cost = 0.0
    for index, section in enumerate(sections):
        cost += estimate_text_cost(
            model,
            len(system_prompt + section_instructions(registry) + section) + schema_chars + 1200 + index * 6000 + starting_registry,
            output_chars=24000,
        )
    return cost + estimate_text_cost(
        model, len(SEQUENCE_PROMPT) + len(json.dumps(organization_schema())) + len(novel_text)
        + starting_registry + 1200 + len(sections) * 9000,
        output_chars=8000 + len(sections) * 500)


def _names(entity) -> set[str]:
    return {name.casefold().strip() for name in (entity.name, *getattr(entity, "aliases", ())) if name}


def apply_exclusions(bible: StoryBible, registry: StoryBible | None) -> tuple[StoryBible, tuple[str, ...]]:
    """Drop new characters and props the author removed earlier.

    Only entities this extraction introduced are considered: an entity already
    in the registry is the author's to keep. Locations stay, because a scene
    needs one; the author can merge a returning location instead.
    """
    excluded = {
        kind: set().union(*(_names(entry) for entry in bible.excluded_entities if entry.kind == kind))
        for kind in ("character", "prop")
    }
    if not any(excluded.values()):
        return bible, ()
    known = {entity.id for kind in ("characters", "props") for entity in getattr(registry, kind)} if registry else set()
    result = bible.model_copy(deep=True)
    suppressed: list[str] = []
    removed: set[str] = set()
    for kind, field in (("character", "characters"), ("prop", "props")):
        kept = []
        for entity in getattr(result, field):
            if entity.id not in known and _names(entity) & excluded[kind]:
                suppressed.append(entity.name)
                removed.add(entity.id)
                continue
            kept.append(entity)
        setattr(result, field, kept)
    for scene in result.scenes:
        scene.character_ids = [cid for cid in scene.character_ids if cid not in removed]
    for character in result.characters:
        character.relationships = [rel for rel in character.relationships if rel.character_id not in removed]
    return result, tuple(suppressed)
