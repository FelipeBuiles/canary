"""Tests for StageRuntime lifecycle module."""

import pytest
from pathlib import Path
from types import SimpleNamespace

from novel_to_comic.server import metrics
from novel_to_comic.stage_runtime import StageRuntime
from novel_to_comic.state import PipelineState, StageStatus, create_initial_state


def _state(tmp_path: Path) -> PipelineState:
    state = create_initial_state("test_project", "novel.txt")
    return state


class TestBeginCompleteLifecycle:
    def test_begin_sets_running_status(self, tmp_path):
        state = _state(tmp_path)
        ctx = StageRuntime("extract", state, tmp_path)
        ctx.begin(total=4)
        assert state.stages["extract"].status == StageStatus.RUNNING
        assert state.stages["extract"].items_total == 4

    def test_complete_sets_awaiting_review_for_checkpoint(self, tmp_path):
        state = _state(tmp_path)
        ctx = StageRuntime("extract", state, tmp_path)
        ctx.begin(total=4)
        ctx.complete()
        # extract is a checkpoint stage
        assert state.stages["extract"].status == StageStatus.AWAITING_REVIEW

    def test_complete_sets_complete_for_non_checkpoint(self, tmp_path):
        state = _state(tmp_path)
        ctx = StageRuntime("plan", state, tmp_path)
        ctx.begin(total=3)
        ctx.complete()
        assert state.stages["plan"].status == StageStatus.COMPLETE

    def test_complete_records_and_warns_on_stage_cost_drift(self, tmp_path, caplog):
        metrics.reset_metrics_for_tests()
        state = _state(tmp_path)
        ctx = StageRuntime("plan", state, tmp_path)
        ctx.begin(total=1, estimated_cost_usd=0.1)
        ctx.record_item_done(cost=0.3)

        with caplog.at_level("WARNING", logger="canary.stage_cost"):
            ctx.complete()

        app = SimpleNamespace(
            state=SimpleNamespace(generation_jobs={}, generation_queue=None)
        )
        rendered = metrics.render_metrics(app)
        assert 'canary_stage_cost_ratio_sum{stage="plan"} 3' in rendered
        assert "Stage cost exceeded estimate" in caplog.text

    def test_fail_sets_failed_status(self, tmp_path):
        state = _state(tmp_path)
        ctx = StageRuntime("adapt", state, tmp_path)
        ctx.begin(total=2)
        ctx.fail("something broke")
        assert state.stages["adapt"].status == StageStatus.FAILED
        assert state.stages["adapt"].error == "something broke"


class TestExecuteContextManager:
    def test_clean_exit_calls_complete(self, tmp_path):
        state = _state(tmp_path)
        ctx = StageRuntime("plan", state, tmp_path)
        with ctx.execute(total=1):
            pass
        assert state.stages["plan"].status == StageStatus.COMPLETE

    def test_exception_calls_fail_and_reraises(self, tmp_path):
        state = _state(tmp_path)
        ctx = StageRuntime("adapt", state, tmp_path)
        with pytest.raises(ValueError, match="boom"):
            with ctx.execute(total=1):
                raise ValueError("boom")
        assert state.stages["adapt"].status == StageStatus.FAILED
        assert "boom" in state.stages["adapt"].error

    def test_execute_saves_state_on_begin(self, tmp_path):
        state = _state(tmp_path)
        ctx = StageRuntime("plan", state, tmp_path)
        with ctx.execute(total=2):
            pass
        assert (tmp_path / "state.json").exists()


