"""Tests for StageRuntime lifecycle module."""

import pytest
from pathlib import Path
from types import SimpleNamespace

from novel_to_comic.server import metrics
from novel_to_comic.stage_runtime import StageRuntime
from novel_to_comic.state import (
    PipelineState,
    StageStatus,
    create_initial_state,
    load_state,
)


def _state(tmp_path: Path) -> PipelineState:
    state = create_initial_state("test_project", "novel.txt")
    return state


class TestBeginCompleteLifecycle:
    def test_begin_sets_running_status(self, tmp_path):
        state = _state(tmp_path)
        ctx = StageRuntime("brief", state, tmp_path)
        ctx.begin(total=4)
        assert state.stages["brief"].status == StageStatus.RUNNING
        assert state.stages["brief"].items_total == 4

    def test_complete_sets_awaiting_review_for_checkpoint(self, tmp_path):
        state = _state(tmp_path)
        ctx = StageRuntime("brief", state, tmp_path)
        ctx.begin(total=4)
        ctx.complete()
        assert state.stages["brief"].status == StageStatus.AWAITING_REVIEW

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


    def test_local_diagnostics_record_traceback_only_when_enabled(
        self, tmp_path, monkeypatch
    ):
        state = _state(tmp_path)
        monkeypatch.setenv("CANARY_ENV", "dev")
        monkeypatch.setenv("CANARY_LOCAL_DIAGNOSTICS", "true")
        ctx = StageRuntime("adapt", state, tmp_path)
        with pytest.raises(ValueError, match="boom"):
            with ctx.execute(total=1):
                raise ValueError("boom")

        assert "ValueError: boom" in state.stages["adapt"].error_detail
        journal = tmp_path / ".canary" / "diagnostics.jsonl"
        assert journal.exists()
        assert "stage_failed" in journal.read_text()
        restored = load_state(tmp_path)
        assert "ValueError: boom" in restored.stages["adapt"].error_detail
        with StageRuntime("adapt", restored, tmp_path).execute():
            pass
        recovered = load_state(tmp_path).stages["adapt"]
        assert recovered.status == StageStatus.COMPLETE
        assert recovered.error is None
        assert recovered.error_detail is None

    def test_production_diagnostics_keep_tracebacks_private(self, tmp_path, monkeypatch):
        state = _state(tmp_path)
        monkeypatch.setenv("CANARY_ENV", "production")
        monkeypatch.setenv("CANARY_LOCAL_DIAGNOSTICS", "true")
        ctx = StageRuntime("adapt", state, tmp_path)
        with pytest.raises(ValueError, match="boom"):
            with ctx.execute(total=1):
                raise ValueError("boom")

        assert state.stages["adapt"].error_detail is None
        assert not (tmp_path / ".canary" / "diagnostics.jsonl").exists()
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

    def test_set_progress_total_cannot_fall_behind_completed_work(self, tmp_path):
        events = []
        state = _state(tmp_path)
        ctx = StageRuntime("plan", state, tmp_path, on_event=events.append)
        ctx.begin(total=1)
        ctx.record_item_done()
        ctx.set_progress_total(0)

        assert state.stages["plan"].items_done == 1
        assert state.stages["plan"].items_total == 1
        assert events[-1] == {
            "type": "stage_progress",
            "stage": "plan",
            "done": 1,
            "total": 1,
        }

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

    def test_record_item_done_persists_progress_for_status_polling(self, tmp_path):
        state = _state(tmp_path)
        ctx = StageRuntime("adapt", state, tmp_path)
        ctx.begin(total=2)

        ctx.record_item_done()

        persisted = load_state(tmp_path)
        assert persisted.stages["adapt"].status == StageStatus.RUNNING
        assert persisted.stages["adapt"].items_done == 1
        assert persisted.stages["adapt"].items_total == 2
        assert persisted.stages["adapt"].last_progress_at is not None

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


