"""Provider-free terminal delivery, restart and privacy regression tests."""
from novel_to_comic.server import page_operations
from types import SimpleNamespace
from unittest.mock import patch
import json

import pytest

from novel_to_comic.server.admission import Admission
from novel_to_comic.server import lifecycle_events
from novel_to_comic.state import StageState


def test_terminal_intent_recovers_after_dependency_failure_and_ack_split(tmp_path):
    app = SimpleNamespace(state=SimpleNamespace(admission=Admission(tmp_path)))
    with app.state.admission.journal() as db:
        lifecycle_events.enqueue(db, "operation_completed", "attempt", user_id="synthetic",
                                 properties={"operation_id": "attempt", "status": "failed", "outcome": "outcome_unknown"})
    with patch.object(lifecycle_events, "record_product_event", side_effect=RuntimeError("offline")):
        with pytest.raises(RuntimeError):
            lifecycle_events.flush(app)
    restarted = SimpleNamespace(state=SimpleNamespace(admission=Admission(tmp_path)))
    sent = []
    with patch.object(lifecycle_events, "record_product_event", side_effect=lambda **kw: sent.append(kw)):
        assert lifecycle_events.flush(restarted) == 1
        assert lifecycle_events.flush(restarted) == 0
    assert sent[0]["properties"]["outcome"] == "outcome_unknown"
    with restarted.state.admission.journal() as db:
        lifecycle_events.enqueue(db, "operation_completed", "attempt", user_id="synthetic", properties={"status": "failed"})
    with patch.object(lifecycle_events, "record_product_event") as record:
        lifecycle_events.flush(restarted)
    assert record.call_args.kwargs["event_id"] == sent[0]["event_id"]


def test_terminal_payload_excludes_content(tmp_path):
    app = SimpleNamespace(state=SimpleNamespace(admission=Admission(tmp_path)))
    with app.state.admission.journal() as db:
        with pytest.raises(ValueError):
            lifecycle_events.enqueue(db, "operation_completed", "attempt", user_id="synthetic", properties={"prompt": "SYNTHETIC_SECRET"})
    assert "SYNTHETIC_SECRET" not in (tmp_path / ".request-journal.sqlite3").read_bytes().decode(errors="ignore")


def test_unobserved_cost_is_unknown_not_zero():
    properties = lifecycle_events.stage_properties(StageState(cost_usd=0, estimated_cost_usd=1.25), "draw", "awaiting_review")
    assert properties["cost_status"] == "unknown"
    assert properties["cost_usd"] is None
    assert properties["estimated_cost_usd"] == 1.25
    assert "prompt" not in json.dumps(properties)


def test_draw_terminal_follows_all_artifacts_and_is_idempotent(tmp_path, monkeypatch):
    from novel_to_comic.state import create_initial_state, save_state, StageStatus
    state = create_initial_state("fixture", "fixture.txt")
    draw = state.stages["draw"]
    draw.status = StageStatus.RUNNING
    draw.run_id, draw.attempt_id = "run", "attempt"
    save_state(state, tmp_path)
    revisions = {1: (1,), 2: ()}
    target = SimpleNamespace(read_plan=lambda: SimpleNamespace(pages=[SimpleNamespace(page_number=1), SimpleNamespace(page_number=2)]),
                             provenance_revisions=lambda number: revisions[number])
    monkeypatch.setattr(page_operations, "TargetArtifacts", lambda directory: target)
    app = SimpleNamespace(state=SimpleNamespace(admission=Admission(tmp_path)))
    page_operations._sync_draw_progress(tmp_path, app)
    assert lifecycle_events.flush(app) == 0
    revisions[2] = (1,)
    page_operations._sync_draw_progress(tmp_path, app)
    page_operations._sync_draw_progress(tmp_path, app)
    with patch.object(lifecycle_events, "record_product_event") as record:
        assert lifecycle_events.flush(app) == 1
    assert record.call_args.kwargs["event_name"] == "stage_succeeded"
    assert record.call_args.kwargs["properties"]["stage"] == "draw"
    assert record.call_args.kwargs["properties"]["outcome"] == "awaiting_review"


