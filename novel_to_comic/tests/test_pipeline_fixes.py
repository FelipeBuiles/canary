"""Regression tests for the draw/cast/prompting review fixes:
per-state location plates, prompt-currency consolidation, word-boundary
anchor filtering, scene interleaving, and the clean-path cascade."""

import json
from pathlib import Path

from novel_to_comic.config import Config
from novel_to_comic.models.layout_plan import PlannedPanel
from novel_to_comic.models.prompt import ImagePrompt
from novel_to_comic.models.appearance import AppearanceState, StateActivation, StoryPosition
from novel_to_comic.models.story_bible import Character, Location, Scene, StoryBible
from novel_to_comic.prompt_assembly import ensure_current_panel_prompt
from novel_to_comic.prompting import (
    IMAGE_PROMPT_VERSION,
    _filter_location_anchor_for_panel,
    build_planned_panel_prompt_spec,
)
from novel_to_comic.stages import clean_cascade
from novel_to_comic.stages.s3_cast import (
    _character_ref_clean_text_prompt,
    _character_ref_prompt,
    _location_plate_jobs,
)
from novel_to_comic.stages.s7_draw import _interleave_by_scene, _plate_ref_path


def _stateful_location() -> Location:
    """Base anchor = pre-collapse; one alternate state (post-collapse) that
    activates partway through scene_001 (at beat 3)."""
    return Location(
        id="loc_001",
        name="Seattle Street",
        visual_anchor="night, outdoors, brick apartment facade, streetlamp",
        mood="tense",
        appearance_states=[
            AppearanceState(
                id="loc_001_post",
                label="Post-collapse",
                visual_anchor="night, flattened dirt, rubble, distant fire",
                visually_significant=True,
            ),
        ],
        appearance_timeline=[
            StateActivation(
                state_id="loc_001_post",
                at=StoryPosition(scene_id="scene_001", beat=3),
            ),
        ],
    )


# ── Per-state location plates ────────────────────────────────────────────────

def test_location_plate_jobs_cover_default_and_states():
    jobs = _location_plate_jobs(_stateful_location())
    assert [(stem, state_id) for stem, _anchor, state_id in jobs] == [
        ("loc_001", None),
        ("loc_001_post", "loc_001_post"),
    ]
    assert jobs[1][1] == "night, flattened dirt, rubble, distant fire"


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


def test_image_prompt_resolves_location_state_from_timeline(tmp_path):
    """Location state is resolved per panel from the location's
    appearance_timeline + the panel's beat position — no per-panel/scene tag."""
    bible = StoryBible(
        title="t", author="a", total_scenes=1,
        characters=[],
        locations=[_stateful_location()],
        scenes=[
            Scene(
                id="scene_001", chapter=1, title="T",
                location_id="loc_001",
                character_ids=[], summary="s", scene_type="action",
                narrative_beat="rising_action", source_start_quote="q",
            )
        ],
        narrative_arcs=[],
    )
    # Beats 1-2 are before the post-collapse activation (beat 3) → base look.
    early = PlannedPanel(
        panel_id="scene_001:panel_001", scene_id="scene_001", panel_number=1,
        beat_ids=["scene_001:beat_001", "scene_001:beat_002"],
    )
    # Beats 3-4 are at/after the activation → post-collapse state.
    late = PlannedPanel(
        panel_id="scene_001:panel_002", scene_id="scene_001", panel_number=2,
        beat_ids=["scene_001:beat_003", "scene_001:beat_004"],
    )

    assert build_planned_panel_prompt_spec(
        Config(), tmp_path, early, bible
    ).location_state_id is None
    assert build_planned_panel_prompt_spec(
        Config(), tmp_path, late, bible
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


def test_clean_cascade_targets_real_artifact_dirs(tmp_path):
    """The cascade must use artifact DIRECTORY names, not stage names.

    The adapt stage writes to ``screenplays/`` but the cascade once listed the
    stage name ``adapt``, so re-running an upstream stage cleaned a nonexistent
    ``adapt/`` dir and left stale screenplays behind — silently corrupting the
    downstream chain after a re-extract.
    """
    from novel_to_comic.stages import REGISTRY

    cascade = clean_cascade(tmp_path, "screenplays")
    assert tmp_path / "screenplays" in cascade
    assert tmp_path / "adapt" not in cascade
    # The adapt stage's own outputs must be inside what it cleans on re-run.
    adapt_outputs = set(REGISTRY["adapt"].outputs(tmp_path))
    assert adapt_outputs <= set(REGISTRY["adapt"].clean_paths(tmp_path))


# ── Cast appearance-state ref sheets ─────────────────────────────────────────

def _girl_and_stumps() -> tuple[StoryBible, Character, AppearanceState]:
    char = Character(
        id="char_001",
        name="The Miller's Daughter",
        visual_anchor="1woman, long blonde hair, blue eyes, peasant dress, bare feet",
        age_range="20s",
        gender="female",
        distinguishing_features=["long blonde hair"],
        default_outfit="simple peasant dress",
        relationships=[],
        first_appearance_scene="scene_001",
    )
    stumps = AppearanceState(
        id="stumps",
        label="Maimed",
        visual_anchor="1woman, long blonde hair, blue eyes, peasant dress, arm stumps, bandaged ends",
        visually_significant=True,
        continuity_guard="She has no hands; both arms end in bandaged stumps; never depict her gripping",
    )
    bible = StoryBible(
        title="T", author="A", total_scenes=1,
        characters=[char], locations=[], scenes=[], narrative_arcs=[], props=[],
    )
    return bible, char, stumps


def test_state_ref_prompt_drops_hand_pose_and_locks_anatomy():
    """A state sheet must not force a 'one hand raised' pose, and must demand the
    altered body be consistent across all quadrants (carrying the guard)."""
    bible, char, stumps = _girl_and_stumps()
    state_char = char.model_copy(update={"visual_anchor": stumps.visual_anchor})
    prompt = _character_ref_prompt(Config(), bible, state_char, "", stumps)

    assert "one hand raised" not in prompt.lower()
    assert "mid-gesture" in prompt.lower()
    assert "specific altered state" in prompt.lower()
    assert "never depict her gripping" in prompt  # guard injected

    # The canonical (base) sheet is unchanged — still uses the hand-gesture pose.
    base = _character_ref_prompt(Config(), bible, char, "")
    assert "one hand raised" in base.lower()
    assert "altered state" not in base.lower()


def test_state_ref_clean_text_prompt_drops_hand_pose():
    bible, char, stumps = _girl_and_stumps()
    state_char = char.model_copy(update={"visual_anchor": stumps.visual_anchor})
    prompt = _character_ref_clean_text_prompt(Config(), state_char, "", stumps)
    assert "one hand raised" not in prompt.lower()
    assert "mid-gesture" in prompt.lower()
    assert "altered state" in prompt.lower()
