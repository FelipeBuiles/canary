"""Slice 03 — prompt source lineage and state-aware overlays.

Currency is content-based: a stored prompt is current iff its recorded
``source_sha256`` matches a fresh build from the current Story Bible +
PlannedPanel. User corrections survive a compatible canonical rebuild because
they are stored as overlays and replayed over the fresh canonical source; an
overlay bound to a removed subject or an incompatible appearance/location state
is dropped with a structured warning instead of being misapplied.

These tests make no paid/model calls — ``build_planned_panel_prompt_spec`` and
``ensure_current_panel_prompt`` are deterministic (LLM visual-brief/layout are
separate ``ensure_*`` steps not exercised here).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from novel_to_comic.config import Config
from novel_to_comic.models.appearance import AppearanceState, StateActivation, StoryPosition
from novel_to_comic.models.layout_plan import PlannedPanel
from novel_to_comic.models.prompt import ImagePrompt, PromptSubject, PromptOverlayOp
from novel_to_comic.models.story_bible import Character, Location, Prop, Scene, StoryBible
from novel_to_comic.panel_store import apply_prompt_patch
from novel_to_comic.prompt_assembly import (
    compute_source_sha256,
    ensure_current_panel_prompt,
    prompt_is_current,
    reapply_overlays,
)
from novel_to_comic.prompting import IMAGE_PROMPT_VERSION


# ── Fixtures ──────────────────────────────────────────────────────────────────


def _character(*, char_id="char_milla", name="Milla", anchor=None, states=None, timeline=None):
    return Character(
        id=char_id,
        name=name,
        visual_anchor=anchor or "1woman, short black hair, green eyes, leather jacket, boots",
        age_range="30s",
        gender="female",
        distinguishing_features=["short black hair"],
        default_outfit="leather jacket",
        relationships=[],
        first_appearance_scene="scene_001",
        appearance_states=states or [],
        appearance_timeline=timeline or [],
    )


def _location(*, loc_id="loc_square", name="Market Square", anchor=None, states=None, timeline=None):
    return Location(
        id=loc_id,
        name=name,
        visual_anchor=anchor or "open cobblestone market square, market stalls, dawn light",
        time_of_day="dawn",
        mood="bustling",
        appearance_states=states or [],
        appearance_timeline=timeline or [],
    )


def _scene(*, scene_id="scene_001", location_id="loc_square", character_ids=None):
    return Scene(
        id=scene_id,
        chapter=1,
        title="The Square",
        location_id=location_id,
        character_ids=character_ids or ["char_milla"],
        summary="Milla crosses the square.",
        scene_type="action",
        narrative_beat="rising_action",
        source_start_quote="quote",
    )


def _panel(
    *,
    panel_id="scene_001:panel_001",
    scene_id="scene_001",
    panel_number=1,
    mood="tense",
    characters_present=None,
    actions=None,
    background="wide shot of the market square",
    beat_ids=None,
    transition_out=None,
):
    present = characters_present if characters_present is not None else ["char_milla"]
    return PlannedPanel(
        panel_id=panel_id,
        scene_id=scene_id,
        panel_number=panel_number,
        mood=mood,
        characters_present=present,
        character_actions=actions or ({"char_milla": "walking briskly"} if present else {}),
        character_expressions={"char_milla": "focused"} if present else {},
        character_positions={"char_milla": "center frame"} if present else {},
        background_description=background,
        lighting="soft golden hour",
        shot_type="medium",
        camera_angle="eye-level",
        beat_ids=beat_ids or ["scene_001:beat_001", "scene_001:beat_002"],
        transition_out=transition_out,
    )


def _bible(
    *,
    characters=None,
    locations=None,
    scenes=None,
    props=None,
    total_scenes=1,
):
    return StoryBible(
        title="T",
        author="A",
        total_scenes=total_scenes,
        characters=characters if characters is not None else [_character()],
        locations=locations if locations is not None else [_location()],
        scenes=scenes if scenes is not None else [_scene()],
        narrative_arcs=[],
        props=props or [],
    )


def _build_stored(config: Config, project_dir: Path, panel: PlannedPanel, bible: StoryBible, prev_panel=None) -> ImagePrompt:
    """Persist a freshly built prompt so the freshness path can find it."""
    prompt = ensure_current_panel_prompt(config, project_dir, panel, bible, prev_panel)
    return prompt


def _write_prompt(project_dir: Path, prompt: ImagePrompt) -> None:
    from novel_to_comic.layout_planning import prompt_path_for_panel

    path = prompt_path_for_panel(project_dir, prompt)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(prompt.model_dump_json(indent=2))


# ── Unchanged sources return the stored prompt without rebuild ───────────────


class TestUnchangedSourcesAreCurrent:
    def test_unchanged_inputs_match_source_hash(self, tmp_path):
        config = Config()
        panel = _panel()
        bible = _bible()
        prompt = _build_stored(config, tmp_path, panel, bible)

        assert prompt.source_sha256 is not None
        assert prompt_is_current(
            prompt, panel, story_bible=bible, project_dir=tmp_path, config=config
        )
        # The stored hash equals a freshly computed one.
        assert prompt.source_sha256 == compute_source_sha256(config, tmp_path, panel, bible)

    def test_unchanged_sources_return_stored_prompt_without_rebuild(self, tmp_path):
        config = Config()
        panel = _panel()
        bible = _bible()
        first = _build_stored(config, tmp_path, panel, bible)

        # Second call with identical inputs returns the same stored prompt
        # (no rebuild / no new LLM/layout work — exercised by identity).
        second = ensure_current_panel_prompt(config, tmp_path, panel, bible)
        assert second is first or second.source_sha256 == first.source_sha256


# ── Each upstream change alters source_sha256 and triggers a rebuild ──────────


class TestSourceChangesAlterHash:
    @pytest.fixture
    def base(self, tmp_path):
        config = Config()
        panel = _panel()
        bible = _bible()
        prompt = _build_stored(config, tmp_path, panel, bible)
        return config, panel, bible, prompt

    def test_panel_action_change_rebuilds(self, tmp_path, base):
        config, panel, bible, prompt = base
        new_panel = panel.model_copy(
            update={"character_actions": {"char_milla": "running hard"}}
        )
        new_hash = compute_source_sha256(config, tmp_path, new_panel, bible)
        assert new_hash != prompt.source_sha256
        assert not prompt_is_current(
            prompt, new_panel, story_bible=bible, project_dir=tmp_path, config=config
        )

    def test_panel_mood_change_rebuilds(self, tmp_path, base):
        config, panel, bible, prompt = base
        new_panel = panel.model_copy(update={"mood": "elated"})
        assert compute_source_sha256(config, tmp_path, new_panel, bible) != prompt.source_sha256

    def test_character_anchor_change_rebuilds(self, tmp_path, base):
        config, panel, bible, prompt = base
        new_char = _character(anchor="1woman, short black hair, green eyes, RED COAT, boots")
        new_bible = _bible(characters=[new_char])
        assert (
            compute_source_sha256(config, tmp_path, panel, new_bible)
            != prompt.source_sha256
        )

    def test_character_appearance_state_activation_rebuilds(self, tmp_path):
        config = Config()
        stumps = AppearanceState(
            id="stumps",
            label="Maimed",
            visual_anchor="1woman, short black hair, green eyes, leather jacket, arm stumps",
            visually_significant=True,
        )
        # Panel lands before the stumps activation (beat 2 < activation beat 5).
        early_char = _character(states=[stumps], timeline=[])
        early_panel = _panel(beat_ids=["scene_001:beat_001", "scene_001:beat_002"])
        early_bible = _bible(characters=[early_char])
        early = compute_source_sha256(config, tmp_path, early_panel, early_bible)

        # Same character but now the stumps state activates at beat 5; panel at
        # beat 6 lands after activation → different appearance → different hash.
        activated_char = _character(
            states=[stumps],
            timeline=[
                StateActivation(state_id="stumps", at=StoryPosition(scene_id="scene_001", beat=5))
            ],
        )
        late_panel = _panel(beat_ids=["scene_001:beat_006"])
        late_bible = _bible(characters=[activated_char])
        late = compute_source_sha256(config, tmp_path, late_panel, late_bible)
        assert early != late

    def test_location_anchor_change_rebuilds(self, tmp_path, base):
        config, panel, bible, prompt = base
        new_loc = _location(anchor="open cobblestone market square, STORM DAMAGE, rubble")
        new_bible = _bible(locations=[new_loc])
        assert compute_source_sha256(config, tmp_path, panel, new_bible) != prompt.source_sha256

    def test_matched_prop_change_rebuilds(self, tmp_path):
        config = Config()
        panel = _panel(
            background="Milla clutches the Monkey's Paw on the cobblestones",
            actions={"char_milla": "clutching the Monkey's Paw"},
        )
        bible_with_prop = _bible(
            props=[
                Prop(
                    id="prop_paw",
                    name="Monkey's Paw",
                    visual_anchor="a withered mummified monkey's paw",
                    first_appearance_scene="scene_001",
                )
            ]
        )
        hash_with_prop = compute_source_sha256(config, tmp_path, panel, bible_with_prop)
        hash_without_prop = compute_source_sha256(config, tmp_path, panel, _bible(props=[]))
        assert hash_with_prop != hash_without_prop

    def test_target_language_change_rebuilds(self, tmp_path, base):
        config, panel, bible, prompt = base
        es_config = Config()
        es_config.target_language = "es"
        assert (
            compute_source_sha256(es_config, tmp_path, panel, bible)
            != prompt.source_sha256
        )

    def test_continuity_mode_change_rebuilds(self, tmp_path, base):
        config, panel, bible, prompt = base
        ref_config = Config()
        ref_config.continuity_mode = "off"
        assert (
            compute_source_sha256(ref_config, tmp_path, panel, bible)
            != prompt.source_sha256
        )

    def test_prior_transition_change_rebuilds(self, tmp_path):
        config = Config()
        prev_smooth = _panel(panel_id="scene_001:panel_000", panel_number=0, transition_out="smooth_continuation")
        prev_hard = _panel(panel_id="scene_001:panel_000", panel_number=0, transition_out="scene_change")
        panel = _panel()
        bible = _bible()
        hash_smooth = compute_source_sha256(config, tmp_path, panel, bible, prev_smooth)
        hash_hard = compute_source_sha256(config, tmp_path, panel, bible, prev_hard)
        # The continuity note only derives from smooth/match-cut transitions,
        # so the hard cut yields a different (or absent) continuity projection.
        assert hash_smooth != hash_hard


# ── Style-only change does not rebuild stored panel structure ─────────────────


class TestStyleExcludedFromLineage:
    def test_style_only_change_does_not_rebuild(self, tmp_path):
        config = Config()
        panel = _panel()
        bible = _bible()
        hash_a = compute_source_sha256(config, tmp_path, panel, bible)

        # Changing only the style template must not alter the source lineage —
        # style is a generation-time input, not stored panel structure.
        config.style_template = "a completely different ink-wash style"
        hash_b = compute_source_sha256(config, tmp_path, panel, bible)
        assert hash_a == hash_b


# ── User overlays survive a compatible canonical rebuild ─────────────────────


class TestOverlaySurvivesRebuild:
    def test_composition_overlay_survives_compatible_rebuild(self, tmp_path):
        config = Config()
        panel = _panel(mood="tense")
        bible = _bible()
        stored = _build_stored(config, tmp_path, panel, bible)
        assert stored.composition is not None

        # User edits composition via the patch path (records an overlay).
        edited = apply_prompt_patch(stored, {"composition": "dramatic low-angle hero shot"})
        assert "dramatic low-angle hero shot" in edited.composition
        assert edited.user_overlays, "composition edit must record an overlay"
        _write_prompt(tmp_path, edited)

        # An upstream change to the panel (mood) forces a rebuild. The overlay
        # is replayed so the user's composition correction survives.
        new_panel = panel.model_copy(update={"mood": "elated"})
        new_bible = _bible()
        rebuilt = ensure_current_panel_prompt(config, tmp_path, new_panel, new_bible)
        assert "dramatic low-angle hero shot" in (rebuilt.composition or "")
        assert any(op.field == "composition" for op in rebuilt.user_overlays)

    def test_state_neutral_framing_overlay_survives(self, tmp_path):
        config = Config()
        char = _character()
        panel = _panel()
        bible = _bible(characters=[char])
        stored = _build_stored(config, tmp_path, panel, bible)

        # A framing overlay (composition) is state-neutral — it survives any
        # appearance state change for the same subject.
        edited = apply_prompt_patch(stored, {"composition": "wide environmental shot"})
        _write_prompt(tmp_path, edited)

        rebuilt = ensure_current_panel_prompt(config, tmp_path, panel, bible)
        assert "wide environmental shot" in (rebuilt.composition or "")


# ── State-aware overlay drop semantics ────────────────────────────────────────


class TestStateAwareOverlayDrops:
    def test_overlay_for_removed_character_is_dropped_with_warning(self, tmp_path):
        config = Config()
        panel = _panel(characters_present=["char_milla"])
        bible = _bible()
        stored = _build_stored(config, tmp_path, panel, bible)

        # Subject-scoped overlay bound to char_milla.
        edited = apply_prompt_patch(
            stored,
            {"subjects": [PromptSubject(
                character_id="char_milla",
                name="Milla",
                identity=stored.subjects[0].identity,
                action="leaping over the stall",
            )]},
        )
        assert any(op.subject_character_id == "char_milla" for op in edited.user_overlays)
        _write_prompt(tmp_path, edited)

        # Rebuild with a bible where the character is no longer present in the
        # panel → the overlay cannot find its subject and is dropped.
        no_char_panel = _panel(characters_present=[])
        no_char_bible = _bible(characters=[_character()])
        rebuilt = ensure_current_panel_prompt(config, tmp_path, no_char_panel, no_char_bible)
        assert all(op.subject_character_id != "char_milla" for op in rebuilt.user_overlays)

    def test_uses_both_hands_overlay_dropped_in_no_hands_state(self):
        """A "uses both hands" overlay bound to the base (hands) state is
        dropped when the character is now in a no-hands state; the overlay must
        NOT be misapplied to that state."""
        prompt = ImagePrompt(
            prompt_version=IMAGE_PROMPT_VERSION,
            planned_panel_id="p1",
            scene_id="scene_001",
            panel_number=1,
            width=768,
            height=1024,
            steps=8,
            subjects=[
                PromptSubject(
                    character_id="char_milla",
                    name="Milla",
                    identity="1woman, short black hair, leather jacket, arm stumps",
                    appearance_state_id="stumps",
                )
            ],
        )
        # Overlay authored in the base (hands) state — bound to the concrete
        # "hands" state so it cannot apply to the active "stumps" state.
        concrete_hands = PromptOverlayOp(
            field="action",
            value="gripping the sword with both hands",
            subject_character_id="char_milla",
            appearance_state_id="hands",  # not the active "stumps" state
        )
        warnings = reapply_overlays(prompt, [concrete_hands])
        assert any(w.code == "state_incompatible" for w in warnings)
        assert prompt.subjects[0].action != "gripping the sword with both hands"

    def test_state_neutral_framing_overlay_survives_state_change(self):
        """A state-neutral framing overlay (composition) re-apes regardless of
        the subject's appearance state, as long as the subject is present."""
        prompt = ImagePrompt(
            prompt_version=IMAGE_PROMPT_VERSION,
            planned_panel_id="p1",
            scene_id="scene_001",
            panel_number=1,
            width=768,
            height=1024,
            steps=8,
            composition="medium shot",
            subjects=[
                PromptSubject(
                    character_id="char_milla",
                    name="Milla",
                    identity="1woman, short black hair, leather jacket, arm stumps",
                    appearance_state_id="stumps",
                )
            ],
        )
        framing_overlay = PromptOverlayOp(
            field="composition",
            value="wide environmental shot with deep shadows",
            subject_character_id=None,
            appearance_state_id=None,
        )
        warnings = reapply_overlays(prompt, [framing_overlay])
        assert warnings == []
        assert "wide environmental shot" in (prompt.composition or "")

    def test_location_sensitive_overlay_revalidated_on_state_change(self):
        """A location-material correction is revalidated when a damage/weather
        state activates: it is dropped if bound to a different location state."""
        prompt = ImagePrompt(
            prompt_version=IMAGE_PROMPT_VERSION,
            planned_panel_id="p1",
            scene_id="scene_001",
            panel_number=1,
            width=768,
            height=1024,
            steps=8,
            location_state_id="loc_square_damaged",
            setting="rubble-strewn square under storm clouds",
        )
        # Overlay authored in the pristine location state.
        pristine_overlay = PromptOverlayOp(
            field="setting",
            value="pristine market stalls with colorful awnings",
            location_state_id="loc_square",
        )
        warnings = reapply_overlays(prompt, [pristine_overlay])
        assert any(w.code == "location_state_incompatible" for w in warnings)
        assert "pristine market stalls" not in (prompt.setting or "")


