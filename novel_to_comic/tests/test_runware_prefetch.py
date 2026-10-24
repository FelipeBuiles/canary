"""Draw's approved references go to Runware, upload-only, once Cast is approved."""
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from novel_to_comic import runware_prefetch
from novel_to_comic.config import Config


@pytest.fixture
def references(tmp_path, monkeypatch):
    a, b = tmp_path / "hero.png", tmp_path / "harbor.png"
    a.write_bytes(b"\x89PNG hero")
    b.write_bytes(b"\x89PNG harbor")
    files = {
        "ref:hero": SimpleNamespace(path=a), "ref:hero:state": SimpleNamespace(path=a),
        "ref:harbor": SimpleNamespace(path=b), "ref:missing": SimpleNamespace(path=tmp_path / "gone.png"),
    }
    monkeypatch.setattr("novel_to_comic.stages.s5_plan.approved_reference_files", lambda project_dir: files)
    return a, b


def _capture(monkeypatch, response=None):
    sent = []

    class Client:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def post(self, url, **kwargs):
            sent.append((url, kwargs))
            return response or httpx.Response(200, json={"data": []}, request=httpx.Request("POST", url))

    monkeypatch.setattr(runware_prefetch.httpx, "Client", Client)
    return sent


def test_each_distinct_reference_is_sent_once_upload_only(tmp_path, references, monkeypatch):
    monkeypatch.setenv("CANARY_RUNWARE_FIRST_ENABLED", "true")
    sent = _capture(monkeypatch)
    count = runware_prefetch.prefetch(Config(litellm_base_url="http://gateway:4000/", litellm_api_key="sk"), tmp_path)

    assert count == 2 and len(sent) == 1
    url, kwargs = sent[0]
    assert url == "http://gateway:4000/v1/images/edits"
    assert kwargs["headers"] == {"Authorization": "Bearer sk"}
    assert kwargs["data"]["model"] == "image-sunburst-runware"
    assert kwargs["data"]["canary_runware_prefetch"] == "1"
    assert sorted(file[1][1] for file in kwargs["files"]) == sorted(p.read_bytes() for p in references)


@pytest.mark.parametrize("enabled,mock", [("", False), ("true", True)])
def test_nothing_is_sent_unless_runware_first_and_real(tmp_path, references, monkeypatch, enabled, mock):
    monkeypatch.setenv("CANARY_RUNWARE_FIRST_ENABLED", enabled)
    sent = _capture(monkeypatch)
    assert runware_prefetch.prefetch(Config(mock_mode=mock), tmp_path) == 0
    assert sent == []


def test_a_background_failure_is_logged_not_raised(tmp_path, references, monkeypatch, caplog):
    monkeypatch.setenv("CANARY_RUNWARE_FIRST_ENABLED", "true")
    _capture(monkeypatch, httpx.Response(500, request=httpx.Request("POST", "http://gateway/v1/images/edits")))
    threads = []
    monkeypatch.setattr(runware_prefetch.threading, "Thread",
                        lambda target, **kwargs: threads.append(target) or SimpleNamespace(start=lambda: None))
    runware_prefetch.start(Config(), Path(tmp_path))
    threads[0]()
    assert "Runware reference prefetch failed" in caplog.text
