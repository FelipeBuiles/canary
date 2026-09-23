"""Tests for the Short Story Library import integration."""

import gzip
import json
import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from starlette.requests import Request

from novel_to_comic.config import load_config
from novel_to_comic.server.routers.projects import (
    ImportStoryRequest,
    import_short_story,
    list_short_stories,
    read_short_story,
)
from novel_to_comic.state import load_state


def _request() -> Request:
    """A minimal real Starlette request.

    ``import_short_story`` is unit-tested by calling it directly, but the
    ``@limiter.limit`` decorator validates that ``request`` is a genuine
    ``starlette.requests.Request`` (it reads the client address for the
    rate-limit key) and that ``request.app.state.limiter`` is set. A bare
    MagicMock is rejected, so build a real one wired to the shared limiter.
    """
    from starlette.applications import Starlette

    from novel_to_comic.server.ratelimit import limiter

    app = Starlette()
    app.state.limiter = limiter
    return Request(
        scope={
            "type": "http",
            "method": "POST",
            "path": "/",
            "headers": [],
            "query_string": b"",
            "client": ("127.0.0.1", 0),
            "app": app,
        }
    )


def _make_http_client_mock(response_mock: MagicMock) -> MagicMock:
    """Build a MagicMock that works as `async with httpx.AsyncClient() as client`."""
    client = MagicMock()
    client.get = AsyncMock(return_value=response_mock)
    async def _bytes():
        yield response_mock.content

    response_mock.aiter_bytes = _bytes
    stream_context = MagicMock()
    stream_context.__aenter__ = AsyncMock(return_value=response_mock)
    stream_context.__aexit__ = AsyncMock(return_value=False)
    client.stream.return_value = stream_context

    # Make the class itself work as an async context manager
    cls_mock = MagicMock()
    cls_mock.return_value.__aenter__ = AsyncMock(return_value=client)
    cls_mock.return_value.__aexit__ = AsyncMock(return_value=False)
    return cls_mock


def test_curated_catalog_has_verified_text_and_license_provenance():
    catalog = list_short_stories()
    curated = [story for story in catalog if story["source_kind"] == "curated"]
    archive = [story for story in catalog if story["source_kind"] == "archive"]
    assert len(curated) >= 20
    assert len(archive) == 1082
    assert sum(story["license"] == "CC BY-SA 3.0" for story in curated) >= 10
    assert len({story["code"] for story in catalog}) == len(catalog)
    assert catalog[0]["code"] == "kaitlin-out-of-space"
    assert len({story["author"] for story in curated}) >= 2
    assert {genre for story in curated for genre in story["genres"]} >= {
        "sci-fi", "drama", "horror", "fantasy"
    }
    for story in curated:
        assert story["license"] in {"CC0 1.0", "CC BY-SA 3.0"}
        assert story["source_url"].startswith("https://")
        assert story["words"] > 100
        assert "filename" not in story
        preview = asyncio.run(read_short_story(story["code"]))
        assert preview["text"].splitlines()[1] == f"By {story['author']}"

    lovecraft = [story for story in archive if story["author"] == "H. P. Lovecraft"]
    assert len(lovecraft) == 56
    assert all(story["rights_note"] and "license" not in story for story in lovecraft)
    assert any(story["code"] == "the-cats-of-ulthar" for story in lovecraft)
    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(read_short_story("missing"))
    assert exc_info.value.status_code == 404


def test_classic_archive_reader_fetches_full_text_with_limits():
    text = "It is said that in Ulthar, no man may kill a cat."
    with patch("novel_to_comic.server.routers.projects._download_remote_story", new_callable=AsyncMock) as fetch:
        fetch.return_value = gzip.compress(text.encode("utf-8"))
        result = asyncio.run(read_short_story("the-cats-of-ulthar"))
    assert result == {"code": "the-cats-of-ulthar", "text": text}
    fetch.assert_awaited_once_with("https://www.libraryofshortstories.com/storiesgzip/the-cats-of-ulthar.txt")


def test_public_sample_reader_route_precedes_project_routes():
    from novel_to_comic.server.routers import projects

    app = FastAPI()
    app.include_router(projects.router, prefix="/api/projects")
    response = TestClient(app).get("/api/projects/short-stories/an-education")
    assert response.status_code == 200
    assert response.json()["text"].startswith("AN EDUCATION\nBy Angie")


def test_import_curated_sample_uses_shipped_text_and_saves_provenance(tmp_path: Path):
    catalog = list_short_stories()
    sample = catalog[0]
    mock_db = MagicMock()
    mock_db.table.return_value.insert.return_value.execute.return_value.data = [{"id": "db-local"}]

    with (
        patch("novel_to_comic.server.routers.projects.httpx.AsyncClient") as remote,
        patch("novel_to_comic.server.routers.projects.get_db", return_value=mock_db),
    ):
        result = asyncio.run(import_short_story(
            request=_request(),
            payload=ImportStoryRequest(name=sample["title"], url_or_code=sample["code"]),
            projects_dir=tmp_path,
            user_id="reader",
        ))

    assert result["id"] == "db-local"
    remote.assert_not_called()
    project_dir = tmp_path / "reader" / "kaitlin-out-of-space"
    assert (project_dir / "input" / "kaitlin-out-of-space.txt").read_text() == asyncio.run(read_short_story(sample["code"]))["text"]
    provenance = json.loads((project_dir / "sample_source.json").read_text())
    assert provenance["license"] == "CC0 1.0"
    assert provenance["source_url"] == sample["source_url"]
    assert provenance["sha256"] == sample["sha256"]