# ── Freshness is shared across all entry points ──────────────────────────────


class TestSharedFreshnessDecision:
    def test_all_entry_points_use_the_same_decision(self, tmp_path):
        """prompt_is_current is the single freshness function used by the direct
        stage, draw preflight, and single-panel rerender (all call
        ensure_current_panel_prompt)."""
        config = Config()
        panel = _panel()
        bible = _bible()
        stored = _build_stored(config, tmp_path, panel, bible)

        # Current → no rebuild regardless of which caller asks.
        assert prompt_is_current(
            stored, panel, story_bible=bible, project_dir=tmp_path, config=config
        )
        again = ensure_current_panel_prompt(config, tmp_path, panel, bible)
        assert again.source_sha256 == stored.source_sha256

    def test_stale_version_triggers_rebuild(self, tmp_path):
        config = Config()
        panel = _panel()
        bible = _bible()
        stored = _build_stored(config, tmp_path, panel, bible)
        # Force an old version on disk.
        data = json.loads(stored.model_dump_json())
        data["prompt_version"] = IMAGE_PROMPT_VERSION - 1
        from novel_to_comic.layout_planning import prompt_path_for_panel

        prompt_path_for_panel(tmp_path, panel).write_text(json.dumps(data))

        rebuilt = ensure_current_panel_prompt(config, tmp_path, panel, bible)
        assert rebuilt.prompt_version == IMAGE_PROMPT_VERSION


