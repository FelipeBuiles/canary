"""Hosted OCR lifecycle contracts; no gateway, credentials, or provider calls."""
from novel_to_comic.server.render_checks import render_check_status
import asyncio
import hashlib
import json
import time

import pytest

from novel_to_comic import page_review, textract_ocr as hosted
from novel_to_comic.config import Config
from novel_to_comic.usage import UsageRecord, calculate_cost_breakdown
from .test_crop_ocr import EXPECTED, MISREAD, PrimaryReader, setup_case


def response(text=EXPECTED, confidence=99):
    return {"DetectDocumentTextModelVersion": "fixture", "ResponseMetadata": {"RequestId": "fixture"}, "Blocks": [
        {"Id": "l", "BlockType": "LINE", "Text": text, "Confidence": 99,
         "Geometry": {"BoundingBox": {"Left": .1, "Top": .1, "Width": .8, "Height": .3}},
         "Relationships": [{"Type": "CHILD", "Ids": ["w"]}]},
        {"Id": "w", "BlockType": "WORD", "Text": text, "Confidence": confidence}]}


@pytest.fixture
def harness(tmp_path, monkeypatch):
    monkeypatch.setenv("CANARY_TEXTRACT_ENABLED", "1")
    case = setup_case(tmp_path)
    calls, usage = [], []
    async def submit(config, image, attempt):
        assert hashlib.sha256(image).hexdigest() == attempt.crop_sha256
        assert case[3].textract_attempts(34, 1, attempt.recognition_sha256)[-1].status == "submitting"
        calls.append(attempt)
        return {"status": "succeeded", "response": response()}
    async def insert(**kwargs):
        pass
    monkeypatch.setattr(hosted, "submit", submit)
    monkeypatch.setattr(hosted, "_record_usage", lambda attempt, config: usage.append(attempt))
    monkeypatch.setattr("novel_to_comic.ai.client._insert_event_async", insert)
    return case, calls, usage


def analyze(case, **kwargs):
    return asyncio.run(page_review.analyze_page_render(page=case[0], render=case[1], image=case[2],
        artifacts=case[3], ocr=PrimaryReader(case[4]), config=Config(), **kwargs)).analysis


def test_success_is_immutable_reusable_evidence_not_a_correction(harness, monkeypatch):
    case, calls, usage = harness
    first = analyze(case)
    assert len(calls) == len(usage) == 1
    assert usage[0].charged_credits == 0
    assert first.crop_verification.complete
    assert first.crop_verification.status == "disagrees"
    assert first.ocr_observations[0].text == MISREAD
    assert not first.lettering_valid
    raw = case[3].raw_ocr_path(34, 1).read_bytes()
    issue = page_review.record_analysis_issues(case[3], first)[0]
    page_review.dismiss_page_issue(case[3], page_number=34, issue_id=issue.id, reason="Looked at art")
    assert analyze(case, retry_crop_ocr=True) == first
    monkeypatch.setattr(hosted, "CONVERTER", "next-converter")
    updated = page_review.revalidate_cached_page_render(page=case[0], render=case[1], artifacts=case[3])
    page_review.record_analysis_issues(case[3], updated)
    assert updated.crop_verification.status == "disagrees"
    assert case[3].read_issues(34)[0].status == "dismissed"
    assert case[3].raw_ocr_path(34, 1).read_bytes() == raw
    assert len(calls) == 1


def test_unknown_requires_explicit_retry_and_free_recovery_never_submits(harness, monkeypatch):
    case, calls, _ = harness
    async def timeout(config, image, attempt):
        calls.append(attempt)
        raise TimeoutError("lost response")
    monkeypatch.setattr(hosted, "submit", timeout)
    first = analyze(case)
    assert not first.crop_verification.complete
    assert first.crop_verification.readings[0].status == "outcome_unknown"
    analyze(case)  # Automatic draw recovery must not repeat ambiguous submissions.
    page_review.revalidate_cached_page_render(page=case[0], render=case[1], artifacts=case[3])
    assert len(calls) == 1
    analyze(case, retry_crop_ocr=True)
    assert len(calls) == 2


