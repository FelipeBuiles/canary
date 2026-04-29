"""Tests for image prompt composition."""

from novel_to_comic.config import Config
from novel_to_comic.models.layout_plan import PlannedPanel
from novel_to_comic.models.story_bible import Character, Location, Scene, StoryBible
from novel_to_comic.prompting import build_planned_panel_prompt_spec


def _story_bible() -> StoryBible:
    return StoryBible(
        title="The Flowers",
        author="Alice Walker",
        total_scenes=1,
        characters=[
            Character(
                id="char_001",
                name="Myop",
                visual_anchor=(
                    "1girl, child, black girl, dark skin, brown eyes, short hair, "
                    "afro textured hair, simple dress, barefoot"
                ),
                age_range="ten",
                gender="female",
                distinguishing_features=["dark brown skin"],
                default_outfit="A simple dress. She is barefoot.",
                relationships=[],
                first_appearance_scene="scene_002",
            )
        ],
        locations=[
            Location(
                id="loc_002",
                name="The gloomy cove",
                visual_anchor="outdoors, day, woods, forest, sweetsuds bush",
                mood="gloomy",
            )
        ],
        scenes=[
            Scene(
                id="scene_002",
                chapter=1,
                title="A New Path",
                location_id="loc_002",
                character_ids=["char_001"],
                summary="Myop gathers flowers in the woods.",
                scene_type="transition",
                narrative_beat="inciting_incident",
                source_start_quote="She had explored the woods",
            )
        ],
        narrative_arcs=[],
    )


def test_prompt_collapses_sequential_same_character_action_to_single_instant(tmp_path):
    panel = PlannedPanel(
        panel_id="scene_002:panel_002",
        scene_id="scene_002",
        panel_number=2,
        beat_ids=["scene_002:beat_003", "scene_002:beat_004"],
        shot_type="close-up",
        camera_angle="from behind, then low side angle",
        characters_present=["char_001"],
        character_actions={
            "char_001": "crouches to inspect flowers, then rises and buries her face in the sweetsuds buds"
        },
        character_positions={"char_001": "center"},
        background_description="Blue velvety flowers in the foreground.",
        camera_note=(
            "A tight view on her hands and upper body as she lifts the blue flowers, "
            "then leans into the fragrant bush with her bundle crowding her chin."
        ),
        lighting="soft warm filtered light",
        mood="curious delighted",
    )

    prompt = build_planned_panel_prompt_spec(Config(), tmp_path, panel, _story_bible())

    assert "buries her face in the sweetsuds buds" in prompt.full_prompt
    assert "rises and buries" not in prompt.full_prompt
    assert "low side angle camera" in prompt.full_prompt
    assert "from behind, then low side angle" not in prompt.full_prompt
    assert "crouches to inspect flowers" not in prompt.full_prompt
    assert "leans into the fragrant bush with her bundle crowding her chin" in prompt.full_prompt
    assert "lifts the blue flowers" not in prompt.full_prompt
    assert "single frozen instant, not a sequence or split-screen" in prompt.constraints


def test_prompt_does_not_split_non_sequential_then_phrase(tmp_path):
    panel = PlannedPanel(
        panel_id="scene_002:panel_001",
        scene_id="scene_002",
        panel_number=1,
        shot_type="wide",
        camera_angle="low angle",
        characters_present=["char_001"],
        character_actions={
            "char_001": "bounces between the trees, veering left then right along no particular path"
        },
        character_positions={"char_001": "center"},
        background_description="Dense woods behind a farmhouse.",
        camera_note="A wide establishing view with the girl darting through the foreground.",
        lighting="warm dappled morning light",
        mood="playful safe",
    )

    prompt = build_planned_panel_prompt_spec(Config(), tmp_path, panel, _story_bible())

    assert "veering left then right along no particular path" in prompt.full_prompt
