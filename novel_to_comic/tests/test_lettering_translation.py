"""Actual quote/admission/reserved job/publication with a local translator only."""
from __future__ import annotations

import asyncio
import json
from contextlib import suppress
from unittest.mock import MagicMock

import httpx
import pytest

from novel_to_comic.config import Config
from novel_to_comic.lettering import service, translation
from novel_to_comic.models.lettering import LetteringSettings
from novel_to_comic.models.page import PlannedPageRevision
from novel_to_comic.server import credited_job
from novel_to_comic.server.deps import get_project
from novel_to_comic.server.generation_jobs import generation_worker
from novel_to_comic.server.routers.lettering import router
from novel_to_comic.usage import ApiResult
from .test_hybrid_lettering import book, save, update
from .test_server_admission import app_at, run_async


def add_page(artifacts, image):
    page = update(artifacts.read_page(1), page_number=2)
    artifacts.write_page(page)
    plan = artifacts.read_plan()
    artifacts.write_plan(update(plan, revision=plan.revision + 1, target_page_min=2, target_page_max=2,
        pages=[*plan.pages, PlannedPageRevision(page_number=2, revision=1, content_sha256=page.content_sha256)]))
    provenance = artifacts.read_provenance(1, 1)
    artifacts.write_render(page_number=2, render_revision=1, image=image)
    artifacts.write_provenance(provenance.model_copy(update={"render": provenance.render.model_copy(
        update={"page_number": 2, "comic_page_sha256": page.content_sha256})}))


@pytest.fixture
def translated_app(book, monkeypatch):
    artifacts, image = book
    config = Config()
    app = app_at(artifacts.project_dir)
    app.state.generation_queue = asyncio.Queue()
    app.state.user_generation_semaphores = {}
    app.include_router(router, prefix="/api/projects/{project_id}")
    app.dependency_overrides[get_project] = lambda: (artifacts.project_dir, config, None)
    database = MagicMock()
    reservations, releases, calls = [], [], []
    monkeypatch.setattr(credited_job, "get_db", lambda: database)
    monkeypatch.setattr(credited_job, "reserve_credits", lambda *args: (reservations.append(args[-1]) or "hold", "ledger-job"))
    monkeypatch.setattr(credited_job, "release_reservation", lambda *args: releases.append(args[-1]))
    monkeypatch.setattr(credited_job, "assert_reservation_active", lambda *args: None)

    async def provider(**kwargs):
        assert reservations, "provider ran before credit admission"
        calls.append(kwargs)
        value = {"translations": [{"page_number": item["page_number"], "element_id": item["element_id"],
            "text": "Traducido: " + item["text"]} for item in json.loads(kwargs["user_content"])["items"]]}
        kwargs["response_sink"](ApiResult(value=json.dumps(value)))
        return ApiResult(value=value)

    monkeypatch.setattr(translation, "generate_json", provider)
    return app, artifacts, image, reservations, releases, calls


@run_async
async def test_estimate_submit_job_translates_every_page_and_preserves_authored_state(translated_app):
    app, artifacts, image, reservations, releases, calls = translated_app
    add_page(artifacts, image)
    initial = service.ensure_lettering(artifacts, 1)
    first = initial.elements[0].model_dump()
    first["text_by_locale"] = {"source": "Saved custom words.", "fr": "Manuel.", "es": "Manual español."}
    custom = first | {"id": "custom-hidden", "source_lettering_item_id": None, "hidden": True,
        "text_by_locale": {"source": "Hidden custom copy.", "fr": "Caché."}, "rotation": 12}
    saved = save(artifacts, update(initial, elements=[first, custom]), reviewed=True)
    art_before = artifacts.read_render(1, 1)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        root = "/api/projects/book/lettering"
        quote = await client.get(root + "/translation-estimate?target_locale=es")
        assert quote.status_code == 200, quote.text
        estimate = quote.json()
        assert (estimate["page_count"], estimate["element_count"], estimate["translate_count"], estimate["preserved_target_count"]) == (2, 3, 2, 1)
        assert calls == reservations == []
        assert not artifacts.lettering_path(2).exists()
        body = {"target_locale": "es", "expected_snapshot_sha256": estimate["snapshot_sha256"]}
        assert (await client.post(root + "/translate", json=body)).status_code == 400
        accepted = await client.post(root + "/translate", json=body, headers={"Idempotency-Key": "translate"})
        assert accepted.status_code == 200, accepted.text
        job = app.state.generation_jobs[accepted.json()["job"]["id"]]
        assert job.kind == "lettering_translation" and job.status == "queued"
        # Even targeted generation, normally allowed alongside page jobs, is blocked.
        assert (await client.post("/api/projects/book/pages/1/generate", headers={"Idempotency-Key": "draw"})).status_code == 409
        replay = await client.post(root + "/translate", json=body, headers={"Idempotency-Key": "translate"})
        assert replay.json() == accepted.json()
        worker = asyncio.create_task(generation_worker(app))
        try:
            await asyncio.wait_for(app.state.generation_queue.join(), 15)
        finally:
            worker.cancel()
            with suppress(asyncio.CancelledError):
                await worker
        assert job.status == "complete", job.error
    assert releases == ["hold"] and len(reservations) == 1
    assert calls and all(not call["retry_invalid_json"] and not call["retry_transport"] for call in calls)
    page1, page2 = artifacts.read_lettering(1), artifacts.read_lettering(2)
    assert page1.locale == page2.locale == artifacts.read_lettering_settings().locale == "es"
    assert page1.elements[0].text_by_locale == saved.elements[0].text_by_locale
    assert page1.elements[1].text_by_locale == saved.elements[1].text_by_locale | {"es": "Traducido: Hidden custom copy."}
    for before, after in zip(saved.elements, page1.elements):
        assert before.model_dump(exclude={"text_by_locale", "resolved"}) == after.model_dump(exclude={"text_by_locale", "resolved"})
    assert page1.reviewed_against_image_sha256 is None
    assert page2.elements[0].text_by_locale["es"] == "Traducido: The door opened."
    assert artifacts.read_render(1, 1) == art_before
    reset = service.reset_lettering(artifacts, 1, expected_revision=page1.revision,
        expected_image_sha256=service.active_render(artifacts, 1).image_sha256)
    assert reset.locale == "es"
    assert "missing_translation" in reset.elements[0].resolved.warnings
    with pytest.raises(service.LetteringConflict, match="belongs to the project"):
        save(artifacts, update(reset, locale="fr"))
    assert list((artifacts.project_dir / "lettering/translations").glob("*/prepared.json"))


