from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
import io
import sys
import time

import pytest
from PIL import Image

from novel_to_comic import crop_ocr, page_review
from novel_to_comic.models.crop_ocr import CropOCRLine, assemble_crop_lines
from novel_to_comic.models.page import ComicPage
from novel_to_comic.page_ocr import _PageOCRDraft, build_extraction
from novel_to_comic.target_artifacts import TargetArtifacts
from novel_to_comic.usage import ApiResult

from .test_page_review import _page, _render

EXPECTED = "Jimmy Robbons was always nuts on mountain climbing."
MISREAD = EXPECTED.replace("Robbons", "Robbins")


class LocalReader:
    fingerprint = "local-test-reader"

    def __init__(self, text=EXPECTED, confidence=0.99, *, fail=False):
        self.text, self.confidence, self.fail = text, confidence, fail
        self.images = []

    def read(self, image, *, timeout):
        assert timeout > 0
        self.images.append(image)
        if self.fail:
            raise RuntimeError("No native OCR runtime")
        return (
            (
                CropOCRLine(
                    text=self.text, confidence=self.confidence, box=(0, 0, 60, 10)
                ),
            )
            if self.text
            else ()
        )


class PrimaryReader:
    def __init__(self, extraction):
        self.extraction, self.calls = extraction, 0

    async def extract(self, image):
        self.calls += 1
        return ApiResult(value=self.extraction)


def setup_case(tmp_path, primary=MISREAD):
    data = _page().model_dump(mode="json")
    data["content"][0]["lettering"][0]["text"] = EXPECTED
    data["content_sha256"] = ""
    page = ComicPage.model_validate(data)
    buffer = io.BytesIO()
    Image.new("RGB", (100, 100), "white").save(buffer, format="PNG")
    image = buffer.getvalue()
    render = _render(image=image).model_copy(
        update={"comic_page_sha256": page.content_sha256}
    )
    artifacts = TargetArtifacts(tmp_path)
    artifacts.write_render(page_number=34, render_revision=1, image=image)
    extraction = build_extraction(
        _PageOCRDraft.model_validate(
            {
                "lettering": [
                    {
                        "text": primary,
                        "box": {"x": 0.1, "y": 0.1, "width": 0.8, "height": 0.2},
                    },
                    {
                        "text": "It wasn't a dream.",
                        "box": {"x": 0.1, "y": 0.5, "width": 0.8, "height": 0.2},
                    },
                ]
            }
        )
    )
    return page, render, image, artifacts, extraction


def analyze(case, reader, monkeypatch):
    monkeypatch.setattr(page_review, "_crop_reader", lambda: reader)
    page, render, image, artifacts, extraction = case
    primary = PrimaryReader(extraction)
    result = asyncio.run(
        page_review.analyze_page_render(
            page=page,
            render=render,
            image=image,
            artifacts=artifacts,
            ocr=primary,
        )
    )
    return result.analysis, primary


def test_disabled_experiment_needs_no_native_package(monkeypatch):
    monkeypatch.delenv("CANARY_CROP_OCR_ENABLED", raising=False)
    assert crop_ocr.reader_from_environment() is None


def test_optional_configuration_failure_preserves_the_original_check(
    tmp_path, monkeypatch, caplog
):
    monkeypatch.setenv("CANARY_CROP_OCR_ENABLED", "1")
    monkeypatch.delenv("CANARY_CROP_OCR_MODELS", raising=False)
    page, render, image, artifacts, extraction = setup_case(tmp_path)
    primary = PrimaryReader(extraction)
    analysis = asyncio.run(
        page_review.analyze_page_render(
            page=page,
            render=render,
            image=image,
            artifacts=artifacts,
            ocr=primary,
        )
    ).analysis
    assert analysis.crop_verification is None
    assert analysis.invariant_failures and primary.calls == 1
    assert analysis.validator_version == page_review.DRAW_VALIDATOR_VERSION
    assert "Optional crop OCR is not configured" in caplog.text