def test_free_validation_does_not_even_prepare_pixels(harness, monkeypatch):
    case, calls, _ = harness
    asyncio.run(page_review.analyze_page_render(page=case[0], render=case[1], image=case[2],
        artifacts=case[3], ocr=PrimaryReader(case[4])))
    def forbidden(*args, **kwargs):
        pytest.fail("free recovery prepared an image")
    monkeypatch.setattr(hosted, "prepare_plan", forbidden)
    result = page_review.revalidate_cached_page_render(page=case[0], render=case[1], artifacts=case[3])
    assert result.crop_verification.readings[0].status == "pending"
    assert not calls


def test_caps_and_expired_claim_prevent_submission(harness, monkeypatch):
    case, calls, _ = harness
    monkeypatch.setattr(hosted, "MAX_CROP_PIXELS", 1)
    result = analyze(case)
    assert result.crop_verification.readings[0].status == "over_budget"
    assert result.crop_verification.complete and not calls


def test_concurrent_claims_and_restart_do_not_duplicate(harness):
    from concurrent.futures import ThreadPoolExecutor
    case, _, _ = harness
    plan = hosted.prepare_plan(render=case[1], extraction=case[4], disputed=case[4].lettering[:1],
        artifacts=case[3], deadline=time.monotonic() + 5)
    def claim(_):
        return hosted._claim(artifacts=case[3], render=case[1], crop=plan.crops[0],
            expires_at=time.time()+5, retry=False, retry_before=time.time())
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(claim, range(4)))
    assert sum(item is not None for item in results) == 1
    assert claim(None) is None
    report = hosted.cached_report(page=case[0], render=case[1], extraction=case[4],
        disputed=case[4].lettering[:1], artifacts=case[3])
    assert report.readings[0].status == "outcome_unknown"


def test_low_word_confidence_and_invalid_geometry_are_not_confident():
    assert hosted.convert_lines(response(confidence=40), 100, 100)[0].confidence == .4
    bad = response()
    bad["Blocks"][0]["Geometry"]["BoundingBox"]["Left"] = float("nan")
    with pytest.raises(ValueError, match="geometry"):
        hosted.convert_lines(bad, 100, 100)
    overlapping = response()
    line = dict(overlapping["Blocks"][0], Id="other")
    overlapping["Blocks"].append(line)
    with pytest.raises(ValueError, match="Ambiguous"):
        hosted.convert_lines(overlapping, 100, 100)


def test_pixels_only_envelope(harness, monkeypatch):
    import httpx
    case, _, _ = harness
    plan = hosted.prepare_plan(render=case[1], extraction=case[4], disputed=case[4].lettering[:1],
        artifacts=case[3], deadline=time.monotonic()+5)
    attempt = hosted._claim(artifacts=case[3], render=case[1], crop=plan.crops[0],
        expires_at=time.time()+5, retry=False, retry_before=time.time())
    captured = []
    def handle(request):
        payload = json.loads(request.content)
        envelope = json.loads(payload["messages"][0]["content"])
        assert set(envelope) == {"schema", "image", "sha256", "attempt_id", "expires_at"}
        assert EXPECTED not in request.content.decode() and MISREAD not in request.content.decode()
        captured.append(envelope)
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps({
            **{k: v for k, v in envelope.items() if k != "image"}, "region": attempt.region,
            "status": "succeeded", "response": response()})}}]})
    original = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: original(transport=httpx.MockTransport(handle), **kwargs))
    # Fixture replaces submit; invoke its original implementation saved at import time.
    asyncio.run(REAL_SUBMIT(Config(), case[3].read_textract_crop(34, 1, attempt.recognition_sha256), attempt))
    assert len(captured) == 1


REAL_SUBMIT = hosted.submit


def test_unknown_provider_cost_is_never_zero():
    usage = UsageRecord(provider="textract", model="ocr-textract", operation="ocr", cost_usd=None)
    assert calculate_cost_breakdown(usage).source == "unknown_provider_usage"


