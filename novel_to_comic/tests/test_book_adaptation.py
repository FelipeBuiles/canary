from __future__ import annotations

import asyncio
import json
import re
from datetime import datetime, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from novel_to_comic.book_adaptation import (
    _BlueprintDraft,
    _BookDraft,
    _LetteringDraft,
    _LedgerException,
    _adaptation_shards,
    _canonicalize_candidate_requirements,
    _generate_book_draft,
    _materialize_draft_ledger,
    _repair_source_scope,
    _splice_draft_repair,
    _story_bible_view,
    _validate_blueprint_scope,
    _validate_locked_lettering,
    AdaptationValidation,
    AdaptationInvariantError,
    build_book_adaptation_prompt,
    build_narrative_treatment_prompt,
    normalize_treatment,
    partition_requirements_by_shard,
    produce_book_adaptation,
    recoverable_adaptation_candidate,
    validate_book_adaptation,
)
from novel_to_comic.models.appearance import (
    AppearanceState,
    StateActivation,
    StoryPosition,
    Transition,
)
from novel_to_comic.models.adaptation import (
    AdaptationBrief,
    AdaptationLedgerEntry,
    AdaptedBeat,
    AppearanceChange,
    BookAdaptation,
    ContinuityTransition,
    LetteringItem,
    NarrativeTreatment,
)
from novel_to_comic.models.source import SourceDocument, SourceScene, SourceUnit
from novel_to_comic.models.story_bible import Character, Scene, StoryBible
from novel_to_comic.models.validation import InvariantFailure
from novel_to_comic.source_extraction import SourceSceneAnchor, build_source_document
from novel_to_comic.stage_runtime import StageRuntime
from novel_to_comic.state import PipelineState
from novel_to_comic.target_artifacts import TargetArtifacts
from novel_to_comic.usage import ApiResult, UsageRecord


def _source_document() -> SourceDocument:
    text = "I saw the door open. I fled into the rain."
    return SourceDocument(
        text=text,
        units=[
            SourceUnit(
                id="source_000001",
                ordinal=1,
                start_offset=0,
                end_offset=21,
                text="I saw the door open. ",
            ),
            SourceUnit(
                id="source_000002",
                ordinal=2,
                start_offset=21,
                end_offset=len(text),
                text="I fled into the rain.",
            ),
        ],
        scenes=[
            SourceScene(
                id="scene_001",
                title="The door",
                first_unit_id="source_000001",
                last_unit_id="source_000002",
            )
        ],
    )


def _story_bible() -> StoryBible:
    return StoryBible(
        title="The Door",
        author="A. Witness",
        total_scenes=0,
        characters=[],
        locations=[],
        scenes=[],
        narrative_arcs=[],
    )


def test_story_bible_view_preserves_extracted_appearance_transitions():
    character = Character(
        id="char_001",
        name="Henry",
        visual_anchor="1man, adult male, dark hair, pale skin",
        age_range="early 20s",
        gender="male",
        distinguishing_features=["dark hair"],
        default_outfit="artist clothes",
        first_appearance_scene="scene_001",
        appearance_states=[
            AppearanceState(
                id="henry_delirious",
                label="Feverish delirium",
                visual_anchor="1man, adult male, dark hair, pale skin",
                baseline_affect="alternating unconsciousness and delirium",
                visually_significant=True,
                continuity_guard="Keep Henry supported in bed; he cannot walk unaided.",
            ),
            AppearanceState(
                id="henry_recovered",
                label="Recovered",
                visual_anchor="1man, adult male, dark hair, pale skin",
                canonical_equivalent=True,
            ),
        ],
        appearance_timeline=[
            StateActivation(
                state_id="henry_delirious",
                at=StoryPosition(scene_id="scene_001", beat=2),
                transition=Transition(label="fever begins"),
            ),
            StateActivation(
                state_id="henry_recovered",
                at=StoryPosition(scene_id="scene_001", beat=4),
                transition=Transition(label="recovers"),
            ),
        ],
    )
    bible = StoryBible(
        title="Fever",
        author="A. Witness",
        total_scenes=1,
        characters=[character],
        locations=[],
        scenes=[
            Scene(
                id="scene_001",
                chapter=1,
                title="The fever",
                location_id="loc_001",
                character_ids=["char_001"],
                summary="Henry becomes delirious, then recovers.",
                scene_type="emotional",
                narrative_beat="rising_action",
                source_start_quote="Henry became ill.",
            )
        ],
        narrative_arcs=[],
    )

    character_view = _story_bible_view(bible)["characters"][0]

    assert character_view["appearance_states"][0]["action_constraint"] == (
        character.appearance_states[0].continuity_guard
    )
    assert character_view["appearance_states"][1]["canonical_equivalent"] is True
    assert [item["state_id"] for item in character_view["appearance_timeline"]] == [
        "henry_delirious",
        "henry_recovered",
    ]


def _approved_brief() -> AdaptationBrief:
    return AdaptationBrief(
        revision=2,
        status="approved",
        story_promises=["The witness survives but cannot recover."],
        themes=["Knowledge has a cost."],
        point_of_view="First-person retrospective.",
        narrator_treatment="Preserve the witness's exact testimony.",
        tone="Cosmic dread.",
        protected_language=["I saw the door open."],
        essential_events=["The witness sees the door open."],
        character_turns=["The witness abandons the investigation."],
        desired_emphasis=["Show the reaction and aftermath."],
        target_page_min=1,
        target_page_max=40,
    )


def _book_adaptation() -> BookAdaptation:
    source = _source_document()
    brief = _approved_brief()
    return BookAdaptation(
        revision=1,
        source_sha256=source.source_sha256,
        brief_revision=brief.revision,
        brief_sha256=brief.content_sha256,
        treatment=NarrativeTreatment(
            causal_spine=[
                "The witness sees the door open.",
                "The witness abandons the investigation.",
            ],
            character_arcs=["Certainty gives way to permanent fear."],
            essential_events=["The witness sees the door open."],
            essential_event_ids=["essential_event_001"],
            character_turns=["The witness abandons the investigation."],
            character_turn_ids=["character_turn_001"],
            reveals=["The door opens without a visible cause."],
            reactions=["The witness flees."],
            consequences=["The witness abandons the investigation."],
            transitions=["The witness flees from the house into the rain."],
            aftermath=["The witness never resumes the investigation."],
            relative_emphasis=["Preserve discovery, reaction, and aftermath."],
        ),
        beats=[
            AdaptedBeat(
                id="beat_0001",
                order=1,
                summary="The witness sees the door open and flees.",
                narrative_function="peak",
                story_functions=[
                    "causal_event",
                    "reveal",
                    "reaction",
                    "consequence",
                    "aftermath",
                    "character_turn",
                ],

                brief_requirement_ids=[
                    "essential_event_001",
                    "character_turn_001",
                ],
                source_unit_ids=["source_000001", "source_000002"],
                lettering=[
                    LetteringItem(
                        id="lettering_0001",
                        kind="caption",
                        text="I saw the door open.",
                        delivery="narration",
                        source_unit_ids=["source_000001"],
                    ),
                    LetteringItem(
                        id="lettering_0002",
                        kind="caption",
                        text="I fled into the rain.",
                        delivery="narration",
                        source_unit_ids=["source_000002"],
                    ),
                ],
            )
        ],
        ledger=[
            AdaptationLedgerEntry(
                source_unit_id="source_000001",
                disposition="caption",
                adapted_beat_ids=["beat_0001"],
                preserved_function="The supernatural reveal remains explicit.",
            ),
            AdaptationLedgerEntry(
                source_unit_id="source_000002",
                disposition="caption",
                adapted_beat_ids=["beat_0001"],
                preserved_function="The immediate reaction remains explicit.",
            ),
        ],
    )


def _blueprint_response(
    beats: tuple[AdaptedBeat, ...] | list[AdaptedBeat],
    *,
    include_legacy_ledger: bool = False,
) -> dict:
    response = {
        "beats": [
            beat.model_dump(mode="json", exclude={"lettering"}) for beat in beats
        ],
        "ledger_exceptions": [],
    }
    if include_legacy_ledger:
        response["ledger"] = [
            {
                "source_unit_id": beats[0].source_unit_ids[0],
                "disposition": "depicted",
                "adapted_beat_ids": [beats[0].id],
                "preserved_function": "An obsolete partial model ledger.",
            }
        ]
    return response


def _lettering_response(
    beats: tuple[AdaptedBeat, ...] | list[AdaptedBeat],
) -> dict:
    return {
        "beats": [
            {
                "beat_id": beat.id,
                "lettering": [
                    item.model_dump(mode="json") for item in beat.lettering
                ],
            }
            for beat in beats
        ]
    }


def test_treatment_prompt_is_book_level_and_forbids_page_or_scene_authority() -> None:
    prompt = build_narrative_treatment_prompt(
        _source_document(),
        _story_bible(),
        _approved_brief(),
    )

    assert '"target_page_min":1' in prompt
    assert '"id":"source_000001"' in prompt
    assert "one book-wide narrative treatment" in prompt
    assert "Do not allocate pages, panels, layouts, or geometry." in prompt
    assert "Do not create parallel per-scene adaptations" in prompt


def test_adaptation_prompt_uses_story_granularity_not_the_page_floor() -> None:
    brief = _approved_brief().model_copy(
        update={"target_page_min": 32, "target_page_max": 40}
    )
    prompt = build_book_adaptation_prompt(
        _source_document(),
        _story_bible(),
        brief,
        _book_adaptation().treatment,
    )

    assert "The target page range is not a beat-count target" in prompt
    assert "one drawable story moment" in prompt
    assert "at least 32 distinct" not in prompt
    assert "Do not allocate pages" in prompt
    assert "source-linked canonical LetteringItem" in prompt


def test_adaptation_prompt_requires_reader_visible_causality_and_speaker_targets():
    prompt = build_book_adaptation_prompt(
        _source_document(),
        _story_bible(),
        _approved_brief(),
        _book_adaptation().treatment,
    )

    assert "reader has not read the source" in prompt
    assert "beat summaries are never visible to the reader" in prompt
    assert "independent pieces of evidence" in prompt
    assert "speaker_entity_id" in prompt
    assert "quoted prose" in prompt
    assert "delivery" in prompt


