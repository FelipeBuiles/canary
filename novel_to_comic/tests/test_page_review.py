from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path

import pytest
from pydantic import ValidationError

from novel_to_comic.models.adaptation import LetteringItem
from novel_to_comic.models.draw import (
    BookEdition,
    CompletePageProviderResult,
    OCRExtraction,
    OCRTextObservation,
    ObservedRegion,
    PageCapabilityProfile,
    PageIssue,
    PageRenderRevision,
    RetryProvenance,
)
from novel_to_comic.models.page import ComicPage, PageContent
from novel_to_comic.models.page import (
    ApprovedVisualReference,
    ApprovedVisualReferenceInventory,
)
from novel_to_comic.page_drawing import (
    ApprovedReferenceFile,
    VertexCompletePageAdapter,
    compile_page_generation_request,
    correct_complete_page,
)
from novel_to_comic.page_review import (
    accept_editorial_page_issue,
    analyze_page_render,
    build_correction_request,
    record_analysis_issues,
    record_page_issue,
    request_issue_correction,
    summarize_page_issues,
)
from novel_to_comic.target_artifacts import TargetArtifacts
from novel_to_comic.usage import ApiResult, UsageRecord


def _page() -> ComicPage:
    return ComicPage(
        revision=1,
        page_number=34,
        adaptation_revision=2,
        adaptation_sha256="a" * 64,
        page_turn_role="reveal",
        spread_role="right",
        emphasis="peak",
        density_intent="standard",
        layout_intent="A descending sequence of three observed regions.",
        content=[
            PageContent(
                id="content-1",
                order=1,
                beat_ids=["beat-1"],
                visual_intent="Johansen opens the idol chamber.",
                lettering=[
                    LetteringItem(
                        id="letter-1",
                        kind="caption",
                        text="The door opened…",
                        source_unit_ids=["source-1"],
                    ),
                    LetteringItem(
                        id="letter-2",
                        kind="dialogue",
                        text="It wasn't a dream.",
                        speaker="Johansen",
                        source_unit_ids=["source-2"],
                    ),
                ],
                entity_ids=["johansen"],
            )
        ],
        reading_order=["content-1", "letter-1", "letter-2"],
    )


def _render(
    *,
    revision: int = 1,
    parent: int | None = None,
    image: bytes = b"page-34",
) -> PageRenderRevision:
    return PageRenderRevision(
        page_number=34,
        revision=revision,
        parent_revision=parent,
        comic_page_revision=1,
        comic_page_sha256=_page().content_sha256,
        request_sha256=str(revision) * 64,
        image_sha256=hashlib.sha256(image).hexdigest(),
        width=2048,
        height=3072,
        provider="vertex-multimodal",
        model="gemini-3-pro-image-preview",
        latency_ms=100,
        cost_usd="0.30",
    )


class _OCR:
    """A stub whose observations each carry their own detected region.

    Real page OCR reports one region per balloon, and that geometry is what
    lets Draw tell a genuine reading-order defect from an engine's sweep order.
    ``shared_region`` models the opposite case: an engine that cannot separate
    the balloons, and therefore cannot prove anything about their order.
    """

    def __init__(self, *texts: str, shared_region: bool = False) -> None:
        self.texts = texts
        self.shared_region = shared_region

    def _region_id(self, index: int) -> str:
        return "region-1" if self.shared_region else f"region-{index}"

    async def extract(self, image: bytes) -> ApiResult[OCRExtraction]:
        assert image
        count = 1 if self.shared_region else len(self.texts)
        band = 1 / max(1, count)
        regions = tuple(
            ObservedRegion(
                id=self._region_id(index),
                polygon=(
                    (0.0, (index - 1) * band),
                    (1.0, (index - 1) * band),
                    (1.0, index * band),
                    (0.0, index * band),
                ),
            )
            for index in range(1, count + 1)
        )
        return ApiResult(
            value=OCRExtraction(
                lettering=[
                    OCRTextObservation(
                        id=f"ocr-{index}",
                        text=text,
                        detected_region_id=self._region_id(index),
                    )
                    for index, text in enumerate(self.texts, start=1)
                ],
                observed_regions=regions,
                observed_reading_order=[region.id for region in regions],
            ),
            usage=UsageRecord(
                provider="gemini",
                model="ocr-balanced",
                operation="text",
                input_tokens=1200,
                output_tokens=80,
            ),
        )


def _analyze(**kwargs):
    """Render analysis reads the page through an async provider seam."""
    return asyncio.run(analyze_page_render(**kwargs)).analysis


