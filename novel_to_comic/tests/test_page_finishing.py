from __future__ import annotations

import asyncio
import hashlib
import io
import zipfile
from pathlib import Path
from unittest.mock import patch

import pytest
from PIL import Image
from pypdf import PdfReader

from novel_to_comic.models.adaptation import (
    AdaptationLedgerEntry,
    AdaptedBeat,
    AppearanceChange,
    BookAdaptation,
    LetteringItem,
    NarrativeTreatment,
)
from novel_to_comic.models.draw import (
    BookEdition,
    LetteringMatch,
    OCRTextObservation,
    PageCapabilityProfile,
    PageGenerationProvenance,
    PageIssue,
    PageRenderRevision,
    RenderAnalysis,
)
from novel_to_comic.models.finish import FinishProductionSpec
from novel_to_comic.models.page import (
    BookPlan,
    ComicPage,
    PageContent,
    PlannedPageRevision,
)
from novel_to_comic.models.validation import InvariantFailure
from novel_to_comic.page_finishing import _appearance_diagnostics, finish_book
from novel_to_comic.target_artifacts import TargetArtifacts
from novel_to_comic.usage import UsageRecord


def _png_bytes(
    color: tuple[int, int, int],
    *,
    size: tuple[int, int] = (120, 180),
) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, color).save(buffer, "PNG")
    return buffer.getvalue()


def _adaptation() -> BookAdaptation:
    return BookAdaptation(
        revision=1,
        source_sha256="s" * 64,
        brief_revision=1,
        brief_sha256="b" * 64,
        treatment=NarrativeTreatment(causal_spine=["The door opens."]),
        beats=[
            AdaptedBeat(
                id="beat-1",
                order=1,
                summary="The door opens.",
                narrative_function="initial",
                source_unit_ids=["source-1"],
                lettering=[
                    LetteringItem(
                        id="letter-1",
                        kind="caption",
                        text="The door opened.",
                        source_unit_ids=["source-1"],
                    )
                ],
            )
        ],
        ledger=[
            AdaptationLedgerEntry(
                source_unit_id="source-1",
                disposition="caption",
                adapted_beat_ids=["beat-1"],
                preserved_function="The initiating event remains explicit.",
            )
        ],
    )


def _page(adaptation: BookAdaptation) -> ComicPage:
    return ComicPage(
        revision=1,
        page_number=1,
        adaptation_revision=adaptation.revision,
        adaptation_sha256=adaptation.content_sha256,
        emphasis="initial",
        density_intent="standard",
        content=[
            PageContent(
                id="content-1",
                order=1,
                beat_ids=["beat-1"],
                visual_intent="A door opens into darkness.",
                lettering=adaptation.beats[0].lettering,
            )
        ],
        reading_order=["content-1", "letter-1"],
    )


def _edition() -> BookEdition:
    return BookEdition(
        revision=1,
        id="edition-1",
        capability_profile=PageCapabilityProfile(
            id="profile-1",
            provider="deterministic-fixture",
            model="fixture-page-model",
            max_image_references=4,
            reference_ordering="ordered",
            editing_modes=["instructed", "region_targeted"],
            output_width=120,
            output_height=180,
            max_prompt_characters=10_000,
            retry_semantics="bounded_submission",
            price_per_page_usd="0",
        ),
    )


def _write_valid_book(tmp_path: Path) -> tuple[TargetArtifacts, bytes]:
    artifacts = TargetArtifacts(tmp_path)
    adaptation = _adaptation()
    page = _page(adaptation)
    image = _png_bytes((15, 35, 55))
    image_sha256 = hashlib.sha256(image).hexdigest()
    render = PageRenderRevision(
        page_number=1,
        revision=1,
        comic_page_revision=page.revision,
        comic_page_sha256=page.content_sha256,
        request_sha256="r" * 64,
        image_sha256=image_sha256,
        width=120,
        height=180,
        provider="deterministic-fixture",
        model="fixture-page-model",
        latency_ms=1,
        cost_usd="0",
    )
    analysis = RenderAnalysis(
        page_number=1,
        render_revision=1,
        render_image_sha256=image_sha256,
        recognized_lettering={"letter-1": "The door opened."},
        ocr_observations=[
            OCRTextObservation(id="ocr-1", text="The door opened.")
        ],
        lettering_matches=[
            LetteringMatch(
                lettering_item_id="letter-1",
                observation_id="ocr-1",
                canonical_text="The door opened.",
                observed_text="The door opened.",
            )
        ],
    )
    artifacts.write_adaptation(adaptation)
    artifacts.write_page(page)
    artifacts.write_plan(
        BookPlan(
            revision=1,
            adaptation_revision=adaptation.revision,
            adaptation_sha256=adaptation.content_sha256,
            target_page_min=1,
            target_page_max=1,
            pages=[
                PlannedPageRevision(
                    page_number=1,
                    revision=page.revision,
                    content_sha256=page.content_sha256,
                )
            ],
        )
    )
    artifacts.write_book_edition(_edition())
    artifacts.write_render(page_number=1, render_revision=1, image=image)
    artifacts.write_provenance(
        PageGenerationProvenance(
            render=render,
            usage=UsageRecord(
                provider="deterministic-fixture",
                model="fixture-page-model",
                operation="image",
                image_count=1,
                cost_usd=0,
            ),
        )
    )
    artifacts.write_analysis(analysis)
    artifacts.write_issues(1, ())
    return artifacts, image