@run_async
async def test_stale_quote_and_insufficient_credits_never_reach_provider(translated_app, monkeypatch):
    app, artifacts, _, reservations, _, calls = translated_app
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        root = "/api/projects/book/lettering"
        estimate = (await client.get(root + "/translation-estimate?target_locale=es")).json()
        service.ensure_lettering(artifacts, 1)  # Lazy publication changes the guarded missing marker.
        body = {"target_locale": "es", "expected_snapshot_sha256": estimate["snapshot_sha256"]}
        stale = await client.post(root + "/translate", json=body, headers={"Idempotency-Key": "stale"})
        assert stale.status_code == 412
        assert not reservations and not calls
        from fastapi import HTTPException
        def denied(*args):
            raise HTTPException(402, "Insufficient credits")
        monkeypatch.setattr(credited_job, "reserve_credits", denied)
        body["expected_snapshot_sha256"] = (await client.get(root + "/translation-estimate?target_locale=es")).json()["snapshot_sha256"]
        denied_response = await client.post(root + "/translate", json=body, headers={"Idempotency-Key": "denied"})
        assert denied_response.status_code == 402
        assert not calls and not app.state.generation_jobs


@pytest.mark.parametrize("defect", ["duplicate", "missing", "unknown", "empty", "conflict", "second_batch_failure"])
@run_async
async def test_bad_or_conflicted_outputs_publish_nothing_and_retain_paid_evidence(book, monkeypatch, defect):
    artifacts, image = book
    add_page(artifacts, image)
    before = service.ensure_lettering(artifacts, 1)
    monkeypatch.setattr(translation, "MAX_BATCH_ELEMENTS", 1)
    prepared = translation.prepare_translation(artifacts, Config(), "es")
    calls = []
    async def provider(**kwargs):
        items = json.loads(kwargs["user_content"])["items"]
        rows = [{"page_number": item["page_number"], "element_id": item["element_id"], "text": "Traducido."} for item in items]
        calls.append(rows)
        if defect == "second_batch_failure" and len(calls) == 2:
            raise RuntimeError("second batch failed")
        if defect == "duplicate":
            rows += rows
        elif defect == "missing":
            rows = []
        elif defect == "unknown":
            rows[0]["element_id"] = "unknown"
        elif defect == "empty":
            rows[0]["text"] = ""
        elif defect == "conflict" and len(calls) == 1:
            artifacts.write_lettering_settings(LetteringSettings(revision=2, locale="fr"))
        value = {"translations": rows}
        kwargs["response_sink"](ApiResult(value=json.dumps(value)))
        return ApiResult(value=value)
    monkeypatch.setattr(translation, "generate_json", provider)
    with pytest.raises((ValueError, RuntimeError)):
        await translation.translate_project(artifacts, Config(), prepared)
    assert artifacts.read_lettering(1) == before
    assert not artifacts.lettering_path(2).exists()
    evidence = artifacts.project_dir / "lettering/translations"
    assert list(evidence.glob("*/raw_0000.json"))
    assert list(evidence.glob("*/failed.json"))
    if defect in {"conflict", "second_batch_failure"}:
        assert list(evidence.glob("*/validated_0000.json"))
    assert not list(evidence.glob("*/published.json"))


