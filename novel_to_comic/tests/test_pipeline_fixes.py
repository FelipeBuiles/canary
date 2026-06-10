"""Regression tests for the draw/cast/prompting review fixes:
per-state location plates, prompt-currency consolidation, word-boundary
anchor filtering, scene interleaving, and the clean-path cascade."""

import json
from pathlib import Path

from novel_to_comic.config import Config
from novel_to_comic.models.layout_plan import PlannedPanel
from novel_to_comic.models.prompt import ImagePrompt
from novel_to_comic.models.story_bible import Location, LocationState, Scene, StoryBible
from novel_to_comic.prompt_assembly import ensure_current_panel_prompt
from novel_to_comic.prompting import (
    IMAGE_PROMPT_VERSION,
    _filter_location_anchor_for_panel,
    build_planned_panel_prompt_spec,
)
from novel_to_comic.stages import clean_cascade
from novel_to_comic.stages.s3_cast import _location_plate_jobs
from novel_to_comic.stages.s7_draw import _interleave_by_scene, _plate_ref_path


def _stateful_location() -> Location:
    return Location(
        id="loc_001",
        name="Seattle Street",
        visual_anchor="night, outdoors, brick apartment facade, streetlamp",
        mood="tense",
        states=[
            LocationState(
                id="loc_001_pre",
                name="Pre-collapse",
                visual_anchor="night, outdoors, brick apartment facade, parked cars",
            ),
            LocationState(
                id="loc_001_post",
                name="Post-collapse",
                visual_anchor="night, flattened dirt, rubble, distant fire",
            ),
        ],
    )


# ── Per-state location plates ────────────────────────────────────────────────

def test_location_plate_jobs_cover_default_and_states():
    jobs = _location_plate_jobs(_stateful_location())
    assert [(stem, state_id) for stem, _anchor, state_id in jobs] == [
        ("loc_001", None),
        ("loc_001_pre", "loc_001_pre"),
        ("loc_001_post", "loc_001_post"),
    ]
    assert jobs[2][1] == "night, flattened dirt, rubble, distant fire"


def test_plate_ref_path_prefers_state_plate(tmp_path):
    plates = tmp_path / "plates"
    plates.mkdir()
    (plates / "loc_001.png").write_bytes(b"default")
    (plates / "loc_001_post.png").write_bytes(b"post")

    assert _plate_ref_path(tmp_path, "loc_001", "loc_001_post") == plates / "loc_001_post.png"
    # Missing state plate falls back to the default plate.
    assert _plate_ref_path(tmp_path, "loc_001", "loc_001_pre") == plates / "loc_001.png"
    assert _plate_ref_path(tmp_path, "loc_001", None) == plates / "loc_001.png"
    assert _plate_ref_path(tmp_path, "loc_999", None) is None


def test_image_prompt_carries_effective_location_state(tmp_path):
    bible = StoryBible(
        title="t", author="a", total_scenes=1,
        characters=[],
        locations=[_stateful_location()],
        scenes=[
            Scene(
                id="scene_001", chapter=1, title="T",
                location_id="loc_001", location_state_id="loc_001_pre",
                character_ids=[], summary="s", scene_type="action",
                narrative_beat="rising_action", source_start_quote="q",
            )
        ],
        narrative_arcs=[],
    )
    scene_default = PlannedPanel(
        panel_id="scene_001:panel_001", scene_id="scene_001", panel_number=1,
    )
    panel_override = PlannedPanel(
        panel_id="scene_001:panel_002", scene_id="scene_001", panel_number=2,
        location_state_id="loc_001_post",
    )

    assert build_planned_panel_prompt_spec(
        Config(), tmp_path, scene_default, bible
    ).location_state_id == "loc_001_pre"
    assert build_planned_panel_prompt_spec(
        Config(), tmp_path, panel_override, bible
    ).location_state_id == "loc_001_post"


# ── Prompt currency consolidation ────────────────────────────────────────────

def test_ensure_current_panel_prompt_rebuilds_stale_and_keeps_current(tmp_path):
    bible = StoryBible(
        title="t", author="a", total_scenes=0,
        characters=[], locations=[], scenes=[], narrative_arcs=[],
    )
    panel = PlannedPanel(
        panel_id="scene_001:panel_001", scene_id="scene_001", panel_number=1,
        mood="tense",
    )
    prompt_path = tmp_path / "direct" / "scene_001" / "panel_001.json"
    prompt_path.parent.mkdir(parents=True)
    stale = ImagePrompt(
        prompt_version=1,
        planned_panel_id="scene_001:panel_001",
        scene_id="scene_001", panel_number=1,
        full_prompt="old", width=768, height=1024, steps=8,
    )
    prompt_path.write_text(stale.model_dump_json())

    rebuilt = ensure_current_panel_prompt(Config(), tmp_path, panel, bible)
    assert rebuilt.prompt_version == IMAGE_PROMPT_VERSION
    assert json.loads(prompt_path.read_text())["prompt_version"] == IMAGE_PROMPT_VERSION

    # A current stored prompt is returned as-is (user edits survive).
    data = json.loads(prompt_path.read_text())
    data["mood"] = "user-edited mood"
    prompt_path.write_text(json.dumps(data))
    kept = ensure_current_panel_prompt(Config(), tmp_path, panel, bible)
    assert kept.mood == "user-edited mood"


# ── Word-boundary anchor filtering ───────────────────────────────────────────

def test_anchor_filter_uses_word_boundaries():
    # "riverbed" must NOT be dropped by the "bed"-family interior tokens when
    # the panel is clearly exterior.
    anchor = "day, outdoors, riverbed, wild ferns, indoors"
    background = "wide shot of the stream cutting through the forest"
    filtered = _filter_location_anchor_for_panel(anchor, background)
    assert "riverbed" in filtered
    assert "indoors" not in filtered


def test_anchor_filter_still_drops_street_furniture_indoors():
    anchor = "night, cold, bicycle rack, moped, stop sign"
    background = "rumpled bedside blanket in a dim bedroom"
    filtered = _filter_location_anchor_for_panel(anchor, background)
    assert "bicycle rack" not in filtered
    assert "moped" not in filtered
    assert "night" in filtered and "cold" in filtered


# ── Draw batching ────────────────────────────────────────────────────────────

def test_interleave_by_scene_round_robins_and_preserves_panel_order():
    files = [
        Path(f"direct/scene_001/panel_{i:03d}.json") for i in range(1, 4)
    ] + [
        Path(f"direct/scene_002/panel_{i:03d}.json") for i in range(1, 3)
    ]
    interleaved = _interleave_by_scene(files)
    assert [str(p.parent.name) + "/" + p.stem for p in interleaved] == [
        "scene_001/panel_001",
        "scene_002/panel_001",
        "scene_001/panel_002",
        "scene_002/panel_002",
        "scene_001/panel_003",
    ]


# ── Clean-path cascade ───────────────────────────────────────────────────────

def test_clean_cascade_runs_to_end_of_pipeline(tmp_path):
    assert clean_cascade(tmp_path, "draw") == [
        tmp_path / "draw", tmp_path / "compose", tmp_path / "exports",
    ]
    assert clean_cascade(tmp_path, "samples")[0] == tmp_path / "samples"
    assert clean_cascade(tmp_path, "samples")[-1] == tmp_path / "exports"
