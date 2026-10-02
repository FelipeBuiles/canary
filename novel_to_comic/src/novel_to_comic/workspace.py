"""Series roots and part workspaces.

A project is a series of parts. Look assets (Story Bible, style samples, Cast
references, the book lettering style) belong to the series root; page work
(source units, Brief, Adapt, Plan, lettering pages, Draw, Finish) belongs to a
part workspace at ``<root>/parts/<part_id>``. A part workspace is marked by a
``part.json`` file. A directory without that marker is its own series root,
which keeps single-directory callers (stage runs, tooling) working unchanged.

Relative paths stored in artifacts stay valid because each kind of path is
always resolved against the same root: Look paths against the series root,
page paths against the part workspace.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

PARTS_DIRNAME = "parts"
PART_MARKER = "part.json"
FIRST_PART_ID = "part_0001"
_PART_ID = re.compile(r"part_(\d{4})")


def part_id(ordinal: int) -> str:
    """The canonical identifier of the ``ordinal``-th part (1-based)."""

    if not 1 <= ordinal <= 9999:
        raise ValueError("part ordinal must be between 1 and 9999")
    return f"part_{ordinal:04d}"


def part_ordinal(identifier: str) -> int:
    """Return the 1-based ordinal encoded in a canonical part identifier."""

    match = _PART_ID.fullmatch(identifier or "")
    if match is None or int(match.group(1)) < 1:
        raise ValueError(f"invalid part id: {identifier!r}")
    return int(match.group(1))


def is_part_workspace(path: Path) -> bool:
    return (Path(path) / PART_MARKER).is_file()


def series_root(path: Path) -> Path:
    """The series root that owns ``path`` (a root or a part workspace)."""

    path = Path(path)
    if is_part_workspace(path):
        return path.parent.parent
    return path


def workspace_part_id(path: Path) -> str | None:
    """The part identifier of a part workspace, or ``None`` for a root."""

    marker = Path(path) / PART_MARKER
    if not marker.is_file():
        return None
    data = json.loads(marker.read_text())
    identifier = data.get("id") if isinstance(data, dict) else None
    part_ordinal(identifier)
    return identifier


def part_id_for_path(path: Path | str) -> str | None:
    """The part a workspace path belongs to, from its location alone (no IO)."""

    path = Path(path)
    if path.parent.name == PARTS_DIRNAME and _PART_ID.fullmatch(path.name):
        return path.name
    return None


def part_workspace(root: Path, identifier: str) -> Path:
    """Path of a part workspace under ``root``; validates the identifier."""

    part_ordinal(identifier)
    return series_root(root) / PARTS_DIRNAME / identifier


def create_part_workspace(root: Path, identifier: str) -> Path:
    """Create (or confirm) the workspace directory and its marker."""

    workspace = part_workspace(root, identifier)
    workspace.mkdir(parents=True, exist_ok=True)
    marker = workspace / PART_MARKER
    if marker.exists():
        if workspace_part_id(workspace) != identifier:
            raise ValueError(f"part workspace marker does not match {identifier}")
        return workspace
    temporary = workspace / f".{PART_MARKER}.tmp"
    temporary.write_text(json.dumps({"id": identifier}) + "\n")
    temporary.replace(marker)
    return workspace


def part_workspaces(root: Path) -> list[Path]:
    """Existing part workspaces in part order."""

    base = series_root(root) / PARTS_DIRNAME
    if not base.is_dir():
        return []
    found = [
        child for child in base.iterdir()
        if child.is_dir() and not child.is_symlink() and _PART_ID.fullmatch(child.name)
        and is_part_workspace(child)
    ]
    return sorted(found, key=lambda child: part_ordinal(child.name))
