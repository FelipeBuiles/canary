import io
import zipfile
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pypdf import PdfReader

from novel_to_comic.config import Config
from novel_to_comic.server.auth import get_current_user
from novel_to_comic.server.deps import get_project, get_project_dir, get_projects_dir
from novel_to_comic.server.deployment_status import require_ops_token
from novel_to_comic.server.routers import publications
from novel_to_comic.state import PipelineState
from tests.test_page_finishing import _write_valid_book


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setenv("CANARY_SHOWCASE_DIR", str(tmp_path / "showcase"))
    monkeypatch.setattr(publications.limiter, "enabled", False)
    project = tmp_path / "private-project"
    target, _ = _write_valid_book(project)
    state = PipelineState(
        project_name="Private title",
        novel_path="input/private.txt",
        created_at="2026-01-01T00:00:00Z",
    )
    app = FastAPI()
    app.include_router(publications.router, prefix="/api/projects/{project_id}")
    app.include_router(publications.public_router, prefix="/api/public/books")
    app.include_router(publications.ops_router, prefix="/api/ops/publications")
    app.dependency_overrides[get_current_user] = lambda: "owner"
    app.dependency_overrides[get_projects_dir] = lambda: tmp_path
    app.dependency_overrides[get_project_dir] = lambda: project
    app.dependency_overrides[get_project] = lambda: (project, Config(), state)
    app.dependency_overrides[require_ops_token] = lambda: None
    return TestClient(app), target


