import pytest

from novel_to_comic.models.layout_plan import LLMPanelSpec
from novel_to_comic.models.panel import ScreenplayBeat
from novel_to_comic.models.story_bible import Prop, StoryBible
from novel_to_comic.stages.s5_layout_plan import (
    _llm_spec_to_planned_panel,
    _scene_planning_user_content,
    _validate_llm_specs,
)


def _story_bible() -> StoryBible:
    from novel_to_comic.models.story_bible import Character

    return StoryBible(
        title="Test",
        author="A. Writer",
        total_scenes=1,
        characters=[
            Character(
                id="char_001",
                name="Mara",
                visual_anchor="1woman, dark hair, leather jacket",
                age_range="late 20s",
                gender="female",
                distinguishing_features=["dark hair"],
                default_outfit="leather jacket",
                relationships=[],
                first_appearance_scene="scene_001",
            )
        ],
        locations=[],
        scenes=[],
        narrative_arcs=[],
        props=[
            Prop(
                id="prop_key",
                name="Brass key",
                visual_anchor="small tarnished brass key, bent tooth, red thread loop",
            )
        ],
    )


def test_llm_spec_to_planned_panel_preserves_expression_objects_and_must_show():
    beats = [
        ScreenplayBeat(type="action", content="Mara grabs the Brass key from the table."),
        ScreenplayBeat(type="dialogue", character_id="char_001", content="We leave now."),
        ScreenplayBeat(type="sfx", content="CRACK"),
    ]
    spec = LLMPanelSpec(
        beat_indices=[1, 2, 3],
        characters_present=["char_001"],
        character_actions={"char_001": "reaches across the table with one hand"},
        character_expressions={"char_001": "eyes narrowed, mouth held still"},
        key_objects=["Brass key"],
        visual_requirements=["the key glints between her fingers"],
        shot_type="close-up",
        camera_angle="low-angle",
        lighting="hard window light",
        mood="urgent",
    )

    panel = _llm_spec_to_planned_panel(
        "scene_001",
        1,
        spec,
        beats,
        _story_bible(),
    )

    assert panel.character_expressions["char_001"] == "eyes narrowed, mouth held still"
    assert "Brass key" in panel.key_objects
    assert any("show Mara grabs the Brass key" in req for req in panel.visual_requirements)
    assert any("show Mara's dialogue moment" in req for req in panel.visual_requirements)
    assert not any("char_001" in req for req in panel.visual_requirements)
    assert not any(req.startswith("beat ") for req in panel.visual_requirements)
    assert any("visible source or result of the CRACK sound effect" in req for req in panel.visual_requirements)
    assert "the key glints between her fingers" in panel.visual_requirements


def test_validate_llm_specs_rejects_missing_visual_beats():
    beats = [
        ScreenplayBeat(type="action", content="Mara grabs the key."),
        ScreenplayBeat(type="action", content="She locks the door."),
    ]

    with pytest.raises(ValueError, match="omitted visual beat_indices"):
        _validate_llm_specs([LLMPanelSpec(beat_indices=[1])], beats)


def test_validate_llm_specs_rejects_duplicate_visual_beats():
    beats = [
        ScreenplayBeat(type="action", content="Mara grabs the key."),
        ScreenplayBeat(type="action", content="She locks the door."),
    ]

    with pytest.raises(ValueError, match="duplicated visual beat_indices"):
        _validate_llm_specs(
            [
                LLMPanelSpec(beat_indices=[1]),
                LLMPanelSpec(beat_indices=[1, 2]),
            ],
            beats,
        )


def test_scene_planning_prompt_includes_story_props():
    from novel_to_comic.models.panel import Screenplay

    screenplay = Screenplay(
        scene_id="scene_001",
        location_id="loc_001",
        characters=[],
        beats=[ScreenplayBeat(type="action", content="Mara studies the lock.")],
    )

    user_content = _scene_planning_user_content(screenplay, _story_bible(), 4)

    assert "Story props:" in user_content
    assert "prop_key (Brass key): small tarnished brass key" in user_content
