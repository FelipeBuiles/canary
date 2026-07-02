"""Version history for regenerable cast reference assets."""

from pathlib import Path

from PIL import Image

from novel_to_comic.panel_versions import (
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
    # Archived files exist and the meta rode along.
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


def test_restore_brings_back_an_old_version(tmp_path):
    sheet = tmp_path / "refs" / "char_001" / "sheet.png"
    _png(sheet, (10, 10, 10))
    record_asset_version(sheet, tmp_path, reason="before_regenerate")  # v001 = dark
    _png(sheet, (200, 200, 200))  # live is now light

    restore_asset_version(sheet, tmp_path, version=1)
    with Image.open(sheet) as img:
        assert img.getpixel((0, 0)) == (10, 10, 10)  # back to the dark original
    # The light version we overwrote was itself archived (restore is reversible).
    assert any(v.get("reason") == "before_restore" for v in list_asset_versions(sheet, tmp_path))
