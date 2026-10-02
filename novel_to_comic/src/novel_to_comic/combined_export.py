"""One book from several consecutive parts' finished pages.

Each part is finished and exported on its own. A combined export stitches the
verified pages of consecutive parts into one PDF or CBZ without re-rendering
anything: every page is the exact normalized image its part's Finish checked.
Each part starts on a right-hand page, so a blank page follows any part that
ends on one.
"""

from __future__ import annotations

import hashlib
import io
import os
import zipfile
from pathlib import Path
from typing import Literal

import img2pdf
from PIL import Image, ImageCms

from novel_to_comic.models.finish import FinishProductionSpec
from novel_to_comic.page_finishing import source_credit_page
from novel_to_comic.target_artifacts import ArtifactInvalid, ArtifactMissing, TargetArtifacts
from novel_to_comic.workspace import part_workspace, series_root

ExportFormat = Literal["pdf", "cbz"]


class CombinedExportRejected(ValueError):
    """The selected parts cannot be combined yet; the message says why."""


def _blank_page(width: int, height: int, production: FinishProductionSpec | None) -> bytes:
    dpi = production.dpi if production else 300
    quality = production.jpeg_quality if production else 88
    output = io.BytesIO()
    srgb = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB"))
    Image.new("RGB", (width, height), "white").save(
        output, "JPEG", icc_profile=srgb.tobytes(), dpi=(dpi, dpi), quality=quality, subsampling=0,
    )
    return output.getvalue()


def _verified_pages(workspace: Path, title: str) -> tuple[list[bytes], FinishProductionSpec | None]:
    target = TargetArtifacts(workspace)
    try:
        preflight = target.read_preflight()
    except (ArtifactMissing, ArtifactInvalid):
        raise CombinedExportRejected(f"Finish {title} before combining it.") from None
    if not preflight.ready_to_export:
        raise CombinedExportRejected(f"{title} has open Finish checks.")
    pages = []
    for page in preflight.pages:
        path = target.normalized_page_path(page.page_number)
        data = path.read_bytes() if path.is_file() else b""
        if not data or hashlib.sha256(data).hexdigest() != page.normalized_image_sha256:
            raise CombinedExportRejected(f"Refresh Finish for {title}: page {page.page_number} changed.")
        pages.append(data)
    return pages, preflight.production


def combined_export(root: Path, part_ids: list[str], export_format: ExportFormat) -> Path:
    """Build one export from consecutive parts, in reading order."""

    root = series_root(root)
    manifest = TargetArtifacts(root).read_part_manifest()
    ordinals = []
    for identifier in part_ids:
        try:
            ordinals.append(manifest.get(identifier).ordinal)
        except KeyError:
            raise CombinedExportRejected(f"Unknown part {identifier}.") from None
    if not ordinals or ordinals != list(range(ordinals[0], ordinals[0] + len(ordinals))):
        raise CombinedExportRejected("Choose consecutive parts in reading order.")

    pages: list[bytes] = []
    production = None
    for position, identifier in enumerate(part_ids):
        record = manifest.get(identifier)
        part_pages, production = _verified_pages(part_workspace(root, identifier), record.title)
        pages.extend(part_pages)
        if position < len(part_ids) - 1 and len(pages) % 2 == 1:
            with Image.open(io.BytesIO(part_pages[-1])) as last:
                pages.append(_blank_page(*last.size, production))
    if production is not None:
        credit = source_credit_page(root, production)
        if credit:
            pages.append(credit)

    digest = hashlib.sha256(
        b"".join(hashlib.sha256(page).digest() for page in pages) + export_format.encode()
    ).hexdigest()[:16]
    output = root / "exports" / "combined" / f"{part_ids[0]}-{part_ids[-1]}-{digest}.{export_format}"
    output.parent.mkdir(parents=True, exist_ok=True)
    if export_format == "pdf":
        data = img2pdf.convert(pages)
    else:
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            for number, page in enumerate(pages, start=1):
                archive.writestr(f"page_{number:03d}.jpg", page)
        data = buffer.getvalue()
    temporary = output.with_name(f".{output.name}.tmp")
    temporary.write_bytes(data)
    os.replace(temporary, output)
    return output
