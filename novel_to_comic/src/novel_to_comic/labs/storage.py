"""On-disk Labs runs, one directory per run under the user's projects root.

    _labs/runs/{run_id}/
        run.json              kind, label, spec, status, timestamps, error
        cells/{cell_id}.json  one result per independently executed cell
        ...                   files owned by the experiment (images, workspaces)

Cells are written independently so concurrent cells never share a file.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_RUN_ID = re.compile(r"^\d{8}-\d{6}-[0-9a-f]{6}$")
_CELL_ID = re.compile(r"^[A-Za-z0-9._-]{1,120}$")


def now() -> str:
    return datetime.now(UTC).isoformat()


def runs_root(user_root: Path) -> Path:
    return user_root / "_labs" / "runs"


def run_dir(user_root: Path, run_id: str) -> Path:
    if not _RUN_ID.match(run_id):
        raise ValueError("Invalid Labs run id")
    return runs_root(user_root) / run_id


def run_file(user_root: Path, run_id: str, relative: str) -> Path:
    """A file inside one run; never a path outside it."""
    base = run_dir(user_root, run_id).resolve()
    target = (base / relative).resolve()
    if base not in target.parents:
        raise ValueError("Invalid Labs run file")
    return target


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as output:
            json.dump(value, output, indent=2, sort_keys=True)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text()) if path.exists() else None


def create_run(user_root: Path, *, kind: str, label: str, spec: dict[str, Any]) -> dict[str, Any]:
    run_id = f"{datetime.now(UTC):%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:6]}"
    run = {
        "run_id": run_id, "kind": kind, "label": label, "spec": spec,
        "status": "running", "created_at": now(), "finished_at": None, "error": None,
    }
    write_json(run_dir(user_root, run_id) / "run.json", run)
    return run


def update_run(user_root: Path, run_id: str, **fields: Any) -> dict[str, Any]:
    path = run_dir(user_root, run_id) / "run.json"
    run = {**_read_json(path), **fields}
    write_json(path, run)
    return run


def write_cell(user_root: Path, run_id: str, cell_id: str, value: dict[str, Any]) -> None:
    if not _CELL_ID.match(cell_id):
        raise ValueError("Invalid Labs cell id")
    write_json(run_dir(user_root, run_id) / "cells" / f"{cell_id}.json", {**value, "cell_id": cell_id})


def read_run(user_root: Path, run_id: str) -> dict[str, Any] | None:
    directory = run_dir(user_root, run_id)
    run = _read_json(directory / "run.json")
    if run is None:
        return None
    cells = [_read_json(path) for path in sorted((directory / "cells").glob("*.json"))]
    return {**run, "cells": cells, "total_cost_usd": _total_cost(cells)}


def _total_cost(cells: list[dict[str, Any]]) -> float | None:
    costs = [cell.get("cost_usd") for cell in cells]
    known = [cost for cost in costs if isinstance(cost, (int, float))]
    return round(sum(known), 6) if known else None


def list_runs(user_root: Path) -> list[dict[str, Any]]:
    root = runs_root(user_root)
    if not root.exists():
        return []
    runs = []
    for child in sorted(root.iterdir(), reverse=True):
        if child.is_dir() and _RUN_ID.match(child.name):
            run = read_run(user_root, child.name)
            if run is not None:
                runs.append({key: run[key] for key in (
                    "run_id", "kind", "label", "status", "created_at", "finished_at", "total_cost_usd",
                )} | {"cell_count": len(run["cells"])})
    return runs


def delete_run(user_root: Path, run_id: str) -> bool:
    directory = run_dir(user_root, run_id)
    if not directory.exists():
        return False
    shutil.rmtree(directory)
    return True


def fixture_id(source: str) -> str:
    """Opaque, stable telemetry ID for a Labs source project; never its path."""
    return "fx_" + hashlib.sha256(source.encode()).hexdigest()[:12]