def _write_corrected_revision(
    artifacts: TargetArtifacts,
    *,
    revision: int,
    parent_revision: int,
    color: tuple[int, int, int],
) -> None:
    page = artifacts.read_page(1)
    image = _png_bytes(color)
    image_sha256 = hashlib.sha256(image).hexdigest()
    render = PageRenderRevision(
        page_number=1,
        revision=revision,
        parent_revision=parent_revision,
        comic_page_revision=page.revision,
        comic_page_sha256=page.content_sha256,
        request_sha256=str(revision) * 64,
        image_sha256=image_sha256,
        width=120,
        height=180,
        provider="deterministic-fixture",
        model="fixture-page-model",
        latency_ms=1,
        cost_usd="0",
    )
    artifacts.write_render(
        page_number=1,
        render_revision=revision,
        image=image,
    )
    artifacts.write_provenance(
        PageGenerationProvenance(
            render=render,
            usage=artifacts.read_provenance(1, 1).usage,
        )
    )
    artifacts.write_analysis(
        RenderAnalysis(
            page_number=1,
            render_revision=revision,
            render_image_sha256=image_sha256,
            recognized_lettering={"letter-1": "The door opened."},
            ocr_observations=[
                OCRTextObservation(id="ocr-1", text="The door opened.")
            ],
            lettering_matches=[
                LetteringMatch(
                    lettering_item_id="letter-1",
                    observation_id="ocr-1",
                    canonical_text="The door opened.",
                    observed_text="The door opened.",
                )
            ],
        )
    )


def test_finish_exports_complete_page_renders_as_optimized_jpegs(
    tmp_path: Path,
) -> None:
    artifacts, _source_image = _write_valid_book(tmp_path)

    result = finish_book(
        artifacts,
        production=FinishProductionSpec(
            canvas_width=120,
            canvas_height=180,
            bleed_px=10,
            dpi=300,
        ),
    )

    assert result.preflight.ready_to_export is True
    assert [package.format for package in result.packages] == ["pdf", "cbz"]
    assert result.preflight.pages[0].bleed_px == 10
    assert result.preflight.pages[0].trim_width == 100
    assert result.preflight.pages[0].trim_height == 160
    assert result.preflight.pages[0].color_profile == "sRGB"
    normalized = artifacts.normalized_page_path(1).read_bytes()
    with Image.open(io.BytesIO(normalized)) as finished:
        assert finished.format == "JPEG"
        assert finished.size == (120, 180)
        assert finished.info["icc_profile"]
    with zipfile.ZipFile(artifacts.export_path("cbz")) as archive:
        assert archive.namelist() == ["page_001.jpg"]
        assert archive.read("page_001.jpg") == normalized
        with Image.open(io.BytesIO(archive.read("page_001.jpg"))) as page:
            assert page.format == "JPEG"
            assert page.size == (120, 180)
    pdf = PdfReader(artifacts.export_path("pdf"))
    assert len(pdf.pages) == 1
    assert float(pdf.pages[0].mediabox.width) == pytest.approx(28.8, abs=0.02)
    assert float(pdf.pages[0].mediabox.height) == pytest.approx(43.2, abs=0.02)
    assert artifacts.read_preflight() == result.preflight


