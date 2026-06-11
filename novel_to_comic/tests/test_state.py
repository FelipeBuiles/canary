"""Tests for pipeline state machine (state.py)."""

from datetime import datetime, timedelta, timezone
import json
import tempfile
from pathlib import Path

import pytest

from novel_to_comic.state import (
    PipelineState,
    StageState,
    StageStatus,
    STAGE_NAMES,
    CHECKPOINT_STAGES,
    create_initial_state,
    begin_stage,
    complete_stage,
    fail_stage,
    approve_stage,
    record_item_done,
    record_item_failed,
    is_stale,
    get_stale_stages,
    reset_stale_stages,
    load_state,
    save_state,
)


class TestStageState:
    def test_default_status_is_pending(self):
        s = StageState()
        assert s.status == StageStatus.PENDING
        assert s.items_done == 0
        assert s.items_total == 0
        assert s.items_failed == []
        assert s.cost_usd == 0.0
        assert s.error is None
        assert s.approved is None


class TestPipelineState:
    def test_creates_all_stages_on_init(self):
        state = create_initial_state("my-project", "novel.txt")
        assert list(state.stages.keys()) == STAGE_NAMES
        assert len(state.stages) == len(STAGE_NAMES)

    def test_total_cost_starts_at_zero(self):
        state = create_initial_state("p", "n.txt")
        assert state.total_cost_usd == 0.0

    def test_stage_names_are_in_order(self):
        assert STAGE_NAMES == [
            "extract", "style", "cast", "adapt", "plan",
            "storyboard", "direct", "draw", "compose",
        ]

    def test_checkpoint_stages(self):
        assert CHECKPOINT_STAGES == {"extract", "style", "cast", "draw"}
        # adapt, plan, storyboard, direct auto-run (4-station model);
        # compose is NOT a checkpoint either
        assert "adapt" not in CHECKPOINT_STAGES
        assert "plan" not in CHECKPOINT_STAGES
        assert "storyboard" not in CHECKPOINT_STAGES
        assert "direct" not in CHECKPOINT_STAGES
        assert "compose" not in CHECKPOINT_STAGES


class TestBeginStage:
    def test_sets_status_running(self):
        state = create_initial_state("p", "n.txt")
        begin_stage(state, "extract")
        assert state.stages["extract"].status == StageStatus.RUNNING

    def test_clears_previous_items(self):
        state = create_initial_state("p", "n.txt")
        state.stages["extract"].items_done = 5
        state.stages["extract"].items_failed = ["a", "b"]
        begin_stage(state, "extract", total=10)
        assert state.stages["extract"].items_done == 0
        assert state.stages["extract"].items_failed == []

    def test_accepts_total_items(self):
        state = create_initial_state("p", "n.txt")
        begin_stage(state, "draw", total=12)
        assert state.stages["draw"].items_total == 12


class TestCompleteStage:
    def test_non_checkpoint_marks_complete(self):
        state = create_initial_state("p", "n.txt")
        begin_stage(state, "adapt")
        complete_stage(state, "adapt")
        assert state.stages["adapt"].status == StageStatus.COMPLETE

    def test_checkpoint_marks_awaiting_review(self):
        state = create_initial_state("p", "n.txt")
        begin_stage(state, "extract")
        complete_stage(state, "extract")
        assert state.stages["extract"].status == StageStatus.AWAITING_REVIEW

    def test_updates_total_cost(self):
        state = create_initial_state("p", "n.txt")
        state.stages["extract"].cost_usd = 0.05
        state.stages["cast"].cost_usd = 0.03
        complete_stage(state, "extract")
        # extract is checkpoint → awaiting_review, still counts toward total
        assert state.total_cost_usd == pytest.approx(0.08)


class TestFailStage:
    def test_sets_failed_status(self):
        state = create_initial_state("p", "n.txt")
        begin_stage(state, "adapt")
        fail_stage(state, "adapt", "API timeout")
        assert state.stages["adapt"].status == StageStatus.FAILED
        assert state.stages["adapt"].error == "API timeout"

    def test_includes_error_in_total_cost(self):
        state = create_initial_state("p", "n.txt")
        state.stages["extract"].cost_usd = 0.05
        fail_stage(state, "extract", "boom")
        assert state.total_cost_usd == 0.05


class TestApproveStage:
    def test_awaiting_review_becomes_complete(self):
        state = create_initial_state("p", "n.txt")
        state.stages["extract"].status = StageStatus.AWAITING_REVIEW
        approve_stage(state, "extract")
        assert state.stages["extract"].status == StageStatus.COMPLETE
        assert state.stages["extract"].approved is True

    def test_non_awaiting_review_raises(self):
        state = create_initial_state("p", "n.txt")
        state.stages["extract"].status = StageStatus.COMPLETE
        with pytest.raises(ValueError, match="not awaiting review"):
            approve_stage(state, "extract")


