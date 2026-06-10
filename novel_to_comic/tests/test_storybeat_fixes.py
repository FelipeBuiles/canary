"""Regression tests for the story-extraction → panel → layout review fixes."""

from novel_to_comic.layout_planning import (
    LayoutPlan,
    repaginate_layout_plan,
)
from novel_to_comic.models.layout_plan import (
    LayoutPlanMetadata,
    LLMNarrationDecisionSpec,
    LLMPanelSpec,
    PlannedPanel,
)
from novel_to_comic.models.panel import Screenplay, ScreenplayBeat
from novel_to_comic.models.story_bible import Location, Scene, StoryBible
from novel_to_comic.stages.s1_extract import _find_quote_position, _write_scene_files
from novel_to_comic.stages.s4_screenplay import _annotate_transition_beats
from novel_to_comic.stages.s5_layout_plan import (
    _aspect_for_shape,
    _cross_scene_transition_pass,
    _dedupe_adjacent_panels,
    _importance_aware_paginate,
    _llm_spec_to_planned_panel,
    _normalize_spec_order,
    _split_run_evenly,
    _stabilize_character_positions,
    _target_panel_count,
    _validate_llm_specs,
)


def _panel(num: int, scene_id: str = "scene_001", **overrides) -> PlannedPanel:
    base = {
        "panel_id": f"{scene_id}:panel_{num:03d}",
        "scene_id": scene_id,
        "panel_number": num,
        "beat_ids": [f"{scene_id}:beat_{num:03d}"],
        "shot_type": "wide",
        "characters_present": ["char_001"],
        "character_actions": {"char_001": "stands still"},
        "background_description": "flat plain",
    }
    base.update(overrides)
    return PlannedPanel(**base)


# ── Stage 1: quote anchoring ─────────────────────────────────────────────────

def test_find_quote_position_respects_start_offset():
    text = "The next morning was cold. Much happened. The next morning was cold again."
    first = _find_quote_position(text, "The next morning was cold")
    later = _find_quote_position(text, "The next morning was cold", start=first + 1)
    assert first == 0
    assert later > first


def test_find_quote_position_fuzzy_recovers_from_early_typo():
    text = "Meanwhile she walked slowly toward the harbor gates that evening, alone."
    quote = "she walkd slowly toward the harbor gates that evening"  # typo in prefix
    pos = _find_quote_position(text, quote)
    assert pos != -1
    assert abs(pos - text.index("she walked")) <= 5


def test_find_quote_position_fuzzy_rejects_weak_matches():
    text = "An entirely different passage about ships and storms on the open sea."
    quote = "the quiet library at midnight held seventeen sleeping cats"
    assert _find_quote_position(text, quote) == -1


def _scene(sid: str, quote: str) -> Scene:
    return Scene(
        id=sid,
        chapter=1,
        title=f"Scene {sid}",
        location_id="loc_001",
        character_ids=[],
        summary=f"Summary of {sid}.",
        scene_type="action",
        narrative_beat="rising_action",
        source_start_quote=quote,
    )


def test_write_scene_files_out_of_order_anchor_falls_back_to_summary(tmp_path):
    novel = (
        "AAA scene one opens with a long passage of morning light over the bay. "
        "BBB scene two follows with rain hammering the rooftops until dusk."
    )
    bible = StoryBible(
        title="t", author="a", total_scenes=2,
        characters=[],
        locations=[Location(id="loc_001", name="L", visual_anchor="x", mood="m")],
        scenes=[
            _scene("scene_001", "BBB scene two follows with rain hammering"),
            _scene("scene_002", "AAA scene one opens with a long passage"),
        ],
        narrative_arcs=[],
    )
    _write_scene_files(bible, novel, tmp_path)

    # scene_002's quote only exists BEFORE scene_001's anchor -> summary fallback.
    assert (tmp_path / "scene_002.txt").read_text().startswith("[Scene:")
    assert "BBB scene two" in (tmp_path / "scene_001.txt").read_text()


# ── Stage 4: transition annotation ───────────────────────────────────────────

def test_annotate_transitions_preserves_model_classification():
    sp = Screenplay(
        scene_id="scene_001", location_id="loc_001", characters=[],
        beats=[ScreenplayBeat(type="transition", content="Fade to white.",
                              transition_type="match_cut")],
    )
    out = _annotate_transition_beats(sp)
    assert out.beats[0].transition_type == "match_cut"


def test_annotate_transitions_fills_fade_as_hard_cut():
    sp = Screenplay(
        scene_id="scene_001", location_id="loc_001", characters=[],
        beats=[ScreenplayBeat(type="transition", content="Fade to black.")],
    )
    out = _annotate_transition_beats(sp)
    assert out.beats[0].transition_type == "hard_cut"


# ── Stage 5: shapes, targets, ordering, thought beats ────────────────────────

def test_panorama_aspect_is_wide_not_tall():
    aspect, aspect_range = _aspect_for_shape("panorama")
    assert aspect > 1.5
    assert aspect_range[0] > 1.5


def test_target_panel_count_never_exceeds_beat_count_floor():
    assert _target_panel_count(8, 2) <= 2
    assert _target_panel_count(8, 12) == 4


