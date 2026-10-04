"""Provider-free lettering lifecycle, browser composition and API regression gates."""

from __future__ import annotations

import hashlib
import io
import json
import zipfile
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image
from pydantic import ValidationError

from novel_to_comic.config import Config
from novel_to_comic.lettering import service
from novel_to_comic.lettering.renderer import render_lettered_page
from novel_to_comic.models.draw import (
    BookEdition,
    OCRExtraction,
    OCRTextObservation,
    ObservedRegion,
    RawOCRObservation,
    RenderAnalysis,
)
from novel_to_comic.models.lettering import LetteringSettings, PageLettering, RoleStyle
from novel_to_comic.models.page import ComicPage, PlannedPageRevision
from novel_to_comic.page_drawing import (
    ensure_current_page_edition,
    production_page_capability_profile,
)
from novel_to_comic.page_finishing import finish_book
from novel_to_comic.page_review import (
    DRAW_VALIDATOR_VERSION,
    revalidate_cached_page_render,
    record_analysis_issues,
)
from novel_to_comic.server.auth import get_current_user
from novel_to_comic.server.deps import get_project
from novel_to_comic.server.routers.lettering import router
from novel_to_comic.usage import UsageRecord
from .test_page_finishing import _edition, _write_valid_book


def update(state, **values):
    return type(state).model_validate(
        state.model_dump() | values | {"content_sha256": ""}
    )


@pytest.fixture
def book(tmp_path):
    return make_book(tmp_path)


def make_book(tmp_path):
    """A hybrid-lettering edition with one analysed page; shared by other suites."""
    profile = _edition().capability_profile.model_copy(
        update={
            "exact_visible_lettering": False,
            "id": "hybrid-fixture",
            "output_width": 800,
            "output_height": 1200,
        }
    )
    artifacts, image = _write_valid_book(
        tmp_path,
        edition=BookEdition(revision=1, id="hybrid", capability_profile=profile),
        size=(800, 1200),
    )
    page = artifacts.read_page(1)
    artifacts.write_analysis(
        RenderAnalysis(
            page_number=1,
            render_revision=1,
            render_image_sha256=hashlib.sha256(image).hexdigest(),
            comic_page_sha256=page.content_sha256,
            validator_version=DRAW_VALIDATOR_VERSION,
        )
    )
    return artifacts, image


def save(artifacts, state, *, base=None, reviewed=False):
    base = base or service.editor_state(artifacts, 1)
    return service.save_lettering(
        artifacts,
        1,
        state,
        expected_revision=base["saved_revision"],
        expected_image_sha256=base["render_image_sha256"],
        expected_style_sha256=base["style"].content_sha256,
        mark_reviewed=reviewed,
    )


def copy_state(state, text="Another door opened."):
    elements = [element.model_dump() for element in state.elements]
    elements[0]["text_by_locale"]["source"] = text
    return update(state, elements=elements)


def test_edit_invalidates_only_finish_and_retains_canonical_art_and_revision_history(
    book,
):
    artifacts, image = book
    before = {
        path: path.read_bytes()
        for directory in ("adapt", "plan", "draw")
        for path in (artifacts.project_dir / directory).rglob("*")
        if path.is_file()
    }
    initial = service.ensure_lettering(artifacts, 1)
    artifacts.export_path("pdf").parent.mkdir(parents=True, exist_ok=True)
    artifacts.export_path("pdf").write_bytes(b"obsolete package")
    state = save(artifacts, copy_state(initial), reviewed=True)
    assert state.revision == initial.revision + 1
    assert state.reviewed_against_image_sha256 == hashlib.sha256(image).hexdigest()
    assert state.elements[0].resolved.text == "Another door opened."
    assert not artifacts.export_path("pdf").exists()
    assert artifacts.lettering_revision_path(initial).is_file()
    assert artifacts.lettering_revision_path(state).is_file()
    assert {path: path.read_bytes() for path in before} == before


