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
from novel_to_comic.models.page import ComicPage, PageContent
from novel_to_comic.models.source import SourceDocument, SourceScene, SourceUnit
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


def _square(x: float, y: float, size: float = 0.3):
    return ((x, y), (x + size, y), (x + size, y + size), (x, y + size))


def _analysis(
    page: ComicPage,
    render: PageRenderRevision,
    *,
    order: tuple[str, ...] = ("panel_000", "panel_001", "panel_002"),
    proven: bool = True,
    letter_regions: tuple[str, str] = ("panel_000", "panel_001"),
    image_sha256: str | None = None,
) -> RenderAnalysis:
    return RenderAnalysis(
        page_number=1, render_revision=render.revision,
        render_image_sha256=image_sha256 or render.image_sha256,
        comic_page_sha256=page.content_sha256,
        ocr_observations=(
            OCRTextObservation(id="ocr_001", text="The idol was older than the sea itself!",
                               detected_region_id=letter_regions[0]),
            OCRTextObservation(id="ocr_002", text="No one listened.", detected_region_id=letter_regions[1]),
        ),
        lettering_matches=(
            LetteringMatch(lettering_item_id="letter-1", observation_id="ocr_001",
                           canonical_text="x", observed_text="x"),
            LetteringMatch(lettering_item_id="letter-2", observation_id="ocr_002",
                           canonical_text="x", observed_text="x"),
        ),
        observed_regions=(
            ObservedRegion(id="panel_000", polygon=_square(0.0, 0.0)),
            ObservedRegion(id="panel_001", polygon=_square(0.5, 0.0)),
            ObservedRegion(id="panel_002", polygon=_square(0.0, 0.5)),
        ),
        observed_reading_order=order if proven else (),
        reading_order_proven=proven,
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


def _marks(view: dict) -> list[tuple[str, str, list[str]]]:
    return [
        (unit["id"], segment["text"], segment["content_ids"], segment["kind"])
        for passage in view["passages"]
        for unit in passage["units"]
        for segment in unit["segments"]
        if segment["kind"]
    ]


def test_passages_follow_beats_and_skip_unadapted_units(story):
    view = page_source_view(story.artifacts, 1)

    assert [(p["scene_title"], [u["id"] for u in p["units"]]) for p in view["passages"]] == [
        ("The harbour", ["source-1", "source-2", "source-3"]),
        ("Oslo", ["source-5"]),
    ]
    # Segments always reassemble the exact manuscript text.
    for passage in view["passages"]:
        for unit in passage["units"]:
            ordinal = unit["ordinal"]
            assert "".join(s["text"] for s in unit["segments"]) == UNITS[ordinal - 1]


def test_lettering_marks_verbatim_words_per_panel_and_depiction_per_beat(story):
    marks = _marks(page_source_view(story.artifacts, 1))

    assert marks == [
        # Depicted units point at every panel on this page carrying their beat.
        ("source-1", "The harbour lay under a green fog.", ["panel-1", "panel-2"], "depicted"),
        # Verbatim dialogue highlights only the quoted words, tied to its panel.
        ("source-2", "the idol was older than the sea itself", ["panel-1"], "lettering"),
        # A paraphrased caption cites the whole unit.
        ("source-3", "Nobody believed him that night.", ["panel-2"], "lettering"),
        ("source-5", "The rain drummed on the chamber door.", ["panel-3"], "depicted"),
    ]


def test_no_render_means_no_outlines(story):
    view = page_source_view(story.artifacts, 1)

    assert [panel["id"] for panel in view["panels"]] == ["panel-1", "panel-2", "panel-3"]
    assert all(panel["box"] is None for panel in view["panels"])
    assert view["geometry_render_revision"] is None


def test_proven_reading_order_outlines_every_planned_panel(story):
    render = _render(story.artifacts, story.page)
    story.artifacts.write_analysis(_analysis(story.page, render))

    view = page_source_view(story.artifacts, 1)

    boxes = {panel["id"]: panel["box"] for panel in view["panels"]}
    assert boxes["panel-1"] == pytest.approx({"x": 0.0, "y": 0.0, "width": 0.3, "height": 0.3})
    assert boxes["panel-2"] == pytest.approx({"x": 0.5, "y": 0.0, "width": 0.3, "height": 0.3})
    assert boxes["panel-3"] == pytest.approx({"x": 0.0, "y": 0.5, "width": 0.3, "height": 0.3})
    assert view["geometry_render_revision"] == 1


def test_order_contradicting_matched_lettering_keeps_only_grounded_panels(story):
    render = _render(story.artifacts, story.page)
    story.artifacts.write_analysis(_analysis(
        story.page, render, order=("panel_001", "panel_000", "panel_002"),
    ))

    boxes = {panel["id"]: panel["box"] for panel in page_source_view(story.artifacts, 1)["panels"]}

    assert boxes["panel-1"]["x"] == pytest.approx(0.0)
    assert boxes["panel-2"]["x"] == pytest.approx(0.5)
    assert boxes["panel-3"] is None


def test_unproven_order_outlines_only_lettering_grounded_panels(story):
    render = _render(story.artifacts, story.page)
    story.artifacts.write_analysis(_analysis(story.page, render, proven=False))

    boxes = {panel["id"]: panel["box"] for panel in page_source_view(story.artifacts, 1)["panels"]}

    assert boxes["panel-1"] is not None and boxes["panel-2"] is not None
    assert boxes["panel-3"] is None


def test_analysis_of_other_art_is_not_used(story):
    render = _render(story.artifacts, story.page)
    story.artifacts.write_analysis(_analysis(story.page, render, image_sha256="f" * 64))

    view = page_source_view(story.artifacts, 1)

    assert all(panel["box"] is None for panel in view["panels"])


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
