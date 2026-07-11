"""Slice 02 — Canonical Prompt IR and Protected Verbatim Anchors.

Tests that:
- Each active character/location/prop anchor reaches the canonical rendered
  projection byte-for-byte, longer than the old 120/180/220 caps, and never
  shortened, filtered, underscore-replaced, translated, or LLM-rewritten.
- Exactly one self-contained appearance anchor resolves per active entity
  (base when no state active; the state's anchor otherwise). Base and state
  anchors are never concatenated; base default_outfit never rides beside an
  active state.
- System constraints (count, one-body, single-instant, no-lettering, crop
  policy, appearance locks, unified canvas) are generated, typed, and
  non-editable. They survive manual and instructed edits; user addenda live
  in a separate field.
- The LLM visual-brief source contains no anchor text or system constraints —
  it owns only scene direction.
"""

import sys
from pathlib import Path

workspace_root = str(Path(__file__).parent.parent.parent)
if workspace_root not in sys.path:
    sys.path.insert(0, workspace_root)

from novel_to_comic.config import Config  # noqa: E402
from novel_to_comic.models.appearance import (  # noqa: E402
    AppearanceState,
    StateActivation,
    StoryPosition,
    Transition,
)
from novel_to_comic.models.layout_plan import PlannedPanel  # noqa: E402
from novel_to_comic.models.story_bible import (  # noqa: E402
    Character,
    Location,
    Prop,
    Scene,
    StoryBible,
)
from novel_to_comic.prompting import build_planned_panel_prompt_spec  # noqa: E402

# A sentinel longer than every old cap (120 / 180 / 220).  If this string
# survives to the canonical projection unchanged, the old shorten / clean
# pipeline is gone for protected anchors.
_CHAR_SENTINEL = (
    "SENTINEL_CHARACTER_ANCHOR_" * 8  # ~240 chars — over the old 220 cap
    + " distinct sharp angular jawline with a faint pale scar running diagonally across the left cheekbone"
)
_LOC_SENTINEL = (
    "SENTINEL_LOCATION_ANCHOR_" * 8  # ~208 chars — over the old 180 cap
    + " crumbling limestone walls veined with dark moss and amber lichen under a sagging timber frame"
)
_PROP_SENTINEL = (
    "SENTINEL_PROP_ANCHOR_" * 8  # ~176 chars — over the old 120 cap
    + " ornate iron key with a dragon-headed bow and three jagged teeth along the blade"
)


def _bible_with_sentinels() -> StoryBible:
    return StoryBible(
        title="t",
        author="a",
        total_scenes=1,
        characters=[
            Character(
                id="char_001",
                name="Sera",
                visual_anchor=_CHAR_SENTINEL,
                age_range="30s",
                gender="female",
                distinguishing_features=[],
                default_outfit="",
                relationships=[],
                first_appearance_scene="scene_001",
            )
        ],
        locations=[
            Location(
                id="loc_001",
                name="The Old Hall",
                visual_anchor=_LOC_SENTINEL,
                mood="gloomy",
            )
        ],
        scenes=[
            Scene(
                id="scene_001",
                chapter=1,
                title="t",
                location_id="loc_001",
                character_ids=["char_001"],
                summary="s",
                scene_type="action",
                narrative_beat="rising_action",
                source_start_quote="q",
            )
        ],
        narrative_arcs=[],
        props=[
            Prop(
                id="prop_001",
                name="Dragon Key",
                visual_anchor=_PROP_SENTINEL,
                first_appearance_scene="scene_001",
            )
        ],
    )


def _base_panel() -> PlannedPanel:
    return PlannedPanel(
        panel_id="scene_001:panel_001",
        scene_id="scene_001",
        panel_number=1,
        beat_ids=["scene_001:beat_001"],
        shot_type="medium",
        camera_angle="eye-level",
        characters_present=["char_001"],
        character_actions={"char_001": "holds the Dragon Key tightly"},
        character_positions={"char_001": "center"},
        background_description="The old hall interior",
        lighting="dim firelight",
        mood="tense",
    )