def test_finish_preflight_can_run_without_packaging_or_clearing_exports(
    tmp_path: Path,
) -> None:
    artifacts, _ = _write_valid_book(tmp_path)
    initial = finish_book(
        artifacts,
        production=FinishProductionSpec(canvas_width=120, canvas_height=180),
        formats=("pdf",),
    )
    existing_export = artifacts.export_path("pdf")
    existing_bytes = existing_export.read_bytes()

    result = finish_book(
        artifacts,
        production=FinishProductionSpec(canvas_width=120, canvas_height=180),
        formats=(),
        clear_derived_outputs=False,
    )

    assert result.preflight.ready_to_export is True
    assert result.packages == initial.packages
    assert existing_export.read_bytes() == existing_bytes
    assert artifacts.read_preflight() == result.preflight


def test_finish_inputs_invalidate_persisted_preflight_and_exports(
    tmp_path: Path,
) -> None:
    artifacts, _ = _write_valid_book(tmp_path)
    finish_book(
        artifacts,
        production=FinishProductionSpec(canvas_width=120, canvas_height=180),
        formats=("pdf",),
    )

    assert artifacts.preflight_path.exists()
    assert artifacts.export_path("pdf").exists()

    # Review decisions are Finish inputs just as much as the page bytes are.
    artifacts.write_issues(1, ())

    assert not artifacts.preflight_path.exists()
    assert not artifacts.export_path("pdf").exists()


def test_stale_render_blocks_export_and_emits_complete_page_draw_request(
    tmp_path: Path,
) -> None:
    artifacts, _ = _write_valid_book(tmp_path)
    original = artifacts.read_page(1)
    revised_payload = original.model_dump()
    revised_payload["revision"] = 2
    revised_payload["content_sha256"] = ""
    revised_payload["content"][0]["visual_intent"] = "The door opens onto a stair."
    revised = ComicPage.model_validate(revised_payload)
    artifacts.write_page(revised)
    plan = artifacts.read_plan()
    artifacts.write_plan(
        BookPlan.model_validate(
            plan.model_copy(
                update={
                    "content_sha256": "",
                    "pages": (
                        PlannedPageRevision(
                            page_number=1,
                            revision=2,
                            content_sha256=revised.content_sha256,
                        ),
                    ),
                }
            ).model_dump()
        )
    )

    with patch(
        "novel_to_comic.page_drawing.GoogleVertexCompletePageTransport.generate",
        side_effect=AssertionError("Finish must not call an image provider"),
    ):
        result = finish_book(
            artifacts,
            production=FinishProductionSpec(
                canvas_width=120,
                canvas_height=180,
                bleed_px=10,
            ),
        )

    assert result.preflight.ready_to_export is False
    assert result.packages == ()
    assert not artifacts.export_path("pdf").exists()
    assert result.preflight.correction_requests[0].owner_stage == "draw"
    assert result.preflight.correction_requests[0].artifact_kind == "complete_page"
    assert "stale_page_render" in (
        result.preflight.correction_requests[0].failure_codes
    )
    assert not (tmp_path / "compose").exists()


def test_missing_ocr_blocks_export_without_requesting_redraw(tmp_path: Path) -> None:
    artifacts, _ = _write_valid_book(tmp_path)
    artifacts.analysis_path(1, 1).unlink()
    result = finish_book(
        artifacts, formats=(),
        production=FinishProductionSpec(canvas_width=120, canvas_height=180, bleed_px=10),
    )
    assert not result.preflight.ready_to_export
    assert {failure.code for failure in result.preflight.pages[0].invariant_failures} == {"ocr_evidence_missing"}
    assert result.preflight.correction_requests == ()


def test_inexact_ocr_and_wrong_dimensions_block_without_normalizing_pixels(
    tmp_path: Path,
) -> None:
    artifacts, _ = _write_valid_book(tmp_path)
    bad_analysis = artifacts.read_analysis(1, 1).model_copy(
        update={"recognized_lettering": {}, "lettering_matches": (), "ocr_observations": ()}
    )
    artifacts.analysis_path(1, 1).write_text(bad_analysis.model_dump_json())

    result = finish_book(
        artifacts,
        production=FinishProductionSpec(
            canvas_width=100,
            canvas_height=160,
            bleed_px=5,
        ),
    )

    codes = {
        failure.code
        for failure in result.preflight.pages[0].invariant_failures
    }
    assert {"lettering_mismatch", "page_render_dimensions"} <= codes
    assert set(result.preflight.correction_requests[0].failure_codes) >= codes
    assert not artifacts.normalized_page_path(1).exists()
    assert not artifacts.export_path("cbz").exists()