class TestPageEvents:
    def test_emit_page_start_includes_page_and_iso_timestamp(self, tmp_path):
        events = []
        state = _state(tmp_path)
        ctx = StageRuntime("draw", state, tmp_path, on_event=events.append)
        ctx.emit_page_start(7)
        evt = next(e for e in events if e["type"] == "page_start")
        assert evt["stage"] == "draw"
        assert evt["page_number"] == 7
        # ISO-8601 with timezone
        assert "T" in evt["started_at"]
        assert evt["started_at"].endswith("+00:00") or evt["started_at"].endswith("Z")

    def test_emit_page_done_ok(self, tmp_path):
        events = []
        state = _state(tmp_path)
        ctx = StageRuntime("draw", state, tmp_path, on_event=events.append)
        ctx.emit_page_done(7, revision=1, status="ok", duration_ms=14320)
        evt = next(e for e in events if e["type"] == "page_done")
        assert evt["status"] == "ok"
        assert evt["duration_ms"] == 14320
        assert evt["error"] is None

    def test_emit_page_done_failed_carries_error(self, tmp_path):
        events = []
        state = _state(tmp_path)
        ctx = StageRuntime("draw", state, tmp_path, on_event=events.append)
        ctx.emit_page_done(
            2, revision=2, status="failed", duration_ms=812, error="provider blocked"
        )
        evt = next(e for e in events if e["type"] == "page_done")
        assert evt["status"] == "failed"
        assert evt["error"] == "provider blocked"

    def test_page_helpers_are_noop_without_callback(self, tmp_path):
        # Should not raise when no on_event is wired (CLI mode).
        state = _state(tmp_path)
        ctx = StageRuntime("draw", state, tmp_path)
        ctx.emit_page_start(1)
        ctx.emit_page_done(1, revision=1, status="ok", duration_ms=100)


class TestActivity:
    def _ctx(self, tmp_path, events: list):
        return StageRuntime("adapt", _state(tmp_path), tmp_path, events.append)

    def test_first_activity_emits_and_clamps_fraction(self, tmp_path):
        events: list = []
        ctx = self._ctx(tmp_path, events)
        ctx.activity(fraction=1.4, detail="drafting")
        assert len(events) == 1
        assert events[0]["type"] == "stage_activity"
        assert events[0]["fraction"] == 1.0
        assert events[0]["detail"] == "drafting"
        assert events[0]["at"]

    def test_negative_fraction_clamps_to_zero(self, tmp_path):
        events: list = []
        self._ctx(tmp_path, events).activity(fraction=-2.0)
        assert events[0]["fraction"] == 0.0

    def test_rapid_small_moves_are_throttled(self, tmp_path):
        events: list = []
        ctx = self._ctx(tmp_path, events)
        ctx.activity(fraction=0.10)
        for _ in range(50):
            ctx.activity(fraction=0.101)
        assert len(events) == 1

    def test_large_move_bypasses_the_time_throttle(self, tmp_path):
        events: list = []
        ctx = self._ctx(tmp_path, events)
        ctx.activity(fraction=0.10)
        ctx.activity(fraction=0.40)
        assert [e["fraction"] for e in events] == [0.10, 0.40]

    def test_force_emits_even_when_throttled(self, tmp_path):
        events: list = []
        ctx = self._ctx(tmp_path, events)
        ctx.activity(fraction=0.10)
        ctx.activity(fraction=0.101, force=True)
        assert len(events) == 2

    def test_activity_does_not_touch_item_counters(self, tmp_path):
        events: list = []
        state = _state(tmp_path)
        ctx = StageRuntime("adapt", state, tmp_path, events.append)
        ctx.begin(total=5)
        ctx.activity(fraction=0.9, detail="drafting")
        # Advisory only: a stale fraction must never be mistaken for progress.
        assert state.stages["adapt"].items_done == 0


def test_refusal_persists_machine_readable_error_code(tmp_path):
    import pytest
    from novel_to_comic.ai.errors import AIRefusalError
    state = _state(tmp_path)
    ctx = StageRuntime("extract", state, tmp_path)
    with pytest.raises(AIRefusalError):
        with ctx.execute():
            raise AIRefusalError("Provider declined")
    assert state.stages["extract"].error_code == "model_refusal"
    ctx.fail("Ordinary failure")
    assert state.stages["extract"].error_code is None
