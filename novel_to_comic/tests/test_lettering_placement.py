"""Panel-aware first placement: gutters, panel assignment, fit and tails. Provider-free."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from PIL import Image, ImageDraw

from novel_to_comic.lettering import placement, service
from novel_to_comic.lettering.panels import detect_panels
from novel_to_comic.models.page import NormalizedPoint, PinnedGeometry

from .test_hybrid_lettering import book  # noqa: F401  (fixture)

TOP = PinnedGeometry(x=0.01, y=0.01, width=0.98, height=0.48)
BOTTOM_LEFT = PinnedGeometry(x=0.01, y=0.51, width=0.48, height=0.48)
BOTTOM_RIGHT = PinnedGeometry(x=0.51, y=0.51, width=0.48, height=0.48)
PANELS = (TOP, BOTTOM_LEFT, BOTTOM_RIGHT)


def _inside(rect, panel, tolerance=1e-9) -> bool:
    return (
        rect.x >= panel.x - tolerance and rect.y >= panel.y - tolerance
        and rect.x + rect.width <= panel.x + panel.width + tolerance
        and rect.y + rect.height <= panel.y + panel.height + tolerance
    )


def _point_in(point, rect) -> bool:
    return rect.x <= point.x <= rect.x + rect.width and rect.y <= point.y <= rect.y + rect.height


def _gutter_page(size=(600, 900)) -> Image.Image:
    """White paper, three bordered panels: one wide tier over two side by side."""
    image = Image.new("RGB", size, "white")
    draw = ImageDraw.Draw(image)
    w, h = size
    for panel in PANELS:
        box = [panel.x * w, panel.y * h, (panel.x + panel.width) * w, (panel.y + panel.height) * h]
        draw.rectangle(box, fill=(150, 160, 170), outline="black", width=3)
    return image


def test_gutters_yield_panels_in_reading_order():
    panels = detect_panels(_gutter_page())
    assert len(panels) == 3
    for found, expected in zip(panels, PANELS):
        assert found.model_dump() == pytest.approx(expected.model_dump(), abs=0.01)


def test_art_without_gutters_is_one_panel_and_not_used_for_a_multi_panel_plan():
    panels = detect_panels(Image.new("RGB", (400, 600), (40, 50, 60)))
    assert [p.model_dump() for p in panels] == [{"x": 0, "y": 0, "width": 1, "height": 1}]
    assert not placement.usable(_page([[_line("a")], [_line("b")]]), panels)
    assert placement.usable(_page([[_line("a")]]), panels)


def _line(id, *, kind="dialogue", speaker="char_a", delivery="onscreen", text="A line of copy."):
    return SimpleNamespace(
        id=id, kind=kind, text=text, delivery=delivery, source_unit_ids=(),
        speaker_entity_id=speaker if delivery == "onscreen" else None,
    )


def _page(parts, *, bounds=None, tails=None, entities=("char_a", "char_b")):
    content = [
        SimpleNamespace(order=order, lettering=items, entity_ids=entities)
        for order, items in enumerate(parts, 1)
    ]
    items = [item for items in parts for item in items]
    bounds, tails = bounds or {}, tails or {}
    reservations = [
        SimpleNamespace(
            lettering_item_id=item.id, bounds=bounds.get(item.id), tail_target=tails.get(item.id),
            preferred_zone="bottom-right", footprint="standard", line_budget=2,
            speaker_entity_id=item.speaker_entity_id,
        )
        for item in items
    ]
    return SimpleNamespace(
        content=content, lettering_reservations=reservations, page_number=1, content_sha256="a" * 64
    )


def test_bounds_pick_the_drawn_panel_but_never_break_reading_order():
    # Plan put b's reservation in the top panel, after a in the bottom-left one.
    page = _page(
        [[_line("a")], [_line("b"), _line("c")]],
        bounds={
            "a": PinnedGeometry(x=0.05, y=0.55, width=0.3, height=0.1),
            "b": PinnedGeometry(x=0.05, y=0.05, width=0.3, height=0.1),
            "c": PinnedGeometry(x=0.6, y=0.6, width=0.3, height=0.1),
        },
    )
    assert placement.assign_panels(page, PANELS) == {"a": 1, "b": 1, "c": 2}


def test_items_without_bounds_follow_plan_order_scaled_to_the_drawn_panels():
    page = _page([[_line("a")], [_line("b")]])
    assert placement.assign_panels(page, PANELS) == {"a": 0, "b": 2}


def test_speaker_side_comes_from_plan_entity_order_and_persists_on_the_page():
    page = _page([
        [_line("a", speaker="char_a"), _line("b", speaker="char_b")],
        [_line("c", speaker="char_b"), _line("n", kind="caption", delivery="narration")],
    ])
    page.content[1].entity_ids = ("char_b",)
    assert placement.speaker_sides(page) == {"a": "left", "b": "right", "c": "right", "n": None}


def test_seed_keeps_every_balloon_and_tail_inside_its_drawn_panel_in_reading_order():
    straddling = PinnedGeometry(x=0.3, y=0.42, width=0.6, height=0.2)  # Across the gutter.
    outside = NormalizedPoint(x=0.8, y=0.8)  # Plan's blind pointer into another panel.
    inside = NormalizedPoint(x=0.3, y=0.9)
    page = _page(
        [[_line("a", speaker="char_a"), _line("b", speaker="char_b"),
          _line("n", kind="caption", delivery="narration")],
         [_line("c")]],
        bounds={"a": straddling, "b": straddling, "c": PinnedGeometry(x=0.05, y=0.55, width=0.3, height=0.1)},
        tails={"a": outside, "c": inside},
    )
    state = service.seed_lettering(
        page, SimpleNamespace(width=600, height=900), service.preset_style(), panels=PANELS
    )
    assigned = placement.assign_panels(page, PANELS)
    by_id = {element.id: element for element in state.elements}
    for element in state.elements:
        panel = PANELS[assigned[element.id]]
        assert _inside(element.placement, panel)
        assert element.suggested_placement == element.placement
        assert element.suggested_tail_target == element.tail_target
        if element.tail_target is not None:
            assert _point_in(element.tail_target, panel)
            assert not _point_in(element.tail_target, element.placement)
    assert by_id["a"].tail_target != outside
    assert by_id["c"].tail_target == inside  # Plan's pointer fits its panel: kept.
    assert by_id["n"].tail_target is None
    a, b = by_id["a"].placement, by_id["b"].placement
    assert b.y >= a.y and (b.x >= a.x + a.width or b.y >= a.y + a.height / 2)
    assert not (a.x < b.x + b.width and b.x < a.x + a.width and a.y < b.y + b.height and b.y < a.y + a.height)


def test_tails_in_one_panel_never_cross():
    # Balloons land left-to-right opposite their speakers' sides.
    page = _page(
        [[_line("a", speaker="char_b"), _line("b", speaker="char_a")]],
        bounds={
            "a": PinnedGeometry(x=0.05, y=0.05, width=0.3, height=0.08),
            "b": PinnedGeometry(x=0.6, y=0.05, width=0.3, height=0.08),
        },
    )
    page.content[0].entity_ids = ("char_a", "char_b")
    layout = placement.layout_page(
        page, (TOP, BOTTOM_LEFT), lambda item, r, panel: (0.3, 0.08)
    )
    stems = [placement._stem(body, tail) for body, tail in layout.values()]
    assert not placement._crosses(*stems)


def test_without_panels_the_plan_reservation_seed_is_unchanged():
    box = PinnedGeometry(x=0.3, y=0.42, width=0.6, height=0.2)
    page = _page([[_line("a")], [_line("b")]], bounds={"a": box, "b": box})
    render, style = SimpleNamespace(width=600, height=900), service.preset_style()
    legacy = service.seed_lettering(page, render, style)
    assert legacy.elements[0].placement == box
    one_panel = (PinnedGeometry(x=0, y=0, width=1, height=1),)
    assert service.seed_lettering(page, render, style, panels=one_panel) == legacy


def test_settled_seed_moves_balloons_into_place_without_rewrapping_or_tight_frames():
    page = _page(
        [[_line("a", speaker="char_a", text="Where am I? Nobody answers here."),
          _line("b", speaker="char_b", text="Somewhere between lives.")],
         [_line("c", kind="caption", delivery="narration", text="And that is when you met me.")]],
    )
    style = service.preset_style()
    seed = service.seed_lettering(page, SimpleNamespace(width=600, height=900), style, panels=PANELS)
    first = service.resolve_lettering(seed, style)
    settled = service.settle_seeds(seed, page, style, PANELS)
    assigned = placement.assign_panels(page, PANELS)
    for before, after in zip(first.elements, settled.elements):
        assert after.resolved.lines == before.resolved.lines
        # Plan's roomier frame is kept (a longer translation can still grow).
        assert after.placement.width >= after.resolved.width
        assert after.placement.width == pytest.approx(
            min(before.placement.width, 1 - after.placement.x)
        )
        body = PinnedGeometry(
            x=after.placement.x, y=after.placement.y,
            width=after.resolved.width, height=after.resolved.height,
        )
        assert _inside(body, PANELS[assigned[after.id]], tolerance=1e-6)
        assert after.suggested_placement == after.placement
    assert settled.reviewed_against_render_revision is None
    assert settled.reviewed_against_image_sha256 is None


def test_fresh_and_reset_seeds_from_the_art_stay_unreviewed(book):  # noqa: F811
    artifacts, image = book
    render = service.active_render(artifacts, 1)
    detected = service.page_panels(artifacts, 1, render)
    assert detected  # Real art bytes are read; no provider is involved.
    state = service.ensure_lettering(artifacts, 1)
    assert state.reviewed_against_render_revision is None
    assert service.editor_state(artifacts, 1)["placement_review_needed"]
    reset = service.reset_lettering(
        artifacts, 1, expected_revision=state.revision, expected_image_sha256=render.image_sha256
    )
    assert reset.reviewed_against_render_revision is None
    assert reset.revision == state.revision + 1
    assert [e.placement for e in reset.elements] == [e.placement for e in state.elements]
    assert artifacts.read_render(1, 1) == image


def test_tail_and_clearing_rules_keep_parity_with_the_engine():
    # The same literals are asserted in web letteringPlacementChecks.test.ts.
    head = (0.2, 0.2, 0.1, 0.12)
    tail = placement.toward_head(PinnedGeometry(x=0.05, y=0.03, width=0.2, height=0.08), head)
    assert (tail.x, tail.y) == pytest.approx((0.2, 0.2))
    tail = placement.toward_head(PinnedGeometry(x=0.15, y=0.15, width=0.3, height=0.3), head)
    assert (tail.x, tail.y) == pytest.approx((0.25, 0.26))
    assert placement.clear_of(0.18, 0.2, 0.2, 0.1, [head], (0.03, 0.024, 0.97, 0.476)) == pytest.approx((0.18, 0.088))


def _head(entity, x, y, w=0.1, h=0.12):
    return SimpleNamespace(entity_id=entity, x=x, y=y, width=w, height=h)


def test_page_read_heads_put_speech_over_its_speaker_off_faces_with_tails_on_them():
    page = _page(
        [[_line("a", speaker="char_a"), _line("b", speaker="char_b"),
          _line("n", kind="caption", delivery="narration")]],
        bounds={"a": PinnedGeometry(x=0.6, y=0.3, width=0.3, height=0.1),  # Plan guessed wrong sides.
                "b": PinnedGeometry(x=0.05, y=0.3, width=0.3, height=0.1),
                "n": PinnedGeometry(x=0.2, y=0.2, width=0.3, height=0.08)},  # On a face.
    )
    heads = [_head("char_a", 0.2, 0.2), _head("char_b", 0.7, 0.25)]
    layout = placement.layout_page(page, (TOP, BOTTOM_LEFT), lambda i, r, p: (0.24, 0.07), heads)
    faces = [(h.x, h.y, h.width, h.height) for h in heads]
    for rect, _tail in layout.values():
        assert not any(placement._overlaps((rect.x, rect.y, rect.width, rect.height), f) for f in faces)
        assert _inside(rect, TOP)
    a, a_tail = layout["a"]
    b, b_tail = layout["b"]
    assert a.x + a.width / 2 < 0.5 < b.x + b.width / 2  # Each over its own speaker.
    assert _point_in(a_tail, PinnedGeometry(x=0.2, y=0.2, width=0.1, height=0.12))
    assert _point_in(b_tail, PinnedGeometry(x=0.7, y=0.25, width=0.1, height=0.12))
    assert layout["n"][1] is None


def test_a_lone_unlabelled_head_is_used_only_for_a_panel_with_one_speaker():
    solo = _page([[_line("a", speaker="char_a")]])
    stranger = [_head(None, 0.6, 0.25)]
    _, tail = placement.layout_page(solo, (TOP, BOTTOM_LEFT), lambda i, r, p: (0.2, 0.06), stranger)["a"]
    assert _point_in(tail, PinnedGeometry(x=0.6, y=0.25, width=0.1, height=0.12))
    duet = _page([[_line("a", speaker="char_a"), _line("b", speaker="char_b")]])
    layout = placement.layout_page(duet, (TOP, BOTTOM_LEFT), lambda i, r, p: (0.2, 0.06), stranger)
    assert not any(
        _point_in(tail, PinnedGeometry(x=0.6, y=0.25, width=0.1, height=0.12))
        for _, tail in layout.values()
    )


def test_page_read_labels_heads_only_with_portraits_it_was_sent(monkeypatch):
    import asyncio

    from novel_to_comic.config import Config
    from novel_to_comic.page_ocr import CastPortrait, GatewayPageOCRAdapter

    sent = {}

    async def fake_generate_json(**kwargs):
        sent.update(kwargs)
        return SimpleNamespace(usage=None, value={
            "lettering": [], "panels": [],
            "figures": [
                {"subject": "char_001", "head": {"x": 0.1, "y": 0.1, "width": 0.1, "height": 0.1}},
                {"subject": "God", "box_2d": [500, 600, 600, 700]},
                {"subject": "unknown", "head": {"x": 0.95, "y": 0.2, "width": 0.1, "height": 0.1}},
            ],
        })

    monkeypatch.setattr("novel_to_comic.clients.text.generate_json", fake_generate_json)
    portraits = (CastPortrait("char_001", b"p1"), CastPortrait("char_002", b"p2"))
    read = asyncio.run(GatewayPageOCRAdapter(Config(), page_number=3, portraits=portraits).extract(b"page"))
    assert sent["image_attachments"] == ((b"page", "image/png"), (b"p1", "image/png"), (b"p2", "image/png"))
    assert "char_001, char_002" in sent["user_content"]
    figures = read.value.figures
    assert [f.entity_id for f in figures] == ["char_001", None, None]  # Names are not labels.
    assert (figures[1].x, figures[1].y) == pytest.approx((0.6, 0.5))
    assert figures[2].x + figures[2].width <= 1


def test_cast_portraits_follow_the_page_speakers_and_their_drawn_state(tmp_path):
    from novel_to_comic.lettering.page_read import cast_portraits

    for path in ("refs/char_a/portrait.png", "refs/char_b/portrait.png",
                 "refs/char_b/states/char_b_old/portrait.png"):
        (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (900, 900), "red" if "old" in path else "blue").save(tmp_path / path)
    page = _page([[_line("b", speaker="char_b"), _line("a", speaker="char_a"),
                   _line("n", kind="caption", delivery="narration")]])
    page.content[0].appearance_states = {"char_b": "char_b_old"}
    portraits = cast_portraits(SimpleNamespace(project_dir=tmp_path), page)
    assert [p.entity_id for p in portraits] == ["char_b", "char_a"]
    with Image.open(__import__("io").BytesIO(portraits[0].image)) as image:
        assert max(image.size) <= 256 and image.getpixel((5, 5))[0] > 200  # The drawn state.


def test_a_read_that_predates_heads_reports_them_unknown_not_absent(book):  # noqa: F811
    from novel_to_comic.models.draw import ObservedFigure, OCRExtraction, RawOCRObservation

    artifacts, _image = book
    render = service.active_render(artifacts, 1)
    page = artifacts.read_page(1)
    assert service.placement_evidence(artifacts, page, render)["page_read"] is None
    head = ObservedFigure(id="figure_001", entity_id=None, x=0.2, y=0.2, width=0.1, height=0.1)

    def stored(figures_read):
        artifacts.raw_ocr_path(1, render.revision).unlink(missing_ok=True)  # Immutable; a fresh case.
        artifacts.write_raw_ocr(RawOCRObservation(
            page_number=1, render_revision=render.revision, render_image_sha256=render.image_sha256,
            extraction=OCRExtraction(figures=(head,)), figures_read=figures_read,
        ))
        return service.placement_evidence(artifacts, page, render)["page_read"]

    assert stored(False)["heads"] is None
    assert service.suggested_placements(artifacts, 1)["uses_faces"] is False
    assert stored(True)["heads"] == [{"id": "figure_001", "entity_id": None, "x": 0.2, "y": 0.2, "width": 0.1, "height": 0.1}]
    suggestion = service.suggested_placements(artifacts, 1)
    assert suggestion["uses_faces"] is True
    assert not artifacts.lettering_path(1).exists()  # Suggestions are proposals; nothing is saved.


def test_a_new_read_re_places_only_untouched_lettering(book, monkeypatch):  # noqa: F811
    artifacts, _image = book
    seeded = service.ensure_lettering(artifacts, 1)
    real_seed = service.seed_page

    def seed_with_faces(*args, **kwargs):
        fresh = real_seed(*args, **kwargs)
        moved = [
            e.model_copy(update={"placement": p, "suggested_placement": p})
            for e in fresh.elements
            for p in [e.placement.model_copy(update={"y": min(e.placement.y + 0.05, 1 - e.placement.height)})]
        ]
        return service._replace(fresh, elements=[e.model_dump() for e in moved])

    monkeypatch.setattr(service, "seed_page", seed_with_faces)
    assert service.reseed_after_read(artifacts, 1)
    reseeded = artifacts.read_lettering(1)
    assert reseeded.revision == seeded.revision + 1
    assert reseeded.reviewed_against_render_revision is None  # Still a seed to confirm.
    assert [e.placement for e in reseeded.elements] != [e.placement for e in seeded.elements]

    # Once the author moves anything, a later read never touches the page.
    first = reseeded.elements[0]
    nudged = first.placement.model_copy(update={"x": first.placement.x / 2})
    edited = service._replace(reseeded, revision=reseeded.revision + 1, elements=[
        e.model_dump() for e in (first.model_copy(update={"placement": nudged}), *reseeded.elements[1:])
    ])
    artifacts.write_lettering(edited)
    assert not service.reseed_after_read(artifacts, 1)
    assert artifacts.read_lettering(1).elements[0].placement == nudged


def test_a_failed_re_placement_never_fails_the_page_read(book, monkeypatch):  # noqa: F811
    import asyncio

    from novel_to_comic.models.draw import OCRExtraction
    from novel_to_comic.page_review import analyze_page_render
    from novel_to_comic.usage import ApiResult

    artifacts, image = book
    artifacts.analysis_path(1, 1).unlink()

    class _Read:
        async def extract(self, image):
            return ApiResult(value=OCRExtraction(), usage=None)

    def broken(*_args, **_kwargs):
        raise RuntimeError("renderer unavailable")

    monkeypatch.setattr(service, "reseed_after_read", broken)
    result = asyncio.run(analyze_page_render(
        page=artifacts.read_page(1), render=service.active_render(artifacts, 1),
        image=image, ocr=_Read(), artifacts=artifacts,
    ))
    assert result.analysis.render_revision == 1
    assert artifacts.read_raw_ocr(1, 1).figures_read
