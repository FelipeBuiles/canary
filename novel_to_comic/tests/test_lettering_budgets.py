import pytest

from novel_to_comic.models.layout_plan import LLMPanelSpec
from novel_to_comic.models.panel import Screenplay, ScreenplayBeat
from novel_to_comic.stages.s4_screenplay import enforce_lettering_budgets
from novel_to_comic.stages.s5_layout_plan import _autosplit_overflow_panels, _validate_llm_specs


def test_screenplay_budget_splits_speech_at_word_boundaries():
    screenplay = Screenplay(
        scene_id="scene_001",
        location_id="loc_001",
        characters=["char_001"],
        beats=[
            ScreenplayBeat(
                type="dialogue",
                character_id="char_001",
                content="One two three four five six seven eight nine ten.",
            )
        ],
    )

    budgeted = enforce_lettering_budgets(screenplay, max_words_per_bubble=4)

    assert [beat.content for beat in budgeted.beats] == [
        "One two three four",
        "five six seven eight",
        "nine ten.",
    ]
    assert all(beat.character_id == "char_001" for beat in budgeted.beats)


def test_screenplay_budget_shortens_narration_without_losing_source_text():
    source = "One two three four five six seven eight nine ten."
    screenplay = Screenplay(
        scene_id="scene_001",
        location_id="loc_001",
        characters=[],
        beats=[ScreenplayBeat(type="narration", content=source, source_text=source)],
    )

    budgeted = enforce_lettering_budgets(screenplay, max_words_per_bubble=4)

    assert budgeted.beats[0].content == "One two three four…"
    assert budgeted.beats[0].source_text == source


def test_planner_rejects_panel_with_too_many_combined_dialogue_words():
    beats = [
        ScreenplayBeat(type="dialogue", character_id="char_001", content="one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen"),
        ScreenplayBeat(type="dialogue", character_id="char_001", content="one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen"),
    ]

    with pytest.raises(ValueError, match="dialogue words"):
        _validate_llm_specs([LLMPanelSpec(beat_indices=[1, 2])], beats)


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
