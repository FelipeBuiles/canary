"""Immutable, screen-sized renditions derived from complete-page renders."""

from __future__ import annotations

import os
from pathlib import Path
from uuid import uuid4

from PIL import Image

from novel_to_comic.target_artifacts import TargetArtifacts


# These are delivery sizes, never creative or print-production dimensions.
# A 424px image keeps a four-column gallery crisp at 2x density, while 1024px
# comfortably covers the reader's normal viewport without decoding a full
# 1696×2528 master for every mounted page.
PREVIEW_WIDTHS = {
    "thumbnail": 424,
    "reader": 1024,
}


def ensure_page_render_preview(
    artifacts: TargetArtifacts,
    *,
    page_number: int,
    render_revision: int,
    rendition: str,
) -> Path:
    """Return a cached WebP rendition, creating it atomically when absent.

    Draw masters are immutable PNGs and remain the source of truth. A new
    render revision owns a distinct preview filename within an edition. A stage
    restart removes those previews and may reuse the filenames, so HTTP delivery
    must revalidate even though files are immutable within an edition.
    """

    try:
        maximum_width = PREVIEW_WIDTHS[rendition]
    except KeyError as exc:
        raise ValueError(f"unknown page render rendition: {rendition}") from exc

    output = artifacts.render_preview_path(
        page_number,
        render_revision,
        rendition,
    )
    if output.is_file():
        return output

    source = artifacts.render_path(page_number, render_revision)
    if not source.is_file():
        raise FileNotFoundError(source)

    with Image.open(source) as original:
        original.load()
        preview = original.convert("RGB")
        if preview.width > maximum_width:
            height = round(preview.height * maximum_width / preview.width)
            preview = preview.resize(
                (maximum_width, height),
                Image.Resampling.LANCZOS,
            )

    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f".{output.name}.{uuid4().hex}.tmp")
    try:
        preview.save(
            temporary,
            format="WEBP",
            quality=82,
            method=6,
        )
        os.replace(temporary, output)
    finally:
        temporary.unlink(missing_ok=True)
    return output
