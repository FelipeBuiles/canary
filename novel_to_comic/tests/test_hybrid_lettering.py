"""Hybrid contracts, software layout, immutable art and provider-free export."""

from __future__ import annotations

import io
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image
from pydantic import ValidationError

from novel_to_comic.models.draw import (
    BookEdition,
    OCRExtraction,
    OCRTextObservation,
    ObservedRegion,
    RawOCRObservation,
)
from novel_to_comic.models.lettering import (
    LetteringStyle,
    PageLettering,
    Point,
    ReservationIntent,
    RoleStyle,
)
from novel_to_comic.models.page import PinnedGeometry
from novel_to_comic.target_artifacts import TargetArtifacts
from novel_to_comic.page_lettering import (
    _balanced_lines,
    composite_identity,
    overlay_svg,
    reservations_for_page,
    resolve_lettering,
    seed_lettering,
)
from novel_to_comic.lettering_service import (
    load_lettering,
    save_lettering,
    saved_composite,
)
from .test_page_finishing import _edition, _write_valid_book, _write_corrected_revision


def hybrid_book(tmp_path):
    old = _edition()
    profile = old.capability_profile.model_copy(
        update={"id": "fixture-hybrid-1", "exact_visible_lettering": False}
    )
    return _write_valid_book(
        tmp_path, edition=BookEdition(revision=1, id=old.id, capability_profile=profile)
    )


def changed(state, **patch):
    return PageLettering(**(state.model_dump(exclude={"content_sha256"}) | patch))


def edit_copy(state, text, *, locale=""):
    element = state.elements[0]
    return changed(
        state,
        locale=locale,
        elements=[
            element.model_copy(update={"copies": {locale: text}}),
            *state.elements[1:],
        ],
    )


def test_baked_edition_round_trip_preserves_exact_hash():
    edition = _edition()
    assert edition.capability_profile.exact_visible_lettering is True
    assert (
        BookEdition.model_validate_json(edition.model_dump_json()).content_sha256
        == edition.content_sha256
    )


def test_new_profiles_explicitly_version_hybrid_without_changing_model():
    from novel_to_comic.page_drawing import (
        production_page_capability_profile,
        openai_page_capability_profile,
        muse_page_capability_profile,
    )

    for profile in [
        production_page_capability_profile(),
        openai_page_capability_profile("gpt-image-2.5-flare"),
        muse_page_capability_profile(),
    ]:
        assert not profile.exact_visible_lettering
        assert profile.id.endswith("hybrid-v1")


def test_reservations_preserve_source_hash_and_order(tmp_path):
    artifacts, _ = hybrid_book(tmp_path)
    page = artifacts.read_page(1)
    original = page.model_dump_json()
    r = reservations_for_page(page)
    assert [e.lettering_item_id for e in r.elements] == ["letter-1"]
    assert [e.order for e in r.elements] == [1]
    assert page.model_dump_json() == original
    with pytest.raises(ValueError, match="exactly one"):
        reservations_for_page(page, {})
    with pytest.raises(ValueError, match="visible"):
        reservations_for_page(
            page, {"letter-1": ReservationIntent(speaker_entity_id="ghost")}
        )


def test_normalized_bounds_and_safe_style_fields():
    with pytest.raises(ValidationError):
        PinnedGeometry(x=0.9, y=0.1, width=0.5, height=0.1)
    with pytest.raises(ValidationError):
        RoleStyle(font="../../secret")
    with pytest.raises(ValidationError):
        RoleStyle(fill='red"/><script>bad()</script>')
    with pytest.raises(ValidationError):
        RoleStyle(min_size=30, max_size=10)
    with pytest.raises(ValidationError):
        Point(x=float("nan"), y=0.1)


def test_balanced_layout_is_deterministic_and_never_splits_words():
    style = LetteringStyle().caption
    copy = "The sea had been quiet all evening. Then the bells began to ring."
    a = _balanced_lines(copy, style, 22, 350, 5)
    assert a == _balanced_lines(copy, style, 22, 350, 5)
    assert " ".join(a) == copy
    assert len(a[-1].split()) > 1
    assert _balanced_lines("unbreakable" * 30, style, 22, 60, 10) is None