def test_faithful_adaptation_cannot_erase_almost_an_entire_source_scene() -> None:
    text = " ".join(f"Sentence {index}." for index in range(1, 21))
    units = []
    offset = 0
    for index in range(1, 21):
        unit_text = f"Sentence {index}."
        suffix = " " if index < 20 else ""
        units.append(
            SourceUnit(
                id=f"source_{index:06d}",
                ordinal=index,
                start_offset=offset,
                end_offset=offset + len(unit_text) + len(suffix),
                text=unit_text + suffix,
            )
        )
        offset += len(unit_text) + len(suffix)
    source = SourceDocument(
        text=text,
        units=units,
        scenes=[
            SourceScene(
                id="scene_001",
                title="The evidence",
                first_unit_id="source_000001",
                last_unit_id="source_000020",
            )
        ],
    )
    brief_payload = _approved_brief().model_dump(mode="json")
    brief_payload.update(
        content_sha256="",
        transformation_level="faithful",
        protected_language=[],
    )
    brief = AdaptationBrief.model_validate(brief_payload)
    adaptation = BookAdaptation(
        revision=1,
        source_sha256=source.source_sha256,
        brief_revision=brief.revision,
        brief_sha256=brief.content_sha256,
        treatment=NarrativeTreatment(
            causal_spine=["The witness reviews the evidence."],
            essential_events=brief.essential_events,
            essential_event_ids=["essential_event_001"],
            character_turns=brief.character_turns,
            character_turn_ids=["character_turn_001"],
        ),
        beats=[
            AdaptedBeat(
                id="beat_0001",
                order=1,
                summary="The witness reviews one surviving clue.",
                narrative_function="initial",
                story_functions=["causal_event", "character_turn"],

                brief_requirement_ids=[
                    "essential_event_001",
                    "character_turn_001",
                ],
                source_unit_ids=["source_000001", "source_000002"],
                lettering=[
                    LetteringItem(
                        id="lettering_0001",
                        kind="caption",
                        text="Only one clue remained.",
                        delivery="narration",
                        source_unit_ids=["source_000001"],
                    )
                ],
            )
        ],
        ledger=[
            AdaptationLedgerEntry(
                source_unit_id=f"source_{index:06d}",
                disposition=(
                    "caption"
                    if index == 1
                    else "depicted"
                    if index == 2
                    else "intentionally_omitted"
                ),
                adapted_beat_ids=(["beat_0001"] if index <= 2 else []),
                reason=(None if index <= 2 else "Removed for compression."),
                preserved_function=(
                    "The clue remains."
                    if index <= 2
                    else "The source function was removed."
                ),
            )
            for index in range(1, 21)
        ],
    )

    validation = validate_book_adaptation(source, brief, adaptation)

    failure = next(
        item
        for item in validation.invariant_failures
        if item.code == "faithful_source_scene_erased"
    )
    assert failure.artifact_ids == ("scene_001",)
    assert failure.source_unit_ids[0] == "source_000003"
    assert failure.source_unit_ids[-1] == "source_000020"


def test_faithful_adaptation_rejects_reader_critical_silent_runs() -> None:
    source = build_source_document(
        "A clue appears. It matches a second record. The witness understands.",
        [
            SourceSceneAnchor(
                id="scene_001",
                title="The correlation",
                opening_quote="A clue appears.",
            )
        ],
    )
    brief_payload = _approved_brief().model_dump(mode="json")
    brief_payload.update(
        content_sha256="",
        transformation_level="faithful",
        protected_language=[],
    )
    brief = AdaptationBrief.model_validate(brief_payload)
    functions = (
        ("causal_event",),
        ("reveal",),
        ("reaction", "character_turn"),
    )
    beats = [
        AdaptedBeat(
            id=f"beat_{index:04d}",
            order=index,
            summary=source.units[index - 1].text.strip(),
            narrative_function=("peak" if index == 2 else "prolongation"),
            story_functions=functions[index - 1],

            brief_requirement_ids=(
                ["essential_event_001", "character_turn_001"] if index == 1 else []
            ),
            source_unit_ids=[source.units[index - 1].id],
            lettering=[],
        )
        for index in range(1, 4)
    ]
    adaptation = BookAdaptation(
        revision=1,
        source_sha256=source.source_sha256,
        brief_revision=brief.revision,
        brief_sha256=brief.content_sha256,
        treatment=NarrativeTreatment(
            causal_spine=["A clue is correlated and changes the witness."],
            essential_events=brief.essential_events,
            essential_event_ids=["essential_event_001"],
            character_turns=brief.character_turns,
            character_turn_ids=["character_turn_001"],
        ),
        beats=beats,
        ledger=[
            AdaptationLedgerEntry(
                source_unit_id=unit.id,
                disposition="depicted",
                adapted_beat_ids=[beats[index].id],
                preserved_function="The event is depicted.",
            )
            for index, unit in enumerate(source.units)
        ],
    )

    validation = validate_book_adaptation(source, brief, adaptation)

    failure = next(
        item
        for item in validation.invariant_failures
        if item.code == "reader_context_gap"
    )
    assert failure.artifact_ids == ("beat_0001", "beat_0002", "beat_0003")


def test_dialogue_requires_explicit_delivery_and_onscreen_speaker_entity() -> None:
    source = _source_document()
    brief_payload = _approved_brief().model_dump(mode="json")
    brief_payload.update(content_sha256="", protected_language=[])
    brief = AdaptationBrief.model_validate(brief_payload)
    payload = _book_adaptation().model_dump(mode="json")
    payload["content_sha256"] = ""
    payload["brief_sha256"] = brief.content_sha256
    payload["beats"][0]["lettering"][0] = {
        "id": "lettering_0001",
        "kind": "dialogue",
        "text": "The records match.",
        "speaker": "Professor Webb",
        "speaker_entity_id": None,
        "delivery": "onscreen",
        "source_unit_ids": ["source_000001"],
    }
    payload["ledger"][0]["disposition"] = "dialogue"
    adaptation = BookAdaptation.model_validate(payload)

    validation = validate_book_adaptation(
        source,
        brief,
        adaptation,
        story_bible=_story_bible(),
    )

    failure = next(
        item
        for item in validation.invariant_failures
        if item.code == "invalid_lettering_speaker"
    )
    assert failure.artifact_ids == ("lettering_0001",)


def test_dialogue_cannot_combine_multiple_speakers_in_one_label() -> None:
    source = _source_document()
    brief_payload = _approved_brief().model_dump(mode="json")
    brief_payload.update(content_sha256="", protected_language=[])
    brief = AdaptationBrief.model_validate(brief_payload)
    payload = _book_adaptation().model_dump(mode="json")
    payload["content_sha256"] = ""
    payload["brief_sha256"] = brief.content_sha256
    payload["beats"][0]["lettering"][0] = {
        "id": "lettering_0001",
        "kind": "dialogue",
        "text": "The records match.",
        "speaker": "Scholars/Cultists",
        "delivery": "offscreen",
        "source_unit_ids": ["source_000001"],
    }
    payload["ledger"][0]["disposition"] = "dialogue"
    adaptation = BookAdaptation.model_validate(payload)

    validation = validate_book_adaptation(
        source,
        brief,
        adaptation,
        story_bible=_story_bible(),
    )

    failure = next(
        item
        for item in validation.invariant_failures
        if item.code == "invalid_lettering_speaker"
    )
    assert "cannot combine multiple possible owners" in failure.evidence[0]


@pytest.mark.parametrize(
    ("ledger", "code"),
    [
        (
            [
                AdaptationLedgerEntry(
                    source_unit_id="source_000001",
                    disposition="caption",
                    adapted_beat_ids=["beat_0001"],
                    preserved_function="The reveal remains explicit.",
                )
            ],
            "missing_source_disposition",
        ),
        (
            [
                AdaptationLedgerEntry(
                    source_unit_id="source_000001",
                    disposition="caption",
                    adapted_beat_ids=["beat_0001"],
                    preserved_function="The reveal remains explicit.",
                ),
                AdaptationLedgerEntry(
                    source_unit_id="source_000002",
                    disposition="caption",
                    adapted_beat_ids=["beat_0001"],
                    preserved_function="The reaction remains explicit.",
                ),
                AdaptationLedgerEntry(
                    source_unit_id="source_999999",
                    disposition="caption",
                    adapted_beat_ids=["beat_0001"],
                    preserved_function="An invented source unit.",
                ),
            ],
            "unknown_source_disposition",
        ),
    ],
)
def test_every_source_unit_requires_exactly_one_valid_disposition(
    ledger: list[AdaptationLedgerEntry],
    code: str,
) -> None:
    payload = _book_adaptation().model_dump()
    payload["ledger"] = [entry.model_dump() for entry in ledger]
    payload["content_sha256"] = ""
    candidate = BookAdaptation.model_validate(payload)

    result = validate_book_adaptation(
        _source_document(),
        _approved_brief(),
        candidate,
    )

    assert [failure.code for failure in result.invariant_failures] == [code]


def test_page_minimum_does_not_force_adapt_to_pad_the_story_with_beats() -> None:
    brief = _approved_brief().model_copy(
        update={"target_page_min": 2, "target_page_max": 4}
    )

    result = validate_book_adaptation(
        _source_document(),
        brief,
        _book_adaptation(),
    )

    assert "insufficient_page_granularity" not in {
        failure.code for failure in result.invariant_failures
    }


def test_saved_candidate_preserves_caption_but_does_not_invent_requirement_coverage() -> None:
    source = _source_document()
    brief = _approved_brief().model_copy(
        update={"protected_language": ("I fled into the rain.",)}
    )
    payload = _book_adaptation().model_dump(mode="json")
    payload["content_sha256"] = ""
    payload["brief_sha256"] = brief.content_sha256
    payload["beats"][0]["summary"] = (
        "The witness sees the door open, then abandons the investigation "
        "and flees into the rain."
    )
    payload["beats"][0]["brief_requirement_ids"] = []
    payload["beats"][0]["lettering"] = payload["beats"][0]["lettering"][:1]
    candidate = BookAdaptation.model_validate(payload)

    recovered = _canonicalize_candidate_requirements(
        candidate,
        source,
        brief,
    )

    assert recovered.beats[0].brief_requirement_ids == ()
    assert recovered.beats[0].lettering[-1].text == "I fled into the rain."
    assert recovered.beats[0].lettering[-1].source_unit_ids == ("source_000002",)
    assert {failure.code for failure in validate_book_adaptation(source, brief, recovered).invariant_failures} >= {"missing_essential_event", "missing_character_turn"}


def test_source_unit_cannot_have_two_ledger_dispositions() -> None:
    payload = _book_adaptation().model_dump()
    payload["content_sha256"] = ""
    payload["ledger"] = [*payload["ledger"], payload["ledger"][0]]

    with pytest.raises(ValidationError, match="ledger source units must be unique"):
        BookAdaptation.model_validate(payload)


@pytest.mark.parametrize(
    ("disposition", "adapted_beat_ids"),
    [
        ("compressed_into", []),
        ("intentionally_omitted", ["beat_0001"]),
    ],
)
def test_compression_and_omission_require_valid_destinations(
    disposition: str,
    adapted_beat_ids: list[str],
) -> None:
    with pytest.raises(ValidationError, match="destination"):
        AdaptationLedgerEntry(
            source_unit_id="source_000001",
            disposition=disposition,
            adapted_beat_ids=adapted_beat_ids,
            reason="A deliberate editorial choice.",
            preserved_function="The source function is explicitly accounted for.",
        )


def _with_lettering_text(text: str) -> BookAdaptation:
    payload = _book_adaptation().model_dump()
    payload["content_sha256"] = ""
    payload["beats"][0]["lettering"][0]["text"] = text
    return BookAdaptation.model_validate(payload)


def test_protected_language_must_survive_verbatim_in_publishable_wording() -> None:
    candidate = _with_lettering_text("I watched the door open.")

    result = validate_book_adaptation(
        _source_document(),
        _approved_brief(),
        candidate,
    )

    assert "protected_language_missing" in {
        failure.code for failure in result.invariant_failures
    }


@pytest.mark.parametrize(
    ("text", "code"),
    [
        ("I saw the door open", "trailing_clipped_display_text"),
        ('I saw the door open. "Then I fled.', "incomplete_display_text"),
    ],
)
def test_incomplete_or_trailing_clipped_display_text_blocks(
    text: str,
    code: str,
) -> None:
    candidate = _with_lettering_text(text)

    result = validate_book_adaptation(
        _source_document(),
        _approved_brief(),
        candidate,
    )

    assert code in {failure.code for failure in result.invariant_failures}


