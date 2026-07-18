from pathlib import Path

from novel_to_comic.artifacts import read_primary_refs, write_primary_refs
from novel_to_comic.ai.providers.base import RefImage
from novel_to_comic.image_ref_strategy import _select_subject_crops
from novel_to_comic.server.panel_flags import (
    clear_panel_flag,
    flag_panel,
    is_panel_flagged,
)


def test_flag_toggle_persists(tmp_path: Path) -> None:
    assert not is_panel_flagged(tmp_path, "scene_001", 3)

    entry = flag_panel(tmp_path, "scene_001", 3)
    assert entry["scene_id"] == "scene_001"
    assert is_panel_flagged(tmp_path, "scene_001", 3)
    assert not is_panel_flagged(tmp_path, "scene_001", 4)

    assert clear_panel_flag(tmp_path, "scene_001", 3)
    assert not clear_panel_flag(tmp_path, "scene_001", 3)
    assert not is_panel_flagged(tmp_path, "scene_001", 3)


def test_flags_survive_reload_from_disk(tmp_path: Path) -> None:
    flag_panel(tmp_path, "scene_002", 1)
    flags_file = tmp_path / "draw" / "panel_flags.json"
    assert flags_file.exists()
    assert is_panel_flagged(tmp_path, "scene_002", 1)


def test_primary_refs_round_trip(tmp_path: Path) -> None:
    assert read_primary_refs(tmp_path) == {}
    write_primary_refs(tmp_path, {"char_001": "portrait"})
    assert read_primary_refs(tmp_path) == {"char_001": "portrait"}


def _ref(tmp_path: Path, char_dir: str, stem: str) -> RefImage:
    path = tmp_path / "refs" / char_dir / f"{stem}.png"
    return RefImage(path=path, role="subject")


def test_primary_pose_overrides_framing_preference(tmp_path: Path) -> None:
    subjects = [
        _ref(tmp_path, "char_001", "portrait"),
        _ref(tmp_path, "char_001", "full_body"),
    ]
    # Default framing preference picks the body/proportion view.
    chosen = _select_subject_crops(subjects, None)
    assert chosen[0].path.stem == "full_body"

    # The legacy/internal override still wins.
    chosen = _select_subject_crops(subjects, None, {"char_001": "portrait"})
    assert chosen[0].path.stem == "portrait"

    # Primary for a different character does not affect this one.
    chosen = _select_subject_crops(subjects, None, {"char_999": "portrait"})
    assert chosen[0].path.stem == "full_body"
