"""Adapt-stage tests: location-state context + scene-boundary guard."""

from novel_to_comic.models.panel import Screenplay, ScreenplayBeat
from novel_to_comic.models.appearance import (
    AppearanceState,
    StateActivation,
    StoryPosition,
    Transition,
)
from novel_to_comic.models.story_bible import (
    Character,
    Location,
    Scene,
    StoryBible,
)
from novel_to_comic.stages.s4_screenplay import (
    _build_user_content,
    _enforce_scene_boundary,
    _find_transition_beat,
    _resolve_present_characters,
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
                appearance_states=[
                    AppearanceState(
                        id="loc_001_post",
                        label="Post-collapse",
                        visual_anchor="night, outdoors, flattened dirt, rubble",
                        visually_significant=True,
                    ),
                ],
                appearance_timeline=[
                    StateActivation(
                        state_id="loc_001_post",
                        at=StoryPosition(scene_id="scene_002"),
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


def test_user_content_surfaces_next_scene_marker():
    bible = _bible_with_two_scenes()
    content = _build_user_content("scene prose here", bible, "scene_001")

    # Location appearance state is resolved per panel from the location's
    # appearance_timeline now, so the screenplay context no longer surfaces
    # state ids for beat-level tagging.
    assert "Location states" not in content
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


def _bible_with_overlapping_cast() -> StoryBible:
    def _char(cid, name):
        return Character(
            id=cid,
            name=name,
            visual_anchor=f"a person, {name}",
            age_range="adult",
            gender="any",
            distinguishing_features=[],
            default_outfit="clothes",
            relationships=[],
            first_appearance_scene="scene_001",
        )

    return StoryBible(
        title="T",
        author="A",
        total_scenes=1,
        characters=[
            _char("char_001", "The Miller's Daughter"),
            _char("char_002", "The Miller"),
            _char("char_004", "The King"),
        ],
        locations=[],
        scenes=[
            Scene(
                id="scene_001",
                chapter=1,
                title="Garden",
                location_id="loc_001",
                character_ids=["char_001", "char_002", "char_004"],
                summary="x",
                scene_type="transition",
                narrative_beat="rising_action",
                source_start_quote="The King strides through the garden at dawn.",
            )
        ],
        narrative_arcs=[],
        props=[],
    )


def test_resolve_present_characters_readds_dropped_onscreen_king():
    """An on-screen, named character the adapt LLM dropped is re-added + tagged."""
    bible = _bible_with_overlapping_cast()
    screenplay = Screenplay(
        scene_id="scene_001",
        location_id="loc_001",
        characters=["char_001"],  # adapt LLM dropped The King
        beats=[
            ScreenplayBeat(type="action", content="The King strides through the garden."),
            ScreenplayBeat(
                type="dialogue",
                content="What became of it?",
                direction="Off-screen speaker: the King.",
            ),
        ],
    )
    fixed = _resolve_present_characters(screenplay, bible)
    assert "char_004" in fixed.characters
    # The unattributed action beat naming exactly one present char is tagged.
    assert fixed.beats[0].character_id == "char_004"


def test_resolve_present_characters_no_subsumption_false_positive():
    """"The Miller's Daughter" must NOT pull in the Miller via the shorter name."""
    bible = _bible_with_overlapping_cast()
    screenplay = Screenplay(
        scene_id="scene_001",
        location_id="loc_001",
        characters=[],
        beats=[
            ScreenplayBeat(type="action", content="The Miller's Daughter kneels in prayer."),
        ],
    )
    fixed = _resolve_present_characters(screenplay, bible)
    assert "char_001" in fixed.characters
    assert "char_002" not in fixed.characters  # The Miller is not present


def test_find_transition_beat_pins_last_act_beat():
    """The depicting beat is the LAST action beat matching the transition, not
    the earlier dialogue that merely threatens the act."""
    activation = StateActivation(
        state_id="stumps",
        at=StoryPosition(scene_id="scene_001"),
        transition=Transition(label="hands severed"),
    )
    state = AppearanceState(
        id="stumps",
        label="Maimed",
        visual_anchor="a person, arm stumps, bandaged ends, weeping",
        visually_significant=True,
    )
    base = "a person, gentle expression"
    beats = [
        ScreenplayBeat(type="dialogue", content="Cut her hands off!"),       # 1 (threat)
        ScreenplayBeat(type="action", content="She lays her hands on the rail."),  # 2 (act-adjacent)
        ScreenplayBeat(type="sfx", content="THWACK"),                        # 3
        ScreenplayBeat(type="action", content="She stands, arms held before her."),  # 4 (no keyword)
    ]
    k = _find_transition_beat(activation, state, base, beats)
    # Last action/sfx beat matching a keyword ("hands") is beat 2.
    assert k == 2


def test_find_transition_beat_returns_none_without_match():
    activation = StateActivation(
        state_id="silver",
        at=StoryPosition(scene_id="scene_001"),
        transition=Transition(label="silver hands forged"),
    )
    state = AppearanceState(
        id="silver", label="Silver", visual_anchor="a person, silver hands", visually_significant=True
    )
    beats = [ScreenplayBeat(type="action", content="They walk down a quiet road.")]
    assert _find_transition_beat(activation, state, "a person", beats) is None