def test_normalize_spec_order_sorts_beats_and_remaps_narration():
    specs = [
        LLMPanelSpec(beat_indices=[5, 4]),
        LLMPanelSpec(beat_indices=[1, 2, 3]),
    ]
    narration = [
        LLMNarrationDecisionSpec(
            beat_index=4, decision="rendered", mode="attached_caption",
            panel_index=1, decision_reason="r",
        )
    ]
    new_specs, new_narration = _normalize_spec_order(specs, narration)
    assert new_specs[0].beat_indices == [1, 2, 3]
    assert new_specs[1].beat_indices == [4, 5]
    # The narration's target panel moved from slot 1 to slot 2.
    assert new_narration[0].panel_index == 2


def test_thought_beats_count_toward_dialogue_cap():
    beats = [
        ScreenplayBeat(type="thought", character_id="char_001", content=f"t{i}")
        for i in range(5)
    ]
    try:
        _validate_llm_specs([LLMPanelSpec(beat_indices=[1, 2, 3, 4, 5])], beats)
    except ValueError as exc:
        assert "dialogue beats" in str(exc)
    else:
        raise AssertionError("expected dialogue-cap violation for thought beats")


def test_thought_beat_becomes_thought_dialogue_line():
    beats = [
        ScreenplayBeat(type="thought", character_id="char_001", content="What if..."),
    ]
    bible = StoryBible(
        title="t", author="a", total_scenes=0,
        characters=[], locations=[], scenes=[], narrative_arcs=[],
    )
    panel = _llm_spec_to_planned_panel(
        "scene_001", 1, LLMPanelSpec(beat_indices=[1]), beats, bible,
    )
    assert panel.dialogue[0]["type"] == "thought"
    assert panel.dialogue_load == 1


# ── Stage 5: dedupe + staging + transitions ──────────────────────────────────

def test_dedupe_skips_merge_when_dialogue_would_overflow():
    lines = [
        {"character_id": "char_001", "text": f"line {i}", "type": "speech"}
        for i in range(3)
    ]
    p1 = _panel(1, dialogue=list(lines))
    p2 = _panel(2, dialogue=list(lines))
    warnings: list[str] = []
    kept, _ = _dedupe_adjacent_panels([p1, p2], [], warnings)
    assert len(kept) == 2


def test_stabilize_character_positions_keeps_sides_across_panels():
    p1 = _panel(1, characters_present=["char_a", "char_b"])
    p2 = _panel(2, characters_present=["char_b", "char_a"])
    solo = _panel(3, characters_present=["char_b"])
    _stabilize_character_positions([p1, p2, solo])
    assert p1.character_positions == p2.character_positions
    assert solo.character_positions == {"char_b": "center"}


def test_cross_scene_state_change_is_hard_cut():
    p1 = _panel(1, scene_id="scene_001")
    p2 = _panel(1, scene_id="scene_002")
    locations = {"scene_001": "loc_001", "scene_002": "loc_001"}
    states = {"scene_001": "loc_001_pre", "scene_002": "loc_001_post"}
    out = _cross_scene_transition_pass([p1, p2], locations, states)
    assert out[0].transition_out == "hard_cut"
    assert out[1].transition_in == "hard_cut"


def test_cross_scene_same_location_and_state_is_smooth():
    p1 = _panel(1, scene_id="scene_001")
    p2 = _panel(1, scene_id="scene_002")
    locations = {"scene_001": "loc_001", "scene_002": "loc_001"}
    out = _cross_scene_transition_pass([p1, p2], locations, {})
    assert out[0].transition_out == "smooth_continuation"


# ── Pagination ───────────────────────────────────────────────────────────────

def test_split_run_evenly_avoids_orphan_pages():
    run = [_panel(i) for i in range(1, 8)]  # 7 panels, max 6
    chunks = _split_run_evenly(run, 6)
    assert [len(c) for c in chunks] == [4, 3]


def test_mid_scene_hero_starts_its_own_page():
    panels = [_panel(i) for i in range(1, 6)]
    panels[3].importance = "hero"
    pages = _importance_aware_paginate("scene_001", panels, 1, 6)
    assert len(pages) == 2
    assert pages[1].panel_ids[0] == panels[3].panel_id
    assert pages[1].layout_template == "hero_top_2"


def test_paginate_clamps_chunks_to_template_capacity():
    panels = [_panel(i) for i in range(1, 9)]  # 8 standard panels
    pages = _importance_aware_paginate("scene_001", panels, 1, 12)
    for page in pages:
        assert len(page.panel_ids) <= 6
        # No two panels may share the same slot region.
        regions = [tuple(g.region) for g in page.panel_geometries]
        assert len(regions) == len(set(regions))


def test_page_rhythm_uses_narrative_beat_not_hero_presence():
    panels = [_panel(i) for i in range(1, 4)]
    panels[0].importance = "hero"
    regular = _importance_aware_paginate("scene_001", panels, 2, 6, scene_beat="rising_action")
    assert all(p.page_rhythm_role == "regular" for p in regular)
    climax = _importance_aware_paginate(
        "scene_001", [_panel(i) for i in range(1, 4)], 2, 6, scene_beat="climax",
    )
    assert all(p.page_rhythm_role == "climax" for p in climax)


def test_repaginate_uses_matching_layout_template():
    panels = [_panel(1), _panel(2)]
    plan = LayoutPlan(
        metadata=LayoutPlanMetadata(
            source_screenplay_hash="x", max_panels_per_page=6,
        ),
        planned_panels=panels,
        planned_pages=[],
    )
    out = repaginate_layout_plan(plan, panels_per_page=2)
    page = out.planned_pages[0]
    assert page.layout_template == "stacked_2"
    # Second panel occupies the lower half, not a quarter of an oversized grid.
    assert page.panel_geometries[1].region == [0.0, 0.5, 1.0, 0.5]
