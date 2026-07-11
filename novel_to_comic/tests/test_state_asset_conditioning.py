"""Slice 09: canonical-conditioned character and location state assets.

State assets (alternate character sheets / location plates) must derive from
compatible canonical identity through the shared reference/compiler/wire path,
with the active state overriding mutable facts. Tests mock all provider I/O.
"""

from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path

import pytest

from novel_to_comic import artifacts
from novel_to_comic.config import Config
from novel_to_comic.models.appearance import AppearanceState
from novel_to_comic.models.story_bible import Character, Location
from novel_to_comic.state_assets import (
    LineageMode,
    LineageStatus,
    build_character_state_spec,
    build_location_state_spec,
    revalidate_state_asset_lineage,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _character() -> Character:
    return Character(
        id="char_001", name="Mara",
        visual_anchor="Mara, age 30, long black hair, two natural hands",
        age_range="early 30s", gender="woman",
        distinguishing_features=["scar over left eyebrow"],
        default_outfit="red wool coat", first_appearance_scene="scene_001",
    )


def _location() -> Location:
    return Location(
        id="loc_001", name="Lake House",
        visual_anchor="stone lake house, intact slate roof, full blue lake, sunny noon",
        time_of_day="noon", mood="peaceful",
    )


def _write_parent(parent: Path, data: bytes = b"canonical-parent-bytes") -> str:
    parent.parent.mkdir(parents=True, exist_ok=True)
    parent.write_bytes(data)
    return hashlib.sha256(data).hexdigest()


def _write_style(project_dir: Path, data: bytes = b"style-sample-bytes") -> tuple[Path, str]:
    style_path = project_dir / "style_sample.png"
    style_path.write_bytes(data)
    return style_path, hashlib.sha256(data).hexdigest()


def _write_minimal_png(path: Path) -> None:
    """Write a valid 4x4 PNG so _crop_sheet_to_poses can crop quadrants."""
    from PIL import Image
    Image.new("RGB", (4, 4), (128, 128, 128)).save(path)


# ---------------------------------------------------------------------------
# Character state conditioning
# ---------------------------------------------------------------------------


def test_character_state_plan_has_canonical_identity_then_style(tmp_path: Path):
    """A character state request receives canonical identity and style in the
    final plan order with compatible facet instructions."""
    from novel_to_comic.state_assets import build_state_reference_plan

    char = _character()
    parent = artifacts.character_ref_sheet_path(tmp_path, char.id)
    parent_hash = _write_parent(parent)
    style_path, style_hash = _write_style(tmp_path)
    state = AppearanceState(
        id="silver", label="Silver hands",
        visual_anchor="Mara, age 30, long black hair, silver prosthetic hands, red coat",
        visually_significant=True,
    )
    spec = build_character_state_spec(
        Config(), tmp_path, char, state, style_path=style_path,
    )
    plan = build_state_reference_plan(spec, tmp_path)

    roles = [asset.role for asset in plan.selected]
    assert "subject" in roles  # canonical identity present
    subject = next(a for a in plan.selected if a.role == "subject")
    assert subject.entity_id == char.id
    assert subject.authority_scope.value == "identity_only"
    # Canonical identity preserves compatible facets (face/hair/build) and
    # ignores the overridden facets (anatomy).
    assert "anatomy" in subject.ignore_facets
    assert subject.content_sha256 == parent_hash
    # Style present where space permits, ordered after the subject.
    if "style" in roles:
        style_asset = next(a for a in plan.selected if a.role == "style")
        assert style_asset.content_sha256 == style_hash
        assert roles.index("subject") < roles.index("style")


@pytest.mark.parametrize(
    "anchor, expected_conflict_facet",
    [
        ("Mara with no hands, healed wrist stumps", "anatomy"),
        ("Mara, age 70, white hair, weathered skin", "age"),
        ("Mara with silver prosthetic hands replacing her natural ones", "anatomy"),
        ("Mara with short cropped blue hair", "hair"),
        ("Mara wearing a green silk gown instead of her coat", "wardrobe"),
    ],
)
def test_character_states_contain_no_contradictory_canonical_matching_rule(
    tmp_path: Path, anchor: str, expected_conflict_facet: str,
):
    from novel_to_comic.state_assets import build_state_reference_plan

    char = _character()
    parent = artifacts.character_ref_sheet_path(tmp_path, char.id)
    _write_parent(parent)
    state = AppearanceState(id="s1", label="S", visual_anchor=anchor, visually_significant=True)
    spec = build_character_state_spec(Config(), tmp_path, char, state)
    plan = build_state_reference_plan(spec, tmp_path)

    subject = next(a for a in plan.selected if a.role == "subject")
    assert expected_conflict_facet in subject.ignore_facets


def test_character_total_transformation_omits_canonical_parent(tmp_path: Path):
    """A total transformation with no compatible facets omits the canonical
    parent and records the conflict rather than sending a contradictory image."""
    from novel_to_comic.state_assets import build_state_reference_plan
    from novel_to_comic.image_references import DropReason

    char = _character()
    parent = artifacts.character_ref_sheet_path(tmp_path, char.id)
    _write_parent(parent)
    # Total transformation: every facet (age, hair, anatomy, clothing) replaced.
    state = AppearanceState(
        id="beast", label="Transformed beast",
        visual_anchor=(
            "Mara transformed into a winged serpent beast, scaled body, tail, "
            "no hair, no human face, no clothing, feral anatomy"
        ),
        visually_significant=True,
    )
    spec = build_character_state_spec(Config(), tmp_path, char, state)
    plan = build_state_reference_plan(spec, tmp_path)

    subject_roles = [a.role for a in plan.selected if a.role == "subject"]
    assert subject_roles == [], "total transformation must not include canonical parent"
    drops = [d for d in plan.dropped if d.reason == DropReason.STATE_CONFLICT]
    assert drops, "total transformation must record a state_conflict drop"
    assert spec.lineage_mode == LineageMode.STATE_ONLY


# ---------------------------------------------------------------------------
# Location state conditioning
# ---------------------------------------------------------------------------


def test_location_state_plan_has_location_identity_reference(tmp_path: Path):
    from novel_to_comic.state_assets import build_state_reference_plan

    loc = _location()
    parent = artifacts.location_plate_path(tmp_path, loc.id)
    parent_hash = _write_parent(parent)
    style_path, _ = _write_style(tmp_path)
    state = AppearanceState(
        id="loc_001_dusk", label="Dusk",
        visual_anchor="stone lake house, intact slate roof, full blue lake at dusk",
        visually_significant=True,
    )
    spec = build_location_state_spec(Config(), tmp_path, loc, state, style_path=style_path)
    plan = build_state_reference_plan(spec, tmp_path)

    plate = next((a for a in plan.selected if a.role == "location_plate"), None)
    assert plate is not None
    assert plate.content_sha256 == parent_hash


@pytest.mark.parametrize(
    "anchor",
    [
        "collapsed stone walls, roof gone, rubble everywhere",
        "drained cracked lakebed, dry mud, no water",
        "flooded lake house, water up to the roofline",
        "lake house at night, moonlit, dark sky",
        "lake house in a thunderstorm, heavy rain, dark clouds",
    ],
)
def test_location_active_anchor_wins_over_canonical_facets(tmp_path: Path, anchor: str):
    from novel_to_comic.state_assets import build_state_reference_plan

    loc = _location()
    parent = artifacts.location_plate_path(tmp_path, loc.id)
    _write_parent(parent)
    state = AppearanceState(id="loc_001_s", label="S", visual_anchor=anchor, visually_significant=True)
    spec = build_location_state_spec(Config(), tmp_path, loc, state)
    plan = build_state_reference_plan(spec, tmp_path)

    # The canonical plate may be present but must defer to the active anchor.
    plate = next((a for a in plan.selected if a.role == "location_plate"), None)
    if plate is not None:
        # The compiled instruction must state the active anchor wins.
        from novel_to_comic.compiled_request import compile_reference_instruction
        instr = compile_reference_instruction(plate, 0)
        assert "active" in instr.semantic_instruction.lower() or "wins" in instr.semantic_instruction.lower()


def test_location_total_destruction_omits_canonical_parent(tmp_path: Path):
    from novel_to_comic.state_assets import build_state_reference_plan
    from novel_to_comic.image_references import DropReason

    loc = _location()
    parent = artifacts.location_plate_path(tmp_path, loc.id)
    _write_parent(parent)
    # Total destruction: architecture, water, weather, light, atmosphere all replaced.
    state = AppearanceState(
        id="loc_001_gone", label="Annihilated",
        visual_anchor=(
            "smoking crater where the house stood, scorched earth, ash-filled sky, "
            "no walls, no roof, no lake, toxic haze, everything destroyed"
        ),
        visually_significant=True,
    )
    spec = build_location_state_spec(Config(), tmp_path, loc, state)
    plan = build_state_reference_plan(spec, tmp_path)

    plate_roles = [a.role for a in plan.selected if a.role == "location_plate"]
    assert plate_roles == []
    assert any(d.reason == DropReason.STATE_CONFLICT for d in plan.dropped)
    assert spec.lineage_mode == LineageMode.STATE_ONLY


# ---------------------------------------------------------------------------
# Cap priority and missing-parent failure
# ---------------------------------------------------------------------------


def test_tight_cap_drops_style_before_canonical_identity(tmp_path: Path):
    """Under a tight provider cap, style is dropped before canonical identity
    and the drop is reported."""
    from novel_to_comic.image_models import ImageModelProfile, ImageRoute
    from novel_to_comic.state_assets import build_state_reference_plan

    char = _character()
    parent = artifacts.character_ref_sheet_path(tmp_path, char.id)
    _write_parent(parent)
    style_path, _ = _write_style(tmp_path)
    state = AppearanceState(
        id="silver", label="Silver hands",
        visual_anchor="Mara, age 30, long black hair, silver hands, red coat",
        visually_significant=True,
    )
    spec = build_character_state_spec(Config(), tmp_path, char, state, style_path=style_path)

    # Cap of 1: only the canonical identity fits.
    tight_profile = ImageModelProfile(
        route=ImageRoute.REVE, max_references=1,
        supported_roles=frozenset({"subject", "style"}),
        prompt_char_limit=4000, native_aspect_modes=("1:1",),
        supported_controls=frozenset(),
    )
    plan = build_state_reference_plan(spec, tmp_path, route_profile=tight_profile)

    selected_roles = [a.role for a in plan.selected]
    assert "subject" in selected_roles
    assert "style" not in selected_roles
    assert any(
        d.candidate.role == "style" for d in plan.dropped
        if d.reason.value in ("provider_cap", "lower_priority")
    )


def test_missing_canonical_parent_fails_before_provider_io(tmp_path: Path):
    """A missing canonical parent blocks conditioned state generation with a
    structured error; no provider I/O occurs."""
    from novel_to_comic.state_assets import StateConditioningError, build_state_reference_plan

    char = _character()
    # NOTE: deliberately do NOT write the parent sheet.
    state = AppearanceState(
        id="silver", label="Silver hands",
        visual_anchor="Mara, age 30, long black hair, silver hands, red coat",
        visually_significant=True,
    )
    spec = build_character_state_spec(Config(), tmp_path, char, state)
    with pytest.raises(StateConditioningError) as exc_info:
        build_state_reference_plan(spec, tmp_path)
    assert "canonical parent" in str(exc_info.value).lower()


def test_digest_mismatched_canonical_parent_fails_before_provider_io(tmp_path: Path):
    """A parent whose bytes don't match the recorded digest fails before I/O."""
    from novel_to_comic.state_assets import StateConditioningError, build_state_reference_plan

    char = _character()
    parent = artifacts.character_ref_sheet_path(tmp_path, char.id)
    _write_parent(parent, b"original-bytes")
    state = AppearanceState(
        id="silver", label="Silver hands",
        visual_anchor="Mara, age 30, long black hair, silver hands, red coat",
        visually_significant=True,
    )
    spec = build_character_state_spec(Config(), tmp_path, char, state)
    # Now corrupt the parent after the spec captured the hash.
    parent.write_bytes(b"different-bytes")
    with pytest.raises(StateConditioningError):
        build_state_reference_plan(spec, tmp_path)


# ---------------------------------------------------------------------------
# Metadata and lineage mode
# ---------------------------------------------------------------------------


def test_state_metadata_records_lineage_mode_conditioned(tmp_path: Path):
    from novel_to_comic.state_assets import build_state_reference_plan

    char = _character()
    parent = artifacts.character_ref_sheet_path(tmp_path, char.id)
    parent_hash = _write_parent(parent)
    style_path, style_hash = _write_style(tmp_path)
    state = AppearanceState(
        id="silver", label="Silver hands",
        visual_anchor="Mara, age 30, long black hair, silver hands, red coat",
        visually_significant=True,
    )
    spec = build_character_state_spec(Config(), tmp_path, char, state, style_path=style_path)
    build_state_reference_plan(spec, tmp_path)
    meta = spec.lineage_metadata()

    assert meta["lineage_mode"] == LineageMode.CONDITIONED
    assert meta["canonical_parent_sha256"] == parent_hash
    assert meta["style_sha256"] == style_hash
    assert meta["lineage_status"] == LineageStatus.CURRENT


def test_state_only_metadata_records_exception(tmp_path: Path):
    from novel_to_comic.state_assets import build_state_reference_plan

    char = _character()
    parent = artifacts.character_ref_sheet_path(tmp_path, char.id)
    parent_hash = _write_parent(parent)
    state = AppearanceState(
        id="beast", label="Beast",
        visual_anchor=(
            "Mara transformed into a winged serpent beast, scaled body, tail, "
            "no hair, no human face, no clothing"
        ),
        visually_significant=True,
    )
    spec = build_character_state_spec(Config(), tmp_path, char, state)
    build_state_reference_plan(spec, tmp_path)
    meta = spec.lineage_metadata()

    assert meta["lineage_mode"] == LineageMode.STATE_ONLY
    # Parent hash retained as semantic lineage even though not sent.
    assert meta["canonical_parent_sha256"] == parent_hash


# ---------------------------------------------------------------------------
# Wire transport: references reach the wire with exact order and hashes
# ---------------------------------------------------------------------------


def test_state_wire_carries_canonical_reference_and_hashes(tmp_path: Path, monkeypatch):
    from novel_to_comic.stages.s3_cast import _generate_state_asset_wire
    from novel_to_comic.usage import ApiResult

    char = _character()
    parent = artifacts.character_ref_sheet_path(tmp_path, char.id)
    _write_parent(parent)
    style_path, _ = _write_style(tmp_path)
    state = AppearanceState(
        id="silver", label="Silver hands",
        visual_anchor="SENTINEL Mara, age 30, long black hair, silver hands, red coat",
        visually_significant=True,
    )
    spec = build_character_state_spec(Config(), tmp_path, char, state, style_path=style_path)
    captured = {}

    async def fake_generate_wire_image(*, config, wire, output_path, feature):
        captured["wire"] = wire
        captured["references"] = wire.references
        output_path.write_bytes(b"state-image")
        return ApiResult(value=output_path)

    monkeypatch.setattr("novel_to_comic.ai.generate_wire_image", fake_generate_wire_image)
    out = tmp_path / "state.png"
    asyncio.run(_generate_state_asset_wire(Config(), spec, out, tmp_path, feature="test"))

    wire = captured["wire"]
    refs = wire.references
    assert len(refs) >= 1
    assert "SENTINEL Mara" in wire.prompt_parts[0]
    # Canonical identity is first (lowest index / strongest positional weight).
    assert refs[0].role == "subject"
    assert refs[0].authority_scope == "identity_only"
    assert "anatomy" in refs[0].ignore_facets
    assert wire.compiled_request_sha256
    assert wire.execution_fingerprint


def test_state_only_wire_has_no_canonical_reference(tmp_path: Path, monkeypatch):
    from novel_to_comic.stages.s3_cast import _generate_state_asset_wire
    from novel_to_comic.usage import ApiResult

    char = _character()
    parent = artifacts.character_ref_sheet_path(tmp_path, char.id)
    _write_parent(parent)
    state = AppearanceState(
        id="beast", label="Beast",
        visual_anchor="SENTINEL winged serpent beast, no human face, no clothing",
        visually_significant=True,
    )
    spec = build_character_state_spec(Config(), tmp_path, char, state)
    captured = {}

    async def fake_generate_wire_image(*, config, wire, output_path, feature):
        captured["wire"] = wire
        output_path.write_bytes(b"state-image")
        return ApiResult(value=output_path)

    monkeypatch.setattr("novel_to_comic.ai.generate_wire_image", fake_generate_wire_image)
    asyncio.run(_generate_state_asset_wire(
        Config(), spec, tmp_path / "state.png", tmp_path, feature="test",
    ))

    wire = captured["wire"]
    assert wire.references == ()
    assert "SENTINEL winged serpent" in wire.prompt_parts[0]


# ---------------------------------------------------------------------------
# Persisted metadata: the s3_cast wire path records conditioned metadata
# ---------------------------------------------------------------------------


def test_regenerate_character_state_persists_conditioned_metadata(tmp_path: Path, monkeypatch):
    """The persisted .meta.json records lineage_mode=conditioned (not the stale
    unconditioned snapshot captured before the wire mutates the spec)."""
    from novel_to_comic.config import save_config
    from novel_to_comic.stages.s3_cast import regenerate_character_state_ref
    from novel_to_comic.usage import ApiResult

    char = _character()
    parent = artifacts.character_ref_sheet_path(tmp_path, char.id)
    _write_parent(parent)
    state = AppearanceState(
        id="silver", label="Silver hands",
        visual_anchor="Mara, age 30, long black hair, silver hands, red coat",
        visually_significant=True,
    )
    char.appearance_states = [state]
    # Write a story bible so regenerate_character_state_ref can read the char.
    from novel_to_comic.models.story_bible import StoryBible
    artifacts.write_story_bible(tmp_path, StoryBible(
        title="T", author="A", total_scenes=1,
        characters=[char], locations=[], props=[],
        scenes=[], narrative_arcs=[],
    ))
    config = Config()
    save_config(config, tmp_path)

    async def fake_generate_wire_image(*, config, wire, output_path, feature):
        # Write a valid 1x1 PNG so _crop_sheet_to_poses can open it.
        _write_minimal_png(output_path)
        return ApiResult(value=output_path)

    monkeypatch.setattr("novel_to_comic.ai.generate_wire_image", fake_generate_wire_image)
    import asyncio
    asyncio.run(regenerate_character_state_ref(config, tmp_path, char.id, state.id))

    sheet = artifacts.character_state_ref_sheet_path(tmp_path, char.id, state.id)
    meta = artifacts.read_asset_meta(sheet)
    assert meta["lineage_mode"] == "conditioned"
    assert meta["lineage_status"] == "current"
    assert meta["reference_summary"]  # non-empty
    assert meta["compiled_request_sha256"]  # set by the wire


def test_generate_location_state_persists_conditioned_metadata(tmp_path: Path, monkeypatch):
    """The persisted location-state plate records lineage_mode=conditioned."""
    from novel_to_comic.config import save_config
    from novel_to_comic.stages.s3_cast import regenerate_location_plate
    from novel_to_comic.usage import ApiResult

    loc = _location()
    parent = artifacts.location_plate_path(tmp_path, loc.id)
    _write_parent(parent)
    state = AppearanceState(
        id="loc_001_dusk", label="Dusk",
        visual_anchor="stone lake house, intact slate roof, full blue lake at dusk",
        visually_significant=True,
    )
    loc.appearance_states = [state]
    from novel_to_comic.models.story_bible import StoryBible
    artifacts.write_story_bible(tmp_path, StoryBible(
        title="T", author="A", total_scenes=1,
        characters=[], locations=[loc], props=[],
        scenes=[], narrative_arcs=[],
    ))
    config = Config()
    save_config(config, tmp_path)

    async def fake_generate_wire_image(*, config, wire, output_path, feature):
        output_path.write_bytes(b"plate-image")
        return ApiResult(value=output_path)

    monkeypatch.setattr("novel_to_comic.ai.generate_wire_image", fake_generate_wire_image)
    import asyncio
    asyncio.run(regenerate_location_plate(config, tmp_path, loc.id, state_id=state.id))

    plate = artifacts.location_state_plate_path(tmp_path, loc.id, state.id)
    meta = artifacts.read_asset_meta(plate)
    assert meta["lineage_mode"] == "conditioned"
    assert meta["lineage_status"] == "current"


# ---------------------------------------------------------------------------
# Stale lineage: no silent auto-spend, restored version currency
# ---------------------------------------------------------------------------


def test_canonical_reroll_keeps_states_stale_no_auto_spend(tmp_path: Path, monkeypatch):
    """When a user regenerates a canonical asset, dependent states stay stale
    until explicitly regenerated. No automatic paid cascade."""
    from novel_to_comic.state_assets import mark_dependent_states_stale

    char = _character()
    parent = artifacts.character_ref_sheet_path(tmp_path, char.id)
    _write_parent(parent, b"v1")
    state_sheet = artifacts.character_state_ref_sheet_path(tmp_path, char.id, "silver")
    _write_parent(state_sheet, b"state-v1")
    state = AppearanceState(
        id="silver", label="Silver hands",
        visual_anchor="Mara, age 30, long black hair, silver hands, red coat",
        visually_significant=True,
    )
    spec = build_character_state_spec(Config(), tmp_path, char, state)
    artifacts.write_asset_meta(state_sheet, spec.lineage_metadata())

    # Simulate canonical reroll.
    parent.write_bytes(b"v2")
    warnings = mark_dependent_states_stale(tmp_path, "character", char.id)
    assert len(warnings) == 1

    meta = artifacts.read_asset_meta(state_sheet)
    assert meta["lineage_status"] == LineageStatus.STALE


def test_restored_version_current_only_when_parent_hash_matches(tmp_path: Path):
    """A restored state version is current only when its parent hash still
    matches the canonical bytes."""
    loc = _location()
    parent = artifacts.location_plate_path(tmp_path, loc.id)
    _write_parent(parent, b"canonical")
    state_plate = artifacts.location_state_plate_path(tmp_path, loc.id, "loc_001_night")
    state_plate.write_bytes(b"state")

    # Metadata with matching parent hash → stays current.
    artifacts.write_asset_meta(state_plate, {
        "entity_id": loc.id, "state_id": "loc_001_night",
        "canonical_parent_sha256": hashlib.sha256(b"canonical").hexdigest(),
        "lineage_mode": "conditioned", "lineage_status": "current",
    })
    meta = revalidate_state_asset_lineage(state_plate, parent)
    assert meta["lineage_status"] == LineageStatus.CURRENT

    # Now the parent changes → restored version becomes stale.
    parent.write_bytes(b"new-canonical")
    meta = revalidate_state_asset_lineage(state_plate, parent)
    assert meta["lineage_status"] == LineageStatus.STALE


# ---------------------------------------------------------------------------
# Provider-boundary: no paid calls
# ---------------------------------------------------------------------------


def test_no_paid_image_call_during_conditioning(tmp_path: Path, monkeypatch):
    """The reference plan builder and wire compiler make no network calls; all
    provider transport is mocked."""
    from novel_to_comic.state_assets import build_state_reference_plan

    char = _character()
    parent = artifacts.character_ref_sheet_path(tmp_path, char.id)
    _write_parent(parent)
    state = AppearanceState(
        id="silver", label="Silver hands",
        visual_anchor="Mara, age 30, long black hair, silver hands, red coat",
        visually_significant=True,
    )
    spec = build_character_state_spec(Config(), tmp_path, char, state)

    def _boom(*args, **kwargs):
        raise AssertionError("no network call should occur during plan building")

    monkeypatch.setattr("novel_to_comic.ai.client.generate_image", _boom)
    monkeypatch.setattr("novel_to_comic.ai.generate_wire_image", _boom)
    plan = build_state_reference_plan(spec, tmp_path)
    assert plan.selected  # conditioning produced a plan without I/O
