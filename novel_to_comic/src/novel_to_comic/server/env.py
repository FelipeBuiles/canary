"""Shared environment variable helpers."""

from __future__ import annotations

import os


def bool_env(name: str, default: bool = False) -> bool:
    """Read a boolean from an environment variable."""
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}