class TestEventEmission:
    def test_emits_stage_begin_on_begin(self, tmp_path):
        events = []
        state = _state(tmp_path)
        ctx = StageRuntime("plan", state, tmp_path, on_event=events.append)
        ctx.begin(total=5)
        assert any(e["type"] == "stage_begin" and e["total"] == 5 for e in events)

    def test_emits_stage_complete_on_complete(self, tmp_path):
        events = []
        state = _state(tmp_path)
        ctx = StageRuntime("plan", state, tmp_path, on_event=events.append)
        with ctx.execute(total=2):
            pass
        assert any(e["type"] == "stage_complete" for e in events)

    def test_emits_stage_fail_on_fail(self, tmp_path):
        events = []
        state = _state(tmp_path)
        ctx = StageRuntime("plan", state, tmp_path, on_event=events.append)
        with pytest.raises(RuntimeError):
            with ctx.execute(total=1):
                raise RuntimeError("oops")
        assert any(e["type"] == "stage_fail" and "oops" in e["message"] for e in events)

    def test_progress_emits_event(self, tmp_path):
        events = []
        state = _state(tmp_path)
        ctx = StageRuntime("plan", state, tmp_path, on_event=events.append)
        ctx.begin(total=3)
        ctx.progress(1, 3)
        assert any(e["type"] == "stage_progress" and e["done"] == 1 for e in events)

    def test_log_emits_event(self, tmp_path):
        events = []
        state = _state(tmp_path)
        ctx = StageRuntime("plan", state, tmp_path, on_event=events.append)
        ctx.begin(total=1)
        ctx.log("hello world", level="info")
        assert any(e["type"] == "log" and e["message"] == "hello world" for e in events)

    def test_on_event_property_returns_none_without_listener(self, tmp_path):
        state = _state(tmp_path)
        ctx = StageRuntime("plan", state, tmp_path)
        assert ctx.on_event is None

    def test_on_event_property_returns_callback_with_listener(self, tmp_path):
        state = _state(tmp_path)

        def cb(e):
            return None

        ctx = StageRuntime("plan", state, tmp_path, on_event=cb)
        assert ctx.on_event is cb


class TestUsageRecording:
    def test_record_item_done_increments_counter(self, tmp_path):
        state = _state(tmp_path)
        ctx = StageRuntime("adapt", state, tmp_path)
        ctx.begin(total=3)
        ctx.record_item_done()
        ctx.record_item_done()
        assert state.stages["adapt"].items_done == 2

    def test_record_item_done_with_cost(self, tmp_path):
        state = _state(tmp_path)
        ctx = StageRuntime("plan", state, tmp_path)
        ctx.begin(total=1)
        ctx.record_item_done(cost=0.05)
        assert state.stages["plan"].cost_usd == pytest.approx(0.05)

    def test_set_style_template_hash(self, tmp_path):
        state = _state(tmp_path)
        ctx = StageRuntime("cast", state, tmp_path)
        ctx.set_style_template_hash("abc123")
        assert state.style_template_hash == "abc123"

    def test_set_estimated_cost(self, tmp_path):
        state = _state(tmp_path)
        ctx = StageRuntime("draw", state, tmp_path)
        ctx.begin(total=5)
        ctx.set_estimated_cost(1.23)
        assert state.stages["draw"].estimated_cost_usd == pytest.approx(1.23)


class TestPanelEvents:
    def test_emit_panel_start_includes_scene_panel_and_iso_timestamp(self, tmp_path):
        events = []
        state = _state(tmp_path)
        ctx = StageRuntime("draw", state, tmp_path, on_event=events.append)
        ctx.emit_panel_start("scene_03", 7)
        evt = next(e for e in events if e["type"] == "panel_start")
        assert evt["stage"] == "draw"
        assert evt["scene_id"] == "scene_03"
        assert evt["panel_number"] == 7
        # ISO-8601 with timezone
        assert "T" in evt["started_at"]
        assert evt["started_at"].endswith("+00:00") or evt["started_at"].endswith("Z")

    def test_emit_panel_done_ok(self, tmp_path):
        events = []
        state = _state(tmp_path)
        ctx = StageRuntime("draw", state, tmp_path, on_event=events.append)
        ctx.emit_panel_done("scene_03", 7, status="ok", duration_ms=14320)
        evt = next(e for e in events if e["type"] == "panel_done")
        assert evt["status"] == "ok"
        assert evt["duration_ms"] == 14320
        assert evt["error"] is None

    def test_emit_panel_done_failed_carries_error(self, tmp_path):
        events = []
        state = _state(tmp_path)
        ctx = StageRuntime("draw", state, tmp_path, on_event=events.append)
        ctx.emit_panel_done(
            "scene_01", 2, status="failed", duration_ms=812, error="provider blocked"
        )
        evt = next(e for e in events if e["type"] == "panel_done")
        assert evt["status"] == "failed"
        assert evt["error"] == "provider blocked"

    def test_panel_helpers_are_noop_without_callback(self, tmp_path):
        # Should not raise when no on_event is wired (CLI mode).
        state = _state(tmp_path)
        ctx = StageRuntime("draw", state, tmp_path)
        ctx.emit_panel_start("scene_01", 1)
        ctx.emit_panel_done("scene_01", 1, status="ok", duration_ms=100)
