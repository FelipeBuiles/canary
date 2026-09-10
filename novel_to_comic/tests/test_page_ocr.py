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




def test_every_observation_carries_its_own_detected_region() -> None:
    extraction = build_extraction(_draft(("one", 0.1, 0.1), ("two", 0.1, 0.5)))

    assert [item.detected_region_id for item in extraction.lettering] == [
        "region_001",
        "region_002",
    ]
    assert len(extraction.observed_regions) == 2


def test_incidental_in_world_writing_is_not_reported_as_comic_lettering() -> None:
    extraction = build_extraction(
        _PageOCRDraft.model_validate(
            {
                "lettering": [
                    {
                        "text": "The canonical caption.",
                        "role": "comic_lettering",
                        "box": {"x": 0.1, "y": 0.1, "width": 0.5, "height": 0.1},
                    },
                    {
                        "text": "Cthulhu fhtagn",
                        "role": "incidental_text",
                        "box": {"x": 0.2, "y": 0.6, "width": 0.3, "height": 0.1},
                    },
                ]
            }
        )
    )

    assert [item.text for item in extraction.lettering] == ["The canonical caption."]
    assert [item.text for item in extraction.incidental_text] == ["Cthulhu fhtagn"]


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


@pytest.mark.parametrize(
    "coordinates",
    [
        [34, 57, 137, 369],
        [[34, 57, 137, 369]],
    ],
)
def test_adapter_accepts_gemini_coordinate_lists_under_box(
    coordinates,
) -> None:
    draft = _PageOCRDraft.model_validate(
        {
            "lettering": [
                {
                    "text": "The stars were right.",
                    "role": "comic_lettering",
                    "box": coordinates,
                }
            ]
        }
    )

    extraction = build_extraction(draft)

    assert extraction.lettering[0].text == "The stars were right."
    expected_polygon = (
        (0.057, 0.034),
        (0.369, 0.034),
        (0.369, 0.137),
        (0.057, 0.137),
    )
    for actual, expected in zip(
        extraction.observed_regions[0].polygon,
        expected_polygon,
        strict=True,
    ):
        assert actual == pytest.approx(expected)


def test_adapter_accepts_role_named_text_fields_from_gemini() -> None:
    extraction = build_extraction(
        _PageOCRDraft.model_validate(
            {
                "lettering": [
                    {
                        "comic_lettering": "The door opened.",
                        "box": [41, 391, 137, 942],
                    },
                    {
                        "incidental_text": "Cthulhu fhtagn",
                        "box": [660, 344, 802, 661],
                    },
                ]
            }
        )
    )

    assert [item.text for item in extraction.lettering] == ["The door opened."]
    assert [item.text for item in extraction.incidental_text] == [
        "Cthulhu fhtagn"
    ]


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
                model="gemini-3.8-flash",
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
    assert read.usage.model == "gemini-3.8-flash"
    assert captured["image_attachments"] == ((b"page-bytes", "image/png"),)
    assert captured["feature"] == "draw.page_ocr"
    assert captured["temperature"] == 0.0
    assert "canary_page_number: 34" in captured["user_content"]
    assert "It was the same face" not in captured["user_content"]


def test_invalid_envelope_retains_full_provider_response_before_parsing(tmp_path, monkeypatch):
    from pydantic import ValidationError
    from novel_to_comic.target_artifacts import TargetArtifacts
    from novel_to_comic.usage import ApiResult
    from tests.test_page_review import _render

    artifacts = TargetArtifacts(tmp_path)
    payload = {"text": [{"text": "Provider words", "box": {"x": 0, "y": 0, "width": 0.5, "height": 0.1}}]}
    raw_text = json.dumps(payload)
    usage = UsageRecord(provider="gemini", model="gemini-3.8-flash", operation="text")

    async def provider(**kwargs):
        # The complete root contract is actually sent to the provider.
        schema = kwargs["json_schema"]
        assert "lettering" in schema["required"]
        assert schema["additionalProperties"] is False
        assert "panels" in schema["properties"]
        kwargs["response_sink"](ApiResult(value=raw_text, usage=usage))
        return ApiResult(value=payload, usage=usage)

    monkeypatch.setattr("novel_to_comic.clients.text.generate_json", provider)
    adapter = GatewayPageOCRAdapter(Config(), page_number=34)
    adapter.bind_render(artifacts, _render())
    with pytest.raises(ValidationError):
        asyncio.run(adapter.extract(b"page-34"))
    retained = artifacts.read_ocr_response(34, 1)
    assert retained.raw_response == raw_text
    assert retained.usage == usage
    assert retained.render_image_sha256 == _render().image_sha256
    assert not artifacts.raw_ocr_path(34, 1).exists()


def test_retained_response_revalidates_without_provider_or_canonical_substitution(tmp_path, monkeypatch):
    from novel_to_comic.models.draw import OCRProviderResponse
    from novel_to_comic.page_review import revalidate_cached_page_render
    from novel_to_comic.target_artifacts import TargetArtifacts
    from tests.test_page_review import _page, _render

    artifacts = TargetArtifacts(tmp_path)
    render = _render()
    artifacts.write_ocr_response(OCRProviderResponse(
        page_number=34, render_revision=1, render_image_sha256=render.image_sha256,
        request_sha256=render.request_sha256, response=None,
        raw_response=json.dumps({"lettering": [{"text": "Actually seen, not canonical",
            "box": {"x": 0, "y": 0, "width": 0.5, "height": 0.1}}], "panels": []}),
        usage=UsageRecord(provider="gemini", model="gemini-3.8-flash", operation="text"),
    ))
    async def forbidden(**kwargs):
        raise AssertionError("cached recovery must never call a provider")
    monkeypatch.setattr("novel_to_comic.clients.text.generate_json", forbidden)
    analysis = revalidate_cached_page_render(page=_page(), render=render, artifacts=artifacts)
    assert analysis.ocr_observations[0].text == "Actually seen, not canonical"
    assert not analysis.lettering_valid
    assert revalidate_cached_page_render(page=_page(), render=render, artifacts=artifacts) == analysis


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
