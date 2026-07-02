"""Persistent draw-panel version history."""

from __future__ import annotations

from datetime import UTC, datetime
import json
import shutil
from pathlib import Path
from typing import Any


def panel_image_path(project_dir: Path, scene_id: str, panel_number: int) -> Path:
    return project_dir / "draw" / scene_id / f"panel_{panel_number:03d}.png"


def panel_versions_dir(project_dir: Path, scene_id: str, panel_number: int) -> Path:
    return project_dir / "draw" / scene_id / "versions" / f"panel_{panel_number:03d}"


def _meta_path(image_path: Path) -> Path:
    return image_path.with_suffix(f"{image_path.suffix}.meta.json")


def _failure_meta_path(image_path: Path) -> Path:
    return image_path.with_suffix(f"{image_path.suffix}.failure.json")


def _relative_to_project(path: Path, project_dir: Path) -> str:
    try:
        return str(path.relative_to(project_dir))
    except ValueError:
        return str(path)


def _image_fingerprint(path: Path) -> dict[str, int] | None:
    if not path.exists():
        return None
    stat = path.stat()
    return {"size": stat.st_size, "mtime_ns": stat.st_mtime_ns}


def _read_manifest(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"version": 1, "active_version": None, "entries": []}
    try:
        data = json.loads(path.read_text())
    except Exception:
        return {"version": 1, "active_version": None, "entries": []}
    if not isinstance(data, dict):
        return {"version": 1, "active_version": None, "entries": []}
    entries = data.get("entries")
    if not isinstance(entries, list):
        entries = []
    active_version = data.get("active_version")
    if not isinstance(active_version, int):
        active_version = None
    return {
        "version": 1,
        "active_version": active_version,
        "entries": [entry for entry in entries if isinstance(entry, dict)],
    }


def _write_manifest(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")


def _next_version_number(entries: list[dict[str, Any]]) -> int:
    max_version = 0
    for entry in entries:
        version = entry.get("version")
        if isinstance(version, int):
            max_version = max(max_version, version)
    return max_version + 1


def _image_dimensions(path: Path) -> dict[str, int] | None:
    try:
        from PIL import Image

        with Image.open(path) as image:
            return {"width": image.width, "height": image.height}
    except Exception:
        return None


def record_current_panel_version(
    project_dir: Path,
    scene_id: str,
    panel_number: int,
    *,
    reason: str,
) -> dict[str, Any] | None:
    """Record the current canonical panel image as the active version."""
    source = panel_image_path(project_dir, scene_id, panel_number)
    if not source.exists():
        return None

    versions_dir = panel_versions_dir(project_dir, scene_id, panel_number)
    manifest_path = versions_dir / "history.json"
    manifest = _read_manifest(manifest_path)
    entries: list[dict[str, Any]] = manifest["entries"]
    source_fingerprint = _image_fingerprint(source)
    for entry in entries:
        if entry.get("fingerprint") == source_fingerprint:
            manifest["active_version"] = entry.get("version")
            _write_manifest(manifest_path, manifest)
            return entry

    version = _next_version_number(entries)
    stem = f"v{version:03d}"
    archived_image = versions_dir / f"{stem}.png"

    versions_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, archived_image)

    source_meta = _meta_path(source)
    source_failure_meta = _failure_meta_path(source)
    archived_meta: Path | None = None
    archived_failure_meta: Path | None = None
    if source_meta.exists():
        archived_meta = versions_dir / f"{stem}.meta.json"
        shutil.copy2(source_meta, archived_meta)
    if source_failure_meta.exists():
        archived_failure_meta = versions_dir / f"{stem}.failure.json"
        shutil.copy2(source_failure_meta, archived_failure_meta)

    entry: dict[str, Any] = {
        "version": version,
        "archived_at": datetime.now(UTC).isoformat(),
        "created_at": datetime.now(UTC).isoformat(),
        "reason": reason,
        "scene_id": scene_id,
        "panel_number": panel_number,
        "image_path": _relative_to_project(archived_image, project_dir),
        "fingerprint": _image_fingerprint(archived_image),
    }
    dimensions = _image_dimensions(archived_image)
    if dimensions:
        entry.update(dimensions)
    if archived_meta:
        entry["meta_path"] = _relative_to_project(archived_meta, project_dir)
    if archived_failure_meta:
        entry["failure_meta_path"] = _relative_to_project(archived_failure_meta, project_dir)

    entries.append(entry)
    manifest["active_version"] = version
    manifest["entries"] = entries
    _write_manifest(manifest_path, manifest)
    return entry


