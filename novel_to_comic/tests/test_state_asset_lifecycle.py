"""Slice 08: alternate-state asset lifecycle and lineage."""

from pathlib import Path

from novel_to_comic import artifacts
from novel_to_comic.config import Config
from novel_to_comic.models.appearance import AppearanceState
from novel_to_comic.models.story_bible import Character, Location
from novel_to_comic.state_assets import (
    LineageStatus,
    build_character_state_spec,
    build_location_state_spec,
    mark_dependent_states_stale,
    revalidate_state_asset_lineage,
)


def _character() -> Character:
    return Character(
        id="char_001", name="Mara", visual_anchor="Mara, age 30, long black hair, two natural hands",
        age_range="early 30s", gender="woman", distinguishing_features=["scar over left eyebrow"],
        default_outfit="red wool coat", first_appearance_scene="scene_001",
    )


def _location() -> Location:
    return Location(
        id="loc_001", name="Lake House",
        visual_anchor="stone lake house, intact slate roof, full blue lake, sunny noon",
        time_of_day="noon", mood="peaceful",
    )


def test_character_state_spec_uses_exact_anchor_without_base_outfit_or_hands(tmp_path: Path):
    char = _character()
    state = AppearanceState(
        id="older_stumps", label="Older without hands",
        visual_anchor="Mara, age 70, cropped white hair, healed wrist stumps, black tunic",
        visually_significant=True,
        continuity_guard="No hands; never depict gripping or a hand-raised gesture",
    )
    spec = build_character_state_spec(Config(), tmp_path, char, state)

    assert state.visual_anchor in spec.rendered_prompt
    assert spec.active_state_anchor == state.visual_anchor
    assert char.default_outfit not in spec.rendered_prompt
    assert "one hand raised" not in spec.rendered_prompt.lower()
    assert "hand-raised" not in spec.rendered_prompt.lower()
    assert {"age", "hair", "anatomy", "clothing"} <= set(spec.overridden_facets)
    assert spec.state_addendum_revision == 0


def test_location_state_wins_over_mutable_canonical_facets(tmp_path: Path):
    loc = _location()
    state = AppearanceState(
        id="loc_001_storm_ruin", label="Storm ruin",
        visual_anchor="collapsed stone walls, roof gone, drained cracked lakebed, stormy moonlit night",
        visually_significant=True,
    )
    spec = build_location_state_spec(Config(), tmp_path, loc, state)

    assert state.visual_anchor in spec.rendered_prompt
    for contradiction in ("intact slate roof", "full blue lake", "sunny noon", "peaceful"):
        assert contradiction not in spec.rendered_prompt
    assert {"architecture", "damage", "water_level", "weather", "light", "atmosphere"} <= set(spec.overridden_facets)


def test_state_addenda_are_isolated_from_canonical(tmp_path: Path):
    canonical = artifacts.character_ref_instructions_path(tmp_path, "char_001")
    state = artifacts.character_state_ref_instructions_path(tmp_path, "char_001", "silver")
    artifacts.append_instruction_log_entry(canonical, {"patch": {"status": "accepted", "addendum": "base fix"}})
    artifacts.append_instruction_log_entry(state, {"patch": {"status": "accepted", "addendum": "state fix"}})

    assert artifacts.read_active_addendum(canonical) == "base fix"
    assert artifacts.read_active_addendum(state) == "state fix"
    assert artifacts.location_state_plate_instructions_path(tmp_path, "loc_001", "night") != artifacts.location_plate_instructions_path(tmp_path, "loc_001")