def test_dismissed_draw_finding_does_not_block_finish_preflight(
    tmp_path: Path,
) -> None:
    artifacts, _ = _write_valid_book(tmp_path)
    failure = InvariantFailure(
        id="draw-page-001-render-001-misspelled_lettering",
        owner_stage="draw",
        code="misspelled_lettering",
        message="OCR lettering does not exactly match canonical wording.",
        evidence=("Visual review confirmed the detector was a false positive.",),
    )
    analysis = artifacts.read_analysis(1, 1)
    artifacts.analysis_path(1, 1).write_text(
        analysis.model_copy(
            update={"invariant_failures": (failure,), "lettering_matches": ()}
        ).model_dump_json()
    )
    artifacts.write_issues(
        1,
        (
            PageIssue(
                id=f"page-issue-{failure.id}",
                issue_type=failure.code,
                classification="invariant_failure",
                page_number=1,
                render_revision=1,
                evidence=failure.evidence,
                requested_correction="Render the canonical lettering exactly.",
                status="dismissed",
                dismissal_reason="Verified as a detector false positive.",
            ),
        ),
    )

    result = finish_book(
        artifacts,
        production=FinishProductionSpec(canvas_width=120, canvas_height=180),
    )

    assert result.preflight.ready_to_export is True
    assert result.preflight.pages[0].invariant_failures == ()


def test_repeated_beat_states_are_not_replayed_or_rejected() -> None:
    base = _adaptation()
    beat = base.beats[0].model_copy(
        update={
            "appearance_changes": (
                AppearanceChange(
                    entity_id="ward",
                    to_state_id="ward-wet",
                    description="Ward's coat is soaked.",
                ),
                AppearanceChange(
                    entity_id="ward",
                    from_state_id="ward-wet",
                    to_state_id="ward-dry",
                    description="Ward's coat dries.",
                ),
            )
        }
    )
    adaptation = base.model_copy(update={"beats": (beat,)})
    page = ComicPage(
        revision=1,
        page_number=1,
        adaptation_revision=adaptation.revision,
        adaptation_sha256=adaptation.content_sha256,
        emphasis="initial",
        density_intent="standard",
        content=[
            PageContent(
                id="content-1",
                order=1,
                beat_ids=["beat-1"],
                visual_intent="Ward is soaked.",
                entity_ids=["ward"],
                appearance_states={"ward": "ward-wet"},
            ),
            PageContent(
                id="content-2",
                order=2,
                beat_ids=["beat-1"],
                visual_intent="Ward is dry.",
                entity_ids=["ward"],
                appearance_states={"ward": "ward-dry"},
            ),
        ],
        reading_order=["content-1", "content-2"],
    )

    assert _appearance_diagnostics(adaptation, (page,)) == {}


def test_deliberately_accepted_editorial_issue_is_recorded_but_open_one_blocks(
    tmp_path: Path,
) -> None:
    artifacts, _ = _write_valid_book(tmp_path)
    accepted = PageIssue(
        id="issue-accepted",
        issue_type="composition",
        page_number=1,
        render_revision=1,
        evidence=["The reveal is quieter than intended."],
        requested_correction="Increase the visual emphasis.",
        status="accepted",
    )
    artifacts.write_issues(1, (accepted,))

    accepted_result = finish_book(
        artifacts,
        production=FinishProductionSpec(
            canvas_width=120,
            canvas_height=180,
            bleed_px=10,
        ),
    )

    assert accepted_result.preflight.ready_to_export is True
    assert accepted_result.preflight.pages[0].accepted_editorial_issue_ids == (
        "issue-accepted",
    )

    open_issue = accepted.model_copy(
        update={"id": "issue-open", "status": "open"}
    )
    artifacts.write_issues(1, (accepted, open_issue))
    open_result = finish_book(
        artifacts,
        production=FinishProductionSpec(
            canvas_width=120,
            canvas_height=180,
            bleed_px=10,
        ),
    )

    assert open_result.preflight.ready_to_export is False
    assert open_result.preflight.pages[0].unresolved_editorial_issue_ids == (
        "issue-open",
    )
    assert not artifacts.export_path("pdf").exists()
    assert not artifacts.export_path("cbz").exists()


