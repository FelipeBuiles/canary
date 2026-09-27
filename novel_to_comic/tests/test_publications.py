import io
import json
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
from novel_to_comic.lettering import service as lettering_service
from novel_to_comic.lettering.translation import switch_stored_locale, stored_languages
from tests.test_page_finishing import _write_valid_book

from .test_hybrid_lettering import make_book, save as save_lettering, update


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


def test_scp_publication_includes_source_credit_in_reader_and_downloads(setup):
    client, target = setup
    (target.project_dir / "sample_source.json").write_text(json.dumps({
        "title": "Merrily, Merrily, Merrily",
        "author": "TL333s",
        "source_url": "https://scp-wiki.wikidot.com/merrily-merrily-merrily",
        "license": "CC BY-SA 3.0",
        "license_url": "https://creativecommons.org/licenses/by-sa/3.0/",
    }))
    book = publish(client)
    assert book["source_credit"]["author"] == "TL333s"
    assert len(book["pages"]) == 2
    assert client.get(book["pages"][-1]["url"]).status_code == 200
    pdf = client.get(f"/api/public/books/{book['id']}/download/pdf")
    assert len(PdfReader(io.BytesIO(pdf.content)).pages) == 3
    cbz = client.get(f"/api/public/books/{book['id']}/download/cbz")
    with zipfile.ZipFile(io.BytesIO(cbz.content)) as archive:
        assert archive.namelist() == ["page_0001.jpg", "page_0002.jpg", "page_0003.jpg"]
        assert archive.read("page_0002.jpg") == client.get(book["pages"][-1]["url"]).content


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


def test_scp_showcase_keeps_credit_after_portable_packaging(setup, tmp_path):
    import runpy
    from pathlib import Path
    from novel_to_comic.server import showcase, publications as store
    from novel_to_comic.state import save_state

    client, target = setup
    project, _, state = client.app.dependency_overrides[get_project]()
    save_state(state, project)
    (target.project_dir / "sample_source.json").write_text(json.dumps({
        "title": "Merrily, Merrily, Merrily",
        "author": "TL333s",
        "source_url": "https://scp-wiki.wikidot.com/merrily-merrily-merrily",
        "license": "CC BY-SA 3.0",
        "license_url": "https://creativecommons.org/licenses/by-sa/3.0/",
    }))
    prepare = runpy.run_path(str(Path(__file__).resolve().parents[2] / "scripts" / "prepare_showcase.py"))["prepare"]
    book = prepare(project, showcase.root() / "01-scp", store.PublicationInput(title="SCP book", author="Artist"))
    assert book.source_credit["author"] == "TL333s"
    assert len(book.pages) == 2
    public = client.get(f"/api/public/books/{book.id}").json()
    assert public["source_credit"]["license"] == "CC BY-SA 3.0"
    assert client.get(public["pages"][-1]["url"]).status_code == 200


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


LONG = "An extremely long caption. " * 100


@pytest.fixture
def hybrid_book(tmp_path):
    return make_book(tmp_path)


@pytest.fixture
def hybrid(hybrid_book, tmp_path, monkeypatch):
    monkeypatch.setenv("CANARY_SHOWCASE_DIR", str(tmp_path / "showcase"))
    monkeypatch.setattr(publications.limiter, "enabled", False)
    artifacts, _image = hybrid_book
    state = PipelineState(
        project_name="Hybrid", novel_path="input/private.txt",
        created_at="2026-01-01T00:00:00Z",
    )
    base = tmp_path / "public-root"
    base.mkdir()
    app = FastAPI()
    app.include_router(publications.router, prefix="/api/projects/{project_id}")
    app.include_router(publications.public_router, prefix="/api/public/books")
    app.dependency_overrides[get_current_user] = lambda: "owner"
    app.dependency_overrides[get_projects_dir] = lambda: base
    app.dependency_overrides[get_project_dir] = lambda: artifacts.project_dir
    app.dependency_overrides[get_project] = lambda: (artifacts.project_dir, Config(), state)
    return TestClient(app), artifacts


def letter(artifacts, texts):
    initial = lettering_service.ensure_lettering(artifacts, 1)
    item = initial.elements[0].model_dump()
    item["text_by_locale"] = texts
    return save_lettering(artifacts, update(initial, elements=[item]))


