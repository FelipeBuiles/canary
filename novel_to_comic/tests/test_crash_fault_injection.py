"""Offline hard-exit exercises; the ledger/provider are explicitly test doubles.

The child exits without finally handlers, using real admission/job SQLite and
complete-page artifacts. No network transport or production database is used.
"""
from __future__ import annotations

import asyncio
import os
from pathlib import Path
import subprocess
import sys

import httpx
import pytest

from novel_to_comic.server.generation_jobs import recovered_generation_jobs
from novel_to_comic.target_artifacts import TargetArtifacts
from tests.test_server_admission import app_at


def _child(root: Path, phase: str):
    from novel_to_comic.server import credited_job
    from novel_to_comic.server.generation_jobs import persist_generation_job
    from novel_to_comic.usage import ApiResult
    from tests.test_complete_page_draw import (
        _compile, _page, _provider_result, _RecordingTransport,
        VertexCompletePageAdapter, draw_complete_page,
    )

    root.mkdir(parents=True, exist_ok=True)
    if phase == "export":
        from tests.test_page_finishing import _write_valid_book, FinishProductionSpec, finish_book
        from novel_to_comic import page_finishing
        artifacts, _ = _write_valid_book(root / "book")
        atomic = page_finishing._atomic_write

        def crash_during_package(path, data):
            if path.suffix == ".pdf":
                path.parent.mkdir(parents=True, exist_ok=True)
                path.with_suffix(".pdf.tmp").write_bytes(data[:100])
                os._exit(73)
            atomic(path, data)

        page_finishing._atomic_write = crash_during_package
        finish_book(artifacts, production=FinishProductionSpec(canvas_width=120, canvas_height=180, bleed_px=10))
        raise AssertionError("fault was not reached")

    app = app_at(root)
    app.state.generation_queue = asyncio.Queue()
    artifacts = TargetArtifacts(root / "book")
    credited_job.get_db = lambda: None

    def reserve(*args):
        (root / "hold").write_text("reserved")
        return "hold", "ledger-job"

    credited_job.reserve_credits = reserve
    credited_job.assert_reservation_active = lambda *args: None
    credited_job.release_reservation = lambda *args: (root / "hold").write_text("released")

    def settle(*args, **kwargs):
        assert phase == "saved_before_settlement"
        os._exit(73)

    credited_job.debit_model_usage = settle

    transport = _RecordingTransport(_provider_result())
    (root / "usage-call-id").write_text(transport.result.usage.call_id)
    adapter = VertexCompletePageAdapter(transport)
    original_generate = adapter.generate

    async def generate(prepared):
        (root / "submissions").write_text("1")
        if phase == "after_submission":
            os._exit(73)
        return await original_generate(prepared)

    adapter.generate = generate

    async def work():
        if phase == "before_submission":
            os._exit(73)
        saved = await draw_complete_page(
            _compile(root), adapter=adapter, artifacts=artifacts, page=_page(),
            defer_completion=True,
        )
        return ApiResult(value=saved, usage=saved.usage)

    @app.post("/api/projects/book/pages/7/generate")
    async def paid():
        job, _ = credited_job.enqueue_reserved_generation_job(
            app, project_name="account:book", user_id="account", project_id="book",
            project_dir=root / "book", stage="draw", kind="complete_page_draw",
            label="Page 7", payload={"page_number": 7}, work=work,
            debit_description="Page", reservation_credits=2,
            operations=(("complete_page", "image-balanced"),),
        )
        job.status = "running"
        persist_generation_job(app, job)
        await job.runner()
        raise AssertionError("fault was not reached")

    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            await client.post("/api/projects/book/pages/7/generate", headers={"Idempotency-Key": "fault-action"})
    asyncio.run(run())


def _crash(root, phase):
    child = subprocess.run([sys.executable, "-m", "tests.test_crash_fault_injection", str(root), phase], cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, timeout=30)
    assert child.returncode == 73, child.stderr


@pytest.mark.parametrize("phase", ["before_submission", "after_submission", "saved_before_settlement"])
def test_hard_exit_never_replays_paid_action_or_releases_hold(tmp_path, phase):
    _crash(tmp_path, phase)
    app = app_at(tmp_path)
    calls = []

    @app.post("/api/projects/book/pages/7/generate")
    async def forbidden_replay():
        calls.append(True)
        raise AssertionError("restart must not submit or settle anything")

    async def retry():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            return await client.post("/api/projects/book/pages/7/generate", headers={"Idempotency-Key": "fault-action"})

    for _ in range(2):
        response = asyncio.run(retry())
        assert response.status_code == 409
        assert response.json()["detail"]["code"] == "idempotency_indeterminate"
    assert calls == []
    jobs = recovered_generation_jobs(app, "account:book")
    assert len(jobs) == 1 and jobs[0]["status"] == "failed"
    assert jobs[0]["payload"]["page_number"] == 7
    assert (tmp_path / "hold").read_text() == "reserved"
    submissions = tmp_path / "submissions"
    assert (submissions.read_text() if submissions.exists() else "0") == ("0" if phase == "before_submission" else "1")
    if phase == "saved_before_settlement":
        from tests.test_complete_page_draw import _provider_result
        artifacts = TargetArtifacts(tmp_path / "book")
        assert artifacts.read_render(7, 1) == _provider_result().image_bytes
        assert artifacts.read_provenance(7, 1).usage.model_dump(exclude={"call_id"}) == _provider_result().usage.model_dump(exclude={"call_id"})
        assert artifacts.read_provenance(7, 1).usage.call_id == (tmp_path / "usage-call-id").read_text()
        assert artifacts.resumable_generation_request(7) is not None


def test_hard_exit_during_export_preserves_artwork_and_rebuilds_offline(tmp_path):
    _crash(tmp_path, "export")
    from tests.test_page_finishing import FinishProductionSpec, finish_book
    artifacts = TargetArtifacts(tmp_path / "book")
    before = artifacts.read_render(1, 1)
    assert not artifacts.export_path("pdf").exists()
    result = finish_book(artifacts, production=FinishProductionSpec(canvas_width=120, canvas_height=180, bleed_px=10))
    assert result.preflight.ready_to_export
    assert {package.format for package in result.packages} == {"pdf", "cbz"}
    assert artifacts.read_render(1, 1) == before
    assert not (tmp_path / "submissions").exists()
    assert not (tmp_path / "hold").exists()


if __name__ == "__main__":
    _child(Path(sys.argv[1]), sys.argv[2])