def test_continuity_is_scoped_to_the_character_or_narrative_thread() -> None:
    payload = _book_adaptation().model_dump()
    payload["content_sha256"] = ""
    first = payload["beats"][0]
    first["transitions"] = [
        {
            "dimension": "emotional_state",
            "scope_id": "henry_wilcox",
            "from_state": "calm",
            "to_state": "terrified",
            "description": "Wilcox receives the signal.",
        }
    ]
    second = {
        **first,
        "id": "beat_0002",
        "order": 2,
        "lettering": [],
        "transitions": [
            {
                "dimension": "emotional_state",
                "scope_id": "gustaf_johansen",
                "from_state": "curious",
                "to_state": "horrified",
                "description": "Johansen reads the manuscript.",
            }
        ],
    }
    payload["beats"] = [first, second]

    result = validate_book_adaptation(
        _source_document(),
        _approved_brief(),
        BookAdaptation.model_validate(payload),
    )

    assert "continuity_state_mismatch" not in {
        issue.code for issue in result.editorial_issues
    }


def test_adapted_beats_record_story_functions_without_page_or_geometry_fields() -> None:
    beat = AdaptedBeat(
        id="beat_0001",
        order=1,
        summary="The witness crosses the threshold and changes.",
        narrative_function="transition",
        story_functions=[
            "causal_event",
            "reveal",
            "reaction",
            "consequence",
            "transition",
            "aftermath",
            "character_turn",
        ],
        source_unit_ids=["source_000001"],
        transitions=[
            ContinuityTransition(
                dimension="place",
                scope_id="witness_testimony",
                from_state="street",
                to_state="threshold",
                description="The witness enters the house.",
            )
        ],
        appearance_changes=[
            AppearanceChange(
                entity_id="witness",
                from_state_id=None,
                to_state_id="witness_rain_soaked",
                description="Rain soaks the witness's coat.",
            )
        ],
    )

    payload = beat.model_dump()

    assert payload["story_functions"][-1] == "character_turn"
    assert payload["transitions"][0]["to_state"] == "threshold"
    assert payload["appearance_changes"][0]["to_state_id"] == "witness_rain_soaked"
    assert not {"page", "panel", "layout", "geometry"} & payload.keys()


@pytest.mark.parametrize(
    ("first_from", "second_from", "code"),
    [
        (None, "witness_dry", "appearance_state_chronology"),
        (None, "witness_rain_soaked", "transition_continuity"),
    ],
)
def test_appearance_state_and_transition_chronology_validate(
    first_from: str | None,
    second_from: str,
    code: str,
) -> None:
    payload = _book_adaptation().model_dump()
    payload["content_sha256"] = ""
    first = payload["beats"][0]
    first["appearance_changes"] = [
        {
            "entity_id": "witness",
            "from_state_id": first_from,
            "to_state_id": "witness_rain_soaked",
            "description": "The witness is soaked by rain.",
        }
    ]
    first["transitions"] = [
        {
            "dimension": "place",
            "scope_id": "witness_testimony",
            "from_state": "street",
            "to_state": "threshold",
            "description": "The witness reaches the house.",
        }
    ]
    second = {
        **first,
        "id": "beat_0002",
        "order": 2,
        "summary": "The witness enters.",
        "source_unit_ids": ["source_000002"],
        "lettering": [],

        "appearance_changes": [
            {
                "entity_id": "witness",
                "from_state_id": second_from,
                "to_state_id": "witness_shaken",
                "description": "The witness begins to shake.",
            }
        ],
        "transitions": [
            {
                "dimension": "place",
                "scope_id": "witness_testimony",
                "from_state": (
                    "cellar" if code == "transition_continuity" else "threshold"
                ),
                "to_state": "hall",
                "description": "The witness enters the hall.",
            }
        ],
    }
    payload["beats"] = [*payload["beats"], second]
    candidate = BookAdaptation.model_validate(payload)

    result = validate_book_adaptation(
        _source_document(),
        _approved_brief(),
        candidate,
    )

    if code == "transition_continuity":
        assert "continuity_state_mismatch" in {
            issue.code for issue in result.editorial_issues
        }
        assert code not in {failure.code for failure in result.invariant_failures}
    else:
        assert code in {failure.code for failure in result.invariant_failures}


def _two_beat_payload(*, from_state: str, from_state_id: str | None) -> dict:
    payload = _book_adaptation().model_dump()
    payload["content_sha256"] = ""
    first = payload["beats"][0]
    first["appearance_changes"] = [
        {
            "entity_id": "witness",
            "from_state_id": None,
            "to_state_id": "witness_dry",
            "description": "The witness is dry.",
        }
    ]
    first["transitions"] = [
        {
            "dimension": "place",
            "scope_id": "witness_testimony",
            "from_state": "street",
            "to_state": "the threshold of the old house",
            "description": "The witness reaches the house.",
        }
    ]
    second = {
        **first,
        "id": "beat_0002",
        "order": 2,
        "summary": "The witness enters.",
        "source_unit_ids": ["source_000002"],
        "lettering": [],

        "appearance_changes": [
            {
                "entity_id": "witness",
                "from_state_id": from_state_id,
                "to_state_id": "witness_shaken",
                "description": "The witness begins to shake.",
            }
        ],
        "transitions": [
            {
                "dimension": "place",
                "scope_id": "witness_testimony",
                "from_state": from_state,
                "to_state": "hall",
                "description": "The witness enters the hall.",
            }
        ],
    }
    payload["beats"] = [*payload["beats"], second]
    return payload


def test_canonicalization_derives_a_paraphrased_transition_origin() -> None:
    """A paraphrase of the prior state is the same continuity, not a break.

    The writer returned "the threshold" for "the threshold of the old house";
    the prior state is already known, so it is filled in rather than compared.
    """
    candidate = BookAdaptation.model_validate(
        _two_beat_payload(from_state="the threshold", from_state_id="witness_dry")
    )

    canonical = _canonicalize_candidate_requirements(
        candidate, _source_document(), _approved_brief()
    )

    assert canonical.beats[1].transitions[0].from_state == (
        "the threshold of the old house"
    )
    result = validate_book_adaptation(_source_document(), _approved_brief(), canonical)
    assert "continuity_state_mismatch" not in {
        issue.code for issue in result.editorial_issues
    }


def test_canonicalization_discards_a_transition_to_the_current_state() -> None:
    payload = _two_beat_payload(
        from_state="London",
        from_state_id="witness_dry",
    )
    payload["beats"][1]["transitions"][0]["to_state"] = (
        "the threshold of the old house"
    )
    candidate = BookAdaptation.model_validate(payload)

    canonical = _canonicalize_candidate_requirements(
        candidate,
        _source_document(),
        _approved_brief(),
    )

    assert canonical.beats[1].transitions == ()


def test_spliced_repair_redirects_external_compression_to_replacement_beat() -> None:
    template = _book_adaptation().beats[0]
    original = _BookDraft(
        beats=(
            template.model_copy(
                update={
                    "id": "beat_0001",
                    "order": 1,
                    "source_unit_ids": ("source_000001",),
                }
            ),
            template.model_copy(
                update={
                    "id": "beat_0002",
                    "order": 2,
                    "source_unit_ids": ("source_000002",),
                }
            ),
        ),
        ledger=(
            AdaptationLedgerEntry(
                source_unit_id="source_000001",
                disposition="compressed_into",
                adapted_beat_ids=["beat_0002"],
                reason="The second beat carries the connection.",
                preserved_function="The connection remains explicit.",
            ),
            AdaptationLedgerEntry(
                source_unit_id="source_000002",
                disposition="depicted",
                adapted_beat_ids=["beat_0002"],
                preserved_function="The destination is depicted.",
            ),
        ),
    )
    repair = _BookDraft(
        beats=(
            template.model_copy(
                update={
                    "id": "beat_0001",
                    "order": 1,
                    "source_unit_ids": ("source_000002",),
                }
            ),
        ),
        ledger=(
            AdaptationLedgerEntry(
                source_unit_id="source_000002",
                disposition="depicted",
                adapted_beat_ids=["beat_0001"],
                preserved_function="The repaired destination is depicted.",
            ),
        ),
    )

    spliced = _splice_draft_repair(
        original,
        repair,
        ("source_000002",),
        {"source_000001": 1, "source_000002": 2},
    )

    assert spliced.ledger[0].adapted_beat_ids == ("beat_0002",)


def test_canonicalization_derives_a_wrong_appearance_origin() -> None:
    # The appearance equivalent blocks the stage, so deriving it removes a
    # repair round rather than just log noise.
    candidate = BookAdaptation.model_validate(
        _two_beat_payload(
            from_state="the threshold of the old house", from_state_id="witness_soaked"
        )
    )

    canonical = _canonicalize_candidate_requirements(
        candidate, _source_document(), _approved_brief()
    )

    assert canonical.beats[1].appearance_changes[0].from_state_id == "witness_dry"
    result = validate_book_adaptation(_source_document(), _approved_brief(), canonical)
    assert "appearance_state_chronology" not in {
        failure.code for failure in result.invariant_failures
    }


def test_canonicalization_leaves_the_first_state_in_a_scope_as_authored() -> None:
    candidate = BookAdaptation.model_validate(
        _two_beat_payload(from_state="the threshold", from_state_id="witness_dry")
    )

    canonical = _canonicalize_candidate_requirements(
        candidate, _source_document(), _approved_brief()
    )

    # Nothing precedes it, so there is no prior state to derive from.
    assert canonical.beats[0].transitions[0].from_state == "street"
    assert canonical.beats[0].appearance_changes[0].from_state_id is None


