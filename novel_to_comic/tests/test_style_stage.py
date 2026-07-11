"""Tests for S2 style suggestions (declared-medium dedup) and the style-sample brief."""

import asyncio
import json
from unittest.mock import AsyncMock, patch

from novel_to_comic import artifacts
from novel_to_comic.config import Config
from novel_to_comic.models.story_bible import Character, Location, Scene, StoryBible
from novel_to_comic.stages.s2_style import (
    SAMPLE_COUNT,
    _build_avoid_block,
    _dedupe_suggestions,
    ensure_style_sample_brief,
    generate_sample_image,
    generate_suggestions,
)
from novel_to_comic.usage import ApiResult

BRIEF = (
    "Carl, a broad-shouldered man in his late twenties wearing a worn leather "
    "jacket, stands ankle-deep in fresh snow on a dark Seattle street."
)


def _bible(character_name: str = "Carl") -> StoryBible:
    return StoryBible(
        title="DCC",
        author="Matt Dinniman",
        total_scenes=1,
        characters=[
            Character(
                id="char_001",
                name=character_name,
                visual_anchor="1man, adult male, leather jacket",
                age_range="late 20s",
                gender="male",
                distinguishing_features=[],
                default_outfit="",
                relationships=[],
                first_appearance_scene="scene_001",
            )
        ],
        locations=[
            Location(
                id="loc_001",
                name="Seattle Street",
                visual_anchor="outdoors, snow, winter",
                mood="apocalyptic",
            )
        ],
        scenes=[
            Scene(
                id="scene_001",
                chapter=1,
                title="The Transformation",
                location_id="loc_001",
                character_ids=["char_001"],
                summary="Carl outside.",
                scene_type="transition",
                narrative_beat="inciting_incident",
                source_start_quote="The transformation occurred",
            )
        ],
        narrative_arcs=[],
        props=[],
    )


def _sugg(label: str, medium: str) -> dict:
    return {
        "label": label,
        "medium": medium,
        "template": f"{label}: a vivid forty-word visual direction in this medium.",
    }


# ── declared-medium dedup ────────────────────────────────────────────────────


def test_dedupe_drops_repeated_declared_medium():
    kept = _dedupe_suggestions(
        [_sugg("A", "woodblock print"), _sugg("B", "gouache"), _sugg("C", "woodblock print")]
    )
    assert [s["label"] for s in kept] == ["A", "B"]


def test_dedupe_treats_refined_medium_as_duplicate():
    kept = _dedupe_suggestions([_sugg("A", "etching"), _sugg("B", "copper etching")])
    assert [s["label"] for s in kept] == ["A"]

    # Sharing one token without refinement is not a collision — the LLM's
    # curation pass owns family-level judgement, not the safety net.
    kept = _dedupe_suggestions([_sugg("A", "woodblock print"), _sugg("B", "screen print")])
    assert [s["label"] for s in kept] == ["A", "B"]


def test_dedupe_respects_existing_pool():
    kept = _dedupe_suggestions(
        [_sugg("New", "gouache"), _sugg("Other", "charcoal")],
        existing_suggestions=[_sugg("Old", "gouache")],
    )
    assert [s["label"] for s in kept] == ["Other"]


def test_dedupe_keeps_legacy_and_drops_malformed():
    # Legacy suggestions (pre-medium) never collide; empty templates are dropped.
    kept = _dedupe_suggestions(
        [
            {"label": "Empty", "medium": "ink", "template": "  "},
            {"label": "Legacy", "template": "a style with no declared medium yet."},
            _sugg("Inked", "ink"),
        ],
        existing_suggestions=[{"label": "OldLegacy", "template": "older style."}],
    )
    assert [s["label"] for s in kept] == ["Legacy", "Inked"]


def test_build_avoid_block_lists_used_mediums():
    assert _build_avoid_block([]) == ""

    block = _build_avoid_block([_sugg("A", "Woodblock Print"), _sugg("B", "gouache")])
    assert "ALREADY been suggested" in block
    assert "woodblock print" in block
    assert "gouache" in block


# ── generate_suggestions ─────────────────────────────────────────────────────


def test_generate_suggestions_dedupes_and_trims_to_sample_count():
    mediums = [
        "woodblock print", "gouache", "35mm photography", "cut-paper collage",
        "charcoal", "woodblock print", "oil paint", "gouache",
    ]
    raw = [_sugg(f"S{i}", m) for i, m in enumerate(mediums)]
    mock = AsyncMock(return_value=ApiResult(value=raw, usage=None))

    with patch("novel_to_comic.clients.text.generate_json", new=mock):
        suggestions, _usage = asyncio.run(generate_suggestions(Config(), _bible()))

    assert [s["label"] for s in suggestions] == ["S0", "S1", "S2", "S3", "S4"]
    assert len(suggestions) == SAMPLE_COUNT
    assert mock.await_count == 1


