"""Tests for the Short Story Library import integration."""

import gzip
import json
import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from novel_to_comic.config import load_config
from novel_to_comic.server.routers.projects import (
    ImportStoryRequest,
    import_short_story,
    list_short_stories,
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


@pytest.fixture(autouse=True)
def reset_globals():
    """Reset the short story catalog cache before each test."""
    import novel_to_comic.server.routers.projects as projects_router
    projects_router._story_catalog_cache = None
    projects_router._story_catalog_last_fetch = 0.0


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


def test_list_short_stories_fetches_and_caches():
    mock_catalog = [{"title": "2BR02B", "code": "2br02b", "words": 2519, "author": "Kurt Vonnegut"}]

    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = mock_catalog

    async_client_cls = _make_http_client_mock(mock_resp)

    with patch("novel_to_comic.server.routers.projects.httpx.AsyncClient", async_client_cls):
        # First call: should fetch from remote
        res1 = asyncio.run(list_short_stories())
        assert res1 == mock_catalog
        assert async_client_cls.return_value.__aenter__.call_count == 1

        # Second call: should read from in-memory cache, no new HTTP call
        res2 = asyncio.run(list_short_stories())
        assert res2 == mock_catalog
        assert async_client_cls.return_value.__aenter__.call_count == 1  # still just 1


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