def test_reported_false_positive_is_uncertain_and_preserves_primary(
    tmp_path, monkeypatch
):
    case = setup_case(tmp_path)
    reader = LocalReader()
    analysis, primary = analyze(case, reader, monkeypatch)
    report = analysis.crop_verification
    assert report.status == "disagrees"
    assert report.readings[0].text == EXPECTED
    assert analysis.ocr_observations[0].text == MISREAD
    assert case[3].read_raw_ocr(34, 1).extraction.lettering[0].text == MISREAD
    assert (
        not analysis.lettering_valid
    )  # No automatic certification from a second model.
    assert primary.calls == 1
    assert len(reader.images) == 1
    with Image.open(io.BytesIO(reader.images[0])) as crop:
        assert crop.width < 100 and crop.height < 100
    issues = page_review.record_analysis_issues(case[3], analysis)
    assert "crop_check_status=disagrees" in issues[0].evidence
    assert not issues[0].requires_resolution


@pytest.mark.parametrize(
    ("text", "confidence", "expected_status"),
    [
        (MISREAD, 0.99, "agrees"),
        (MISREAD, 0.50, "inconclusive"),
        (EXPECTED, 0.50, "inconclusive"),
        ("", 0.99, "inconclusive"),
    ],
)
def test_agreement_requires_readable_high_score_evidence(
    tmp_path, monkeypatch, text, confidence, expected_status
):
    analysis, _ = analyze(
        setup_case(tmp_path), LocalReader(text, confidence), monkeypatch
    )
    assert analysis.crop_verification.status == expected_status
    assert [failure.code for failure in analysis.invariant_failures] == [
        "misspelled_lettering"
    ]


def test_failed_local_read_preserves_original_findings(tmp_path, monkeypatch):
    analysis, _ = analyze(setup_case(tmp_path), LocalReader(fail=True), monkeypatch)
    assert analysis.crop_verification.status == "inconclusive"
    assert analysis.crop_verification.readings[0].status == "unavailable"
    assert analysis.ocr_observations[0].text == MISREAD
    assert analysis.invariant_failures


def test_transient_local_failure_is_retried_not_saved(tmp_path, monkeypatch):
    case = setup_case(tmp_path)
    failing = LocalReader(fail=True)
    first, primary = analyze(case, failing, monkeypatch)
    assert not first.crop_verification.complete
    assert first.validator_version.endswith(page_review.INCOMPLETE_CROP_SUFFIX)
    assert not list(case[3].analysis_path(34, 1).parent.glob("crop_ocr_*.json"))
    # Still presented as a checked page; only the optional pass is pending.
    assert page_review.analysis_is_current(first.validator_version)

    working = LocalReader()
    monkeypatch.setattr(page_review, "_crop_reader", lambda: working)
    retried = page_review.revalidate_cached_page_render(
        page=case[0], render=case[1], artifacts=case[3]
    )
    assert retried.crop_verification.complete
    assert retried.crop_verification.status == "disagrees"
    assert not retried.validator_version.endswith(page_review.INCOMPLETE_CROP_SUFFIX)
    assert len(working.images) == 1 and primary.calls == 1
    assert len(list(case[3].analysis_path(34, 1).parent.glob("crop_ocr_*.json"))) == 1
    # Complete evidence is final: no further local reads.
    page_review.revalidate_cached_page_render(page=case[0], render=case[1], artifacts=case[3])
    assert len(working.images) == 1


def test_each_disputed_line_keeps_its_own_verdict(tmp_path, monkeypatch):
    import json

    case = setup_case(tmp_path)
    extraction = case[4].model_copy(update={"lettering": (
        case[4].lettering[0],
        case[4].lettering[1].model_copy(update={"text": "It wasnt a dreem."}),
    )})
    reads = iter([MISREAD, "It wasn't a dream."])

    class Reader(LocalReader):
        def read(self, image, *, timeout):
            self.text = next(reads)
            return super().read(image, timeout=timeout)

    analysis, _ = analyze((*case[:4], extraction), Reader(), monkeypatch)
    report = analysis.crop_verification
    assert [read.verdict for read in report.readings] == ["agrees", "disagrees"]
    assert report.status == "disagrees"
    evidence = analysis.invariant_failures[0].evidence
    readings = json.loads(next(item for item in evidence if item.startswith("crop_readings="))[len("crop_readings="):])
    assert readings == [
        {"first": MISREAD, "close_up": MISREAD, "verdict": "agrees"},
        {"first": "It wasnt a dreem.", "close_up": "It wasn't a dream.", "verdict": "disagrees"},
    ]