class TestRecordItemDone:
    def test_increments_items_done(self):
        state = create_initial_state("p", "n.txt")
        record_item_done(state, "draw")
        assert state.stages["draw"].items_done == 1
        record_item_done(state, "draw", cost=0.01)
        assert state.stages["draw"].items_done == 2
        assert state.stages["draw"].cost_usd == pytest.approx(0.01)


class TestRecordItemFailed:
    def test_appends_to_items_failed(self):
        state = create_initial_state("p", "n.txt")
        record_item_failed(state, "draw", "scene_001-panel_03")
        assert "scene_001-panel_03" in state.stages["draw"].items_failed


class TestIsStale:
    def test_not_stale_if_not_running(self):
        s = StageState(status=StageStatus.COMPLETE)
        assert is_stale(s) is False

    def test_not_stale_if_just_started(self):
        s = StageState(status=StageStatus.RUNNING, started_at=datetime.now(timezone.utc))
        assert is_stale(s) is False

    def test_stale_after_threshold_with_no_progress(self):
        s = StageState(
            status=StageStatus.RUNNING,
            started_at=datetime.now(timezone.utc) - timedelta(minutes=6),
        )
        assert is_stale(s) is True

    def test_recent_heartbeat_resets_stale_window(self):
        # Started 10 minutes ago but progress was reported 30 seconds ago —
        # this is the long-draw case the old heuristic falsely flagged.
        s = StageState(
            status=StageStatus.RUNNING,
            started_at=datetime.now(timezone.utc) - timedelta(minutes=10),
            last_progress_at=datetime.now(timezone.utc) - timedelta(seconds=30),
        )
        assert is_stale(s) is False

    def test_old_heartbeat_is_stale(self):
        s = StageState(
            status=StageStatus.RUNNING,
            started_at=datetime.now(timezone.utc) - timedelta(minutes=20),
            last_progress_at=datetime.now(timezone.utc) - timedelta(minutes=6),
        )
        assert is_stale(s) is True

    def test_no_heartbeat_falls_back_to_started_at(self):
        # Stage just began — last_progress_at is None until the first
        # record_item_done call.
        s = StageState(
            status=StageStatus.RUNNING,
            started_at=datetime.now(timezone.utc) - timedelta(minutes=2),
            last_progress_at=None,
        )
        assert is_stale(s) is False


class TestRecordItemDoneHeartbeat:
    def test_record_item_done_updates_last_progress_at(self):
        from novel_to_comic.state import record_item_done
        state = create_initial_state("p", "n.txt")
        begin_stage(state, "draw", total=3)
        before = state.stages["draw"].last_progress_at
        record_item_done(state, "draw")
        after = state.stages["draw"].last_progress_at
        assert before is None
        assert after is not None

    def test_begin_stage_resets_last_progress_at(self):
        from novel_to_comic.state import record_item_done
        state = create_initial_state("p", "n.txt")
        begin_stage(state, "draw", total=3)
        record_item_done(state, "draw")
        assert state.stages["draw"].last_progress_at is not None
        # Re-begin the stage (e.g. rerun) — heartbeat should be cleared so
        # is_stale falls back to the new started_at.
        begin_stage(state, "draw", total=3)
        assert state.stages["draw"].last_progress_at is None


class TestGetStaleStages:
    def test_finds_stale_running_stages(self):
        state = create_initial_state("p", "n.txt")
        state.stages["extract"].status = StageStatus.RUNNING
        state.stages["extract"].started_at = datetime.now(timezone.utc) - timedelta(minutes=10)
        state.stages["cast"].status = StageStatus.RUNNING
        state.stages["cast"].started_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        stale = get_stale_stages(state)
        assert stale == ["extract"]


class TestResetStaleStages:
    def test_resets_only_stale_stages(self):
        state = create_initial_state("p", "n.txt")
        state.stages["extract"].status = StageStatus.RUNNING
        state.stages["extract"].started_at = datetime.now(timezone.utc) - timedelta(minutes=10)
        state.stages["cast"].status = StageStatus.RUNNING
        state.stages["cast"].started_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        reset = reset_stale_stages(state)
        assert reset == ["extract"]
        assert state.stages["extract"].status == StageStatus.PENDING
        assert state.stages["cast"].status == StageStatus.RUNNING  # untouched


class TestLoadSaveState:
    def test_save_and_load_roundtrip(self):
        state = create_initial_state("my-project", "novel.txt")
        state.stages["extract"].status = StageStatus.COMPLETE
        state.stages["extract"].cost_usd = 0.05

        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = Path(tmpdir)
            save_state(state, project_dir)
            loaded = load_state(project_dir)

        assert loaded.project_name == "my-project"
        assert loaded.stages["extract"].status == StageStatus.COMPLETE
        assert loaded.stages["extract"].cost_usd == pytest.approx(0.05)

    def test_load_raises_on_missing_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with pytest.raises(FileNotFoundError):
                load_state(Path(tmpdir))

    def test_all_eight_stages_present_after_load(self):
        state = create_initial_state("p", "n.txt")
        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = Path(tmpdir)
            save_state(state, project_dir)
            loaded = load_state(project_dir)
        assert list(loaded.stages.keys()) == STAGE_NAMES
