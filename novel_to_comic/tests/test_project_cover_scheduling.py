"""Cover creation follows Draw startup and never replays old paid attempts."""
from novel_to_comic.server import cover_operations, pipeline_operations
import asyncio
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import HTTPException

from novel_to_comic.config import Config
from novel_to_comic.models.story_bible import Character, StoryBible
from novel_to_comic.server.routers import pipeline, projects
from novel_to_comic.server.generation_jobs import enqueue_generation_job
from novel_to_comic.state import PipelineState, StageState, StageStatus
from tests.test_server_admission import app_at


@pytest.mark.parametrize("status", [StageStatus.AWAITING_REVIEW, StageStatus.COMPLETE, StageStatus.FAILED])
def test_cast_never_queues_cover_before_adaptation(tmp_path, monkeypatch, status):
    state = PipelineState(project_name="book", novel_path="book.txt", created_at="2026-09-12")
    order = []
    async def credited(**kwargs):
        order.append("cast")
        state.stages["cast"] = StageState(status=status)
        return "cast-job"
    def enqueue(*args):
        assert state.stages["cast"].status in {StageStatus.AWAITING_REVIEW, StageStatus.COMPLETE}
        order.append("cover")
    monkeypatch.setattr(pipeline_operations, "run_credited_stage", credited)
    monkeypatch.setattr(pipeline_operations, "capture_server_event", lambda *a, **k: None)
    monkeypatch.setattr(cover_operations, "enqueue_project_cover", enqueue)
    request = SimpleNamespace(app=app_at(tmp_path))
    asyncio.run(pipeline_operations._run_stage_with_credits(
        "cast", Config(), tmp_path, state, asyncio.Queue(), "account", "book", request=request,
    ))
    assert order == ["cast"]


def test_cover_attempt_is_not_replayed_after_restart(tmp_path):
    app = app_at(tmp_path)
    app.state.generation_queue = asyncio.Queue()
    async def never_run():
        raise AssertionError("Do not submit images during recovery")
    enqueue_generation_job(app, "account:book", "project_cover", "Cover", {}, never_run)
    restarted = app_at(tmp_path)
    restarted.state.projects_dir = tmp_path
    from novel_to_comic.server.durable_queue import DurableQueue
    asyncio.run(DurableQueue(restarted, 'postgresql://unused').restore())
    for current in (app, restarted):
        request = SimpleNamespace(app=current)
        assert not cover_operations.needs_initial_project_cover(request, "account:book", tmp_path)
        assert cover_operations.needs_initial_project_cover(request, "account:other", tmp_path)
        payload = projects._project_cover_job_payload(request, "account:book", tmp_path)
        assert payload["status"] == ("queued" if current is app else "failed")


def test_existing_cover_does_not_generate_again(tmp_path):
    (tmp_path / "cover").mkdir()
    (tmp_path / "cover/cover.png").write_bytes(b"existing artwork")
    assert not cover_operations.needs_initial_project_cover(SimpleNamespace(app=app_at(tmp_path)), "account:book", tmp_path)


def test_missing_character_reference_is_rejected_before_credit_reservation(tmp_path, monkeypatch):
    from novel_to_comic.server import credited_job
    bible = StoryBible(title="Book", author="Author", total_scenes=0, characters=[Character(
        id="ada", name="Ada", visual_anchor="An adult with dark curls", age_range="adult",
        gender="female", distinguishing_features=[], default_outfit="coat", first_appearance_scene="scene_1",
    )], locations=[], scenes=[], sequences=[])
    (tmp_path / "story_bible.json").write_text(bible.model_dump_json())
    enqueue = Mock()
    monkeypatch.setattr(credited_job, "enqueue_credited_job", enqueue)
    with pytest.raises(HTTPException) as caught:
        asyncio.run(cover_operations.enqueue_project_cover(SimpleNamespace(app=app_at(tmp_path)), "book", (tmp_path, Config(), None), "account"))
    assert caught.value.status_code == 409
    assert "Ada" in caught.value.detail
    enqueue.assert_not_called()


def test_cast_estimate_excludes_deferred_cover(tmp_path, monkeypatch):
    estimate = {"estimate_credits": 20, "reserved_credits": 25, "reservation_multiplier": 1.25,
                "confidence": "usually_within_estimate", "funding": "api"}
    monkeypatch.setattr(pipeline.UnifiedCostResolver, "estimate_stage_cost", lambda *a: estimate)
    monkeypatch.setattr(cover_operations, "_project_cover_credit_estimate", lambda *a: {**estimate, "estimate_credits": 5, "reserved_credits": None})
    request = SimpleNamespace(app=app_at(tmp_path))
    for needs_cover, expected in ((True, 20), (False, 20)):
        monkeypatch.setattr(cover_operations, "needs_initial_project_cover", lambda *a: needs_cover)
        result = asyncio.run(pipeline.estimate_stage_cost(request, "book", "cast", (tmp_path, Config(), None), "account"))
        assert result["estimate_credits"] == expected
        assert result["reserved_credits"] == 25


def test_cover_enqueue_failure_keeps_cast_successful(tmp_path, monkeypatch):
    state = PipelineState(project_name="book", novel_path="book.txt", created_at="2026-09-12")
    async def credited(**kwargs):
        state.stages["cast"] = StageState(status=StageStatus.AWAITING_REVIEW)
        return "cast-job"
    monkeypatch.setattr(pipeline_operations, "run_credited_stage", credited)
    monkeypatch.setattr(pipeline_operations, "capture_server_event", lambda *a, **k: None)
    monkeypatch.setattr(cover_operations, "enqueue_project_cover", Mock(side_effect=HTTPException(402, "Insufficient credits")))
    asyncio.run(pipeline_operations._run_stage_with_credits(
        "cast", Config(), tmp_path, state, asyncio.Queue(), "account", "book",
        request=SimpleNamespace(app=app_at(tmp_path)),
    ))
    assert state.stages["cast"].status == StageStatus.AWAITING_REVIEW


def test_cover_queues_after_draw_initializes(tmp_path, monkeypatch):
    state = PipelineState(project_name="book", novel_path="book.txt", created_at="2026-09-12")
    order = []
    async def run(*args, **_kwargs):
        order.append("draw")
        state.stages["draw"] = StageState(status=StageStatus.RUNNING)
    monkeypatch.setattr(pipeline_operations, "_run_stage", run)
    monkeypatch.setattr(pipeline_operations, "capture_server_event", lambda *a, **k: None)
    async def async_cover(*args):
        order.append("cover")
    monkeypatch.setattr(cover_operations, "enqueue_project_cover", async_cover)
    asyncio.run(pipeline_operations._run_stage_with_credits("draw", Config(), tmp_path, state, asyncio.Queue(), "account", "book", request=SimpleNamespace(app=app_at(tmp_path))))
    assert order == ["draw", "cover"]