def test_cthulhu_page_34_exact_lettering_is_verified_without_mutating_page(
    tmp_path: Path,
) -> None:
    page = _page()
    artifacts = TargetArtifacts(tmp_path)
    analysis = _analyze(
        page=page,
        render=_render(),
        image=b"page-34",
        ocr=_OCR("The door opened…", "It wasn't a dream."),
        artifacts=artifacts,
    )

    assert analysis.lettering_valid is True
    assert analysis.invariant_failures == ()
    assert [match.lettering_item_id for match in analysis.lettering_matches] == [
        "letter-1",
        "letter-2",
    ]
    assert artifacts.read_analysis(34, 1) == analysis
    assert page == _page()
    assert not hasattr(page.content[0], "observed_region")


def test_ocr_normalizes_only_the_explicit_punctuation_equivalences(
    tmp_path: Path,
) -> None:
    analysis = _analyze(
        page=_page(),
        render=_render(),
        image=b"page-34",
        ocr=_OCR('The door opened...', "It wasn’t a dream."),
        artifacts=TargetArtifacts(tmp_path),
    )

    assert analysis.lettering_valid is True
    assert analysis.punctuation_policy == "typographic_lettering_v2"

    wrong_case = _analyze(
        page=_page(),
        render=_render(revision=2, parent=1, image=b"page-34-case"),
        image=b"page-34-case",
        ocr=_OCR("The door opened…", "It Wasn't a dream."),
        artifacts=TargetArtifacts(tmp_path / "case"),
    )
    assert [failure.code for failure in wrong_case.invariant_failures] == [
        "misspelled_lettering"
    ]


@pytest.mark.parametrize(
    ("observed", "expected_code"),
    [
        (("The door opened…",), "missing_lettering"),
        (
            ("The door opened…", "It wasn't a dream.", "INVENTED"),
            "invented_lettering",
        ),
        (
            (
                "The door opened…",
                "It wasn't a dream.",
                "It wasn't a dream.",
            ),
            "duplicated_lettering",
        ),
        (
            ("The door opened…", "It wasn't the dream."),
            "misspelled_lettering",
        ),
        (
            ("It wasn't a dream.", "The door opened…"),
            "reordered_lettering",
        ),
    ],
)
def test_ocr_mismatches_are_blocking_draw_invariants(
    tmp_path: Path,
    observed: tuple[str, ...],
    expected_code: str,
) -> None:
    analysis = _analyze(
        page=_page(),
        render=_render(),
        image=b"page-34",
        ocr=_OCR(*observed),
        artifacts=TargetArtifacts(tmp_path),
    )

    assert analysis.lettering_valid is False
    assert expected_code in [failure.code for failure in analysis.invariant_failures]
    assert all(failure.owner_stage == "draw" for failure in analysis.invariant_failures)
    assert all(failure.blocking for failure in analysis.invariant_failures)


@pytest.mark.parametrize(
    "observed",
    [
        # An OCR engine reads an em dash as a hyphen and a curly apostrophe as
        # a straight one; a letterer wraps a balloon across lines. None of that
        # changes the words, so none of it may block a page.
        ("The door opened...", "It wasn't a dream."),
        ("The door opened…", "It wasn’t\na dream."),
        ("The door  opened…", " It wasn't a dream. "),
    ],
)
def test_formatting_variance_between_letterer_and_ocr_is_not_a_defect(
    tmp_path: Path,
    observed: tuple[str, ...],
) -> None:
    analysis = _analyze(
        page=_page(),
        render=_render(),
        image=b"page-34",
        ocr=_OCR(*observed),
        artifacts=TargetArtifacts(tmp_path),
    )

    assert analysis.invariant_failures == ()
    assert analysis.lettering_valid is True
    assert analysis.recognized_lettering["letter-1"] == observed[0]


def test_em_dash_wording_survives_an_ocr_hyphen(tmp_path: Path) -> None:
    page = _page()
    dashed = page.model_copy(
        update={
            "content": (
                page.content[0].model_copy(
                    update={
                        "lettering": (
                            page.content[0].lettering[0].model_copy(
                                update={"text": "The door opened—slowly."}
                            ),
                            page.content[0].lettering[1],
                        )
                    }
                ),
            )
        }
    )
    dashed = ComicPage.model_validate(
        {**dashed.model_dump(), "content_sha256": ""}
    )
    render = _render().model_copy(
        update={"comic_page_sha256": dashed.content_sha256}
    )
    render = PageRenderRevision.model_validate(render.model_dump())

    analysis = _analyze(
        page=dashed,
        render=render,
        image=b"page-34",
        ocr=_OCR("The door opened-slowly.", "It wasn't a dream."),
        artifacts=TargetArtifacts(tmp_path),
    )

    assert analysis.invariant_failures == ()


