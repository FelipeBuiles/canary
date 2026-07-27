from __future__ import annotations

import asyncio

import pytest
from pydantic import ValidationError

from novel_to_comic.models.adaptation import (
    AdaptationBrief,
    AdaptationLedgerEntry,
    AdaptedBeat,
    BookAdaptation,
    LetteringItem,
    NarrativeTreatment,
)
from novel_to_comic.models.source import (
    SourceContextReference,
    SourceDocument,
    SourceScene,
    SourceUnit,
)
from novel_to_comic.models.story_bible import Scene, StoryBible
from novel_to_comic.models.page import (
    BookPlan,
    ComicPage,
    PageContent,
    PlannedPageRevision,
    PinnedGeometry,
)
from novel_to_comic.models.validation import EditorialIssue, InvariantFailure
from novel_to_comic.models.draw import (
    BookEdition,
    FrozenPageGenerationRequest,
    PageCapabilityProfile,
    PageIssue,
    PageReference,
    PageRenderRevision,
    RenderAnalysis,
    RetryProvenance,
)
from novel_to_comic.models.finish import (
    FinishPreflight,
    PreflightPage,
)
from novel_to_comic.target_artifacts import ArtifactMissing, TargetArtifacts
from novel_to_comic.source_extraction import (
    SourceSceneAnchor,
    _find_quote_position,
    align_scene_anchors,
    build_source_document,
    produce_source_document,
)
from novel_to_comic.briefing import (
    StoryDecision,
    approve_brief,
    approve_story,
    infer_brief,
    propose_brief,
    require_approved_brief,
    revise_brief,
    revise_persisted_brief,
    revise_story,
)