archive_current_panel_version = record_current_panel_version


def list_panel_versions(project_dir: Path, scene_id: str, panel_number: int) -> list[dict[str, Any]]:
    versions_dir = panel_versions_dir(project_dir, scene_id, panel_number)
    manifest = _read_manifest(versions_dir / "history.json")
    active_version = manifest.get("active_version")
    entries = []
    for entry in manifest["entries"]:
        image_path = entry.get("image_path")
        if not isinstance(image_path, str) or not (project_dir / image_path).exists():
            continue
        entries.append({**entry, "current": entry.get("version") == active_version})

    current_image = panel_image_path(project_dir, scene_id, panel_number)
    if current_image.exists() and not any(entry["current"] for entry in entries):
        current_fingerprint = _image_fingerprint(current_image)
        for index, entry in enumerate(entries):
            if entry.get("fingerprint") == current_fingerprint:
                entries[index] = {**entry, "current": True}
                return entries
        current_version = (entries[-1]["version"] + 1) if entries else 1
        current: dict[str, Any] = {
            "version": current_version,
            "current": True,
            "scene_id": scene_id,
            "panel_number": panel_number,
            "image_path": _relative_to_project(current_image, project_dir),
            "fingerprint": _image_fingerprint(current_image),
        }
        dimensions = _image_dimensions(current_image)
        if dimensions:
            current.update(dimensions)
        current_meta = _meta_path(current_image)
        current_failure_meta = _failure_meta_path(current_image)
        if current_meta.exists():
            current["meta_path"] = _relative_to_project(current_meta, project_dir)
        if current_failure_meta.exists():
            current["failure_meta_path"] = _relative_to_project(current_failure_meta, project_dir)
        entries.append(current)

    return entries


def archived_panel_version_count(project_dir: Path, scene_id: str, panel_number: int) -> int:
    versions_dir = panel_versions_dir(project_dir, scene_id, panel_number)
    manifest = _read_manifest(versions_dir / "history.json")
    return len(
        [
            entry
            for entry in manifest["entries"]
            if isinstance(entry.get("image_path"), str) and (project_dir / entry["image_path"]).exists()
        ]
    )


def restore_panel_version(
    project_dir: Path,
    scene_id: str,
    panel_number: int,
    version: int,
) -> dict[str, Any]:
    versions = list_panel_versions(project_dir, scene_id, panel_number)
    entry = next(
        (candidate for candidate in versions if candidate.get("version") == version),
        None,
    )
    if not entry:
        raise FileNotFoundError(f"Panel version not found: {scene_id}/panel_{panel_number:03d}/v{version:03d}")

    source = project_dir / entry["image_path"]
    current = panel_image_path(project_dir, scene_id, panel_number)
    current.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, current)

    current_meta = _meta_path(current)
    current_failure_meta = _failure_meta_path(current)
    current_meta.unlink(missing_ok=True)
    current_failure_meta.unlink(missing_ok=True)

    meta_path = entry.get("meta_path")
    failure_meta_path = entry.get("failure_meta_path")
    if isinstance(meta_path, str) and (project_dir / meta_path).exists():
        shutil.copy2(project_dir / meta_path, current_meta)
    if isinstance(failure_meta_path, str) and (project_dir / failure_meta_path).exists():
        shutil.copy2(project_dir / failure_meta_path, current_failure_meta)

    manifest_path = panel_versions_dir(project_dir, scene_id, panel_number) / "history.json"
    manifest = _read_manifest(manifest_path)
    manifest["active_version"] = version
    _write_manifest(manifest_path, manifest)

    restored_versions = list_panel_versions(project_dir, scene_id, panel_number)
    restored = next(candidate for candidate in restored_versions if candidate.get("version") == version)
    return {**restored, "restored_from_version": version}


