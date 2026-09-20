"""Bounded, resumable extraction with deterministic entity continuity.

Only narrative-arc organization needs a book-wide model response. Scene and
entity authorities are validated and merged locally, never rewritten by it.
"""

from __future__ import annotations

import json
import time
from collections import Counter

from pydantic import BaseModel, ConfigDict

from novel_to_comic.ai.context import ai_source_context
from novel_to_comic.clients.structured_call import generate_validated_json
from novel_to_comic.clients.text import generate_json
from novel_to_comic.generation_checkpoints import checkpointed_generator
from novel_to_comic.models.story_bible import NarrativeArc, StoryBible
from novel_to_comic.source_extraction import source_units
from novel_to_comic.target_artifacts import TargetArtifacts
from novel_to_comic.usage import estimate_text_cost

SECTION_OUTPUT_TOKENS = 16000
SECTION_INSTRUCTIONS = """
SECTION EXTRACTION overrides the whole-novel scope and scene-count/three-act
instructions above. Extract ONLY the supplied SOURCE SECTION, including its
ending. Do not invent a climax or resolution for an intermediate section.
Keep chapter numbering book-wide, using previous_chapter until a source heading
establishes a new chapter; a section boundary is not a chapter boundary.
Return narrative_arcs: []; the book's acts will be organized separately.
Use the supplied ID PREFIX for ALL NEW character, location, prop and scene IDs.
Reuse an existing entity ID when a name, alias, description or role refers to
that entity. Never create a duplicate identity because its name or look changes.
Return only characters physically participating here, locations used here, and
significant props present here. Include one-scene participants and plot objects:
later sections may establish recurrence. Relationships may reference registry IDs.
For existing entities, return only id, NEW appearance_states, NEW
appearance_timeline activations, and NEW relationships. Omit unchanged fields:
code supplies the established identity and state definitions verbatim from the
registry. Never retype names, anchors, first appearances, outfits or existing
state definitions. A recurring character with no changes is just {"id":"..."}.
For NEW entities return the full schema above. Describe physical changes as
appearance_states, never by replacing an existing base. Reuse existing state
IDs in activations without re-emitting their definitions. Return only appearance_timeline
activations happening in THIS section; do not repeat earlier transitions or
reset a carried state merely because a section starts. Include recovered states
when a temporary change explicitly ends. First appearances refer to local scenes;
the merger retains the original book-wide first appearance for existing entities.
An appearance state describes a visible physical look, not whether an entity is
present. Disappearance, absence, being mentioned, and being remembered are story
events or participation classifications, not appearance states. Every activation
must reference a state declared on that same entity, either in the supplied
registry or in this response's appearance_states. A carried state needs no new
activation until the source actually changes the look.
These section-delta rules override the whole-novel timeline rule: an existing
entity may have a nonempty state catalog and an empty local appearance_timeline.
Start a scene at the first source unit in this section, even if it continues a
scene in the previous section; downstream adaptation can combine these segments.
Keep summaries concise and omit empty optional arrays. Cover every event through
the final source unit. Do not copy the registry's inactive entities into output.
"""
ARC_PROMPT = """Organize these ordered scene summaries into exactly three narrative acts.
Return JSON with title, author, style_notes (string or null), and narrative_arcs.
Each arc has act (1, 2, or 3), title, scenes (ordered scene IDs), and optional
turning_point (string). Each supplied scene must occur exactly once, in supplied
order across the three acts. Do not return or rewrite scenes, entities, visual
anchors, or timelines. Use the supplied source heading for title/author; never
invent an author if unstated. Empty acts are allowed for very short works.
"""