def test_empty_plan_does_not_prove_draw_success(tmp_path, monkeypatch):
    target = SimpleNamespace(read_plan=lambda: SimpleNamespace(pages=[]))
    monkeypatch.setattr(page_operations, "TargetArtifacts", lambda directory: target)
    from novel_to_comic.state import create_initial_state, save_state
    save_state(create_initial_state("fixture", "fixture.txt"), tmp_path)
    with patch.object(lifecycle_events, "capture") as capture:
        page_operations._sync_draw_progress(tmp_path)
    capture.assert_not_called()


@pytest.mark.parametrize("status,phase,outcome", [("failed", None, "failed"), ("failed", "outcome_unknown", "outcome_unknown"), ("cancelled", None, "cancelled"), ("complete", None, "awaiting_review")])
def test_draw_rerun_waits_for_jobs_not_existing_artwork(tmp_path, monkeypatch, status, phase, outcome):
    from novel_to_comic.state import create_initial_state, save_state, StageStatus
    state = create_initial_state("fixture", "fixture.txt")
    draw = state.stages["draw"]
    draw.status = StageStatus.AWAITING_REVIEW
    draw.items_done = 1
    draw.attempt_id, draw.run_id = "attempt", "run"
    draw.telemetry_draw_rerun, draw.telemetry_draw_jobs = True, ["job"]
    save_state(state, tmp_path)
    target = SimpleNamespace(read_plan=lambda: SimpleNamespace(pages=[SimpleNamespace(page_number=1)]), provenance_revisions=lambda number: (1,))
    monkeypatch.setattr(page_operations, "TargetArtifacts", lambda directory: target)
    job = SimpleNamespace(status="running", phase=None)
    app = SimpleNamespace(state=SimpleNamespace(admission=Admission(tmp_path), generation_jobs={"job": job}))
    page_operations._sync_draw_progress(tmp_path, app)
    assert lifecycle_events.flush(app) == 0
    job.status, job.phase = status, phase
    page_operations._sync_draw_progress(tmp_path, app)
    with patch.object(lifecycle_events, "record_product_event") as record:
        assert lifecycle_events.flush(app) == 1
    assert record.call_args.kwargs["properties"]["outcome"] == outcome
    page_operations._sync_draw_progress(tmp_path, app)
    assert lifecycle_events.flush(app) == 0


def test_stage_has_one_terminal_identity_even_after_crash_reconciliation(tmp_path):
    app = SimpleNamespace(state=SimpleNamespace(admission=Admission(tmp_path)))
    lifecycle_events.capture(app, "stage_succeeded", "attempt", user_id="synthetic", properties={"stage": "extract", "outcome": "succeeded"})
    lifecycle_events.capture(app, "stage_failed", "attempt", user_id="synthetic", properties={"stage": "extract", "outcome": "outcome_unknown"})
    with patch.object(lifecycle_events, "record_product_event") as record:
        assert lifecycle_events.flush(app) == 1
    assert record.call_args.kwargs["event_name"] == "stage_succeeded"


def test_draw_cohort_reads_terminal_jobs_beyond_in_memory_history(tmp_path, monkeypatch):
    from novel_to_comic.state import create_initial_state, load_state, save_state, StageStatus
    state = create_initial_state("book", "source.txt")
    draw = state.stages["draw"]
    draw.status = StageStatus.AWAITING_REVIEW
    draw.items_done = 1
    draw.attempt_id = "large-draw"
    draw.telemetry_user_id, draw.telemetry_project_id = "owner", "book"
    draw.telemetry_draw_rerun = True
    draw.telemetry_draw_jobs = [f"draw-{n}" for n in range(450)]
    save_state(state, tmp_path)
    app = SimpleNamespace(state=SimpleNamespace(admission=Admission(tmp_path), generation_jobs={}))
    with app.state.admission.journal() as db:
        for identity in draw.telemetry_draw_jobs:
            db.execute("INSERT INTO jobs VALUES(?,?,?)", (identity, "owner:book", json.dumps({
                "id": identity, "status": "complete", "phase": "complete"})))
    target = SimpleNamespace(read_plan=lambda: SimpleNamespace(pages=[SimpleNamespace(page_number=1)]),
                             provenance_revisions=lambda number: (1,))
    monkeypatch.setattr(page_operations, "TargetArtifacts", lambda directory: target)
    page_operations._sync_draw_progress(tmp_path, app)
    assert load_state(tmp_path).stages["draw"].telemetry_terminal_outcome == "awaiting_review"
    with patch.object(lifecycle_events, "record_product_event") as record:
        assert lifecycle_events.flush(app) == 1
    assert record.call_args.kwargs["event_name"] == "stage_succeeded"