# ── Generic asset version history ────────────────────────────────────────────
# Cast reference sheets (refs/<char>/sheet.png, refs/<char>/states/<id>/sheet.png)
# are overwritten in place on regenerate, so prior re-rolls were lost. These
# helpers archive any image asset by its own path — same manifest shape as draw
# panels — so a regen keeps a comparable, restorable history.


def asset_versions_dir(image_path: Path) -> Path:
    return image_path.parent / "versions" / image_path.stem


def record_asset_version(
    image_path: Path,
    project_dir: Path,
    *,
    reason: str,
) -> dict[str, Any] | None:
    """Archive the current asset image (+ its .meta.json) before it is
    overwritten. No-op (returns None) when the asset does not exist yet."""
    if not image_path.exists():
        return None

    versions_dir = asset_versions_dir(image_path)
    manifest_path = versions_dir / "history.json"
    manifest = _read_manifest(manifest_path)
    entries: list[dict[str, Any]] = manifest["entries"]

    fingerprint = _image_fingerprint(image_path)
    for entry in entries:
        if entry.get("fingerprint") == fingerprint:
            return entry  # already archived (identical bytes)

    version = _next_version_number(entries)
    stem = f"v{version:03d}"
    archived = versions_dir / f"{stem}{image_path.suffix}"
    versions_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(image_path, archived)

    meta_src = _meta_path(image_path)
    archived_meta: Path | None = None
    if meta_src.exists():
        archived_meta = versions_dir / f"{stem}.meta.json"
        shutil.copy2(meta_src, archived_meta)

    entry: dict[str, Any] = {
        "version": version,
        "archived_at": datetime.now(UTC).isoformat(),
        "created_at": datetime.now(UTC).isoformat(),
        "reason": reason,
        "image_path": _relative_to_project(archived, project_dir),
        "fingerprint": _image_fingerprint(archived),
    }
    dimensions = _image_dimensions(archived)
    if dimensions:
        entry.update(dimensions)
    if archived_meta:
        entry["meta_path"] = _relative_to_project(archived_meta, project_dir)

    entries.append(entry)
    manifest["entries"] = entries
    _write_manifest(manifest_path, manifest)
    return entry


def list_asset_versions(image_path: Path, project_dir: Path) -> list[dict[str, Any]]:
    """Archived versions of one asset, newest last; the live file is appended as
    the current entry."""
    manifest = _read_manifest(asset_versions_dir(image_path) / "history.json")
    entries = [
        entry
        for entry in manifest["entries"]
        if isinstance(entry.get("image_path"), str) and (project_dir / entry["image_path"]).exists()
    ]
    if image_path.exists():
        live_fp = _image_fingerprint(image_path)
        if not any(entry.get("fingerprint") == live_fp for entry in entries):
            current: dict[str, Any] = {
                "version": (entries[-1]["version"] + 1) if entries else 1,
                "current": True,
                "image_path": _relative_to_project(image_path, project_dir),
                "fingerprint": live_fp,
            }
            dims = _image_dimensions(image_path)
            if dims:
                current.update(dims)
            entries.append(current)
    return entries


def restore_asset_version(image_path: Path, project_dir: Path, version: int) -> Path:
    """Copy an archived version back to the live asset path. The caller is
    responsible for any derived artifacts (e.g. re-cropping a character sheet)."""
    manifest = _read_manifest(asset_versions_dir(image_path) / "history.json")
    entry = next(
        (e for e in manifest["entries"] if e.get("version") == version),
        None,
    )
    if not entry or not isinstance(entry.get("image_path"), str):
        raise FileNotFoundError(f"Asset version not found: {image_path.name}/v{version:03d}")
    # Archive the current bytes first so a restore is itself reversible.
    record_asset_version(image_path, project_dir, reason="before_restore")
    shutil.copy2(project_dir / entry["image_path"], image_path)
    archived_meta = entry.get("meta_path")
    live_meta = _meta_path(image_path)
    live_meta.unlink(missing_ok=True)
    if isinstance(archived_meta, str) and (project_dir / archived_meta).exists():
        shutil.copy2(project_dir / archived_meta, live_meta)
    return image_path
