"""Tests for project-creation abuse protection (upload cap + per-user cap).

Covers the launch-hardening additions to server/routers/projects.py:

- ``_save_upload_capped`` streams to disk and aborts (413) past the size cap,
  removing the partial file so disk isn't left polluted.
- ``_max_upload_bytes`` / ``_max_projects_per_user`` read env-configured caps.
"""

import io

import pytest
from fastapi import HTTPException, UploadFile

from novel_to_comic.server.routers import projects


def _upload(data: bytes, name: str = "novel.txt") -> UploadFile:
    return UploadFile(file=io.BytesIO(data), filename=name)


def test_max_upload_bytes_default(monkeypatch):
    monkeypatch.delenv("CANARY_MAX_UPLOAD_MB", raising=False)
    assert projects._max_upload_bytes() == 50 * 1024 * 1024


def test_max_upload_bytes_env(monkeypatch):
    monkeypatch.setenv("CANARY_MAX_UPLOAD_MB", "2")
    assert projects._max_upload_bytes() == 2 * 1024 * 1024


def test_max_projects_per_user_default(monkeypatch):
    monkeypatch.delenv("CANARY_MAX_PROJECTS_PER_USER", raising=False)
    assert projects._max_projects_per_user() == 25


def test_save_upload_under_cap_succeeds(tmp_path, monkeypatch):
    monkeypatch.setattr(projects, "_max_upload_bytes", lambda: 16)
    dst = tmp_path / "input" / "novel.txt"
    projects._save_upload_capped(_upload(b"hello"), dst)
    assert dst.read_bytes() == b"hello"


def test_save_upload_over_cap_raises_413_and_cleans_up(tmp_path, monkeypatch):
    monkeypatch.setattr(projects, "_max_upload_bytes", lambda: 4)
    dst = tmp_path / "input" / "novel.txt"
    with pytest.raises(HTTPException) as exc_info:
        projects._save_upload_capped(_upload(b"way too many bytes"), dst)
    assert exc_info.value.status_code == 413
    # Partial file must be removed so disk isn't polluted by a rejected upload.
    assert not dst.exists()
    assert not list(dst.parent.glob("*")), "leftover partial upload files"


def test_save_upload_chunks_past_cap_aborts_midstream(tmp_path, monkeypatch):
    # Cap between two chunk boundaries: first 1 MB chunk lands, second overflows.
    monkeypatch.setattr(projects, "_max_upload_bytes", lambda: 1_500_000)
    dst = tmp_path / "input" / "novel.txt"
    payload = b"x" * (2 * 1024 * 1024)  # 2 MB, > 1.5 MB cap
    with pytest.raises(HTTPException) as exc_info:
        projects._save_upload_capped(_upload(payload), dst)
    assert exc_info.value.status_code == 413
    assert not dst.exists()
