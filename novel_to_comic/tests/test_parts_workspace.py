"""Series roots, part workspaces, the part manifest and per-part source units."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from novel_to_comic import artifacts
from novel_to_comic.models.parts import PartManifest, PartRecord, text_sha256
from novel_to_comic.models.source import SourceDocument
from novel_to_comic.source_extraction import (
    SourceSceneAnchor,
    build_source_document,
    source_units,
)
from novel_to_comic.target_artifacts import TargetArtifacts
from novel_to_comic.workspace import (
    FIRST_PART_ID,
    create_part_workspace,
    is_part_workspace,
    part_id,
    part_ordinal,
    part_workspace,
    part_workspaces,
    series_root,
    workspace_part_id,
)


def _record(ordinal: int, text: str = "Some text.") -> PartRecord:
    return PartRecord(
        id=part_id(ordinal), ordinal=ordinal, title=f"Part {ordinal}",
        text_sha256=text_sha256(text), characters=len(text),
        created_at="2026-10-01T00:00:00+00:00",
    )


def test_part_ids_round_trip_and_reject_traversal() -> None:
    assert part_id(1) == FIRST_PART_ID == "part_0001"
    assert part_ordinal("part_0012") == 12
    for bad in ("part_0000", "part_1", "../part_0001", "part_0001/x", ""):
        with pytest.raises(ValueError):
            part_ordinal(bad)
    with pytest.raises(ValueError):
        part_id(0)


def test_a_plain_directory_is_its_own_series_root(tmp_path) -> None:
    assert series_root(tmp_path) == tmp_path
    assert workspace_part_id(tmp_path) is None
    assert not is_part_workspace(tmp_path)


def test_part_workspaces_resolve_to_their_series_root(tmp_path) -> None:
    second = create_part_workspace(tmp_path, part_id(2))
    first = create_part_workspace(tmp_path, FIRST_PART_ID)

    assert first == part_workspace(tmp_path, FIRST_PART_ID) == tmp_path / "parts" / "part_0001"
    assert series_root(first) == tmp_path
    assert series_root(second) == tmp_path
    assert workspace_part_id(second) == "part_0002"
    # Creating again is a confirmation, not an error.
    assert create_part_workspace(tmp_path, FIRST_PART_ID) == first
    assert part_workspaces(tmp_path) == [first, second]
    assert part_workspaces(first) == [first, second]


def test_look_assets_resolve_to_the_series_root_from_a_part(tmp_path) -> None:
    workspace = create_part_workspace(tmp_path, FIRST_PART_ID)

    assert artifacts.story_bible_path(workspace) == tmp_path / "story_bible.json"
    assert artifacts.character_ref_sheet_path(workspace, "char_001") == (
        tmp_path / "refs" / "char_001" / "sheet.png"
    )
    assert artifacts.location_plate_path(workspace, "loc_001") == tmp_path / "plates" / "loc_001.png"
    assert artifacts.style_sample_path(workspace, 1) == tmp_path / "samples" / "style_1.png"

    target = TargetArtifacts(workspace)
    assert target.series_dir == tmp_path
    assert target.cast_design_path == tmp_path / "refs" / "cast_design.json"
    assert target.lettering_style_path == tmp_path / "lettering" / "style.json"
    # Page artifacts stay in the part workspace.
    assert target.source_path == workspace / "source" / "source.json"
    assert target.brief_path == workspace / "brief" / "adaptation_brief.json"
    assert target.lettering_path(1) == workspace / "lettering" / "pages" / "page_001.json"


def test_manifest_requires_consecutive_parts_matching_their_ids() -> None:
    manifest = PartManifest(parts=(_record(1), _record(2)))
    assert manifest.latest.id == "part_0002"
    assert manifest.previous("part_0002").id == "part_0001"
    assert manifest.previous("part_0001") is None

    with pytest.raises(ValidationError):
        PartManifest(parts=(_record(2),))
    with pytest.raises(ValidationError):
        PartRecord(**{**_record(1).model_dump(), "id": "part_0002"})
    with pytest.raises(ValidationError):
        PartManifest(parts=())


def test_part_text_is_verified_against_its_record(tmp_path) -> None:
    workspace = create_part_workspace(tmp_path, FIRST_PART_ID)
    target = TargetArtifacts(workspace)
    text = "Chapter One. It began."
    target.write_part_manifest(PartManifest(parts=(_record(1, text),)))
    target.write_part_text(FIRST_PART_ID, text)

    assert target.part_manifest_path == tmp_path / "source" / "parts.json"
    assert TargetArtifacts(tmp_path).read_part_text(FIRST_PART_ID) == text

    target.part_text_path(FIRST_PART_ID).write_text("Edited elsewhere.")
    with pytest.raises(ValueError, match="changed outside Canary"):
        target.read_part_text(FIRST_PART_ID)


def test_a_later_part_continues_series_unit_ordinals() -> None:
    first = source_units("One. Two. ")
    second = source_units("Three. Four.", first_ordinal=first[-1].ordinal + 1)

    assert [unit.id for unit in first] == ["source_000001", "source_000002"]
    assert [unit.id for unit in second] == ["source_000003", "source_000004"]
    # Offsets are relative to the part's own text.
    assert second[0].start_offset == 0

    document = build_source_document(
        "Three. Four.",
        (SourceSceneAnchor(id="p0002s0001_scene_001", title="Later", opening_quote="Three."),),
        first_ordinal=3,
    )
    assert document.scenes[0].first_unit_id == "source_000003"
    assert document.scenes[0].last_unit_id == "source_000004"


def test_source_ordinals_must_still_be_consecutive() -> None:
    units = source_units("One. Two.", first_ordinal=5)
    with pytest.raises(ValidationError, match="consecutive"):
        SourceDocument(
            text="One. Two.",
            units=(units[0], units[1].model_copy(update={"ordinal": 7})),
            scenes=({"id": "s", "title": "S", "first_unit_id": units[0].id,
                     "last_unit_id": units[1].id},),
        )
