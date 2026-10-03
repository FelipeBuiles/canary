"""Revision and approval behavior for target adaptation briefs."""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from typing import Any, Awaitable, Callable

from pydantic import BaseModel, ConfigDict

from novel_to_comic.narrative_instructions import BRIEF_DEPICTION_GUIDANCE
from novel_to_comic.models.adaptation import AdaptationBrief
from novel_to_comic.models.source import SourceDocument
from novel_to_comic.models.story_bible import StoryBible, story_bible_context
from novel_to_comic.cast_roster import cast_character_ids
from novel_to_comic.book_context import book_context_instructions
from novel_to_comic.target_artifacts import TargetArtifacts

logger = logging.getLogger("canary.briefing")


def recommended_page_envelope(
    *,
    word_count: int,
    scene_count: int,
) -> tuple[int, int]:
    """Return a stable initial editorial range for Brief inference.

    The range is deliberately a recommendation rather than a downstream
    capacity limit. It keeps an unconstrained model from confusing source
    units or prose pages with comic pages while leaving the draft editable.
    """

    words = max(1, word_count)
    scenes = max(1, scene_count)
    minimum = max(scenes * 2, (words + 399) // 400)
    maximum = max(minimum, scenes * 4, (words + 249) // 250)
    return minimum, maximum


def story_page_envelope(
    source: SourceDocument,
    story_bible: StoryBible,
    *,
    part_id: str | None = None,
) -> tuple[int, int]:
    """The recommended page range for one part's source (or a whole book)."""
    scenes = [scene for scene in story_bible.scenes if scene.scene_type != "non_narrative"
              and (part_id is None or scene.part_id == part_id)]
    narrative_ids = {scene.id for scene in scenes}
    units = {unit.id: unit for unit in source.units}
    narrative_text = "".join(source.text[units[scene.first_unit_id].start_offset:
                                         units[scene.last_unit_id].end_offset]
                             for scene in source.scenes if scene.id in narrative_ids)
    return recommended_page_envelope(
        word_count=len(narrative_text.split()),
        scene_count=len(scenes),
    )


#: Decided once for the series; each later part's Brief inherits them from the
#: nearest earlier approved Brief instead of inferring them again.
SERIES_BRIEF_FIELDS = (
    "themes", "point_of_view", "narrator_treatment", "tone", "motifs", "transformation_level",
)


def inherited_brief_fields(brief: AdaptationBrief) -> dict[str, Any]:
    return {field: getattr(brief, field) for field in SERIES_BRIEF_FIELDS}


def brief_inference_schema(*, inherited: Mapping[str, Any] | None = None) -> dict:
    """Request only inferred story direction; code owns approval and inheritance."""
    schema = AdaptationBrief.model_json_schema()
    owned = {"revision", "content_sha256", "status", *(inherited or {})}
    schema["properties"] = {name: value for name, value in schema["properties"].items() if name not in owned}
    schema["required"] = [name for name in schema.get("required", []) if name not in owned]
    return schema


def part_story_view(story_bible: StoryBible, part_id: str) -> dict[str, Any]:
    """The Story Bible as one part's Brief sees it: its own scenes and sequences
    and the characters and places in them. Later parts never leak into a Brief."""
    context = story_bible_context(story_bible)
    scenes = [scene for scene in context["scenes"] if scene["part_id"] == part_id]
    characters = {cid for scene in scenes for cid in scene["character_ids"]}
    locations = {scene["location_id"] for scene in scenes}
    context.update(
        scenes=scenes,
        total_scenes=len(scenes),
        characters=[c for c in context["characters"] if c["id"] in characters],
        locations=[loc for loc in context["locations"] if loc["id"] in locations],
        sequences=[sequence for sequence in context["sequences"] if sequence["part_id"] == part_id],
    )
    return context


def story_so_far(story_bible: StoryBible, part_id: str) -> dict[str, Any]:
    """The previous part's scenes, for direct continuity.

    Earlier parts reach a Brief through the book map's bounded slice instead.
    """
    from novel_to_comic.workspace import part_id as part_identifier, part_ordinal

    ordinal = part_ordinal(part_id)
    previous = part_identifier(ordinal - 1) if ordinal > 1 else None
    return {
        "previous_part_scenes": [
            {"title": scene.title, "summary": scene.summary}
            for scene in story_bible.scenes if scene.part_id == previous
        ],
    }


_SERIES_INSTRUCTIONS = (
    "This source is one part of a longer series. series_direction holds the series' "
    "approved tone, point of view, narrator treatment, themes, motifs and transformation "
    "level: code inherits them unchanged; do not return these fields. story_so_far gives the "
    "previous part's scenes for continuity only. Infer story_promises, ambiguities, protected_language, essential_events, "
    "character_turns, desired_emphasis and the page range from THIS part's source units; "
    "do not list earlier parts' events as this part's essential events. "
)


class StoryDecision(BaseModel):
    """The Story station's single review and approval contract."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    story_bible: StoryBible
    brief: AdaptationBrief


def build_brief_inference_prompt(
    source: SourceDocument,
    story_bible: StoryBible,
    *,
    part_id: str | None = None,
    previous_brief: AdaptationBrief | None = None,
    book: dict[str, Any] | None = None,
) -> str:
    """Compile the target Brief inference contract from canonical Story inputs.

    A part sees only its own scenes; a later part also receives the inherited
    series direction and the previous part's scenes. ``book`` places a part of
    a multi-part book: its position and, when mapped, the book's slice for it.
    """

    page_minimum, page_maximum = story_page_envelope(source, story_bible, part_id=part_id)
    # Brief returns editorial direction, not unit citations or visual assets.
    # Materialize each primary scene range once instead of wrapping every
    # sentence in JSON or repeating the appearance catalogs needed by Cast.
    units = {unit.id: unit for unit in source.units}
    story = (story_bible_context(story_bible) if part_id is None
             else part_story_view(story_bible, part_id))
    fields = {
        'characters': {'id', 'name', 'aliases', 'age_range', 'gender', 'relationships',
                       'identity_kind', 'visual_anchor', 'distinguishing_features', 'default_outfit'},
        'locations': {'id', 'name', 'aliases', 'visual_anchor'},
        'props': {'id', 'name', 'aliases', 'visual_anchor'},
    }
    local_scenes = {scene['id'] for scene in story['scenes']}
    scene_order = {scene.id: index for index, scene in enumerate(story_bible.scenes)}
    first_local = min((scene_order[sid] for sid in local_scenes), default=len(scene_order))
    continuity = {}
    for field in fields:
        for entity in story[field]:
            activations = [activation for activation in entity['appearance_timeline']
                           if activation['at']['scene_id'] in local_scenes]
            previous = [activation for activation in entity['appearance_timeline']
                        if scene_order[activation['at']['scene_id']] < first_local]
            carried = previous[-1]['state_id'] if previous else None
            active_ids = {activation['state_id'] for activation in activations} | {carried}
            states = [{key: state[key] for key in ('id', 'label', 'visual_anchor', 'continuity_guard')}
                      for state in entity['appearance_states'] if state['id'] in active_ids]
            if states:
                continuity[entity['id']] = {'carried_state_id': carried, 'states': states,
                    'activations': [{'state_id': activation['state_id'], 'at': activation['at']}
                                    for activation in activations]}
    for field, included in fields.items():
        story[field] = [{key: value for key, value in entity.items() if key in included}
                        for entity in story[field]]
    scene_fields = {'id', 'part_id', 'chapter', 'title', 'location_id',
                    'character_ids', 'scene_type', 'narrative_beat'}
    story['scenes'] = [{key: value for key, value in scene.items() if key in scene_fields}
                       for scene in story['scenes']]
    story['cast_character_ids'] = sorted(cast_character_ids(story_bible)
                                         & {character['id'] for character in story['characters']})
    story['visual_continuity'] = continuity
    scene_types = {scene['id']: scene['scene_type'] for scene in story['scenes']}
    context = {
        "source_sha256": source.source_sha256,
        "recommended_page_envelope": {
            "minimum": page_minimum,
            "maximum": page_maximum,
        },
        "source_scenes": [
            {"id": scene.id, "scene_type": scene_types.get(scene.id), "text": source.text[
                units[scene.first_unit_id].start_offset:units[scene.last_unit_id].end_offset]}
            for scene in source.scenes
        ],
        "story_bible": story,
    }
    series = ""
    if previous_brief is not None and part_id is not None:
        context["series_direction"] = inherited_brief_fields(previous_brief)
        context["story_so_far"] = story_so_far(story_bible, part_id)
        series = _SERIES_INSTRUCTIONS
    if book:
        context["book_context"] = book
        series = book_context_instructions(book, stage="brief") + series
    fields = brief_inference_schema(inherited=context.get("series_direction"))["properties"]
    transformation = (
        "transformation_level is exactly one of 'faithful', 'medium_specific', or 'transformative'. "
        if "transformation_level" in fields else ""
    )
    return (
        series
        + "Infer an adaptation brief from the complete canonical source and Story Bible. "
        "source_scenes partitions the full, verbatim source text in reading order; "
        "no text is omitted or repeated. Each passage is a derived view of immutable source units. "
        "Prioritize the recurring and author-selected cast_character_ids for ongoing character "
        "arcs; infrequent participants can matter to individual events without needing an arc. "
        "Keep principal bosses, on-page creatures and named companions in essential events "
        "even when they appear briefly. identity_kind='group' is one shared design; source "
        "passages and summaries retain the number of members and their actions. "
        "Read stated physical facts and visual_continuity when interpreting identities and "
        "motifs. Persistent equipped objects stay present through later looks until removed; "
        "a crown motif must agree with its wearer's equipped states. Never upgrade a stated "
        "child to an adult, invent unstated physical detail, or substitute an occupation for "
        "anatomy. Record specific unresolved source/catalog contradictions in ambiguities; "
        "a reading that resolves on reflection is not one (the small hours of a day belong "
        "to the night before). "
        + f"Return one JSON object containing {', '.join(fields)}. "
        "Use plain strings for text fields; list fields are arrays of "
        "plain strings, never objects. Write character_turns as sentences naming "
        "the character and their change. "
        + transformation
        + "target_page_min and target_page_max are positive integers, with min <= max. "
        "The context contains a calibrated recommended_page_envelope. Both "
        "target_page_min and target_page_max MUST remain inside that envelope. "
        "Choose a useful editorial range within it; it is an editable narrative "
        "recommendation, not a page-allocation or layout decision. Do not equate "
        "source units, sentences, paragraphs, or prose pages with comic pages, "
        "and do not assign one page per source unit. "
        "Do not return approval status or revision metadata. "
        "Scenes with scene_type non_narrative retain source matter such as credits "
        "or recommendations; do not turn them into story promises, character turns "
        "or essential events. "
        + BRIEF_DEPICTION_GUIDANCE
        + "\n"
        + json.dumps(
            context,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    )


async def infer_brief(
    source: SourceDocument,
    story_bible: StoryBible,
    /,
    *,
    infer: Callable[[str], Awaitable[Mapping[str, Any]]],
) -> AdaptationBrief:
    """Produce a validated draft through an injected model adapter."""

    inferred_content = await infer(build_brief_inference_prompt(source, story_bible))
    return propose_brief(
        inferred_content,
        page_envelope=story_page_envelope(source, story_bible),
    )


_LIST_FIELDS = (
    "story_promises",
    "themes",
    "ambiguities",
    "motifs",
    "protected_language",
    "essential_events",
    "character_turns",
    "desired_emphasis",
)
_TEXT_FIELDS = ("point_of_view", "narrator_treatment", "tone")
_TRANSFORMATION_LEVELS = ("faithful", "medium_specific", "transformative")
_AUTHORED_FIELDS = ("revision", "status", "content_sha256")


def _transformation_level(described: str) -> str:
    """Map a described transformation level onto the contract's vocabulary.

    The brief is a draft the Story station presents for approval, so reading the
    model's own word is better than discarding what it said — the user sees the
    result and can change it.
    """

    text = described.casefold()
    if "transformative" in text or "reinvent" in text:
        return "transformative"
    if "faithful" in text:
        return "faithful"
    return "medium_specific"


def normalize_inferred_brief(
    inferred_content: Mapping[str, Any],
    /,
    *,
    page_envelope: tuple[int, int] | None = None,
) -> dict[str, Any]:
    """Repair shape slips in inferred brief content without inventing intent.

    A model asked for a list routinely returns one string, and asked for an enum
    returns a sentence describing it. Those are formatting mistakes, not missing
    creative intent, so they are corrected here rather than costing the user a
    failed stage.
    """

    allowed = set(AdaptationBrief.model_fields) - set(_AUTHORED_FIELDS)
    normalized = {
        key: value for key, value in inferred_content.items() if key in allowed
    }
    for field in _LIST_FIELDS:
        value = normalized.get(field)
        if isinstance(value, str):
            normalized[field] = (value,) if value.strip() else ()
    for field in _TEXT_FIELDS:
        value = normalized.get(field)
        if isinstance(value, (list, tuple)):
            normalized[field] = "; ".join(
                str(item).strip() for item in value if str(item).strip()
            )
    level = normalized.get("transformation_level")
    if isinstance(level, str) and level not in _TRANSFORMATION_LEVELS:
        normalized["transformation_level"] = _transformation_level(level)
        logger.info(
            "Inferred transformation_level %r read as %r",
            level,
            normalized["transformation_level"],
        )
    if page_envelope is not None:
        inferred_minimum = normalized.get("target_page_min")
        inferred_maximum = normalized.get("target_page_max")
        envelope_minimum, envelope_maximum = page_envelope
        if (
            isinstance(inferred_minimum, int)
            and not isinstance(inferred_minimum, bool)
            and isinstance(inferred_maximum, int)
            and not isinstance(inferred_maximum, bool)
            and (
                inferred_minimum < envelope_minimum
                or inferred_maximum > envelope_maximum
                or inferred_minimum > inferred_maximum
            )
        ):
            logger.warning(
                "Inferred page range %d-%d fell outside recommended envelope "
                "%d-%d; using the envelope without another model call",
                inferred_minimum,
                inferred_maximum,
                envelope_minimum,
                envelope_maximum,
            )
            normalized["target_page_min"] = envelope_minimum
            normalized["target_page_max"] = envelope_maximum
    return normalized


def propose_brief(
    inferred_content: Mapping[str, Any],
    /,
    *,
    page_envelope: tuple[int, int] | None = None,
    inherited: Mapping[str, Any] | None = None,
) -> AdaptationBrief:
    """Parse inferred adaptation intent without allowing inference to approve it.

    ``inherited`` series fields replace whatever the model returned for them.
    """

    return AdaptationBrief.model_validate(
        {
            **normalize_inferred_brief(
                inferred_content,
                page_envelope=page_envelope,
            ),
            **(inherited or {}),
            "revision": 1,
            "status": "draft",
            "content_sha256": "",
        }
    )


def _reject_stale_revision(
    brief: AdaptationBrief,
    expected_revision: int,
) -> None:
    if expected_revision != brief.revision:
        raise ValueError(
            "stale adaptation brief revision: "
            f"expected {expected_revision}, current revision is {brief.revision}"
        )


def revise_brief(
    brief: AdaptationBrief,
    /,
    *,
    expected_revision: int,
    **changes: Any,
) -> AdaptationBrief:
    """Create a new non-authoritative brief revision with authored changes."""

    _reject_stale_revision(brief, expected_revision)
    payload = brief.model_dump()
    payload.update(changes)
    payload.update(
        revision=brief.revision + 1,
        status="draft",
        content_sha256="",
    )
    return AdaptationBrief.model_validate(payload)


def revise_persisted_brief(
    artifacts: TargetArtifacts,
    /,
    *,
    expected_revision: int,
    **changes: Any,
) -> AdaptationBrief:
    """Persist a stale-safe edit and remove every artifact derived from Brief."""

    revised = revise_brief(
        artifacts.read_brief(),
        expected_revision=expected_revision,
        **changes,
    )
    artifacts.invalidate_after_brief()
    artifacts.write_brief(revised)
    return revised


def revise_story(
    decision: StoryDecision,
    /,
    *,
    expected_revision: int,
    story_bible: StoryBible | None = None,
    **brief_changes: Any,
) -> StoryDecision:
    """Create one revised Story decision and return it to draft review."""

    return StoryDecision(
        story_bible=(
            decision.story_bible
            if story_bible is None
            else story_bible
        ),
        brief=revise_brief(
            decision.brief,
            expected_revision=expected_revision,
            **brief_changes,
        ),
    )


def approve_brief(
    brief: AdaptationBrief,
    /,
    *,
    expected_revision: int,
) -> AdaptationBrief:
    """Approve the current draft, rejecting an editor based on stale content."""

    _reject_stale_revision(brief, expected_revision)
    if brief.status != "draft":
        raise ValueError("approval requires a draft adaptation brief")
    return AdaptationBrief.model_validate(
        {
            **brief.model_dump(),
            "revision": brief.revision + 1,
            "status": "approved",
            "content_sha256": "",
        }
    )


def approve_story(
    decision: StoryDecision,
    /,
    *,
    expected_revision: int,
) -> StoryDecision:
    """Approve the Story Bible and current Brief through one decision."""

    return StoryDecision(
        story_bible=decision.story_bible,
        brief=approve_brief(
            decision.brief,
            expected_revision=expected_revision,
        ),
    )


def series_brief(project_dir) -> AdaptationBrief | None:
    """The nearest earlier part's approved Brief, which a later part inherits."""
    from novel_to_comic.workspace import (
        part_id as part_identifier, part_ordinal, part_workspace, series_root, workspace_part_id,
    )
    from novel_to_comic.target_artifacts import ArtifactInvalid, ArtifactMissing

    identifier = workspace_part_id(project_dir)
    if identifier is None:
        return None
    root = series_root(project_dir)
    for number in range(part_ordinal(identifier) - 1, 0, -1):
        try:
            brief = TargetArtifacts(part_workspace(root, part_identifier(number))).read_brief()
        except (ArtifactMissing, ArtifactInvalid):
            continue
        if brief.status == "approved":
            return brief
    return None


def require_approved_brief(brief: AdaptationBrief, /) -> AdaptationBrief:
    """Return authoritative Brief input or block Adapt before work begins."""

    if brief.status != "approved":
        raise ValueError("Adapt requires an approved adaptation brief")
    return brief