def test_canonicalization_realizes_ledgered_dialogue_and_protected_wording() -> None:
    protected = (
        "That is not dead which can eternal lie, "
        "And with strange aeons even death may die."
    )
    source_text = (
        "The ritual ended: “Ph’nglui mglw’nafh Cthulhu R’lyeh "
        "wgah’nagl fhtagn.”\n"
        "The book preserved a couplet:\n\n"
        "“That is not dead which can eternal lie,\n"
        "And with strange aeons even death may die.”"
    )
    split = source_text.index("The book")
    source = SourceDocument(
        text=source_text,
        units=[
            SourceUnit(
                id="source_000186",
                ordinal=1,
                start_offset=0,
                end_offset=split,
                text=source_text[:split],
            ),
            SourceUnit(
                id="source_000255",
                ordinal=2,
                start_offset=split,
                end_offset=len(source_text),
                text=source_text[split:],
            ),
        ],
        scenes=[
            SourceScene(
                id="scene_001",
                title="The ritual",
                first_unit_id="source_000186",
                last_unit_id="source_000255",
            )
        ],
    )
    brief = AdaptationBrief.model_validate(
        {
            **_approved_brief().model_dump(mode="json"),
            "protected_language": [protected],
            "content_sha256": "",
        }
    )
    base = _book_adaptation()
    first = base.beats[0].model_copy(
        update={
            "id": "beat_0011",
            "source_unit_ids": ("source_000186",),
            "lettering": (),
        }
    )
    second = base.beats[0].model_copy(
        update={
            "id": "beat_0017",
            "order": 2,
            "source_unit_ids": ("source_000255",),
            "lettering": (),
        }
    )
    candidate = base.model_copy(
        update={
            "source_sha256": source.source_sha256,
            "brief_revision": brief.revision,
            "brief_sha256": brief.content_sha256,
            "content_sha256": "",
            "beats": (first, second),
            "ledger": (
                AdaptationLedgerEntry(
                    source_unit_id="source_000186",
                    disposition="dialogue",
                    adapted_beat_ids=("beat_0011",),
                    preserved_function="ritual chant",
                ),
                AdaptationLedgerEntry(
                    source_unit_id="source_000255",
                    disposition="depicted",
                    adapted_beat_ids=("beat_0017",),
                    preserved_function="Necronomicon quote",
                ),
            ),
        }
    )

    canonical = _canonicalize_candidate_requirements(candidate, source, brief)
    result = validate_book_adaptation(source, brief, canonical)

    assert {failure.code for failure in result.invariant_failures}.isdisjoint(
        {"source_disposition_not_realized", "protected_language_missing"}
    )
    dialogue = canonical.beats[0].lettering[0]
    assert dialogue.kind == "caption"
    assert dialogue.delivery == "quoted_text"
    assert canonical.ledger[0].disposition == "caption"
    assert dialogue.source_unit_ids == ("source_000186",)
    assert dialogue.text == ("Ph’nglui mglw’nafh Cthulhu R’lyeh wgah’nagl fhtagn.")
    caption = canonical.beats[1].lettering[0]
    assert caption.kind == "caption"
    assert caption.source_unit_ids == ("source_000255",)
    assert caption.text == protected
    assert caption.delivery == "quoted_text"
    assert canonical.ledger[1].disposition == "caption"


def test_requirements_are_partitioned_to_the_shard_that_realizes_them() -> None:
    """The shard that contains a requirement's source should own it.

    Without this a shard sees every approved requirement and has to infer which
    fall in its own range — the guess that cost a repair round on shard 3.
    """
    source = _source_document()
    brief = _approved_brief()
    shards = (("source_000001",), ("source_000002",))

    owners = partition_requirements_by_shard(source, brief, shards)

    # "The witness sees the door open." overlaps unit 1 ("door", "open");
    # "The witness abandons the investigation." has no overlap and stays put.
    assert "essential_event_001" in owners[0]
    assert sum(len(ids) for ids in owners) == 2
    assert all(
        requirement_id.startswith(("essential_event_", "character_turn_"))
        for ids in owners
        for requirement_id in ids
    )


def test_partition_never_assigns_a_requirement_before_its_predecessor() -> None:
    source = _source_document()
    brief = _approved_brief().model_copy(
        update={
            "essential_events": (
                "The witness sees the door open.",
                "The witness flees into the rain.",
                # No lexical anchor at all — must not fall back to an earlier shard.
                "Something ineffable transpires offstage.",
            )
        }
    )
    shards = (("source_000001",), ("source_000002",))

    owners = partition_requirements_by_shard(source, brief, shards)

    placement = {
        requirement_id: index
        for index, ids in enumerate(owners)
        for requirement_id in ids
    }
    ordered = [placement[f"essential_event_{index:03d}"] for index in (1, 2, 3)]
    assert ordered == sorted(ordered), ordered


def test_character_turns_are_not_dragged_along_by_essential_events() -> None:
    """The two requirement kinds are independent ordered sequences.

    Sharing one monotonic floor pushed every character turn into whichever shard
    the last essential event reached.
    """
    source = _source_document()
    brief = _approved_brief().model_copy(
        update={
            "essential_events": (
                "The witness sees the door open.",
                "The witness flees into the rain.",
            ),
            "character_turns": ("The witness sees the door and doubts himself.",),
        }
    )
    shards = (("source_000001",), ("source_000002",))

    owners = partition_requirements_by_shard(source, brief, shards)

    placement = {
        requirement_id: index
        for index, ids in enumerate(owners)
        for requirement_id in ids
    }
    assert placement["essential_event_002"] == 1
    # The turn's own words point at shard 0 and must not inherit event 2's floor.
    assert placement["character_turn_001"] == 0


def test_partition_of_a_single_shard_owns_everything() -> None:
    source = _source_document()
    brief = _approved_brief()

    owners = partition_requirements_by_shard(
        source, brief, (("source_000001", "source_000002"),)
    )

    assert owners == (("essential_event_001", "character_turn_001"),)


def test_shard_prompt_states_which_requirements_it_owns() -> None:
    prompt = build_book_adaptation_prompt(
        _source_document(),
        _story_bible(),
        _approved_brief(),
        _book_adaptation().treatment,
        primary_source_unit_ids=("source_000002",),
        owned_requirement_ids=("character_turn_001",),
        shard_index=2,
        shard_count=2,
    )

    assert "owned_requirement_ids" in prompt
    assert "carry each one onto the beat that realizes it" in prompt
    # Judgment is preserved: a shard may still carry what its source realizes.
    assert "only if this shard's own source plainly realizes it" in prompt


def test_transition_story_function_requires_explicit_continuity_change() -> None:
    payload = _book_adaptation().model_dump()
    payload["content_sha256"] = ""
    payload["beats"][0]["narrative_function"] = "transition"
    payload["beats"][0]["story_functions"] = [
        *payload["beats"][0]["story_functions"],
        "transition",
    ]
    payload["beats"][0]["transitions"] = []
    candidate = BookAdaptation.model_validate(payload)

    result = validate_book_adaptation(
        _source_document(),
        _approved_brief(),
        candidate,
    )

    assert "incomplete_transition" in {
        failure.code for failure in result.invariant_failures
    }


def test_faithful_cthulhu_missing_reaction_or_aftermath_blocks_adaptation() -> None:
    fixture = json.loads(
        (
            Path(__file__).parent / "fixtures" / "cthulhu_adapt_missing_aftermath.json"
        ).read_text()
    )
    source = build_source_document(
        fixture["source_text"],
        [
            SourceSceneAnchor(
                id="scene_001",
                title=fixture["title"],
                opening_quote=fixture["opening_quote"],
            )
        ],
    )
    brief = AdaptationBrief.model_validate(
        {
            **_approved_brief().model_dump(),
            "protected_language": (),
            "transformation_level": "faithful",
            "essential_events": ("Johansen sees the titan rise.",),
            "character_turns": ("Johansen abandons any hope of an ordinary life.",),
            "content_sha256": "",
        }
    )
    candidate = BookAdaptation(
        revision=1,
        source_sha256=source.source_sha256,
        brief_revision=brief.revision,
        brief_sha256=brief.content_sha256,
        treatment=fixture["treatment"],
        beats=fixture["beats"],
        ledger=fixture["ledger"],
    )

    result = validate_book_adaptation(source, brief, candidate)

    assert "faithful_rushed_reaction_or_aftermath" in {
        failure.code for failure in result.invariant_failures
    }
    assert [issue.code for issue in result.editorial_issues] == [
        "rushed_reaction_or_aftermath"
    ]
    assert result.editorial_issues[0].source_unit_ids == ("source_000001",)
    assert result.editorial_issues[0].artifact_ids == ("beat_0001",)
    assert "score" not in result.editorial_issues[0].model_dump()


def test_ledger_dialogue_must_be_realized_by_source_linked_lettering() -> None:
    payload = _book_adaptation().model_dump()
    payload["content_sha256"] = ""
    payload["ledger"][0]["disposition"] = "dialogue"
    candidate = BookAdaptation.model_validate(payload)

    result = validate_book_adaptation(
        _source_document(),
        _approved_brief(),
        candidate,
    )

    failure = next(
        failure
        for failure in result.invariant_failures
        if failure.code == "source_disposition_not_realized"
    )
    assert failure.source_unit_ids == ("source_000001",)
    assert "dialogue" in failure.evidence[0]


def test_reaction_before_the_next_transition_is_sufficient_follow_through() -> None:
    fixture = json.loads(
        (
            Path(__file__).parent / "fixtures" / "cthulhu_adapt_missing_aftermath.json"
        ).read_text()
    )
    source = build_source_document(
        fixture["source_text"],
        [
            SourceSceneAnchor(
                id="scene_001",
                title=fixture["title"],
                opening_quote=fixture["opening_quote"],
            )
        ],
    )
    brief = AdaptationBrief.model_validate(
        {
            **_approved_brief().model_dump(),
            "protected_language": (),
            "essential_events": ("Johansen sees the titan rise.",),
            "character_turns": ("Johansen abandons any hope of an ordinary life.",),
            "content_sha256": "",
        }
    )
    beats = fixture["beats"]
    beats[1]["story_functions"] = [
        *beats[1]["story_functions"],
        "reaction",
    ]
    candidate = BookAdaptation(
        revision=1,
        source_sha256=source.source_sha256,
        brief_revision=brief.revision,
        brief_sha256=brief.content_sha256,
        treatment=fixture["treatment"],
        beats=beats,
        ledger=fixture["ledger"],
    )

    result = validate_book_adaptation(source, brief, candidate)

    assert "rushed_reaction_or_aftermath" not in {
        issue.code for issue in result.editorial_issues
    }


def test_reaction_on_the_transition_beat_is_still_follow_through() -> None:
    fixture = json.loads(
        (
            Path(__file__).parent / "fixtures" / "cthulhu_adapt_missing_aftermath.json"
        ).read_text()
    )
    source = build_source_document(
        fixture["source_text"],
        [
            SourceSceneAnchor(
                id="scene_001",
                title=fixture["title"],
                opening_quote=fixture["opening_quote"],
            )
        ],
    )
    brief = AdaptationBrief.model_validate(
        {
            **_approved_brief().model_dump(),
            "protected_language": (),
            "essential_events": ("Johansen sees the titan rise.",),
            "character_turns": ("Johansen abandons any hope of an ordinary life.",),
            "content_sha256": "",
        }
    )
    beats = fixture["beats"]
    beats[2]["story_functions"] = [
        *beats[2]["story_functions"],
        "reaction",
    ]
    candidate = BookAdaptation(
        revision=1,
        source_sha256=source.source_sha256,
        brief_revision=brief.revision,
        brief_sha256=brief.content_sha256,
        treatment=fixture["treatment"],
        beats=beats,
        ledger=fixture["ledger"],
    )

    result = validate_book_adaptation(source, brief, candidate)

    assert "rushed_reaction_or_aftermath" not in {
        issue.code for issue in result.editorial_issues
    }


def _omission_source() -> SourceDocument:
    sentences = (
        "I saw the door open. ",
        "The hall was cold. ",
        "A clock ticked somewhere. ",
        "Dust hung in the air. ",
        "I fled into the rain.",
    )
    text = "".join(sentences)
    units = []
    start = 0
    for ordinal, sentence in enumerate(sentences, start=1):
        units.append(
            SourceUnit(
                id=f"source_{ordinal:06d}",
                ordinal=ordinal,
                start_offset=start,
                end_offset=start + len(sentence),
                text=sentence,
            )
        )
        start += len(sentence)
    return SourceDocument(
        text=text,
        units=units,
        scenes=[
            SourceScene(
                id="scene_001",
                title="The door",
                first_unit_id="source_000001",
                last_unit_id="source_000005",
            )
        ],
    )


