"""Shared text helpers for prompt composition and indexing."""

from __future__ import annotations


def clean(value: str | None) -> str:
    """Collapse whitespace and strip a string."""
    return " ".join((value or "").replace("\n", " ").split())


def shorten(value: str, limit: int) -> str:
    """Truncate to *limit* characters on a word boundary."""
    value = clean(value)
    if len(value) <= limit:
        return value
    shortened = value[:limit].rsplit(" ", 1)[0].rstrip(" ,.;:")
    return f"{shortened}."
