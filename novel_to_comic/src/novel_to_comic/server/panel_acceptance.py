"""Persistent draw-panel acceptance state."""

from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Any


ACCEPTANCE_REL_PATH = Path("draw") / "panel_acceptance.json"


def panel_key(scene_id: str, panel_number: int) -> str:
    return f"{scene_id}/panel_{panel_number:03d}"


def panel_image_path(project_dir: Path, scene_id: str, panel_number: int) -> Path:
    return project_dir / "draw" / scene_id / f"panel_{panel_number:03d}.png"


def image_fingerprint(path: Path) -> dict[str, int] | None:
    if not path.exists():
        return None
    stat = path.stat()
    return {"size": stat.st_size, "mtime_ns": stat.st_mtime_ns}


def _acceptance_path(project_dir: Path) -> Path:
    return project_dir / ACCEPTANCE_REL_PATH


def load_acceptance(project_dir: Path) -> dict[str, Any]:
    path = _acceptance_path(project_dir)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text())
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_acceptance(project_dir: Path, data: dict[str, Any]) -> None:
    path = _acceptance_path(project_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")


def is_panel_accepted(project_dir: Path, scene_id: str, panel_number: int) -> bool:
    data = load_acceptance(project_dir)
    entry = data.get(panel_key(scene_id, panel_number))
    if not isinstance(entry, dict):
        return False
    current = image_fingerprint(panel_image_path(project_dir, scene_id, panel_number))
    return bool(current and entry.get("image") == current)


def accept_panel(project_dir: Path, scene_id: str, panel_number: int) -> dict[str, Any]:
    image = image_fingerprint(panel_image_path(project_dir, scene_id, panel_number))
    if image is None:
        raise FileNotFoundError(f"Panel image not found: {scene_id}/panel_{panel_number:03d}")
    data = load_acceptance(project_dir)
    entry = {
        "scene_id": scene_id,
        "panel_number": panel_number,
        "accepted_at": datetime.now(UTC).isoformat(),
        "image": image,
    }
    data[panel_key(scene_id, panel_number)] = entry
    save_acceptance(project_dir, data)
    return entry


def clear_panel_acceptance(project_dir: Path, scene_id: str, panel_number: int) -> bool:
    data = load_acceptance(project_dir)
    key = panel_key(scene_id, panel_number)
    existed = key in data
    if existed:
        data.pop(key, None)
        save_acceptance(project_dir, data)
    return existed
