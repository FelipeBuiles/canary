from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from novel_to_comic.config import Config
from novel_to_comic.usage import UsageRecord
from novel_to_comic.page_ocr import (
    GatewayPageOCRAdapter,
    _PageOCRDraft,
    build_extraction,
)


def _draft(*boxes: tuple[str, float, float]) -> _PageOCRDraft:
    return _PageOCRDraft.model_validate(
        {
            "lettering": [
                {
                    "text": text,
                    "box": {"x": x, "y": y, "width": 0.3, "height": 0.1},
                }
                for text, x, y in boxes
            ]
        }
    )


def test_reading_order_comes_from_geometry_not_the_models_list_order() -> None:
    # The engine listed the bottom balloon first; the boxes say otherwise, and
    # geometry is the evidence Draw uses to judge reading order.
    extraction = build_extraction(
        _draft(
            ("bottom left", 0.05, 0.80),
            ("top right", 0.60, 0.10),
            ("top left", 0.05, 0.12),
        )
    )

    assert [item.text for item in extraction.lettering] == [
        "bottom left",
        "top right",
        "top left",
    ]
    assert extraction.observed_reading_order == (
        "region_003",
        "region_002",
        "region_001",
    )


def test_balloons_in_one_row_are_ordered_left_to_right() -> None:
    extraction = build_extraction(_draft(("right", 0.60, 0.11), ("left", 0.05, 0.14)))

    # Slightly different heights within a tier must not zig-zag the order.
    assert extraction.observed_reading_order == ("region_002", "region_001")


def test_every_observation_carries_its_own_detected_region() -> None:
    extraction = build_extraction(_draft(("one", 0.1, 0.1), ("two", 0.1, 0.5)))

    assert [item.detected_region_id for item in extraction.lettering] == [
        "region_001",
        "region_002",
    ]
    assert len(extraction.observed_regions) == 2


def test_adapter_accepts_gemini_bare_list_and_box_2d(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_generate_json(**kwargs):
        class _Result:
            usage = None
            value = [
                {
                    "box_2d": [56, 38, 106, 438],
                    "text": "We should voyage far.",
                }
            ]

        return _Result()

    monkeypatch.setattr("novel_to_comic.clients.text.generate_json", fake_generate_json)

    read = asyncio.run(GatewayPageOCRAdapter(Config(), page_number=1).extract(b"png"))

    assert [item.text for item in read.value.lettering] == ["We should voyage far."]
    expected_polygon = (
        (0.038, 0.056),
        (0.438, 0.056),
        (0.438, 0.106),
        (0.038, 0.106),
    )
    for actual, expected in zip(
        read.value.observed_regions[0].polygon, expected_polygon, strict=True
    ):
        assert actual == pytest.approx(expected)


def test_adapter_accepts_gemini_nested_normalized_box_2d(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_generate_json(**kwargs):
        class _Result:
            usage = None
            value = {
                "lettering": [
                    {
                        "box_2d": [[0.057, 0.076, 0.134, 0.439]],
                        "text_content": "Void of clothing...",
                    }
                ]
            }

        return _Result()

    monkeypatch.setattr("novel_to_comic.clients.text.generate_json", fake_generate_json)

    read = asyncio.run(GatewayPageOCRAdapter(Config(), page_number=16).extract(b"png"))

    expected_polygon = (
        (0.076, 0.057),
        (0.439, 0.057),
        (0.439, 0.134),
        (0.076, 0.134),
    )
    for actual, expected in zip(
        read.value.observed_regions[0].polygon, expected_polygon, strict=True
    ):
        assert actual == pytest.approx(expected)


def test_adapter_sends_the_page_image_and_no_canonical_wording(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # An OCR pass primed with the expected text cannot falsify a render.
    captured: dict = {}

    async def fake_generate_json(**kwargs):
        captured.update(kwargs)

        class _Result:
            usage = UsageRecord(
                provider="gemini",
                model="ocr-balanced",
                operation="text",
                input_tokens=1200,
                output_tokens=80,
            )
            value = {
                "lettering": [
                    {
                        "text": "It was the same face.",
                        "box": {"x": 0.1, "y": 0.1, "width": 0.5, "height": 0.1},
                    }
                ]
            }

        return _Result()

    monkeypatch.setattr("novel_to_comic.clients.text.generate_json", fake_generate_json)
    adapter = GatewayPageOCRAdapter(Config(), page_number=34)

    read = asyncio.run(adapter.extract(b"page-bytes"))

    assert [item.text for item in read.value.lettering] == ["It was the same face."]
    # The analysis pass is billable, so its usage has to come back with it.
    assert read.usage is not None
    assert read.usage.model == "ocr-balanced"
    assert captured["image_attachments"] == ((b"page-bytes", "image/png"),)
    assert captured["feature"] == "draw.page_ocr"
    assert captured["temperature"] == 0.0
    assert "canary_page_number: 34" in captured["user_content"]
    assert "It was the same face" not in captured["user_content"]


def test_mock_replay_answers_page_ocr_from_the_canonical_page(
    tmp_path: Path,
) -> None:
    from novel_to_comic.mock_models import TargetFixtureReplay

    project = tmp_path / "fixture"
    (project / "brief").mkdir(parents=True)
    (project / "adapt").mkdir()
    (project / "plan" / "pages").mkdir(parents=True)
    (project / "story_bible.json").write_text("{}")
    (project / "brief" / "adaptation_brief.json").write_text("{}")
    (project / "adapt" / "book.json").write_text("{}")
    (project / "plan" / "book.json").write_text("{}")
    (project / "sample.png").write_bytes(b"png")
    (project / "plan" / "pages" / "page_003.json").write_text(
        json.dumps(
            {
                "reading_order": ["content-1", "letter-2", "letter-1"],
                "content": [
                    {
                        "id": "content-1",
                        "lettering": [
                            {"id": "letter-1", "text": "Second in reading order."},
                            {"id": "letter-2", "text": "First in reading order."},
                        ],
                    }
                ],
            }
        )
    )

    replay = TargetFixtureReplay(project)
    result = replay.page_ocr(3)

    assert [item["text"] for item in result["lettering"]] == [
        "First in reading order.",
        "Second in reading order.",
    ]
    extraction = build_extraction(_PageOCRDraft.model_validate(result))
    assert extraction.observed_reading_order == ("region_001", "region_002")