class BookOrganization(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str
    author: str
    style_notes: str | None = None
    narrative_arcs: list[NarrativeArc]


def split_source(text: str, limit: int) -> list[str]:
    """Partition without lost/duplicated characters or mid-sentence cuts.

    A single source unit larger than the budget is rejected before generation;
    silently splitting it would violate the immutable-source contract.
    """
    sections: list[str] = []
    pending: list[str] = []
    size = 0
    for unit in source_units(text):
        if len(unit.text) > limit:
            raise ValueError(
                f"Source unit {unit.id} exceeds the extraction section limit "
                f"({len(unit.text):,} > {limit:,} characters). Check the source's "
                "sentence formatting or increase extraction_chunk_chars before rerunning."
            )
        if pending and size + len(unit.text) > limit:
            sections.append("".join(pending))
            pending, size = [], 0
        pending.append(unit.text)
        size += len(unit.text)
    if pending:
        sections.append("".join(pending))
    if not sections:
        raise ValueError("Source text cannot be empty")
    return sections


def registry_context(bible: StoryBible | None) -> dict:
    if bible is None:
        return {}
    registry = {}
    for kind in ("characters", "locations", "props"):
        entries = []
        for entity in getattr(bible, kind):
            entry = entity.model_dump(exclude={"appearance_timeline"})
            # The last activation carries the current look across section boundaries.
            entry["carried_state_id"] = (
                entity.appearance_timeline[-1].state_id
                if entity.appearance_timeline else None
            )
            entries.append(entry)
        registry[kind] = entries
    return registry


def hydrate_section(raw: object, previous: StoryBible | None) -> object:
    """Supply immutable known fields locally, leaving new facts model-authored.

    Explicitly supplied conflicting values remain visible to validation. This
    is not a repair that overwrites a model decision with a convenient default.
    """
    if previous is None:
        return raw
    result = json.loads(json.dumps(raw[0] if isinstance(raw, list) else raw))
    if not isinstance(result, dict):
        return result
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
                isinstance(entry, dict) and set(entry) == {"id"}
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
        names = {e.name.casefold().strip(): e.id for e in existing.values()}
        for entity in incoming:
            if entity.id not in existing:
                if not entity.id.startswith(prefix):
                    raise ValueError(f"New entity {entity.id} must use prefix {prefix}")
                if entity.name.casefold().strip() in names:
                    raise ValueError(f"Reuse the registry ID for {entity.name}")
                if previous:
                    getattr(merged, kind).append(entity.model_copy(deep=True))
            else:
                target = targets[entity.id]
                if entity.visual_anchor != target.visual_anchor:
                    raise ValueError(f"Preserve base visual_anchor verbatim for {entity.id}")
                states = {s.id: s for s in target.appearance_states}
                for state in entity.appearance_states:
                    if state.id in states and state != states[state.id]:
                        raise ValueError(f"Preserve state definition verbatim: {entity.id}/{state.id}")
                    if state.id not in states:
                        target.appearance_states.append(state.model_copy(deep=True))
                target.appearance_timeline.extend(entity.appearance_timeline)
                if kind == "characters":
                    for relationship in entity.relationships:
                        if relationship not in target.relationships:
                            target.relationships.append(relationship.model_copy(deep=True))
            for activation in entity.appearance_timeline:
                if activation.at.scene_id not in local_ids:
                    raise ValueError(f"{entity.id} must emit only local timeline activations")
    merged.total_scenes = len(merged.scenes)
    merged.narrative_arcs = []
    validate_references(merged)
    return merged


def validate_references(bible: StoryBible) -> None:
    scenes = {s.id: i for i, s in enumerate(bible.scenes)}
    characters = {c.id for c in bible.characters}
    locations = {loc.id for loc in bible.locations}
    for scene in bible.scenes:
        if scene.location_id not in locations or set(scene.character_ids) - characters:
            raise ValueError(f"Unknown entity reference in {scene.id}")
    for kind in ("characters", "locations", "props"):
        for entity in getattr(bible, kind):
            first = getattr(entity, "first_appearance_scene", None)
            if first is not None and first not in scenes:
                raise ValueError(f"Unknown first appearance for {entity.id}")
            if kind == "characters" and any(r.character_id not in characters for r in entity.relationships):
                raise ValueError(f"Unknown relationship target for {entity.id}")
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


def organization_content(bible: StoryBible, heading: str) -> str:
    return json.dumps({
        "source_heading": heading,
        "title": bible.title, "author": bible.author,
        "scenes": [{"id": s.id, "title": s.title, "summary": s.summary} for s in bible.scenes],
    }, ensure_ascii=False)


async def extract_sections(config, project_dir, ctx, novel_text, system_prompt) -> StoryBible:
    # Local import keeps the existing extraction boundary authoritative.
    from novel_to_comic.stages.s1_extract import _extract_with_retry

    sections = split_source(novel_text, config.extraction_chunk_chars)
    units = source_units(novel_text)
    ctx.set_progress_total(len(sections) + 2)  # sections, organization, publication

    async def recorded_generate(*, execution_mode, **kwargs):
        # Config contains credentials and is neither request JSON nor cache data.
        result = await generate_json(config=config, **kwargs)
        for usage in (*result.additional_usage, result.usage):
            if usage is not None:
                ctx.record_api_usage(usage)
        return result

    cached_generate = checkpointed_generator(
        recorded_generate, artifacts=TargetArtifacts(project_dir), stage="extract",
        model=config.effective_extraction_model(),
    )

    async def generate(*, config, **kwargs):
        return await cached_generate(execution_mode="mock" if config.mock_mode else "live", **kwargs)
    bible = None
    section_offset = 0
    for index, section in enumerate(sections, 1):
        started = time.monotonic()
        prefix = f"part{index:04d}_"
        ctx.log(f"Extracting source section {index}/{len(sections)} ({len(section):,} characters)...")
        ctx.activity(detail=f"Source section {index}/{len(sections)}", force=True)
        content = json.dumps({
            "section": index, "section_count": len(sections), "id_prefix": prefix,
            "source_heading": novel_text[:1000],
            "previous_chapter": bible.scenes[-1].chapter if bible else None,
            "registry": registry_context(bible), "source_section": section,
        }, ensure_ascii=False)

        def validate(value):
            if not value.scenes or value.scenes[0].source_start_quote != source_units(section)[0].text.strip():
                raise ValueError("The section's first scene must start at its first source unit")
            merge_section(bible, value, prefix)

        scope = tuple(unit.id for unit in units
                      if section_offset <= unit.start_offset < section_offset + len(section))
        with ai_source_context(f"section_{index:04d}", scope):
            result = await _extract_with_retry(
                config, system_prompt + SECTION_INSTRUCTIONS, section,
                user_content=content, generate=generate, validate=validate,
                prepare=lambda raw: hydrate_section(raw, bible),
                max_output_tokens=SECTION_OUTPUT_TOKENS,
            )
        # Persist deterministic offsets so repeated sentences in earlier sections
        # cannot pull these scene boundaries backwards during publication.
        search_from = 0
        for scene in result.value.scenes:
            position = section.index(scene.source_start_quote, search_from)
            scene.source_start_offset = section_offset + position
            search_from = position + len(scene.source_start_quote)
        bible = merge_section(bible, result.value, prefix)
        section_offset += len(section)
        ctx.record_item_done()
        ctx.progress(index, len(sections) + 2)
        ctx.log(f"Source section {index}/{len(sections)} ready in {time.monotonic() - started:.1f}s.")

    assert bible is not None
    expected = [s.id for s in bible.scenes]

    def parse_organization(raw):
        value = BookOrganization.model_validate(raw)
        flattened = [s for arc in value.narrative_arcs for s in arc.scenes]
        if [arc.act for arc in value.narrative_arcs] != [1, 2, 3] or flattened != expected:
            missing = list((Counter(expected) - Counter(flattened)).elements())
            raise ValueError(f"Acts 1, 2, 3 must partition all scenes exactly once in order; missing={missing}")
        return value

    content = organization_content(bible, novel_text[:1000])
    ctx.log("Organizing book-wide narrative arcs...")
    outcome = await generate_validated_json(
        config, model=config.effective_extraction_model(), system_prompt=ARC_PROMPT,
        user_content=content, parse=parse_organization,
        correction=lambda raw, error: f"{content}\nPrevious JSON: {json.dumps(raw)}\nFix: {error}",
        label="Extraction narrative arcs", feature="extract.narrative_arcs",
        max_output_tokens=8000, generate=generate,
    )
    bible.title = outcome.value.title
    bible.author = outcome.value.author
    bible.style_notes = outcome.value.style_notes
    bible.narrative_arcs = outcome.value.narrative_arcs
    ctx.record_item_done()
    ctx.progress(len(sections) + 1, len(sections) + 2)
    return bible


def estimate_sections(config, novel_text: str, system_prompt: str) -> float:
    """Price the clean call graph, including growing continuity context.

    Future registries and summaries are unknown at admission; explicit allowances
    keep their repeated inputs in the estimate rather than quoting one request.
    """
    sections = split_source(novel_text, config.extraction_chunk_chars)
    model = config.effective_extraction_model()
    cost = 0.0
    for index, section in enumerate(sections):
        cost += estimate_text_cost(
            model, len(system_prompt + SECTION_INSTRUCTIONS + section) + 1200 + index * 6000,
            output_chars=24000,
        )
    return cost + estimate_text_cost(model, len(ARC_PROMPT) + 1200 + len(sections) * 3000,
                                     output_chars=4000 + len(sections) * 200)