def test_sponsored_usage_retains_real_cost_without_credit_settlement(harness, monkeypatch):
    from novel_to_comic.ai import client
    from unittest.mock import Mock
    case, _, receipts = harness
    analyze(case)
    updates = []
    database = Mock()
    database.table.return_value.update.side_effect = lambda payload, **kwargs: updates.append(payload) or database
    monkeypatch.setattr("novel_to_comic.server.db.get_db", lambda: database)
    monkeypatch.setattr(client, "_settle_event_usage", lambda *a, **k: pytest.fail("charged author"))
    monkeypatch.setattr("novel_to_comic.server.credits.release_model_call_authorization",
        lambda *a, **k: pytest.fail("touched primary call authorization"))
    REAL_RECORD_USAGE(receipts[0], Config())
    assert updates[-1]["billable"] is False
    assert updates[-1]["cost_usd"] == .0015
    assert updates[-1]["usage_json"]["document_pages"] == 1
    assert updates[-1]["metadata_json"]["cost_owner"] == "canary"
    REAL_RECORD_USAGE(receipts[0].model_copy(update={"status": "outcome_unknown", "response": None}), Config())
    assert updates[-1]["cost_usd"] is None
    assert updates[-1]["billable"] is False


REAL_RECORD_USAGE = hosted._record_usage


def test_hosted_only_route_estimate_and_admission_are_free(harness, monkeypatch):
    from novel_to_comic.models.draw import PageGenerationProvenance
    from novel_to_comic.server.routers import pages
    case, calls, _ = harness
    first = asyncio.run(page_review.analyze_page_render(page=case[0], render=case[1], image=case[2],
        artifacts=case[3], ocr=PrimaryReader(case[4]))).analysis
    assert not first.crop_verification.complete
    case[3].write_page(case[0])
    case[3].write_provenance(PageGenerationProvenance(render=case[1],
        usage=UsageRecord(provider="fixture", model="fixture", operation="image", cost_usd=0)))
    # The optional second look never makes the page unchecked or asks the author to pay.
    recovery = render_check_status(case[3], 34)
    assert recovery == {"status": "checked", "requires_paid_call": False}
    project = (case[3].project_dir, Config(), None)
    quote = pages.estimate_page_analysis(34, project)
    assert quote["estimate_credits"] == 0
    admissions = []
    async def admitted(**kwargs):
        cached = kwargs["cached_work"]()
        if cached is not None:
            return cached
        admissions.append(kwargs)
        return await kwargs["work"]()
    monkeypatch.setattr("novel_to_comic.server.credited_job.run_credited_page_check", admitted)
    asyncio.run(pages.analyze_page(34, "fixture", project, "author", allow_paid=False))
    assert not calls and not admissions
    asyncio.run(pages.analyze_page(34, "fixture", project, "author", second_look_only=True))
    assert len(calls) == len(admissions) == 1
    assert admissions[0]["estimated_cost_usd"] == 0
    assert admissions[0]["operations"] == ()


def test_partial_success_retries_only_the_unfinished_crop(harness, monkeypatch):
    case, calls, _ = harness
    extraction = case[4].model_copy(update={"lettering": (
        case[4].lettering[0], case[4].lettering[1].model_copy(update={"text": "It wasnt a dreem."}))})
    case = (*case[:4], extraction)
    async def partial(config, image, attempt):
        calls.append(attempt)
        return {"status": "succeeded", "response": response()} if len(calls) == 1 else {"status": "outcome_unknown"}
    monkeypatch.setattr(hosted, "submit", partial)
    first = analyze(case)
    assert len(calls) == 2 and not first.crop_verification.complete
    successful_sha = calls[0].crop_sha256
    first_receipt = case[3].textract_attempts(34, 1, calls[0].recognition_sha256)[0]
    async def success(config, image, attempt):
        assert attempt.crop_sha256 != successful_sha
        calls.append(attempt)
        return {"status": "succeeded", "response": response("It wasn't a dream.")}
    monkeypatch.setattr(hosted, "submit", success)
    final = analyze(case, retry_crop_ocr=True)
    assert len(calls) == 3 and final.crop_verification.complete
    assert case[3].textract_attempts(34, 1, calls[0].recognition_sha256) == (first_receipt,)


