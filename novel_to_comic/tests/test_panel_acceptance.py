from pathlib import Path

from novel_to_comic.server.panel_acceptance import (
    accept_panel,
    clear_panel_acceptance,
    is_panel_accepted,
)


def test_acceptance_tracks_current_panel_file(tmp_path: Path) -> None:
    panel_path = tmp_path / "draw" / "scene_001" / "panel_001.png"
    panel_path.parent.mkdir(parents=True)
    panel_path.write_bytes(b"first")

    assert not is_panel_accepted(tmp_path, "scene_001", 1)

    accept_panel(tmp_path, "scene_001", 1)
    assert is_panel_accepted(tmp_path, "scene_001", 1)

    panel_path.write_bytes(b"second")
    assert not is_panel_accepted(tmp_path, "scene_001", 1)


def test_clear_acceptance_is_idempotent(tmp_path: Path) -> None:
    panel_path = tmp_path / "draw" / "scene_001" / "panel_001.png"
    panel_path.parent.mkdir(parents=True)
    panel_path.write_bytes(b"first")
    accept_panel(tmp_path, "scene_001", 1)

    assert clear_panel_acceptance(tmp_path, "scene_001", 1)
    assert not clear_panel_acceptance(tmp_path, "scene_001", 1)
    assert not is_panel_accepted(tmp_path, "scene_001", 1)
