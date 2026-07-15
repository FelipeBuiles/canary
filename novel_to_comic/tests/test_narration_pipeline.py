from novel_to_comic.config import Config
from novel_to_comic.models.layout_plan import LLMNarrationDecisionSpec, PlannedPanel
from novel_to_comic.models.panel import ScreenplayBeat
from novel_to_comic.models.story_bible import Location, StoryBible
from novel_to_comic.layout_planning import sync_narration_into_panels
from novel_to_comic.prompting import build_planned_panel_prompt_spec
from novel_to_comic.stages.s5_layout_plan import _build_narration_decisions


def test_llm_narration_decision_normalizes_common_mode_variants():
    assert LLMNarrationDecisionSpec(
        beat_index=1,
        decision="rendered",
        mode="overlay",
        decision_reason="Overlay the caption on the image.",
    ).mode == "attached_caption"
    assert LLMNarrationDecisionSpec(
        beat_index=1,
        decision="rendered",
        mode="separate panel",
        decision_reason="Give the bridge its own panel.",
    ).mode == "caption_panel"


def test_llm_narration_decision_keeps_unknown_mode_invalid():
    import pytest

    with pytest.raises(ValueError, match="attached_caption"):
        LLMNarrationDecisionSpec(
            beat_index=1,
            decision="rendered",
            mode="speech_bubble",
            decision_reason="Unsupported narration placement.",
        )


def test_narration_fallback_uses_adapted_caption_and_preserves_source_quote():
    beats = [
        ScreenplayBeat(type="action", content="Myop lays down her flowers."),
        ScreenplayBeat(
            type="narration",
            content="Summer ends in that silent moment.",
            source_text="And the summer was over.",
            narration_reason="Authorial closing turn.",
        ),
    ]
    panel = PlannedPanel(
        panel_id="scene_004:panel_001",
        scene_id="scene_004",
        panel_number=1,
        beat_ids=["scene_004:beat_001"],
    )
    warnings: list[str] = []

    decisions = _build_narration_decisions("scene_004", [], [panel], beats, warnings)
    panels = sync_narration_into_panels([panel], decisions)

    assert decisions[0].source_text == "And the summer was over."
    assert decisions[0].caption_text == "Summer ends in that silent moment."
    assert decisions[0].decision == "rendered"
    assert decisions[0].fallback_decision is True
    assert warnings == ['scene_004: fallback narration decision for "Summer ends in that silent moment."']
    assert panels[0].dialogue[0]["type"] == "narration"
    assert panels[0].dialogue[0]["text"] == "Summer ends in that silent moment."
    assert panels[0].dialogue[0]["source_text"] == "And the summer was over."
    assert panels[0].dialogue[0]["source_beat_id"] == "scene_004:beat_002"


def test_llm_narration_decision_attaches_caption_to_panel():
    beats = [
        ScreenplayBeat(type="action", content="Myop lays down her flowers."),
        ScreenplayBeat(
            type="narration",
            content="Summer ends in that silent moment.",
            source_text="And the summer was over.",
            narration_reason="Authorial closing turn.",
        ),
    ]
    panel = PlannedPanel(
        panel_id="scene_004:panel_001",
        scene_id="scene_004",
        panel_number=1,
        beat_ids=["scene_004:beat_001", "scene_004:beat_002"],
    )

    decisions = _build_narration_decisions(
        "scene_004",
        [
            LLMNarrationDecisionSpec(
                beat_index=2,
                decision="rendered",
                mode="attached_caption",
                panel_index=1,
                preferred_zone="bottom",
                decision_reason="The line is the story's final turn.",
            )
        ],
        [panel],
        beats,
        [],
    )
    panels = sync_narration_into_panels([panel], decisions)

    assert decisions[0].preferred_zone == "bottom"
    assert panels[0].has_narration_caption is True
    assert panels[0].preferred_caption_zone == "bottom"
    assert panels[0].dialogue[0]["narration_mode"] == "attached_caption"
    assert panels[0].dialogue[0]["text"] == "Summer ends in that silent moment."
    assert panels[0].dialogue[0]["source_text"] == "And the summer was over."


def test_sync_narration_decisions_removes_duplicate_untracked_caption():
    decision_panel = PlannedPanel(
        panel_id="scene_004:panel_001",
        scene_id="scene_004",
        panel_number=1,
        beat_ids=["scene_004:beat_001", "scene_004:beat_002"],
    )
    duplicate_panel = PlannedPanel(
        panel_id="scene_004:panel_002",
        scene_id="scene_004",
        panel_number=2,
        beat_ids=["scene_004:beat_002", "scene_004:beat_003"],
        dialogue=[
            {
                "character_id": None,
                "text": "And the summer was over.",
                "type": "narration",
                "source_beat_id": None,
                "source_text": None,
                "narration_mode": None,
                "preferred_zone": None,
            }
        ],
        has_narration_caption=True,
        narration_mode="attached_caption",
        preferred_caption_zone="top",
    )
    decisions = [
        _build_narration_decisions(
            "scene_004",
            [
                LLMNarrationDecisionSpec(
                    beat_index=2,
                    decision="rendered",
                    mode="attached_caption",
                    panel_index=1,
                    preferred_zone="bottom",
                    decision_reason="The line is the story's final turn.",
                )
            ],
            [decision_panel, duplicate_panel],
            [
                ScreenplayBeat(type="action", content="Myop lays down her flowers."),
                ScreenplayBeat(
                    type="narration",
                    content="Summer ends in that silent moment.",
                    source_text="And the summer was over.",
                    narration_reason="Authorial closing turn.",
                ),
                ScreenplayBeat(type="action", content="She turns away."),
            ],
            [],
        )[0]
    ]

    panels = sync_narration_into_panels([decision_panel, duplicate_panel], decisions)

    narration_lines = [
        line
        for panel in panels
        for line in panel.dialogue
        if line.get("type") == "narration"
    ]
    assert len(narration_lines) == 1
    assert narration_lines[0]["text"] == "Summer ends in that silent moment."
    assert panels[0].has_narration_caption is True
    assert panels[1].has_narration_caption is False


def test_image_prompt_uses_caption_metadata_without_quote(tmp_path):
    story_bible = StoryBible(
        title="The Flowers",
        author="Alice Walker",
        total_scenes=0,
        characters=[],
        locations=[
            Location(
                id="loc_001",
                name="Woods",
                visual_anchor="dense woods, dark soil, old oak",
                mood="quiet",
            )
        ],
        scenes=[],
        narrative_arcs=[],
        style_notes=None,
        props=[],
    )
    panel = PlannedPanel(
        panel_id="scene_004:panel_001",
        scene_id="scene_004",
        panel_number=1,
        background_description="a child stands beneath an old oak",
        shot_type="wide",
        has_narration_caption=True,
        narration_mode="attached_caption",
        preferred_caption_zone="top",
        dialogue=[
            {
                "character_id": None,
                "text": "And the summer was over.",
                "type": "narration",
                "source_beat_id": "scene_004:beat_002",
            }
        ],
    )

    prompt = build_planned_panel_prompt_spec(Config(), tmp_path, panel, story_bible)

    assert prompt.has_narration_caption is True
    assert prompt.preferred_caption_zone == "top"
    assert "quiet negative space near the top" in prompt.full_prompt
    assert "And the summer was over." not in prompt.full_prompt
    # The no-draw-caption-box note is a system constraint generated by the
    # canonical projection (Slice 02), not stored in full_prompt.
    from novel_to_comic.generation_prompt import render_canonical_body
    assert "do not draw caption boxes" in render_canonical_body(prompt)