def _omission_candidate(omitted: tuple[str, ...]) -> BookAdaptation:
    source = _omission_source()
    payload = _book_adaptation().model_dump()
    payload["content_sha256"] = ""
    payload["source_sha256"] = source.source_sha256
    kept = [unit.id for unit in source.units if unit.id not in omitted]
    payload["beats"][0]["source_unit_ids"] = kept
    payload["beats"][0]["lettering"] = [
        item
        for item in payload["beats"][0]["lettering"]
        if all(unit_id in kept for unit_id in item["source_unit_ids"])
    ]
    payload["ledger"] = [
        {
            "source_unit_id": unit.id,
            "disposition": "intentionally_omitted" if unit.id in omitted else "caption",
            "adapted_beat_ids": [] if unit.id in omitted else ["beat_0001"],
            "reason": "Already carried by the surrounding art."
            if unit.id in omitted
            else None,
            "preserved_function": "The prose detail is intentionally removed."
            if unit.id in omitted
            else "The testimony remains explicit.",
        }
        for unit in source.units
    ]
    return BookAdaptation.model_validate(payload)


def _omission_issues(omitted: tuple[str, ...]) -> list:
    return [
        issue
        for issue in validate_book_adaptation(
            _omission_source(),
            _approved_brief(),
            _omission_candidate(omitted),
        ).editorial_issues
        if issue.code == "questionable_omission"
    ]


def test_a_reworded_requirement_is_covered_not_missing() -> None:
    # The Brief, the treatment, and the beat citation are three model outputs.
    # Requiring byte-identical echoes made a blocking failure out of ordinary
    # rewording, with no repair available to the user.
    payload = _book_adaptation().model_dump()
    payload["content_sha256"] = ""
    payload["treatment"]["essential_events"] = ["the witness sees the door open"]

    result = validate_book_adaptation(
        _source_document(),
        _approved_brief(),
        BookAdaptation.model_validate(payload),
    )

    assert result.invariant_failures == ()


def test_a_genuinely_uncovered_requirement_still_blocks() -> None:
    payload = _book_adaptation().model_dump()
    payload["content_sha256"] = ""
    payload["beats"][0]["brief_requirement_ids"] = ["character_turn_001"]

    result = validate_book_adaptation(
        _source_document(),
        _approved_brief(),
        BookAdaptation.model_validate(payload),
    )

    assert [failure.code for failure in result.invariant_failures] == [
        "missing_essential_event"
    ]


def test_protected_language_survives_typographic_variance() -> None:
    payload = _book_adaptation().model_dump()
    payload["content_sha256"] = ""
    payload["beats"][0]["lettering"][0]["text"] = "I saw the door\nopen."
    brief = _approved_brief().model_dump()
    brief["content_sha256"] = ""
    brief["protected_language"] = ["I saw the door open."]
    approved = AdaptationBrief.model_validate(brief)
    payload["brief_sha256"] = approved.content_sha256

    result = validate_book_adaptation(
        _source_document(),
        approved,
        BookAdaptation.model_validate(payload),
    )

    assert [
        failure.code
        for failure in result.invariant_failures
        if failure.code == "protected_language_missing"
    ] == []


def test_paraphrased_protected_language_still_blocks() -> None:
    payload = _book_adaptation().model_dump()
    payload["content_sha256"] = ""
    payload["beats"][0]["lettering"][0]["text"] = "I watched the door swing wide."

    result = validate_book_adaptation(
        _source_document(),
        _approved_brief(),
        BookAdaptation.model_validate(payload),
    )

    assert "protected_language_missing" in [
        failure.code for failure in result.invariant_failures
    ]


def test_an_isolated_ordinary_omission_is_not_an_editorial_exception() -> None:
    # A faithful adaptation omits hundreds of ordinary source units. Reporting
    # each one as an exception would bury the omissions that matter.
    assert _omission_issues(("source_000003",)) == []


def test_omitting_protected_language_is_reviewable_with_cited_evidence() -> None:
    issues = _omission_issues(("source_000001",))

    assert [issue.source_unit_ids for issue in issues] == [("source_000001",)]
    assert issues[0].evidence[0] == (
        "Protected phrase in the omitted unit: 'I saw the door open.'"
    )


def test_a_continuous_omitted_stretch_is_reviewable_as_one_exception() -> None:
    issues = _omission_issues(("source_000002", "source_000003", "source_000004"))

    assert len(issues) == 1
    assert issues[0].source_unit_ids == (
        "source_000002",
        "source_000003",
        "source_000004",
    )
    assert issues[0].evidence == (
        "3 consecutive source units were omitted, source_000002 through source_000004.",
    )


@pytest.mark.parametrize(
    ("missing_requirement", "code"),
    [
        ("The witness sees the door open.", "missing_essential_event"),
        (
            "The witness abandons the investigation.",
            "missing_character_turn",
        ),
    ],
)
def test_essential_events_and_character_turns_require_explicit_beat_coverage(
    missing_requirement: str,
    code: str,
) -> None:
    payload = _book_adaptation().model_dump()
    payload["content_sha256"] = ""
    missing_id = (
        "essential_event_001"
        if code == "missing_essential_event"
        else "character_turn_001"
    )
    payload["beats"][0]["brief_requirement_ids"] = [
        requirement_id
        for requirement_id in payload["beats"][0]["brief_requirement_ids"]
        if requirement_id != missing_id
    ]
    candidate = BookAdaptation.model_validate(payload)

    result = validate_book_adaptation(
        _source_document(),
        _approved_brief(),
        candidate,
    )

    assert code in {failure.code for failure in result.invariant_failures}


def test_global_treatment_must_carry_approved_essential_events() -> None:
    payload = _book_adaptation().model_dump()
    payload["content_sha256"] = ""
    payload["treatment"]["essential_events"] = []
    payload["treatment"]["essential_event_ids"] = []
    candidate = BookAdaptation.model_validate(payload)

    result = validate_book_adaptation(
        _source_document(),
        _approved_brief(),
        candidate,
    )

    assert "missing_essential_event" in {
        failure.code for failure in result.invariant_failures
    }


def test_book_prompt_owns_complete_wording_ledger_and_prohibits_page_planning() -> None:
    prompt = build_book_adaptation_prompt(
        _source_document(),
        _story_bible(),
        _approved_brief(),
        _book_adaptation().treatment,
    )

    assert "complete, publishable dialogue, thought, caption, and SFX wording" in prompt
    assert "code derives depicted, dialogue, thought, and caption" in prompt
    assert "ledger_exceptions" in prompt
    assert "Preserve every protected-language string verbatim" in prompt
    assert '"I saw the door open."' in prompt
    assert "Do not allocate pages, panels, layouts, or geometry." in prompt


def test_producer_writes_one_book_artifact_and_records_model_usage(
    tmp_path: Path,
) -> None:
    source = _source_document()
    brief = _approved_brief()
    expected = _book_adaptation()
    responses = [
        expected.treatment.model_dump(mode="json"),
        _blueprint_response(expected.beats, include_legacy_ledger=True),
        _lettering_response(expected.beats),
    ]
    calls: list[dict] = []

    async def generate(**request):
        calls.append(request)
        return ApiResult(
            value=responses[len(calls) - 1],
            usage=UsageRecord(
                provider="mock",
                model="gpt-4o-mini",
                operation="text",
                input_tokens=100,
                output_tokens=50,
                cost_usd=0.001,
                cost_source="mock",
            ),
        )

    state = PipelineState(
        project_name="adapt-test",
        novel_path="novel.txt",
        created_at=datetime.now(timezone.utc),
    )
    runtime = StageRuntime("adapt", state, tmp_path)
    artifacts = TargetArtifacts(tmp_path)

    produced = asyncio.run(
        produce_book_adaptation(
            source,
            _story_bible(),
            brief,
            artifacts=artifacts,
            ctx=runtime,
            model="gpt-4o-mini",
            generate=generate,
        )
    )

    assert produced == artifacts.read_adaptation()
    assert produced.beats == expected.beats
    assert [entry.source_unit_id for entry in produced.ledger] == [
        "source_000001",
        "source_000002",
    ]
    # One adaptation authority, plus Adapt's own derived verdict on it. No
    # per-scene screenplay outputs of any kind.
    assert sorted(path.name for path in (tmp_path / "adapt").iterdir()) == [
        "book.json",
        "validation.json",
    ]
    assert (tmp_path / ".checkpoints" / "adapt" / "treatment.json").exists()
    assert artifacts.read_validation("adapt").invariant_failures == ()
    assert [call["feature"] for call in calls] == [
        "adapt.narrative_treatment",
        "adapt.blueprint",
        "adapt.lettering",
    ]
    assert all(call["json_schema"]["type"] == "object" for call in calls)
    assert "ledger" not in calls[1]["json_schema"]["properties"]
    assert state.stages["adapt"].items_done == 3
    assert len(state.stages["adapt"].usage_log) == 3
    assert state.stages["adapt"].cost_usd > 0
    assert state.stages["adapt"].cost_usd > 0
    assert state.stages["adapt"].estimated_cost_usd > 0


def test_restart_reuses_paid_treatment_and_blueprint_checkpoints(
    tmp_path: Path,
) -> None:
    expected = _book_adaptation()
    first_calls: list[str] = []

    async def interrupted_generate(**request):
        first_calls.append(request["feature"])
        if request["feature"] == "adapt.narrative_treatment":
            value = expected.treatment.model_dump(mode="json")
        elif request["feature"] == "adapt.blueprint":
            value = _blueprint_response(expected.beats)
        else:
            raise RuntimeError("connection lost during lettering")
        return ApiResult(value=value, usage=None)

    artifacts = TargetArtifacts(tmp_path)
    with pytest.raises(RuntimeError):
        asyncio.run(
            produce_book_adaptation(
                _source_document(),
                _story_bible(),
                _approved_brief(),
                artifacts=artifacts,
                ctx=StageRuntime(
                    "adapt",
                    PipelineState(
                        project_name="checkpoint-test",
                        novel_path="novel.txt",
                        created_at=datetime.now(timezone.utc),
                    ),
                    tmp_path,
                ),
                model="gpt-4o-mini",
                generate=interrupted_generate,
            )
        )

    resumed_calls: list[str] = []

    async def resumed_generate(**request):
        resumed_calls.append(request["feature"])
        assert request["feature"] == "adapt.lettering"
        return ApiResult(value=_lettering_response(expected.beats), usage=None)

    produced = asyncio.run(
        produce_book_adaptation(
            _source_document(),
            _story_bible(),
            _approved_brief(),
            artifacts=artifacts,
            ctx=StageRuntime(
                "adapt",
                PipelineState(
                    project_name="checkpoint-test",
                    novel_path="novel.txt",
                    created_at=datetime.now(timezone.utc),
                ),
                tmp_path,
            ),
            model="gpt-4o-mini",
            generate=resumed_generate,
        )
    )

    assert first_calls == [
        "adapt.narrative_treatment",
        "adapt.blueprint",
        "adapt.lettering",
    ]
    assert resumed_calls == ["adapt.lettering"]
    assert produced.beats == expected.beats


