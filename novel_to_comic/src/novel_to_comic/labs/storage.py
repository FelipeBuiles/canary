"""On-disk layout for labs experiment runs.

Layout (relative to projects_dir):

    _labs/
      runs/
        {run_id}/
          manifest.json
          refs/
            {n}.png            # copies of reference images used by this run
          panels/
            {panel_idx}/
              {model_id}.png   # generated image
              {model_id}.json  # per-cell metadata (latency, cost, errors)

The manifest is the source of truth for what was attempted; per-cell JSON files
record the outcome and surface in the UI.
"""

from __future__ import annotations

import json
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def labs_root(projects_dir: Path) -> Path:
    return projects_dir / "_labs" / "runs"


def run_dir(projects_dir: Path, run_id: str) -> Path:
    return labs_root(projects_dir) / run_id


def manifest_path(projects_dir: Path, run_id: str) -> Path:
    return run_dir(projects_dir, run_id) / "manifest.json"


def panel_dir(projects_dir: Path, run_id: str, panel_idx: int) -> Path:
    return run_dir(projects_dir, run_id) / "panels" / str(panel_idx)


def cell_image_path(projects_dir: Path, run_id: str, panel_idx: int, model_id: str) -> Path:
    return panel_dir(projects_dir, run_id, panel_idx) / f"{model_id}.png"


def cell_meta_path(projects_dir: Path, run_id: str, panel_idx: int, model_id: str) -> Path:
    return panel_dir(projects_dir, run_id, panel_idx) / f"{model_id}.json"


def ref_dir(projects_dir: Path, run_id: str) -> Path:
    return run_dir(projects_dir, run_id) / "refs"


def write_manifest(projects_dir: Path, run_id: str, manifest: dict[str, Any]) -> None:
    path = manifest_path(projects_dir, run_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True))


def read_manifest(projects_dir: Path, run_id: str) -> dict[str, Any] | None:
    path = manifest_path(projects_dir, run_id)
    if not path.exists():
        return None
    return json.loads(path.read_text())


def write_cell(
    projects_dir: Path,
    run_id: str,
    panel_idx: int,
    model_id: str,
    *,
    image_bytes: bytes | None,
    meta: dict[str, Any],
) -> None:
    pdir = panel_dir(projects_dir, run_id, panel_idx)
    pdir.mkdir(parents=True, exist_ok=True)
    if image_bytes is not None:
        cell_image_path(projects_dir, run_id, panel_idx, model_id).write_bytes(image_bytes)
    meta = {**meta, "updated_at": datetime.now(UTC).isoformat()}
    cell_meta_path(projects_dir, run_id, panel_idx, model_id).write_text(
        json.dumps(meta, indent=2, sort_keys=True)
    )


def read_cell_meta(projects_dir: Path, run_id: str, panel_idx: int, model_id: str) -> dict[str, Any] | None:
    path = cell_meta_path(projects_dir, run_id, panel_idx, model_id)
    if not path.exists():
        return None
    return json.loads(path.read_text())


def sum_run_cost(projects_dir: Path, run_id: str) -> float:
    manifest = read_manifest(projects_dir, run_id)
    if not manifest:
        return 0.0
    total = 0.0
    for panel in manifest.get("panels") or []:
        try:
            panel_idx = int(panel.get("idx") or 0)
        except (TypeError, ValueError):
            continue
        for model_id in manifest.get("model_ids") or []:
            meta = read_cell_meta(projects_dir, run_id, panel_idx, str(model_id))
            if not meta:
                continue
            value = meta.get("cost_usd")
            if value is None:
                continue
            try:
                total += float(value)
            except (TypeError, ValueError):
                continue
    return total


def stage_reference_images(projects_dir: Path, run_id: str, sources: list[Path]) -> list[Path]:
    """Copy refs into the run directory so the manifest stays self-contained."""
    if not sources:
        return []
    target = ref_dir(projects_dir, run_id)
    target.mkdir(parents=True, exist_ok=True)
    staged: list[Path] = []
    for i, src in enumerate(sources):
        if not src.exists():
            continue
        dest = target / f"{i:02d}{src.suffix or '.png'}"
        shutil.copyfile(src, dest)
        staged.append(dest)
    return staged


def list_runs(projects_dir: Path) -> list[dict[str, Any]]:
    root = labs_root(projects_dir)
    if not root.exists():
        return []
    out: list[dict[str, Any]] = []
    for child in sorted(root.iterdir(), reverse=True):
        if not child.is_dir():
            continue
        manifest = read_manifest(projects_dir, child.name)
        if not manifest:
            continue
        total_cost = manifest.get("total_cost_usd")
        if total_cost is None:
            total_cost = sum_run_cost(projects_dir, child.name)
        out.append({
            "run_id": child.name,
            "created_at": manifest.get("created_at"),
            "label": manifest.get("label"),
            "model_ids": manifest.get("model_ids", []),
            "panel_count": len(manifest.get("panels", [])),
            "status": manifest.get("status", "unknown"),
            "total_cost_usd": total_cost,
        })
    return out