def test_ocr_sweep_order_alone_is_an_editorial_issue_not_a_blocking_failure(
    tmp_path: Path,
) -> None:
    # Both balloons landed in one detected region: the engine's own ordering is
    # a heuristic sweep and proves nothing about the rendered reading order.
    analysis = _analyze(
        page=_page(),
        render=_render(),
        image=b"page-34",
        ocr=_OCR(
            "It wasn't a dream.",
            "The door opened…",
            shared_region=True,
        ),
        artifacts=TargetArtifacts(tmp_path),
    )

    assert analysis.invariant_failures == ()
    assert [issue.code for issue in analysis.editorial_issues] == [
        "unverified_lettering_order"
    ]
    assert all(not issue.blocking for issue in analysis.editorial_issues)
    assert [match.lettering_item_id for match in analysis.lettering_matches] == [
        "letter-1",
        "letter-2",
    ]


def test_ocr_invariant_failures_become_page_issues_that_gate_book(
    tmp_path: Path,
) -> None:
    # Without this the failure lives only in the derived analysis, and Continue
    # to Book stays enabled on a page whose lettering is provably wrong.
    artifacts = TargetArtifacts(tmp_path)
    analysis = _analyze(
        page=_page(),
        render=_render(),
        image=b"page-34",
        ocr=_OCR("The door opened…"),
        artifacts=artifacts,
    )
    recorded = record_analysis_issues(artifacts, analysis)

    assert [issue.issue_type for issue in recorded] == ["missing_lettering"]
    assert all(issue.classification == "invariant_failure" for issue in recorded)
    summary = summarize_page_issues(artifacts, page_number=34)
    assert summary.blocking_issue_ids == (recorded[0].id,)
    assert summary.can_continue is False
    # Re-analysing the same immutable render must not duplicate the issue.
    assert record_analysis_issues(artifacts, analysis) == ()


def test_invariant_page_issue_cannot_be_deliberately_accepted() -> None:
    with pytest.raises(ValidationError, match="invariant"):
        PageIssue(
            id="issue-ocr",
            issue_type="lettering_mismatch",
            classification="invariant_failure",
            correction_owner="draw",
            page_number=34,
            render_revision=1,
            evidence=["OCR differs from canonical lettering."],
            requested_correction="Render the canonical lettering exactly.",
            lettering_item_ids=["letter-1"],
            status="accepted",
        )


def test_page_issues_are_reviewed_by_exception_and_copy_changes_route_to_adapt(
    tmp_path: Path,
) -> None:
    artifacts = TargetArtifacts(tmp_path)
    render_issue = PageIssue(
        id="issue-art",
        issue_type="appearance_state",
        classification="editorial_issue",
        correction_owner="draw",
        page_number=34,
        render_revision=1,
        evidence=["Johansen's coat is the wrong color."],
        requested_correction="Correct the coat while preserving the complete page.",
        detected_region_ids=["region-1"],
        entity_ids=["johansen"],
        status="open",
    )
    copy_issue = PageIssue(
        id="issue-copy",
        issue_type="copy_change",
        classification="editorial_issue",
        correction_kind="copy_change",
        correction_owner="adapt",
        page_number=34,
        render_revision=1,
        evidence=["The author wants different dialogue."],
        requested_correction="Change the words to a new sentence.",
        lettering_item_ids=["letter-2"],
        status="open",
    )
    record_page_issue(artifacts, render_issue)
    record_page_issue(artifacts, copy_issue)

    summary = summarize_page_issues(artifacts)
    upstream = request_issue_correction(copy_issue, profile=_profile())

    assert summary.unresolved_issue_ids == ("issue-art", "issue-copy")
    assert summary.can_continue is True
    assert upstream.owner_stage == "adapt"
    assert upstream.requires_replan is True
    assert "lettering" not in upstream.model_dump()

    accept_editorial_page_issue(
        artifacts,
        issue_id="issue-art",
        page_number=34,
    )
    accepted_summary = summarize_page_issues(artifacts)
    assert accepted_summary.unresolved_issue_ids == ("issue-copy",)
    assert accepted_summary.accepted_editorial_issue_ids == ("issue-art",)