def test_generate_suggestions_retries_with_expanded_avoid_pool():
    first = [_sugg("A", "gouache"), _sugg("B", "ink"), _sugg("C", "gouache")]
    second = [
        _sugg("D", "gouache"),  # repeats a kept medium — dropped by safety net
        _sugg("E", "charcoal"),
        _sugg("F", "35mm photography"),
        _sugg("G", "woodblock print"),
    ]
    mock = AsyncMock(side_effect=[
        ApiResult(value=first, usage=None),
        ApiResult(value=second, usage=None),
    ])

    with patch("novel_to_comic.clients.text.generate_json", new=mock):
        suggestions, _usage = asyncio.run(generate_suggestions(Config(), _bible()))

    assert [s["label"] for s in suggestions] == ["A", "B", "E", "F", "G"]
    assert mock.await_count == 2
    retry_system = mock.await_args.kwargs["system_prompt"]
    assert "ALREADY been suggested" in retry_system
    assert "gouache" in retry_system
    assert "ink" in retry_system


# ── style-sample brief ───────────────────────────────────────────────────────


def test_ensure_style_sample_brief_generates_then_serves_from_cache(tmp_path):
    mock = AsyncMock(return_value=ApiResult(value=BRIEF, usage=None))

    with patch("novel_to_comic.clients.text.generate_text", new=mock):
        first = asyncio.run(ensure_style_sample_brief(Config(), _bible(), tmp_path))
        second = asyncio.run(ensure_style_sample_brief(Config(), _bible(), tmp_path))

    assert first == BRIEF
    assert second == BRIEF
    assert mock.await_count == 1
    cached = json.loads(artifacts.style_sample_brief_path(tmp_path).read_text())
    assert cached["brief"] == BRIEF


def test_ensure_style_sample_brief_regenerates_when_bible_changes(tmp_path):
    mock = AsyncMock(return_value=ApiResult(value=BRIEF, usage=None))

    with patch("novel_to_comic.clients.text.generate_text", new=mock):
        asyncio.run(ensure_style_sample_brief(Config(), _bible("Carl"), tmp_path))
        asyncio.run(ensure_style_sample_brief(Config(), _bible("Donut"), tmp_path))

    assert mock.await_count == 2


def test_ensure_style_sample_brief_disabled_skips_llm(tmp_path):
    config = Config(style_sample_brief_enabled=False)
    with patch(
        "novel_to_comic.clients.text.generate_text",
        new=AsyncMock(side_effect=AssertionError("should not be called")),
    ):
        assert asyncio.run(ensure_style_sample_brief(config, _bible(), tmp_path)) is None


def test_ensure_style_sample_brief_fails_soft(tmp_path):
    with patch(
        "novel_to_comic.clients.text.generate_text",
        new=AsyncMock(side_effect=RuntimeError("gateway down")),
    ):
        assert asyncio.run(ensure_style_sample_brief(Config(), _bible(), tmp_path)) is None
    assert not artifacts.style_sample_brief_path(tmp_path).exists()


def test_generate_sample_image_uses_brief_and_writes_meta(tmp_path):
    captured: dict = {}

    async def _fake_generate_image(*, config, prompt, output_path, feature, **kwargs):
        captured["prompt"] = prompt
        captured["kwargs"] = kwargs
        return ApiResult(value=str(output_path), usage=None)

    sample_path = tmp_path / "samples" / "style_1.png"
    with patch(
        "novel_to_comic.clients.flux.generate_image",
        new=AsyncMock(side_effect=_fake_generate_image),
    ):
        asyncio.run(
            generate_sample_image(
                Config(style_template="Clinical, desaturated visual language."),
                _bible(),
                sample_path,
                brief=BRIEF,
            )
        )

    assert BRIEF in captured["prompt"]
    meta = json.loads((tmp_path / "samples" / "style_1.png.meta.json").read_text())
    assert meta["prompt"] == captured["prompt"]
    assert meta["parameters"]["style_template"] == "Clinical, desaturated visual language."
    # Slice 06: style proof images use a portrait 4:5 frame.
    assert meta["parameters"]["width"] == 819
    assert meta["parameters"]["height"] == 1024
