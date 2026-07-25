from __future__ import annotations

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
from novel_to_comic.models.source import SourceDocument, SourceScene, SourceUnit
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
)
from novel_to_comic.models.finish import (
    FinishPreflight,
    PreflightPage,
)
from novel_to_comic.target_artifacts import ArtifactMissing, TargetArtifacts


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


def _approved_brief() -> AdaptationBrief:
    return AdaptationBrief(
        revision=1,
        status="approved",
        story_promises=["The investigator's certainty must collapse."],
        themes=["Knowledge has a cost."],
        point_of_view="First-person retrospective.",
        tone="Mounting cosmic dread.",
        protected_language=["the most merciful thing in the world"],
        transformation_level="medium_specific",
        desired_emphasis=["Preserve discovery, reaction, and aftermath."],
        target_page_min=32,
        target_page_max=40,
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
        provider="vertex",
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
        profile=_page_profile(),
        prompt="Render one complete comic page.",
        references=[
            PageReference(
                id="character_witness",
                order=1,
                media_type="image/png",
                content_sha256="a" * 64,
                visual_anchor="weathered face; left eyebrow scar",
            )
        ],
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