def test_copy_reset_and_placement_reset_are_independent(book):
    artifacts, _ = book
    initial = service.ensure_lettering(artifacts, 1)
    element = initial.elements[0].model_dump()
    element["placement"] = {"x": 0.30, "y": 0.40, "width": 0.4, "height": 0.15}
    element["text_by_locale"] = {"source": "Changed words."}
    changed = save(artifacts, update(initial, elements=[element]))
    element = changed.elements[0].model_dump()
    element["text_by_locale"]["source"] = (
        artifacts.read_page(1).content[0].lettering[0].text
    )
    reset_copy = save(artifacts, update(changed, elements=[element]))
    assert reset_copy.elements[0].placement == changed.elements[0].placement
    element = reset_copy.elements[0].model_dump()
    element["placement"] = element["suggested_placement"]
    assert (
        save(artifacts, update(reset_copy, elements=[element]))
        .elements[0]
        .text_by_locale
        == reset_copy.elements[0].text_by_locale
    )


def test_optimistic_conflict_keeps_the_newer_saved_state(book):
    artifacts, _ = book
    base = service.editor_state(artifacts, 1)
    first = save(artifacts, copy_state(base["state"], "First editor."), base=base)
    with pytest.raises(service.LetteringConflict, match="elsewhere"):
        save(artifacts, copy_state(base["state"], "Stale editor."), base=base)
    assert artifacts.read_lettering(1) == first


def test_concurrent_saves_cannot_both_claim_the_same_revision(book):
    artifacts, _ = book
    base = service.editor_state(artifacts, 1)

    def attempt(text):
        try:
            return save(artifacts, copy_state(base["state"], text), base=base).revision
        except service.LetteringConflict:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, ["One editor.", "Another editor."]))
    assert sorted(map(str, results)) == ["2", "conflict"]


@pytest.mark.parametrize(
    "defect",
    [
        "delete_source",
        "change_identity",
        "change_suggestion",
        "invent_tail",
        "duplicate",
    ],
)
def test_server_rejects_invalid_source_backed_edits(book, defect):
    artifacts, _ = book
    state = service.ensure_lettering(artifacts, 1)
    elements = [element.model_dump() for element in state.elements]
    if defect == "delete_source":
        elements = []
    elif defect == "change_identity":
        elements[0]["id"] = "another-id"
    elif defect == "change_suggestion":
        elements[0]["suggested_placement"]["x"] += 0.01
    elif defect == "invent_tail":
        elements[0]["tail_target"] = {"x": 0.5, "y": 0.6}
    elif defect == "duplicate":
        elements.append(elements[0])
    with pytest.raises((ValueError, ValidationError)):
        save(artifacts, update(state, elements=elements))
    assert artifacts.read_lettering(1) == state


def test_server_recomputes_forged_client_layout(book):
    artifacts, _ = book
    state = service.ensure_lettering(artifacts, 1)
    raw = copy_state(state).model_dump()
    raw["elements"][0]["resolved"]["lines"] = ["FORGED LINES"]
    raw["content_sha256"] = ""
    saved = save(artifacts, PageLettering.model_validate(raw))
    assert saved.elements[0].resolved.lines != ("FORGED LINES",)
    assert saved.elements[0].resolved.text == "Another door opened."


def test_missing_translation_is_visible_and_cannot_be_exported(book):
    artifacts, image = book
    artifacts.write_lettering_settings(LetteringSettings(revision=1, locale="fr"))
    state = service.ensure_lettering(artifacts, 1)
    assert "missing_translation" in state.elements[0].resolved.warnings
    with pytest.raises(ValueError, match="missing_translation"):
        render_lettered_page(state, service.ensure_style(artifacts), image, 800, 1200)
    item = state.elements[0].model_dump()
    item["text_by_locale"]["fr"] = "La porte s'est ouverte."
    state = save(artifacts, update(state, elements=[item]))
    assert state.elements[0].resolved.text == "La porte s'est ouverte."
    assert state.elements[0].text_by_locale["source"] == "The door opened."
    assert state.elements[0].resolved.warnings == ()


