"""Version history for regenerable cast reference assets."""

from pathlib import Path

from PIL import Image
import pytest
from pydantic import ValidationError

from novel_to_comic.models.appearance import AppearanceState

from novel_to_comic.asset_versions import (
    asset_versions_dir,
    list_asset_versions,
    record_asset_version,
    restore_asset_version,
)


def _png(path: Path, color: tuple[int, int, int]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (8, 8), color).save(path)


def test_regenerate_archives_prior_versions(tmp_path):
    sheet = tmp_path / "refs" / "char_001" / "states" / "stumps" / "sheet.png"
    _png(sheet, (10, 10, 10))
    sheet.with_suffix(".png.meta.json").write_text('{"appearance_state_id": "stumps"}')

    # First regen: archive the original, then overwrite (simulated).
    e1 = record_asset_version(sheet, tmp_path, reason="before_regenerate")
    _png(sheet, (20, 20, 20))
    # Second regen: archive the second, overwrite again.
    e2 = record_asset_version(sheet, tmp_path, reason="before_regenerate")
    _png(sheet, (30, 30, 30))

    assert e1 and e1["version"] == 1
    assert e2 and e2["version"] == 2
    # Archived image and its metadata exist.
    assert (asset_versions_dir(sheet) / "v001.png").exists()
    assert (asset_versions_dir(sheet) / "v001.meta.json").exists()

    versions = list_asset_versions(sheet, tmp_path)
    # Two archived + the live current.
    assert [v["version"] for v in versions] == [1, 2, 3]
    assert versions[-1].get("current") is True


def test_record_is_idempotent_for_identical_bytes(tmp_path):
    sheet = tmp_path / "refs" / "char_001" / "sheet.png"
    _png(sheet, (5, 5, 5))
    first = record_asset_version(sheet, tmp_path, reason="before_regenerate")
    again = record_asset_version(sheet, tmp_path, reason="before_regenerate")
    assert first["version"] == 1
    assert again["version"] == 1  # same bytes → no new version
    versions = list_asset_versions(sheet, tmp_path)
    assert [v["version"] for v in versions] == [1]
    assert versions[0].get("current") is True


def test_restore_brings_back_an_old_version(tmp_path):
    sheet = tmp_path / "refs" / "char_001" / "sheet.png"
    _png(sheet, (10, 10, 10))
    record_asset_version(sheet, tmp_path, reason="before_regenerate")  # v001 = dark
    _png(sheet, (200, 200, 200))  # live is now light

    for version, color in [(1, 10), (2, 200), (1, 10), (2, 200)]:
        restore_asset_version(sheet, tmp_path, version=version)
        with Image.open(sheet) as img:
            assert img.getpixel((0, 0)) == (color, color, color)
        versions = list_asset_versions(sheet, tmp_path)
        assert [v["version"] for v in versions] == [1, 2]
        assert [v["version"] for v in versions if v.get("current")] == [version]
    # The light version we overwrote was itself archived (restore is reversible).
    assert any(v.get("reason") == "before_restore" for v in versions)


def test_list_existing_history_identifies_current_without_rewriting_it(tmp_path):
    plate = tmp_path / "plates" / "hall.png"
    _png(plate, (10, 10, 10))
    record_asset_version(plate, tmp_path, reason="before_regenerate")
    _png(plate, (200, 200, 200))
    restore_asset_version(plate, tmp_path, version=1)
    manifest = asset_versions_dir(plate) / "history.json"
    before = manifest.read_bytes()

    versions = list_asset_versions(plate, tmp_path)

    assert [v["version"] for v in versions] == [1, 2]
    assert [v["version"] for v in versions if v.get("current")] == [1]
    assert manifest.read_bytes() == before


def test_new_art_after_restoring_an_old_version_keeps_chronological_ids(tmp_path):
    sheet = tmp_path / "refs" / "char_001" / "sheet.png"
    _png(sheet, (10, 10, 10))
    record_asset_version(sheet, tmp_path, reason="before_regenerate")
    _png(sheet, (20, 20, 20))
    restore_asset_version(sheet, tmp_path, version=1)

    record_asset_version(sheet, tmp_path, reason="before_regenerate")
    _png(sheet, (30, 30, 30))
    versions = list_asset_versions(sheet, tmp_path)
    assert [v["version"] for v in versions] == [1, 2, 3]
    assert [v["version"] for v in versions if v.get("current")] == [3]

    restore_asset_version(sheet, tmp_path, version=2)
    with Image.open(sheet) as img:
        assert img.getpixel((0, 0)) == (20, 20, 20)
    versions = list_asset_versions(sheet, tmp_path)
    assert [v["version"] for v in versions] == [1, 2, 3]
    assert [v["version"] for v in versions if v.get("current")] == [2]


def test_asset_versioning_rejects_another_projects_path(tmp_path):
    owner = tmp_path / "owner" / "book"
    (owner / "refs").mkdir(parents=True)
    foreign = tmp_path / "other" / "book" / "refs" / "hero" / "sheet.png"
    _png(foreign, (5, 5, 5))
    escaped = owner / "refs" / ".." / ".." / ".." / "other" / "book" / "refs" / "hero" / "sheet.png"

    with pytest.raises(ValueError, match="escapes its project"):
        record_asset_version(escaped, owner, reason="before_regenerate")
    assert not (foreign.parent / "versions").exists()


def test_appearance_state_id_cannot_escape_reference_directory():
    with pytest.raises(ValidationError, match="one nonempty path component"):
        AppearanceState(id="../../other-project", label="Other", visual_anchor="Other")


def test_failure_sidecar_rejects_foreign_project_path_before_writing(tmp_path):
    from novel_to_comic.asset_generation import persist_non_panel_provenance
    from novel_to_comic.artifacts import asset_failure_path

    owner = tmp_path / "owner" / "book"
    owner.mkdir(parents=True)
    foreign = tmp_path / "other" / "book" / "refs" / "hero" / "sheet.png"
    _png(foreign, (7, 7, 7))
    escaped = owner / "refs" / ".." / ".." / ".." / "other" / "book" / "refs" / "hero" / "sheet.png"

    with pytest.raises(ValueError, match="escapes its project"):
        persist_non_panel_provenance(
            request=None, output_path=escaped, project_dir=owner,
            request_id=None, error=RuntimeError("request rejected"),
        )
    assert not asset_failure_path(foreign).exists()