# ── PromptAnchor model ─────────────────────────────────────────────────────


class TestPromptAnchorModel:
    def test_anchor_has_kind_entity_id_name_text(self):
        from novel_to_comic.models.prompt import PromptAnchor

        anchor = PromptAnchor(
            kind="character",
            entity_id="char_001",
            name="Sera",
            text=_CHAR_SENTINEL,
        )
        assert anchor.kind == "character"
        assert anchor.entity_id == "char_001"
        assert anchor.name == "Sera"
        assert anchor.text == _CHAR_SENTINEL
        assert anchor.appearance_state_id is None

    def test_anchor_accepts_appearance_state_id(self):
        from novel_to_comic.models.prompt import PromptAnchor

        anchor = PromptAnchor(
            kind="character",
            entity_id="char_001",
            name="Sera",
            appearance_state_id="stumps",
            text="arm stumps",
        )
        assert anchor.appearance_state_id == "stumps"


# ── Sentinel anchors reach the projection verbatim ─────────────────────────


class TestSentinelAnchorsPreservedVerbatim:
    def test_character_anchor_reaches_projection_verbatim(self, tmp_path):
        # Create the prop ref so the prop anchor attaches.
        ref = tmp_path / "refs" / "props" / "prop_001" / "ref.png"
        ref.parent.mkdir(parents=True)
        ref.write_bytes(b"k")
        prompt = build_planned_panel_prompt_spec(
            Config(), tmp_path, _base_panel(), _bible_with_sentinels()
        )

        # The verbatim anchor lives on the PromptSubject.
        assert prompt.subjects[0].identity == _CHAR_SENTINEL

    def test_location_anchor_reaches_projection_verbatim(self, tmp_path):
        prompt = build_planned_panel_prompt_spec(
            Config(), tmp_path, _base_panel(), _bible_with_sentinels()
        )
        # The location anchor lives in the new anchors list, verbatim.
        loc_anchors = [a for a in prompt.anchors if a.kind == "location"]
        assert len(loc_anchors) == 1
        assert loc_anchors[0].text == _LOC_SENTINEL

    def test_prop_anchor_reaches_projection_verbatim(self, tmp_path):
        ref = tmp_path / "refs" / "props" / "prop_001" / "ref.png"
        ref.parent.mkdir(parents=True)
        ref.write_bytes(b"k")
        prompt = build_planned_panel_prompt_spec(
            Config(), tmp_path, _base_panel(), _bible_with_sentinels()
        )
        prop_anchors = [a for a in prompt.anchors if a.kind == "prop"]
        assert len(prop_anchors) == 1
        assert prop_anchors[0].text == _PROP_SENTINEL

    def test_character_identity_not_shortened(self, tmp_path):
        """The identity must survive full — over the old 220 cap."""
        prompt = build_planned_panel_prompt_spec(
            Config(), tmp_path, _base_panel(), _bible_with_sentinels()
        )
        assert len(prompt.subjects[0].identity) >= len(_CHAR_SENTINEL)

    def test_location_anchor_not_shortened(self, tmp_path):
        prompt = build_planned_panel_prompt_spec(
            Config(), tmp_path, _base_panel(), _bible_with_sentinels()
        )
        loc = [a for a in prompt.anchors if a.kind == "location"][0]
        assert len(loc.text) >= len(_LOC_SENTINEL)

    def test_sentinels_appear_in_canonical_projection(self, tmp_path):
        """The canonical prompt-body projection must contain every sentinel
        as an exact substring."""
        from novel_to_comic.generation_prompt import render_canonical_body

        ref = tmp_path / "refs" / "props" / "prop_001" / "ref.png"
        ref.parent.mkdir(parents=True)
        ref.write_bytes(b"k")
        prompt = build_planned_panel_prompt_spec(
            Config(), tmp_path, _base_panel(), _bible_with_sentinels()
        )
        body = render_canonical_body(prompt)

        assert _CHAR_SENTINEL in body
        assert _LOC_SENTINEL in body
        assert _PROP_SENTINEL in body


# ── Exactly one self-contained anchor per active entity ────────────────────


