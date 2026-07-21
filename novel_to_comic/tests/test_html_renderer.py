import asyncio
from pathlib import Path

from novel_to_comic.assembly.html_renderer import build_page_html, inspect_html_lettering_metrics
from novel_to_comic.models.comic_page import Bubble, ComicPage, PagePanel


def test_auto_narration_renders_as_caption_box_with_preferred_zone(tmp_path: Path):
    page = ComicPage(
        page_number=1,
        panels=[
            PagePanel(
                id="scene_001-001",
                image_path="draw/missing.png",
                scene_id="scene_001",
                panel_number=1,
                bubbles=[
                    Bubble(
                        id="scene_001-p1-b0",
                        type="narration",
                        text="The night held its breath.",
                        preferred_zone="bottom",
                    ),
                ],
            )
        ],
    )

    html = build_page_html(page, tmp_path)

    assert '<div class="captions zone-bottom">' in html
    assert 'class="caption narration"' in html
    assert "The night held its breath." in html
    assert 'class="bubble narration' not in html


def test_pinned_narration_keeps_caption_style(tmp_path: Path):
    page = ComicPage(
        page_number=1,
        panels=[
            PagePanel(
                id="scene_001-001",
                image_path="draw/missing.png",
                scene_id="scene_001",
                panel_number=1,
                bubbles=[
                    Bubble(
                        id="scene_001-p1-b0",
                        type="narration",
                        text="Later...",
                        x=120,
                        y=80,
                        tail_x=200,
                        tail_y=400,
                    ),
                ],
            )
        ],
    )

    html = build_page_html(page, tmp_path)

    assert 'class="caption narration pinned"' in html
    assert '<svg class="speaker-tail"' not in html


def test_pinned_bubble_coordinates_are_clamped_inside_panel(tmp_path: Path):
    page = ComicPage(
        page_number=1,
        panels=[
            PagePanel(
                id="scene_001-001",
                image_path="draw/missing.png",
                scene_id="scene_001",
                panel_number=1,
                bubbles=[
                    Bubble(
                        id="thought",
                        type="thought",
                        text="Too close.",
                        x=-120,
                        y=-40,
                    )
                ],
            )
        ],
    )

    html = build_page_html(page, tmp_path)

    assert 'style="left: 8px; top:  8px"' in html


def test_rendered_pinned_bubble_is_refit_at_far_panel_edge(tmp_path: Path):
    page = ComicPage(
        page_number=1,
        layout="1",
        panels=[
            PagePanel(
                id="scene_001-001",
                image_path="draw/missing.png",
                scene_id="scene_001",
                panel_number=1,
                bubbles=[
                    Bubble(
                        id="speech",
                        type="speech",
                        text="Keep me visible.",
                        x=2400,
                        y=3300,
                        width=520,
                    )
                ],
            )
        ],
    )

    html = build_page_html(page, tmp_path)
    metrics = asyncio.run(inspect_html_lettering_metrics(html))

    assert metrics[0]["overflowing_bubble_ids"] == []


def test_balloon_geometry_is_compact_and_panel_responsive(tmp_path: Path):
    page = ComicPage(
        page_number=1,
        panels=[
            PagePanel(
                id="scene_001-001",
                image_path="draw/missing.png",
                scene_id="scene_001",
                panel_number=1,
                bubbles=[Bubble(id="thought", type="thought", text="A long thought.")],
            )
        ],
    )

    html = build_page_html(page, tmp_path)

    assert "--bubble-font-size: 44px" in html
    assert "--bubble-padding: 18px 26px" in html
    assert "padding: 22px 30px 32px" in html
    assert ".bubble.thought { max-width: 84%; }" in html
    assert "width: 88%" in html


def test_semantic_balloon_shapes_and_upper_flow_render(tmp_path: Path):
    page = ComicPage(
        page_number=1,
        panels=[
            PagePanel(
                id="scene_001-001",
                image_path="draw/missing.png",
                scene_id="scene_001",
                panel_number=1,
                bubbles=[
                    Bubble(id="speech", type="speech", text="Who is there?"),
                    Bubble(id="thought", type="thought", text="Not again."),
                    Bubble(id="caption", type="narration", text="Midnight."),
                ],
            )
        ],
    )

    html = build_page_html(page, tmp_path)

    assert 'class="panel has-top-captions"' in html
    assert 'class="bubble speech left"' in html
    assert html.count('class="speaker-tail"') == 2
    assert 'data-tail-kind="thought"' in html
    assert _speech_path() in html
    assert _thought_path() in html
    assert _narration_path() in html


def test_pinned_speech_tail_uses_measured_panel_target(tmp_path: Path):
    page = ComicPage(
        page_number=1,
        panels=[
            PagePanel(
                id="scene_001-001",
                image_path="draw/missing.png",
                scene_id="scene_001",
                panel_number=1,
                bubbles=[
                    Bubble(
                        id="speech",
                        type="speech",
                        text="Here.",
                        x=120,
                        y=80,
                        width=360,
                        tail_x=640,
                        tail_y=520,
                    ),
                ],
            )
        ],
    )

    html = build_page_html(page, tmp_path)

    assert 'data-tail-x="640.00" data-tail-y="520.00"' in html
    assert 'class="tail-fill"' in html
    assert 'class="tail-outline"' in html
    assert "speechGeometryFor(bubble.offsetWidth, bubble.offsetHeight, targetX, targetY)" in html


def test_multiline_text_is_verified_inside_actual_svg_fill(tmp_path: Path):
    page = ComicPage(
        page_number=1,
        layout="1",
        panels=[
            PagePanel(
                id="scene_001-001",
                image_path="draw/missing.png",
                scene_id="scene_001",
                panel_number=1,
                bubbles=[
                    Bubble(
                        id="narration",
                        type="narration",
                        text="Midnight. He had been pondering over volumes of forgotten lore.",
                        x=100,
                        y=100,
                        width=1100,
                    ),
                    Bubble(
                        id="speech",
                        type="speech",
                        text=(
                            "'Tis some visitor tapping at my chamber door — "
                            "only this and nothing more."
                        ),
                        x=180,
                        y=650,
                        width=620,
                    ),
                    Bubble(
                        id="thought",
                        type="thought",
                        text="I should not have come.",
                        x=1500,
                        y=900,
                        width=560,
                    ),
                ],
            )
        ],
    )

    html = build_page_html(page, tmp_path)
    metrics = asyncio.run(inspect_html_lettering_metrics(html))

    assert "isPointInFill" in html
    assert "content.style.width" not in html
    assert "host.style.padding" not in html
    assert "__fitLetteringSafeAreas" not in html
    assert metrics[0]["unsafe_bubble_ids"] == []


def _speech_path() -> str:
    return "M4 1 C30 0 70 0 94 2"


def _thought_path() -> str:
    return "M18 2 C8 2 2 10 2 22"


def _narration_path() -> str:
    return "M2 4 L96 2 L99 88 L92 98 L3 96 Z"


def test_panel_image_scale_is_emitted_for_web_rendering(tmp_path: Path):
    page = ComicPage(
        page_number=1,
        panels=[
            PagePanel(
                id="scene_001-001",
                image_path="draw/panel.png",
                scene_id="scene_001",
                panel_number=1,
                image_scale=1.5,
            )
        ],
    )

    html = build_page_html(page, tmp_path, image_url_fn=lambda path: f"https://example.test/{path}")

    assert "--panel-art-scale: 1.50" in html
