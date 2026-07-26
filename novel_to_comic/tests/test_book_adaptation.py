from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from novel_to_comic.book_adaptation import (
    build_book_adaptation_prompt,
    build_narrative_treatment_prompt,
    produce_book_adaptation,
    validate_book_adaptation,
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
from novel_to_comic.models.story_bible import StoryBible
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
        target_page_min=32,
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
            character_turns=["The witness abandons the investigation."],
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
                brief_requirements=[
                    "The witness sees the door open.",
                    "The witness abandons the investigation.",
                ],
                source_unit_ids=["source_000001", "source_000002"],
                lettering=[
                    LetteringItem(
                        id="lettering_0001",
                        kind="caption",
                        text="I saw the door open.",
                        source_unit_ids=["source_000001"],
                    ),
                    LetteringItem(
                        id="lettering_0002",
                        kind="caption",
                        text="I fled into the rain.",
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


def test_treatment_prompt_is_book_level_and_forbids_page_or_scene_authority() -> None:
    prompt = build_narrative_treatment_prompt(
        _source_document(),
        _story_bible(),
        _approved_brief(),
    )

    assert '"target_page_min":32' in prompt
    assert '"id":"source_000001"' in prompt
    assert "one book-wide narrative treatment" in prompt
    assert "Do not allocate pages, panels, layouts, or geometry." in prompt
    assert "Do not create parallel per-scene adaptations" in prompt


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
        "brief_requirements": [],
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

    assert code in {failure.code for failure in result.invariant_failures}


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


def test_cthulhu_missing_reaction_or_aftermath_is_an_editorial_issue() -> None:
    fixture = json.loads(
        (
            Path(__file__).parent
            / "fixtures"
            / "cthulhu_adapt_missing_aftermath.json"
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
            "character_turns": (
                "Johansen abandons any hope of an ordinary life.",
            ),
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

    assert result.invariant_failures == ()
    assert [issue.code for issue in result.editorial_issues] == [
        "rushed_reaction_or_aftermath"
    ]
    assert result.editorial_issues[0].source_unit_ids == ("source_000001",)
    assert result.editorial_issues[0].artifact_ids == ("beat_0001",)
    assert "score" not in result.editorial_issues[0].model_dump()


def test_intentional_omission_is_reviewable_with_cited_evidence() -> None:
    payload = _book_adaptation().model_dump()
    payload["content_sha256"] = ""
    payload["beats"][0]["source_unit_ids"] = ["source_000001"]
    payload["beats"][0]["lettering"] = [payload["beats"][0]["lettering"][0]]
    ledger = list(payload["ledger"])
    ledger[1] = {
        "source_unit_id": "source_000002",
        "disposition": "intentionally_omitted",
        "adapted_beat_ids": [],
        "reason": "The flight already communicates immediate panic.",
        "preserved_function": "The prose reaction is intentionally removed.",
    }
    payload["ledger"] = ledger
    candidate = BookAdaptation.model_validate(payload)

    result = validate_book_adaptation(
        _source_document(),
        _approved_brief(),
        candidate,
    )

    issue = next(
        issue
        for issue in result.editorial_issues
        if issue.code == "questionable_omission"
    )
    assert issue.source_unit_ids == ("source_000002",)
    assert issue.evidence == (
        "The flight already communicates immediate panic.",
        "The prose reaction is intentionally removed.",
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
    payload["beats"][0]["brief_requirements"] = [
        requirement
        for requirement in payload["beats"][0]["brief_requirements"]
        if requirement != missing_requirement
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
    assert "exactly one ledger disposition for every source unit" in prompt
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
        {
            "beats": [
                beat.model_dump(mode="json")
                for beat in expected.beats
            ],
            "ledger": [
                entry.model_dump(mode="json")
                for entry in expected.ledger
            ],
        },
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
    assert (tmp_path / "adapt").iterdir().__next__().name == "book.json"
    assert sorted(path.name for path in (tmp_path / "adapt").iterdir()) == [
        "book.json"
    ]
    assert [call["feature"] for call in calls] == [
        "adapt.narrative_treatment",
        "adapt.book",
    ]
    assert state.stages["adapt"].items_done == 2
    assert len(state.stages["adapt"].usage_log) == 2
    assert state.stages["adapt"].cost_usd > 0
    assert state.stages["adapt"].estimated_cost_usd > 0


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
