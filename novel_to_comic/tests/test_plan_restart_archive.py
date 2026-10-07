"""Plan restarts retain paid work even when old artifact schemas cannot load."""
from novel_to_comic.server import pipeline_operations
from pathlib import Path
from types import SimpleNamespace
import asyncio

import pytest
from fastapi import HTTPException

from novel_to_comic.config import Config
from novel_to_comic.target_artifacts import TargetArtifacts
from novel_to_comic.server.routers import pipeline


def old_book(root):
    files = {"plan/book.json": b"incompatible plan", "draw/pages/page_001/render_001.png": b"paid art",
             "draw/pages/page_001/render_002.png": b"paid revision", "finish/book.pdf": b"finished book",
             "exports/book.cbz": b"export", "lettering/pages/page_001.json": b"lettering",
             ".checkpoints/plan/work/budget.json": b"budget", "adapt/book.json": b"upstream",
             "lettering/style.json": b"book style"}
    for name, data in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    return files


def test_plan_archive_keeps_art_accessible_and_does_not_rebind_it(tmp_path):
    files = old_book(tmp_path)
    target = TargetArtifacts(tmp_path)
    assert target.drawn_page_count() == 1
    pipeline_operations._clear_outputs_for_rerun(tmp_path, "plan")
    archive, = target.restart_archives()
    assert archive["page_count"] == 1
    assert not target.plan_path.exists()
    for name, data in files.items():
        if name in {"adapt/book.json", "lettering/style.json"}:
            assert (tmp_path / name).read_bytes() == data
        else:
            assert (tmp_path / ".checkpoints/restarts" / archive["id"] / name).read_bytes() == data
    assert target.restart_archive_file(archive["id"], "draw/pages/page_001/render_002.png").read_bytes() == b"paid revision"
    assert target.restart_archive_file(archive["id"], "finish/book.pdf").read_bytes() == b"finished book"
    for bad in ("../../state.json", "state.json", "draw/../../adapt/book.json", "/etc/passwd"):
        with pytest.raises(ValueError):
            target.restart_archive_file(archive["id"], bad)


def test_archive_failure_rolls_back_every_move(tmp_path, monkeypatch):
    files = old_book(tmp_path)
    rename = Path.rename
    def failing(source, destination):
        if source == tmp_path / "draw":
            raise OSError("disk error")
        return rename(source, destination)
    monkeypatch.setattr(Path, "rename", failing)
    with pytest.raises(OSError, match="disk error"):
        pipeline_operations._clear_outputs_for_rerun(tmp_path, "plan")
    assert all((tmp_path / name).read_bytes() == data for name, data in files.items())
    assert TargetArtifacts(tmp_path).restart_archives() == []


@pytest.mark.parametrize("confirmed", [None, 0, 2])
def test_plan_restart_requires_current_page_count_before_spend(tmp_path, monkeypatch, confirmed):
    files = old_book(tmp_path)
    monkeypatch.setattr(pipeline, "project_busy", lambda *args, **kwargs: False)
    monkeypatch.setattr(pipeline, "admit_stage_action", lambda *args: None)
    with pytest.raises(HTTPException) as caught:
        asyncio.run(pipeline._start_stage(SimpleNamespace(app=None), "book", "plan", True,
            (tmp_path, Config(), None), "account", confirmed_archive_pages=confirmed))
    assert caught.value.status_code == 409
    assert "1 drawn pages" in caught.value.detail
    assert all((tmp_path / name).read_bytes() == data for name, data in files.items())


def test_archive_file_cannot_follow_a_symlink_outside_the_archive(tmp_path):
    old_book(tmp_path)
    target = TargetArtifacts(tmp_path)
    root = target.archive_stage_work("plan")
    outside = tmp_path / "private.png"
    outside.write_bytes(b"private")
    (root / "draw" / "escape.png").symlink_to(outside)
    with pytest.raises(ValueError):
        target.restart_archive_file(root.name, "draw/escape.png")
    assert "draw/escape.png" not in target.restart_archives()[0]["files"]