def _bible_with_states() -> StoryBible:
    """A character with a minor state, a significant state, and a restored
    state — plus a location with a post-collapse state."""
    char = Character(
        id="char_001",
        name="Carl",
        visual_anchor=(
            "1man, adult male, short brown hair, lean build, "
            "wearing a worn leather jacket and faded jeans"
        ),
        age_range="late 20s",
        gender="male",
        distinguishing_features=[],
        default_outfit="A worn leather jacket and faded jeans.",
        relationships=[],
        first_appearance_scene="scene_001",
        appearance_states=[
            AppearanceState(
                id="formal",
                label="Formal wear",
                # Minor alternate outfit — not visually significant.
                visual_anchor="1man, adult male, short brown hair, lean build, wearing a tailored black tuxedo with a bow tie",
            ),
            AppearanceState(
                id="injured",
                label="Injured",
                visually_significant=True,
                visual_anchor="1man, adult male, short brown hair, lean build, wearing a worn leather jacket, left arm in a bloodied sling, bruised face",
                continuity_guard="Left arm is injured and immobilized; never show him using both hands freely",
            ),
            AppearanceState(
                id="restored",
                label="Restored",
                visually_significant=True,
                visual_anchor="1man, adult male, short brown hair, lean build, wearing a worn leather jacket, both arms healed and healthy",
            ),
        ],
        appearance_timeline=[
            StateActivation(state_id="formal", at=StoryPosition(scene_id="scene_002")),
            StateActivation(state_id="injured", at=StoryPosition(scene_id="scene_003")),
            StateActivation(state_id="restored", at=StoryPosition(scene_id="scene_004")),
        ],
    )
    loc = Location(
        id="loc_001",
        name="Seattle Street",
        visual_anchor="night, outdoors, snow, brick apartment facade, streetlamp, parked cars, sidewalk",
        mood="apocalyptic",
        appearance_states=[
            AppearanceState(
                id="loc_001_post",
                label="Post-collapse aftermath",
                visually_significant=True,
                visual_anchor="night, flattened dirt, rubble, distant fire, bicycle rack, moped, stop sign",
            ),
        ],
        appearance_timeline=[
            StateActivation(
                state_id="loc_001_post",
                at=StoryPosition(scene_id="scene_001", beat=4),
                transition=Transition(label="the block collapses"),
            ),
        ],
    )
    scenes = [
        Scene(
            id=f"scene_{i:03d}",
            chapter=1,
            title="t",
            location_id="loc_001",
            character_ids=["char_001"],
            summary="s",
            scene_type="action",
            narrative_beat="rising_action",
            source_start_quote="q",
        )
        for i in range(1, 6)
    ]
    return StoryBible(
        title="DCC",
        author="Matt Dinniman",
        total_scenes=5,
        characters=[char],
        locations=[loc],
        scenes=scenes,
        narrative_arcs=[],
        props=[],
    )


