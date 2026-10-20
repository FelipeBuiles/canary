"""Status decisions are independent of HTTP and never require an OCR client."""
from types import SimpleNamespace

import pytest

from novel_to_comic.page_review import current_draw_validator_version
from novel_to_comic.server.render_checks import render_check_status
from novel_to_comic.target_artifacts import ArtifactMissing


@pytest.mark.parametrize("drawn,stale,checked,cached,status,paid", [
    (False, False, False, False, "undrawn", False),
    (True, True, False, False, "stale_render", False),
    (True, False, True, False, "checked", False),
    (True, False, False, True, "cached_evidence", False),
    (True, False, False, False, "requires_ocr", True),
])
def test_status_table(tmp_path, drawn, stale, checked, cached, status, paid):
    raw = tmp_path / "raw.json"
    if cached:
        raw.write_text("{}")
    def missing(*args):
        raise ArtifactMissing("analysis", tmp_path / "analysis.json")
    render = SimpleNamespace(revision=1, image_sha256="image", is_stale_for=lambda page: stale)
    target = SimpleNamespace(
        active_render_revision=lambda page: 1 if drawn else None,
        read_provenance=lambda *args: SimpleNamespace(render=render),
        read_page=lambda page: SimpleNamespace(content_sha256="page"),
        read_analysis=(lambda *args: SimpleNamespace(render_image_sha256="image",
            comic_page_sha256="page", validator_version=current_draw_validator_version())) if checked else missing,
        read_raw_ocr=(lambda *args: SimpleNamespace(schema_version=1, page_number=1,
            render_revision=1, render_image_sha256="image")) if cached else missing,
        raw_ocr_path=lambda *args: raw,
        analysis_path=lambda *args: tmp_path / "analysis.json",
        read_ocr_response=missing,
    )
    assert render_check_status(target, 1) == {"status": status, "requires_paid_call": paid}
