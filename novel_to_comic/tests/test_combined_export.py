"""Consecutive finished parts combine into one book without re-rendering."""

from __future__ import annotations

import hashlib
import io
import zipfile
from pathlib import Path

import pytest
from PIL import Image
from pypdf import PdfReader

from novel_to_comic.combined_export import CombinedExportRejected, combined_export
from novel_to_comic.models.finish import FinishPreflight, FinishProductionSpec, PreflightPage
from novel_to_comic.series import append_parts, initialize_series
from novel_to_comic.target_artifacts import TargetArtifacts
from novel_to_comic.workspace import part_workspace


def _page_image(color: str) -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (60, 90), color).save(output, "JPEG", dpi=(300, 300))
    return output.getvalue()


def _finish(workspace: Path, colors: list[str]) -> None:
    target = TargetArtifacts(workspace)
    pages = []
    for number, color in enumerate(colors, start=1):
        data = _page_image(color)
        path = target.normalized_page_path(number)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        pages.append(PreflightPage(
            page_number=number, comic_page_revision=1, comic_page_sha256="a" * 64,
            render_revision=1, render_image_sha256="b" * 64,
            normalized_image_sha256=hashlib.sha256(data).hexdigest(),
        ))
    target.write_preflight(FinishPreflight(
        edition_revision=1, edition_sha256="c" * 64, validator_version=3,
        production=FinishProductionSpec(canvas_width=60, canvas_height=90), pages=tuple(pages),
    ))


@pytest.fixture
def series(tmp_path) -> Path:
    root = tmp_path / "book"
    root.mkdir()
    (root / "input").mkdir()
    initialize_series(root, project_name="Book", novel_path=root / "input" / "a.txt", text="One. " * 5)
    append_parts(root, [(None, "Two. " * 5), (None, "Three. " * 5)])
    _finish(part_workspace(root, "part_0001"), ["red"])
    _finish(part_workspace(root, "part_0002"), ["green", "blue"])
    return root


def test_parts_combine_with_each_part_starting_on_a_right_hand_page(series) -> None:
    pdf = combined_export(series, ["part_0001", "part_0002"], "pdf")
    assert len(PdfReader(pdf).pages) == 4  # red, blank, green, blue

    cbz = combined_export(series, ["part_0001", "part_0002"], "cbz")
    with zipfile.ZipFile(cbz) as archive:
        names = archive.namelist()
        assert names == ["page_001.jpg", "page_002.jpg", "page_003.jpg", "page_004.jpg"]
        with Image.open(io.BytesIO(archive.read("page_002.jpg"))) as blank:
            assert blank.getpixel((5, 5)) == (255, 255, 255)
    assert cbz.parent == series / "exports" / "combined"


def test_only_consecutive_finished_unchanged_parts_combine(series) -> None:
    with pytest.raises(CombinedExportRejected, match="consecutive"):
        combined_export(series, ["part_0001", "part_0003"], "pdf")
    with pytest.raises(CombinedExportRejected, match="Finish Part 3"):
        combined_export(series, ["part_0002", "part_0003"], "pdf")
    TargetArtifacts(part_workspace(series, "part_0002")).normalized_page_path(1).write_bytes(_page_image("black"))
    with pytest.raises(CombinedExportRejected, match="page 1 changed"):
        combined_export(series, ["part_0001", "part_0002"], "pdf")