def test_http_draft_previews_preserve_missing_translation_and_cannot_bypass_finish(
    book,
):
    artifacts, image = book
    artifacts.write_lettering_settings(LetteringSettings(revision=1, locale="fr"))
    state = service.ensure_lettering(artifacts, 1)
    assert state.elements[0].resolved.text == state.elements[0].text_by_locale["source"]
    assert "missing_translation" in state.elements[0].resolved.warnings
    app = FastAPI()
    app.include_router(router, prefix="/api/projects/{project_id}")
    app.dependency_overrides[get_project] = lambda: (
        artifacts.project_dir,
        Config(),
        None,
    )
    app.dependency_overrides[get_current_user] = lambda: "user"
    client = TestClient(app)
    root = "/api/projects/test/pages/1/composite"
    for rendition, size in (
        ("thumbnail", (424, 636)),
        ("reader", (800, 1200)),
        ("full", (800, 1200)),
    ):
        response = client.get(f"{root}/{rendition}?render_revision=1")
        assert response.status_code == 200, response.text
        with Image.open(io.BytesIO(response.content)) as rendered:
            assert rendered.size == size
        assert client.get(f"{root}/{rendition}?render_revision=1").content == response.content
        with pytest.raises(ValueError, match="missing_translation"):
            service.composite_page(artifacts, 1, rendition=rendition)
    assert artifacts.read_lettering(1) == state
    result = finish_book(artifacts, formats=())
    assert not result.preflight.ready_to_export
    failures = result.preflight.pages[0].invariant_failures
    assert {failure.code for failure in failures} == {"lettering_layout"}
    assert any("missing_translation" in evidence for failure in failures for evidence in failure.evidence)
    assert result.preflight.correction_requests == ()
    assert artifacts.read_lettering(1) == state
    assert artifacts.read_render(1, 1) == image


def test_overflow_is_saved_but_blocks_finish_without_requesting_draw(book):
    artifacts, _ = book
    state = copy_state(
        service.ensure_lettering(artifacts, 1), "An extremely long caption. " * 100
    )
    saved = save(artifacts, state)
    assert saved.elements[0].resolved.overflow
    assert (
        saved.elements[0].resolved.font_size
        == service.ensure_style(artifacts).roles.caption.min_font_size
    )
    preview, _ = service.composite_page(artifacts, 1, draft_preview=True)
    with Image.open(preview) as rendered:
        assert rendered.size == (800, 1200)
    assert artifacts.read_lettering(1) == saved
    result = finish_book(artifacts, formats=())
    assert not result.preflight.ready_to_export
    assert result.preflight.correction_requests == ()
    assert {
        failure.code for failure in result.preflight.pages[0].invariant_failures
    } == {"lettering_layout"}
    assert artifacts.provenance_revisions(1) == (1,)


def test_composite_uses_same_resolved_svg_for_all_renditions_and_keys_all_inputs(
    book, monkeypatch
):
    artifacts, image = book
    state = service.ensure_lettering(artifacts, 1)
    style = service.ensure_style(artifacts)
    full, key = service.composite_page(artifacts, 1)
    data = full.read_bytes()
    assert data == render_lettered_page(state, style, image, 800, 1200)
    assert data != image
    monkeypatch.setattr(
        service,
        "render_lettered_page",
        lambda *args: pytest.fail("cached composite must not be regenerated"),
    )
    reader, reader_key = service.composite_page(artifacts, 1, rendition="reader")
    thumb, thumb_key = service.composite_page(artifacts, 1, rendition="thumbnail")
    assert key == reader_key == thumb_key
    assert Image.open(reader).size == (800, 1200)
    assert Image.open(thumb).size == (424, 636)
    render = service.active_render(artifacts, 1)
    assert key != service.composite_identity(render, update(state, locale="es"), style)
    assert key != service.composite_identity(render, copy_state(state), style)
    assert key != service.composite_identity(
        render, state, service.preset_style("pulp")
    )
    assert key != service.composite_identity(
        render.model_copy(update={"image_sha256": "b" * 64}), state, style
    )
    assert artifacts.read_render(1, 1) == image


