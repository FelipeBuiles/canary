"""Local complete-page profile boundaries; no SDK or provider calls."""
import asyncio
import hashlib
import io
import json
from types import MappingProxyType, SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from PIL import Image

from novel_to_comic import codex_dev, page_drawing
from novel_to_comic.ai import codex_runtime
from novel_to_comic.config import Config
from novel_to_comic.models.draw import (
    BookEdition,
    PageCapabilityProfile, FrozenPageGenerationRequest,
    PageRenderCorrection, RetryProvenance,
)
from novel_to_comic.models.page import ApprovedVisualReference, ApprovedVisualReferenceInventory, ComicPage
from novel_to_comic.server.routers import pages
from novel_to_comic.target_artifacts import TargetArtifacts
from tests.test_complete_page_draw import _page


@pytest.fixture

def dev_routes(monkeypatch):
    process = dict.fromkeys(codex_dev._PROCESS)
    process.update(CANARY_CODEX_DEV_ENABLED="1", CANARY_ENV="development")
    monkeypatch.setattr(codex_dev, "_PROCESS", MappingProxyType(process))
    monkeypatch.setattr(codex_dev, "_SETTINGS_ERROR", None)
    monkeypatch.setattr(codex_dev, "_IMAGES", frozenset({"image-gemini-pro"}))
    monkeypatch.setattr(codex_dev, "_IMAGE_REASONING", "gpt-5.5")
    monkeypatch.setattr(codex_dev, "_TEXT", MappingProxyType({
        Config().effective_page_ocr_model(): "gpt-5.6-terra",
    }))


def _authorities(tmp_path, count):
    entities = [f"subject-{index}" for index in range(count)]
    original = _page()
    page = ComicPage.model_validate({
        **original.model_dump(exclude={"content_sha256"}),
        "content": [{
            **original.content[0].model_dump(),
            "entity_ids": entities, "appearance_states": {},
        }],
    })
    refs, files = [], {}
    for index, entity in enumerate(entities):
        ref_id = f"{entity}-ref"
        path = tmp_path / f"{ref_id}.png"
        output = io.BytesIO()
        Image.new("RGB", (3, 4), (index, 0, 0)).save(output, format="PNG")
        path.write_bytes(output.getvalue())
        refs.append(ApprovedVisualReference(
            id=ref_id, entity_id=entity, visual_anchor=f"Exact crown number {index}.",
        ))
        files[ref_id] = page_drawing.ApprovedReferenceFile(
            reference_id=ref_id, path=path, media_type="image/png",
        )
    return page, ApprovedVisualReferenceInventory(references=refs), files


def _compiled(page, inventory, files, config=None, **kwargs):
    return page_drawing.compile_page_generation_request(
        page, page_drawing.select_book_edition(
            edition_id="dev-edition", profile=page_drawing.current_page_capability_profile(config),
        ), inventory, files, retry=RetryProvenance(attempt=1), **kwargs,
    )


