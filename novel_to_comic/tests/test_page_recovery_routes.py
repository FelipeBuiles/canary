"""Saved-page recovery exercises routes, artifact lineage, and credit holds."""

from __future__ import annotations

import asyncio
import hashlib
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from novel_to_comic.config import Config
from novel_to_comic.models.adaptation import LetteringItem
from novel_to_comic.models.draw import (
    OCRExtraction,
    OCRTextObservation,
    PageGenerationProvenance,
    PageRenderRevision,
    RawOCRObservation,
)
from novel_to_comic.models.page import BookPlan, ComicPage, PageContent, PlannedPageRevision
from novel_to_comic.server.render_checks import active_provenance
from novel_to_comic.server import credited_job
from novel_to_comic.server.routers import pages
from novel_to_comic.target_artifacts import ArtifactMissing, TargetArtifacts
from novel_to_comic.usage import ApiResult, UsageRecord


def _extraction() -> OCRExtraction:
    return OCRExtraction(lettering=(OCRTextObservation(id="ocr-1", text="A door opens."),))


def _render(artifacts: TargetArtifacts, page: ComicPage, revision: int = 1):
    image = f"page-{page.page_number}-render-{revision}".encode()
    render = PageRenderRevision(
        page_number=page.page_number,
        revision=revision,
        parent_revision=revision - 1 if revision > 1 else None,
        comic_page_revision=page.revision,
        comic_page_sha256=page.content_sha256,
        request_sha256=hashlib.sha256(b"request:" + image).hexdigest(),
        image_sha256=hashlib.sha256(image).hexdigest(),
        width=120,
        height=180,
        provider="fixture",
        model="fixture",
        latency_ms=1,
        cost_usd="0",
    )
    artifacts.write_render(page_number=page.page_number, render_revision=revision, image=image)
    artifacts.write_provenance(PageGenerationProvenance(
        render=render,
        usage=UsageRecord(provider="fixture", model="fixture", operation="image", cost_usd=0),
    ))
    return render


@pytest.fixture
def recovery(tmp_path, monkeypatch):
    artifacts = TargetArtifacts(tmp_path)
    canonical = []
    renders = []
    for number in (1, 2):
        page = ComicPage(
            revision=1,
            page_number=number,
            adaptation_revision=1,
            adaptation_sha256="a" * 64,
            emphasis="initial",
            density_intent="sparse",
            content=(PageContent(
                id="panel-1", order=1, beat_ids=("beat-1",), visual_intent="An open door.",
                lettering=(LetteringItem(
                    id="letter-1", kind="caption", text="A door opens.",
                    source_unit_ids=("source-1",),
                ),),
            ),),
            reading_order=("panel-1", "letter-1"),
        )
        artifacts.write_page(page)
        canonical.append(page)
        renders.append(_render(artifacts, page))
    artifacts.write_plan(BookPlan(
        revision=1, adaptation_revision=1, adaptation_sha256="a" * 64,
        target_page_min=2, target_page_max=2,
        pages=tuple(PlannedPageRevision(
            page_number=page.page_number, revision=page.revision, content_sha256=page.content_sha256,
        ) for page in canonical),
    ))
    reserve = Mock(side_effect=lambda *args: (f"hold-{reserve.call_count}", f"job-{reserve.call_count}"))
    release = Mock()
    monkeypatch.setattr(credited_job, "get_db", Mock(return_value=object()))
    monkeypatch.setattr(credited_job, "reserve_credits", reserve)
    monkeypatch.setattr(credited_job, "assert_reservation_active", Mock())
    monkeypatch.setattr(credited_job, "release_reservation", release)
    monkeypatch.setattr(
        "novel_to_comic.server.db.get_db",
        Mock(side_effect=RuntimeError("No database in route tests")),
    )
    provider_calls = []
    failures = set()

    async def extract(adapter, image):
        provider_calls.append(image)
        if image in failures:
            raise RuntimeError("OCR unavailable")
        return ApiResult(value=_extraction(), usage=UsageRecord(
            provider="fixture", model="fixture", operation="text", cost_usd=0,
        ))

    monkeypatch.setattr(pages.GatewayPageOCRAdapter, "extract", extract)
    app = FastAPI()
    app.include_router(pages.router, prefix="/projects/{project_id}")
    project = (tmp_path, Config(), None)
    app.dependency_overrides[pages.get_project] = lambda: project
    app.dependency_overrides[pages.get_current_user] = lambda: "user-1"
    with TestClient(app) as client:
        yield SimpleNamespace(
            client=client, artifacts=artifacts, canonical=canonical, renders=renders,
            reserve=reserve, release=release, provider_calls=provider_calls, failures=failures,
        )