def test_second_look_only_refuses_work_needing_a_primary_read(harness, monkeypatch):
    from fastapi import HTTPException
    from novel_to_comic.models.draw import PageGenerationProvenance
    from novel_to_comic.server.routers import pages
    case, calls, _ = harness
    case[3].write_page(case[0])
    case[3].write_provenance(PageGenerationProvenance(render=case[1],
        usage=UsageRecord(provider="fixture", model="fixture", operation="image", cost_usd=0)))
    monkeypatch.setattr("novel_to_comic.server.credited_job.run_credited_page_check",
        lambda **kwargs: pytest.fail("admitted a primary read"))
    with pytest.raises(HTTPException) as refused:
        asyncio.run(pages.analyze_page(34, "fixture", (case[3].project_dir, Config(), None), "author",
            second_look_only=True))
    assert refused.value.status_code == 409 and not calls


def test_enabling_hosted_reads_keeps_saved_checks_current(monkeypatch):
    monkeypatch.delenv("CANARY_TEXTRACT_ENABLED", raising=False)
    monkeypatch.setattr(page_review, "_crop_reader", lambda: None)
    before = page_review.current_draw_validator_version()
    monkeypatch.setenv("CANARY_TEXTRACT_ENABLED", "1")
    assert page_review.current_draw_validator_version() == before


def test_hyphenated_line_wrap_is_one_word():
    from novel_to_comic.models.crop_ocr import CropOCRLine
    lines = (CropOCRLine(text="It was won-", confidence=1, box=(0, 0, 10, 5)),
             CropOCRLine(text="derful.", confidence=1, box=(0, 6, 10, 11)))
    assert "It was wonderful." in hosted.joined_variants(lines)
    compound = (CropOCRLine(text="A well-", confidence=1, box=(0, 0, 10, 5)),
                CropOCRLine(text="known face", confidence=1, box=(0, 6, 10, 11)))
    assert "A well-known face" in hosted.joined_variants(compound)
    dash = (CropOCRLine(text="Wait -", confidence=1, box=(0, 0, 10, 5)),
            CropOCRLine(text="what?", confidence=1, box=(0, 6, 10, 11)))
    assert hosted.joined_variants(dash) == ("Wait - what?",)


def test_gateway_refusal_and_unreachable_gateway_are_known_failures(harness, monkeypatch):
    import httpx
    case, _, _ = harness
    plan = hosted.prepare_plan(render=case[1], extraction=case[4], disputed=case[4].lettering[:1],
        artifacts=case[3], deadline=time.monotonic()+5)
    attempt = hosted._claim(artifacts=case[3], render=case[1], crop=plan.crops[0],
        expires_at=time.time()+5, retry=False, retry_before=time.time())
    image = case[3].read_textract_crop(34, 1, attempt.recognition_sha256)
    original = httpx.AsyncClient
    def respond(handler):
        monkeypatch.setattr(httpx, "AsyncClient",
            lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs))
        return asyncio.run(REAL_SUBMIT(Config(), image, attempt))
    assert respond(lambda request: httpx.Response(401))["status"] == "not_submitted"
    assert respond(lambda request: httpx.Response(429))["status"] == "not_submitted"
    def refuse(request):
        raise httpx.ConnectError("refused")
    assert respond(refuse) == {"status": "not_submitted", "error_code": "gateway_unreachable"}
    with pytest.raises(httpx.HTTPStatusError):
        respond(lambda request: httpx.Response(408))  # May have reached the provider.


def test_usage_projection_failure_still_submits_once(harness, monkeypatch):
    case, calls, _ = harness
    async def broken(**kwargs):
        raise RuntimeError("database unavailable")
    monkeypatch.setattr("novel_to_comic.ai.client._insert_event_async", broken)
    result = analyze(case)
    assert len(calls) == 1 and result.crop_verification.complete
    assert result.crop_verification.readings[0].status == "read"