def test_cold_start_does_not_spend_the_page_budget(tmp_path, monkeypatch):
    reader = protocol_reader(tmp_path, monkeypatch, slow_start=0.4)
    try:
        assert reader.read(b"caption", timeout=0.3)[0].text == "caption"
    finally:
        reader.close()


def test_failed_configuration_is_not_reprobed(tmp_path, monkeypatch):
    attempts = []

    def probe(python):
        attempts.append(python)
        raise ValueError("no optional runtime")

    monkeypatch.setenv("CANARY_CROP_OCR_ENABLED", "1")
    monkeypatch.setenv("CANARY_CROP_OCR_MODELS", str(tmp_path))
    monkeypatch.setattr(crop_ocr, "_runtime_identity", probe)
    monkeypatch.setattr(crop_ocr, "_configured_reader", None)
    monkeypatch.setattr(crop_ocr, "_configured_options", None)
    monkeypatch.setattr(crop_ocr, "_configuration_error", None)
    for _ in range(5):
        assert page_review._crop_reader() is None
    assert len(attempts) == 1


def test_matching_copy_never_starts_local_reader(tmp_path, monkeypatch):
    reader = LocalReader()
    analysis, _ = analyze(setup_case(tmp_path, primary=EXPECTED), reader, monkeypatch)
    assert reader.images == []
    assert analysis.crop_verification is None
    assert analysis.lettering_valid


def test_hybrid_does_not_compare_software_lettering(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "novel_to_comic.lettering.service.is_hybrid", lambda artifacts: True
    )
    reader = LocalReader()
    analysis, _ = analyze(setup_case(tmp_path), reader, monkeypatch)
    assert reader.images == []
    assert analysis.crop_verification is None
    assert all(
        issue.code == "unexpected_generated_lettering"
        for issue in analysis.editorial_issues
    )


def test_cached_and_upgraded_analysis_never_repeat_primary_or_crop_reads(
    tmp_path, monkeypatch
):
    case = setup_case(tmp_path)
    reader = LocalReader()
    first, primary = analyze(case, reader, monkeypatch)
    original_raw = case[3].raw_ocr_path(34, 1).read_bytes()
    second = asyncio.run(
        page_review.analyze_page_render(
            page=case[0],
            render=case[1],
            image=case[2],
            artifacts=case[3],
            ocr=primary,
        )
    ).analysis
    assert second == first
    monkeypatch.setattr(page_review, "DRAW_VALIDATOR_VERSION", "new-validator")
    upgraded = page_review.revalidate_cached_page_render(
        page=case[0], render=case[1], artifacts=case[3]
    )
    assert upgraded.crop_verification == first.crop_verification
    assert len(reader.images) == 1 and primary.calls == 1
    assert case[3].raw_ocr_path(34, 1).read_bytes() == original_raw


def test_opt_in_refreshes_old_issue_evidence_without_resetting_dismissal(
    tmp_path, monkeypatch
):
    case = setup_case(tmp_path)
    original, _ = analyze(case, None, monkeypatch)
    issue = page_review.record_analysis_issues(case[3], original)[0]
    page_review.dismiss_page_issue(
        case[3], page_number=34, issue_id=issue.id, reason="Checked the artwork"
    )
    updated, primary = analyze(case, LocalReader(), monkeypatch)
    page_review.record_analysis_issues(case[3], updated)
    retained = case[3].read_issues(34)[0]
    assert retained.status == "dismissed"
    assert retained.dismissal_reason == "Checked the artwork"
    assert "crop_check_status=disagrees" in retained.evidence
    assert primary.calls == 0


