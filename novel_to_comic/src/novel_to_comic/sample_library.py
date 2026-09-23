"""Shipped, licensed story texts used by the sample picker and imports."""

from __future__ import annotations

import hashlib
import json
import re
from functools import lru_cache
from pathlib import Path


_ROOT = Path(__file__).with_name("sample_stories")
ARCHIVE_RIGHTS_NOTE = (
    "Rights for classic archive stories vary by work and jurisdiction. "
    "Check the original publication and your local rights before publishing an adaptation."
)


@lru_cache(maxsize=1)
def _entries() -> tuple[dict, ...]:
    entries = json.loads((_ROOT / "catalog.json").read_text(encoding="utf-8"))
    codes: set[str] = set()
    for entry in entries:
        code = entry["code"]
        if code in codes or entry["filename"] != f"{code}.txt":
            raise ValueError(f"Invalid sample library entry: {code}")
        codes.add(code)
        text = _verified_text(entry)
        entry["words"] = len(text.split())
    return tuple(entries)


def _verified_text(entry: dict) -> str:
    data = (_ROOT / entry["filename"]).read_bytes()
    if hashlib.sha256(data).hexdigest() != entry["sha256"]:
        raise ValueError(f"Sample text differs from catalog provenance: {entry['code']}")
    return data.decode("utf-8")


def catalog() -> list[dict]:
    """Return public metadata in editorial order, without internal file paths."""
    return [
        {**{key: value for key, value in entry.items() if key != "filename"}, "source_kind": "curated"}
        for entry in _entries()
    ]


def find(code: str) -> tuple[dict, str] | None:
    for entry in _entries():
        if entry["code"] == code:
            return entry.copy(), _verified_text(entry)
    return None


@lru_cache(maxsize=1)
def _archive_entries() -> dict[str, dict]:
    """Keep the former browse catalog available even if its site is offline."""
    snapshot = json.loads((_ROOT / "archive_catalog.json").read_text(encoding="utf-8"))
    entries: dict[str, dict] = {}
    curated_codes = {entry["code"] for entry in _entries()}
    for raw in snapshot["stories"]:
        code = raw["code"]
        if not re.fullmatch(r"[a-zA-Z0-9_-]{1,200}", code) or code in entries:
            raise ValueError(f"Invalid classic archive entry: {code}")
        if code in curated_codes:
            continue
        entries[code] = {
            "code": code,
            "title": raw["title"],
            "author": raw["author"],
            "words": raw["words"],
            "genres": raw["genres"],
            "publish_year": raw.get("publish_year"),
            "publish_source": raw.get("publish_source"),
            "source_kind": "archive",
            "source_url": f"https://www.libraryofshortstories.com/onlinereader/{code}",
            "rights_note": ARCHIVE_RIGHTS_NOTE,
        }
    return entries


def archive_catalog() -> list[dict]:
    return [entry.copy() for entry in _archive_entries().values()]


def find_archive(code: str) -> dict | None:
    entry = _archive_entries().get(code)
    return entry.copy() if entry else None