class TestExactlyOneSelfContainedAnchor:
    def test_base_look_no_state(self, tmp_path):
        """scene_001: base look — identity == character.visual_anchor verbatim,
        no default_outfit concatenated."""
        bible = _bible_with_states()
        panel = PlannedPanel(
            panel_id="scene_001:panel_001",
            scene_id="scene_001",
            panel_number=1,
            beat_ids=["scene_001:beat_001"],
            shot_type="medium",
            camera_angle="eye-level",
            characters_present=["char_001"],
            character_actions={"char_001": "stands"},
            character_positions={"char_001": "center"},
            background_description="dark street",
            lighting="cold blue",
            mood="tense",
        )
        prompt = build_planned_panel_prompt_spec(Config(), tmp_path, panel, bible)
        char = bible.characters[0]

        assert prompt.subjects[0].identity == char.visual_anchor
        # The default_outfit is NOT concatenated beside the base anchor.
        assert "A worn leather jacket and faded jeans" not in prompt.subjects[0].identity
        # State id is absent.
        assert prompt.subjects[0].appearance_state_id is None

    def test_minor_state_uses_state_anchor(self, tmp_path):
        """scene_002: minor formal state — identity == the formal state's
        self-contained anchor, not the base anchor."""
        bible = _bible_with_states()
        panel = PlannedPanel(
            panel_id="scene_002:panel_001",
            scene_id="scene_002",
            panel_number=1,
            beat_ids=["scene_002:beat_001"],
            shot_type="medium",
            camera_angle="eye-level",
            characters_present=["char_001"],
            character_actions={"char_001": "adjusts his bow tie"},
            character_positions={"char_001": "center"},
            background_description="ballroom",
            lighting="warm chandeliers",
            mood="elegant",
        )
        prompt = build_planned_panel_prompt_spec(Config(), tmp_path, panel, bible)

        formal = next(s for s in bible.characters[0].appearance_states if s.id == "formal")
        assert prompt.subjects[0].identity == formal.visual_anchor
        assert prompt.subjects[0].appearance_state_id == "formal"
        # Base anchor is NOT concatenated.
        assert "faded jeans" not in prompt.subjects[0].identity

    def test_significant_state_uses_state_anchor(self, tmp_path):
        """scene_003: significant injured state — identity == the injured
        state's self-contained anchor, not the base + default_outfit."""
        bible = _bible_with_states()
        panel = PlannedPanel(
            panel_id="scene_003:panel_001",
            scene_id="scene_003",
            panel_number=1,
            beat_ids=["scene_003:beat_001"],
            shot_type="medium",
            camera_angle="eye-level",
            characters_present=["char_001"],
            character_actions={"char_001": "staggers forward"},
            character_positions={"char_001": "center"},
            background_description="ruined street",
            lighting="firelight",
            mood="desperate",
        )
        prompt = build_planned_panel_prompt_spec(Config(), tmp_path, panel, bible)

        injured = next(s for s in bible.characters[0].appearance_states if s.id == "injured")
        assert prompt.subjects[0].identity == injured.visual_anchor
        assert prompt.subjects[0].appearance_state_id == "injured"
        # Not concatenated with base + default_outfit.
        assert prompt.subjects[0].identity.count("leather jacket") == 1

    def test_restored_state_uses_state_anchor(self, tmp_path):
        """scene_004: restored state — identity == the restored state's
        self-contained anchor."""
        bible = _bible_with_states()
        panel = PlannedPanel(
            panel_id="scene_004:panel_001",
            scene_id="scene_004",
            panel_number=1,
            beat_ids=["scene_004:beat_001"],
            shot_type="medium",
            camera_angle="eye-level",
            characters_present=["char_001"],
            character_actions={"char_001": "flexes both hands"},
            character_positions={"char_001": "center"},
            background_description="rebuilding site",
            lighting="morning sun",
            mood="hopeful",
        )
        prompt = build_planned_panel_prompt_spec(Config(), tmp_path, panel, bible)

        restored = next(s for s in bible.characters[0].appearance_states if s.id == "restored")
        assert prompt.subjects[0].identity == restored.visual_anchor
        assert prompt.subjects[0].appearance_state_id == "restored"

    def test_location_state_uses_state_anchor(self, tmp_path):
        """Post-collapse panel: location anchor == the post state's
        self-contained anchor, not the base location anchor."""
        bible = _bible_with_states()
        panel = PlannedPanel(
            panel_id="scene_001:panel_006",
            scene_id="scene_001",
            panel_number=6,
            beat_ids=["scene_001:beat_005", "scene_001:beat_006"],
            shot_type="wide",
            camera_angle="eye-level",
            characters_present=[],
            background_description="entire block flattened, rubble everywhere",
            lighting="dark fire glow",
            mood="catastrophic",
        )
        prompt = build_planned_panel_prompt_spec(Config(), tmp_path, panel, bible)

        loc_anchors = [a for a in prompt.anchors if a.kind == "location"]
        assert len(loc_anchors) == 1
        post_state = bible.locations[0].appearance_states[0]
        assert loc_anchors[0].text == post_state.visual_anchor
        assert prompt.location_state_id == "loc_001_post"


# ── LLM brief owns only scene direction ────────────────────────────────────