def _source_document() -> SourceDocument:
    text = "The door opened. Nothing moved."
    return SourceDocument(
        text=text,
        units=[
            SourceUnit(
                id="source_000001",
                ordinal=1,
                start_offset=0,
                end_offset=17,
                text="The door opened. ",
            ),
            SourceUnit(
                id="source_000002",
                ordinal=2,
                start_offset=17,
                end_offset=len(text),
                text="Nothing moved.",
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


def test_source_document_preserves_exact_text_and_primary_coverage() -> None:
    document = _source_document()

    assert document.source_sha256 == (
        "f215d65515d173ddd482db5f1923319a3621b5df118cc3340f476b5a2911d792"
    )
    assert "".join(unit.text for unit in document.units) == document.text
    assert document.scenes[0].unit_ids(document) == [
        "source_000001",
        "source_000002",
    ]


def test_source_document_rejects_a_gap_between_units() -> None:
    payload = _source_document().model_dump()
    payload["units"][1]["start_offset"] = 18
    payload["units"][1]["text"] = "othing moved."

    with pytest.raises(ValidationError, match="contiguous"):
        SourceDocument.model_validate(payload)


def test_source_document_rejects_an_offset_text_mismatch() -> None:
    payload = _source_document().model_dump()
    payload["units"][0]["text"] = "The door closed. "

    with pytest.raises(ValidationError, match="does not match source text"):
        SourceDocument.model_validate(payload)


def test_source_document_rejects_a_mid_sentence_unit_boundary() -> None:
    text = "The door opened. Nothing moved."

    with pytest.raises(ValidationError, match="sentence-aligned"):
        SourceDocument(
            text=text,
            units=[
                SourceUnit(
                    id="source_000001",
                    ordinal=1,
                    start_offset=0,
                    end_offset=8,
                    text="The door",
                ),
                SourceUnit(
                    id="source_000002",
                    ordinal=2,
                    start_offset=8,
                    end_offset=len(text),
                    text=" opened. Nothing moved.",
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


def test_source_builder_uses_exact_sentence_units_and_contiguous_scene_ranges() -> None:
    text = 'Dr. Ward listened. "The cry stopped." Then silence.'

    document = build_source_document(
        text,
        [
            SourceSceneAnchor(
                id="scene_001",
                title="The cry",
                opening_quote="Dr. Ward listened.",
            ),
            SourceSceneAnchor(
                id="scene_002",
                title="Silence",
                opening_quote="Then silence.",
            ),
        ],
    )

    assert [unit.text for unit in document.units] == [
        "Dr. Ward listened. ",
        '"The cry stopped." ',
        "Then silence.",
    ]
    assert document.scenes[0].unit_ids(document) == [
        "source_000001",
        "source_000002",
    ]
    assert document.scenes[1].unit_ids(document) == ["source_000003"]


def test_source_builder_does_not_split_at_mid_word_punctuation() -> None:
    text = "Visit example.com today. Then leave."

    document = build_source_document(
        text,
        [
            SourceSceneAnchor(
                id="scene_001",
                title="Visit",
                opening_quote="Visit example.com today.",
            ),
            SourceSceneAnchor(
                id="scene_002",
                title="Leave",
                opening_quote="Then leave.",
            ),
        ],
    )

    assert [unit.text for unit in document.units] == [
        "Visit example.com today. ",
        "Then leave.",
    ]


def test_source_builder_rejects_an_unresolvable_scene_anchor() -> None:
    with pytest.raises(ValueError, match="verbatim opening quote"):
        build_source_document(
            "The door opened.",
            [
                SourceSceneAnchor(
                    id="scene_001",
                    title="Wrong",
                    opening_quote="The window opened.",
                )
            ],
        )


def test_source_builder_rejects_a_truncated_opening_sentence_anchor() -> None:
    with pytest.raises(ValueError, match="complete opening sentence"):
        build_source_document(
            "The door opened onto darkness. Nothing moved.",
            [
                SourceSceneAnchor(
                    id="scene_001",
                    title="The door",
                    opening_quote="The door opened",
                )
            ],
        )


_ANCHOR_ALIGNMENT_TEXT = (
    "The Call of Cthulhu\nby H. P. Lovecraft\n\nI. The Horror in Clay\n\n"
    "The most merciful thing in the world is inability. "
    'The cry rose: "Cthulhu fhtagn. . . the stars were wrong." '
    "Prof. Angell studied the tablet. "
    "Then silence fell."
)


def _anchor_scene(scene_id: str, quote: str) -> Scene:
    return Scene(
        id=scene_id,
        chapter=1,
        title=scene_id,
        location_id="location_room",
        character_ids=[],
        summary="A scene.",
        scene_type="action",
        narrative_beat="initial",
        source_start_quote=quote,
    )


def _aligned_bible(text: str, quotes: list[str]) -> StoryBible:
    story_bible = _story_bible().model_copy(
        update={
            "total_scenes": len(quotes),
            "scenes": [
                _anchor_scene(f"scene_{ordinal:03d}", quote)
                for ordinal, quote in enumerate(quotes, start=1)
            ],
        }
    )
    align_scene_anchors(story_bible, text)
    return story_bible


def test_truncated_scene_anchors_align_to_complete_source_units() -> None:
    story_bible = _aligned_bible(
        _ANCHOR_ALIGNMENT_TEXT,
        [
            "The most merciful thing in the world is inability.",
            'The cry rose: "Cthulhu fhtagn',
            "Prof.",
        ],
    )

    assert [scene.source_start_quote for scene in story_bible.scenes] == [
        "The Horror in Clay\n\nThe most merciful thing in the world is inability.",
        'The cry rose: "Cthulhu fhtagn.',
        "Prof. Angell studied the tablet.",
    ]


def test_mid_sentence_scene_anchor_aligns_to_its_owning_source_unit() -> None:
    story_bible = _aligned_bible(
        _ANCHOR_ALIGNMENT_TEXT,
        [
            "The most merciful thing in the world is inability.",
            "the stars were wrong",
        ],
    )

    assert story_bible.scenes[1].source_start_quote == 'the stars were wrong." '.strip()


def test_aligned_anchors_produce_a_valid_source_document(tmp_path) -> None:
    story_bible = _aligned_bible(
        _ANCHOR_ALIGNMENT_TEXT,
        [
            "The most merciful thing in the world is inability.",
            'The cry rose: "Cthulhu fhtagn',
            "Prof.",
        ],
    )

    document = produce_source_document(
        TargetArtifacts(tmp_path),
        _ANCHOR_ALIGNMENT_TEXT,
        story_bible,
    )

    covered = [
        unit_id for scene in document.scenes for unit_id in scene.unit_ids(document)
    ]
    assert covered == [unit.id for unit in document.units]


def test_front_matter_before_the_first_anchor_belongs_to_the_first_scene() -> None:
    text = "PART ONE.\n\nThe door opened. Nothing moved."

    document = build_source_document(
        text,
        [
            SourceSceneAnchor(
                id="scene_001",
                title="The door",
                opening_quote="The door opened.",
            ),
            SourceSceneAnchor(
                id="scene_002",
                title="Silence",
                opening_quote="Nothing moved.",
            ),
        ],
    )

    assert document.scenes[0].first_unit_id == document.units[0].id
    assert document.scenes[0].unit_ids(document) == [
        "source_000001",
        "source_000002",
    ]


def test_an_unlocatable_scene_anchor_does_not_destroy_the_source_document(
    tmp_path,
) -> None:
    # One hallucinated quote out of several is not a reason to lose the whole
    # immutable source. Extract has no approval checkpoint, so a hard failure
    # here leaves the user with nothing to inspect.
    text = "The door opened. A light burned. Nothing moved."
    story_bible = _aligned_bible(
        text,
        [
            "The door opened.",
            "A voice called from the cellar.",
            "Nothing moved.",
        ],
    )

    document = produce_source_document(TargetArtifacts(tmp_path), text, story_bible)

    assert [scene.id for scene in document.scenes] == ["scene_001", "scene_003"]
    assert document.scenes[0].unit_ids(document) == [
        "source_000001",
        "source_000002",
    ]
    covered = [
        unit_id for scene in document.scenes for unit_id in scene.unit_ids(document)
    ]
    assert covered == [unit.id for unit in document.units]


def test_alignment_reports_the_scenes_it_could_not_place() -> None:
    text = "The door opened. A light burned. Nothing moved."
    story_bible = _story_bible().model_copy(
        update={
            "total_scenes": 2,
            "scenes": [
                _anchor_scene("scene_001", "The door opened."),
                _anchor_scene("scene_002", "A voice called from the cellar."),
            ],
        }
    )

    assert align_scene_anchors(story_bible, text) == ("scene_002",)


def test_scenes_are_never_silently_reordered_to_fit_their_quotes() -> None:
    # A scene whose quote sits before the previous boundary is a model ordering
    # slip. Moving the boundary backwards would reorder the book, so the anchor
    # is reported unresolved and its units stay with the preceding scene.
    text = "The door opened. A light burned. Nothing moved."
    story_bible = _story_bible().model_copy(
        update={
            "total_scenes": 2,
            "scenes": [
                _anchor_scene("scene_001", "Nothing moved."),
                _anchor_scene("scene_002", "A light burned."),
            ],
        }
    )

    unresolved = align_scene_anchors(story_bible, text)

    assert unresolved == ("scene_002",)
    assert story_bible.scenes[1].source_start_quote == "A light burned."


def test_a_source_with_no_locatable_anchor_at_all_still_fails(tmp_path) -> None:
    story_bible = _aligned_bible(
        "The door opened. Nothing moved.",
        ["A voice called from the cellar."],
    )

    with pytest.raises(ValueError, match="no Story Bible scene anchor"):
        produce_source_document(
            TargetArtifacts(tmp_path),
            "The door opened. Nothing moved.",
            story_bible,
        )


def test_quote_positions_are_offsets_into_the_unmodified_source() -> None:
    text = (
        "The angles were wrong—utterly wrong—and he fled. "
        "Later he wrote it down. "
        "The dream returned."
    )

    # A misquoted final word forces the fuzzy path, which searches a
    # dash-normalised copy of the source; that copy must stay offset-faithful.
    position = _find_quote_position(text, "Later he wrote it downn")

    assert text[position:].startswith("Later he wrote it down.")


def test_extract_producer_writes_only_the_canonical_source_document(tmp_path) -> None:
    story_bible = _story_bible().model_copy(
        update={
            "total_scenes": 2,
            "scenes": [
                Scene(
                    id="scene_001",
                    chapter=1,
                    title="Opening",
                    location_id="location_room",
                    character_ids=[],
                    summary="The door opens.",
                    scene_type="action",
                    narrative_beat="initial",
                    source_start_quote="The door opened.",
                ),
                Scene(
                    id="scene_002",
                    chapter=1,
                    title="Silence",
                    location_id="location_room",
                    character_ids=[],
                    summary="Nothing moves.",
                    scene_type="emotional",
                    narrative_beat="release",
                    source_start_quote="Nothing moved.",
                ),
            ],
        }
    )
    artifacts = TargetArtifacts(tmp_path)

    document = produce_source_document(
        artifacts,
        "The door opened. Nothing moved.",
        story_bible,
    )

    assert artifacts.read_source() == document
    assert not (tmp_path / "scenes").exists()


def test_canonical_source_cannot_be_overwritten_with_different_text(tmp_path) -> None:
    artifacts = TargetArtifacts(tmp_path)
    artifacts.write_source(_source_document())
    changed = build_source_document(
        "The door closed.",
        [
            SourceSceneAnchor(
                id="scene_001",
                title="The door",
                opening_quote="The door closed.",
            )
        ],
    )

    with pytest.raises(ValueError, match="immutable source"):
        artifacts.write_source(changed)


def test_labeled_context_references_do_not_change_primary_ownership() -> None:
    payload = _source_document().model_dump()
    payload["scenes"] = [
        {
            "id": "scene_001",
            "title": "Opening",
            "first_unit_id": "source_000001",
            "last_unit_id": "source_000001",
            "context": [
                SourceContextReference(
                    label="Foreshadows the later silence.",
                    unit_ids=["source_000002"],
                ).model_dump()
            ],
        },
        {
            "id": "scene_002",
            "title": "Silence",
            "first_unit_id": "source_000002",
            "last_unit_id": "source_000002",
        },
    ]

    document = SourceDocument.model_validate(payload)

    assert document.scenes[0].context[0].unit_ids == ("source_000002",)


def test_context_reference_must_not_duplicate_its_scenes_primary_range() -> None:
    payload = _source_document().model_dump()
    payload["scenes"][0]["context"] = [
        {
            "label": "Not actually context.",
            "unit_ids": ["source_000001"],
        }
    ]

    with pytest.raises(ValidationError, match="outside its primary range"):
        SourceDocument.model_validate(payload)


def test_source_document_rejects_reordered_primary_scene_ranges() -> None:
    payload = _source_document().model_dump()
    payload["scenes"] = [
        {
            "id": "scene_002",
            "title": "Silence",
            "first_unit_id": "source_000002",
            "last_unit_id": "source_000002",
        },
        {
            "id": "scene_001",
            "title": "Opening",
            "first_unit_id": "source_000001",
            "last_unit_id": "source_000001",
        },
    ]

    with pytest.raises(ValidationError, match="ordered"):
        SourceDocument.model_validate(payload)


def test_source_document_rejects_duplicate_scene_ids() -> None:
    payload = _source_document().model_dump()
    payload["scenes"] = [
        {
            "id": "scene_001",
            "title": "Opening",
            "first_unit_id": "source_000001",
            "last_unit_id": "source_000001",
        },
        {
            "id": "scene_001",
            "title": "Silence",
            "first_unit_id": "source_000002",
            "last_unit_id": "source_000002",
        },
    ]

    with pytest.raises(ValidationError, match="scene IDs must be unique"):
        SourceDocument.model_validate(payload)


@pytest.mark.parametrize(
    ("scenes", "message"),
    [
        (
            [
                {
                    "id": "scene_001",
                    "title": "Opening",
                    "first_unit_id": "source_000002",
                    "last_unit_id": "source_000002",
                }
            ],
            "complete and ordered",
        ),
        (
            [
                {
                    "id": "scene_001",
                    "title": "Opening",
                    "first_unit_id": "source_000001",
                    "last_unit_id": "source_000002",
                },
                {
                    "id": "scene_002",
                    "title": "Overlap",
                    "first_unit_id": "source_000002",
                    "last_unit_id": "source_000002",
                },
            ],
            "complete and ordered",
        ),
        (
            [
                {
                    "id": "scene_001",
                    "title": "Unknown",
                    "first_unit_id": "source_missing",
                    "last_unit_id": "source_missing",
                }
            ],
            "unknown source unit",
        ),
        (
            [
                {
                    "id": "scene_001",
                    "title": "Inverted",
                    "first_unit_id": "source_000002",
                    "last_unit_id": "source_000001",
                }
            ],
            "inverted",
        ),
    ],
)
def test_source_document_rejects_invalid_primary_scene_ownership(
    scenes,
    message,
) -> None:
    payload = _source_document().model_dump()
    payload["scenes"] = scenes

    with pytest.raises(ValidationError, match=message):
        SourceDocument.model_validate(payload)


def _approved_brief() -> AdaptationBrief:
    return AdaptationBrief(
        revision=1,
        status="approved",
        story_promises=["The investigator's certainty must collapse."],
        themes=["Knowledge has a cost."],
        point_of_view="First-person retrospective.",
        narrator_treatment="Retain the narrator's eroding confidence.",
        tone="Mounting cosmic dread.",
        ambiguities=["Whether the witness truly saw the room empty."],
        motifs=["Doors as thresholds to forbidden knowledge."],
        protected_language=["the most merciful thing in the world"],
        essential_events=["The witness opens the door."],
        character_turns=["The witness refuses to continue the investigation."],
        transformation_level="medium_specific",
        desired_emphasis=["Preserve discovery, reaction, and aftermath."],
        target_page_min=32,
        target_page_max=40,
    )


def _story_bible() -> StoryBible:
    return StoryBible(
        title="The Door",
        author="A. Writer",
        total_scenes=0,
        characters=[],
        locations=[],
        scenes=[],
        narrative_arcs=[],
    )


def _book_adaptation() -> BookAdaptation:
    brief = _approved_brief()
    return BookAdaptation(
        revision=1,
        source_sha256=_source_document().source_sha256,
        brief_revision=brief.revision,
        brief_sha256=brief.content_sha256,
        treatment=NarrativeTreatment(
            causal_spine=["The door opens.", "The witness cannot explain the silence."],
            reveals=["The room is empty."],
            reactions=["The witness refuses to enter."],
            aftermath=["The refusal ends the investigation."],
        ),
        beats=[
            AdaptedBeat(
                id="beat_0001",
                order=1,
                summary="The door opens on an empty room.",
                narrative_function="peak",
                source_unit_ids=["source_000001"],
                lettering=[
                    LetteringItem(
                        id="lettering_0001",
                        kind="caption",
                        text="The door opened.",
                        source_unit_ids=["source_000001"],
                    )
                ],
            )
        ],
        ledger=[
            AdaptationLedgerEntry(
                source_unit_id="source_000001",
                disposition="caption",
                adapted_beat_ids=["beat_0001"],
                preserved_function="The initiating event remains explicit.",
            ),
            AdaptationLedgerEntry(
                source_unit_id="source_000002",
                disposition="intentionally_omitted",
                reason="The empty room depicts the same information.",
                preserved_function="Silence is carried visually.",
            ),
        ],
    )


def test_book_adaptation_round_trip_preserves_complete_lettering_and_hash() -> None:
    adaptation = _book_adaptation()

    loaded = BookAdaptation.model_validate_json(adaptation.model_dump_json())

    assert loaded.beats[0].lettering[0].text == "The door opened."
    assert loaded.content_sha256 == adaptation.content_sha256
    assert len(loaded.content_sha256) == 64


def test_book_adaptation_rejects_stale_content_hash() -> None:
    payload = _book_adaptation().model_dump()
    payload["beats"][0]["lettering"][0]["text"] = "The door closed."

    with pytest.raises(ValidationError, match="content_sha256"):
        BookAdaptation.model_validate(payload)


def test_intentional_omission_requires_a_reason() -> None:
    payload = _book_adaptation().model_dump()
    payload["content_sha256"] = ""
    payload["ledger"][1]["reason"] = None

    with pytest.raises(ValidationError, match="reason"):
        BookAdaptation.model_validate(payload)


def test_brief_editing_creates_a_draft_revision_before_explicit_approval() -> None:
    approved = _approved_brief()

    draft = revise_brief(
        approved,
        expected_revision=1,
        tone="Quiet dread that breaks into panic.",
    )
    reapproved = approve_brief(draft, expected_revision=2)

    assert draft.revision == 2
    assert draft.status == "draft"
    assert draft.content_sha256 != approved.content_sha256
    assert reapproved.revision == 3
    assert reapproved.status == "approved"


def test_inferred_brief_is_always_a_non_authoritative_draft() -> None:
    inferred = _approved_brief().model_dump(
        exclude={"revision", "content_sha256", "status"}
    )

    proposed = propose_brief({**inferred, "status": "approved"})

    assert proposed.revision == 1
    assert proposed.status == "draft"


def test_brief_cannot_be_approved_without_desired_emphasis() -> None:
    payload = _approved_brief().model_dump()
    payload["desired_emphasis"] = []
    payload["content_sha256"] = ""

    with pytest.raises(ValidationError, match="desired_emphasis"):
        AdaptationBrief.model_validate(payload)


def test_brief_inference_uses_source_units_and_story_bible_without_approval() -> None:
    prompts: list[str] = []
    inferred = _approved_brief().model_dump(
        exclude={"revision", "content_sha256", "status"}
    )

    async def infer(prompt: str):
        prompts.append(prompt)
        return inferred

    proposed = asyncio.run(
        infer_brief(_source_document(), _story_bible(), infer=infer)
    )

    assert proposed.status == "draft"
    assert '"id":"source_000001"' in prompts[0]
    assert '"text":"The door opened. "' in prompts[0]
    assert '"title":"The Door"' in prompts[0]


def test_brief_approval_rejects_a_stale_editor_revision() -> None:
    with pytest.raises(ValueError, match="stale adaptation brief"):
        approve_brief(_approved_brief(), expected_revision=0)


def test_brief_approval_requires_a_draft_revision() -> None:
    with pytest.raises(ValueError, match="draft adaptation brief"):
        approve_brief(_approved_brief(), expected_revision=1)


def test_brief_editing_rejects_a_stale_editor_revision() -> None:
    with pytest.raises(ValueError, match="stale adaptation brief"):
        revise_brief(
            _approved_brief(),
            expected_revision=0,
            tone="Quiet dread.",
        )


def test_adapt_remains_blocked_until_the_brief_is_approved() -> None:
    draft = revise_brief(
        _approved_brief(),
        expected_revision=1,
        tone="Quiet dread.",
    )

    with pytest.raises(ValueError, match="approved adaptation brief"):
        require_approved_brief(draft)

    assert require_approved_brief(_approved_brief()).status == "approved"


def test_story_bible_and_brief_share_one_story_approval_contract() -> None:
    draft = propose_brief(
        _approved_brief().model_dump(
            exclude={"revision", "content_sha256", "status"}
        )
    )
    review = StoryDecision(story_bible=_story_bible(), brief=draft)

    approved = approve_story(review, expected_revision=1)

    assert approved.story_bible == review.story_bible
    assert approved.brief.revision == 2
    assert approved.brief.status == "approved"


def test_story_edit_revises_bible_and_brief_as_one_draft_decision() -> None:
    review = StoryDecision(story_bible=_story_bible(), brief=_approved_brief())
    edited_bible = review.story_bible.model_copy(update={"title": "The Open Door"})

    revised = revise_story(
        review,
        expected_revision=1,
        story_bible=edited_bible,
        target_page_min=36,
    )

    assert revised.story_bible.title == "The Open Door"
    assert revised.brief.revision == 2
    assert revised.brief.status == "draft"
    assert revised.brief.target_page_min == 36


def test_persisted_brief_edit_invalidates_adapt_and_all_downstream_artifacts(
    tmp_path,
) -> None:
    artifacts = TargetArtifacts(tmp_path)
    artifacts.write_brief(_approved_brief())
    invalidated_paths = [
        tmp_path / name
        for name in ("adapt", "plan", "draw", "finish", "exports")
    ]
    for path in invalidated_paths:
        path.mkdir()
        (path / "stale").write_text("stale")

    revised = revise_persisted_brief(
        artifacts,
        expected_revision=1,
        tone="Quiet dread.",
    )

    assert artifacts.read_brief() == revised
    assert all(not path.exists() for path in invalidated_paths)


def _comic_page() -> ComicPage:
    adaptation = _book_adaptation()
    lettering = adaptation.beats[0].lettering[0]
    return ComicPage(
        page_number=1,
        revision=1,
        adaptation_revision=adaptation.revision,
        adaptation_sha256=adaptation.content_sha256,
        page_turn_role="reveal",
        spread_role="right",
        emphasis="peak",
        density_intent="sparse",
        content=[
            PageContent(
                id="content_001",
                order=1,
                beat_ids=["beat_0001"],
                visual_intent="The open door dominates the page.",
                lettering=[lettering],
                entity_ids=["character_witness", "location_room"],
                appearance_state_ids=["witness_before_entry"],
            )
        ],
        reading_order=["content_001", "lettering_0001"],
    )


def test_comic_page_is_semantic_until_geometry_is_explicitly_pinned() -> None:
    page = _comic_page()

    assert page.content[0].pinned_geometry is None
    assert "pinned_geometry" not in page.model_dump(exclude_none=True)["content"][0]

    pinned = PageContent(
        **{
            **page.content[0].model_dump(exclude={"pinned_geometry"}),
            "pinned_geometry": PinnedGeometry(x=0.1, y=0.2, width=0.8, height=0.6),
        }
    )
    assert pinned.pinned_geometry.width == 0.8


def test_comic_page_hash_invalidates_when_exact_lettering_changes() -> None:
    payload = _comic_page().model_dump()
    payload["content"][0]["lettering"][0]["text"] = "The door closed."

    with pytest.raises(ValidationError, match="content_sha256"):
        ComicPage.model_validate(payload)


def test_validation_has_only_blocking_or_editorial_categories_and_no_score() -> None:
    failure = InvariantFailure(
        id="failure_001",
        owner_stage="plan",
        code="lettering_changed",
        message="Plan changed canonical lettering.",
        artifact_ids=["page_001"],
        evidence=["Expected 'opened'; found 'closed'."],
    )
    issue = EditorialIssue(
        id="issue_001",
        owner_stage="adapt",
        code="rushed_aftermath",
        message="The reaction has no aftermath beat.",
        source_unit_ids=["source_000002"],
        artifact_ids=["beat_0001"],
        evidence=["Peak is followed immediately by a scene transition."],
    )

    assert failure.kind == "invariant_failure"
    assert failure.blocking is True
    assert issue.kind == "editorial_issue"
    assert issue.blocking is False
    assert "score" not in failure.model_dump()
    assert "score" not in issue.model_dump()


def _page_profile() -> PageCapabilityProfile:
    return PageCapabilityProfile(
        id="nano_banana_pro_page_v1",
        provider="vertex-multimodal",
        model="gemini-3-pro-image-preview",
        exact_visible_lettering=True,
        max_image_references=8,
        reference_ordering="ordered",
        editing_modes=["instructed", "region_targeted"],
        output_width=2048,
        output_height=3072,
        max_prompt_characters=32_000,
        retry_semantics="idempotent_request",
        price_per_page_usd="0.30",
    )


def _page_request() -> FrozenPageGenerationRequest:
    return FrozenPageGenerationRequest.compile(
        page=_comic_page(),
        edition=BookEdition(
            revision=1,
            id="edition_001",
            capability_profile=_page_profile(),
        ),
        prompt="Render one complete comic page.",
        references=[
            PageReference(
                id="character_witness",
                order=1,
                media_type="image/png",
                content_sha256="a" * 64,
                visual_anchor="weathered face; left eyebrow scar",
                entity_id="character_witness",
            )
        ],
        retry=RetryProvenance(attempt=1),
    )


def test_frozen_request_preserves_page_copy_anchors_and_revision_identity() -> None:
    page = _comic_page()
    request = _page_request()

    assert request.lettering[0].text == "The door opened."
    assert request.references[0].visual_anchor == "weathered face; left eyebrow scar"
    assert request.is_stale_for(page) is False
    assert len(request.request_sha256) == 64

    changed = ComicPage.model_validate(
        {**page.model_dump(), "revision": 2, "content_sha256": ""}
    )
    assert request.is_stale_for(changed) is True


def test_profile_must_support_complete_pages_and_exact_lettering() -> None:
    payload = _page_profile().model_dump()
    payload["complete_page_generation"] = False

    with pytest.raises(ValidationError, match="complete_page_generation"):
        PageCapabilityProfile.model_validate(payload)


def test_page_render_and_analysis_are_derived_from_one_frozen_request() -> None:
    page = _comic_page()
    request = _page_request()
    render = PageRenderRevision(
        page_number=1,
        revision=1,
        comic_page_revision=page.revision,
        comic_page_sha256=page.content_sha256,
        request_sha256=request.request_sha256,
        image_sha256="b" * 64,
        width=2048,
        height=3072,
        provider="vertex",
        model="gemini-3-pro-image-preview",
        latency_ms=4_200,
        cost_usd="0.30",
    )
    analysis = RenderAnalysis(
        page_number=1,
        render_revision=1,
        render_image_sha256=render.image_sha256,
        recognized_lettering={"lettering_0001": "The door opened."},
        observed_reading_order=["content_001", "lettering_0001"],
    )

    assert render.is_stale_for(page) is False
    assert analysis.recognized_lettering["lettering_0001"] == "The door opened."


def test_page_issue_targets_a_render_without_creating_panel_ownership() -> None:
    issue = PageIssue(
        id="page_issue_001",
        issue_type="lettering_mismatch",
        page_number=1,
        render_revision=1,
        evidence=["OCR read 'closed' instead of 'opened'."],
        requested_correction="Render the canonical lettering exactly.",
        lettering_item_ids=["lettering_0001"],
        status="open",
    )

    assert issue.render_revision == 1
    assert "panel" not in issue.model_dump()


def test_target_artifacts_round_trip_through_their_single_canonical_paths(
    tmp_path,
) -> None:
    artifacts = TargetArtifacts(tmp_path)
    source = _source_document()
    brief = _approved_brief()
    adaptation = _book_adaptation()
    page = _comic_page()
    request = _page_request()
    plan = BookPlan(
        revision=1,
        adaptation_revision=adaptation.revision,
        adaptation_sha256=adaptation.content_sha256,
        target_page_min=1,
        target_page_max=1,
        pages=[
            PlannedPageRevision(
                page_number=page.page_number,
                revision=page.revision,
                content_sha256=page.content_sha256,
            )
        ],
    )
    edition = BookEdition(
        revision=1,
        id="edition_001",
        capability_profile=_page_profile(),
    )
    preflight = FinishPreflight(
        edition_revision=edition.revision,
        edition_sha256=edition.content_sha256,
        pages=[
            PreflightPage(
                page_number=1,
                comic_page_revision=1,
                comic_page_sha256=page.content_sha256,
                render_revision=1,
                render_image_sha256="b" * 64,
                invariant_failures=[],
                unresolved_editorial_issue_ids=[],
            )
        ],
    )

    artifacts.write_source(source)
    artifacts.write_brief(brief)
    artifacts.write_adaptation(adaptation)
    artifacts.write_plan(plan)
    artifacts.write_page(page)
    artifacts.write_book_edition(edition)
    artifacts.write_request(request, request_revision=1)
    artifacts.write_render(page_number=1, render_revision=1, image=b"complete-page")
    artifacts.write_preflight(preflight)

    assert artifacts.read_source() == source
    assert artifacts.read_brief() == brief
    assert artifacts.read_adaptation() == adaptation
    assert artifacts.read_plan() == plan
    assert artifacts.read_page(1) == page
    assert artifacts.read_book_edition() == edition
    assert artifacts.read_request(1, 1) == request
    assert artifacts.read_render(1, 1) == b"complete-page"
    assert artifacts.read_preflight() == preflight
    assert artifacts.page_path(1).relative_to(tmp_path).as_posix() == (
        "plan/pages/page_001.json"
    )
    assert artifacts.request_path(1, 1).relative_to(tmp_path).as_posix() == (
        "draw/pages/page_001/request_001.json"
    )
    assert artifacts.render_path(1, 1).relative_to(tmp_path).as_posix() == (
        "draw/pages/page_001/render_001.png"
    )


def test_target_artifact_reads_do_not_fall_back_to_legacy_paths(tmp_path) -> None:
    legacy = tmp_path / "compose" / "pages" / "page_001.json"
    legacy.parent.mkdir(parents=True)
    legacy.write_text(_comic_page().model_dump_json())

    with pytest.raises(ArtifactMissing) as exc:
        TargetArtifacts(tmp_path).read_page(1)

    assert exc.value.path == tmp_path / "plan" / "pages" / "page_001.json"