def test_production_profile_and_old_serialized_hashes_remain_compatible(monkeypatch):
    monkeypatch.setattr(codex_dev, "_IMAGES", frozenset())
    legacy_profile = {
        "id": "nano-banana-pro-complete-page-v1", "provider": "vertex-multimodal",
        "model": "gemini-3-pro-image", "complete_page_generation": True,
        "exact_visible_lettering": True, "max_image_references": 8,
        "reference_ordering": "ordered", "editing_modes": ["instructed", "region_targeted"],
        "output_width": 1696, "output_height": 2528, "output_media_type": "image/png",
        "max_prompt_characters": 32000, "retry_semantics": "bounded_submission",
        "max_attempts": 3, "price_per_page_usd": "0.134", "price_per_reference_usd": "0.00112",
    }
    def digest(payload):
        return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True,
                                         separators=(",", ":")).encode()).hexdigest()
    profile = page_drawing.production_page_capability_profile()
    assert profile.exact_visible_lettering is False
    assert profile.id.endswith("-hybrid-v1")
    profile = PageCapabilityProfile.model_validate(legacy_profile)
    assert profile.content_sha256 == digest(legacy_profile)
    legacy_edition = {"revision": 1, "id": "old-edition", "capability_profile": legacy_profile}
    legacy_edition["content_sha256"] = digest(legacy_edition)
    edition = BookEdition.model_validate(legacy_edition)
    assert edition.model_dump(mode="json") == legacy_edition
    legacy_request = {
        "page_number": 7, "comic_page_revision": 2, "comic_page_sha256": "a" * 64,
        "edition_id": edition.id, "edition_revision": 1, "edition_sha256": edition.content_sha256,
        "profile_id": profile.id, "profile_sha256": profile.content_sha256,
        "provider": profile.provider, "model": profile.model, "prompt": "Exact old request",
        "lettering": [], "references": [], "output_width": 1696, "output_height": 2528,
        "output_media_type": "image/png", "estimated_cost_usd": "0.134",
        "artifact_kind": "complete_page", "retry": {"attempt": 1, "retries_request_sha256": None},
        "correction": None,
    }
    legacy_request["request_sha256"] = digest(legacy_request)
    request = FrozenPageGenerationRequest.model_validate(legacy_request)
    assert request.model_dump(mode="json") == legacy_request


def test_profile_binds_reasoner_and_runtime_and_cannot_rewrite_an_edition(tmp_path, monkeypatch, dev_routes):
    profile = page_drawing.current_page_capability_profile()
    assert (profile.provider, profile.model, profile.max_attempts) == ("codex-dev", "gpt-image-2", 1)
    assert page_drawing.page_profile_uses_native_dimensions(profile)
    artifacts = TargetArtifacts(tmp_path)
    production = BookEdition(revision=1, id="production", capability_profile=page_drawing.production_page_capability_profile())
    artifacts.write_book_edition(production)
    before = artifacts.book_edition_path.read_bytes()
    with pytest.raises(ValueError):
        page_drawing.ensure_current_page_edition(artifacts, production)
    assert artifacts.book_edition_path.read_bytes() == before
    edition = page_drawing.select_book_edition(edition_id="dev", profile=profile)
    monkeypatch.setattr(codex_dev, "_IMAGE_REASONING", "gpt-5.6-terra")
    assert page_drawing.current_page_capability_profile().id != profile.id
    with pytest.raises(ValueError):
        page_drawing.select_book_edition(edition_id=edition.id, profile=profile, existing=edition)
    monkeypatch.setattr(codex_dev, "_IMAGE_REASONING", "gpt-5.5")
    controls = codex_runtime.image_execution_controls()
    monkeypatch.setattr(codex_runtime, "image_execution_controls", lambda: (*controls, ("changed-runtime-control", "enabled")))
    assert page_drawing.current_page_capability_profile().id != profile.id
    with pytest.raises(ValueError):
        page_drawing.select_book_edition(edition_id=edition.id, profile=profile, existing=edition)


def test_five_references_preserve_exact_authority_and_six_reject(tmp_path, dev_routes):
    page, inventory, files = _authorities(tmp_path, 5)
    compiled = _compiled(page, inventory, files)
    prepared = page_drawing.complete_page_adapter(Config()).prepare(compiled)
    assert tuple(ref.id for ref in prepared.references) == tuple(ref.id for ref in inventory.references)
    assert prepared.reference_bytes == tuple(files[ref.id].path.read_bytes() for ref in inventory.references)
    assert compiled.request.lettering == ()
    for ref in inventory.references:
        assert ref.visual_anchor in prepared.prompt
    assert compiled.request.estimated_cost_usd == 0
    page, inventory, files = _authorities(tmp_path, 6)
    with pytest.raises(ValueError):
        _compiled(page, inventory, files)


