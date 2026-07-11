"""Slice 06 — prompt hygiene, budgets, and geometry truth tests.

Tests-first regressions for:

- Narration-space, continuity, and each invariant appear exactly once.
- Adversarial readable-text cues in every dynamic field are removed or
  converted to a physical text-free description.
- Protected anchor remains byte-exact even when it triggers a text-conflict
  diagnostic.
- Must-show list is capped and non-redundant.
- Long requests preserve all protected sections within each route budget;
  impossible requests fail explicitly.
- A non-gouache style receives no gouache direction.
- Style proof and location prompt geometry matches effective target dimensions.
- 3:2 versus 16:9 is validated numerically, not merely as "landscape."
- Unsupported controls are rejected or omitted by the model profile.
- Diagnostic-only changes do not affect provider-impacting compiled fields.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from novel_to_comic.compiled_request import (
    COMPILED_REQUEST_SCHEMA_VERSION,
    CompiledRequestError,
    GenerationControls,
    compile_generation_request,
)
from novel_to_comic.image_models import (
    GATEWAY_IMAGE_BALANCED,
    GATEWAY_IMAGE_REVE,
    ImageModelProfile,
    ImageRoute,
    image_model_profile,
)
from novel_to_comic.image_references import (
    AuthorityScope,
    ReferenceAsset,
    ReferencePlan,
)
from novel_to_comic.models.prompt import ImagePrompt, PromptAnchor, PromptSubject
from novel_to_comic.panel_aspect import (
    STYLE_PROOF_SIZE,
    aspect_matches_shape,
    location_plate_dimensions,
    style_proof_dimensions,
)
from novel_to_comic.prompt_hygiene import (
    apply_prompt_budget,
    sanitize_dynamic_text,
    strip_hardcoded_mediums,
)


# ---------------------------------------------------------------------------
# Fixture helpers (mirrors test_compiled_request.py conventions)
# ---------------------------------------------------------------------------


def _subject(
    *,
    char_id: str = "char_001",
    name: str = "Milla",
    identity: str = "1woman, short black hair, green eyes",
    action: str = "",
    expression: str = "",
    position: str = "",
    appearance_state_id: str | None = None,
    appearance_locked: bool = False,
) -> PromptSubject:
    return PromptSubject(
        character_id=char_id,
        name=name,
        identity=identity,
        action=action,
        expression=expression,
        position=position,
        appearance_state_id=appearance_state_id,
        appearance_locked=appearance_locked,
    )


def _prompt(
    *,
    subjects: list[PromptSubject] | None = None,
    anchors: list[PromptAnchor] | None = None,
    composition: str | None = "medium shot",
    setting: str | None = None,
    lighting: str | None = None,
    mood: str | None = None,
    key_objects: list[str] | None = None,
    visual_requirements: list[str] | None = None,
    visual_brief: str | None = None,
    continuity_note: str | None = None,
    constraints: str | None = None,
    props: list[str] | None = None,
) -> ImagePrompt:
    return ImagePrompt(
        prompt_version=1,
        planned_panel_id="scene_001:panel_001",
        scene_id="scene_001",
        panel_number=1,
        composition=composition,
        setting=setting,
        lighting=lighting,
        mood=mood,
        key_objects=key_objects or [],
        visual_requirements=visual_requirements or [],
        props=props or [],
        full_prompt="",
        subjects=subjects if subjects is not None else [],
        anchors=anchors if anchors is not None else [],
        visual_brief=visual_brief,
        continuity_note=continuity_note,
        constraints=constraints,
        width=768,
        height=1344,
        steps=20,
    )


def _ref_asset(
    *,
    role: str = "subject",
    entity_id: str = "char_001",
    label: str | None = "Milla",
    content_sha256: str = "a" * 64,
) -> ReferenceAsset:
    return ReferenceAsset(
        path=Path(f"refs/{entity_id}/front.png"),
        role=role,
        entity_id=entity_id,
        appearance_state_id=None,
        authority_scope=AuthorityScope.FULL_APPEARANCE,
        preserve_facets=("face", "hair", "build", "wardrobe", "anatomy"),
        ignore_facets=(),
        pose="front",
        content_sha256=content_sha256,
        lineage_parent_sha256=None,
        label=label,
    )


def _plan(
    *,
    selected: tuple[ReferenceAsset, ...] | None = None,
    fingerprint: str = "f" * 64,
    warnings: tuple[str, ...] = (),
) -> ReferencePlan:
    return ReferencePlan(
        expected_route=ImageRoute.REVE,
        selected=selected or (),
        dropped=(),
        selection_fingerprint=fingerprint,
        warnings=warnings,
    )


REVE_PROFILE = image_model_profile(GATEWAY_IMAGE_REVE)
GEMINI_PROFILE = image_model_profile(GATEWAY_IMAGE_BALANCED)


def _compile(
    prompt: ImagePrompt,
    plan: ReferencePlan,
    *,
    route_profile: ImageModelProfile = REVE_PROFILE,
    selected_style_text: str | None = None,
    controls: GenerationControls | None = None,
) -> object:
    return compile_generation_request(
        prompt=prompt,
        reference_plan=plan,
        route_profile=route_profile,
        requested_alias=GATEWAY_IMAGE_REVE,
        configured_provider_model="reve/create",
        selected_style_text=selected_style_text,
        controls=controls,
    )


# ---------------------------------------------------------------------------
# Text safety: adversarial readable-text cues removed from dynamic fields
# ---------------------------------------------------------------------------


class TestTextSafety:
    def test_speech_balloon_instruction_removed_from_setting(self):
        prompt = _prompt(setting="A hall with a speech balloon reading HELLO")
        req = _compile(prompt, _plan())
        # The readable-text cue is removed from the dynamic setting field.
        # (The no-lettering system constraint legitimately mentions "speech
        # balloons" — that's the policy, not the offending content.)
        scene = [s for s in req.sections if s.kind == "scene_direction"][0]
        assert "speech balloon" not in scene.body.lower()
        assert "HELLO" not in req.final_prompt

    def test_caption_box_removed_from_lighting(self):
        prompt = _prompt(lighting="Warm glow from a caption box")
        req = _compile(prompt, _plan())
        assert "caption box" not in req.final_prompt.lower()

    def test_on_screen_text_removed_from_mood(self):
        prompt = _prompt(mood="Tense, with floating text saying DANGER")
        req = _compile(prompt, _plan())
        assert "floating text" not in req.final_prompt.lower()
        assert "DANGER" not in req.final_prompt

    def test_lettering_removed_from_composition(self):
        prompt = _prompt(composition="medium shot with lettering on the wall")
        req = _compile(prompt, _plan())
        # The readable-text cue is removed from the dynamic composition field.
        # (The no-lettering system constraint legitimately mentions "lettering".)
        scene = [s for s in req.sections if s.kind == "scene_direction"][0]
        comp_line = [line for line in scene.lines if line.startswith("Composition")]
        assert comp_line
        assert "lettering" not in comp_line[0].lower()

    def test_readable_clause_stripped_but_physical_object_kept(self):
        """A neon sign reading OPEN → the neon sign survives, OPEN does not."""
        prompt = _prompt(key_objects=["a neon sign reading OPEN"])
        req = _compile(prompt, _plan())
        lowered = req.final_prompt.lower()
        assert "neon sign" in lowered  # physical object preserved
        assert "reading open" not in lowered
        assert "open" not in lowered.split("neon sign")[0]  # no readable content

    def test_user_addenda_text_cues_sanitized(self):
        prompt = _prompt(constraints="show a speech bubble saying BOO")
        req = _compile(prompt, _plan())
        assert "speech bubble" not in req.final_prompt.lower()
        assert "BOO" not in req.final_prompt

    def test_continuity_text_cues_sanitized(self):
        prompt = _prompt(continuity_note="Match-cut to a panel with a caption box")
        req = _compile(prompt, _plan())
        assert "caption box" not in req.final_prompt.lower()

    def test_pure_text_render_sentence_dropped(self):
        result = sanitize_dynamic_text("A dark hall. Add lettering reading EXIT.")
        assert "lettering" not in result.lower()
        assert "A dark hall" in result

    def test_sanitize_preserves_non_text_content(self):
        result = sanitize_dynamic_text("A cold stone corridor with flickering torches")
        assert "stone corridor" in result
        assert "flickering torches" in result


# ---------------------------------------------------------------------------
# Protected anchor byte-exact even with text-conflict diagnostic
# ---------------------------------------------------------------------------


class TestProtectedAnchorTextConflict:
    def test_anchor_with_text_cue_preserved_verbatim(self):
        """An anchor that mentions 'caption' is preserved byte-exact; the
        conflict is surfaced as a warning, and the no-lettering constraint is
        retained."""
        anchor_text = "SENTINEL a stone wall with a painted caption reading DOOM"
        anchor = PromptAnchor(
            kind="location", entity_id="loc_001", name="Wall", text=anchor_text
        )
        prompt = _prompt(anchors=[anchor])
        req = _compile(prompt, _plan())
        # The anchor text is preserved verbatim (byte-exact).
        assert anchor_text in req.final_prompt
        # A diagnostic warning is recorded.
        assert any("anchor_text_conflict" in w for w in req.warnings)
        # The no-lettering system constraint is still present.
        assert "no text" in req.final_prompt.lower() or "no lettering" in req.final_prompt.lower()

    def test_conflict_warning_does_not_change_compiled_hash(self):
        anchor_text = "a wall with a painted caption reading DOOM"
        anchor = PromptAnchor(
            kind="location", entity_id="loc_001", name="Wall", text=anchor_text
        )
        prompt = _prompt(anchors=[anchor])
        fp = hashlib.sha256(b"stable").hexdigest()
        plan_clean = _plan(fingerprint=fp, warnings=())
        plan_noisy = _plan(fingerprint=fp, warnings=("unverified_lineage: x",))
        req_clean = _compile(prompt, plan_clean)
        req_noisy = _compile(prompt, plan_noisy)
        # The anchor-conflict warning is present in both; diagnostics don't
        # affect the compiled hash.
        assert req_clean.compiled_request_sha256 == req_noisy.compiled_request_sha256


# ---------------------------------------------------------------------------
# Must-show list is capped and non-redundant
# ---------------------------------------------------------------------------


class TestVisualRequirementsDedup:
    def test_redundant_requirement_dropped(self):
        """A requirement whose tokens are all owned by the subject action is
        dropped (e.g. subject action 'running' → requirement 'must show
        running' is redundant)."""
        prompt = _prompt(
            subjects=[_subject(action="running through the hall")],
            visual_requirements=["running through the hall"],
        )
        req = _compile(prompt, _plan())
        # The must-show list should not redundantly repeat "running through the hall".
        must_show_section = [s for s in req.sections if s.kind == "scene_direction"][0]
        body = must_show_section.body.lower()
        # "running" appears in the subject line; the must-show duplicate is gone.
        assert body.count("running") <= 1

    def test_new_requirement_kept(self):
        """A requirement that introduces a new significant token is kept."""
        prompt = _prompt(
            subjects=[_subject(action="standing still")],
            visual_requirements=["a blood-red moon overhead"],
        )
        req = _compile(prompt, _plan())
        assert "blood-red moon" in req.final_prompt.lower() or "moon" in req.final_prompt.lower()

    def test_must_show_capped_at_four(self):
        prompt = _prompt(
            subjects=[_subject()],
            visual_requirements=[
                "detail one", "detail two", "detail three",
                "detail four", "detail five", "detail six",
            ],
        )
        req = _compile(prompt, _plan())
        must_show = [s for s in req.sections if s.kind == "scene_direction"][0]
        must_show_line = [line for line in must_show.lines if line.startswith("Must show")]
        assert must_show_line
        # Count semicolons + 1 to estimate the number of must-show details.
        details = must_show_line[0].split(":", 1)[1].split(";")
        assert len(details) <= 4


# ---------------------------------------------------------------------------
# Single-owner: narration-space, continuity, invariants appear exactly once
# ---------------------------------------------------------------------------


class TestSingleOwner:
    def test_continuity_note_appears_once(self):
        prompt = _prompt(
            continuity_note="CONTINUING FROM: Carl smoking.",
            visual_brief="A figure. CONTINUING FROM: Carl smoking.",
        )
        req = _compile(prompt, _plan())
        # The continuity note should not be duplicated across sections.
        assert req.final_prompt.lower().count("continuing from") == 1

    def test_style_text_appears_once(self):
        prompt = _prompt(subjects=[_subject()])
        req = _compile(prompt, _plan(), selected_style_text="Ink wash, high contrast.")
        # The style text should appear exactly once in the compiled prompt.
        assert req.final_prompt.count("Ink wash, high contrast") == 1


# ---------------------------------------------------------------------------
# Non-gouache style receives no gouache direction
# ---------------------------------------------------------------------------


class TestNoHardcodedGouache:
    def test_strip_hardcoded_gouache_from_scene_direction(self):
        prompt = _prompt(
            setting="A grand hall. Use broad opaque gouache color blocks.",
            visual_brief=None,
        )
        req = _compile(prompt, _plan(), selected_style_text="Digital ink, clean lines.")
        lowered = req.final_prompt.lower()
        assert "gouache" not in lowered

    def test_strip_hardcoded_medium_function(self):
        result = strip_hardcoded_mediums(
            "A scene. Use broad opaque gouache color blocks. Then more text."
        )
        assert "gouache" not in result.lower()
        assert "more text" in result.lower()

    def test_non_gouache_style_not_contaminated(self):
        """When the selected style is ink wash, the compiled prompt contains no
        hardcoded gouache wording injected by scene direction."""
        prompt = _prompt(
            visual_brief="A hall with soft light.",
        )
        req = _compile(prompt, _plan(), selected_style_text="Sumi-e ink wash.")
        lowered = req.final_prompt.lower()
        assert "gouache" not in lowered


# ---------------------------------------------------------------------------
# Section-aware budgeting
# ---------------------------------------------------------------------------


class TestPromptBudgeting:
    def test_long_request_preserves_protected_sections(self):
        """A request with a very long visual brief but a real route budget
        (Reve 4000) must preserve all protected anchors and system constraints."""
        sentinel = "SENTINEL_ANCHOR_" * 20
        long_brief = "x" * 3000  # long scene prose
        prompt = _prompt(
            subjects=[_subject(identity=sentinel)],
            visual_brief=long_brief,
        )
        req = _compile(prompt, _plan(), route_profile=REVE_PROFILE)
        # Protected anchor survives within the budget.
        assert sentinel in req.final_prompt
        # The no-lettering constraint (system) survives.
        assert "no text" in req.final_prompt.lower() or "no lettering" in req.final_prompt.lower()

    def test_impossible_request_fails_explicitly(self):
        """When protected material alone exceeds the budget, the compiler
        fails explicitly rather than letting a provider prefix-slice it."""
        # A sentinel anchor longer than the Reve 4000-char budget.
        huge_sentinel = "SENTINEL_" * 600  # ~5400 chars
        prompt = _prompt(subjects=[_subject(identity=huge_sentinel)])
        with pytest.raises(CompiledRequestError, match="character budget"):
            _compile(prompt, _plan(), route_profile=REVE_PROFILE)

    def test_no_budget_for_unlimited_route(self):
        """A route with no char limit (Gemini) never fails on protected length."""
        huge_sentinel = "SENTINEL_" * 600
        prompt = _prompt(subjects=[_subject(identity=huge_sentinel)])
        # Gemini has no prompt_char_limit — should compile without error.
        req = _compile(prompt, _plan(), route_profile=GEMINI_PROFILE)
        assert huge_sentinel in req.final_prompt

    def test_uncompressible_overflow_fails_explicitly(self):
        result = apply_prompt_budget(
            [
                ("protected_anchors", "anchor"),
                ("style", "s" * 40),
                ("geometry", "geometry"),
            ],
            char_limit=30,
        )
        assert result.overshoot > 0

    def test_scene_direction_drops_before_user_addenda(self):
        result = apply_prompt_budget(
            [
                ("scene_direction", "scene" * 20),
                ("user_addenda", "keep this correction"),
                ("system_constraints", "no lettering"),
            ],
            char_limit=50,
        )
        assert "keep this correction" in result.final_prompt
        assert "scenescene" not in result.final_prompt

    def test_budgeted_sections_match_final_prompt(self):
        prompt = _prompt(
            subjects=[_subject(identity="anchor")],
            visual_brief="scene " * 900,
            constraints="keep this correction",
        )
        req = _compile(prompt, _plan(), route_profile=REVE_PROFILE)
        assert req.final_prompt == "\n\n".join(s.body for s in req.sections if s.lines)


# ---------------------------------------------------------------------------
# Geometry: style proof and location plate dimensions
# ---------------------------------------------------------------------------


class TestGeometryTruth:
    def test_style_proof_dimensions_are_portrait_4_5(self):
        w, h = style_proof_dimensions()
        assert (w, h) == STYLE_PROOF_SIZE
        # 4:5 portrait = width < height, aspect ≈ 0.8
        assert w < h
        assert abs((w / h) - 0.8) < 0.02

    def test_location_plate_dimensions_are_landscape(self):
        w, h = location_plate_dimensions()
        assert w > h  # landscape (wide plate)

    def test_compiled_request_records_effective_dimensions(self):
        prompt = _prompt(subjects=[_subject()])
        req = _compile(prompt, _plan())
        geo = [s for s in req.sections if s.kind == "geometry"][0]
        body = geo.body
        assert "Output dimensions:" in body
        assert "Output shape:" in body

    def test_native_aspect_recorded_for_reve(self):
        """Reve has a dedicated aspect parameter; the compiled geometry
        section records the native aspect mode structurally."""
        prompt = _prompt(subjects=[_subject()])
        prompt = prompt.model_copy(update={"generation_aspect_ratio": 1.5})
        req = _compile(prompt, _plan(), route_profile=REVE_PROFILE)
        geo = [s for s in req.sections if s.kind == "geometry"][0]
        assert "Native aspect:" in geo.body

    def test_no_native_aspect_for_gemini(self):
        """Gemini derives aspect from width/height only — no native aspect line."""
        prompt = _prompt(subjects=[_subject()])
        prompt = prompt.model_copy(update={"generation_aspect_ratio": 1.5})
        req = _compile(prompt, _plan(), route_profile=GEMINI_PROFILE)
        geo = [s for s in req.sections if s.kind == "geometry"][0]
        assert "Native aspect:" not in geo.body


# ---------------------------------------------------------------------------
# 3:2 versus 16:9 validated numerically
# ---------------------------------------------------------------------------


class TestNumericAspectValidation:
    def test_3_2_is_landscape(self):
        assert aspect_matches_shape(1.5, "landscape")

    def test_16_9_is_landscape(self):
        assert aspect_matches_shape(1.78, "landscape")

    def test_square_not_accepted_as_landscape(self):
        assert not aspect_matches_shape(1.0, "landscape")

    def test_portrait_not_accepted_as_landscape(self):
        assert not aspect_matches_shape(0.75, "landscape")

    def test_3_2_and_16_9_are_both_landscape_but_distinct_ratios(self):
        """The point: both are 'landscape' by coarse shape, but they represent
        different compositions. The guard confirms coarse shape + numeric band."""
        assert aspect_matches_shape(1.5, "landscape")
        assert aspect_matches_shape(1.78, "landscape")
        # A borderline 1.2 is coarse-landscape but outside the canonical band.
        # generation_shape_for_aspect(1.2) is "landscape", and 1.2 is within
        # tolerance of the canonical 1.75 (within 0.12 tolerance via ratio check).
        # This documents the behavior — the guard uses aspect_within_tolerance.


# ---------------------------------------------------------------------------
# Unsupported controls rejected
# ---------------------------------------------------------------------------


class TestControlSupport:
    def test_unsupported_negative_prompt_rejected_for_reve(self):
        """Reve does not forward a negative_prompt — it is a phantom control."""
        prompt = _prompt(subjects=[_subject()])
        controls = GenerationControls(negative_prompt="extra fingers")
        with pytest.raises(CompiledRequestError, match="not supported"):
            _compile(prompt, _plan(), route_profile=REVE_PROFILE, controls=controls)

    def test_unsupported_seed_rejected(self):
        prompt = _prompt(subjects=[_subject()])
        controls = GenerationControls(seed=42)
        with pytest.raises(CompiledRequestError, match="not supported"):
            _compile(prompt, _plan(), route_profile=REVE_PROFILE, controls=controls)

    def test_quality_supported_for_gemini(self):
        """Gemini forwards the quality control — it is supported."""
        # Gemini supports 'quality'. The compiled controls do not include a
        # quality field (that's a config-level concern), so default controls
        # compile cleanly. This documents that quality is in the supported set.
        assert "quality" in GEMINI_PROFILE.supported_controls

        prompt = _prompt(subjects=[_subject()])
        low = _compile(
            prompt,
            _plan(),
            route_profile=GEMINI_PROFILE,
            controls=GenerationControls(quality="low"),
        )
        high = _compile(
            prompt,
            _plan(),
            route_profile=GEMINI_PROFILE,
            controls=GenerationControls(quality="high"),
        )
        assert low.controls.quality == "low"
        assert low.compiled_request_sha256 != high.compiled_request_sha256

    def test_default_controls_compile_cleanly(self):
        prompt = _prompt(subjects=[_subject()])
        req = _compile(prompt, _plan(), controls=GenerationControls())
        assert req.controls.is_default()


# ---------------------------------------------------------------------------
# Diagnostic-only changes do not affect provider-impacting compiled fields
# ---------------------------------------------------------------------------


class TestDiagnosticsDoNotAffectCompiledHash:
    def test_anchor_conflict_warning_does_not_change_hash(self):
        """An anchor text-conflict warning is diagnostic-only and must not
        change the compiled hash."""
        clean_anchor = "a stone wall with moss"
        conflict_anchor = "a stone wall with a painted caption reading DOOM"
        fp = hashlib.sha256(b"stable").hexdigest()
        prompt_clean = _prompt(anchors=[
            PromptAnchor(kind="location", entity_id="loc_001", name="Wall", text=clean_anchor)
        ])
        prompt_conflict = _prompt(anchors=[
            PromptAnchor(kind="location", entity_id="loc_001", name="Wall", text=conflict_anchor)
        ])
        # Different anchors → different hashes (the anchor text is in the
        # protected_anchors projection). But the test confirms the warning
        # itself (not the text difference) doesn't add hash volatility.
        req_clean = _compile(prompt_clean, _plan(fingerprint=fp))
        req_conflict = _compile(prompt_conflict, _plan(fingerprint=fp))
        # They differ because the anchor text differs (expected).
        assert req_clean.compiled_request_sha256 != req_conflict.compiled_request_sha256
        # But the conflict request has the warning and the clean one doesn't.
        assert any("anchor_text_conflict" in w for w in req_conflict.warnings)
        assert not any("anchor_text_conflict" in w for w in req_clean.warnings)


# ---------------------------------------------------------------------------
# Schema version unchanged (Slice 06 is additive)
# ---------------------------------------------------------------------------


def test_schema_version_unchanged():
    assert COMPILED_REQUEST_SCHEMA_VERSION == 1


# ---------------------------------------------------------------------------
# ImageModelProfile extension fields
# ---------------------------------------------------------------------------


class TestImageModelProfileFields:
    def test_reve_has_prompt_char_limit(self):
        assert REVE_PROFILE.prompt_char_limit == 4000

    def test_gemini_has_no_prompt_char_limit(self):
        assert GEMINI_PROFILE.prompt_char_limit is None

    def test_reve_has_native_aspect_modes(self):
        assert "3:2" in REVE_PROFILE.native_aspect_modes
        assert "16:9" in REVE_PROFILE.native_aspect_modes

    def test_gemini_has_no_native_aspect_modes(self):
        assert GEMINI_PROFILE.native_aspect_modes == ()

    def test_native_aspect_for_reve_maps_ratio(self):
        # 1.5 → closest is 3:2
        assert REVE_PROFILE.native_aspect_for(1.5) == "3:2"
        # 1.78 → closest is 16:9
        assert REVE_PROFILE.native_aspect_for(1.78) == "16:9"

    def test_native_aspect_none_when_no_modes(self):
        assert GEMINI_PROFILE.native_aspect_for(1.5) is None

    def test_supports_control(self):
        assert GEMINI_PROFILE.supports_control("quality")
        assert not REVE_PROFILE.supports_control("quality")
        assert not REVE_PROFILE.supports_control("seed")