def test_book_style_reflows_saved_pages_without_changing_source_or_art(book):
    artifacts, image = book
    state = service.ensure_lettering(artifacts, 1)
    previous_style = service.ensure_style(artifacts)
    style = service.save_style(
        artifacts,
        service.preset_style("pulp"),
        expected_revision=previous_style.revision,
    )
    saved = artifacts.read_lettering(1)
    assert saved.revision == state.revision + 1
    assert saved.style_sha256 == style.content_sha256
    assert saved.elements[0].text_by_locale == state.elements[0].text_by_locale
    assert saved.elements[0].placement == state.elements[0].placement
    assert artifacts.read_render(1, 1) == image
    with pytest.raises(service.LetteringConflict):
        service.save_style(
            artifacts, previous_style, expected_revision=previous_style.revision
        )


def test_first_multi_page_export_seeds_before_normalizing_any_page(book):
    artifacts, image = book
    first = artifacts.read_page(1)
    second = update(first, page_number=2)
    artifacts.write_page(second)
    plan = artifacts.read_plan()
    artifacts.write_plan(
        update(
            plan,
            revision=2,
            target_page_min=2,
            target_page_max=2,
            pages=[
                *plan.pages,
                PlannedPageRevision(
                    page_number=2, revision=1, content_sha256=second.content_sha256
                ),
            ],
        )
    )
    provenance = artifacts.read_provenance(1, 1)
    second_render = provenance.render.model_copy(
        update={"page_number": 2, "comic_page_sha256": second.content_sha256}
    )
    artifacts.write_render(page_number=2, render_revision=1, image=image)
    artifacts.write_provenance(provenance.model_copy(update={"render": second_render}))
    result = finish_book(artifacts)
    assert result.preflight.ready_to_export, result.preflight.model_dump()
    assert len(result.preflight.pages) == 2
    assert all(
        page.lettering_sha256 and page.composite_identity
        for page in result.preflight.pages
    )
    with zipfile.ZipFile(artifacts.export_path("cbz")) as archive:
        assert archive.namelist() == ["page_001.jpg", "page_002.jpg"]
        for page in result.preflight.pages:
            assert (
                hashlib.sha256(
                    archive.read(f"page_{page.page_number:03d}.jpg")
                ).hexdigest()
                == page.normalized_image_sha256
            )
    assert artifacts.read_render(1, 1) == artifacts.read_render(2, 1) == image


def test_new_art_revision_preserves_words_but_requires_placement_review(book):
    artifacts, image = book
    initial = save(
        artifacts, copy_state(service.ensure_lettering(artifacts, 1)), reviewed=True
    )
    provenance = artifacts.read_provenance(1, 1)
    buffer = io.BytesIO()
    Image.new("RGB", (800, 1200), "#ded5c4").save(buffer, "PNG")
    changed = buffer.getvalue()
    artifacts.write_render(page_number=1, render_revision=2, image=changed)
    render = provenance.render.model_copy(
        update={
            "revision": 2,
            "parent_revision": 1,
            "image_sha256": hashlib.sha256(changed).hexdigest(),
        }
    )
    artifacts.write_provenance(provenance.model_copy(update={"render": render}))
    view = service.editor_state(artifacts, 1)
    assert view["placement_review_needed"]
    assert view["state"] == initial
    assert service.placement_review_needed(initial, render)
    assert artifacts.read_render(1, 1) == image
    with pytest.raises(service.LetteringConflict):
        service.composite_page(artifacts, 1, expected_render_revision=1)


def test_retained_baked_edition_never_gets_a_duplicate_overlay(tmp_path):
    artifacts, image = _write_valid_book(tmp_path)
    assert service.editor_state(artifacts, 1)["mode"] == "baked"
    path, key = service.composite_page(artifacts, 1)
    assert path.read_bytes() == image and key is None
    assert not (tmp_path / "lettering").exists()
    with pytest.raises(service.LetteringConflict):
        service.ensure_lettering(artifacts, 1)