def publish(client, **kwargs):
    response = client.post(
        "/api/projects/project/publication",
        json={"title": "A public book", "author": "An Author", **kwargs},
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_snapshot_update_and_unpublish(setup):
    client, target = setup
    book = publish(client)
    page_url = book["pages"][0]["url"]
    original = client.get(page_url)
    assert original.status_code == 200
    assert original.headers["cache-control"] == "no-store"
    target.normalized_page_path(1).write_bytes(b"changed private output")
    assert client.get(page_url).content == original.content
    assert "private-project" not in str(book)
    updated = publish(client, title="Updated title")
    assert updated["id"] == book["id"]
    assert updated["version"] != book["version"]
    assert client.get(page_url).status_code == 404
    assert client.delete("/api/projects/project/publication").status_code == 200
    assert client.get(f"/api/public/books/{book['id']}").status_code == 404
    assert client.get(updated["pages"][0]["url"]).status_code == 404
    assert client.get(f"/api/public/books/{book['id']}/download/pdf").status_code == 404
    assert publish(client)["id"] == book["id"]


def test_failed_update_preserves_previous_publication(setup):
    client, _ = setup
    book = publish(client)
    with patch(
        "novel_to_comic.server.publications.finish_book",
        side_effect=ValueError("Not ready"),
    ):
        response = client.post(
            "/api/projects/project/publication",
            json={"title": "Broken", "author": "Author"},
        )
    assert response.status_code == 422
    assert client.get(f"/api/public/books/{book['id']}").json() == book
    assert client.get(book["pages"][0]["url"]).status_code == 200


def test_public_download_bookend_is_always_last(setup):
    client, _ = setup
    book = publish(client)
    prefix = f"/api/public/books/{book['id']}/download"
    for query in ["", "?bookend=false"]:
        count = 2
        response = client.get(prefix + "/pdf" + query)
        assert response.status_code == 200, response.text
        pdf = PdfReader(io.BytesIO(response.content))
        assert len(pdf.pages) == count
        assert tuple(pdf.pages[-1].mediabox) == tuple(pdf.pages[0].mediabox)
        assert "scenewright" in str(pdf.pages[-1]["/Annots"][0].get_object())
        response = client.get(prefix + "/cbz" + query)
        assert response.status_code == 200
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            assert archive.namelist() == [
                f"page_{i:04d}.jpg" for i in range(1, count + 1)
            ]
            assert (
                archive.read("page_0001.jpg")
                == client.get(book["pages"][0]["url"]).content
            )


def test_author_consent_does_not_add_books_to_manual_showcase(setup):
    client, _ = setup
    book = publish(client, allow_feature=True)
    assert client.get("/api/public/books").json() == []
    assert client.put(
        f"/api/ops/publications/{book['id']}/feature", json={"featured": True}
    ).status_code in (404, 405)


def test_owner_metadata_is_account_scoped(setup):
    client, _ = setup
    publish(client)
    client.app.dependency_overrides[get_current_user] = lambda: "other-owner"
    assert client.get("/api/projects/project/publication").json() is None
    client.delete("/api/projects/project/publication")
    client.app.dependency_overrides[get_current_user] = lambda: "owner"
    assert (
        client.get("/api/projects/project/publication").json()["title"]
        == "A public book"
    )


def test_rejects_unfinished_book(setup):
    client, target = setup
    target.normalized_page_path(1).unlink(missing_ok=True)
    target.render_path(1, 1).unlink()
    response = client.post(
        "/api/projects/project/publication",
        json={"title": "Incomplete", "author": "Author"},
    )
    assert response.status_code == 422
    assert client.get("/api/projects/project/publication").json() is None


def test_reader_metadata_escapes_author_content(setup, tmp_path):
    client, _ = setup
    book = publish(client, title='<script>alert("x")</script>')
    index = tmp_path / "index.html"
    index.write_text(
        '<html><head><title>Old</title><meta property="og:title" content="Old"></head><body><div id="root"></div></body></html>'
    )
    response = publications.reader_html(book["id"], tmp_path, index)
    body = response.body.decode()
    assert "<script>alert" not in body
    assert "&lt;script&gt;" in body
    assert body.count('property="og:title"') == 1
    assert book["pages"][0]["url"] in body


def test_private_management_requires_authentication(setup):
    client, _ = setup
    book = publish(client)
    del client.app.dependency_overrides[get_current_user]
    assert client.get("/api/projects/project/publication").status_code == 401
    assert client.delete("/api/projects/project/publication").status_code == 401
    assert client.get(f"/api/public/books/{book['id']}").status_code == 200


def test_curation_requires_operator_token(setup, monkeypatch):
    client, _ = setup
    publish(client, allow_feature=True)
    del client.app.dependency_overrides[require_ops_token]
    monkeypatch.setenv("CANARY_OPS_TOKEN", "test-operator-token")
    assert client.get("/api/ops/publications").status_code in (401, 403)


def test_project_deletion_removes_public_access(setup, tmp_path):
    from unittest.mock import MagicMock
    from novel_to_comic.server.routers.projects import delete_project
    from tests.test_project_library_recovery import _request

    client, target = setup
    book = publish(client)
    request = _request()
    request.app.state.projects_dir = tmp_path
    with patch(
        "novel_to_comic.server.routers.projects.get_db", return_value=MagicMock()
    ):
        delete_project(
            request=request,
            project_id="project",
            project_dir=target.project_dir,
            user_id="owner",
        )
    assert client.get(f"/api/public/books/{book['id']}").status_code == 404


def test_unpublished_direct_link_renders_unavailable_reader_shell(tmp_path):
    index = tmp_path / "index.html"
    index.write_text('<html><head></head><body><div id="root"></div></body></html>')
    response = publications.reader_html("a" * 32, tmp_path, index)
    assert response.status_code == 404
    assert '<div id="root">' in response.body.decode()
    assert response.headers["cache-control"] == "no-store"


def test_folder_showcase_supports_reader_downloads_updates_and_removal(setup, tmp_path):
    import runpy
    from pathlib import Path
    import shutil

    from novel_to_comic.server import showcase, publications as store
    from novel_to_comic.state import save_state

    client, _ = setup
    project, _, state = client.app.dependency_overrides[get_project]()
    save_state(state, project)
    script = Path(__file__).resolve().parents[2] / "scripts" / "prepare_showcase.py"
    prepare = runpy.run_path(str(script))["prepare"]
    destination = showcase.root() / "01-first-book"
    book = prepare(project, destination, store.PublicationInput(title="Folder book", author="Author"))
    record = client.get("/api/public/books").json()[0]
    assert record["id"] == book.id
    assert record["title"] == "Folder book"
    assert record["featured"] is True
    assert "private" not in str(record)
    assert client.get(f"/api/public/books/{book.id}").json() == record
    assert client.get(record["pages"][0]["url"]).status_code == 200
    assert client.get(f"/api/public/books/{book.id}/bookend").status_code == 200
    for format in ("pdf", "cbz"):
        assert client.get(f"/api/public/books/{book.id}/download/{format}").status_code == 200
    # Complete prepared folders can be copied to another machine unchanged.
    moved_root = tmp_path / "deployment"
    shutil.copytree(showcase.root(), moved_root)
    assert (moved_root / destination.name / "book.json").is_file()
    assert sorted(p.name for p in destination.iterdir()) == sorted([book.version, "book.json"])
    with patch("novel_to_comic.server.publications.finish_book", side_effect=ValueError("Not ready")):
        with pytest.raises(ValueError, match="Not ready"):
            prepare(project, destination, store.PublicationInput(title="Broken", author="Author"))
    assert client.get(f"/api/public/books/{book.id}").json() == record
    updated = prepare(project, destination, store.PublicationInput(title="Updated", author="Author"))
    assert updated.id == book.id
    assert updated.version != book.version
    assert client.get(record["pages"][0]["url"]).status_code == 404
    shutil.rmtree(destination)
    assert client.get("/api/public/books").json() == []
    assert client.get(f"/api/public/books/{book.id}").status_code == 404


def test_showcase_rejects_unsafe_manifest_and_missing_pages(tmp_path, monkeypatch):
    import json
    from novel_to_comic.server import showcase

    monkeypatch.setenv("CANARY_SHOWCASE_DIR", str(tmp_path))
    destination = tmp_path / "01-book"
    destination.mkdir()
    record = {
        "id": "a" * 32, "version": "../private",
        "title": "Book", "author": "Author", "published_at": "2026-01-01",
        "pages": [{"number": 1, "width": 10, "height": 20}],
    }
    manifest = destination / "book.json"
    manifest.write_text(json.dumps(record))
    with pytest.raises(ValueError):
        showcase.books()
    record["version"] = "b" * 32
    manifest.write_text(json.dumps(record))
    with pytest.raises(ValueError, match="Missing"):
        showcase.books()