def test_producer_canonicalizes_approved_requirement_metadata(
    tmp_path: Path,
) -> None:
    expected = _book_adaptation()
    treatment = expected.treatment.model_copy(
        update={
            "essential_event_ids": (),
            "character_turns": (),
            "character_turn_ids": (),
        }
    )
    beat = expected.beats[0].model_copy(
        update={
            "brief_requirement_ids": ("character_turn_001", "essential_event_001"),
        }
    )
    calls: list[dict] = []

    async def generate(**request):
        calls.append(request)
        if request["feature"] == "adapt.narrative_treatment":
            value = treatment.model_dump(mode="json")
        elif request["feature"] == "adapt.blueprint":
            value = _blueprint_response([beat])
        else:
            value = _lettering_response([beat])
        return ApiResult(value=value, usage=None)

    produced = asyncio.run(
        produce_book_adaptation(
            _source_document(),
            _story_bible(),
            _approved_brief(),
            artifacts=TargetArtifacts(tmp_path),
            ctx=StageRuntime(
                "adapt",
                PipelineState(
                    project_name="canonical-requirements-test",
                    novel_path="novel.txt",
                    created_at=datetime.now(timezone.utc),
                ),
                tmp_path,
            ),
            model="gpt-5.6-terra",
            generate=generate,
        )
    )

    assert len(calls) == 3
    assert produced.treatment.essential_event_ids == ("essential_event_001",)
    assert produced.treatment.character_turn_ids == ("character_turn_001",)
    assert produced.beats[0].brief_requirement_ids == (
        "character_turn_001",
        "essential_event_001",
    )


def test_retry_recovers_a_paid_candidate_without_another_model_call(
    tmp_path: Path,
) -> None:
    expected = _book_adaptation()
    treatment = expected.treatment.model_copy(
        update={
            "essential_event_ids": (),
            "character_turns": (),
            "character_turn_ids": (),
        }
    )
    beat = expected.beats[0].model_copy(
        update={"brief_requirement_ids": ("character_turn_001", "essential_event_001")}
    )
    candidate = BookAdaptation.model_validate(
        {
            **expected.model_dump(mode="json"),
            "content_sha256": "",
            "treatment": treatment.model_dump(mode="json"),
            "beats": [beat.model_dump(mode="json")],
        }
    )
    artifacts = TargetArtifacts(tmp_path)
    artifacts.write_failed_adaptation_candidate(candidate)

    async def generate(**request):
        raise AssertionError("a recoverable paid candidate must not call the model")

    produced = asyncio.run(
        produce_book_adaptation(
            _source_document(),
            _story_bible(),
            _approved_brief(),
            artifacts=artifacts,
            ctx=StageRuntime(
                "adapt",
                PipelineState(
                    project_name="recover-paid-candidate-test",
                    novel_path="novel.txt",
                    created_at=datetime.now(timezone.utc),
                ),
                tmp_path,
            ),
            model="gpt-5.6-terra",
            generate=generate,
        )
    )

    assert produced == artifacts.read_adaptation()
    assert produced.treatment.character_turn_ids == ("character_turn_001",)
    assert not artifacts.failed_adaptation_candidate_path.exists()


def test_large_book_adaptation_is_written_in_bounded_internal_shards(
    tmp_path: Path,
) -> None:
    sentences = [f"Sentence {index} records event {index}. " for index in range(1, 182)]
    text = "".join(sentences).rstrip()
    units: list[SourceUnit] = []
    offset = 0
    for index, sentence in enumerate(sentences, 1):
        unit_text = sentence if index < len(sentences) else sentence.rstrip()
        units.append(
            SourceUnit(
                id=f"source_{index:06d}",
                ordinal=index,
                start_offset=offset,
                end_offset=offset + len(unit_text),
                text=unit_text,
            )
        )
        offset += len(unit_text)
    source = SourceDocument(
        text=text,
        units=units,
        scenes=[
            SourceScene(
                id="scene_001",
                title="First movement",
                first_unit_id="source_000001",
                last_unit_id="source_000060",
            ),
            SourceScene(
                id="scene_002",
                title="Second movement",
                first_unit_id="source_000061",
                last_unit_id="source_000181",
            ),
        ],
    )
    brief_payload = _approved_brief().model_dump()
    brief_payload.update({"content_sha256": "", "protected_language": []})
    brief = AdaptationBrief.model_validate(brief_payload)
    treatment = _book_adaptation().treatment
    calls: list[dict] = []
    active_book_calls = 0
    max_active_book_calls = 0
    shard_attempts: dict[str, int] = {}

    async def generate(**request):
        nonlocal active_book_calls, max_active_book_calls
        calls.append(request)
        if request["feature"] == "adapt.narrative_treatment":
            return ApiResult(value=treatment.model_dump(mode="json"), usage=None)
        if request["feature"] == "adapt.lettering":
            beat_ids = list(
                dict.fromkeys(
                    re.findall(r'"id":"(beat_\d{4})"', request["user_content"])
                )
            )
            return ApiResult(
                value={
                    "beats": [
                        {"beat_id": beat_id, "lettering": []}
                        for beat_id in beat_ids
                    ]
                },
                usage=None,
            )
        active_book_calls += 1
        max_active_book_calls = max(max_active_book_calls, active_book_calls)
        await asyncio.sleep(0.01)
        source_ids = list(
            dict.fromkeys(re.findall(r'"id":"(source_\d{6})"', request["user_content"]))
        )
        shard_attempts[source_ids[0]] = shard_attempts.get(source_ids[0], 0) + 1
        carries_requirements = (
            source_ids[0] == "source_000001" and shard_attempts[source_ids[0]] > 1
        )
        result = ApiResult(
            value={
                "beats": [
                    {
                        "id": "beat_0001",
                        "order": 1,
                        "summary": f"Adapt {source_ids[0]} through {source_ids[-1]}.",
                        "narrative_function": "prolongation",
                        "story_functions": ["causal_event"],
                        "brief_requirement_ids": (
                            ["essential_event_001", "character_turn_001"]
                            if carries_requirements
                            else []
                        ),
                        "source_unit_ids": source_ids,
                        "lettering": [],
                        "transitions": [],
                        "appearance_changes": [],
                    }
                ],
                    "ledger_exceptions": [],
                },
            usage=None,
        )
        active_book_calls -= 1
        return result

    produced = asyncio.run(
        produce_book_adaptation(
            source,
            _story_bible(),
            brief,
            artifacts=TargetArtifacts(tmp_path),
            ctx=StageRuntime(
                "adapt",
                PipelineState(
                    project_name="large-adapt-test",
                    novel_path="novel.txt",
                    created_at=datetime.now(timezone.utc),
                ),
                tmp_path,
            ),
            model="gpt-4o-mini",
            generate=generate,
        )
    )

    book_calls = [call for call in calls if call["feature"] == "adapt.blueprint"]
    assert len(book_calls) == 3
    assert all(
        len(set(re.findall(r'"id":"source_\d{6}"', call["user_content"]))) <= 180
        for call in book_calls
    )
    assert [entry.source_unit_id for entry in produced.ledger] == [
        unit.id for unit in source.units
    ]
    assert [beat.order for beat in produced.beats] == [1, 2]
    assert len({beat.id for beat in produced.beats}) == 2
    assert max_active_book_calls == 2
    assert all("ledger" not in call["json_schema"]["properties"] for call in book_calls)
    assert shard_attempts == {
        "source_000001": 2,
        "source_000181": 1,
    }
    assert "VALIDATION ERRORS" in book_calls[-1]["user_content"]


def test_adaptation_shards_use_model_output_budget_and_fit_cthulhu_in_three() -> None:
    sentences = [
        f"Event {index} "
        + ("records source-faithful dramatic detail " * 3)
        + "with exact context. "
        for index in range(1, 459)
    ]
    sentences[-1] = sentences[-1].rstrip()
    text = "".join(sentences)
    units: list[SourceUnit] = []
    offset = 0
    for index, sentence in enumerate(sentences, 1):
        units.append(
            SourceUnit(
                id=f"source_{index:06d}",
                ordinal=index,
                start_offset=offset,
                end_offset=offset + len(sentence),
                text=sentence,
            )
        )
        offset += len(sentence)
    source = SourceDocument(
        text=text,
        units=units,
        scenes=[
            SourceScene(
                id="scene_001",
                title="Opening",
                first_unit_id="source_000001",
                last_unit_id="source_000153",
            ),
            SourceScene(
                id="scene_002",
                title="Investigation",
                first_unit_id="source_000154",
                last_unit_id="source_000306",
            ),
            SourceScene(
                id="scene_003",
                title="Revelation",
                first_unit_id="source_000307",
                last_unit_id="source_000458",
            ),
        ],
    )

    shards = _adaptation_shards(source, model="gpt-5.6-terra")

    assert [len(shard) for shard in shards] == [180, 180, 98]
    assert max(map(len, shards)) <= 180
    assert tuple(source_id for shard in shards for source_id in shard) == tuple(
        unit.id for unit in source.units
    )


def test_a_blocked_adaptation_gets_one_repair_pass_with_its_failures(
    tmp_path: Path,
) -> None:
    source = _source_document()
    brief = _approved_brief()
    expected = _book_adaptation()
    broken = {
        "beats": [
            {
                **expected.beats[0].model_dump(mode="json"),

                "brief_requirement_ids": [],
            }
        ],
        "ledger": [entry.model_dump(mode="json") for entry in expected.ledger],
    }
    repaired = {
        "beats": [beat.model_dump(mode="json") for beat in expected.beats],
        "ledger": [entry.model_dump(mode="json") for entry in expected.ledger],
    }
    responses = [
        expected.treatment.model_dump(mode="json"),
        broken,
        repaired,
        _lettering_response(expected.beats),
    ]
    calls: list[dict] = []

    async def generate(**request):
        calls.append(request)
        return ApiResult(
            value=responses[len(calls) - 1],
            usage=UsageRecord(
                provider="mock",
                model="gpt-4o-mini",
                operation="text",
                input_tokens=10,
                output_tokens=5,
                cost_usd=0.001,
                cost_source="mock",
            ),
        )

    artifacts = TargetArtifacts(tmp_path)
    produced = asyncio.run(
        produce_book_adaptation(
            source,
            _story_bible(),
            brief,
            artifacts=artifacts,
            ctx=StageRuntime(
                "adapt",
                PipelineState(
                    project_name="adapt-test",
                    novel_path="novel.txt",
                    created_at=datetime.now(timezone.utc),
                ),
                tmp_path,
            ),
            model="gpt-4o-mini",
            generate=generate,
        )
    )

    assert produced.beats == expected.beats
    assert len(calls) == 4
    # Structural omissions are repaired before the expensive prose pass.
    assert "missing owned requirement IDs" in calls[2]["user_content"]
    assert "quality_tier" not in calls[2]
    assert calls[3]["feature"] == "adapt.lettering"
    assert artifacts.read_validation("adapt").attempts == 1


