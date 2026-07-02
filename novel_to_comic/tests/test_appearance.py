"""Unit tests for the appearance-timeline resolver."""

from novel_to_comic.appearance import active_state, panel_position
from novel_to_comic.models.appearance import (
    AppearanceState,
    StateActivation,
    StoryPosition,
)

SCENE_ORDER = [f"scene_{i:03d}" for i in range(1, 17)]


def _states() -> list[AppearanceState]:
    return [
        AppearanceState(id="stumps", label="Maimed", visual_anchor="bloodied stumps", visually_significant=True),
        AppearanceState(id="silver", label="Silver hands", visual_anchor="polished silver hands", visually_significant=True),
        AppearanceState(id="restored", label="Restored", visual_anchor="natural hands", visually_significant=True),
    ]


def _timeline() -> list[StateActivation]:
    return [
        StateActivation(state_id="stumps", at=StoryPosition(scene_id="scene_004")),
        StateActivation(state_id="silver", at=StoryPosition(scene_id="scene_009")),
        StateActivation(state_id="restored", at=StoryPosition(scene_id="scene_016")),
    ]


def _resolve(scene_id: str, beat: int | None = None):
    return active_state(
        "BASE real hands",
        _states(),
        _timeline(),
        StoryPosition(scene_id=scene_id, beat=beat),
        SCENE_ORDER,
    )


def test_base_look_before_first_activation():
    r = _resolve("scene_003")
    assert r.state_id is None
    assert r.anchor == "BASE real hands"


def test_activation_inclusive_at_its_scene():
    assert _resolve("scene_004").state_id == "stumps"
    assert _resolve("scene_009").state_id == "silver"
    assert _resolve("scene_016").state_id == "restored"


def test_state_holds_until_next_activation():
    assert _resolve("scene_005").state_id == "stumps"
    assert _resolve("scene_008").state_id == "stumps"
    assert _resolve("scene_013").state_id == "silver"
    assert _resolve("scene_015").state_id == "silver"


def test_silver_never_resolves_before_scene_009():
    for i in range(1, 9):
        assert _resolve(f"scene_{i:03d}").state_id != "silver"


def test_resolved_anchor_is_the_state_anchor():
    assert _resolve("scene_009").anchor == "polished silver hands"
    assert _resolve("scene_016").anchor == "natural hands"


def test_beat_level_resolution_within_a_scene():
    states = [AppearanceState(id="post", label="Post", visual_anchor="rubble")]
    timeline = [StateActivation(state_id="post", at=StoryPosition(scene_id="scene_001", beat=3))]
    order = ["scene_001"]
    before = active_state("base", states, timeline, StoryPosition(scene_id="scene_001", beat=2), order)
    at = active_state("base", states, timeline, StoryPosition(scene_id="scene_001", beat=3), order)
    after = active_state("base", states, timeline, StoryPosition(scene_id="scene_001", beat=5), order)
    assert before.state_id is None
    assert at.state_id == "post"
    assert after.state_id == "post"


def test_non_monotonic_reactivation():
    # A location can return to an earlier state (revisit, day→night→day).
    states = [
        AppearanceState(id="night", label="Night", visual_anchor="dark"),
        AppearanceState(id="day", label="Day", visual_anchor="bright"),
    ]
    timeline = [
        StateActivation(state_id="night", at=StoryPosition(scene_id="scene_002")),
        StateActivation(state_id="day", at=StoryPosition(scene_id="scene_004")),
    ]
    assert active_state("base", states, timeline, StoryPosition(scene_id="scene_003"), SCENE_ORDER).state_id == "night"
    assert active_state("base", states, timeline, StoryPosition(scene_id="scene_005"), SCENE_ORDER).state_id == "day"


def test_unknown_activation_state_falls_back_to_base():
    timeline = [StateActivation(state_id="ghost", at=StoryPosition(scene_id="scene_001"))]
    r = active_state("base", [], timeline, StoryPosition(scene_id="scene_002"), SCENE_ORDER)
    assert r.state_id is None
    assert r.anchor == "base"


class _Panel:
    def __init__(self, scene_id: str, beat_ids: list[str]):
        self.scene_id = scene_id
        self.beat_ids = beat_ids


def test_panel_position_uses_last_covered_beat():
    pos = panel_position(_Panel("scene_004", ["scene_004:beat_002", "scene_004:beat_005"]), SCENE_ORDER)
    assert pos.scene_id == "scene_004"
    assert pos.beat == 5


def test_panel_position_without_beats_is_scene_start():
    pos = panel_position(_Panel("scene_004", []), SCENE_ORDER)
    assert pos.beat is None
