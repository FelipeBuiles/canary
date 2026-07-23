import asyncio

import pytest

from novel_to_comic.config import Config
from novel_to_comic.models.layout_plan import LLMPanelSpec
from novel_to_comic.models.panel import Screenplay, ScreenplayBeat
from novel_to_comic.models.story_bible import Prop, StoryBible
from novel_to_comic.stages.s5_layout_plan import (
    estimate_cost,
    _importance_aware_paginate,
    _llm_spec_to_planned_panel,
    _scene_planning_user_content,
    _plan_scene_llm,
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


def _make_panel(panel_num: int, **overrides):
    from novel_to_comic.models.layout_plan import PlannedPanel

    base = {
        "panel_id": f"scene_001:panel_{panel_num:03d}",
        "scene_id": "scene_001",
        "panel_number": panel_num,
        "beat_ids": [f"scene_001:beat_{panel_num:03d}"],
        "shot_type": "wide",
        "characters_present": ["char_001"],
        "character_actions": {"char_001": "stands numb"},
        "background_description": "featureless flattened ground, fire on the far horizon",
    }
    base.update(overrides)
    return PlannedPanel(**base)


def test_pagination_sets_generation_aspect_from_page_geometry():
    panels = [_make_panel(i, shot_type="close-up", shape_intent="rect") for i in range(1, 7)]
    panels[0].importance = "hero"

    pages = _importance_aware_paginate("scene_001", panels, 1, 6)

    assert pages[0].layout_template == "3x2"
    assert pages[0].panel_geometries[4].panel_id == "scene_001:panel_005"
    assert pages[0].panel_geometries[4].aspect_ratio == pytest.approx(1.5)
    assert panels[4].generation_aspect_ratio == pytest.approx(1.5)
    assert panels[4].generation_width == 1536
    assert panels[4].generation_height == 1024
    assert panels[4].generation_shape == "landscape"
    assert panels[4].generation_aspect_source == "page_geometry"


def test_dedupe_adjacent_panels_merges_visual_duplicates():
    from novel_to_comic.stages.s5_layout_plan import _dedupe_adjacent_panels

    panels = [_make_panel(10), _make_panel(11), _make_panel(12, shot_type="medium")]
    warnings: list[str] = []

    kept, _ = _dedupe_adjacent_panels(panels, [], warnings)

    # p10 and p11 are visually identical -> merged. p12 differs by shot -> kept.
    assert [p.panel_id for p in kept] == [
        "scene_001:panel_010",
        "scene_001:panel_012",
    ]
    # Beat ids from p11 carried into p10.
    assert "scene_001:beat_011" in kept[0].beat_ids
    assert any("merged duplicate" in w for w in warnings)


def test_dedupe_remaps_narration_decisions_for_dropped_panels():
    from novel_to_comic.models.layout_plan import NarrationDecision
    from novel_to_comic.stages.s5_layout_plan import _dedupe_adjacent_panels

    panels = [_make_panel(10), _make_panel(11)]
    decisions = [
        NarrationDecision(
            beat_id="scene_001:beat_011",
            scene_id="scene_001",
            beat_index=11,
            source_text="The voice droned on.",
            decision="rendered",
            panel_id="scene_001:panel_011",
            decision_reason="caption",
        )
    ]
    warnings: list[str] = []

    _, updated_decisions = _dedupe_adjacent_panels(panels, decisions, warnings)

    assert updated_decisions[0].panel_id == "scene_001:panel_010"


def test_dedupe_preserves_panels_when_action_differs():
    from novel_to_comic.stages.s5_layout_plan import _dedupe_adjacent_panels

    p1 = _make_panel(10)
    p2 = _make_panel(
        11,
        character_actions={"char_001": "turns toward the light"},
    )
    warnings: list[str] = []
    kept, _ = _dedupe_adjacent_panels([p1, p2], [], warnings)
    assert len(kept) == 2
    assert not warnings


def test_warn_scene_overflow_flags_overlong_scenes():
    from novel_to_comic.stages.s5_layout_plan import _warn_scene_panel_overflow

    panels = [_make_panel(i) for i in range(1, 20)]  # 19 panels, all scene_001
    warnings: list[str] = []
    _warn_scene_panel_overflow(panels, warnings)
    assert any("planned 19 panels" in w for w in warnings)


def test_warn_scene_overflow_silent_on_normal_scene_sizes():
    from novel_to_comic.stages.s5_layout_plan import _warn_scene_panel_overflow

    panels = [_make_panel(i) for i in range(1, 10)]  # 9 panels — fine
    warnings: list[str] = []
    _warn_scene_panel_overflow(panels, warnings)
    assert warnings == []


def _bible_for_splash_demote() -> "StoryBible":
    from novel_to_comic.models.story_bible import (
        Character,
        Location,
        NarrativeArc,
        Scene,
        StoryBible,
    )
    return StoryBible(
        title="Test",
        author="A",
        total_scenes=4,
        characters=[
            Character(
                id="char_001", name="X",
                visual_anchor="tag", age_range="20s", gender="any",
                distinguishing_features=[], default_outfit="",
                relationships=[], first_appearance_scene="scene_001",
            )
        ],
        locations=[Location(id="loc_001", name="L", visual_anchor="x", mood="m")],
        scenes=[
            Scene(id="scene_001", chapter=1, title="A",
                  location_id="loc_001", character_ids=[],
                  summary="...", scene_type="action",
                  narrative_beat="inciting_incident",
                  source_start_quote="..."),
            Scene(id="scene_002", chapter=1, title="B",
                  location_id="loc_001", character_ids=[],
                  summary="...", scene_type="action",
                  narrative_beat="rising_action",
                  source_start_quote="..."),
            Scene(id="scene_003", chapter=1, title="C",
                  location_id="loc_001", character_ids=[],
                  summary="...", scene_type="action",
                  narrative_beat="rising_action",
                  source_start_quote="..."),
            Scene(id="scene_004", chapter=1, title="D",
                  location_id="loc_001", character_ids=[],
                  summary="...", scene_type="action",
                  narrative_beat="climax",
                  source_start_quote="..."),
        ],
        narrative_arcs=[
            NarrativeArc(act=1, title="Setup",
                         scenes=["scene_001", "scene_002"], turning_point=None),
            NarrativeArc(act=2, title="Confrontation",
                         scenes=["scene_003", "scene_004"], turning_point=None),
        ],
        props=[],
    )


def _splash_panel(scene_id: str, panel_num: int):
    from novel_to_comic.models.layout_plan import PlannedPanel
    return PlannedPanel(
        panel_id=f"{scene_id}:panel_{panel_num:03d}",
        scene_id=scene_id,
        panel_number=panel_num,
        importance="splash",
        shape_intent="wide",
        shot_type="wide",
        characters_present=[],
        background_description=f"bg for {scene_id}",
    )


def test_demote_excess_splashes_caps_one_per_act():
    from novel_to_comic.stages.s5_layout_plan import _demote_excess_splashes

    bible = _bible_for_splash_demote()
    # Each scene gets one splash + a regular follow-up panel.
    panels = []
    for sid, pn in [("scene_001", 1), ("scene_002", 1), ("scene_003", 1), ("scene_004", 1)]:
        panels.append(_splash_panel(sid, pn))

    warnings: list[str] = []
    out = _demote_excess_splashes(panels, bible, warnings)

    importances = {p.panel_id: p.importance for p in out}
    # Act 1: scene_001 (inciting_incident) keeps splash, scene_002 demoted.
    assert importances["scene_001:panel_001"] == "splash"
    assert importances["scene_002:panel_001"] == "hero"
    # Act 2: scene_004 (climax) keeps splash, scene_003 (rising_action) demoted.
    assert importances["scene_003:panel_001"] == "hero"
    assert importances["scene_004:panel_001"] == "splash"
    # Demoted panels keep shape prominence
    demoted = next(p for p in out if p.panel_id == "scene_002:panel_001")
    assert demoted.shape_intent in {"wide", "panorama", "bleed"}
    # Warnings emitted for each demotion
    assert any("scene_002" in w for w in warnings)
    assert any("scene_003" in w for w in warnings)


def test_demote_excess_splashes_keeps_lone_splashes():
    from novel_to_comic.stages.s5_layout_plan import _demote_excess_splashes

    bible = _bible_for_splash_demote()
    # Only one splash per act — nothing should be demoted.
    panels = [
        _splash_panel("scene_001", 1),  # act 1
        _splash_panel("scene_004", 1),  # act 2
    ]
    warnings: list[str] = []
    out = _demote_excess_splashes(panels, bible, warnings)
    assert all(p.importance == "splash" for p in out)
    assert warnings == []


def test_demote_excess_splashes_skipped_when_no_arcs():
    from novel_to_comic.stages.s5_layout_plan import _demote_excess_splashes
    from novel_to_comic.models.story_bible import StoryBible

    bible = StoryBible(
        title="t", author="a", total_scenes=0,
        characters=[], locations=[], scenes=[], narrative_arcs=[], props=[],
    )
    panels = [_splash_panel("scene_001", 1), _splash_panel("scene_001", 2)]
    warnings: list[str] = []
    out = _demote_excess_splashes(panels, bible, warnings)
    assert all(p.importance == "splash" for p in out)


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


def test_scene_planner_caps_completion_after_reasoning_is_disabled(monkeypatch):
    screenplay = Screenplay(
        scene_id="scene_001",
        location_id="loc_001",
        characters=[],
        beats=[ScreenplayBeat(type="action", content="Mara studies the lock.")],
    )
    captured = {}

    async def fake_generate_validated_json(*_args, **kwargs):
        captured.update(kwargs)
        return type("Outcome", (), {
            "value": ([LLMPanelSpec(beat_indices=[1], lighting="daylight")], []),
            "usage_records": [],
        })()

    monkeypatch.setattr(
        "novel_to_comic.stages.s5_layout_plan.generate_validated_json",
        fake_generate_validated_json,
    )

    asyncio.run(_plan_scene_llm(Config(), screenplay, _story_bible(), []))

    assert captured["max_output_tokens"] == 16_384


def test_scene_planner_repairs_parseable_cap_violation_without_paid_retry(monkeypatch):
    from novel_to_comic.usage import ApiResult

    screenplay = Screenplay(
        scene_id="scene_001",
        location_id="loc_001",
        characters=["char_001"],
        beats=[
            ScreenplayBeat(
                type="dialogue",
                character_id="char_001",
                content="One two three four five six seven eight nine ten eleven twelve thirteen.",
            ),
            ScreenplayBeat(
                type="dialogue",
                character_id="char_001",
                content="Fourteen fifteen sixteen seventeen eighteen nineteen twenty twenty-one twenty-two twenty-three twenty-four twenty-five.",
            ),
        ],
    )
    calls = 0

    async def fake_generate_json(**_kwargs):
        nonlocal calls
        calls += 1
        return ApiResult(
            value={
                "panels": [{"beat_indices": [1, 2], "lighting": "daylight"}],
                "narration_decisions": [],
            }
        )

    monkeypatch.setattr(
        "novel_to_comic.clients.structured_call.generate_json",
        fake_generate_json,
    )
    warnings: list[str] = []

    specs, _ = asyncio.run(
        _plan_scene_llm(Config(), screenplay, _story_bible(), warnings)
    )

    assert calls == 1
    assert [spec.beat_indices for spec in specs] == [[1], [2]]
    assert any("repaired locally" in warning for warning in warnings)


def test_plan_estimate_budgets_realistic_structured_output(tmp_path, monkeypatch):
    from novel_to_comic import artifacts

    bible = _bible_for_splash_demote().model_copy(
        update={"scenes": _bible_for_splash_demote().scenes[:1], "total_scenes": 1}
    )
    screenplay_dir = tmp_path / "screenplays"
    screenplay_dir.mkdir()
    (screenplay_dir / "scene_001.json").write_text('{"beats": []}')
    monkeypatch.setattr(artifacts, "read_story_bible_safe", lambda _path: bible)
    output_budgets: list[int] = []

    def fake_estimate_text_cost(_model, _input, output_chars=0):
        output_budgets.append(output_chars)
        return 1.0

    monkeypatch.setattr(
        "novel_to_comic.usage.estimate_text_cost",
        fake_estimate_text_cost,
    )

    assert estimate_cost(Config(), tmp_path, None) == 1.0
    assert output_budgets == [16_384]
