"""Preview requests must not monopolize the editor's artifact lock."""

from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest
from fastapi import HTTPException

from novel_to_comic.artifact_lock import production_lock
from novel_to_comic.server.routers import lettering


def test_editor_can_open_while_preview_is_rendering(tmp_path, monkeypatch):
    rendering, release = Event(), Event()
    preview = tmp_path / "preview.webp"
    preview.write_bytes(b"preview")

    def composite(target, *args, **kwargs):
        # Match the service boundary: snapshot under lock, render outside it.
        with production_lock(target.project_dir):
            pass
        rendering.set()
        assert release.wait(5)
        return preview, "identity"

    def editor(target, page_number):
        with production_lock(target.project_dir):
            return {"page_number": page_number}

    monkeypatch.setattr(lettering, "composite_page", composite)
    monkeypatch.setattr(lettering, "editor_state", editor)
    with ThreadPoolExecutor(max_workers=2) as pool:
        request = pool.submit(lettering.get_page_composite, 1, "reader", 1, (tmp_path,))
        try:
            assert rendering.wait(5)
            opened = pool.submit(lettering.get_lettering, 1, (tmp_path,))
            assert opened.result(timeout=2) == {"page_number": 1}
        finally:
            release.set()
        response = request.result(timeout=5)
    assert response.body == b"preview"
    assert response.headers["etag"] == '"identity-reader"'


@pytest.mark.parametrize("during_composition", [False, True])
def test_preview_rebuilds_after_concurrent_invalidation(tmp_path, monkeypatch, during_composition):
    path = tmp_path / "preview.webp"
    calls = []

    def composite(*args, **kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            if during_composition:
                raise FileNotFoundError(path)
            return path, "old"
        path.write_bytes(b"current")
        return path, "new"

    monkeypatch.setattr(lettering, "composite_page", composite)
    response = lettering.get_page_composite(1, "reader", 7, (tmp_path,))
    path.unlink()  # The response has already captured its bytes.
    assert response.body == b"current"
    assert response.headers["etag"] == '"new-reader"'
    assert response.headers["cache-control"] == "private, no-cache"
    assert len(calls) == 2
    assert all(call["expected_render_revision"] == 7 for call in calls)


def test_repeated_invalidation_returns_conflict_without_looping(tmp_path, monkeypatch):
    calls = []

    def composite(*args, **kwargs):
        calls.append(1)
        return tmp_path / "missing.webp", "identity"

    monkeypatch.setattr(lettering, "composite_page", composite)
    with pytest.raises(HTTPException) as error:
        lettering.get_page_composite(1, "reader", 1, (tmp_path,))
    assert error.value.status_code == 409
    assert len(calls) == 2