def test_missing_regions_and_missing_text_cannot_be_confident(tmp_path, monkeypatch):
    case = setup_case(tmp_path)
    extraction = case[4].model_copy(
        update={
            "observed_regions": (),
            "lettering": tuple(
                item.model_copy(update={"detected_region_id": None})
                for item in case[4].lettering
            ),
        }
    )
    reader = LocalReader()
    analysis, _ = analyze((*case[:4], extraction), reader, monkeypatch)
    assert analysis.crop_verification.readings[0].status == "no_region"
    assert analysis.crop_verification.status == "inconclusive"
    assert not reader.images
    missing = case[4].model_copy(update={"lettering": case[4].lettering[1:]})
    other = setup_case(tmp_path / "missing")
    analysis, _ = analyze((*other[:4], missing), reader, monkeypatch)
    # Nothing on the page is unmatched, so there is nothing to read close up.
    assert analysis.crop_verification is None
    assert not any(
        item.startswith("crop_") for item in analysis.invariant_failures[0].evidence
    )
    assert not reader.images


def test_crop_count_and_pixel_budget_are_bounded(tmp_path, monkeypatch):
    case = setup_case(tmp_path)
    monkeypatch.setattr(crop_ocr, "MAX_CROPS", 0)
    reader = LocalReader()
    analysis, _ = analyze(case, reader, monkeypatch)
    assert analysis.crop_verification.readings[0].status == "over_budget"
    assert not reader.images
    monkeypatch.setattr(crop_ocr, "MAX_CROPS", 6)
    monkeypatch.setattr(crop_ocr, "MAX_CROP_PIXELS", 1)
    case = setup_case(tmp_path / "pixels")
    analysis, _ = analyze(case, reader, monkeypatch)
    assert analysis.crop_verification.readings[0].status == "over_budget"
    assert not reader.images


