"""The fixture-replay server must speak the same wire shape the client reads.

Text completions stream, so a replay server that only answers buffered JSON
breaks the whole `--mock` stack silently.
"""

import asyncio
import json
from pathlib import Path

import httpx
import pytest

from novel_to_comic import mock_models
from novel_to_comic.ai import client

BEATS = [{"beat_id": "b1", "summary": "The stars are wrong."}]
LEDGER = [{"source_id": "s1", "beat_ids": ["b1"]}]


@pytest.fixture
def fixture_project(tmp_path: Path) -> Path:
    (tmp_path / "brief").mkdir()
    (tmp_path / "adapt").mkdir()
    (tmp_path / "plan").mkdir()
    (tmp_path / "story_bible.json").write_text("{}")
    (tmp_path / "brief" / "adaptation_brief.json").write_text("{}")
    (tmp_path / "adapt" / "book.json").write_text(
        json.dumps({"treatment": {}, "beats": BEATS, "ledger": LEDGER})
    )
    (tmp_path / "plan" / "book.json").write_text(json.dumps({"pages": []}))
    (tmp_path / "asset.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    return tmp_path


def _read_via_client(app, monkeypatch, payload: dict) -> dict:
    transport = httpx.ASGITransport(app=app)
    monkeypatch.setattr(client, "_http", httpx.AsyncClient(transport=transport))
    data, _ = asyncio.run(
        client._read_chat_stream("http://mock/v1/chat/completions", headers={}, payload=payload)
    )
    return data


def test_streamed_replay_round_trips_through_the_client(fixture_project, monkeypatch):
    app = mock_models.create_app(fixture_project)
    data = _read_via_client(
        app,
        monkeypatch,
        {
            "stream": True,
            "stream_options": {"include_usage": True},
            "metadata": {"feature": "adapt.book"},
        },
    )

    choice = data["choices"][0]
    assert json.loads(choice["message"]["content"]) == {
        "beats": BEATS,
        "ledger": LEDGER,
    }
    assert choice["finish_reason"] == "stop"
    assert data["usage"]["total_tokens"] == 0


def test_buffered_replay_still_answers_non_streaming_callers(fixture_project):
    from fastapi.testclient import TestClient

    app = mock_models.create_app(fixture_project)
    with TestClient(app) as http:
        response = http.post(
            "/v1/chat/completions", json={"metadata": {"feature": "adapt.book"}}
        )

    assert response.status_code == 200
    body = response.json()
    assert json.loads(body["choices"][0]["message"]["content"])["beats"] == BEATS