def test_active_page_manifest_order_mismatch_blocks_instead_of_exporting(
    tmp_path: Path,
) -> None:
    artifacts, _ = _write_valid_book(tmp_path)
    payload = artifacts.read_page(1).model_dump()
    payload["content_sha256"] = ""
    payload["page_number"] = 2
    artifacts.page_path(1).write_text(
        ComicPage.model_validate(payload).model_dump_json()
    )

    result = finish_book(
        artifacts,
        production=FinishProductionSpec(
            canvas_width=120,
            canvas_height=180,
            bleed_px=10,
        ),
    )

    assert result.preflight.ready_to_export is False
    assert result.preflight.pages[0].page_number == 1
    assert "active_page_order" in {
        failure.code
        for failure in result.preflight.pages[0].invariant_failures
    }
    assert not artifacts.export_path("pdf").exists()


def test_cross_page_appearance_state_blocks_export(
    tmp_path: Path,
) -> None:
    artifacts, first_image = _write_valid_book(tmp_path)
    adaptation_payload = artifacts.read_adaptation().model_dump()
    adaptation_payload["content_sha256"] = ""
    adaptation_payload["beats"][0]["appearance_changes"] = [
        AppearanceChange(
            entity_id="ward",
            to_state_id="ward-wet",
            description="Rain soaks Ward's coat.",
        ).model_dump(mode="json")
    ]
    adaptation_payload["beats"] = [
        *adaptation_payload["beats"],
        AdaptedBeat(
            id="beat-2",
            order=2,
            summary="Ward descends the stair.",
            narrative_function="prolongation",
            source_unit_ids=["source-2"],
        ).model_dump(mode="json"),
    ]
    adaptation_payload["ledger"] = [
        *adaptation_payload["ledger"],
        AdaptationLedgerEntry(
            source_unit_id="source-2",
            disposition="depicted",
            adapted_beat_ids=["beat-2"],
            preserved_function="Ward's descent remains explicit.",
        ).model_dump(mode="json"),
    ]
    adaptation = BookAdaptation.model_validate(adaptation_payload)
    artifacts.write_adaptation(adaptation)

    first_payload = artifacts.read_page(1).model_dump()
    first_payload.update(
        {
            "content_sha256": "",
            "adaptation_revision": adaptation.revision,
            "adaptation_sha256": adaptation.content_sha256,
        }
    )
    first_payload["content"][0]["entity_ids"] = ["ward"]
    first_payload["content"][0]["appearance_states"] = {"ward": "ward-wet"}
    first_page = ComicPage.model_validate(first_payload)
    second_page = ComicPage(
        revision=1,
        page_number=2,
        adaptation_revision=adaptation.revision,
        adaptation_sha256=adaptation.content_sha256,
        emphasis="prolongation",
        density_intent="sparse",
        content=[
            PageContent(
                id="content-2",
                order=1,
                beat_ids=["beat-2"],
                visual_intent="Ward descends, but his coat is shown dry.",
                entity_ids=["ward"],
            )
        ],
        reading_order=["content-2"],
    )
    artifacts.write_page(first_page)
    artifacts.write_page(second_page)
    artifacts.write_plan(
        BookPlan(
            revision=2,
            adaptation_revision=adaptation.revision,
            adaptation_sha256=adaptation.content_sha256,
            target_page_min=2,
            target_page_max=2,
            pages=[
                PlannedPageRevision(
                    page_number=1,
                    revision=1,
                    content_sha256=first_page.content_sha256,
                ),
                PlannedPageRevision(
                    page_number=2,
                    revision=1,
                    content_sha256=second_page.content_sha256,
                ),
            ],
        )
    )

    first_provenance = artifacts.read_provenance(1, 1)
    first_render = first_provenance.render.model_copy(
        update={"comic_page_sha256": first_page.content_sha256}
    )
    artifacts.provenance_path(1, 1).write_text(
        first_provenance.model_copy(
            update={"render": first_render}
        ).model_dump_json()
    )
    second_image = _png_bytes((65, 45, 25))
    second_sha = hashlib.sha256(second_image).hexdigest()
    second_render = PageRenderRevision(
        page_number=2,
        revision=1,
        comic_page_revision=1,
        comic_page_sha256=second_page.content_sha256,
        request_sha256="q" * 64,
        image_sha256=second_sha,
        width=120,
        height=180,
        provider="deterministic-fixture",
        model="fixture-page-model",
        latency_ms=1,
        cost_usd="0",
    )
    artifacts.write_render(page_number=2, render_revision=1, image=second_image)
    artifacts.write_provenance(
        PageGenerationProvenance(
            render=second_render,
            usage=first_provenance.usage,
        )
    )
    artifacts.write_analysis(
        RenderAnalysis(
            page_number=2,
            render_revision=1,
            render_image_sha256=second_sha,
        )
    )
    artifacts.write_issues(2, ())
    assert hashlib.sha256(first_image).hexdigest() == first_render.image_sha256

    result = finish_book(
        artifacts,
        production=FinishProductionSpec(
            canvas_width=120,
            canvas_height=180,
            bleed_px=10,
        ),
    )

    assert result.preflight.ready_to_export is False
    assert "cross_page_appearance_state" in {
        diagnostic.code
        for diagnostic in result.preflight.pages[1].invariant_failures
    }
    assert result.preflight.correction_requests == ()  # Repair the Plan state citation, not the image.