def test_parent_replacement_marks_only_dependent_state_stale(tmp_path: Path):
    parent = artifacts.character_ref_sheet_path(tmp_path, "char_001")
    parent.parent.mkdir(parents=True)
    parent.write_bytes(b"old-parent")
    state_sheet = artifacts.character_state_ref_sheet_path(tmp_path, "char_001", "silver")
    state_sheet.parent.mkdir(parents=True)
    state_sheet.write_bytes(b"state")
    spec = build_character_state_spec(
        Config(), tmp_path, _character(),
        AppearanceState(id="silver", label="Silver", visual_anchor="Mara with silver hands", visually_significant=True),
    )
    artifacts.write_asset_meta(state_sheet, spec.lineage_metadata())

    parent.write_bytes(b"new-parent")
    warnings = mark_dependent_states_stale(tmp_path, "character", "char_001")
    meta = artifacts.read_asset_meta(state_sheet)

    assert len(warnings) == 1
    assert warnings[0]["code"] == "state_asset_regeneration_required"
    assert meta["lineage_status"] == LineageStatus.STALE
    assert meta["lineage_status"] != LineageStatus.CURRENT


def test_unrelated_parent_change_does_not_mark_state_stale(tmp_path: Path):
    parent = artifacts.character_ref_sheet_path(tmp_path, "char_001")
    parent.parent.mkdir(parents=True)
    parent.write_bytes(b"parent")
    state_sheet = artifacts.character_state_ref_sheet_path(tmp_path, "char_001", "silver")
    state_sheet.parent.mkdir(parents=True)
    state_sheet.write_bytes(b"state")
    spec = build_character_state_spec(
        Config(), tmp_path, _character(),
        AppearanceState(id="silver", label="Silver", visual_anchor="Mara with silver hands", visually_significant=True),
    )
    artifacts.write_asset_meta(state_sheet, spec.lineage_metadata())

    other = artifacts.character_ref_sheet_path(tmp_path, "char_002")
    other.parent.mkdir(parents=True)
    other.write_bytes(b"changed")
    assert mark_dependent_states_stale(tmp_path, "character", "char_002") == []
    assert artifacts.read_asset_meta(state_sheet)["lineage_status"] == LineageStatus.UNVERIFIED


def test_unconditioned_spec_is_never_claimed_as_current(tmp_path: Path):
    parent = artifacts.character_ref_sheet_path(tmp_path, "char_001")
    parent.parent.mkdir(parents=True)
    parent.write_bytes(b"parent")
    spec = build_character_state_spec(
        Config(), tmp_path, _character(),
        AppearanceState(id="silver", label="Silver", visual_anchor="Mara with silver hands"),
    )
    assert spec.lineage_mode == "unconditioned"
    assert spec.lineage_status == LineageStatus.UNVERIFIED


def test_restore_revalidation_marks_parent_mismatch_stale(tmp_path: Path):
    parent = artifacts.location_plate_path(tmp_path, "loc_001")
    parent.parent.mkdir(parents=True)
    parent.write_bytes(b"new")
    state = artifacts.location_state_plate_path(tmp_path, "loc_001", "loc_001_night")
    state.write_bytes(b"state")
    artifacts.write_asset_meta(state, {
        "entity_id": "loc_001", "state_id": "loc_001_night",
        "canonical_parent_sha256": "old", "lineage_mode": "unconditioned",
        "lineage_status": "current",
    })
    meta = revalidate_state_asset_lineage(state, parent)
    assert meta["lineage_status"] == LineageStatus.STALE


def test_restore_revalidation_marks_missing_parent_stale(tmp_path: Path):
    state = artifacts.location_state_plate_path(tmp_path, "loc_001", "loc_001_night")
    state.parent.mkdir(parents=True)
    state.write_bytes(b"state")
    artifacts.write_asset_meta(state, {
        "entity_id": "loc_001", "state_id": "loc_001_night",
        "canonical_parent_sha256": None,
        "lineage_mode": "conditioned", "lineage_status": "current",
    })

    meta = revalidate_state_asset_lineage(
        state, artifacts.location_plate_path(tmp_path, "loc_001"),
    )
    assert meta["lineage_status"] == LineageStatus.STALE


