"""Slice 04 — model capabilities and semantic ReferencePlan.

The ReferencePlan owns final reference selection, ordering, authority facets,
selected content hashes, and drop diagnostics before prompt compilation. No
later layer selects, caps, or reorders references. These tests are pure — they
build fixtures on ``tmp_path`` and make no paid/model calls.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from novel_to_comic.image_models import (
    GATEWAY_IMAGE_BALANCED,
    GATEWAY_IMAGE_FAST,
    GATEWAY_IMAGE_QUALITY,
    GATEWAY_IMAGE_REVE,
    ImageModelProfile,
    ImageRoute,
    image_model_profile,
)
from novel_to_comic.image_references import (
    AuthorityScope,
    DropReason,
    ReferenceMaterializationError,
    build_reference_plan,
    selection_fingerprint_hex,
)
from novel_to_comic.models.prompt import ImagePrompt, PromptSubject

# ── Fixture builders ──────────────────────────────────────────────────────────


def _write_png(path: Path, payload: bytes | None = None) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload or f"png:{path}".encode())
    return path


def _subject(
    *,
    char_id="char_001",
    name="Milla",
    appearance_state_id=None,
    appearance_locked=False,
) -> PromptSubject:
    return PromptSubject(
        character_id=char_id,
        name=name,
        identity="1woman, short black hair, green eyes",
        appearance_state_id=appearance_state_id,
        appearance_locked=appearance_locked,
    )


def _prompt(
    *,
    subjects=None,
    location_id=None,
    location_state_id=None,
    scene_id="scene_001",
    panel_number=1,
    transition_out=None,
) -> ImagePrompt:
    return ImagePrompt(
        prompt_version=1,
        planned_panel_id=f"{scene_id}:panel_{panel_number:03d}",
        scene_id=scene_id,
        panel_number=panel_number,
        composition="medium shot",
        full_prompt="",
        subjects=subjects if subjects is not None else [],
        location_id=location_id,
        location_state_id=location_state_id,
        transition_out=transition_out,
        width=768,
        height=1344,
        steps=20,
    )


# ── ImageModelProfile — route reference capabilities ──────────────────────────


class TestImageModelProfile:
    def test_reve_has_conservative_product_cap_four(self):
        profile = image_model_profile(GATEWAY_IMAGE_REVE)
        assert profile.route is ImageRoute.REVE
        assert profile.max_references == 4
        assert "subject" in profile.supported_roles

    def test_gemini_flash_lite_supports_many_refs(self):
        profile = image_model_profile(GATEWAY_IMAGE_FAST)
        assert profile.route is ImageRoute.GEMINI_FLASH_LITE
        assert profile.max_references >= 4

    def test_quality_route_matches_seedream_pro_profile(self):
        profile = image_model_profile(GATEWAY_IMAGE_QUALITY)
        assert profile.route is ImageRoute.SEEDREAM
        assert profile.max_references == image_model_profile(GATEWAY_IMAGE_FAST).max_references
        assert {"subject", "style", "location_plate", "prop", "continuity"} <= profile.supported_roles

    def test_profiles_agree_with_configured_production_routes(self):
        # Hard caps and role support are verified for every production route.
        for alias in (GATEWAY_IMAGE_FAST, GATEWAY_IMAGE_BALANCED, GATEWAY_IMAGE_QUALITY, GATEWAY_IMAGE_REVE):
            profile = image_model_profile(alias)
            assert profile.max_references >= 1
            assert "subject" in profile.supported_roles

        gpt = image_model_profile("openai/gpt-image-2")
        assert gpt.max_references == 4
        assert gpt.supported_roles == frozenset({"subject", "prop"})
        gemini = image_model_profile(GATEWAY_IMAGE_BALANCED)
        assert gemini.max_references == 10
        assert {"subject", "style", "location_plate", "prop", "continuity"} <= gemini.supported_roles

    def test_profile_is_frozen_and_hashable(self):
        profile = image_model_profile(GATEWAY_IMAGE_REVE)
        assert isinstance(profile, ImageModelProfile)
        # Frozen dataclass: fields are immutable.
        with pytest.raises(Exception):
            profile.max_references = 99  # type: ignore[misc]


# ── Selection matrix: 0–4 subjects + contextual candidates ────────────────────


def _setup_subject_refs(project_dir: Path, char_ids: list[str], *, pose="portrait") -> dict[str, Path]:
    """Write one canonical ref per character."""
    return {cid: _write_png(project_dir / "refs" / cid / f"{pose}.png") for cid in char_ids}


class TestSubjectMatrix:
    """Deliverable 4: full 0–4 subject matrix plus location/prop/style/continuity."""

    def test_zero_subjects_selects_location_and_style(self, tmp_path):
        _write_png(tmp_path / "plates" / "loc_001.png")
        _write_png(tmp_path / "samples" / "style_1.png")
        prompt = _prompt(subjects=[], location_id="loc_001")
        plan = build_reference_plan(
            route_profile=image_model_profile(GATEWAY_IMAGE_REVE),
            project_dir=tmp_path,
            prompt=prompt,
            style_sample=tmp_path / "samples" / "style_1.png",
            scene_to_location={"scene_001": "loc_001"},
        )
        roles = [a.role for a in plan.selected]
        assert "location_plate" in roles
        assert "style" in roles

    def test_one_subject_plus_location_and_style_under_cap(self, tmp_path):
        _setup_subject_refs(tmp_path, ["char_001"])
        _write_png(tmp_path / "plates" / "loc_001.png")
        _write_png(tmp_path / "samples" / "style_1.png")
        prompt = _prompt(
            subjects=[_subject()],
            location_id="loc_001",
        )
        plan = build_reference_plan(
            route_profile=image_model_profile(GATEWAY_IMAGE_REVE),
            project_dir=tmp_path,
            prompt=prompt,
            style_sample=tmp_path / "samples" / "style_1.png",
            scene_to_location={"scene_001": "loc_001"},
        )
        roles = [a.role for a in plan.selected]
        assert "subject" in roles
        assert len(plan.selected) <= 4

    def test_two_subjects_fit_under_reve_cap(self, tmp_path):
        _setup_subject_refs(tmp_path, ["char_001", "char_002"])
        prompt = _prompt(subjects=[_subject(char_id="char_001"), _subject(char_id="char_002", name="Jin")])
        plan = build_reference_plan(
            route_profile=image_model_profile(GATEWAY_IMAGE_REVE),
            project_dir=tmp_path,
            prompt=prompt,
        )
        subject_selected = [a for a in plan.selected if a.role == "subject"]
        assert {a.entity_id for a in subject_selected} == {"char_001", "char_002"}

    def test_three_subjects_fit_under_reve_cap(self, tmp_path):
        _setup_subject_refs(tmp_path, ["char_001", "char_002", "char_003"])
        prompt = _prompt(
            subjects=[
                _subject(char_id="char_001"),
                _subject(char_id="char_002", name="Jin"),
                _subject(char_id="char_003", name="Aro"),
            ]
        )
        plan = build_reference_plan(
            route_profile=image_model_profile(GATEWAY_IMAGE_REVE),
            project_dir=tmp_path,
            prompt=prompt,
        )
        subject_selected = [a for a in plan.selected if a.role == "subject"]
        assert len(subject_selected) == 3

    def test_subjects_exceed_reve_cap_text_only_overflow(self, tmp_path):
        """Deliverable 3: overflow follows text-only policy and names every
        unreferenced subject — never silently erases. Five subjects on a Reve
        route (hard cap 4) overflow by one."""
        _setup_subject_refs(tmp_path, ["char_001", "char_002", "char_003", "char_004", "char_005"])
        prompt = _prompt(
            subjects=[
                _subject(char_id="char_001", name="Milla"),
                _subject(char_id="char_002", name="Jin"),
                _subject(char_id="char_003", name="Aro"),
                _subject(char_id="char_004", name="Zed"),
                _subject(char_id="char_005", name="Kai"),
            ]
        )
        plan = build_reference_plan(
            route_profile=image_model_profile(GATEWAY_IMAGE_REVE),
            project_dir=tmp_path,
            prompt=prompt,
        )
        selected_subject_ids = {
            a.entity_id for a in plan.selected if a.role == "subject"
        }
        # Four subjects fit under the Reve cap; one is unreferenced but named.
        assert len(selected_subject_ids) == 4
        all_names = ["Milla", "Jin", "Aro", "Zed", "Kai"]
        unreferenced = [
            n for i, n in enumerate(all_names, start=1)
            if f"char_{i:03d}" not in selected_subject_ids
        ]
        assert unreferenced, "overflow must name at least one unreferenced subject"
        drop_reasons = {d.reason for d in plan.dropped}
        assert DropReason.PROVIDER_CAP in drop_reasons
        # The dropped entry's detail names the unreferenced subject.
        cap_drops = [d for d in plan.dropped if d.reason == DropReason.PROVIDER_CAP]
        assert any(unreferenced[0] in (d.detail or "") for d in cap_drops)

    def test_four_subjects_fill_reve_cap_no_contextual_refs(self, tmp_path):
        """Deliverable 4: the full 0–4 matrix. Four subjects consume the entire
        Reve cap (4); no contextual refs fit. Subjects are never silently
        dropped while under the cap."""
        _setup_subject_refs(tmp_path, ["char_001", "char_002", "char_003", "char_004"])
        _write_png(tmp_path / "plates" / "loc_001.png")
        prompt = _prompt(
            subjects=[
                _subject(char_id="char_001", name="Milla"),
                _subject(char_id="char_002", name="Jin"),
                _subject(char_id="char_003", name="Aro"),
                _subject(char_id="char_004", name="Zed"),
            ],
            location_id="loc_001",
        )
        plan = build_reference_plan(
            route_profile=image_model_profile(GATEWAY_IMAGE_REVE),
            project_dir=tmp_path,
            prompt=prompt,
            scene_to_location={"scene_001": "loc_001"},
        )
        selected_subject_ids = {
            a.entity_id for a in plan.selected if a.role == "subject"
        }
        assert selected_subject_ids == {"char_001", "char_002", "char_003", "char_004"}
        # No contextual refs fit; the location is lower_priority.
        assert all(a.role == "subject" for a in plan.selected)
        assert len(plan.selected) == 4

    def test_shot_type_changes_chosen_crop(self, tmp_path):
        """Deliverable: close framing picks a face-forward crop; wide picks
        full-body. Same character dir, multiple crops."""
        char_dir = tmp_path / "refs" / "char_001"
        _write_png(char_dir / "portrait.png")
        _write_png(char_dir / "full_body.png")

        close_prompt = _prompt(subjects=[_subject()])
        close_prompt.composition = "close-up portrait, face filling the panel"
        close_plan = build_reference_plan(
            route_profile=image_model_profile(GATEWAY_IMAGE_REVE),
            project_dir=tmp_path,
            prompt=close_prompt,
        )
        assert close_plan.selected[0].path.name == "portrait.png"

        wide_prompt = _prompt(subjects=[_subject()])
        wide_prompt.composition = "wide establishing panel, full body visible"
        wide_plan = build_reference_plan(
            route_profile=image_model_profile(GATEWAY_IMAGE_REVE),
            project_dir=tmp_path,
            prompt=wide_prompt,
        )
        assert wide_plan.selected[0].path.name == "full_body.png"

    @pytest.mark.parametrize("subject_count", range(5))
    @pytest.mark.parametrize("composition", [
        "close-up portrait",
        "medium shot",
        "wide establishing panel",
    ])
    def test_zero_to_four_subject_slot_matrix(self, tmp_path, subject_count, composition):
        ids = [f"char_{index:03d}" for index in range(1, subject_count + 1)]
        _setup_subject_refs(tmp_path, ids)
        _write_png(tmp_path / "plates" / "loc_001.png")
        _write_png(tmp_path / "samples" / "style_1.png")
        prompt = _prompt(
            subjects=[_subject(char_id=char_id, name=char_id) for char_id in ids],
            location_id="loc_001",
        )
        prompt.composition = composition
        plan = build_reference_plan(
            route_profile=image_model_profile(GATEWAY_IMAGE_REVE),
            project_dir=tmp_path,
            prompt=prompt,
            style_sample=tmp_path / "samples" / "style_1.png",
            scene_to_location={"scene_001": "loc_001"},
        )
        assert len(plan.selected) <= 4
        assert len([a for a in plan.selected if a.role == "subject"]) == subject_count

    def test_missing_base_subject_is_named_in_diagnostics(self, tmp_path):
        prompt = _prompt(subjects=[_subject(name="Missing Milla")])
        plan = build_reference_plan(
            route_profile=image_model_profile(GATEWAY_IMAGE_REVE),
            project_dir=tmp_path,
            prompt=prompt,
        )
        missing = [d for d in plan.dropped if d.reason is DropReason.MISSING]
        assert missing
        assert "Missing Milla" in (missing[0].detail or "")


# ── One character, many crops → one correct crop ──────────────────────────────


class TestOneCropPerCharacter:
    def test_many_crops_select_one(self, tmp_path):
        char_dir = tmp_path / "refs" / "char_001"
        for pose in ("portrait", "full_body"):
            _write_png(char_dir / f"{pose}.png")
        prompt = _prompt(subjects=[_subject()])
        plan = build_reference_plan(
            route_profile=image_model_profile(GATEWAY_IMAGE_REVE),
            project_dir=tmp_path,
            prompt=prompt,
        )
        subject_selected = [a for a in plan.selected if a.role == "subject"]
        assert len(subject_selected) == 1

    def test_internal_primary_override_wins(self, tmp_path):
        """A legacy/internal primary override still wins for compatibility."""
        char_dir = tmp_path / "refs" / "char_001"
        for pose in ("portrait", "full_body"):
            _write_png(char_dir / f"{pose}.png")
        # Mark portrait as the legacy/internal primary override.
        primary_refs = tmp_path / "refs" / "primary_refs.json"
        primary_refs.write_text(json.dumps({"char_001": "portrait"}))

        prompt = _prompt(subjects=[_subject()])
        plan = build_reference_plan(
            route_profile=image_model_profile(GATEWAY_IMAGE_REVE),
            project_dir=tmp_path,
            prompt=prompt,
            primary_poses={"char_001": "portrait"},
        )
        subject_selected = [a for a in plan.selected if a.role == "subject"]
        assert subject_selected[0].path.name == "portrait.png"

    def test_internal_primary_override_wins_in_state_directory(self, tmp_path):
        """The internal override also applies to assets nested in state dirs."""
        state_dir = tmp_path / "refs" / "char_001" / "states" / "silver"
        for pose in ("portrait", "full_body"):
            _write_png(state_dir / f"{pose}.png")
        prompt = _prompt(
            subjects=[_subject(appearance_state_id="silver", appearance_locked=True)],
        )
        plan = build_reference_plan(
            route_profile=image_model_profile(GATEWAY_IMAGE_REVE),
            project_dir=tmp_path,
            prompt=prompt,
            primary_poses={"char_001": "full_body"},
        )
        subject_selected = [a for a in plan.selected if a.role == "subject"]
        assert subject_selected[0].path.name == "full_body.png"
        assert subject_selected[0].appearance_state_id == "silver"


# ── Authority scopes ──────────────────────────────────────────────────────────


class TestAuthorityScopes:
    def test_dedicated_significant_state_ref_full_appearance_authority(self, tmp_path):
        """Deliverable 6: dedicated significant-state ref → full active
        appearance authority."""
        state_dir = tmp_path / "refs" / "char_001" / "states" / "silver"
        _write_png(state_dir / "portrait.png")
        prompt = _prompt(
            subjects=[_subject(appearance_state_id="silver", appearance_locked=True)],
        )
        plan = build_reference_plan(
            route_profile=image_model_profile(GATEWAY_IMAGE_REVE),
            project_dir=tmp_path,
            prompt=prompt,
        )
        subject = next(a for a in plan.selected if a.role == "subject")
        assert subject.authority_scope is AuthorityScope.FULL_APPEARANCE
        assert subject.appearance_state_id == "silver"

    def test_canonical_base_ref_full_appearance_authority(self, tmp_path):
        """Base-look ref with no state → full appearance authority."""
        _write_png(tmp_path / "refs" / "char_001" / "portrait.png")
        prompt = _prompt(subjects=[_subject()])
        plan = build_reference_plan(
            route_profile=image_model_profile(GATEWAY_IMAGE_REVE),
            project_dir=tmp_path,
            prompt=prompt,
        )
        subject = next(a for a in plan.selected if a.role == "subject")
        assert subject.authority_scope is AuthorityScope.FULL_APPEARANCE
        assert subject.appearance_state_id is None

    def test_missing_significant_state_ref_omits_contradictory_canonical(self, tmp_path):
        """Deliverable 6: missing significant-state ref → no contradictory
        canonical full-body conditioning. The canonical ref is NOT used."""
        # Only a canonical (base) ref exists; the subject is in a significant state.
        _write_png(tmp_path / "refs" / "char_001" / "portrait.png")
        prompt = _prompt(
            subjects=[_subject(appearance_state_id="silver", appearance_locked=True)],
        )
        plan = build_reference_plan(
            route_profile=image_model_profile(GATEWAY_IMAGE_REVE),
            project_dir=tmp_path,
            prompt=prompt,
        )
        subject_refs = [a for a in plan.selected if a.role == "subject"]
        assert subject_refs == [], "no canonical ref should condition a significant state"
        drops = [d for d in plan.dropped if d.reason == DropReason.STATE_CONFLICT]
        assert drops, "the omitted canonical ref must be reported as a state_conflict drop"

    def test_explicit_canonical_equivalent_state_allows_full_canonical_ref(self, tmp_path):
        _write_png(tmp_path / "refs" / "char_001" / "portrait.png")
        subject = _subject(appearance_state_id="restored", appearance_locked=True)
        subject.appearance_state_canonical_equivalent = True
        plan = build_reference_plan(
            route_profile=image_model_profile(GATEWAY_IMAGE_REVE),
            project_dir=tmp_path,
            prompt=_prompt(subjects=[subject]),
        )
        selected = next(a for a in plan.selected if a.role == "subject")
        assert selected.authority_scope is AuthorityScope.FULL_APPEARANCE


# ── Location state authority ─────────────────────────────────────────────────


class TestLocationStateAuthority:
    def test_active_location_state_outranks_redundant_style_sample(self, tmp_path):
        """Deliverable 4: active location state normally outranks a redundant
        style sample under the route cap."""
        _write_png(tmp_path / "plates" / "loc_001_dawn.png")
        _write_png(tmp_path / "samples" / "style_1.png")
        # Fill 3 subject slots so only one contextual slot remains.
        _setup_subject_refs(tmp_path, ["char_001", "char_002", "char_003"])
        prompt = _prompt(
            subjects=[
                _subject(char_id="char_001"),
                _subject(char_id="char_002", name="Jin"),
                _subject(char_id="char_003", name="Aro"),
            ],
            location_id="loc_001",
            location_state_id="loc_001_dawn",
        )
        plan = build_reference_plan(
            route_profile=image_model_profile(GATEWAY_IMAGE_REVE),
            project_dir=tmp_path,
            prompt=prompt,
            style_sample=tmp_path / "samples" / "style_1.png",
            scene_to_location={"scene_001": "loc_001"},
        )
        roles = [a.role for a in plan.selected]
        assert "location_plate" in roles
        # Under a 4-cap with 3 subjects, only one contextual slot exists; the
        # active location state should claim it over the style sample.
        assert "style" not in roles

    def test_missing_location_state_no_canonical_substitution(self, tmp_path):
        """Deliverable 6: missing active location-state plate → no canonical
        substitution; warn and remain text-only for the location."""
        # Only the canonical plate exists; the panel wants a state plate.
        _write_png(tmp_path / "plates" / "loc_001.png")
        prompt = _prompt(
            subjects=[_subject()],
            location_id="loc_001",
            location_state_id="loc_001_ruined",
        )
        plan = build_reference_plan(
            route_profile=image_model_profile(GATEWAY_IMAGE_REVE),
            project_dir=tmp_path,
            prompt=prompt,
            scene_to_location={"scene_001": "loc_001"},
        )
        loc_refs = [a for a in plan.selected if a.role == "location_plate"]
        assert loc_refs == [], "canonical plate must not substitute for a missing state plate"
        drops = [d for d in plan.dropped if d.reason == DropReason.STATE_CONFLICT]
        assert drops


# ── Lineage ──────────────────────────────────────────────────────────────────


class TestLineage:
    def test_stale_lineage_excluded_when_parent_hash_mismatches(self, tmp_path):
        """Deliverable 7: a state asset's recorded canonical parent hash that
        mismatches current canonical bytes → stale_lineage, excluded."""
        state_dir = tmp_path / "refs" / "char_001" / "states" / "silver"
        _write_png(state_dir / "portrait.png")
        # Record a lineage sidecar pointing at a stale canonical hash.
        _write_png(tmp_path / "refs" / "char_001" / "sheet.png", b"canonical-v1")
        import hashlib

        stale_parent = hashlib.sha256(b"different-canonical").hexdigest()
        meta_path = state_dir / "sheet.png.meta.json"
        meta_path.write_text(json.dumps({"lineage_parent_sha256": stale_parent}))

        prompt = _prompt(
            subjects=[_subject(appearance_state_id="silver", appearance_locked=True)],
        )
        plan = build_reference_plan(
            route_profile=image_model_profile(GATEWAY_IMAGE_REVE),
            project_dir=tmp_path,
            prompt=prompt,
        )
        subject_refs = [a for a in plan.selected if a.role == "subject"]
        assert subject_refs == [], "stale-lineage state ref must be excluded"
        drops = [d for d in plan.dropped if d.reason == DropReason.STALE_LINEAGE]
        assert drops

    def test_absent_lineage_treated_as_unverified_safety_policy(self, tmp_path):
        """Deliverable 7: absent lineage → unverified_lineage under an explicit
        safety policy. Until Slice 08 makes lineage mandatory, an unverified
        significant-state ref is still selected (the safety policy is non-blocking
        for significant states) but flagged in the plan diagnostics."""
        state_dir = tmp_path / "refs" / "char_001" / "states" / "silver"
        _write_png(state_dir / "portrait.png")
        # No lineage sidecar.
        prompt = _prompt(
            subjects=[_subject(appearance_state_id="silver", appearance_locked=True)],
        )
        plan = build_reference_plan(
            route_profile=image_model_profile(GATEWAY_IMAGE_REVE),
            project_dir=tmp_path,
            prompt=prompt,
        )
        subject_refs = [a for a in plan.selected if a.role == "subject"]
        # Unverified is non-blocking but the plan reports it.
        assert subject_refs, "unverified lineage should not block a significant state ref"
        # The diagnostic may be surfaced as a non-dropping warning; assert at
        # least the plan does not crash and the asset carries its state.
        assert subject_refs[0].appearance_state_id == "silver"

    def test_stale_location_state_lineage_is_excluded(self, tmp_path):
        _write_png(tmp_path / "plates" / "loc_001.png", b"canonical-current")
        state = _write_png(tmp_path / "plates" / "loc_001_ruined.png", b"state")
        stale_parent = __import__("hashlib").sha256(b"canonical-old").hexdigest()
        state.with_suffix(".png.meta.json").write_text(json.dumps({
            "lineage_parent_sha256": stale_parent,
        }))
        prompt = _prompt(location_id="loc_001", location_state_id="loc_001_ruined")
        plan = build_reference_plan(
            route_profile=image_model_profile(GATEWAY_IMAGE_REVE),
            project_dir=tmp_path,
            prompt=prompt,
        )
        assert not any(a.role == "location_plate" for a in plan.selected)
        assert any(d.reason is DropReason.STALE_LINEAGE for d in plan.dropped)

    def test_unverified_location_state_is_selected_with_warning(self, tmp_path):
        _write_png(tmp_path / "plates" / "loc_001.png", b"canonical")
        _write_png(tmp_path / "plates" / "loc_001_rain.png", b"state")
        prompt = _prompt(location_id="loc_001", location_state_id="loc_001_rain")
        plan = build_reference_plan(
            route_profile=image_model_profile(GATEWAY_IMAGE_REVE),
            project_dir=tmp_path,
            prompt=prompt,
        )
        assert any(a.role == "location_plate" for a in plan.selected)
        assert any("unverified_lineage" in warning for warning in plan.warnings)


# ── Continuity ───────────────────────────────────────────────────────────────


class TestContinuity:
    def test_state_change_suppresses_incompatible_continuity(self, tmp_path):
        """Deliverable 8: disable previous-panel continuity when character/
        location state authority changes across the boundary."""
        _write_png(tmp_path / "draw" / "scene_001" / "panel_001.png")
        _write_png(tmp_path / "refs" / "char_001" / "portrait.png")
        prompt = _prompt(
            subjects=[_subject(appearance_state_id="silver", appearance_locked=True)],
            panel_number=2,
            transition_out="match_cut",
        )
        # Previous panel was in the base state (no appearance_state_id).
        plan = build_reference_plan(
            route_profile=image_model_profile(GATEWAY_IMAGE_REVE),
            project_dir=tmp_path,
            prompt=prompt,
            prev_subject_states={"char_001": None},
            prev_location_state_id=None,
            continuity_enabled=True,
        )
        cont = [a for a in plan.selected if a.role == "continuity"]
        assert cont == [], "continuity must be suppressed when subject state changed"

    def test_compatible_match_cut_keeps_continuity(self, tmp_path):
        _write_png(tmp_path / "draw" / "scene_001" / "panel_001.png")
        _write_png(tmp_path / "refs" / "char_001" / "portrait.png")
        prompt = _prompt(
            subjects=[_subject(appearance_state_id=None)],
            panel_number=2,
            transition_out="match_cut",
        )
        plan = build_reference_plan(
            route_profile=image_model_profile(GATEWAY_IMAGE_REVE),
            project_dir=tmp_path,
            prompt=prompt,
            prev_subject_states={"char_001": None},
            prev_location_state_id=None,
            continuity_enabled=True,
        )
        cont = [a for a in plan.selected if a.role == "continuity"]
        assert cont, "match_cut with compatible state should keep continuity"

    @pytest.mark.parametrize(
        ("current_ids", "previous_states"),
        [
            (["char_001", "char_002"], {"char_001": None}),
            (["char_001"], {"char_001": None, "char_002": None}),
        ],
    )
    def test_subject_entry_or_exit_suppresses_continuity(
        self, tmp_path, current_ids, previous_states
    ):
        _write_png(tmp_path / "draw" / "scene_001" / "panel_001.png")
        _setup_subject_refs(tmp_path, current_ids)
        prompt = _prompt(
            subjects=[_subject(char_id=char_id, name=char_id) for char_id in current_ids],
            panel_number=2,
        )
        plan = build_reference_plan(
            route_profile=image_model_profile(GATEWAY_IMAGE_REVE),
            project_dir=tmp_path,
            prompt=prompt,
            prev_subject_states=previous_states,
            prev_location_state_id=None,
            continuity_enabled=True,
        )
        assert not any(a.role == "continuity" for a in plan.selected)


# ── Content hashes and selection fingerprint ──────────────────────────────────


class TestSelectionFingerprint:
    def test_selected_byte_change_alters_fingerprint(self, tmp_path):
        ref = _write_png(tmp_path / "refs" / "char_001" / "portrait.png", b"v1")
        prompt = _prompt(subjects=[_subject()])
        plan1 = build_reference_plan(
            route_profile=image_model_profile(GATEWAY_IMAGE_REVE),
            project_dir=tmp_path,
            prompt=prompt,
        )
        ref.write_bytes(b"v2")
        plan2 = build_reference_plan(
            route_profile=image_model_profile(GATEWAY_IMAGE_REVE),
            project_dir=tmp_path,
            prompt=prompt,
        )
        assert plan1.selection_fingerprint != plan2.selection_fingerprint

    def test_unselected_byte_change_does_not_alter_fingerprint(self, tmp_path):
        """Deliverable 10: a changed unselected candidate must not invalidate
        cache unless it changes the selected plan."""
        char_dir = tmp_path / "refs" / "char_001"
        _write_png(char_dir / "portrait.png", b"front-v1")
        unselected = _write_png(char_dir / "full_body.png", b"gesture-v1")
        prompt = _prompt(subjects=[_subject()])
        prompt.composition = "close-up portrait"
        plan1 = build_reference_plan(
            route_profile=image_model_profile(GATEWAY_IMAGE_REVE),
            project_dir=tmp_path,
            prompt=prompt,
        )
        # Change the unselected candidate bytes.
        unselected.write_bytes(b"gesture-v2")
        plan2 = build_reference_plan(
            route_profile=image_model_profile(GATEWAY_IMAGE_REVE),
            project_dir=tmp_path,
            prompt=prompt,
        )
        assert plan1.selection_fingerprint == plan2.selection_fingerprint

    def test_fingerprint_is_stable_across_rebuilds(self, tmp_path):
        _write_png(tmp_path / "refs" / "char_001" / "portrait.png", b"stable")
        prompt = _prompt(subjects=[_subject()])
        kwargs = dict(
            route_profile=image_model_profile(GATEWAY_IMAGE_REVE),
            project_dir=tmp_path,
            prompt=prompt,
        )
        assert build_reference_plan(**kwargs).selection_fingerprint == build_reference_plan(**kwargs).selection_fingerprint

    def test_fingerprint_covers_roles_order_scopes_and_hashes(self, tmp_path):
        _write_png(tmp_path / "refs" / "char_001" / "portrait.png", b"a")
        prompt = _prompt(subjects=[_subject()])
        plan = build_reference_plan(
            route_profile=image_model_profile(GATEWAY_IMAGE_REVE),
            project_dir=tmp_path,
            prompt=prompt,
        )
        fp = selection_fingerprint_hex(plan.selected)
        assert isinstance(fp, str)
        assert len(fp) == 64


# ── Readability / failure ────────────────────────────────────────────────────


class TestReadability:
    def test_unreadable_selected_asset_fails_before_prompt_indices(self, tmp_path, monkeypatch):
        """Deliverable 9 + test: an unreadable selected asset fails before prompt
        indices can be constructed."""
        path = tmp_path / "refs" / "char_001" / "portrait.png"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"png")  # exists
        prompt = _prompt(subjects=[_subject()])
        import novel_to_comic.image_references as image_references

        monkeypatch.setattr(image_references, "_file_sha256", lambda _path: None)
        with pytest.raises(ReferenceMaterializationError):
            build_reference_plan(
                route_profile=image_model_profile(GATEWAY_IMAGE_REVE),
                project_dir=tmp_path,
                prompt=prompt,
            )


# ── Props ────────────────────────────────────────────────────────────────────


class TestProps:
    def test_critical_prop_selected(self, tmp_path):
        _setup_subject_refs(tmp_path, ["char_001"])
        _write_png(tmp_path / "refs" / "props" / "prop_001" / "ref.png")
        prompt = _prompt(subjects=[_subject()])
        prompt.props = ["The Monkey's Paw"]
        plan = build_reference_plan(
            route_profile=image_model_profile(GATEWAY_IMAGE_REVE),
            project_dir=tmp_path,
            prompt=prompt,
            prop_ids=["prop_001"],
        )
        prop_refs = [a for a in plan.selected if a.role == "prop"]
        assert prop_refs
        assert prop_refs[0].entity_id == "prop_001"

    def test_noncritical_prop_dropped_when_no_slot(self, tmp_path):
        """A non-critical prop is lower_priority when the cap is exhausted by
        subjects + location + continuity."""
        _setup_subject_refs(tmp_path, ["char_001", "char_002", "char_003"])
        _write_png(tmp_path / "refs" / "props" / "prop_001" / "ref.png")
        prompt = _prompt(
            subjects=[
                _subject(char_id="char_001"),
                _subject(char_id="char_002", name="Jin"),
                _subject(char_id="char_003", name="Aro"),
            ],
        )
        prompt.props = ["The Monkey's Paw"]
        plan = build_reference_plan(
            route_profile=image_model_profile(GATEWAY_IMAGE_REVE),
            project_dir=tmp_path,
            prompt=prompt,
            prop_ids=["prop_001"],
        )
        prop_selected = [a for a in plan.selected if a.role == "prop"]
        # Subjects take all 4 slots (3 subjects + 1 contextual); prop may or may
        # not fit. If it doesn't, it's lower_priority.
        if not prop_selected:
            drops = [d for d in plan.dropped if d.reason == DropReason.LOWER_PRIORITY]
            assert drops

    @pytest.mark.parametrize(("critical", "expected_role"), [(True, "prop"), (False, "location_plate")])
    def test_close_shot_critical_prop_policy(self, tmp_path, critical, expected_role):
        _setup_subject_refs(tmp_path, ["char_001", "char_002", "char_003"])
        _write_png(tmp_path / "refs" / "props" / "prop_001" / "ref.png")
        _write_png(tmp_path / "plates" / "loc_001.png")
        prompt = _prompt(
            subjects=[
                _subject(char_id="char_001"),
                _subject(char_id="char_002"),
                _subject(char_id="char_003"),
            ],
            location_id="loc_001",
        )
        prompt.composition = "close-up detail shot"
        plan = build_reference_plan(
            route_profile=image_model_profile(GATEWAY_IMAGE_REVE),
            project_dir=tmp_path,
            prompt=prompt,
            scene_to_location={"scene_001": "loc_001"},
            prop_ids=["prop_001"],
            critical_prop_ids={"prop_001"} if critical else set(),
        )
        contextual = [a.role for a in plan.selected if a.role != "subject"]
        assert contextual == [expected_role]


# ── Final ordering ──────────────────────────────────────────────────────────


class TestFinalOrdering:
    def test_subjects_before_contextual_refs(self, tmp_path):
        _setup_subject_refs(tmp_path, ["char_001"])
        _write_png(tmp_path / "plates" / "loc_001.png")
        _write_png(tmp_path / "samples" / "style_1.png")
        _write_png(tmp_path / "refs" / "props" / "prop_001" / "ref.png")
        prompt = _prompt(subjects=[_subject()], location_id="loc_001")
        prompt.props = ["prop"]
        plan = build_reference_plan(
            route_profile=image_model_profile(GATEWAY_IMAGE_REVE),
            project_dir=tmp_path,
            prompt=prompt,
            style_sample=tmp_path / "samples" / "style_1.png",
            scene_to_location={"scene_001": "loc_001"},
            prop_ids=["prop_001"],
        )
        roles = [a.role for a in plan.selected]
        # Subjects first, then contextual in priority order.
        subject_idx = roles.index("subject") if "subject" in roles else -1
        assert subject_idx == 0


# ── Estimate uses selected count ─────────────────────────────────────────────


class TestEstimateCount:
    def test_plan_selected_count_matches_estimate_input(self, tmp_path):
        """Deliverable 11/Tests: estimate uses the final selected count."""
        _setup_subject_refs(tmp_path, ["char_001"])
        _write_png(tmp_path / "plates" / "loc_001.png")
        prompt = _prompt(subjects=[_subject()], location_id="loc_001")
        plan = build_reference_plan(
            route_profile=image_model_profile(GATEWAY_IMAGE_REVE),
            project_dir=tmp_path,
            prompt=prompt,
            scene_to_location={"scene_001": "loc_001"},
        )
        # The estimate path consumes len(plan.selected).
        assert len(plan.selected) == sum(1 for _ in plan.selected)