def test_explicit_newlines_are_retained():
    assert _balanced_lines(
        "First line\nSecond line", LetteringStyle().caption, 20, 400, 4
    ) == ("First line", "Second line")


def test_copy_override_locale_and_placement_do_not_mutate_source(tmp_path):
    a, art = hybrid_book(tmp_path)
    page = a.read_page(1)
    state = load_lettering(a, 1, 1.5)
    edited = resolve_lettering(
        edit_copy(state, "La puerta se abrió.", locale="es"), page, 1.5
    )
    assert " ".join(edited.elements[0].resolved.lines) == "La puerta se abrió."
    assert a.read_page(1) == page
    assert a.read_render(1, 1) == art
    assert composite_identity(art, state) != composite_identity(art, edited)
    assert (
        edited.elements[0].suggested_placement == state.elements[0].suggested_placement
    )


def test_missing_translation_does_not_silently_use_original(tmp_path):
    a, _ = hybrid_book(tmp_path)
    state = load_lettering(a, 1, 1.5)
    result = resolve_lettering(changed(state, locale="es"), a.read_page(1), 1.5)
    assert result.elements[0].resolved.overflow
    assert "Missing es copy" in result.elements[0].resolved.reason


def test_overflow_stops_at_minimum_and_hidden_copy_does_not_block(tmp_path):
    a, _ = hybrid_book(tmp_path)
    state = load_lettering(a, 1, 1.5)
    result = resolve_lettering(
        edit_copy(state, "unbreakable" * 100), a.read_page(1), 1.5
    )
    assert result.elements[0].resolved.overflow
    assert result.elements[0].resolved.font_size == state.style.caption.min_size
    hidden = result.elements[0].model_copy(update={"hidden": True})
    result = resolve_lettering(changed(result, elements=[hidden]), a.read_page(1), 1.5)
    assert not result.elements[0].resolved.overflow


def test_source_ids_must_be_retained_hidden_not_deleted(tmp_path):
    a, _ = hybrid_book(tmp_path)
    state = load_lettering(a, 1, 1.5)
    with pytest.raises(ValueError, match="hide an element"):
        resolve_lettering(changed(state, elements=[]), a.read_page(1), 1.5)


def test_svg_is_same_canonical_safe_geometry_and_explicit_lines(tmp_path):
    a, _ = hybrid_book(tmp_path)
    page = a.read_page(1)
    state = load_lettering(a, 1, 1.5)
    state = resolve_lettering(
        edit_copy(state, '<script>alert("x")</script> & sea'), page, 1.5
    )
    svg = overlay_svg(state, 1.5)
    root = ET.fromstring(svg)
    assert not root.findall(".//{http://www.w3.org/2000/svg}script")
    assert "&lt;script&gt;" in svg
    assert all(
        "textLength" in text.attrib
        for text in root.findall(".//{http://www.w3.org/2000/svg}text")
    )
    assert svg == overlay_svg(state, 1.5)


def test_save_cas_invalidates_finish_only_and_keeps_revision_history(tmp_path):
    a, art = hybrid_book(tmp_path)
    page_before = a.page_path(1).read_bytes()
    state = load_lettering(a, 1, 1.5)
    a.preflight_path.parent.mkdir(parents=True, exist_ok=True)
    a.preflight_path.write_text("stale")
    with a.lettering_lock():
        first = save_lettering(a, state, expected_sha256=None)
    assert not a.preflight_path.exists()
    with a.lettering_lock():
        second = save_lettering(
            a,
            edit_copy(first["state"], "Changed copy"),
            expected_sha256=first["saved_sha256"],
        )
    assert second["state"].revision == 2
    with pytest.raises(ValueError, match="another session"):
        with a.lettering_lock():
            save_lettering(a, state, expected_sha256=None)
    assert a.read_render(1, 1) == art
    assert a.page_path(1).read_bytes() == page_before
    assert (
        len(list((a.project_dir / "lettering/revisions/page_001").glob("*.json"))) == 2
    )


def test_concurrent_saves_have_one_winner(tmp_path):
    a, _ = hybrid_book(tmp_path)
    state = load_lettering(a, 1, 1.5)

    def write(text):
        try:
            with a.lettering_lock():
                save_lettering(a, edit_copy(state, text), expected_sha256=None)
            return True
        except ValueError:
            return False

    with ThreadPoolExecutor(max_workers=2) as pool:
        result = list(pool.map(write, ["One", "Two"]))
    assert sorted(result) == [False, True]


