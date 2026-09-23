"""Validate entity-scoped identifiers used as filesystem path components."""

from __future__ import annotations


def safe_asset_id(value: str) -> str:
    """Keep authored IDs intact while rejecting filesystem traversal."""
    if (
        not value
        or value in {".", ".."}
        or any(char in value for char in "/\\\x00")
        or any(ord(char) < 32 or ord(char) == 127 for char in value)
    ):
        raise ValueError("Asset ID must be one nonempty path component")
    return value
