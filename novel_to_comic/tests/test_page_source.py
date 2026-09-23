"""Pages → Source: a provider-free read from a planned page back to its manuscript."""

from __future__ import annotations

import hashlib
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from novel_to_comic.config import Config
from novel_to_comic.models.adaptation import (
    AdaptationLedgerEntry,
    AdaptedBeat,
    BookAdaptation,
    LetteringItem,
    NarrativeTreatment,
)
from novel_to_comic.models.draw import (
    LetteringMatch,
    ObservedRegion,
    OCRTextObservation,
    PageGenerationProvenance,
    PageRenderRevision,
    RenderAnalysis,
)
from novel_to_comic.models.lettering import LetteringElement, PageLettering
from novel_to_comic.models.page import ComicPage, PageContent, PinnedGeometry
from novel_to_comic.models.source import SourceDocument, SourceScene, SourceUnit
from novel_to_comic import page_source
from novel_to_comic.page_source import page_source_view
from novel_to_comic.server.routers import pages
from novel_to_comic.target_artifacts import TargetArtifacts
from novel_to_comic.usage import UsageRecord

UNITS = (
    "The harbour lay under a green fog. ",
    "Johansen said the idol was older than the sea itself. ",
    "Nobody believed him that night. ",
    "Later, in Oslo, his widow burned the letters. ",
    "The rain drummed on the chamber door.",
)


def _source() -> SourceDocument:
    units, offset = [], 0
    for ordinal, text in enumerate(UNITS, 1):
        units.append(SourceUnit(
            id=f"source-{ordinal}", ordinal=ordinal,
            start_offset=offset, end_offset=offset + len(text), text=text,
        ))
        offset += len(text)
    return SourceDocument(
        text="".join(UNITS),
        units=units,
        scenes=[
            SourceScene(id="scene-1", title="The harbour", first_unit_id="source-1", last_unit_id="source-3"),
            SourceScene(id="scene-2", title="Oslo", first_unit_id="source-4", last_unit_id="source-5"),
        ],
    )


def _adaptation(source: SourceDocument) -> BookAdaptation:
    return BookAdaptation(
        revision=1,
        source_sha256=source.source_sha256,
        brief_revision=1,
        brief_sha256="b" * 64,
        treatment=NarrativeTreatment(causal_spine=["A warning nobody heeds."]),
        beats=[
            AdaptedBeat(
                id="beat-1", order=1, summary="Fog, and Johansen's warning.",
                narrative_function="initial",
                source_unit_ids=["source-1", "source-2", "source-3"],
                lettering=[
                    LetteringItem(
                        id="letter-1", kind="dialogue", speaker="Johansen",
                        text="The idol was older than the sea itself!",
                        source_unit_ids=["source-2"],
                    ),
                    LetteringItem(
                        id="letter-2", kind="caption", text="No one listened.",
                        source_unit_ids=["source-3"],
                    ),
                ],
            ),
            AdaptedBeat(
                id="beat-2", order=2, summary="The chamber door in the rain.",
                narrative_function="prolongation", source_unit_ids=["source-5"],
            ),
        ],
        ledger=[
            AdaptationLedgerEntry(source_unit_id="source-1", disposition="depicted",
                                  adapted_beat_ids=["beat-1"], preserved_function="Fog is drawn."),
            AdaptationLedgerEntry(source_unit_id="source-2", disposition="dialogue",
                                  adapted_beat_ids=["beat-1"], preserved_function="Spoken warning."),
            AdaptationLedgerEntry(source_unit_id="source-3", disposition="caption",
                                  adapted_beat_ids=["beat-1"], preserved_function="Disbelief."),
            AdaptationLedgerEntry(source_unit_id="source-4", disposition="intentionally_omitted",
                                  reason="Epilogue material.", preserved_function="None."),
            AdaptationLedgerEntry(source_unit_id="source-5", disposition="depicted",
                                  adapted_beat_ids=["beat-2"], preserved_function="Rain is drawn."),
        ],
    )


def _page(adaptation: BookAdaptation) -> ComicPage:
    beat_1 = adaptation.beats[0]
    return ComicPage(
        revision=1,
        page_number=1,
        adaptation_revision=adaptation.revision,
        adaptation_sha256=adaptation.content_sha256,
        emphasis="initial",
        density_intent="standard",
        content=(
            PageContent(id="panel-1", order=1, beat_ids=("beat-1",), visual_intent="Johansen in fog.",
                        lettering=(beat_1.lettering[0],)),
            PageContent(id="panel-2", order=2, beat_ids=("beat-1",), visual_intent="Sailors turn away.",
                        lettering=(beat_1.lettering[1],)),
            PageContent(id="panel-3", order=3, beat_ids=("beat-2",), visual_intent="Rain on the door."),
        ),
        reading_order=("panel-1", "letter-1", "panel-2", "letter-2", "panel-3"),
    )