def test_retained_page_hash_and_profile_stay_readable_without_adding_reservations(
    tmp_path,
):
    artifacts, _ = _write_valid_book(tmp_path)
    page = artifacts.read_page(1)
    payload = page.model_dump()
    payload.pop("lettering_reservations")
    payload.pop("content_sha256")
    payload["content_sha256"] = hashlib.sha256(
        json.dumps(
            payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")
        ).encode()
    ).hexdigest()
    restored = ComicPage.model_validate(payload)
    assert restored.lettering_reservations is None
    assert restored.model_dump(mode="json") == json.loads(json.dumps(payload))
    from novel_to_comic.config import (
        COMPLETE_PAGE_MODEL, COMPLETE_PAGE_PROFILE_ID, COMPLETE_PAGE_PROVIDER,
    )

    # A retained baked Gemini edition, recognized by its full identity.
    profile = production_page_capability_profile().model_copy(
        update={
            "id": COMPLETE_PAGE_PROFILE_ID,
            "provider": COMPLETE_PAGE_PROVIDER,
            "model": COMPLETE_PAGE_MODEL,
            "exact_visible_lettering": True,
        }
    )
    edition = BookEdition(revision=1, id="retained", capability_profile=profile)
    assert (
        ensure_current_page_edition(
            artifacts, edition, Config(), allow_retained_review=True
        )
        == edition
    )
    with pytest.raises(ValueError):
        ensure_current_page_edition(artifacts, edition, Config())


def test_hybrid_ocr_checks_base_art_for_unwanted_comic_copy_not_missing_overlays(book):
    artifacts, image = book
    page = artifacts.read_page(1)
    render = artifacts.read_provenance(1, 1).render
    raw = RawOCRObservation(
        page_number=1,
        render_revision=1,
        render_image_sha256=render.image_sha256,
        extraction=OCRExtraction(
            lettering=[
                OCRTextObservation(
                    id="unwanted-copy",
                    text="Unwanted generated caption",
                    detected_region_id="comic-region",
                )
            ],
            incidental_text=[OCRTextObservation(id="sign", text="OPEN")],
            observed_regions=[
                ObservedRegion(
                    id="comic-region",
                    polygon=((0.1, 0.1), (0.4, 0.1), (0.4, 0.2), (0.1, 0.2)),
                )
            ],
        ),
        usage=UsageRecord(
            provider="fixture", model="fixture", operation="text", cost_usd=0
        ),
    )
    artifacts.write_raw_ocr(raw)
    # Remove only the synthetic fixture receipt; real analysis identities are immutable.
    for receipt in artifacts.analysis_path(1, 1).parent.glob("analysis_001*.json"):
        receipt.unlink()
    analysis = revalidate_cached_page_render(
        page=page, render=render, artifacts=artifacts
    )
    assert analysis.lettering_matches == ()
    assert analysis.invariant_failures == ()
    assert len(analysis.editorial_issues) == 1
    assert analysis.editorial_issues[0].code == "unexpected_generated_lettering"
    assert analysis.incidental_text[0].text == "OPEN"
    record_analysis_issues(artifacts, analysis)
    issue = artifacts.read_issues(1)[0]
    assert issue.detected_region_ids == ("comic-region",)
    assert issue.lettering_item_ids == ()
    assert issue.requires_resolution
    assert artifacts.read_render(1, 1) == image