def test_draw_revision_retains_lettering_but_review_is_outdated(tmp_path):
    a, _ = hybrid_book(tmp_path)
    state = changed(load_lettering(a, 1, 1.5), reviewed_against_render_revision=1)
    with a.lettering_lock():
        save_lettering(a, state, expected_sha256=None)
    saved = a.lettering_path(1).read_bytes()
    _write_corrected_revision(a, revision=2, parent_revision=1, color=(20, 40, 60))
    assert a.lettering_path(1).read_bytes() == saved
    assert a.read_lettering(1).reviewed_against_render_revision != 2


def test_baked_lettering_edits_are_rejected(tmp_path):
    a, _ = _write_valid_book(tmp_path)
    page = a.read_page(1)
    state = seed_lettering(page, reservations_for_page(page), LetteringStyle(), 1.5)
    with pytest.raises(ValueError, match="baked"):
        save_lettering(a, state, expected_sha256=None)


def test_hybrid_prompt_omits_publishable_copy_and_style_lettering(tmp_path):
    from novel_to_comic.page_drawing import _compile_prompt

    a, _ = hybrid_book(tmp_path)
    page = a.read_page(1)
    text = _compile_prompt(
        page,
        (),
        style_template="Woodcut art. LETTERING STANDARD — Paint exact words. PAGE FRAMING STANDARD — Narrow gutters.",
        exact_visible_lettering=False,
    )
    assert "The door opened." not in text
    assert "Paint exact words" not in text
    assert "Narrow gutters" in text
    assert "lettering_reservations" in text
    assert "Draw NO speech/thought balloons" in text
    assert "The door opened." in _compile_prompt(page, (), exact_visible_lettering=True)


def test_hybrid_ocr_flags_only_generated_lettering_with_regions(tmp_path):
    from novel_to_comic.page_review import (
        _validate_observations,
        record_analysis_issues,
    )

    a, _ = hybrid_book(tmp_path)
    page = a.read_page(1)
    render = a.read_provenance(1, 1).render
    observation = OCRTextObservation(
        id="text1", text="BAD COPY", detected_region_id="region1"
    )
    incidental = OCRTextObservation(id="sign", text="OPEN", role="incidental_text")
    extraction = OCRExtraction(
        lettering=[observation],
        incidental_text=[incidental],
        observed_regions=[
            ObservedRegion(
                id="region1", polygon=[(0.1, 0.1), (0.3, 0.1), (0.3, 0.2), (0.1, 0.2)]
            )
        ],
    )
    raw = RawOCRObservation(
        page_number=1,
        render_revision=1,
        render_image_sha256=render.image_sha256,
        extraction=extraction,
    )
    result = _validate_observations(page=page, render=render, raw=raw, artifacts=a)
    assert not result.invariant_failures
    assert [e.code for e in result.editorial_issues] == [
        "unexpected_generated_lettering"
    ]
    assert result.incidental_text == (incidental,)
    record_analysis_issues(a, result)
    issue = a.read_issues(1)[0]
    assert issue.detected_region_ids == ("region1",)
    assert issue.lettering_item_ids == ()


def test_plan_cascade_preserves_lettering_only_for_draw(tmp_path):
    from novel_to_comic.stages import clean_cascade

    assert tmp_path / "lettering" not in clean_cascade(tmp_path, "draw")
    assert tmp_path / "lettering" in clean_cascade(tmp_path, "plan")
    assert tmp_path / "lettering" in clean_cascade(tmp_path, "adapt")


def test_compositor_and_finish_export_identical_saved_overlay(tmp_path):
    from novel_to_comic.page_finishing import finish_book

    a, art = hybrid_book(tmp_path)
    state = load_lettering(a, 1, 1.5)
    with a.lettering_lock():
        save_lettering(a, state, expected_sha256=None)
    composed, saved, identity = saved_composite(a, 1, art)
    assert Image.open(io.BytesIO(composed)).size == (120, 180)
    assert composed != art
    assert identity == composite_identity(art, saved)
    result = finish_book(a, formats=("pdf", "cbz"))
    assert result.preflight.ready_to_export
    assert result.preflight.pages[0].lettering_sha256 == saved.content_sha256
    assert result.preflight.pages[0].composite_sha256 == identity
    assert a.read_render(1, 1) == art


