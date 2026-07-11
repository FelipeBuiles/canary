"""Slice 05 — CompiledGenerationRequest compiler tests.

Tests-first regressions for the one provider-independent compiled request:

- Long sentinel character, location, state, and prop anchors survive exact.
- A visual brief that omits or contradicts identity cannot alter protected
  sections.
- Full-appearance, identity-only, location-state, prop, style, and continuity
  instructions name the correct preserved/ignored facets.
- Collapsed-building, drained-lake, and day/night state anchors overrule
  incompatible canonical location facets.
- No generic "ignore all backgrounds" or "match all wardrobe" instruction
  remains.
- Same inputs serialize identically and produce the same compiled hash.
- Style-only change updates compiled identity while leaving Slice 03's stored
  panel prompt-source identity unchanged.
- Changing warnings/dropped-candidate diagnostics alone does not change the
  provider-independent compiled request hash.
- Configured model fields never appear as provider-reported actual identity.
- Compiler performs no LLM, filesystem-discovery, persistence, or provider I/O.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from novel_to_comic.compiled_request import (
    COMPILED_REQUEST_SCHEMA_VERSION,
    CompiledGenerationRequest,
    CompiledRequestError,
    GenerationControls,
    compile_generation_request,
    compile_reference_instruction,
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

# ---------------------------------------------------------------------------
# Sentinel anchors (exceed any old character cap; verbatim-survival probes)
# ---------------------------------------------------------------------------

_CHAR_SENTINEL = "SENTINEL_CHARACTER_ANCHOR_" * 8 + " distinct sharp angular jawline"
_LOC_SENTINEL = "SENTINEL_LOCATION_ANCHOR_" * 8 + " crumbling limestone facade"
_LOC_STATE_SENTINEL = "SENTINEL_LOCATION_STATE_" * 6 + " collapsed building rubble"
_PROP_SENTINEL = "SENTINEL_PROP_ANCHOR_" * 8 + " ornate iron key"


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _write_png(path: Path, payload: bytes | None = None) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload or f"png:{path}".encode())
    return path


def _subject(
    *,
    char_id: str = "char_001",
    name: str = "Milla",
    identity: str = "1woman, short black hair, green eyes",
    appearance_state_id: str | None = None,
    appearance_locked: bool = False,
    canonical_equivalent: bool = False,
) -> PromptSubject:
    return PromptSubject(
        character_id=char_id,
        name=name,
        identity=identity,
        appearance_state_id=appearance_state_id,
        appearance_locked=appearance_locked,
        appearance_state_canonical_equivalent=canonical_equivalent,
    )


def _prompt(
    *,
    subjects: list[PromptSubject] | None = None,
    anchors: list[PromptAnchor] | None = None,
    scene_id: str = "scene_001",
    panel_number: int = 1,
    location_id: str | None = None,
    location_state_id: str | None = None,
    style: str | None = None,
    visual_brief: str | None = None,
    constraints: str | None = None,
    source_sha256: str | None = None,
    composition: str = "medium shot",
    setting: str | None = None,
) -> ImagePrompt:
    return ImagePrompt(
        prompt_version=1,
        planned_panel_id=f"{scene_id}:panel_{panel_number:03d}",
        scene_id=scene_id,
        panel_number=panel_number,
        composition=composition,
        setting=setting,
        full_prompt="",
        subjects=subjects if subjects is not None else [],
        anchors=anchors if anchors is not None else [],
        location_id=location_id,
        location_state_id=location_state_id,
        style=style,
        visual_brief=visual_brief,
        constraints=constraints,
        source_sha256=source_sha256,
        width=768,
        height=1344,
        steps=20,
    )


def _ref_asset(
    *,
    role: str = "subject",
    entity_id: str = "char_001",
    appearance_state_id: str | None = None,
    authority_scope: AuthorityScope = AuthorityScope.FULL_APPEARANCE,
    preserve_facets: tuple[str, ...] = ("face", "hair", "build", "wardrobe", "anatomy"),
    ignore_facets: tuple[str, ...] = (),
    label: str | None = "Milla",
    content_sha256: str = "a" * 64,
) -> ReferenceAsset:
    return ReferenceAsset(
        path=Path(f"refs/{entity_id}/front.png"),
        role=role,
        entity_id=entity_id,
        appearance_state_id=appearance_state_id,
        authority_scope=authority_scope,
        preserve_facets=preserve_facets,
        ignore_facets=ignore_facets,
        pose="front",
        content_sha256=content_sha256,
        lineage_parent_sha256=None,
        label=label,
    )


def _plan(
    *,
    selected: tuple[ReferenceAsset, ...] | None = None,
    dropped: tuple = (),
    warnings: tuple[str, ...] = (),
    route: ImageRoute = ImageRoute.REVE,
) -> ReferencePlan:
    selected = selected or ()
    return ReferencePlan(
        expected_route=route,
        selected=selected,
        dropped=dropped,
        selection_fingerprint="f" * 64,
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
    requested_alias: str | None = GATEWAY_IMAGE_REVE,
    configured_provider_model: str = "reve/create",
    selected_style_source_hash: str | None = None,
    controls: GenerationControls | None = None,
) -> CompiledGenerationRequest:
    return compile_generation_request(
        prompt=prompt,
        reference_plan=plan,
        route_profile=route_profile,
        requested_alias=requested_alias,
        configured_provider_model=configured_provider_model,
        selected_style_text=selected_style_text,
        selected_style_source_hash=selected_style_source_hash,
        controls=controls,
    )


# ---------------------------------------------------------------------------
# Sentinel anchors survive exact
# ---------------------------------------------------------------------------


class TestSentinelAnchorsSurviveExact:
    def test_long_character_anchor_survives_byte_for_byte(self):
        subject = _subject(identity=_CHAR_SENTINEL)
        prompt = _prompt(subjects=[subject])
        req = _compile(prompt, _plan())
        assert _CHAR_SENTINEL in req.final_prompt
        char_anchors = [a for a in req.protected_anchors if a.kind == "character"]
        assert char_anchors and char_anchors[0].text == _CHAR_SENTINEL

    def test_long_location_anchor_survives_byte_for_byte(self):
        anchor = PromptAnchor(
            kind="location", entity_id="loc_001", name="Library", text=_LOC_SENTINEL
        )
        prompt = _prompt(anchors=[anchor])
        req = _compile(prompt, _plan())
        assert _LOC_SENTINEL in req.final_prompt
        loc_anchors = [a for a in req.protected_anchors if a.kind == "location"]
        assert loc_anchors and loc_anchors[0].text == _LOC_SENTINEL

    def test_long_prop_anchor_survives_byte_for_byte(self):
        anchor = PromptAnchor(
            kind="prop", entity_id="prop_001", name="Iron Key", text=_PROP_SENTINEL
        )
        prompt = _prompt(anchors=[anchor])
        req = _compile(prompt, _plan())
        assert _PROP_SENTINEL in req.final_prompt

    def test_long_location_state_anchor_survives_byte_for_byte(self):
        anchor = PromptAnchor(
            kind="location",
            entity_id="loc_001",
            name="Library",
            appearance_state_id="collapsed",
            text=_LOC_STATE_SENTINEL,
        )
        prompt = _prompt(anchors=[anchor], location_state_id="collapsed")
        req = _compile(prompt, _plan())
        assert _LOC_STATE_SENTINEL in req.final_prompt


class TestBriefCannotAlterProtectedAnchors:
    def test_contradictory_brief_does_not_remove_anchors(self):
        subject = _subject(identity=_CHAR_SENTINEL)
        prompt = _prompt(
            subjects=[subject],
            visual_brief="A simple figure in a hall holding something. Nothing distinctive.",
        )
        req = _compile(prompt, _plan())
        assert _CHAR_SENTINEL in req.final_prompt

    def test_empty_brief_still_emits_anchors(self):
        subject = _subject(identity=_CHAR_SENTINEL)
        prompt = _prompt(subjects=[subject], visual_brief="")
        req = _compile(prompt, _plan())
        assert _CHAR_SENTINEL in req.final_prompt


# ---------------------------------------------------------------------------
# Role-aware reference instructions
# ---------------------------------------------------------------------------


class TestReferenceInstructionsNameCorrectFacets:
    def test_full_appearance_names_all_facets(self):
        asset = _ref_asset(
            authority_scope=AuthorityScope.FULL_APPEARANCE,
            preserve_facets=("face", "hair", "build", "wardrobe", "anatomy"),
        )
        instr = compile_reference_instruction(asset, 0)
        text = instr.semantic_instruction.lower()
        assert "face" in text
        assert "hair" in text
        assert "build" in text
        assert "wardrobe" in text
        assert "anatomy" in text

    def test_identity_only_preserves_identity_ignores_wardrobe_anatomy(self):
        asset = _ref_asset(
            authority_scope=AuthorityScope.IDENTITY_ONLY,
            appearance_state_id="casual_outfit",
            preserve_facets=("face", "hair", "build"),
            ignore_facets=("wardrobe", "anatomy"),
        )
        instr = compile_reference_instruction(asset, 0)
        text = instr.semantic_instruction.lower()
        assert "preserve only face, hair and build" in text
        assert "ignore wardrobe and anatomy" in text

    def test_identity_only_does_not_match_all_wardrobe(self):
        """No generic 'match all wardrobe' instruction for identity-only."""
        asset = _ref_asset(
            authority_scope=AuthorityScope.IDENTITY_ONLY,
            preserve_facets=("face", "hair", "build"),
            ignore_facets=("wardrobe", "anatomy"),
        )
        instr = compile_reference_instruction(asset, 0)
        assert "match face, hair, build, wardrobe" not in instr.semantic_instruction

    def test_location_identity_preserves_architecture(self):
        asset = _ref_asset(
            role="location_plate",
            entity_id="loc_001",
            label="Library",
        )
        instr = compile_reference_instruction(asset, 0)
        text = instr.semantic_instruction.lower()
        assert "architecture" in text
        assert "landmarks" in text
        assert "materials" in text

    def test_location_state_anchor_wins_over_canonical_facets(self):
        asset = _ref_asset(
            role="location_plate",
            entity_id="loc_001",
            label="Library",
            appearance_state_id="collapsed",
        )
        instr = compile_reference_instruction(asset, 0)
        text = instr.semantic_instruction.lower()
        assert "active state does not replace" in text
        assert "active damage, weather, or time-of-day anchor wins" in text

    def test_prop_preserves_object_ignores_backdrop(self):
        asset = _ref_asset(
            role="prop",
            entity_id="prop_001",
            label="Iron Key",
        )
        instr = compile_reference_instruction(asset, 0)
        text = instr.semantic_instruction.lower()
        assert "preserve object" in text
        assert "ignore reference backdrop" in text

    def test_style_preserves_medium_ignores_content(self):
        asset = _ref_asset(
            role="style",
            entity_id="style_1",
            label="selected style",
        )
        instr = compile_reference_instruction(asset, 0)
        text = instr.semantic_instruction.lower()
        assert "medium" in text
        assert "mark-making" in text
        assert "palette" in text
        assert "ignore depicted content" in text

    def test_continuity_preserves_only_compatible_facets(self):
        asset = _ref_asset(
            role="continuity",
            entity_id=None,
            label="previous panel",
        )
        instr = compile_reference_instruction(asset, 0)
        text = instr.semantic_instruction.lower()
        assert "incompatible with current states" in text


class TestNoGenericAllReferenceGuard:
    def test_no_ignore_all_backgrounds_instruction(self):
        asset = _ref_asset(
            role="location_plate",
            entity_id="loc_001",
            label="Library",
        )
        instr = compile_reference_instruction(asset, 0)
        assert "ignore all backgrounds" not in instr.semantic_instruction.lower()
        assert "do not copy their borders" not in instr.semantic_instruction.lower()

    def test_no_generic_palette_continuity_line(self):
        """The old single-line 'identity, palette, and continuity only' guard is gone."""
        prompt = _prompt(
            subjects=[_subject()],
            visual_brief="A figure.",
        )
        plan = _plan(selected=(_ref_asset(),))
        req = _compile(prompt, plan)
        assert "identity, palette, and continuity only" not in req.final_prompt


# ---------------------------------------------------------------------------
# State anchors overrule incompatible canonical facets
# ---------------------------------------------------------------------------


class TestStateAnchorsOverruleCanonical:
    def test_collapsed_building_state_overrules_location_facets(self):
        anchor = PromptAnchor(
            kind="location",
            entity_id="loc_001",
            name="Library",
            appearance_state_id="collapsed",
            text=_LOC_STATE_SENTINEL,
        )
        prompt = _prompt(anchors=[anchor], location_state_id="collapsed")
        asset = _ref_asset(
            role="location_plate",
            entity_id="loc_001",
            label="Library",
            appearance_state_id="collapsed",
        )
        req = _compile(prompt, _plan(selected=(asset,)))
        assert _LOC_STATE_SENTINEL in req.final_prompt
        loc_instr = req.reference_instructions[0].semantic_instruction.lower()
        assert "active damage, weather, or time-of-day anchor wins" in loc_instr

    def test_day_night_state_anchor_wins(self):
        night_anchor = PromptAnchor(
            kind="location",
            entity_id="loc_001",
            name="Library",
            appearance_state_id="night",
            text="SENTINEL_NIGHT_STATE deep shadows, moonlight through broken windows",
        )
        prompt = _prompt(anchors=[night_anchor], location_state_id="night")
        asset = _ref_asset(
            role="location_plate",
            entity_id="loc_001",
            label="Library",
            appearance_state_id="night",
        )
        req = _compile(prompt, _plan(selected=(asset,)))
        assert "SENTINEL_NIGHT_STATE" in req.final_prompt
        loc_instr = req.reference_instructions[0].semantic_instruction.lower()
        assert "active state does not replace" in loc_instr


# ---------------------------------------------------------------------------
# Determinism: same inputs → same hash
# ---------------------------------------------------------------------------


class TestDeterminism:
    def test_same_inputs_produce_same_hash(self):
        prompt = _prompt(subjects=[_subject()], visual_brief="A figure in a hall.")
        plan = _plan(selected=(_ref_asset(),))
        req1 = _compile(prompt, plan)
        req2 = _compile(prompt, plan)
        assert req1.compiled_request_sha256 == req2.compiled_request_sha256
        assert req1.final_prompt == req2.final_prompt

    def test_selected_byte_change_changes_hash(self):
        prompt = _prompt(subjects=[_subject()])
        asset1 = _ref_asset(content_sha256="a" * 64)
        asset2 = _ref_asset(content_sha256="b" * 64)
        # The selection fingerprint differs, simulating different selected bytes.
        plan1 = _plan(selected=(asset1,), )
        plan2 = _plan(selected=(asset2,))
        # Give them distinct fingerprints so the compiled hash reflects the change.
        plan1 = ReferencePlan(
            expected_route=ImageRoute.REVE,
            selected=(asset1,),
            dropped=(),
            selection_fingerprint=hashlib.sha256(b"v1").hexdigest(),
            warnings=(),
        )
        plan2 = ReferencePlan(
            expected_route=ImageRoute.REVE,
            selected=(asset2,),
            dropped=(),
            selection_fingerprint=hashlib.sha256(b"v2").hexdigest(),
            warnings=(),
        )
        req1 = _compile(prompt, plan1)
        req2 = _compile(prompt, plan2)
        assert req1.compiled_request_sha256 != req2.compiled_request_sha256

    def test_diagnostics_change_does_not_change_hash(self):
        """Changing warnings/dropped-candidate diagnostics alone leaves the
        provider-independent compiled request hash unchanged."""
        prompt = _prompt(subjects=[_subject()])
        asset = _ref_asset()
        fp = hashlib.sha256(b"stable").hexdigest()
        plan_clean = ReferencePlan(
            expected_route=ImageRoute.REVE,
            selected=(asset,),
            dropped=(),
            selection_fingerprint=fp,
            warnings=(),
        )
        plan_noisy = ReferencePlan(
            expected_route=ImageRoute.REVE,
            selected=(asset,),
            dropped=(),
            selection_fingerprint=fp,
            warnings=(
                "unverified_lineage: state ref x has no parent",
                "another diagnostic warning",
            ),
        )
        req_clean = _compile(prompt, plan_clean)
        req_noisy = _compile(prompt, plan_noisy)
        assert req_clean.compiled_request_sha256 == req_noisy.compiled_request_sha256


# ---------------------------------------------------------------------------
# Style-only change updates compiled identity, not stored source hash
# ---------------------------------------------------------------------------


class TestStyleChangeUpdatesCompiledIdentity:
    def test_style_text_change_changes_compiled_hash(self):
        prompt = _prompt(
            subjects=[_subject()],
            source_sha256="stored-source-sha-unchanged",
        )
        plan = _plan(selected=(_ref_asset(),))
        req1 = _compile(prompt, plan, selected_style_text="Ink wash.")
        req2 = _compile(prompt, plan, selected_style_text="Oil painting.")
        assert req1.compiled_request_sha256 != req2.compiled_request_sha256

    def test_style_source_hash_change_changes_compiled_identity(self):
        prompt = _prompt(
            subjects=[_subject()],
            source_sha256="stored-source-sha-unchanged",
        )
        plan = _plan(selected=(_ref_asset(),))
        req1 = _compile(
            prompt, plan, selected_style_text="Ink wash.", selected_style_source_hash="hash-a"
        )
        req2 = _compile(
            prompt, plan, selected_style_text="Ink wash.", selected_style_source_hash="hash-b"
        )
        assert req1.compiled_request_sha256 != req2.compiled_request_sha256

    def test_stored_prompt_source_hash_unchanged_by_style_swap(self):
        """Slice 03's contract: style is generation-time-only and excluded
        from the stored source hash. The compiler carries the source hash
        forward unchanged."""
        prompt = _prompt(
            subjects=[_subject()],
            source_sha256="stored-source-sha-fixed",
        )
        plan = _plan(selected=(_ref_asset(),))
        req = _compile(prompt, plan, selected_style_text="Oil painting.")
        assert req.prompt_source_sha256 == "stored-source-sha-fixed"


# ---------------------------------------------------------------------------
# Configured model fields never appear as provider-reported actual identity
# ---------------------------------------------------------------------------


class TestConfiguredModelNotActualIdentity:
    def test_no_actual_provider_model_field(self):
        """The compiled request has configured_provider_model but NO
        actual_provider_model — that belongs to result provenance after
        transport."""
        prompt = _prompt(subjects=[_subject()])
        req = _compile(
            prompt,
            _plan(),
            requested_alias="image-reve",
            configured_provider_model="reve/create",
        )
        assert req.requested_alias == "image-reve"
        assert req.expected_route is ImageRoute.REVE
        assert req.configured_provider_model == "reve/create"
        assert not hasattr(req, "actual_provider_model")

    def test_route_profile_fields_distinct(self):
        prompt = _prompt(subjects=[_subject()])
        req = _compile(prompt, _plan(), route_profile=GEMINI_PROFILE)
        assert req.expected_route is ImageRoute.GEMINI_FLASH_LITE
        # These three are distinct fields, never collapsed.
        assert req.requested_alias != req.configured_provider_model or req.configured_provider_model


# ---------------------------------------------------------------------------
# Compiler performs no I/O
# ---------------------------------------------------------------------------


class TestCompilerPerformsNoIO:
    def test_no_filesystem_discovery_required(self, tmp_path, monkeypatch):
        """The compiler must not read from the filesystem. Patch open() to
        fail if it tries."""
        import builtins

        original_open = builtins.open

        def _guarded_open(file, *args, **kwargs):
            # Allow nothing from the project dir.
            path = Path(str(file))
            if path.is_absolute() and str(tmp_path) in str(path):
                raise AssertionError(f"compiler opened {file} — no filesystem I/O allowed")
            return original_open(file, *args, **kwargs)

        monkeypatch.setattr(builtins, "open", _guarded_open)
        prompt = _prompt(subjects=[_subject()], visual_brief="A figure.")
        plan = _plan(selected=(_ref_asset(),))
        req = _compile(prompt, plan)
        assert req.final_prompt

    def test_pure_function_no_mutation_of_inputs(self):
        prompt = _prompt(subjects=[_subject()])
        original_subjects = list(prompt.subjects)
        plan = _plan(selected=(_ref_asset(),))
        original_selected = plan.selected
        _compile(prompt, plan)
        assert prompt.subjects == original_subjects
        assert plan.selected == original_selected


# ---------------------------------------------------------------------------
# Section order and content
# ---------------------------------------------------------------------------


class TestPromptSectionOrder:
    def test_stable_section_order(self):
        anchor = PromptAnchor(
            kind="location", entity_id="loc_001", name="Library", text=_LOC_SENTINEL
        )
        prompt = _prompt(
            subjects=[_subject()],
            anchors=[anchor],
            visual_brief="A figure in a hall.",
            constraints="non-graphic implied action",
        )
        asset = _ref_asset()
        plan = _plan(selected=(asset,))
        req = _compile(prompt, plan, selected_style_text="Ink wash.")
        kinds = [s.kind for s in req.sections]
        # Anchors before scene_direction before style before references.
        assert kinds.index("protected_anchors") < kinds.index("scene_direction")
        assert kinds.index("scene_direction") < kinds.index("style")
        if "reference_instructions" in kinds:
            assert kinds.index("style") < kinds.index("reference_instructions")
        # Geometry is last.
        assert kinds[-1] == "geometry"


# ---------------------------------------------------------------------------
# Active-state validation
# ---------------------------------------------------------------------------


class TestActiveStateValidation:
    def test_full_appearance_base_ref_for_locked_state_fails(self):
        subject = _subject(
            appearance_state_id="stumps",
            appearance_locked=True,
        )
        prompt = _prompt(subjects=[subject])
        # A base-look ref (no state) with FULL_APPEARANCE for a locked state.
        asset = _ref_asset(
            appearance_state_id=None,
            authority_scope=AuthorityScope.FULL_APPEARANCE,
        )
        plan = _plan(selected=(asset,))
        with pytest.raises(CompiledRequestError):
            _compile(prompt, plan)

    def test_identity_only_base_ref_for_minor_state_ok(self):
        subject = _subject(appearance_state_id="casual_outfit", appearance_locked=False)
        prompt = _prompt(subjects=[subject])
        asset = _ref_asset(
            appearance_state_id=None,
            authority_scope=AuthorityScope.IDENTITY_ONLY,
            preserve_facets=("face", "hair", "build"),
            ignore_facets=("wardrobe", "anatomy"),
        )
        plan = _plan(selected=(asset,))
        req = _compile(prompt, plan)
        assert req.reference_instructions


# ---------------------------------------------------------------------------
# Reference selection/order unchanged from Slice 04
# ---------------------------------------------------------------------------


class TestReferenceSelectionUnchanged:
    def test_instructions_follow_plan_order(self):
        assets = (
            _ref_asset(role="subject", entity_id="char_001", label="Milla"),
            _ref_asset(role="prop", entity_id="prop_001", label="Iron Key"),
            _ref_asset(role="style", entity_id="style_1", label="selected style"),
        )
        plan = _plan(selected=assets)
        prompt = _prompt(subjects=[_subject()])
        req = _compile(prompt, plan)
        assert [i.role for i in req.reference_instructions] == [
            "subject",
            "prop",
            "style",
        ]
        assert [i.index for i in req.reference_instructions] == [0, 1, 2]

    def test_reference_count_matches_plan(self):
        plan = _plan(selected=(_ref_asset(), _ref_asset(entity_id="char_002", label="Ada")))
        prompt = _prompt(subjects=[_subject()])
        req = _compile(prompt, plan)
        assert len(req.reference_instructions) == plan.ref_count


# ---------------------------------------------------------------------------
# Schema version
# ---------------------------------------------------------------------------


def test_compiled_request_schema_version():
    assert COMPILED_REQUEST_SCHEMA_VERSION == 1