def test_location_spec_dimensions_match_route_strategy(tmp_path: Path):
    config = Config(image_model="gpt-image-2")
    spec = build_location_state_spec(
        config, tmp_path, _location(),
        AppearanceState(id="loc_001_night", label="Night", visual_anchor="lake house at night"),
    )
    assert (spec.effective_width, spec.effective_height) == (1536, 1024)
    assert spec.configured_route == "gpt_image_2"


def test_explicit_state_routes_are_registered():
    from novel_to_comic.server.routers.pipeline import router
    paths = {route.path for route in router.routes}
    assert "/characters/{char_id}/states/{state_id}/regenerate" in paths
    assert "/locations/{loc_id}/states/{state_id}/regenerate" in paths
    assert "/{kind}s/{entity_id}/states/{state_id}/versions" in paths
    assert "/{kind}s/{entity_id}/states/{state_id}/versions/{version}/restore" in paths
    assert "/{kind}s/{entity_id}/states/{state_id}/metadata" in paths
    assert "/location-plate-versions/restore" in paths


def test_legacy_character_state_restore_revalidates_lineage(tmp_path: Path, monkeypatch):
    from novel_to_comic.server.routers.pipeline import restore_character_ref_version

    calls = {}

    monkeypatch.setattr(
        "novel_to_comic.panel_versions.restore_asset_version",
        lambda image_path, project_dir, version: calls.setdefault("restored", image_path),
    )
    monkeypatch.setattr(
        "novel_to_comic.panel_versions.list_asset_versions",
        lambda image_path, project_dir: [],
    )
    monkeypatch.setattr(
        "novel_to_comic.stages.s3_cast._crop_sheet_to_poses",
        lambda image_path: None,
    )
    monkeypatch.setattr(
        "novel_to_comic.state_assets.revalidate_state_asset_lineage",
        lambda state_path, parent_path: calls.update(
            state_path=state_path, parent_path=parent_path,
        ) or {},
    )

    restore_character_ref_version(
        char_id="char_001", version=1, state_id="silver",
        project=(tmp_path, Config(), None),
    )

    assert calls["state_path"] == artifacts.character_state_ref_sheet_path(
        tmp_path, "char_001", "silver",
    )
    assert calls["parent_path"] == artifacts.character_ref_sheet_path(tmp_path, "char_001")


def test_state_generation_uses_compiled_wire_with_canonical_conditioning(
    tmp_path: Path, monkeypatch,
):
    """Slice 08→09: state generation now conditions on the canonical parent.

    Slice 08 built the wire with an empty ReferencePlan (unconditioned). Slice 09
    adds compatible canonical identity conditioning, so the wire carries the
    canonical parent as an identity-only subject reference.
    """
    from novel_to_comic.stages.s3_cast import _generate_state_asset_wire
    from novel_to_comic.usage import ApiResult

    # The canonical parent must exist for conditioning.
    parent = artifacts.character_ref_sheet_path(tmp_path, "char_001")
    parent.parent.mkdir(parents=True)
    parent.write_bytes(b"canonical-sheet")

    spec = build_character_state_spec(
        Config(), tmp_path, _character(),
        AppearanceState(id="silver", label="Silver", visual_anchor="SENTINEL silver hands"),
    )
    captured = {}

    async def fake_generate_wire_image(*, config, wire, output_path, feature):
        captured["wire"] = wire
        output_path.write_bytes(b"image")
        return ApiResult(value=output_path)

    monkeypatch.setattr("novel_to_comic.ai.generate_wire_image", fake_generate_wire_image)
    import asyncio
    asyncio.run(_generate_state_asset_wire(
        Config(), spec, tmp_path / "state.png", tmp_path, feature="test"
    ))

    wire = captured["wire"]
    assert "SENTINEL silver hands" in wire.prompt_parts[0]
    # Slice 09: the canonical parent is now a conditioned identity reference.
    assert len(wire.references) >= 1
    assert wire.references[0].role == "subject"
    assert wire.compiled_request_sha256
    assert wire.execution_fingerprint