@pytest.mark.parametrize("authority_count", [4, 5])
def test_correction_parent_consumes_one_of_five_image_inputs(tmp_path, dev_routes, authority_count):
    page, inventory, files = _authorities(tmp_path, authority_count)
    parent = next(iter(files.values())).path.read_bytes()
    correction = PageRenderCorrection(
        page_number=page.page_number, comic_page_revision=page.revision,
        comic_page_sha256=page.content_sha256, parent_render_revision=1,
        parent_render_image_sha256=hashlib.sha256(parent).hexdigest(),
        mode="instructed", instruction="Restore the crown; preserve exact lettering.",
        note="Restore the crown; preserve exact lettering.",
    )
    if authority_count == 5:
        with pytest.raises(ValueError):
            _compiled(page, inventory, files, correction=correction, edit_source_bytes=parent)
    else:
        compiled = _compiled(page, inventory, files, correction=correction, edit_source_bytes=parent)
        prepared = page_drawing.complete_page_adapter(Config()).prepare(compiled)
        assert prepared.edit_source_bytes == parent
        assert prepared.reference_bytes == tuple(files[ref.id].path.read_bytes() for ref in inventory.references)
        assert compiled.request.lettering == ()


def test_queue_all_later_reference_overflow_has_no_enqueue_or_credit_hold(tmp_path, monkeypatch, dev_routes):
    first, _, _ = _authorities(tmp_path, 2)
    later, inventory, files = _authorities(tmp_path, 6)
    later = ComicPage.model_validate({
        **later.model_dump(exclude={"content_sha256"}), "page_number": 8,
    })
    artifacts = TargetArtifacts(tmp_path)
    artifacts.write_page(first)
    artifacts.write_page(later)
    monkeypatch.setattr(TargetArtifacts, "read_plan", lambda self: SimpleNamespace(pages=[first, later]))
    monkeypatch.setattr(pages, "approved_visual_inventory", lambda path: inventory)
    monkeypatch.setattr(pages, "approved_reference_files", lambda path: files)
    enqueue = MagicMock(side_effect=AssertionError("partial batch was enqueued"))
    monkeypatch.setattr(pages, "enqueue_complete_page_draw", enqueue)
    from novel_to_comic.server import credited_job
    reserve = MagicMock(side_effect=AssertionError("batch reached credit reservation"))
    monkeypatch.setattr(credited_job, "reserve_credits", reserve)
    events = asyncio.Queue()
    app = SimpleNamespace(state=SimpleNamespace(
        event_queues={}, generation_jobs={}, generation_queue=events,
    ))
    with pytest.raises(ValueError):
        pages.enqueue_all_undrawn_pages(
            SimpleNamespace(app=app), project_id="project", user_id="user",
            project_dir=tmp_path, config=Config(),
        )
    enqueue.assert_not_called()
    reserve.assert_not_called()
    assert events.empty()
    assert app.state.generation_jobs == {}
    assert not artifacts.book_edition_path.exists()
    assert artifacts.provenance_revisions(7) == artifacts.provenance_revisions(8) == ()


@pytest.mark.parametrize("page_count", [0, 1])
def test_batch_subscription_quote_is_zero_and_subscription_even_when_empty(tmp_path, monkeypatch, dev_routes, page_count):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from novel_to_comic.server.deps import get_project
    page, inventory, files = _authorities(tmp_path, 2)
    artifacts = TargetArtifacts(tmp_path)
    artifacts.write_page(page)
    monkeypatch.setattr(TargetArtifacts, "read_plan", lambda self: SimpleNamespace(pages=[page] if page_count else []))
    monkeypatch.setattr(pages, "approved_visual_inventory", lambda path: inventory)
    monkeypatch.setattr(pages, "approved_reference_files", lambda path: files)
    app = FastAPI()
    app.include_router(pages.router)
    app.dependency_overrides[get_project] = lambda: (tmp_path, Config(), None)
    response = TestClient(app).get("/pages/generate/estimate")
    assert response.status_code == 200
    quote = response.json()
    assert quote["funding"] == "codex_subscription"
    assert quote["estimate_credits"] == quote["reserved_credits"] == 0
    assert not artifacts.book_edition_path.exists()


