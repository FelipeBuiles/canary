import asyncio

import pytest

from novel_to_comic import artifacts
from novel_to_comic.config import Config
from novel_to_comic.models.layout_plan import LLMPanelSpec
from novel_to_comic.models.panel import ScreenplayBeat
from novel_to_comic.models.story_bible import Scene, StoryBible
from novel_to_comic.stages.s4_screenplay import _process_scene
from novel_to_comic.stages.s5_layout_plan import _autosplit_overflow_panels, _validate_llm_specs
from novel_to_comic.usage import ApiResult


def test_adapt_preserves_complete_lettering_text(monkeypatch, tmp_path):
    narration = "One two three four five six seven eight nine ten."
    dialogue = "There was an aged colleague. He saved me through my great illness years ago."
    bible = StoryBible(
        title="Test",
        author="Author",
        total_scenes=1,
        characters=[],
        locations=[],
        scenes=[
            Scene(
                id="scene_001",
                chapter=1,
                title="Scene",
                location_id="loc_001",
                character_ids=[],
                summary="A conversation.",
                scene_type="dialogue",
                narrative_beat="setup",
                source_start_quote="Opening line",
            )
        ],
        narrative_arcs=[],
        props=[],
    )
    artifacts.write_scene_text(tmp_path, "scene_001", "Scene prose.")

    async def fake_generate_json(**_kwargs):
        return ApiResult(
            value={
                "scene_id": "scene_001",
                "location_id": "loc_001",
                "characters": [],
                "beats": [
                    {"type": "narration", "content": narration, "source_text": narration},
                    {"type": "dialogue", "character_id": None, "content": dialogue},
                ],
            },
            usage=None,
        )

    monkeypatch.setattr("novel_to_comic.clients.text.generate_json", fake_generate_json)

    asyncio.run(
        _process_scene(
            Config(max_words_per_bubble=4),
            tmp_path,
            bible,
            "scene_001",
            "system prompt",
            asyncio.Semaphore(1),
        )
    )
    saved = artifacts.read_screenplay(tmp_path, "scene_001")

    assert [beat.content for beat in saved.beats] == [narration, dialogue]


def test_planner_rejects_panel_with_too_many_combined_dialogue_words():
    beats = [
        ScreenplayBeat(type="dialogue", character_id="char_001", content="one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen"),
        ScreenplayBeat(type="dialogue", character_id="char_001", content="one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen"),
    ]

    with pytest.raises(ValueError, match="dialogue words"):
        _validate_llm_specs([LLMPanelSpec(beat_indices=[1, 2])], beats)


def test_planner_accepts_one_long_dialogue_beat():
    beats = [
        ScreenplayBeat(
            type="dialogue",
            character_id="char_001",
            content=(
                "one two three four five six seven eight nine ten eleven twelve "
                "thirteen fourteen fifteen sixteen seventeen eighteen nineteen twenty "
                "twenty-one twenty-two twenty-three twenty-four twenty-five"
            ),
        ),
    ]

    _validate_llm_specs([LLMPanelSpec(beat_indices=[1])], beats)


def test_planner_accepts_one_long_narration_beat():
    source = (
        "one two three four five six seven eight nine ten eleven twelve thirteen "
        "fourteen fifteen sixteen seventeen"
    )
    beats = [ScreenplayBeat(type="narration", content=source, source_text=source)]

    _validate_llm_specs([LLMPanelSpec(beat_indices=[1])], beats)


def test_planner_does_not_autosplit_one_long_dialogue_beat():
    beats = [
        ScreenplayBeat(
            type="dialogue",
            character_id="char_001",
            content=" ".join(f"word-{index}" for index in range(25)),
        ),
    ]

    specs, _narration, count = _autosplit_overflow_panels(
        [LLMPanelSpec(beat_indices=[1])], [], beats
    )

    assert count == 0
    assert [spec.beat_indices for spec in specs] == [[1]]


def test_planner_autosplits_combined_dialogue_word_overflow():
    beats = [
        ScreenplayBeat(type="dialogue", character_id="char_001", content="one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen"),
        ScreenplayBeat(type="dialogue", character_id="char_001", content="one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen"),
    ]

    specs, _narration, count = _autosplit_overflow_panels(
        [LLMPanelSpec(beat_indices=[1, 2])], [], beats
    )

    assert count == 1
    assert [spec.beat_indices for spec in specs] == [[1], [2]]