def test_authenticated_free_routes_validate_revisions_and_serve_composites(
    book, monkeypatch
):
    artifacts, image = book
    app = FastAPI()
    app.include_router(router, prefix="/api/projects/{project_id}")
    app.dependency_overrides[get_project] = lambda: (
        artifacts.project_dir,
        Config(),
        None,
    )
    app.dependency_overrides[get_current_user] = lambda: "user"
    client = TestClient(app)
    root = "/api/projects/test/pages/1"
    paid = AsyncMock(side_effect=AssertionError("lettering must never call providers"))
    monkeypatch.setattr("novel_to_comic.clients.text.generate_json", paid)
    first = client.get(root + "/lettering")
    assert first.status_code == 200, first.text
    data = first.json()
    assert data["mode"] == "hybrid"
    state = data["state"]
    state["elements"][0]["text_by_locale"]["source"] = "Edited in the browser."
    state["content_sha256"] = ""
    body = {
        "state": state,
        "expected_revision": data["saved_revision"],
        "expected_image_sha256": data["render_image_sha256"],
        "expected_style_sha256": data["style"]["content_sha256"],
        "mark_reviewed": True,
    }
    saved = client.put(root + "/lettering", json=body)
    assert saved.status_code == 200, saved.text
    assert client.put(root + "/lettering", json=body).status_code == 409
    preview = client.get(root + "/composite/thumbnail?render_revision=1")
    assert preview.status_code == 200, preview.text
    assert preview.headers["cache-control"] == "private, no-cache"
    assert preview.headers["content-type"] == "image/webp"
    assert (
        client.get(root + "/composite/thumbnail?render_revision=2").status_code == 409
    )
    assert client.get(root + "/composite/invalid").status_code == 422
    assert artifacts.read_render(1, 1) == image
    paid.assert_not_called()


@pytest.mark.parametrize("project_locale", [None, "fr"])
def test_saved_locale_mismatch_opens_without_writes_and_requires_guarded_save(
    book, monkeypatch, project_locale
):
    artifacts, image = book
    initial = service.ensure_lettering(artifacts, 1)
    element = initial.elements[0].model_dump()
    element["text_by_locale"] = {
        "source": "Edited source.", "es": "Editado.", "fr": "Modifié."
    }
    element["translation_sources"] = {"es": "Edited source.", "fr": "Edited source."}
    element["placement"] = {"x": 0.30, "y": 0.40, "width": 0.4, "height": 0.15}
    custom = element | {
        "id": "custom-hidden", "source_lettering_item_id": None,
        "hidden": True, "rotation": 12,
    }
    persisted = service.resolve_lettering(
        update(initial, revision=7, locale="es", elements=[element, custom]),
        service.ensure_style(artifacts),
    )
    artifacts.write_lettering(persisted)
    if project_locale is not None:
        artifacts.write_lettering_settings(LetteringSettings(revision=2, locale=project_locale))
    else:
        assert not artifacts.lettering_settings_path.exists()
    expected_locale = project_locale or "source"
    before = {
        path: path.read_bytes()
        for path in (artifacts.project_dir / "lettering").rglob("*") if path.is_file()
    }
    paid = AsyncMock(side_effect=AssertionError("reopening must never call providers"))
    monkeypatch.setattr("novel_to_comic.clients.text.generate_json", paid)
    monkeypatch.setattr("novel_to_comic.lettering.translation.generate_json", paid)
    app = FastAPI()
    app.include_router(router, prefix="/api/projects/{project_id}")
    app.dependency_overrides[get_project] = lambda: (artifacts.project_dir, Config(), None)
    app.dependency_overrides[get_current_user] = lambda: "user"
    client = TestClient(app)
    root = "/api/projects/test/pages/1"
    response = client.get(root + "/lettering")
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["mode"] == "hybrid" and data["needs_save"]
    assert not data["source_stale"]
    assert data["saved_revision"] == data["state"]["revision"] == persisted.revision
    assert data["state"]["locale"] == data["settings"]["locale"] == expected_locale
    draft = PageLettering.model_validate(data["state"])
    for old, current in zip(persisted.elements, draft.elements, strict=True):
        assert old.model_dump(exclude={"resolved"}) == current.model_dump(exclude={"resolved"})
        assert current.resolved.text == current.text_by_locale[expected_locale]
    assert service.ensure_lettering(artifacts, 1) == persisted
    for rendition in ("full", "reader", "thumbnail"):
        with pytest.raises(service.LetteringConflict):
            service.composite_page(artifacts, 1, rendition=rendition)
    assert client.get(root + "/composite/thumbnail").status_code == 409
    preflight = finish_book(artifacts, formats=()).preflight
    assert not preflight.ready_to_export
    assert "lettering_layout" in {
        failure.code for failure in preflight.pages[0].invariant_failures
    }
    assert {
        path: path.read_bytes()
        for path in (artifacts.project_dir / "lettering").rglob("*") if path.is_file()
    } == before
    body = {
        "state": data["state"],
        "expected_revision": data["saved_revision"],
        "expected_image_sha256": data["render_image_sha256"],
        "expected_style_sha256": data["style"]["content_sha256"],
    }
    wrong_locale = update(draft, locale="es").model_dump(mode="json")
    assert client.put(root + "/lettering", json=body | {"state": wrong_locale}).status_code == 409
    for guard, value in (
        ("expected_revision", persisted.revision - 1),
        ("expected_image_sha256", "a" * 64),
        ("expected_style_sha256", "b" * 64),
    ):
        assert client.put(root + "/lettering", json=body | {guard: value}).status_code == 409
    assert artifacts.read_lettering(1) == persisted
    saved = client.put(root + "/lettering", json=body)
    assert saved.status_code == 200, saved.text
    assert not saved.json()["needs_save"]
    published = artifacts.read_lettering(1)
    assert published.revision == persisted.revision + 1
    assert published.locale == expected_locale
    assert published.elements == draft.elements
    assert artifacts.lettering_revision_path(persisted).read_bytes() == before[artifacts.lettering_revision_path(persisted)]
    assert client.put(root + "/lettering", json=body).status_code == 409
    assert service.composite_page(artifacts, 1)[0].is_file()
    assert artifacts.read_render(1, 1) == image
    assert artifacts.read_lettering_settings().locale == expected_locale
    paid.assert_not_called()