class TestLLMBriefOwnsOnlySceneDirection:
    def test_brief_source_excludes_character_anchor(self, tmp_path):
        from novel_to_comic.prompting import visual_brief_source_spec

        prompt = build_planned_panel_prompt_spec(
            Config(), tmp_path, _base_panel(), _bible_with_sentinels()
        )
        spec = visual_brief_source_spec(prompt)

        # The sentinel anchor is protected — it must NOT appear in the LLM spec.
        assert _CHAR_SENTINEL not in spec

    def test_brief_source_excludes_location_anchor(self, tmp_path):
        from novel_to_comic.prompting import visual_brief_source_spec

        prompt = build_planned_panel_prompt_spec(
            Config(), tmp_path, _base_panel(), _bible_with_sentinels()
        )
        spec = visual_brief_source_spec(prompt)
        assert _LOC_SENTINEL not in spec

    def test_brief_source_excludes_system_constraints(self, tmp_path):
        """No system constraint text (count, one-body, single-instant,
        no-lettering, crop policy, appearance locks) in the LLM spec."""
        from novel_to_comic.prompting import visual_brief_source_spec

        prompt = build_planned_panel_prompt_spec(
            Config(), tmp_path, _base_panel(), _bible_with_sentinels()
        )
        spec = visual_brief_source_spec(prompt)

        assert "one body per listed character" not in spec
        assert "single frozen instant" not in spec
        assert "no text, captions, speech balloons" not in spec
        assert "exactly 1 character" not in spec.lower()

    def test_brief_source_includes_scene_direction(self, tmp_path):
        """The LLM spec DOES carry scene direction: framing, action, expression,
        position, setting (background), lighting, mood."""
        from novel_to_comic.prompting import visual_brief_source_spec

        prompt = build_planned_panel_prompt_spec(
            Config(), tmp_path, _base_panel(), _bible_with_sentinels()
        )
        spec = visual_brief_source_spec(prompt)

        assert "holds the Dragon Key tightly" in spec  # action
        assert "The old hall interior" in spec  # background setting
        assert "dim firelight" in spec  # lighting
        assert "tense" in spec  # mood

    def test_mock_brief_omitting_anchor_still_preserves_it(self, tmp_path):
        """Even if the LLM brief omits/contradicts an anchor, the canonical
        rendered projection must still contain the protected anchor unchanged."""
        from novel_to_comic.generation_prompt import render_canonical_body

        prompt = build_planned_panel_prompt_spec(
            Config(), tmp_path, _base_panel(), _bible_with_sentinels()
        )
        # Simulate a malicious / broken LLM brief that drops the anchor.
        prompt.visual_brief = "A simple figure in a hall holding something. Nothing distinctive."
        body = render_canonical_body(prompt)

        assert _CHAR_SENTINEL in body
        assert _LOC_SENTINEL in body


# ── System constraints are generated, typed, non-editable ───────────────────


