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
    from .test_page_finishing import _write_valid_book
    from novel_to_comic.models.page import BookPlan, PlannedPageRevision, ComicPage
    from novel_to_comic.models.draw import PageGenerationProvenance, PageRenderRevision
    from novel_to_comic.models.finish import FINISH_PREFLIGHT_VALIDATOR_VERSION
    target, _ = _write_valid_book(workspace, size=(60,90))
    original = target.read_page(1)
    pages, checked, images = [], [], []
    base = target.read_provenance(1,1)
    for number, color in enumerate(colors, start=1):
        page = ComicPage.model_validate(original.model_dump() | {"page_number": number, "content_sha256": ""})
        target.write_page(page)
        data = _page_image(color)
        # Deliberately author the provider-free fixture before freezing Finish.
        render = PageRenderRevision.model_validate(base.render.model_dump() | {
            "page_number": number, "comic_page_sha256": page.content_sha256,
            "image_sha256": hashlib.sha256(data).hexdigest()})
        target.render_path(number,1).parent.mkdir(parents=True, exist_ok=True)
        target.render_path(number,1).write_bytes(data)
        target.provenance_path(number,1).write_text(PageGenerationProvenance(render=render,usage=base.usage).model_dump_json())
        normalized = target.normalized_page_path(number)
        normalized.parent.mkdir(parents=True, exist_ok=True)
        images.append((normalized, data))
        pages.append(PlannedPageRevision(page_number=number, revision=page.revision, content_sha256=page.content_sha256))
        checked.append(PreflightPage(page_number=number, comic_page_revision=page.revision,
            comic_page_sha256=page.content_sha256, render_revision=1, render_image_sha256=render.image_sha256,
            normalized_image_sha256=hashlib.sha256(data).hexdigest()))
    old = target.read_plan()
    target.write_plan(BookPlan.model_validate(old.model_dump() | {"content_sha256":"", "pages": [p.model_dump() for p in pages], "target_page_max":len(pages)}))
    for normalized, data in images:
        normalized.parent.mkdir(parents=True,exist_ok=True)
        normalized.write_bytes(data)
    edition = target.read_book_edition()
    target.write_preflight(FinishPreflight(edition_revision=edition.revision,
        edition_sha256=edition.content_sha256, validator_version=FINISH_PREFLIGHT_VALIDATOR_VERSION,
        production=FinishProductionSpec(canvas_width=60,canvas_height=90),pages=tuple(checked)))


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


def test_combined_download_rejects_corruption_and_stale_sources(series):
    from novel_to_comic.combined_export import open_combined_export
    output = combined_export(series, ["part_0001", "part_0002"], "cbz")
    stream, size = open_combined_export(series, output.name)
    with stream:
        assert len(stream.read()) == size
    original = output.read_bytes()
    output.write_bytes(b"x" * len(original))
    with pytest.raises(CombinedExportRejected):
        open_combined_export(series, output.name)
    output.write_bytes(original)
    TargetArtifacts(part_workspace(series, "part_0001")).invalidate_finish()
    with pytest.raises(CombinedExportRejected):
        open_combined_export(series, output.name)


def test_combined_export_rejects_old_validator(series):
    target = TargetArtifacts(part_workspace(series, "part_0001"))
    target.write_preflight(target.read_preflight().model_copy(update={"validator_version":1}))
    with pytest.raises(CombinedExportRejected):
        combined_export(series, ["part_0001", "part_0002"], "pdf")