def test_serialized_new_contract_survives_privacy_boundary_without_content():
    from novel_to_comic.server.analytics_delivery import wire_event
    identity = "11111111-1111-4111-8111-111111111111"
    event = wire_event({"id": identity, "event_name": "stage_succeeded", "user_id": identity,
                       "project_id": identity, "source": "server", "occurred_at": "2026-09-30T00:00:00Z",
                       "properties_json": {"stage": "draw", "run_id": identity, "attempt_id": identity,
                                           "cost_status": "unknown", "cost_usd": None, "unknown_usage_count": 1,
                                           "prompt": "SYNTHETIC_SECRET", "title": "SYNTHETIC_SECRET"}})
    assert event["properties"]["run_id"] == identity
    assert event["properties"]["attempt_id"] == identity
    assert event["properties"]["cost_status"] == "unknown"
    assert "cost_usd" not in event["properties"]  # Unknown is absent on the wire, never zero.
    assert event["properties"]["unknown_usage_count"] == 1
    assert "SYNTHETIC_SECRET" not in json.dumps(event)


def test_acceptance_requires_successful_draw_approval(tmp_path, monkeypatch):
    import asyncio
    from fastapi import HTTPException
    from novel_to_comic.config import Config
    from novel_to_comic.server.routers import pipeline
    from novel_to_comic.state import create_initial_state, save_state, StageStatus
    state = create_initial_state("fixture", "fixture.txt")
    state.stages["draw"].status = StageStatus.AWAITING_REVIEW
    state.stages["draw"].attempt_id = "attempt"
    save_state(state, tmp_path)
    rendered = []
    target = SimpleNamespace(read_plan=lambda: SimpleNamespace(pages=[SimpleNamespace(page_number=1)]), provenance_revisions=lambda number: rendered)
    monkeypatch.setattr(pipeline, "TargetArtifacts", lambda directory: target)
    monkeypatch.setattr("novel_to_comic.page_review.summarize_page_issues", lambda target: SimpleNamespace(blocking_issue_ids=[]))
    monkeypatch.setattr(pipeline, "capture_server_event", lambda *args, **kwargs: None)
    app = SimpleNamespace(state=SimpleNamespace(admission=Admission(tmp_path)))
    request = SimpleNamespace(app=app)
    kwargs = dict(stage="draw", project_id="fixture", request=request, project=(tmp_path, Config(), state), user_id="synthetic")
    with pytest.raises(HTTPException):
        asyncio.run(pipeline.approve(**kwargs))
    assert lifecycle_events.flush(app) == 0
    rendered.append(1)
    assert asyncio.run(pipeline.approve(**kwargs))["status"] == "approved"
    with patch.object(lifecycle_events, "record_product_event") as record:
        assert lifecycle_events.flush(app) == 1
    assert record.call_args.kwargs["event_name"] == "output_accepted"
    assert record.call_args.kwargs["properties"]["scope"] == "edition"
    with pytest.raises(HTTPException):
        asyncio.run(pipeline.approve(**kwargs))
    assert lifecycle_events.flush(app) == 0


@pytest.mark.parametrize("sources,expected", [(["request_estimate"], "estimated"), (["provider"], "reported"), (["provider", "request_estimate"], "estimated")])
def test_terminal_stage_cost_preserves_estimate_provenance(sources, expected):
    from novel_to_comic.state import StageState
    records = [{"provider": "fixture", "model": "image-sunburst", "operation": "image", "image_count": 1, "cost_usd": 0.1, "cost_source": source} for source in sources]
    properties = lifecycle_events.stage_properties(StageState(usage_log=records), "draw", "awaiting_review")
    assert properties["cost_status"] == expected
    assert properties["cost_source"] == ("provider_reported" if expected == "reported" else "pricing_estimate")
    assert properties["cost_usd"] == pytest.approx(0.1 * len(sources))