def test_packaging_integrity_failure_leaves_no_partial_export(
    tmp_path: Path,
) -> None:
    artifacts, _ = _write_valid_book(tmp_path)

    result = finish_book(
        artifacts,
        production=FinishProductionSpec(
            canvas_width=120,
            canvas_height=180,
            bleed_px=10,
        ),
        formats=("pdf", "epub"),
    )

    assert result.preflight.ready_to_export is False
    assert result.packages == ()
    assert result.preflight.packaging_failures[0].code == "packaging_integrity"
    assert not artifacts.export_path("pdf").exists()
    assert not artifacts.export_path("cbz").exists()


def test_resolved_issue_revision_must_be_in_active_render_lineage(
    tmp_path: Path,
) -> None:
    artifacts, _ = _write_valid_book(tmp_path)
    _write_corrected_revision(
        artifacts,
        revision=2,
        parent_revision=1,
        color=(20, 40, 60),
    )
    _write_corrected_revision(
        artifacts,
        revision=3,
        parent_revision=1,
        color=(25, 45, 65),
    )
    artifacts.write_issues(
        1,
        (
            PageIssue(
                id="issue-branched-resolution",
                issue_type="render_fidelity",
                classification="invariant_failure",
                page_number=1,
                render_revision=1,
                evidence=["The first render omitted a word."],
                requested_correction="Restore exact canonical lettering.",
                status="resolved",
                resolution_revision=2,
            ),
        ),
    )

    result = finish_book(
        artifacts,
        production=FinishProductionSpec(
            canvas_width=120,
            canvas_height=180,
            bleed_px=10,
        ),
    )

    assert result.preflight.ready_to_export is False
    assert "page_issue_lineage" in {
        failure.code
        for failure in result.preflight.pages[0].invariant_failures
    }


def test_invalid_embedded_color_profile_blocks_safe_normalization(
    tmp_path: Path,
) -> None:
    artifacts, _ = _write_valid_book(tmp_path)
    buffer = io.BytesIO()
    Image.new("RGB", (120, 180), (15, 35, 55)).save(
        buffer,
        "PNG",
        icc_profile=b"not-an-icc-profile",
    )
    image = buffer.getvalue()
    image_sha256 = hashlib.sha256(image).hexdigest()
    artifacts.render_path(1, 1).write_bytes(image)
    provenance = artifacts.read_provenance(1, 1)
    artifacts.provenance_path(1, 1).write_text(
        provenance.model_copy(
            update={
                "render": provenance.render.model_copy(
                    update={"image_sha256": image_sha256}
                )
            }
        ).model_dump_json()
    )
    analysis = artifacts.read_analysis(1, 1)
    artifacts.analysis_path(1, 1).write_text(
        analysis.model_copy(
            update={"render_image_sha256": image_sha256}
        ).model_dump_json()
    )

    result = finish_book(
        artifacts,
        production=FinishProductionSpec(
            canvas_width=120,
            canvas_height=180,
            bleed_px=10,
        ),
    )

    assert result.preflight.ready_to_export is False
    assert "production_normalization" in {
        failure.code
        for failure in result.preflight.pages[0].invariant_failures
    }
    assert not artifacts.export_path("pdf").exists()