def _profile() -> PageCapabilityProfile:
    return PageCapabilityProfile(
        id="profile",
        provider="vertex-multimodal",
        model="gemini-3-pro-image-preview",
        max_image_references=4,
        reference_ordering="ordered",
        editing_modes=["instructed", "region_targeted"],
        output_width=2048,
        output_height=3072,
        max_prompt_characters=32_000,
        retry_semantics="idempotent_request",
        price_per_page_usd="0.30",
    )


def test_region_target_creates_a_complete_page_correction_request_only() -> None:
    issue = PageIssue(
        id="issue-region",
        issue_type="artwork",
        classification="editorial_issue",
        correction_owner="draw",
        page_number=34,
        render_revision=1,
        evidence=["A hand has six fingers."],
        requested_correction="Correct the hand.",
        detected_region_ids=["region-1"],
        status="open",
    )

    correction = request_issue_correction(issue, profile=_profile())

    assert correction.mode == "region_targeted"
    assert correction.artifact_kind == "complete_page"
    assert correction.parent_render_revision == 1
    assert not hasattr(correction, "panel_number")

    with pytest.raises(ValueError, match="region-targeted"):
        request_issue_correction(
            issue,
            profile=_profile().model_copy(update={"editing_modes": ("instructed",)}),
        )


class _Transport:
    async def generate(self, request):
        assert request.edit_source_bytes == b"parent-complete-page"
        return CompletePageProviderResult(
            artifact_kind="complete_page",
            image_bytes=b"corrected-complete-page",
            media_type="image/png",
            width=2048,
            height=3072,
            latency_ms=120,
            provider_request_id="provider-correction",
            actual_provider_model="vertex_ai/gemini-3-pro-image-preview",
            usage=UsageRecord(
                provider="gemini",
                model="gemini-3-pro-image-preview",
                operation="image",
                image_count=1,
                cost_usd=0.30,
                cost_source="provider",
            ),
        )


def test_correction_supersedes_without_overwriting_parent_or_creating_panels(
    tmp_path: Path,
) -> None:
    artifacts = TargetArtifacts(tmp_path)
    parent_image = b"parent-complete-page"
    parent = _render(image=parent_image)
    artifacts.write_render(
        page_number=34,
        render_revision=1,
        image=parent_image,
    )
    issue = PageIssue(
        id="issue-region",
        issue_type="artwork",
        classification="editorial_issue",
        correction_owner="draw",
        page_number=34,
        render_revision=1,
        evidence=["A hand has six fingers."],
        requested_correction="Correct the hand.",
        detected_region_ids=["region-1"],
        status="open",
    )
    record_page_issue(artifacts, issue)
    _analyze(
        page=_page(),
        render=parent,
        image=parent_image,
        ocr=_OCR("The door opened…", "It wasn't a dream."),
        artifacts=artifacts,
    )
    correction = build_correction_request(
        issue=issue,
        page=_page(),
        parent=parent,
        profile=_profile(),
        artifacts=artifacts,
    )
    reference_path = tmp_path / "johansen.png"
    reference_path.write_bytes(b"johansen-reference")
    compiled = compile_page_generation_request(
        _page(),
        BookEdition(revision=1, id="edition", capability_profile=_profile()),
        ApprovedVisualReferenceInventory(
            references=[
                ApprovedVisualReference(
                    id="johansen-ref",
                    entity_id="johansen",
                    visual_anchor="Johansen: salt-stiff coat; scar over left eye",
                )
            ]
        ),
        {
            "johansen-ref": ApprovedReferenceFile(
                reference_id="johansen-ref",
                path=reference_path,
                media_type="image/png",
            )
        },
        retry=RetryProvenance(attempt=1),
        correction=correction,
        edit_source_bytes=parent_image,
    )

    result = asyncio.run(
        correct_complete_page(
            compiled,
            issue=issue,
            adapter=VertexCompletePageAdapter(_Transport()),
            artifacts=artifacts,
            page=_page(),
            request_revision=2,
            render_revision=2,
        )
    )

    assert result.render.revision == 2
    assert result.render.parent_revision == 1
    assert compiled.request.correction == correction
    assert "Correct the hand." in compiled.request.prompt
    assert artifacts.read_render(34, 1) == parent_image
    assert artifacts.read_render(34, 2) == b"corrected-complete-page"
    assert artifacts.read_issues(34)[0].resolution_revision == 2
    assert not list((tmp_path / "draw").rglob("*panel*"))