def _render(artifacts: TargetArtifacts, page: ComicPage) -> PageRenderRevision:
    image = b"page-1-render-1"
    render = PageRenderRevision(
        page_number=1, revision=1, comic_page_revision=page.revision,
        comic_page_sha256=page.content_sha256,
        request_sha256=hashlib.sha256(b"request").hexdigest(),
        image_sha256=hashlib.sha256(image).hexdigest(),
        width=120, height=180, provider="fixture", model="fixture", latency_ms=1, cost_usd="0",
    )
    artifacts.write_render(page_number=1, render_revision=1, image=image)
    artifacts.write_provenance(PageGenerationProvenance(
        render=render,
        usage=UsageRecord(provider="fixture", model="fixture", operation="image", cost_usd=0),
    ))
    return render


def _analysis(
    page: ComicPage,
    render: PageRenderRevision,
    *,
    image_sha256: str | None = None,
) -> RenderAnalysis:
    return RenderAnalysis(
        page_number=1, render_revision=render.revision,
        render_image_sha256=image_sha256 or render.image_sha256,
        comic_page_sha256=page.content_sha256,
        ocr_observations=(
            OCRTextObservation(id="ocr_001", text="The idol was older than the sea itself!",
                               detected_region_id="panel_000"),
            OCRTextObservation(id="ocr_002", text="No one listened.", detected_region_id="panel_001"),
        ),
        # Only the first item was read back; the second has no located text.
        lettering_matches=(
            LetteringMatch(lettering_item_id="letter-1", observation_id="ocr_001",
                           canonical_text="x", observed_text="x"),
        ),
        observed_regions=(
            ObservedRegion(id="region_001", polygon=((0.1, 0.2), (0.4, 0.2), (0.4, 0.3), (0.1, 0.3))),
            ObservedRegion(id="region_002", polygon=((0.6, 0.2), (0.9, 0.2), (0.9, 0.3), (0.6, 0.3))),
            # Panel boxes are observed too, but say nothing about planned content.
            ObservedRegion(id="panel_000", polygon=((0, 0), (0.5, 0), (0.5, 0.5), (0, 0.5))),
            ObservedRegion(id="panel_001", polygon=((0.5, 0), (1, 0), (1, 0.5), (0.5, 0.5))),
        ),
        observed_reading_order=("panel_000", "panel_001"),
        reading_order_proven=True,
    )


def _element(item_id: str, **update) -> LetteringElement:
    placement = PinnedGeometry(x=0.1, y=0.6, width=0.5, height=0.2)
    values = dict(
        id=f"el-{item_id}", source_lettering_item_id=item_id, role="speech",
        text_by_locale={"source": "copy"}, suggested_placement=placement, placement=placement,
        scale=1.5, rotation=-8,
    )
    return LetteringElement(**(values | update))


def _lettering(page: ComicPage, *elements: LetteringElement, comic_page_sha256: str | None = None):
    return PageLettering(
        revision=3, page_number=1, comic_page_sha256=comic_page_sha256 or page.content_sha256,
        style_sha256="e" * 64, canvas_aspect_ratio=2 / 3, elements=elements,
    )


@pytest.fixture
def story(tmp_path):
    artifacts = TargetArtifacts(tmp_path)
    source = _source()
    adaptation = _adaptation(source)
    page = _page(adaptation)
    artifacts.write_source(source)
    artifacts.write_adaptation(adaptation)
    artifacts.write_page(page)
    return SimpleNamespace(artifacts=artifacts, source=source, adaptation=adaptation, page=page, dir=tmp_path)


def _marks(view: dict) -> list[tuple[str, str, list[str], str]]:
    return [
        (unit["id"], segment["text"], segment["lettering_item_ids"], segment["kind"])
        for passage in view["passages"]
        for unit in passage["units"]
        for segment in unit["segments"]
        if segment["kind"]
    ]


def _located(view: dict) -> dict[str, dict | None]:
    return {item["id"]: item["element"] or item["region"] for item in view["lettering"]}


def test_passages_follow_beats_and_skip_unadapted_units(story):
    view = page_source_view(story.artifacts, 1)

    assert [(p["scene_title"], [u["id"] for u in p["units"]]) for p in view["passages"]] == [
        ("The harbour", ["source-1", "source-2", "source-3"]),
        ("Oslo", ["source-5"]),
    ]
    # Segments always reassemble the exact manuscript text.
    for passage in view["passages"]:
        for unit in passage["units"]:
            assert "".join(s["text"] for s in unit["segments"]) == UNITS[unit["ordinal"] - 1]


