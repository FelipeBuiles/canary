"""Screen-sized WebP renditions of reference images for small UI tiles.

Cast references, plates and Style proofs are full-resolution PNG masters that
redraws replace at the same path. The roster, look strip and version history
show them at a few dozen pixels, so they read a derived WebP instead. A
rendition is keyed by its source's path and validator, which makes a redraw
miss the old rendition by construction; the superseded one is removed when its
replacement is written. Masters stay the only source of truth.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from uuid import uuid4

from PIL import Image

# Delivery sizes only. 256px covers an 80px tile at 3x density; 768px covers
# a sheet-grid card at 2x without decoding the master for every mounted card.
THUMBNAIL_WIDTHS = {
    "thumbnail": 256,
    "card": 768,
}
THUMBNAIL_SOURCE_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".webp"})
THUMBNAIL_DIR = ".thumbnails"


def ensure_asset_thumbnail(root: Path, source: Path, rendition: str) -> Path:
    """Return the cached rendition of ``source``, creating it atomically when absent."""
    try:
        maximum_width = THUMBNAIL_WIDTHS[rendition]
    except KeyError as exc:
        raise ValueError(f"unknown thumbnail rendition: {rendition}") from exc
    if source.suffix.lower() not in THUMBNAIL_SOURCE_SUFFIXES:
        raise ValueError(f"not a thumbnail source: {source.name}")
    stat = source.stat()
    key = hashlib.sha256(source.relative_to(root).as_posix().encode()).hexdigest()[:24]
    directory = root / THUMBNAIL_DIR / rendition
    output = directory / f"{key}.{stat.st_mtime_ns:x}-{stat.st_size:x}.webp"
    if output.is_file():
        return output

    with Image.open(source) as original:
        original.load()
        preview = original.convert("RGBA" if original.mode in {"RGBA", "LA", "P"} else "RGB")
    if preview.width > maximum_width:
        height = max(1, round(preview.height * maximum_width / preview.width))
        preview = preview.resize((maximum_width, height), Image.Resampling.LANCZOS)

    directory.mkdir(parents=True, exist_ok=True)
    temporary = directory / f".{output.name}.{uuid4().hex}.tmp"
    try:
        preview.save(temporary, format="WEBP", quality=82, method=4)
        os.replace(temporary, output)
    finally:
        temporary.unlink(missing_ok=True)
    for stale in directory.glob(f"{key}.*.webp"):
        if stale != output:
            stale.unlink(missing_ok=True)
    return output