def test_hybrid_publishes_only_complete_fitting_languages(hybrid):
    client, artifacts = hybrid
    # en is missing, fr is stored but overflows; only es is complete and fits.
    letter(artifacts, {"source": "The door opened.", "es": "La puerta se abrió.", "fr": LONG})
    book = publish(client)
    assert book["locale"] == "source"
    assert [item["locale"] for item in book["translations"]] == ["es"]
    assert set(book["unpublished_locales"]) == {"en", "fr"}
    assert "does not fit" in book["unpublished_locales"]["fr"]
    public = client.get(f"/api/public/books/{book['id']}").json()
    assert "unpublished_locales" not in public
    assert public["translations"] == book["translations"]

    spanish = book["translations"][0]["pages"]
    assert [page["number"] for page in spanish] == [page["number"] for page in book["pages"]]
    primary = client.get(book["pages"][0]["url"])
    translated = client.get(spanish[0]["url"])
    assert translated.status_code == 200
    assert translated.headers["content-type"] == "image/jpeg"
    assert translated.content != primary.content
    root = f"/api/public/books/{book['id']}/{book['version']}/locales"
    for locale in ("en", "fr", "source", "ES", "de"):
        assert client.get(f"{root}/{locale}/pages/1").status_code == 404
    assert client.get(f"{root}/es/pages/99").status_code == 404
    download = f"/api/public/books/{book['id']}/download/cbz"
    assert client.get(download, params={"locale": "es"}).status_code == 200
    assert client.get(download, params={"locale": "fr"}).status_code == 404
    # The project itself was never switched or rewritten to publish other languages.
    assert artifacts.read_lettering_settings().locale == "source"
    assert artifacts.read_lettering(1).locale == "source"


def test_published_languages_stay_frozen_until_republished(hybrid):
    client, artifacts = hybrid
    letter(artifacts, {"source": "The door opened.", "es": "La puerta se abrió.", "fr": "La porte s'ouvrit."})
    book = publish(client)
    assert [item["locale"] for item in book["translations"]] == ["es", "fr"]
    spanish_url = book["translations"][0]["pages"][0]["url"]
    before = client.get(spanish_url).content
    letter(artifacts, {"source": "The door opened.", "es": "Otra puerta.", "fr": "La porte s'ouvrit."})
    selection = next(item for item in stored_languages(artifacts, Config())["languages"] if item["locale"] == "es")
    switch_stored_locale(artifacts, Config(), "es", selection["snapshot_sha256"])
    assert client.get(spanish_url).content == before
    assert client.get(f"/api/public/books/{book['id']}").json()["locale"] == "source"

    updated = publish(client)
    assert updated["version"] != book["version"]
    assert updated["locale"] == "es"
    assert [item["locale"] for item in updated["translations"]] == ["fr"]
    assert set(updated["unpublished_locales"]) == {"en"}
    assert client.get(spanish_url).status_code == 404
    assert client.get(updated["pages"][0]["url"]).content != before


def test_showcase_packages_hybrid_languages(hybrid):
    import runpy
    from pathlib import Path
    from novel_to_comic.server import showcase, publications as store
    from novel_to_comic.state import save_state

    client, artifacts = hybrid
    save_state(client.app.dependency_overrides[get_project]()[2], artifacts.project_dir)
    letter(artifacts, {"source": "The door opened.", "es": "La puerta se abrió.", "fr": LONG})
    prepare = runpy.run_path(str(Path(__file__).resolve().parents[2] / "scripts" / "prepare_showcase.py"))["prepare"]
    book = prepare(artifacts.project_dir, showcase.root() / "01-hybrid", store.PublicationInput(title="Hybrid", author="Author"))
    assert book.locale == "source"
    assert [item.locale for item in book.translations] == ["es"]
    manifest = (showcase.root() / "01-hybrid" / "book.json").read_text()
    assert "unpublished_locales" not in manifest and "/api/" not in manifest
    public = client.get(f"/api/public/books/{book.id}").json()
    spanish = public["translations"][0]["pages"][0]["url"]
    assert spanish == f"/api/public/books/{book.id}/{book.version}/locales/es/pages/1"
    assert client.get(spanish).status_code == 200
    assert client.get(spanish).content != client.get(public["pages"][0]["url"]).content


def test_baked_editions_publish_without_languages(setup):
    client, _target = setup
    book = publish(client)
    assert "locale" not in book and "translations" not in book
    assert "unpublished_locales" not in book
    root = f"/api/public/books/{book['id']}/{book['version']}/locales"
    assert client.get(f"{root}/es/pages/1").status_code == 404
    download = f"/api/public/books/{book['id']}/download/pdf"
    assert client.get(download, params={"locale": "es"}).status_code == 404


def test_source_edits_exclude_stale_translations_from_publication(hybrid):
    client, artifacts = hybrid
    letter(artifacts, {"source": "The door opened.", "es": "La puerta se abrió."})
    letter(artifacts, {"source": "The window opened.", "es": "La puerta se abrió."})
    result = publish(client)
    assert result["locale"] == "source"
    assert not result["translations"]
    assert "es" in result["unpublished_locales"]
    assert artifacts.read_lettering(1).elements[0].text_by_locale["es"] == "La puerta se abrió."