def test_lettering_marks_verbatim_words_and_depiction_is_never_located(story):
    marks = _marks(page_source_view(story.artifacts, 1))

    assert marks == [
        # Depicted detail has no recorded place on model-composed art.
        ("source-1", "The harbour lay under a green fog.", [], "depicted"),
        # Verbatim dialogue highlights only the quoted words.
        ("source-2", "the idol was older than the sea itself", ["letter-1"], "lettering"),
        # A paraphrased caption cites the whole unit.
        ("source-3", "Nobody believed him that night.", ["letter-2"], "lettering"),
        ("source-5", "The rain drummed on the chamber door.", [], "depicted"),
    ]


def test_undrawn_integrated_page_locates_nothing(story):
    view = page_source_view(story.artifacts, 1)

    assert [(item["id"], item["text"]) for item in view["lettering"]] == [
        ("letter-1", "The idol was older than the sea itself!"),
        ("letter-2", "No one listened."),
    ]
    assert _located(view) == {"letter-1": None, "letter-2": None}
    assert view["geometry"] is None


def test_integrated_text_check_locates_matched_lettering_only(story):
    render = _render(story.artifacts, story.page)
    story.artifacts.write_analysis(_analysis(story.page, render))

    view = page_source_view(story.artifacts, 1)

    assert view["lettering"][0]["region"] == pytest.approx({"x": 0.1, "y": 0.2, "width": 0.3, "height": 0.1})
    assert view["lettering"][1]["region"] is None
    assert view["geometry"] == {"source": "text_check", "render_revision": 1}


def test_text_check_of_other_art_is_not_used(story):
    render = _render(story.artifacts, story.page)
    story.artifacts.write_analysis(_analysis(story.page, render, image_sha256="f" * 64))

    view = page_source_view(story.artifacts, 1)

    assert _located(view) == {"letter-1": None, "letter-2": None}
    assert view["geometry"] is None


def test_editable_edition_uses_saved_lettering_elements(story, monkeypatch):
    monkeypatch.setattr(page_source, "is_hybrid", lambda target: True)
    render = _render(story.artifacts, story.page)
    # A text check on base art never locates editable lettering.
    story.artifacts.write_analysis(_analysis(story.page, render))
    story.artifacts.write_lettering(_lettering(
        story.page, _element("letter-1"), _element("letter-2", hidden=True),
    ))

    view = page_source_view(story.artifacts, 1)

    element = view["lettering"][0]["element"]
    assert element["source_lettering_item_id"] == "letter-1"
    assert (element["placement"], element["scale"], element["rotation"]) == (
        {"x": 0.1, "y": 0.6, "width": 0.5, "height": 0.2}, 1.5, -8,
    )
    assert view["lettering"][0]["region"] is None
    assert view["lettering"][1]["element"] is None
    assert view["geometry"] == {"source": "lettering_placement", "lettering_revision": 3}


def test_editable_lettering_saved_for_another_plan_is_not_used(story, monkeypatch):
    monkeypatch.setattr(page_source, "is_hybrid", lambda target: True)
    story.artifacts.write_lettering(_lettering(story.page, _element("letter-1"), comic_page_sha256="c" * 64))

    view = page_source_view(story.artifacts, 1)

    assert _located(view) == {"letter-1": None, "letter-2": None}
    assert view["geometry"] is None


@pytest.fixture
def client(story):
    app = FastAPI()
    app.include_router(pages.router, prefix="/projects/{project_id}")
    app.dependency_overrides[pages.get_project] = lambda: (story.dir, Config(), None)
    with TestClient(app) as test_client:
        yield test_client


def test_route_returns_source_view(client):
    response = client.get("/projects/p/pages/1/source")

    assert response.status_code == 200
    assert response.json()["passages"][0]["scene_title"] == "The harbour"


def test_route_rejects_page_planned_from_older_adaptation(client, story):
    story.artifacts.write_page(story.page.model_copy(update={
        "revision": 2, "adaptation_sha256": "c" * 64, "content_sha256": "",
    }))

    response = client.get("/projects/p/pages/1/source")

    assert response.status_code == 409
    assert "Re-run Plan" in response.json()["detail"]


def test_route_rejects_adaptation_of_other_manuscript(client, story):
    story.artifacts.write_adaptation(story.adaptation.model_copy(update={
        "source_sha256": "d" * 64, "content_sha256": "",
    }))

    response = client.get("/projects/p/pages/1/source")

    assert response.status_code == 409
    assert "Re-run Adapt" in response.json()["detail"]


def test_route_404s_unplanned_page(client):
    assert client.get("/projects/p/pages/9/source").status_code == 404