def test_import_scp_story_preserves_author_and_share_alike_license(tmp_path: Path):
    sample = next(story for story in list_short_stories() if story["code"] == "merrily-merrily-merrily")
    mock_db = MagicMock()
    mock_db.table.return_value.insert.return_value.execute.return_value.data = [{"id": "db-scp"}]
    with (
        patch("novel_to_comic.server.routers.projects.httpx.AsyncClient") as remote,
        patch("novel_to_comic.server.routers.projects.get_db", return_value=mock_db),
    ):
        asyncio.run(import_short_story(
            request=_request(),
            payload=ImportStoryRequest(name="Cosmic river", url_or_code=sample["code"]),
            projects_dir=tmp_path,
            user_id="reader",
        ))
    remote.assert_not_called()
    provenance = json.loads((tmp_path / "reader" / "cosmic-river" / "sample_source.json").read_text())
    assert provenance["author"] == "TL333s"
    assert provenance["license"] == "CC BY-SA 3.0"
    assert provenance["license_url"] == "https://creativecommons.org/licenses/by-sa/3.0/"


def test_import_rejects_unrelated_urls_before_fetch(tmp_path: Path):
    mock_db = MagicMock()
    mock_db.table.return_value.select.return_value.eq.return_value.execute.return_value.data = []
    with patch("novel_to_comic.server.routers.projects.httpx.AsyncClient") as remote, \
         patch("novel_to_comic.server.routers.projects.get_db", return_value=mock_db):
        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(import_short_story(
                request=_request(),
                payload=ImportStoryRequest(name="Unrelated", url_or_code="https://example.com/story"),
                projects_dir=tmp_path,
                user_id="reader",
            ))
    assert exc_info.value.status_code == 400
    remote.assert_not_called()


def test_import_short_story_handles_onlinereader_url(tmp_path: Path):
    story_text = "Everything was perfectly swell."
    gzipped_content = gzip.compress(story_text.encode("utf-8"))

    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.content = gzipped_content

    async_client_cls = _make_http_client_mock(mock_resp)

    mock_db = MagicMock()
    mock_db.table.return_value.insert.return_value.execute.return_value.data = [{"id": "db-proj-1"}]

    payload = ImportStoryRequest(
        name="Test Dystopia",
        url_or_code="https://www.libraryofshortstories.com/onlinereader/2br02b",
        config_overrides=json.dumps({"dev_mode": True}),
    )

    with patch("novel_to_comic.server.routers.projects.httpx.AsyncClient", async_client_cls), \
         patch("novel_to_comic.server.routers.projects.get_db", return_value=mock_db):
        res = asyncio.run(import_short_story(
            request=_request(),
            payload=payload,
            projects_dir=tmp_path,
            user_id="user123",
        ))

    assert res["id"] == "db-proj-1"
    assert res["project_name"] == "Test Dystopia"
    assert res["name"] == "test-dystopia"

    project_dir = tmp_path / "user123" / "test-dystopia"
    assert project_dir.exists()
    txt_file = project_dir / "input" / "2br02b.txt"
    assert txt_file.exists()
    assert txt_file.read_text() == story_text
    provenance = json.loads((project_dir / "sample_source.json").read_text())
    assert provenance["source_kind"] == "archive"
    assert provenance["author"] == "Kurt Vonnegut"
    assert provenance["license"] is None
    assert provenance["rights_note"]

    config, _ = load_config(project_dir)
    assert config.dev_mode is True

    state = load_state(project_dir)
    assert state.project_name == "Test Dystopia"
    assert state.novel_path == str(project_dir / "input" / "2br02b.txt")


def test_import_short_story_rejects_decompression_bomb_without_project(
    tmp_path: Path, monkeypatch
):
    monkeypatch.setenv("CANARY_MAX_REMOTE_DECOMPRESSED_CHARACTERS", "10")
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.content = gzip.compress(b"x" * 100)
    async_client_cls = _make_http_client_mock(mock_resp)
    mock_db = MagicMock()
    mock_db.table.return_value.select.return_value.eq.return_value.execute.return_value.data = []

    with (
        patch(
            "novel_to_comic.server.routers.projects.httpx.AsyncClient",
            async_client_cls,
        ),
        patch(
            "novel_to_comic.server.routers.projects.get_db",
            return_value=mock_db,
        ),
        pytest.raises(HTTPException) as exc_info,
    ):
        asyncio.run(
            import_short_story(
                request=_request(),
                payload=ImportStoryRequest(name="Too Large", url_or_code="large"),
                projects_dir=tmp_path,
                user_id="user789",
            )
        )

    assert exc_info.value.status_code == 413
    assert not (tmp_path / "user789" / "too-large").exists()


def test_import_short_story_handles_raw_code(tmp_path: Path):
    story_text = "Once upon a time..."

    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    # Plain text — does NOT start with gzip magic bytes, so router uses r.text
    mock_resp.content = story_text.encode("utf-8")
    mock_resp.text = story_text

    async_client_cls = _make_http_client_mock(mock_resp)

    mock_db = MagicMock()
    mock_db.table.return_value.insert.return_value.execute.return_value.data = [{"id": "db-proj-2"}]

    payload = ImportStoryRequest(
        name="Sample Story",
        url_or_code="the-cask-of-amontillado",
    )

    with patch("novel_to_comic.server.routers.projects.httpx.AsyncClient", async_client_cls), \
         patch("novel_to_comic.server.routers.projects.get_db", return_value=mock_db):
        res = asyncio.run(import_short_story(
            request=_request(),
            payload=payload,
            projects_dir=tmp_path,
            user_id="user456",
        ))

    assert res["name"] == "sample-story"
    txt_file = tmp_path / "user456" / "sample-story" / "input" / "the-cask-of-amontillado.txt"
    assert txt_file.exists()
    assert txt_file.read_text() == story_text
