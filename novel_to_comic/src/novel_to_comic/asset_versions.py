"""Version snapshots for approved Cast assets."""

from __future__ import annotations

import hashlib
import json
import shutil
from datetime import UTC, datetime
from pathlib import Path

from novel_to_comic.asset_scope import require_project_asset_path


def asset_versions_dir(image_path: Path) -> Path:
    return image_path.parent / "versions" / image_path.stem


def record_asset_version(
    image_path: Path,
    project_dir: Path,
    *,
    reason: str,
) -> dict | None:
    require_project_asset_path(project_dir, image_path)
    if not image_path.exists():
        return None
    versions = asset_versions_dir(image_path)
    manifest_path = versions / "history.json"
    entries = []
    if manifest_path.exists():
        try:
            entries = json.loads(manifest_path.read_text()).get("entries", [])
        except (OSError, ValueError):
            entries = []
    digest = hashlib.sha256(image_path.read_bytes()).hexdigest()
    existing = next(
        (entry for entry in entries if entry.get("sha256") == digest),
        None,
    )
    if existing is not None:
        return existing
    version = max(
        (entry.get("version", 0) for entry in entries),
        default=0,
    ) + 1
    archived = versions / f"v{version:03d}{image_path.suffix}"
    archived.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(image_path, archived)
    metadata = image_path.with_suffix(f"{image_path.suffix}.meta.json")
    if metadata.exists():
        shutil.copy2(metadata, versions / f"v{version:03d}.meta.json")
    entry = {
        "version": version,
        "created_at": datetime.now(UTC).isoformat(),
        "reason": reason,
        "sha256": digest,
        "image_path": str(archived.relative_to(project_dir)),
    }
    entries.append(entry)
    manifest_path.write_text(
        json.dumps({"version": 1, "entries": entries}, indent=2) + "\n"
    )
    return entry


def list_asset_versions(image_path: Path, project_dir: Path) -> list[dict]:
    require_project_asset_path(project_dir, image_path)
    versions = asset_versions_dir(image_path)
    manifest = versions / "history.json"
    entries = json.loads(manifest.read_text()).get("entries", []) if manifest.exists() else []
    result = list(entries)
    if image_path.exists():
        result.append({
            "version": max((entry["version"] for entry in result), default=0) + 1,
            "current": True,
            "sha256": hashlib.sha256(image_path.read_bytes()).hexdigest(),
            "image_path": str(image_path.relative_to(project_dir)),
        })
    return result


def restore_asset_version(
    image_path: Path,
    project_dir: Path,
    version: int,
) -> None:
    require_project_asset_path(project_dir, image_path)
    archived = asset_versions_dir(image_path) / f"v{version:03d}{image_path.suffix}"
    if not archived.exists():
        raise FileNotFoundError(f"asset version {version} does not exist")
    record_asset_version(image_path, project_dir, reason="before_restore")
    shutil.copy2(archived, image_path)
    archived_metadata = archived.with_suffix(".meta.json")
    live_metadata = image_path.with_suffix(f"{image_path.suffix}.meta.json")
    if archived_metadata.exists():
        shutil.copy2(archived_metadata, live_metadata)
    elif live_metadata.exists():
        live_metadata.unlink()
