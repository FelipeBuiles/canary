import asyncio
from functools import wraps
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from novel_to_comic.config import Config
from novel_to_comic.server.credited_job import CreditReservationDenied
from novel_to_comic.server.event_channel import EventChannel
from novel_to_comic.server.routers import pipeline
from novel_to_comic.state import PipelineState, StageState, StageStatus, load_state, save_state


def run_async(test):
    @wraps(test)
    def run(*args, **kwargs):
        return asyncio.run(test(*args, **kwargs))
    return run


def existing_project(tmp_path):
    state = PipelineState(
        project_name="book", novel_path="novel.txt",
        created_at="2026-01-01T00:00:00Z",
    )
    state.stages["extract"] = StageState(status=StageStatus.COMPLETE)
    save_state(state, tmp_path)
    artifact = tmp_path / "story_bible.json"
    artifact.write_text('{"paid": "prior output"}')
    return state, artifact


@run_async
async def test_rejected_rerun_keeps_paid_output_and_state(tmp_path, monkeypatch):
    state, artifact = existing_project(tmp_path)
    before = (tmp_path / "state.json").read_bytes()
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(running_tasks={}, style_tasks={}, generation_jobs={})))
    monkeypatch.setattr(pipeline, "estimate_stage_credit_reservation", lambda *args: 100)
    monkeypatch.setattr(pipeline, "get_db", lambda: object())

    def reject(*args, **kwargs):
        raise HTTPException(402, "Insufficient credits")

    monkeypatch.setattr(pipeline, "assert_sufficient_credits", reject)
    with pytest.raises(HTTPException) as denied:
        await pipeline._start_stage(request, "book", "extract", True, (tmp_path, Config(), state), "account")
    assert denied.value.status_code == 402
    assert artifact.read_text() == '{"paid": "prior output"}'
    assert (tmp_path / "state.json").read_bytes() == before


@run_async
async def test_reservation_race_rejection_does_not_reset_rerun(tmp_path, monkeypatch):
    state, artifact = existing_project(tmp_path)
    before = (tmp_path / "state.json").read_bytes()

    async def reject(**kwargs):
        raise CreditReservationDenied("Another action consumed the balance")

    monkeypatch.setattr(pipeline, "run_credited_stage", reject)
    monkeypatch.setattr(pipeline, "capture_server_event", lambda *args, **kwargs: None)
    await pipeline._run_stage_with_credits("extract", Config(), tmp_path, state, EventChannel(), "account", "book", rerun=True)
    assert artifact.read_text() == '{"paid": "prior output"}'
    assert (tmp_path / "state.json").read_bytes() == before


def test_failed_stage_reset_returns_pending_without_destroying_outputs(tmp_path):
    state, artifact = existing_project(tmp_path)
    state.stages["extract"] = StageState(status=StageStatus.FAILED, error="provider unavailable")
    save_state(state, tmp_path)
    response = pipeline.reset_stage("extract", "book", (tmp_path, Config(), state), "account")
    assert response == {"status": "reset", "reset": ["extract"]}
    assert load_state(tmp_path).stages["extract"].status == StageStatus.PENDING
    assert artifact.read_text() == '{"paid": "prior output"}'


@run_async
async def test_missing_style_rejects_rerun_without_reset(tmp_path, monkeypatch):
    state, artifact = existing_project(tmp_path)
    state.stages["cast"] = StageState(status=StageStatus.COMPLETE)
    save_state(state, tmp_path)
    before = (tmp_path / "state.json").read_bytes()
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(running_tasks={}, style_tasks={}, generation_jobs={})))
    monkeypatch.setattr("novel_to_comic.server.routers.styles.is_style_selected", lambda *args: False)
    with pytest.raises(HTTPException) as denied:
        await pipeline._start_stage(request, "book", "cast", True, (tmp_path, Config(), state), "account")
    assert denied.value.status_code == 403
    assert artifact.exists()
    assert (tmp_path / "state.json").read_bytes() == before