def _cache(recovery, number=1, *, image_sha256=None):
    render = recovery.renders[number - 1]
    recovery.artifacts.write_raw_ocr(RawOCRObservation(
        page_number=number, render_revision=render.revision,
        render_image_sha256=image_sha256 or render.image_sha256,
        extraction=_extraction(),
    ))


def _estimate(recovery):
    response = recovery.client.get("/projects/project-1/pages/checks/estimate")
    assert response.status_code == 200
    return response.json()


def _recover(recovery, body):
    response = recovery.client.post("/projects/project-1/pages/checks/recover", json=body)
    assert response.status_code == 200
    return response.json()["pages"]


def test_provider_free_batch_recovers_cached_page_without_submitting_uncached_page(recovery):
    _cache(recovery)
    quote = _estimate(recovery)
    assert quote["paid_pages"] == 1
    assert [(page["status"], page["requires_paid_call"]) for page in quote["pages"]] == [
        ("cached_evidence", False), ("requires_ocr", True),
    ]
    results = _recover(recovery, {"allow_paid": False, "renders": {}})
    assert [(page["page_number"], page["status"]) for page in results] == [
        (1, "checked"), (2, "requires_ocr"),
    ]
    analysis = recovery.artifacts.read_analysis(1, 1)
    assert analysis.recognized_lettering == {"letter-1": "A door opens."}
    assert analysis.render_image_sha256 == recovery.renders[0].image_sha256
    with pytest.raises(ArtifactMissing):
        recovery.artifacts.read_analysis(2, 1)
    recovery.reserve.assert_not_called()
    assert recovery.provider_calls == []


def test_render_map_without_paid_consent_does_not_authorize_ocr(recovery):
    quote = _estimate(recovery)
    renders = {str(page["page_number"]): page["render_image_sha256"] for page in quote["pages"]}
    results = _recover(recovery, {"renders": renders})
    assert [page["status"] for page in results] == ["requires_ocr", "requires_ocr"]
    recovery.reserve.assert_not_called()
    assert recovery.provider_calls == []


def test_paid_recovery_requires_estimated_render_identity_and_releases_each_hold(recovery):
    quote = _estimate(recovery)
    assert quote["paid_pages"] == 2
    rejected = _recover(recovery, {"allow_paid": True, "renders": {}})
    assert [page["status"] for page in rejected] == ["selection_changed", "selection_changed"]
    recovery.reserve.assert_not_called()
    assert recovery.provider_calls == []
    renders = {str(page["page_number"]): page["render_image_sha256"] for page in quote["pages"]}
    results = _recover(recovery, {"allow_paid": True, "renders": renders})
    assert [page["status"] for page in results] == ["checked", "checked"]
    assert recovery.provider_calls == [b"page-1-render-1", b"page-2-render-1"]
    assert recovery.reserve.call_count == 2
    assert sum(call.args[-1] for call in recovery.reserve.call_args_list) == quote["reserved_credits"]
    assert [call.args[1] for call in recovery.release.call_args_list] == ["hold-1", "hold-2"]
    assert _estimate(recovery)["paid_pages"] == 0