def test_a_failed_adaptation_preserves_the_last_candidate(
    tmp_path: Path,
) -> None:
    expected = _book_adaptation()
    brief = AdaptationBrief.model_validate(
        {
            **_approved_brief().model_dump(mode="json"),
            "transformation_level": "faithful",
            "content_sha256": "",
        }
    )
    reveal = expected.beats[0].model_copy(
        update={
            "source_unit_ids": ("source_000001",),
            "story_functions": ("reveal",),

            "brief_requirement_ids": ("essential_event_001",),
            "lettering": (expected.beats[0].lettering[0],),
        }
    )
    transition = expected.beats[0].model_copy(
        update={
            "id": "beat_0002",
            "order": 2,
            "summary": "The witness abandons the investigation.",
            "narrative_function": "transition",
            "source_unit_ids": ("source_000002",),
            "story_functions": ("transition", "character_turn"),

            "brief_requirement_ids": ("character_turn_001",),
            "transitions": (
                ContinuityTransition(
                    dimension="place",
                    scope_id="thread_witness",
                    from_state="inside the house",
                    to_state="outside in the rain",
                    description="The witness flees the house.",
                ),
            ),
            "lettering": (
                expected.beats[0].lettering[1].model_copy(
                    update={"id": "lettering_0002"}
                ),
            ),
        }
    )
    broken = {
        "beats": [
            reveal.model_dump(mode="json"),
            transition.model_dump(mode="json"),
        ],
        "ledger_exceptions": [],
    }
    responses = [
        expected.treatment.model_dump(mode="json"),
        _blueprint_response([reveal, transition]),
        _lettering_response([reveal, transition]),
        broken,
    ]

    async def generate(**request):
        return ApiResult(value=responses.pop(0), usage=None)

    artifacts = TargetArtifacts(tmp_path)
    with pytest.raises(AdaptationInvariantError):
        asyncio.run(
            produce_book_adaptation(
                _source_document(),
                _story_bible(),
                brief,
                artifacts=artifacts,
                ctx=StageRuntime(
                    "adapt",
                    PipelineState(
                        project_name="adapt-test",
                        novel_path="novel.txt",
                        created_at=datetime.now(timezone.utc),
                    ),
                    tmp_path,
                ),
                model="gpt-4o-mini",
                generate=generate,
            )
        )

    resumed_features: list[str] = []

    async def still_invalid(**request):
        resumed_features.append(request["feature"])
        return ApiResult(value=broken, usage=None)

    for _ in range(2):
        with pytest.raises(AdaptationInvariantError):
            asyncio.run(produce_book_adaptation(
                _source_document(), _story_bible(), brief,
                artifacts=artifacts,
                ctx=StageRuntime("adapt", PipelineState(
                    project_name="adapt-test", novel_path="novel.txt",
                    created_at=datetime.now(timezone.utc),
                ), tmp_path),
                model="gpt-4o-mini", generate=still_invalid,
            ))
    # Each explicit retry gets one fresh repair, without repaying the initial
    # treatment, blueprint, or lettering even when repair output is unchanged.
    assert resumed_features == ["adapt.book", "adapt.book"]

    candidate = artifacts.read_failed_adaptation_candidate()
    assert candidate.beats[0].story_functions == ("reveal",)
    assert not artifacts.adaptation_path.exists()


@pytest.mark.parametrize(
    ("change", "code"),
    [
        ({"source_sha256": "a" * 64}, "source_authority_mismatch"),
        ({"brief_revision": 99}, "brief_authority_mismatch"),
        ({"brief_sha256": "b" * 64}, "brief_authority_mismatch"),
    ],
)
def test_adaptation_must_match_its_canonical_input_authority(
    change: dict,
    code: str,
) -> None:
    payload = _book_adaptation().model_dump()
    payload.update(change)
    payload["content_sha256"] = ""
    candidate = BookAdaptation.model_validate(payload)

    result = validate_book_adaptation(
        _source_document(),
        _approved_brief(),
        candidate,
    )

    assert code in {failure.code for failure in result.invariant_failures}


def test_adapted_beat_provenance_must_resolve_to_source_units() -> None:
    payload = _book_adaptation().model_dump()
    payload["content_sha256"] = ""
    payload["beats"][0]["source_unit_ids"] = ["source_999999"]
    candidate = BookAdaptation.model_validate(payload)

    result = validate_book_adaptation(
        _source_document(),
        _approved_brief(),
        candidate,
    )

    assert "unknown_source_provenance" in {
        failure.code for failure in result.invariant_failures
    }


def test_a_schema_slip_is_repaired_instead_of_failing_the_stage(
    tmp_path: Path,
) -> None:
    # A model returning one string where a list belongs is a formatting mistake,
    # not a contract violation the user can act on.
    expected = _book_adaptation()
    beat = expected.beats[0].model_dump(mode="json")
    responses = [
        expected.treatment.model_dump(mode="json"),
        {
            "beats": [{**beat, "story_functions": "causal_event"}],
            "ledger": [entry.model_dump(mode="json") for entry in expected.ledger],
        },
        {
            "beats": [beat],
            "ledger": [entry.model_dump(mode="json") for entry in expected.ledger],
        },
        _lettering_response(expected.beats),
    ]
    calls: list[dict] = []

    async def generate(**request):
        calls.append(request)
        return ApiResult(
            value=responses[len(calls) - 1],
            usage=UsageRecord(
                provider="mock",
                model="gpt-4o-mini",
                operation="text",
                input_tokens=10,
                output_tokens=5,
                cost_usd=0.001,
                cost_source="mock",
            ),
        )

    produced = asyncio.run(
        produce_book_adaptation(
            _source_document(),
            _story_bible(),
            _approved_brief(),
            artifacts=TargetArtifacts(tmp_path),
            ctx=StageRuntime(
                "adapt",
                PipelineState(
                    project_name="adapt-test",
                    novel_path="novel.txt",
                    created_at=datetime.now(timezone.utc),
                ),
                tmp_path,
            ),
            model="gpt-4o-mini",
            generate=generate,
        )
    )

    assert produced.beats == expected.beats
    assert len(calls) == 4
    assert "VALIDATION ERRORS" in calls[2]["user_content"]
    assert "story_functions" in calls[2]["user_content"]


def test_a_repaired_attempt_is_billed_without_inflating_progress(
    tmp_path: Path,
) -> None:
    # The failed attempt was paid for, so its usage is in the audit log and its
    # cost is in the stage total, but only the two real steps count as done.
    expected = _book_adaptation()
    broken = {
        "beats": [
            {
                **expected.beats[0].model_dump(mode="json"),

                "brief_requirement_ids": [],
            }
        ],
        "ledger": [entry.model_dump(mode="json") for entry in expected.ledger],
    }
    repaired = {
        "beats": [beat.model_dump(mode="json") for beat in expected.beats],
        "ledger": [entry.model_dump(mode="json") for entry in expected.ledger],
    }
    responses = [
        expected.treatment.model_dump(mode="json"),
        broken,
        repaired,
        _lettering_response(expected.beats),
    ]
    calls: list[dict] = []

    async def generate(**request):
        calls.append(request)
        return ApiResult(
            value=responses[len(calls) - 1],
            usage=UsageRecord(
                provider="mock",
                model="gpt-4o-mini",
                operation="text",
                input_tokens=10,
                output_tokens=5,
                cost_usd=0.001,
                cost_source="provider",
            ),
        )

    state = PipelineState(
        project_name="adapt-test",
        novel_path="novel.txt",
        created_at=datetime.now(timezone.utc),
    )
    asyncio.run(
        produce_book_adaptation(
            _source_document(),
            _story_bible(),
            _approved_brief(),
            artifacts=TargetArtifacts(tmp_path),
            ctx=StageRuntime("adapt", state, tmp_path),
            model="gpt-4o-mini",
            generate=generate,
        )
    )

    assert len(state.stages["adapt"].usage_log) == 4
    assert state.stages["adapt"].items_done == 3
    assert state.stages["adapt"].cost_usd == pytest.approx(0.004)


def test_treatment_prompt_does_not_duplicate_the_strict_response_schema() -> None:
    prompt = build_narrative_treatment_prompt(
        _source_document(),
        _story_bible(),
        _approved_brief(),
    )

    assert "scene_obligations" in prompt
    assert "<NarrativeTreatment>" not in prompt
    assert '"causal_spine"' not in prompt


def test_book_prompt_uses_compact_ledger_exceptions_under_strict_schema() -> None:
    prompt = build_book_adaptation_prompt(
        _source_document(),
        _story_bible(),
        _approved_brief(),
        _book_adaptation().treatment,
    )

    assert "ledger=[]" in prompt
    assert "ledger_exceptions" in prompt
    assert "<AdaptedBeat>" not in prompt
    assert "<AdaptationLedgerEntry>" not in prompt


def test_compact_ledger_exceptions_expand_into_canonical_source_accounting() -> None:
    expected = _book_adaptation()
    draft = _BookDraft(
        beats=expected.beats,
        ledger_exceptions=[
            _LedgerException(
                source_unit_ids=["source_000002"],
                disposition="compressed_into",
                adapted_beat_ids=["beat_0001"],
                reason="The flight is combined with the discovery.",
                preserved_function="The witness still flees immediately.",
            )
        ],
    )

    materialized = _materialize_draft_ledger(
        draft,
        ("source_000001", "source_000002"),
    )

    assert [entry.source_unit_id for entry in materialized.ledger] == [
        "source_000001",
        "source_000002",
    ]
    assert materialized.ledger[0].disposition == "caption"
    assert materialized.ledger[1].disposition == "compressed_into"
    assert materialized.ledger_exceptions == ()


def test_sfx_lettering_is_depicted_in_the_source_ledger() -> None:
    """SFX is publishable lettering, but not a canonical ledger disposition."""

    beat = _book_adaptation().beats[0].model_copy(
        update={
            "source_unit_ids": ("source_000001",),
            "lettering": (
                LetteringItem(
                    id="lettering_0001",
                    kind="sfx",
                    text="BANG",
                    delivery="display",
                    source_unit_ids=("source_000001",),
                ),
            ),
        }
    )

    materialized = _materialize_draft_ledger(
        _BookDraft(beats=(beat,)),
        ("source_000001",),
    )

    assert materialized.ledger[0].disposition == "depicted"
    assert materialized.ledger[0].adapted_beat_ids == ("beat_0001",)


def test_blueprint_rejects_an_unexplained_transition_before_lettering() -> None:
    beat = _book_adaptation().beats[0].model_copy(
        update={
            "narrative_function": "transition",
            "story_functions": ("transition",),
            "transitions": (),
        }
    )
    blueprint = _BlueprintDraft.model_validate(
        _blueprint_response([beat])
    )

    with pytest.raises(
        ValueError,
        match="transition beats missing continuity transitions",
    ):
        _validate_blueprint_scope(
            blueprint,
            source_unit_ids=("source_000001", "source_000002"),
            owned_requirement_ids=(
                "essential_event_001",
                "character_turn_001",
            ),
        )


def test_locked_lettering_rejects_onscreen_speech_without_entity_id() -> None:
    lettering = _LetteringDraft.model_validate(
        {
            "beats": [
                {
                    "beat_id": "beat_0001",
                    "lettering": [
                        {
                            "id": "lettering_0001",
                            "kind": "dialogue",
                            "text": "The stars are right.",
                            "speaker": "Prisoner",
                            "delivery": "onscreen",
                            "source_unit_ids": ["source_000001"],
                        }
                    ],
                }
            ]
        }
    )

    with pytest.raises(
        ValueError,
        match="On-screen lettering requires speaker_entity_id",
    ):
        _validate_locked_lettering(
            lettering,
            known_speaker_ids={"char_006"},
        )