def test_overflow_finish_is_typography_error_never_draw_request(tmp_path):
    from novel_to_comic.page_finishing import finish_book

    a, _ = hybrid_book(tmp_path)
    state = edit_copy(load_lettering(a, 1, 1.5), "longword" * 150)
    with a.lettering_lock():
        save_lettering(a, state, expected_sha256=None)
    result = finish_book(a, formats=())
    assert not result.preflight.ready_to_export
    assert any(
        f.code == "lettering_layout"
        for f in result.preflight.pages[0].invariant_failures
    )
    assert not result.preflight.correction_requests


def test_http_preview_is_read_only_and_stale_save_returns_conflict(tmp_path):
    from novel_to_comic.server.routers import lettering
    from novel_to_comic.config import Config
    from novel_to_comic.server.ratelimit import limiter

    a, art = hybrid_book(tmp_path)
    app = FastAPI()
    app.state.limiter = limiter
    app.include_router(lettering.router)
    app.dependency_overrides[lettering.get_project] = lambda: (tmp_path, Config(), None)
    with TestClient(app) as client:
        initial = client.get("/pages/1/lettering").json()
        state = initial["state"]
        state.pop("content_sha256")
        state["elements"][0]["copies"] = {"": "Updated words"}
        body = {"state": state, "expected_sha256": None}
        preview = client.post("/pages/1/lettering/preview", json=body)
        assert preview.status_code == 200, preview.text
        assert not a.lettering_path(1).exists()
        saved = client.put("/pages/1/lettering", json=body)
        assert saved.status_code == 200, saved.text
        assert client.put("/pages/1/lettering", json=body).status_code == 409
        assert client.put("/pages/2/lettering", json=body).status_code == 422
        assert a.read_render(1, 1) == art


def test_preview_uses_cached_local_fonts_but_identical_export_geometry(tmp_path):
    artifacts, _ = hybrid_book(tmp_path)
    state = load_lettering(artifacts, 1, 1.5)
    preview = ET.fromstring(overlay_svg(state, 1.5, embed_fonts=False))
    exported = ET.fromstring(overlay_svg(state, 1.5))
    ns = "{http://www.w3.org/2000/svg}"
    assert len(overlay_svg(state, 1.5, embed_fonts=False)) < 10000
    assert "/static/fonts/" in overlay_svg(state, 1.5, embed_fonts=False)
    assert [ET.tostring(g) for g in preview.findall(f"{ns}g")] == [
        ET.tostring(g) for g in exported.findall(f"{ns}g")
    ]


def test_untrusted_resolved_lines_cannot_bypass_server_layout(tmp_path):
    from novel_to_comic.lettering_service import prepare_lettering

    artifacts, _ = hybrid_book(tmp_path)
    state = load_lettering(artifacts, 1, 1.5)
    element = state.elements[0]
    forged = element.resolved.model_copy(
        update={"lines": ("Forged text",), "widths": (1,), "overflow": False}
    )
    edited = changed(state, elements=[element.model_copy(update={"resolved": forged})])
    actual, _, _ = prepare_lettering(artifacts, edited)
    assert actual.elements[0].resolved.lines == element.resolved.lines


def test_selected_structured_style_seeds_book_without_an_extra_ai_call(tmp_path):
    from novel_to_comic.config import Config, save_config
    from novel_to_comic.stages.s2_style import normalize_suggestion, save_suggestions
    from novel_to_comic.style_contract import style_template_for_suggestion
    from novel_to_comic.lettering_service import default_style

    suggestion = normalize_suggestion(
        {
            "label": "Night",
            "medium": "woodcut",
            "template": "Black ink and deep shadow.",
            "lettering": "White geometric captions on black.",
            "lettering_style": {
                "preset": "noir",
                "caption": {
                    "font": "Exo2-SemiBold",
                    "fill": "#111111",
                    "color": "#ffffff",
                },
            },
        }
    )
    assert normalize_suggestion(suggestion)["id"] == suggestion["id"]
    save_suggestions(tmp_path, [suggestion], "Night")
    save_config(
        Config(style_template=style_template_for_suggestion(suggestion)), tmp_path
    )
    style = default_style(TargetArtifacts(tmp_path))
    assert style.caption.font == "Exo2-SemiBold"
    assert style.caption.fill == "#111111"