@pytest.mark.parametrize("reasoner", [None, "gpt-5.5", "gpt-5.6-terra"])
def test_native_draw_persists_untouched_png_and_unknown_observed_cost_and_model(tmp_path, monkeypatch, dev_routes, reasoner):
    import time
    from novel_to_comic.ai import client, finalisation
    from novel_to_comic.server import credited_job
    from novel_to_comic.server.codex_admission import draw_operations
    from novel_to_comic.usage import ApiResult

    page, inventory, files = _authorities(tmp_path, 2)
    config = Config(draw_model=f"codex-dev/image/{reasoner}") if reasoner else Config()
    compiled = _compiled(page, inventory, files, config=config)
    adapter = page_drawing.complete_page_adapter(config)
    output = io.BytesIO()
    Image.new("RGB", (83, 117), "navy").save(output, format="PNG")
    native = output.getvalue()
    reference_digests = [
        hashlib.sha256(files[ref.id].path.read_bytes()).hexdigest()
        for ref in inventory.references
    ]
    runtime = AsyncMock(return_value=SimpleNamespace(
        image_bytes=native, input_tokens=12, output_tokens=3,
        metadata={
            "turn_id": "native-turn", "tool_id": "native-image-tool",
            "execution_fingerprint": "restricted",
            "usage_scope": "reasoning_thread_only", "image_tool_usage_available": False,
            "references": [
                {"index": index, "sha256": digest, "mime": "image/png",
                 "path": f"/private/secret/reference-{index}.png"}
                for index, digest in enumerate(reference_digests)
            ],
            "local_path": "/private/secret/not-provenance", "untrusted": {"secret": "no"},
        },
    ))
    monkeypatch.setattr(codex_runtime, "run_image", runtime)
    monkeypatch.setattr(finalisation, "begin_image_call", AsyncMock(return_value=SimpleNamespace(
        event_id="native-call", started=time.perf_counter(), started_at=None,
        metadata={}, estimated_cost_usd=0, langfuse_input={}, operation="image",
    )))
    finalized = AsyncMock()
    monkeypatch.setattr(client, "_finalize_event_shielded", finalized)
    database = MagicMock()
    monkeypatch.setattr(credited_job, "get_db", lambda: database)
    artifacts = TargetArtifacts(tmp_path / "project")

    async def work():
        provenance = await page_drawing.draw_complete_page(
            compiled, adapter=adapter, artifacts=artifacts, page=page,
        )
        return ApiResult(value=provenance, usage=provenance.usage)

    app = SimpleNamespace(state=SimpleNamespace(
        generation_jobs={}, generation_job_sequence=0, generation_queue=asyncio.Queue(),
    ))
    job, created = credited_job.enqueue_reserved_generation_job(
        app, project_name="project", user_id="user", project_id="id",
        project_dir=artifacts.project_dir, stage="draw", kind="complete_page_draw",
        label="Page 7", payload={"request_sha256": compiled.request.request_sha256},
        work=work, debit_description="Draw page", reservation_credits=99,
        operations=draw_operations(config),
    )
    asyncio.run(job.runner())
    assert created
    database.rpc.assert_not_called()
    assert runtime.call_args.kwargs["reasoning_model"] == (reasoner or "gpt-5.5")
    assert runtime.await_count == 1
    assert runtime.call_args.kwargs["prompt"] == compiled.request.prompt
    assert runtime.call_args.kwargs["references"] == tuple(
        (files[ref.id].path.read_bytes(), "image/png") for ref in inventory.references
    )
    provenance = artifacts.read_provenance(page.page_number, 1)
    assert artifacts.read_render(page.page_number, 1) == native
    assert (provenance.render.width, provenance.render.height) == (83, 117)
    assert provenance.render.model == "gpt-image-2"
    assert provenance.render.cost_usd is None
    assert provenance.usage.model == config.draw_model
    assert provenance.usage.provider_model is None
    assert provenance.usage.cost_usd is None
    assert provenance.usage.funding == "codex_subscription"
    assert provenance.response_metadata["turn_id"] == "native-turn"
    assert provenance.provider_request_id == "native-image-tool"
    assert provenance.response_metadata["tool_id"] == "native-image-tool"
    assert provenance.response_metadata["usage_scope"] == "reasoning_thread_only"
    assert provenance.response_metadata["image_tool_usage_available"] is False
    reference_evidence = provenance.response_metadata["references"]
    assert [(ref["index"], ref["sha256"]) for ref in reference_evidence] == list(enumerate(reference_digests))
    assert all("path" not in ref for ref in reference_evidence)
    assert "local_path" not in provenance.response_metadata
    assert "untrusted" not in provenance.response_metadata
    assert finalized.call_args.kwargs["usage"].provider_model is None
    assert finalized.call_args.kwargs["response_data"]["id"] == provenance.provider_request_id


