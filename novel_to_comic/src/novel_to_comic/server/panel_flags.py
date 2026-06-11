"""Persistent draw-panel re-work flags (review-by-exception).

Generated panels are accepted by default; users flag the ones that need
re-work. Flags never block the pipeline — they drive the "Review N flagged"
secondary action and the flagged filter in the UI.
"""

from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Any

from .panel_acceptance import panel_key

FLAGS_REL_PATH = Path("draw") / "panel_flags.json"


def _flags_path(project_dir: Path) -> Path:
    return project_dir / FLAGS_REL_PATH


def load_flags(project_dir: Path) -> dict[str, Any]:
    path = _flags_path(project_dir)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text())
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_flags(project_dir: Path, data: dict[str, Any]) -> None:
    path = _flags_path(project_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")


def is_panel_flagged(project_dir: Path, scene_id: str, panel_number: int) -> bool:
    return panel_key(scene_id, panel_number) in load_flags(project_dir)


def flag_panel(project_dir: Path, scene_id: str, panel_number: int) -> dict[str, Any]:
    data = load_flags(project_dir)
    entry = {
        "scene_id": scene_id,
        "panel_number": panel_number,
        "flagged_at": datetime.now(UTC).isoformat(),
    }
    data[panel_key(scene_id, panel_number)] = entry
    save_flags(project_dir, data)
    return entry


def clear_panel_flag(project_dir: Path, scene_id: str, panel_number: int) -> bool:
    data = load_flags(project_dir)
    key = panel_key(scene_id, panel_number)
    existed = key in data
    if existed:
        data.pop(key, None)
        save_flags(project_dir, data)
    return existed