def test_oversized_source_image_is_rejected_before_a_crop_is_decoded(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(crop_ocr, "MAX_PAGE_PIXELS", 1)
    reader = LocalReader()
    analysis, _ = analyze(setup_case(tmp_path), reader, monkeypatch)
    read = analysis.crop_verification.readings[0]
    assert read.status == "over_budget" and read.bounds is None
    assert not reader.images


def test_cached_crop_evidence_rejects_changed_render_bytes(tmp_path):
    page, render, image, artifacts, extraction = setup_case(tmp_path)
    reader = LocalReader()
    crop_ocr.verify_mismatches(
        page=page,
        render=render,
        extraction=extraction,
        artifacts=artifacts,
        reader=reader,
        disputed=extraction.lettering[:1],
    )
    artifacts.render_path(34, 1).write_bytes(b"corrupted image")
    with pytest.raises(ValueError, match="render bytes"):
        crop_ocr.verify_mismatches(
            page=page,
            render=render,
            extraction=extraction,
            artifacts=artifacts,
            reader=reader,
            disputed=extraction.lettering[:1],
        )


def test_fragment_top_edges_do_not_reorder_words_or_join_separate_lines():
    fragments = (
        CropOCRLine(text="Robbons was", confidence=0.98, box=(195, 78, 475, 124)),
        CropOCRLine(text="always nuts", confidence=0.99, box=(467, 76, 728, 127)),
        CropOCRLine(text="Jimmy", confidence=0.99, box=(55, 75, 216, 126)),
        CropOCRLine(text="climbing.", confidence=0.99, box=(326, 127, 536, 174)),
        CropOCRLine(text="mountain", confidence=0.99, box=(119, 129, 322, 169)),
        CropOCRLine(text="on", confidence=0.97, box=(57, 132, 113, 167)),
    )
    lines = assemble_crop_lines(fragments)
    assert [line.text for line in lines] == [
        "Jimmy Robbons was always nuts",
        "on mountain climbing.",
    ]
    assert [line.confidence for line in lines] == [0.98, 0.97]


def test_analysis_recovery_recognizes_enabled_verifier_version(tmp_path, monkeypatch):
    from novel_to_comic.models.draw import PageGenerationProvenance
    from novel_to_comic.server.render_checks import render_check_status as _analysis_recovery
    from novel_to_comic.usage import UsageRecord

    case = setup_case(tmp_path)
    analysis, _ = analyze(case, LocalReader(), monkeypatch)
    case[3].write_page(case[0])
    case[3].write_provenance(
        PageGenerationProvenance(
            render=case[1],
            usage=UsageRecord(
                provider="fixture",
                model="fixture",
                operation="image",
                cost_usd=0,
            ),
        )
    )
    assert analysis.validator_version != page_review.DRAW_VALIDATOR_VERSION
    assert _analysis_recovery(case[3], 34) == {
        "status": "checked",
        "requires_paid_call": False,
    }


def protocol_reader(tmp_path, monkeypatch, *, stall=False, stop_consuming=False, slow_start=0.0):
    """Exercise subprocess isolation and deadlines without native packages."""
    worker = tmp_path / "worker.py"
    worker.write_text(
        f"""import base64, json, sys, time
time.sleep({slow_start})
"""
        + """print(json.dumps({"ready": True}), flush=True)
"""
        + ("time.sleep(60)\n" if stop_consuming else "")
        + """for request in sys.stdin:
    data = json.loads(request)
    assert set(data) == {"image"}
    text = base64.b64decode(data["image"]).decode()
    print("ignored library output", flush=True)
"""
        + (
            """    sys.stdout.write("{")
    sys.stdout.flush()
    time.sleep(60)
"""
            if stall
            else """    time.sleep(0.02)
    print(json.dumps({"lines": [{"text": text, "confidence": 0.99, "box": [0, 0, 50, 10]}]}), flush=True)
"""
        )
    )
    for name in ("det", "rec"):
        directory = tmp_path / name
        directory.mkdir()
        (directory / "model.bin").write_bytes(b"protocol-fixture")
    monkeypatch.setattr(crop_ocr, "WORKER_PATH", worker)
    monkeypatch.setattr(crop_ocr, "_runtime_identity", lambda python: b"test-runtime")
    return crop_ocr.PaddleCropReader(sys.executable, tmp_path)


def test_worker_is_persistent_and_serializes_concurrent_requests(tmp_path, monkeypatch):
    reader = protocol_reader(tmp_path, monkeypatch)
    try:
        with ThreadPoolExecutor(max_workers=3) as pool:
            reads = list(
                pool.map(
                    lambda name: reader.read(name.encode(), timeout=5)[0].text,
                    ("first", "second", "third"),
                )
            )
        assert reads == ["first", "second", "third"]
        process = reader._process
        assert reader.read(b"fourth", timeout=5)[0].text == "fourth"
        assert reader._process is process
    finally:
        reader.close()
    assert process.poll() is not None


def test_partial_worker_output_cannot_bypass_timeout(tmp_path, monkeypatch):
    reader = protocol_reader(tmp_path, monkeypatch, stall=True)
    started = time.monotonic()
    with pytest.raises(TimeoutError, match="time budget"):
        reader.read(b"caption", timeout=0.25)
    assert time.monotonic() - started < 2
    assert reader._process is None


def test_worker_not_consuming_input_cannot_bypass_timeout(tmp_path, monkeypatch):
    reader = protocol_reader(tmp_path, monkeypatch, stop_consuming=True)
    started = time.monotonic()
    with pytest.raises(TimeoutError, match="time budget"):
        reader.read(b"x" * 1_000_000, timeout=0.25)
    assert time.monotonic() - started < 2
    assert reader._process is None


def test_concurrent_configuration_does_not_create_multiple_model_workers(monkeypatch):
    created = []

    class Reader:
        def __init__(self, *args):
            time.sleep(0.02)
            created.append(self)

    monkeypatch.setenv("CANARY_CROP_OCR_ENABLED", "1")
    monkeypatch.setenv("CANARY_CROP_OCR_MODELS", "fixture")
    monkeypatch.setattr(crop_ocr, "PaddleCropReader", Reader)
    monkeypatch.setattr(crop_ocr, "_configured_reader", None)
    monkeypatch.setattr(crop_ocr, "_configured_options", None)
    with ThreadPoolExecutor(max_workers=3) as pool:
        readers = list(pool.map(lambda _: crop_ocr.reader_from_environment(), range(3)))
    assert len(created) == 1
    assert all(reader is created[0] for reader in readers)