def test_explicit_retry_estimate_after_failed_codex_draw(tmp_path, monkeypatch, dev_routes):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from novel_to_comic.server.deps import get_project

    page, inventory, files = _authorities(tmp_path, 2)
    original = _compiled(page, inventory, files)
    artifacts = TargetArtifacts(tmp_path)
    artifacts.write_page(page)
    artifacts.write_book_edition(page_drawing.select_book_edition(
        edition_id="dev-edition", profile=page_drawing.current_page_capability_profile(),
    ))
    artifacts.write_request(original.request, request_revision=1)
    monkeypatch.setattr(pages, "approved_visual_inventory", lambda path: inventory)
    monkeypatch.setattr(pages, "approved_reference_files", lambda path: files)
    app = FastAPI()
    app.include_router(pages.router)
    app.dependency_overrides[get_project] = lambda: (tmp_path, Config(), None)

    client = TestClient(app)
    edition_bytes = artifacts.book_edition_path.read_bytes()
    prior = original.request
    for attempt in range(2, 5):
        response = client.get(f"/pages/{page.page_number}/generate/estimate")
        assert response.status_code == 200, response.text
        assert response.json()["funding"] == "codex_subscription"
        assert artifacts.request_revisions(page.page_number) == tuple(range(1, attempt))
        _, _, compiled = pages._prepare_initial_generation(
            (tmp_path, Config(), None), page.page_number, "canonical",
        )
        assert compiled.request.retry == RetryProvenance(
            attempt=attempt, retries_request_sha256=prior.request_sha256,
        )
        assert compiled.request.request_sha256 != prior.request_sha256
        assert compiled.request.edition_sha256 == original.request.edition_sha256
        assert compiled.request.profile_sha256 == original.request.profile_sha256
        artifacts.write_request(compiled.request, request_revision=attempt)
        prior = compiled.request
    assert artifacts.book_edition_path.read_bytes() == edition_bytes


@pytest.mark.parametrize("indeterminate", [False, True])
def test_codex_draw_failure_submits_once_even_on_explicit_retry(
    tmp_path, monkeypatch, dev_routes, indeterminate,
):
    from novel_to_comic.ai import finalisation

    page, inventory, files = _authorities(tmp_path, 2)
    original = _compiled(page, inventory, files)
    artifacts = TargetArtifacts(tmp_path / "project")
    artifacts.write_request(original.request, request_revision=1)
    retried = page_drawing.compile_page_generation_request(
        page, page_drawing.select_book_edition(
            edition_id="dev-edition", profile=page_drawing.current_page_capability_profile(),
        ), inventory, files, retry=pages._generation_retry(artifacts, page.page_number),
    )
    error = codex_runtime.CodexRuntimeError(
        "image_tool_failed", {"submitted": True, "indeterminate": indeterminate},
    )
    runtime = AsyncMock(side_effect=error)
    monkeypatch.setattr(codex_runtime, "run_image", runtime)
    monkeypatch.setattr(finalisation, "begin_image_call", AsyncMock(return_value=SimpleNamespace(event_id="retry-call")))
    monkeypatch.setattr(finalisation, "finalise_image_failure", AsyncMock())

    with pytest.raises(codex_runtime.CodexRuntimeError):
        asyncio.run(page_drawing.draw_complete_page(
            retried, adapter=page_drawing.complete_page_adapter(Config()),
            artifacts=artifacts, page=page,
        ))
    runtime.assert_awaited_once()
    assert artifacts.request_revisions(page.page_number) == (1, 2)
    assert artifacts.provenance_revisions(page.page_number) == ()