def test_replacement_after_estimate_cannot_spend_old_consent(recovery):
    quote = _estimate(recovery)
    replacement = _render(recovery.artifacts, recovery.canonical[0], revision=2)
    renders = {str(page["page_number"]): page["render_image_sha256"] for page in quote["pages"]}
    results = _recover(recovery, {"allow_paid": True, "renders": renders})
    assert [page["status"] for page in results] == ["selection_changed", "checked"]
    assert recovery.provider_calls == [b"page-2-render-1"]
    assert recovery.reserve.call_count == 1
    with pytest.raises(ArtifactMissing):
        recovery.artifacts.read_analysis(1, replacement.revision)
    assert recovery.artifacts.read_render(1, 1) == b"page-1-render-1"


def test_later_provider_failure_preserves_success_and_retry_only_pays_failed_page(recovery):
    quote = _estimate(recovery)
    renders = {str(page["page_number"]): page["render_image_sha256"] for page in quote["pages"]}
    recovery.failures.add(b"page-2-render-1")
    results = _recover(recovery, {"allow_paid": True, "renders": renders})
    assert [page["status"] for page in results] == ["checked", "failed"]
    first = recovery.artifacts.read_analysis(1, 1)
    assert first.recognized_lettering == {"letter-1": "A door opens."}
    assert recovery.release.call_count == 2
    recovery.failures.clear()
    retry_quote = _estimate(recovery)
    assert retry_quote["paid_pages"] == 1
    results = _recover(recovery, {"allow_paid": True, "renders": renders, "recovery_attempt_id": "confirmed-retry"})
    assert [page["status"] for page in results] == ["checked", "checked"]
    assert recovery.artifacts.read_analysis(1, 1) == first
    assert recovery.provider_calls == [b"page-1-render-1", b"page-2-render-1", b"page-2-render-1"]
    assert recovery.reserve.call_count == recovery.release.call_count == 3


def test_wrong_lineage_cached_evidence_fails_without_falling_back_to_paid_ocr(recovery):
    _cache(recovery, image_sha256="f" * 64)
    quote = _estimate(recovery)
    assert quote["pages"][0]["status"] == "failed"
    assert quote["pages"][0]["phase"] == "analysis"
    assert quote["pages"][0]["requires_paid_call"] is False
    renders = {str(page["page_number"]): page["render_image_sha256"] for page in quote["pages"]}
    results = _recover(recovery, {"allow_paid": True, "renders": renders})
    assert [page["status"] for page in results] == ["failed", "checked"]
    assert recovery.provider_calls == [b"page-2-render-1"]
    assert recovery.reserve.call_count == 1
    with pytest.raises(ArtifactMissing):
        recovery.artifacts.read_analysis(1, 1)


def test_cache_written_while_waiting_for_page_lock_prevents_credit_reservation(recovery):
    async def recover_after_draw():
        project_dir = recovery.artifacts.project_dir
        lock = credited_job.page_operation_lock(project_dir, 1)
        async with lock:
            task = asyncio.create_task(pages.analyze_page(
                1, "project-1", (project_dir, Config(), None), "user-1",
                allow_paid=False,
            ))
            await asyncio.sleep(0)
            assert not task.done()
            recovery.reserve.assert_not_called()
            assert recovery.provider_calls == []
            _cache(recovery)
        return await task

    analysis = asyncio.run(recover_after_draw())
    assert analysis.recognized_lettering == {"letter-1": "A door opens."}
    assert recovery.artifacts.read_analysis(1, 1) == analysis
    recovery.reserve.assert_not_called()
    assert recovery.provider_calls == []