def test_estimate_rejects_baked_undrawn_and_stale_before_calls(book, monkeypatch):
    artifacts, _ = book
    paid = MagicMock(side_effect=AssertionError("estimate called a provider"))
    monkeypatch.setattr(translation, "generate_json", paid)
    monkeypatch.setattr(translation, "is_hybrid", lambda _: False)
    with pytest.raises(service.LetteringConflict, match="Baked"):
        translation.prepare_translation(artifacts, Config(), "es")
    monkeypatch.setattr(translation, "is_hybrid", lambda _: True)
    def undrawn(*args):
        raise service.LetteringConflict("Draw this page")
    monkeypatch.setattr(translation, "active_render", undrawn)
    with pytest.raises(service.LetteringConflict, match="Draw"):
        translation.prepare_translation(artifacts, Config(), "es")
    monkeypatch.setattr(translation, "active_render", service.active_render)
    state = service.ensure_lettering(artifacts, 1)
    artifacts.write_lettering(update(state, comic_page_sha256="a" * 64))
    with pytest.raises(service.LetteringConflict, match="earlier plan"):
        translation.prepare_translation(artifacts, Config(), "es")
    paid.assert_not_called()


@run_async
async def test_publication_failure_restores_all_current_pages(book, monkeypatch):
    artifacts, image = book
    add_page(artifacts, image)
    before = service.ensure_lettering(artifacts, 1)
    prepared = translation.prepare_translation(artifacts, Config(), "es")
    async def provider(**kwargs):
        return ApiResult(value={"translations": [{"page_number": item["page_number"],
            "element_id": item["element_id"], "text": "Traducido."}
            for item in json.loads(kwargs["user_content"])["items"]]})
    monkeypatch.setattr(translation, "generate_json", provider)
    original = artifacts.write_lettering
    def fail_second(state):
        if state.page_number == 2:
            raise OSError("publication unavailable")
        original(state)
    monkeypatch.setattr(artifacts, "write_lettering", fail_second)
    with pytest.raises(OSError, match="publication unavailable"):
        await translation.translate_project(artifacts, Config(), prepared)
    assert artifacts.read_lettering(1) == before
    assert not artifacts.lettering_path(2).exists()
    assert artifacts.read_lettering_settings().locale == "source"
    assert list((artifacts.project_dir / "lettering/translations").glob("*/prepared.json"))


@run_async
async def test_existing_empty_target_is_preserved_without_provider_and_active_copy_is_source(book, monkeypatch):
    artifacts, _ = book
    artifacts.write_lettering_settings(LetteringSettings(revision=1, locale="fr"))
    initial = service.ensure_lettering(artifacts, 1)
    item = initial.elements[0].model_dump()
    item["text_by_locale"] = {"source": "Original.", "fr": "Texte enregistré.", "es": ""}
    save(artifacts, update(initial, elements=[item]))
    prepared = translation.prepare_translation(artifacts, Config(), "en")
    assert json.loads(prepared.batches[0])["items"][0]["text"] == "Texte enregistré."
    prepared = translation.prepare_translation(artifacts, Config(), "es")
    assert prepared.estimate["translate_count"] == 0
    async def no_provider(**kwargs):
        raise AssertionError("preserved target called provider")
    monkeypatch.setattr(translation, "generate_json", no_provider)
    await translation.translate_project(artifacts, Config(), prepared)
    assert artifacts.read_lettering(1).elements[0].text_by_locale["es"] == ""
    assert artifacts.read_lettering_settings().locale == "es"


@run_async
async def test_translation_recovers_mixed_saved_locales_without_replacing_variants(book, monkeypatch):
    artifacts, image = book
    add_page(artifacts, image)
    saved = []
    for page_number, locale in ((1, "fr"), (2, "es")):
        initial = service.ensure_lettering(artifacts, page_number)
        item = initial.elements[0].model_dump()
        item["text_by_locale"] = {
            "source": "Edited source.", "fr": "Français.", "es": "Español."
        }
        state = service.resolve_lettering(
            update(initial, revision=3, locale=locale, elements=[item]),
            service.ensure_style(artifacts),
        )
        artifacts.write_lettering(state)
        saved.append(state)
    prepared = translation.prepare_translation(artifacts, Config(), "es")
    assert prepared.estimate["translate_count"] == 0
    assert prepared.estimate["preserved_target_count"] == 2
    paid = MagicMock(side_effect=AssertionError("retained translations require no provider"))
    monkeypatch.setattr(translation, "generate_json", paid)
    await translation.translate_project(artifacts, Config(), prepared)
    assert artifacts.read_lettering_settings().locale == "es"
    for old in saved:
        current = artifacts.read_lettering(old.page_number)
        assert current.locale == "es" and current.revision == old.revision + 1
        assert current.elements[0].resolved.text == "Español."
        assert current.elements[0].model_dump(exclude={"resolved"}) == old.elements[0].model_dump(exclude={"resolved"})
        assert not service.editor_state(artifacts, old.page_number)["needs_save"]
    paid.assert_not_called()
