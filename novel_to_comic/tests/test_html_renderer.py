from pathlib import Path

from novel_to_comic.assembly.html_renderer import build_page_html
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
    assert '<svg class="tail-svg"' not in html


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