def test_diagonal_tail_root_intersects_the_rounded_body():
    from novel_to_comic.page_lettering import _rounded_boundary

    x, y = _rounded_boundary(1, 1, 100, 30)
    assert x == pytest.approx(y)
    assert x < 100 and y <= 30
    x, y = _rounded_boundary(5, 1, 100, 30)
    assert (x - 70) ** 2 + y * y == pytest.approx(30**2)


def test_scale_keeps_measured_text_inside_padded_body(tmp_path):
    artifacts, _ = hybrid_book(tmp_path)
    state = load_lettering(artifacts, 1, 1.5)
    element = state.elements[0].model_copy(update={"kind": "dialogue", "scale": 0.5})
    state = resolve_lettering(
        changed(state, elements=[element]), artifacts.read_page(1), 1.5
    )
    e = state.elements[0]
    assert not e.resolved.overflow
    available = e.placement.width * 1000 - 2 * (
        state.style.dialogue.padding * e.scale + e.placement.width * 1000 * 0.09
    )
    assert max(e.resolved.widths) * e.scale <= available


def test_provider_free_edits_work_with_unavailable_credit_ledger_and_other_draw_jobs(
    tmp_path,
):
    from types import SimpleNamespace
    from novel_to_comic.server.admission import Admission, admission_middleware
    from novel_to_comic.server.auth import get_current_user
    from novel_to_comic.server.routers import lettering
    from novel_to_comic.server.ratelimit import limiter
    from novel_to_comic.config import Config

    hybrid_book(tmp_path)
    app = FastAPI()
    app.state.limiter = limiter
    app.state.admission = Admission(tmp_path)
    app.state.running_tasks = {}
    app.state.style_tasks = {}
    app.state.credit_leases_ready = False
    app.state.generation_jobs = {
        "another-page": SimpleNamespace(project_name="account:book", status="running")
    }
    app.dependency_overrides[get_current_user] = lambda: "account"
    app.dependency_overrides[lettering.get_project] = lambda: (tmp_path, Config(), None)
    app.middleware("http")(admission_middleware)
    app.include_router(lettering.router, prefix="/api/projects/{project_id}")
    with TestClient(app) as client:
        value = client.get("/api/projects/book/pages/1/lettering").json()
        state = value["state"]
        state.pop("content_sha256")
        body = {"state": state, "expected_sha256": None}
        assert (
            client.post(
                "/api/projects/book/pages/1/lettering/preview", json=body
            ).status_code
            == 200
        )
        assert (
            client.put("/api/projects/book/pages/1/lettering", json=body).status_code
            == 200
        )


def test_mixed_cjk_and_latin_copy_does_not_gain_spaces():
    assert _balanced_lines(
        "海Tokyoの灯", RoleStyle(font="MPLUS1p-Bold"), 20, 500, 2
    ) == ("海Tokyoの灯",)


def test_interrupted_publication_does_not_overwrite_history_or_strand_saves(tmp_path):
    artifacts, _ = hybrid_book(tmp_path)
    state = load_lettering(artifacts, 1, 1.5)
    with artifacts.lettering_lock():
        first = save_lettering(artifacts, state, expected_sha256=None)["state"]
        orphan = changed(edit_copy(first, "Interrupted draft"), revision=2)
        archive = (
            artifacts.lettering_path(1).parent.parent
            / "revisions"
            / "page_001"
            / "revision_000002.json"
        )
        artifacts._write_immutable_model(archive, orphan, PageLettering)
        resumed = save_lettering(
            artifacts,
            edit_copy(first, "Recovered draft"),
            expected_sha256=first.content_sha256,
        )["state"]
    assert resumed.revision == 3
    assert artifacts.read_lettering(1) == resumed
    assert (
        PageLettering.model_validate_json(archive.read_text()).content_sha256
        == orphan.content_sha256
    )
