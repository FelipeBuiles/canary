"""Filesystem authority must not come from a mutable database path string."""

from __future__ import annotations

import re
from pathlib import Path

_COMPONENT = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]*\Z")


def project_directory(root: Path, user_id: str, slug: str) -> Path:
    """Return a direct, non-aliased child of this account's directory.

    Accept not-yet-created paths for uploads, but reject traversal, absolute
    names, hidden directories, and symlink aliases (including other projects
    in the same account). The configured volume root itself may be a symlink.
    Database ownership is checked separately; it does not validate a path.
    """
    if any(not isinstance(value, str) or not _COMPONENT.fullmatch(value)
           for value in (user_id, slug)):
        raise ValueError("Invalid project directory")
    try:
        account = root.resolve() / user_id
        directory = account / slug
        if account.resolve() != account or directory.resolve() != directory:
            raise ValueError("Invalid project directory")
    except (OSError, RuntimeError) as exc:
        raise ValueError("Invalid project directory") from exc
    return directory