def test_choose_saved_version_updates_reading_lettering_and_finish_without_spend(recovery):
    from novel_to_comic.lettering.service import active_render
    from novel_to_comic.page_finishing import _load_active_render

    target = recovery.artifacts
    _render(target, recovery.canonical[0], 2)
    original = target.read_provenance(1, 1)
    target.preflight_path.parent.mkdir(parents=True, exist_ok=True)
    target.preflight_path.write_text("cached finish")
    response = recovery.client.post("/projects/demo/pages/1/renders/1/select", json={"expected_revision": 2})
    assert response.status_code == 200, response.text
    assert target.active_render_revision(1) == 1
    assert target.provenance_revisions(1) == (1, 2)
    assert target.read_provenance(1, 1) == original
    assert not target.preflight_path.exists()
    assert active_provenance(target, 1).render.revision == 1
    assert active_render(target, 1).revision == 1
    render, image, failures = _load_active_render(target, 1)
    assert render.revision == 1
    assert image == target.read_render(1, 1)
    assert not failures
    assert recovery.client.get("/projects/demo/pages/1").json()["active_render_revision"] == 1
    recovery.reserve.assert_not_called()
    assert not recovery.provider_calls
    # Selection is durable; a genuinely new render becomes active and keeps all history.
    assert TargetArtifacts(target.project_dir).active_render_revision(1) == 1
    _render(target, recovery.canonical[0], 3)
    assert target.active_render_revision(1) == 3
    assert target.provenance_revisions(1) == (1, 2, 3)


def test_select_render_rejects_stale_expected_revision_and_missing_artwork(recovery):
    target = recovery.artifacts
    _render(target, recovery.canonical[0], 2)
    url = "/projects/demo/pages/1/renders/1/select"
    assert recovery.client.post(url, json={"expected_revision": 1}).status_code == 409
    target.render_path(1, 1).unlink()
    assert recovery.client.post(url, json={"expected_revision": 2}).status_code == 404
    assert target.active_render_revision(1) == 2


def test_select_render_rejects_old_plan_and_corrupt_image(recovery):
    target = recovery.artifacts
    _render(target, recovery.canonical[0], 2)
    target.render_path(1, 1).write_bytes(b"corrupt")
    url = "/projects/demo/pages/1/renders/1/select"
    assert recovery.client.post(url, json={"expected_revision": 2}).status_code == 409
    page = ComicPage.model_validate({**recovery.canonical[0].model_dump(exclude={"content_sha256"}), "revision": 2})
    target.write_page(page)
    response = recovery.client.post(url, json={"expected_revision": 2})
    assert response.status_code == 409
    assert "earlier page plan" in response.text


def test_select_render_rejects_inflight_generation(recovery):
    recovery.client.app.state.generation_jobs = {"job": SimpleNamespace(
        project_name="user-1:demo", kind="complete_page_draw", status="running",
        payload={"page_number": 1},
    )}
    response = recovery.client.post("/projects/demo/pages/1/renders/1/select", json={"expected_revision": 1})
    assert response.status_code == 409
    recovery.reserve.assert_not_called()


def test_selecting_older_art_does_not_inherit_verification_from_newer_art(recovery):
    from novel_to_comic.models.draw import PageIssue
    target = recovery.artifacts
    _render(target, recovery.canonical[0], 2)
    target.write_issues(1, (PageIssue(
        id="wrong-end", issue_type="render_fidelity", classification="editorial_issue",
        page_number=1, render_revision=1, evidence=("Mop head leads.",),
        requested_correction="Reverse the mop.", status="revised", resolution_revision=2,
    ),))
    target.select_render(1, 1, expected_revision=2)
    issue = target.read_issues(1)[0]
    assert issue.status == "open"
    assert issue.resolution_revision is None


def test_invalid_cached_evidence_reports_failed_without_quoting_a_replacement_read(recovery):
    recovery.artifacts.raw_ocr_path(1, 1).parent.mkdir(parents=True, exist_ok=True)
    recovery.artifacts.raw_ocr_path(1, 1).write_text("{}")
    quote = _estimate(recovery)
    failed = quote["pages"][0]
    assert failed["status"] == "failed"
    assert failed["phase"] == "analysis"
    assert failed["error"]
    assert failed["requires_paid_call"] is False
    assert quote["paid_pages"] == 1
    recovery.reserve.assert_not_called()
    assert recovery.provider_calls == []
