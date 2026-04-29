import json

from novel_to_comic.panel_versions import (
    archive_current_panel_version,
    list_panel_versions,
    panel_image_path,
    record_current_panel_version,
    restore_panel_version,
)


def test_archive_current_panel_version_preserves_image_and_meta(tmp_path):
    project_dir = tmp_path
    image_path = panel_image_path(project_dir, "scene_001", 1)
    image_path.parent.mkdir(parents=True)
    image_path.write_bytes(b"first")
    image_path.with_suffix(".png.meta.json").write_text(json.dumps({"prompt": "first"}))

    entry = archive_current_panel_version(project_dir, "scene_001", 1, reason="regenerate")

    assert entry is not None
    assert entry["version"] == 1
    assert entry["reason"] == "regenerate"
    archived_image = project_dir / entry["image_path"]
    archived_meta = project_dir / entry["meta_path"]
    assert archived_image.read_bytes() == b"first"
    assert json.loads(archived_meta.read_text()) == {"prompt": "first"}


def test_restore_panel_version_switches_active_without_creating_new_version(tmp_path):
    project_dir = tmp_path
    image_path = panel_image_path(project_dir, "scene_001", 1)
    image_path.parent.mkdir(parents=True)
    image_path.write_bytes(b"first")
    image_path.with_suffix(".png.meta.json").write_text(json.dumps({"prompt": "first"}))
    record_current_panel_version(project_dir, "scene_001", 1, reason="initial")

    image_path.write_bytes(b"second")
    image_path.with_suffix(".png.meta.json").write_text(json.dumps({"prompt": "second"}))
    record_current_panel_version(project_dir, "scene_001", 1, reason="regenerate")

    restored = restore_panel_version(project_dir, "scene_001", 1, 1)

    assert restored["current"] is True
    assert restored["restored_from_version"] == 1
    assert image_path.read_bytes() == b"first"
    assert json.loads(image_path.with_suffix(".png.meta.json").read_text()) == {"prompt": "first"}

    versions = list_panel_versions(project_dir, "scene_001", 1)
    assert [version["version"] for version in versions] == [1, 2]
    assert [version["version"] for version in versions if version["current"]] == [1]
    assert (project_dir / versions[1]["image_path"]).read_bytes() == b"second"