# ── Reference availability does not affect prompt lineage ────────────────────


class TestReferencesExcludedFromLineage:
    def test_reference_file_availability_does_not_change_source_hash(self, tmp_path):
        """Newly available state references do not affect prompt lineage here;
        selected-reference materialization is a ReferencePlan concern (Slice 04)."""
        config = Config()
        panel = _panel()
        bible = _bible()
        hash_before = compute_source_sha256(config, tmp_path, panel, bible)

        # Add reference image files on disk — the source hash must be unchanged.
        refs_dir = tmp_path / "refs" / "char_milla"
        refs_dir.mkdir(parents=True)
        (refs_dir / "front.png").write_bytes(b"ref")
        hash_after = compute_source_sha256(config, tmp_path, panel, bible)
        assert hash_before == hash_after


# ── Overlay merge / dedup ─────────────────────────────────────────────────────


class TestOverlayMerge:
    def test_repeated_field_edit_supersedes_older_overlay(self, tmp_path):
        config = Config()
        panel = _panel()
        bible = _bible()
        stored = _build_stored(config, tmp_path, panel, bible)

        first = apply_prompt_patch(stored, {"composition": "first edit"})
        second = apply_prompt_patch(first, {"composition": "second edit"})
        comp_overlays = [op for op in second.user_overlays if op.field == "composition"]
        assert len(comp_overlays) == 1
        assert comp_overlays[0].value == "second edit"