def test_adaptation_repair_retries_invalid_onscreen_lettering(
    tmp_path: Path,
) -> None:
    expected = _book_adaptation()
    invalid_item = expected.beats[0].lettering[0].model_copy(
        update={
            "kind": "dialogue",
            "speaker": "Gregor Samsa",
            "speaker_entity_id": None,
            "delivery": "onscreen",
        }
    )
    valid_item = invalid_item.model_copy(update={"speaker_entity_id": "char_001"})
    responses = [
        _BookDraft(
            beats=(
                expected.beats[0].model_copy(
                    update={"lettering": (invalid_item,)}
                ),
            ),
        ).model_dump(mode="json"),
        _BookDraft(
            beats=(
                expected.beats[0].model_copy(update={"lettering": (valid_item,)}),
            ),
        ).model_dump(mode="json"),
    ]
    calls: list[dict] = []

    async def generate(**request):
        calls.append(request)
        return ApiResult(value=responses.pop(0), usage=None)

    draft = asyncio.run(
        _generate_book_draft(
            prompt="repair prompt",
            generate=generate,
            ctx=StageRuntime(
                "adapt",
                PipelineState(
                    project_name="lettering-repair-test",
                    novel_path="novel.txt",
                    created_at=datetime.now(timezone.utc),
                ),
                tmp_path,
            ),
            known_speaker_ids={"char_001"},
        )
    )

    assert draft.beats[0].lettering[0].speaker_entity_id == "char_001"
    assert len(calls) == 2
    assert "On-screen lettering requires speaker_entity_id" in calls[1]["user_content"]


def test_missing_compact_ledger_exception_becomes_a_repairable_failure() -> None:
    expected = _book_adaptation()
    beat = expected.beats[0].model_copy(
        update={
            "source_unit_ids": ("source_000001",),
            "lettering": (expected.beats[0].lettering[0],),
        }
    )
    draft = _materialize_draft_ledger(
        _BookDraft(beats=(beat,)),
        ("source_000001", "source_000002"),
    )
    candidate = BookAdaptation(
        revision=1,
        source_sha256=_source_document().source_sha256,
        brief_revision=_approved_brief().revision,
        brief_sha256=_approved_brief().content_sha256,
        treatment=expected.treatment,
        beats=draft.beats,
        ledger=draft.ledger,
    )

    validation = validate_book_adaptation(
        _source_document(),
        _approved_brief(),
        candidate,
    )

    assert "missing_ledger_exception" in {
        failure.code for failure in validation.invariant_failures
    }


def test_adapt_repair_scope_expands_failure_to_its_source_scene_only() -> None:
    text = " ".join(f"Sentence {index}." for index in range(1, 7))
    units: list[SourceUnit] = []
    offset = 0
    for index in range(1, 7):
        unit_text = f"Sentence {index}."
        suffix = " " if index < 6 else ""
        units.append(
            SourceUnit(
                id=f"source_{index:06d}",
                ordinal=index,
                start_offset=offset,
                end_offset=offset + len(unit_text) + len(suffix),
                text=unit_text + suffix,
            )
        )
        offset += len(unit_text) + len(suffix)
    source = SourceDocument(
        text=text,
        units=units,
        scenes=[
            SourceScene(
                id="scene_001",
                title="First",
                first_unit_id="source_000001",
                last_unit_id="source_000003",
            ),
            SourceScene(
                id="scene_002",
                title="Second",
                first_unit_id="source_000004",
                last_unit_id="source_000006",
            ),
        ],
    )
    validation = AdaptationValidation(
        invariant_failures=[
            InvariantFailure(
                id="failure",
                owner_stage="adapt",
                code="reader_context_gap",
                message="The second scene lost its causal context.",
                source_unit_ids=["source_000005"],
                evidence=["The causal explanation is absent."],
            )
        ]
    )

    scope = _repair_source_scope(
        source,
        tuple(unit.id for unit in units),
        validation,
    )

    assert scope == (
        "source_000004",
        "source_000005",
        "source_000006",
    )


def test_a_treatment_returned_in_the_wrong_containers_is_reshaped() -> None:
    # Exactly the shapes one model produced: a bare string where a list belongs,
    # a list of objects, and an object keyed by motif name.
    normalized = normalize_treatment(
        {
            "causal_spine": "Thurston inherits the papers and seals his fate.",
            "character_turns": [
                {"character": "Thurston", "turn": "There is nowhere left to go."},
            ],
            "motifs": {"carven_idols": "The idol recurs in the closing captions."},
        }
    )
    treatment = NarrativeTreatment.model_validate(normalized)

    assert treatment.causal_spine == (
        "Thurston inherits the papers and seals his fate.",
    )
    assert treatment.character_turns == (
        "character: Thurston; turn: There is nowhere left to go.",
    )
    assert treatment.motifs == (
        "carven_idols: The idol recurs in the closing captions.",
    )


def test_keys_the_contract_does_not_have_are_dropped_not_fatal() -> None:
    normalized = normalize_treatment(
        {
            "causal_spine": ["A causal spine."],
            "title": "The Call of Cthulhu",
            "acts": [{"act_number": 1}],
            "narrator_voice": {"treatment": "Retrospective."},
        }
    )

    assert set(normalized) == {"causal_spine"}
    assert NarrativeTreatment.model_validate(normalized).causal_spine == (
        "A causal spine.",
    )


def test_a_treatment_in_the_wrong_containers_costs_no_extra_model_call(
    tmp_path: Path,
) -> None:
    # Reshaping is deterministic, so the stage must not pay for a retry to fix
    # something it can fix itself.
    expected = _book_adaptation()
    treatment = expected.treatment.model_dump(mode="json")
    slipped = {
        **treatment,
        "causal_spine": treatment["causal_spine"][0],
        "motifs": {"door": "The door recurs."},
    }
    responses = [
        slipped,
        {
            "beats": [beat.model_dump(mode="json") for beat in expected.beats],
            "ledger": [entry.model_dump(mode="json") for entry in expected.ledger],
        },
        _lettering_response(expected.beats),
    ]
    calls: list[dict] = []

    async def generate(**request):
        calls.append(request)
        return ApiResult(value=responses[len(calls) - 1], usage=None)

    produced = asyncio.run(
        produce_book_adaptation(
            _source_document(),
            _story_bible(),
            _approved_brief(),
            artifacts=TargetArtifacts(tmp_path),
            ctx=StageRuntime(
                "adapt",
                PipelineState(
                    project_name="adapt-test",
                    novel_path="novel.txt",
                    created_at=datetime.now(timezone.utc),
                ),
                tmp_path,
            ),
            model="gpt-4o-mini",
            generate=generate,
        )
    )

    assert len(calls) == 3
    assert produced.treatment.causal_spine == (expected.treatment.causal_spine[0],)
    assert produced.treatment.motifs == ("door: The door recurs.",)


def _protected_title_candidate() -> tuple[SourceDocument, AdaptationBrief, BookAdaptation, StoryBible]:
    source = _source_document()
    text = "Dungeon Crawler Carl"
    first_text = text + " by Matt Dinniman. I saw the door open. "
    source = SourceDocument.model_validate({
        **source.model_dump(), "source_sha256": "",
        "text": first_text + source.units[1].text,
        "units": [
            {**source.units[0].model_dump(), "text": first_text, "end_offset": len(first_text)},
            {**source.units[1].model_dump(), "start_offset": len(first_text),
             "end_offset": len(first_text) + len(source.units[1].text)},
        ],
    })
    brief = AdaptationBrief.model_validate({
        **_approved_brief().model_dump(), "protected_language": (text,), "content_sha256": "",
    })
    candidate = _with_lettering_text(text)
    first = candidate.beats[0]
    item = first.lettering[0].model_copy(update={"delivery": None})
    candidate = candidate.model_copy(update={"beats": (first.model_copy(update={"lettering": (item, *first.lettering[1:])}),)})
    bible = _story_bible().model_copy(update={"title": text})
    candidate = BookAdaptation.model_validate({
        **candidate.model_dump(), "content_sha256": "",
        "source_sha256": source.source_sha256, "brief_sha256": brief.content_sha256,
    })
    return source, brief, candidate, bible


def test_protected_title_recovers_missing_delivery_without_changing_wording() -> None:
    source, brief, candidate, bible = _protected_title_candidate()
    before = validate_book_adaptation(source, brief, candidate, story_bible=bible)
    assert {failure.code for failure in before.invariant_failures} >= {
        "invalid_lettering_speaker", "trailing_clipped_display_text",
    }
    recovered = _canonicalize_candidate_requirements(candidate, source, brief)
    after = validate_book_adaptation(source, brief, recovered, story_bible=bible)
    assert not after.invariant_failures
    assert recovered.beats[0].lettering[0].text == "Dungeon Crawler Carl"
    assert recovered.beats[0].lettering[0].delivery == "quoted_text"


@pytest.mark.parametrize("defect", ["prose", "wrong_title", "missing_provenance"])
def test_title_exception_does_not_allow_clipped_prose_or_unproven_titles(defect: str) -> None:
    source, brief, candidate, bible = _protected_title_candidate()
    candidate = _canonicalize_candidate_requirements(candidate, source, brief)
    if defect == "prose":
        bible = bible.model_copy(update={"title": "I saw the door open"})
        candidate = _with_lettering_text("I saw the door open")
    elif defect == "wrong_title":
        bible = bible.model_copy(update={"title": "Another Book"})
    else:
        item = candidate.beats[0].lettering[0].model_copy(update={"source_unit_ids": ()})
        beat = candidate.beats[0].model_copy(update={"lettering": (item,)})
        candidate = candidate.model_copy(update={"beats": (beat,)})
    result = validate_book_adaptation(source, brief, candidate, story_bible=bible)
    assert "trailing_clipped_display_text" in {failure.code for failure in result.invariant_failures}


def test_saved_protected_title_resumes_without_a_provider_call(tmp_path: Path) -> None:
    source, brief, candidate, bible = _protected_title_candidate()
    artifacts = TargetArtifacts(tmp_path)
    artifacts.write_failed_adaptation_candidate(candidate)

    async def forbidden_generate(**request):
        pytest.fail("Recovering a source-backed title must not call a provider")

    produced = asyncio.run(produce_book_adaptation(
        source, bible, brief, artifacts=artifacts,
        ctx=StageRuntime("adapt", PipelineState(
            project_name="title-recovery", novel_path="novel.txt",
            created_at=datetime.now(timezone.utc),
        ), tmp_path),
        model="gpt-4o-mini", generate=forbidden_generate,
    ))
    assert produced == artifacts.read_adaptation()
    assert not artifacts.failed_adaptation_candidate_path.exists()
    assert not artifacts.read_validation("adapt").invariant_failures


@pytest.mark.parametrize("change", ["source", "brief", "instruction"])
def test_saved_candidate_recovery_requires_unchanged_authority(tmp_path: Path, change: str) -> None:
    source, brief, candidate, bible = _protected_title_candidate()
    artifacts = TargetArtifacts(tmp_path)
    artifacts.write_failed_adaptation_candidate(candidate)
    if change == "source":
        source = source.model_copy(update={"source_sha256": "a" * 64})
    if change == "brief":
        brief = brief.model_copy(update={"revision": brief.revision + 1})
    assert recoverable_adaptation_candidate(
        source, bible, brief, artifacts=artifacts,
        story_instruction="Change the ending" if change == "instruction" else "",
    ) is None
    assert artifacts.failed_adaptation_candidate_path.exists()