def test_models_reject_nonfinite_geometry_unsafe_styles_and_bad_reservation_anchors(
    book,
):
    artifacts, _ = book
    with pytest.raises(ValidationError):
        RoleStyle(fill='" onload="alert(1)')
    with pytest.raises(ValidationError):
        RoleStyle(max_font_size=float("inf"))
    page = artifacts.read_page(1)
    raw = page.model_dump()
    raw["content_sha256"] = ""
    raw["lettering_reservations"][0]["speaker_entity_id"] = "not-a-speaker"
    with pytest.raises(ValidationError):
        ComicPage.model_validate(raw)


def test_brief_change_invalidates_mutable_lettering_with_its_source(book):
    artifacts, _ = book
    service.ensure_lettering(artifacts, 1)
    assert artifacts.lettering_path(1).exists()
    artifacts.invalidate_after_brief()
    assert not artifacts.lettering_path(1).exists()
    assert not artifacts.book_edition_path.exists()


def test_unreviewed_placement_is_exportable_but_not_visually_accepted(book):
    artifacts, _ = book
    result = finish_book(artifacts)
    assert result.preflight.ready_to_export
    assert result.preflight.pages[0].lettering_placement_review_needed
    assert not result.preflight.correction_requests
    save(artifacts, service.ensure_lettering(artifacts, 1), reviewed=True)
    accepted = finish_book(artifacts)
    assert accepted.preflight.ready_to_export
    assert not accepted.preflight.pages[0].lettering_placement_review_needed


def test_unreviewed_copy_save_cannot_inherit_previous_visual_acceptance(book):
    artifacts, _ = book
    state = save(artifacts, service.ensure_lettering(artifacts, 1), reviewed=True)
    # An unchanged save is not a new presentation, but changed copy is.
    same = save(artifacts, state)
    assert same.reviewed_against_image_sha256 == state.reviewed_against_image_sha256
    changed = save(artifacts, copy_state(same), reviewed=False)
    assert changed.reviewed_against_image_sha256 is None
    assert changed.reviewed_against_render_revision is None
    assert service.editor_state(artifacts, 1)["placement_review_needed"]


def test_book_style_reflow_invalidates_visual_acceptance(book):
    artifacts, _ = book
    save(artifacts, service.ensure_lettering(artifacts, 1), reviewed=True)
    style = service.ensure_style(artifacts)
    roles = style.roles.model_dump()
    roles["caption"]["max_font_size"] += 2
    service.save_style(artifacts, update(style, roles=roles), expected_revision=style.revision)
    state = artifacts.read_lettering(1)
    assert state.reviewed_against_image_sha256 is None
    assert state.reviewed_against_render_revision is None
    assert service.editor_state(artifacts, 1)["placement_review_needed"]