def test_failed_codex_correction_can_be_explicitly_retried(tmp_path, dev_routes):
    page, inventory, files = _authorities(tmp_path, 2)
    parent = next(iter(files.values())).path.read_bytes()
    correction = PageRenderCorrection(
        issue_ids=("issue-crown",),
        page_number=page.page_number, comic_page_revision=page.revision,
        comic_page_sha256=page.content_sha256, parent_render_revision=1,
        parent_render_image_sha256=hashlib.sha256(parent).hexdigest(),
        mode="instructed", instruction="Restore the crown; preserve exact lettering.",
    )
    original = _compiled(page, inventory, files, correction=correction, edit_source_bytes=parent)
    artifacts = TargetArtifacts(tmp_path / "project")
    artifacts.write_request(original.request, request_revision=2)
    retried = page_drawing.compile_page_generation_request(
        page, page_drawing.select_book_edition(
            edition_id="dev-edition", profile=page_drawing.current_page_capability_profile(),
        ), inventory, files,
        retry=pages._aggregated_correction_retry(
            artifacts, page_number=page.page_number, issue_ids=correction.issue_ids,
        ),
        correction=correction, edit_source_bytes=parent,
    )
    prepared = page_drawing.complete_page_adapter(Config()).prepare(retried)
    assert retried.request.retry == RetryProvenance(
        attempt=2, retries_request_sha256=original.request.request_sha256,
    )
    assert retried.request.correction == correction
    assert prepared.edit_source_bytes == parent
    assert prepared.references == original.request.references
    assert retried.request.profile_sha256 == original.request.profile_sha256


def test_explicit_codex_draw_selection_cannot_reroute_frozen_request(tmp_path, dev_routes):
    first = Config(draw_model="codex-dev/image/gpt-5.5")
    second = Config(draw_model="codex-dev/image/gpt-5.6-terra")
    page, inventory, files = _authorities(tmp_path, 1)
    compiled = _compiled(page, inventory, files, config=first)
    first_adapter = page_drawing.complete_page_adapter(first)
    prepared = first_adapter.prepare(compiled)
    second_adapter = page_drawing.complete_page_adapter(second)
    assert page_drawing.current_page_capability_profile(first).id != page_drawing.current_page_capability_profile(second).id
    with pytest.raises(ValueError):
        second_adapter.prepare(compiled)
    with pytest.raises(ValueError):
        asyncio.run(second_adapter.generate(prepared))
    edition = page_drawing.select_book_edition(
        edition_id="fixed", profile=page_drawing.current_page_capability_profile(first),
    )
    with pytest.raises(ValueError, match="different page profile"):
        page_drawing.ensure_current_page_edition(TargetArtifacts(tmp_path), edition, second)


@pytest.fixture(autouse=True)
def reviewed_story_precondition(monkeypatch):
    # This suite tests rendering/credit contracts with deliberately partial
    # upstream fixtures. Real missing/stale review admission is tested in
    # test_narrative_review.py.
    monkeypatch.setattr("novel_to_comic.server.routers.pages.require_draw_narrative_reviews", lambda target: None)
    monkeypatch.setattr("novel_to_comic.narrative_review.require_draw_narrative_reviews", lambda target: None)
