"""Adapt-stage tests: location-state context + scene-boundary guard."""

from novel_to_comic.models.panel import Screenplay, ScreenplayBeat
from novel_to_comic.models.story_bible import (
    Character,
    Location,
    LocationState,
    Scene,
    StoryBible,
)
from novel_to_comic.stages.s4_screenplay import (
    _build_user_content,
    _enforce_scene_boundary,
)


def _bible_with_two_scenes() -> StoryBible:
    return StoryBible(
        title="DCC",
        author="Matt Dinniman",
        total_scenes=2,
        characters=[
            Character(
                id="char_001",
                name="Carl",
                visual_anchor="1man, adult male",
                age_range="late 20s",
                gender="male",
                distinguishing_features=["muscular build"],
                default_outfit="boxers, leather jacket",
                relationships=[],
                first_appearance_scene="scene_001",
            )
        ],
        locations=[
            Location(
                id="loc_001",
                name="Seattle Street",
                visual_anchor="night, outdoors, street",
                mood="apocalyptic",
                states=[
                    LocationState(
                        id="loc_001_pre",
                        name="Pre-collapse",
                        visual_anchor="night, outdoors, brick apartment facade, streetlamp",
                        description="Buildings still standing.",
                    ),
                    LocationState(
                        id="loc_001_post",
                        name="Post-collapse",
                        visual_anchor="night, outdoors, flattened dirt, rubble",
                    ),
                ],
            )
        ],
        scenes=[
            Scene(
                id="scene_001",
                chapter=1,
                title="The Transformation",
                location_id="loc_001",
                location_state_id="loc_001_pre",
                character_ids=["char_001"],
                summary="Carl outside.",
                scene_type="transition",
                narrative_beat="inciting_incident",
                source_start_quote="The transformation occurred at approximately 2:23 AM",
            ),
            Scene(
                id="scene_002",
                chapter=1,
                title="The Descent",
                location_id="loc_001",
                character_ids=["char_001"],
                summary="Carl descends.",
                scene_type="transition",
                narrative_beat="rising_action",
                source_start_quote="Dungeon Floor 1. Time to Level Collapse",
            ),
        ],
        narrative_arcs=[],
        props=[],
    )


def test_user_content_surfaces_location_states_and_next_scene_marker():
    bible = _bible_with_two_scenes()
    content = _build_user_content("scene prose here", bible, "scene_001")

    assert "Location states" in content
    assert "loc_001_pre" in content
    assert "loc_001_post" in content
    assert "[default]" in content  # marks the scene's default state
    assert "SCENE BOUNDARY" in content
    assert "Dungeon Floor 1" in content


def test_enforce_scene_boundary_trims_overflow_beats():
    bible = _bible_with_two_scenes()
    screenplay = Screenplay(
        scene_id="scene_001",
        location_id="loc_001",
        characters=["char_001"],
        beats=[
            ScreenplayBeat(type="action", content="Carl outside in the cold."),
            ScreenplayBeat(type="narration", content="World announcement plays."),
            ScreenplayBeat(
                type="action",
                content="Carl descends.",
                source_text="Dungeon Floor 1. Time to Level Collapse: Five days.",
            ),
            ScreenplayBeat(type="action", content="Carl reaches the bottom."),
        ],
    )

    trimmed, warning = _enforce_scene_boundary(screenplay, bible)

    assert len(trimmed.beats) == 2
    assert warning is not None and "trimmed" in warning


def test_enforce_scene_boundary_silent_when_no_overflow():
    bible = _bible_with_two_scenes()
    screenplay = Screenplay(
        scene_id="scene_001",
        location_id="loc_001",
        characters=["char_001"],
        beats=[
            ScreenplayBeat(type="action", content="Carl outside in the cold."),
            ScreenplayBeat(type="narration", content="World announcement plays."),
        ],
    )
    trimmed, warning = _enforce_scene_boundary(screenplay, bible)
    assert len(trimmed.beats) == 2
    assert warning is None


def test_enforce_scene_boundary_skipped_for_last_scene():
    bible = _bible_with_two_scenes()
    screenplay = Screenplay(
        scene_id="scene_002",
        location_id="loc_001",
        characters=["char_001"],
        beats=[ScreenplayBeat(type="action", content="Carl reaches the bottom.")],
    )
    trimmed, warning = _enforce_scene_boundary(screenplay, bible)
    assert len(trimmed.beats) == 1
    assert warning is None