def test_missing_bundled_glyph_is_not_exported_with_a_system_fallback(book):
    artifacts, _ = book
    initial = service.ensure_lettering(artifacts, 1)
    changed = save(artifacts, copy_state(initial, "Hello 🙂"))
    assert "missing_glyphs" in changed.elements[0].resolved.warnings
    preview, _ = service.composite_page(artifacts, 1, draft_preview=True)
    with Image.open(preview) as rendered:
        assert rendered.size == (800, 1200)
    assert artifacts.read_lettering(1) == changed
    result = finish_book(artifacts)
    assert not result.preflight.ready_to_export
    assert any(issue.code == "lettering_layout" for issue in result.preflight.pages[0].invariant_failures)
    assert not result.preflight.correction_requests


def test_page_list_flags_unreviewed_placement_without_writing_lettering(book, monkeypatch):
    from novel_to_comic.server.routers import pages
    from novel_to_comic.server.routers.pages import router as pages_router

    monkeypatch.setattr(pages, "_sync_draw_progress", lambda _project_dir, app=None: None)

    artifacts, _image = book
    app = FastAPI()
    app.include_router(pages_router, prefix="/api/projects/{project_id}")
    app.dependency_overrides[get_project] = lambda: (artifacts.project_dir, Config(), None)
    app.dependency_overrides[get_current_user] = lambda: "user"
    client = TestClient(app)

    def flag():
        response = client.get("/api/projects/test/pages")
        assert response.status_code == 200, response.text
        return response.json()["pages"][0]["lettering_placement_review_needed"]

    assert flag() is True
    with pytest.raises(Exception):
        artifacts.read_lettering(1)
    base = service.editor_state(artifacts, 1)
    save(artifacts, base["state"], base=base)
    assert flag() is True
    save(artifacts, service.editor_state(artifacts, 1)["state"], reviewed=True)
    assert flag() is False


def test_engine_upgrade_composites_without_an_editor_save_but_asks_for_review(book):
    artifacts, _image = book
    base = service.editor_state(artifacts, 1)
    saved = save(artifacts, base["state"], base=base, reviewed=True)
    render = service.active_render(artifacts, 1)
    assert not service.placement_review_needed(saved, render)
    elements = [element.model_dump() for element in saved.elements]
    for element in elements:
        element["resolved"]["engine_version"] = "lettering-svg-v9"
    stale = update(saved, elements=elements)
    artifacts.write_lettering(stale)
    before = artifacts.lettering_path(1).read_bytes()

    path, identity = service.composite_page(artifacts, 1)

    assert path.is_file() and identity
    assert artifacts.lettering_path(1).read_bytes() == before
    assert service.placement_review_needed(artifacts.read_lettering(1), render)


def test_lettering_save_records_an_author_outcome(book, monkeypatch):
    artifacts, _image = book
    recorded = []
    monkeypatch.setattr("novel_to_comic.server.routers.lettering.record_page_outcome",
                        lambda app, outcome, **kwargs: recorded.append((outcome, kwargs)))
    app = FastAPI()
    app.include_router(router, prefix="/api/projects/{project_id}")
    app.dependency_overrides[get_project] = lambda: (artifacts.project_dir, Config(), None)
    app.dependency_overrides[get_current_user] = lambda: "user"
    client = TestClient(app)
    root = "/api/projects/test/pages/1"
    data = client.get(root + "/lettering").json()
    saved = client.put(root + "/lettering", json={
        "state": {**data["state"], "content_sha256": ""}, "expected_revision": data["saved_revision"],
        "expected_image_sha256": data["render_image_sha256"],
        "expected_style_sha256": data["style"]["content_sha256"], "mark_reviewed": True,
    })
    assert saved.status_code == 200, saved.text
    [(outcome, kwargs)] = recorded
    assert outcome == "lettering_saved"
    assert kwargs["mode"] == "reviewed" and kwargs["page_number"] == 1
    assert kwargs["project_id"] == "test" and kwargs["user_id"] == "user"