class TestSystemConstraintsGeneratedAndNonEditable:
    def test_system_constraints_present_in_canonical_projection(self, tmp_path):
        from novel_to_comic.generation_prompt import render_canonical_body

        prompt = build_planned_panel_prompt_spec(
            Config(), tmp_path, _base_panel(), _bible_with_sentinels()
        )
        body = render_canonical_body(prompt)

        assert "exactly 1 character" in body  # count
        assert "one body per listed character" in body
        assert "single frozen instant" in body
        assert "no text, captions, speech balloons, or lettering" in body

    def test_constraints_field_is_user_addenda_only(self, tmp_path):
        """The stored `constraints` field should NOT carry system constraints
        (count, one-body, single-instant, no-lettering)."""
        prompt = build_planned_panel_prompt_spec(
            Config(), tmp_path, _base_panel(), _bible_with_sentinels()
        )
        c = prompt.constraints or ""
        assert "one body per listed character" not in c
        assert "single frozen instant" not in c
        assert "no text, captions, speech balloons" not in c
        assert "exactly 1 character" not in c

    def test_system_constraints_survive_manual_edit(self, tmp_path):
        """A manual edit to constraints (user addenda) must not remove system
        constraints from the canonical projection."""
        from novel_to_comic.generation_prompt import render_canonical_body
        from novel_to_comic.panel_store import apply_prompt_patch

        prompt = build_planned_panel_prompt_spec(
            Config(), tmp_path, _base_panel(), _bible_with_sentinels()
        )
        edited = apply_prompt_patch(
            prompt, {"constraints": "avoid showing the key prominently"}
        )
        body = render_canonical_body(edited)

        # User addenda survives.
        assert "avoid showing the key prominently" in body
        # System constraints survive.
        assert "one body per listed character" in body
        assert "single frozen instant" in body
        assert "no text, captions, speech balloons" in body

    def test_system_constraints_survive_instructed_edit(self, tmp_path):
        """An instructed edit must not remove system constraints from the
        canonical projection."""
        from novel_to_comic.generation_prompt import render_canonical_body
        from novel_to_comic.prompt_instructions import apply_instruction_patch, parse_instruction_patch

        prompt = build_planned_panel_prompt_spec(
            Config(), tmp_path, _base_panel(), _bible_with_sentinels()
        )
        patch = parse_instruction_patch(
            {
                "status": "accepted",
                "message": "warmer light",
                "operations": [
                    {"type": "panel", "field": "lighting", "value": "warm amber glow"}
                ],
            }
        )
        edited = apply_instruction_patch(prompt, patch)
        body = render_canonical_body(edited)

        assert "one body per listed character" in body
        assert "single frozen instant" in body
        assert "no text, captions, speech balloons" in body

    def test_appearance_lock_is_system_constraint(self, tmp_path):
        """A significant state's appearance lock is a system constraint — it
        appears in the projection even though the LLM owns scene direction."""
        from novel_to_comic.generation_prompt import render_canonical_body

        bible = _bible_with_states()
        panel = PlannedPanel(
            panel_id="scene_003:panel_001",
            scene_id="scene_003",
            panel_number=1,
            beat_ids=["scene_003:beat_001"],
            shot_type="medium",
            camera_angle="eye-level",
            characters_present=["char_001"],
            character_actions={"char_001": "staggers forward"},
            character_positions={"char_001": "center"},
            background_description="ruined street",
            lighting="firelight",
            mood="desperate",
        )
        prompt = build_planned_panel_prompt_spec(Config(), tmp_path, panel, bible)
        body = render_canonical_body(prompt)

        assert "fixed altered appearance" in body
        assert "do not restore" in body


# ── PromptSubject carries active state id ───────────────────────────────────


class TestSubjectCarriesActiveStateId:
    def test_base_subject_has_no_state_id(self, tmp_path):
        bible = _bible_with_states()
        panel = PlannedPanel(
            panel_id="scene_001:panel_001",
            scene_id="scene_001",
            panel_number=1,
            beat_ids=["scene_001:beat_001"],
            shot_type="medium",
            characters_present=["char_001"],
            character_actions={"char_001": "stands"},
            background_description="street",
            lighting="cold",
            mood="tense",
        )
        prompt = build_planned_panel_prompt_spec(Config(), tmp_path, panel, bible)
        assert prompt.subjects[0].appearance_state_id is None

    def test_significant_state_subject_has_state_id(self, tmp_path):
        bible = _bible_with_states()
        panel = PlannedPanel(
            panel_id="scene_003:panel_001",
            scene_id="scene_003",
            panel_number=1,
            beat_ids=["scene_003:beat_001"],
            shot_type="medium",
            characters_present=["char_001"],
            character_actions={"char_001": "staggers"},
            background_description="street",
            lighting="fire",
            mood="desperate",
        )
        prompt = build_planned_panel_prompt_spec(Config(), tmp_path, panel, bible)
        assert prompt.subjects[0].appearance_state_id == "injured"


# ── Prompt version bump ────────────────────────────────────────────────────


def test_image_prompt_version_bumped():
    from novel_to_comic.prompting import IMAGE_PROMPT_VERSION

    assert IMAGE_PROMPT_VERSION >= 21