def test_a_drawn_page_reaches_export_without_hand_written_analysis(
    tmp_path: Path,
) -> None:
    """Draw → render analysis → Finish, with nothing filled in by hand.

    Finish requires exact OCR status on every active render, so an unwired
    analysis step made export unreachable no matter how good the art was.
    """

    from novel_to_comic.models.draw import (
        CompletePageProviderResult,
        OCRExtraction,
        OCRTextObservation,
        RetryProvenance,
    )
    from novel_to_comic.models.page import ApprovedVisualReferenceInventory
    from novel_to_comic.usage import ApiResult
    from novel_to_comic.page_drawing import (
        VertexCompletePageAdapter,
        compile_page_generation_request,
        draw_complete_page,
        production_page_capability_profile,
        select_book_edition,
    )

    profile = production_page_capability_profile()
    edition = select_book_edition(edition_id="edition-1", profile=profile)
    artifacts = TargetArtifacts(tmp_path)
    adaptation = _adaptation()
    page = _page(adaptation)
    artifacts.write_adaptation(adaptation)
    artifacts.write_page(page)
    artifacts.write_plan(
        BookPlan(
            revision=1,
            adaptation_revision=adaptation.revision,
            adaptation_sha256=adaptation.content_sha256,
            target_page_min=1,
            target_page_max=1,
            pages=[
                PlannedPageRevision(
                    page_number=1,
                    revision=page.revision,
                    content_sha256=page.content_sha256,
                )
            ],
        )
    )
    artifacts.write_book_edition(edition)
    image = _png_bytes(
        (15, 35, 55),
        size=(profile.output_width, profile.output_height),
    )

    class _Transport:
        async def generate(self, request):
            return CompletePageProviderResult(
                artifact_kind="complete_page",
                image_bytes=image,
                media_type="image/png",
                width=profile.output_width,
                height=profile.output_height,
                latency_ms=5,
                actual_provider_model=f"vertex_ai/{profile.model}",
                usage=UsageRecord(
                    provider="gemini",
                    model=profile.model,
                    operation="image",
                    image_count=1,
                    cost_usd=0,
                ),
            )

    class _OCR:
        async def extract(self, image_bytes: bytes):
            assert image_bytes == image
            return ApiResult(
                value=OCRExtraction(
                    lettering=[OCRTextObservation(id="ocr-1", text="The door opened.")]
                ),
                usage=UsageRecord(
                    provider="gemini",
                    model="ocr-balanced",
                    operation="text",
                    input_tokens=1200,
                    output_tokens=80,
                ),
            )

    compiled = compile_page_generation_request(
        page,
        edition,
        ApprovedVisualReferenceInventory(),
        {},
        retry=RetryProvenance(attempt=1),
    )
    asyncio.run(
        draw_complete_page(
            compiled,
            adapter=VertexCompletePageAdapter(_Transport()),
            artifacts=artifacts,
            page=page,
            ocr=_OCR(),
        )
    )

    assert artifacts.read_analysis(1, 1).lettering_valid is True
    # A clean render records no issue file at all.
    assert not artifacts.issues_path(1).exists()

    result = finish_book(
        artifacts,
        production=FinishProductionSpec(
            canvas_width=profile.output_width,
            canvas_height=profile.output_height,
        ),
    )

    assert result.preflight.ready_to_export is True
    assert [package.format for package in result.packages] == ["pdf", "cbz"]


def test_finish_revalidates_old_observations_without_provider_and_keeps_order_advisory(tmp_path, monkeypatch):
    from novel_to_comic import page_review

    artifacts, _ = _write_valid_book(tmp_path)
    monkeypatch.setattr(page_review, "DRAW_VALIDATOR_VERSION", "finish-upgraded-validator")
    result = finish_book(
        artifacts, production=FinishProductionSpec(canvas_width=120, canvas_height=180),
        formats=(),
    )
    assert result.preflight.ready_to_export
    assert artifacts.read_analysis(1, 1).validator_version == "finish-upgraded-validator"
    assert artifacts.read_raw_ocr(1, 1).render_image_sha256 == artifacts.read_provenance(1, 1).render.image_sha256
    artifacts.write_issues(1, (
        PageIssue(
            id="uncertain-order", issue_type="unverified_lettering_order",
            classification="editorial_issue", page_number=1, render_revision=1,
            evidence=("No panel geometry proves the balloon sweep order.",),
            requested_correction="Review order visually if desired.", status="open",
        ),
    ))
    result = finish_book(
        artifacts, production=FinishProductionSpec(canvas_width=120, canvas_height=180),
        formats=(),
    )
    assert result.preflight.ready_to_export
    assert artifacts.read_issues(1)[0].status == "open"
