import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from novel_to_comic.config import Config
from novel_to_comic.server import metrics
from novel_to_comic.server.app import create_app
from novel_to_comic.server.routers import pipeline
from novel_to_comic.state import StageStatus, create_initial_state
from novel_to_comic.server.product_events import (
    _clean_properties,
    capture_server_event,
    record_product_event,
)


def test_server_product_event_rejects_unknown_event_and_properties():
    with pytest.raises(ValueError, match="Unknown server product event"):
        _clean_properties("button_clicked", {}, source="server")

    with pytest.raises(ValueError, match="Unsupported properties"):
        _clean_properties(
            "project_created",
            {"source": "upload", "project_name": "private title"},
            source="server",
        )


def test_server_product_event_persists_only_bounded_scalar_properties():
    table = MagicMock()
    db = MagicMock()
    db.table.return_value = table

    with patch(
        "novel_to_comic.server.product_events.get_db", return_value=db
    ):
        record_product_event(
            "project_created",
            user_id="00000000-0000-0000-0000-000000000001",
            project_id="00000000-0000-0000-0000-000000000002",
            properties={"source": "upload", "file_type": "x" * 500},
        )

    payload = table.insert.call_args.args[0]
    assert payload["event_name"] == "project_created"
    assert payload["source"] == "server"
    assert payload["properties_json"] == {
        "source": "upload",
        "file_type": "x" * 200,
    }
    table.insert.return_value.execute.assert_called_once_with()


def test_server_product_event_failure_never_escapes_customer_action():
    with patch(
        "novel_to_comic.server.product_events.record_product_event",
        side_effect=RuntimeError("database unavailable"),
    ):
        capture_server_event("stage_started", user_id="user", properties={"stage": "draw"})


def test_prometheus_metrics_are_aggregate_and_low_cardinality():
    metrics.reset_metrics_for_tests()
    metrics.increment(
        "canary_http_requests_total",
        method="POST",
        route="/api/projects/{project_id}/run",
        status_class="2xx",
    )
    metrics.observe(
        "canary_http_request_duration_seconds",
        1.25,
        method="POST",
        route="/api/projects/{project_id}/run",
    )
    metrics.record_ai_call(
        provider="gemini",
        model="image-gpt-2",
        operation="image",
        status="succeeded",
        stage="draw",
        cost_usd=0.125,
        input_tokens=100,
        output_tokens=80,
        reasoning_tokens=50,
    )
    metrics.record_structured_attempt(feature="plan.scene_layout", retry=True)
    app = SimpleNamespace(
        state=SimpleNamespace(
            generation_jobs={
                "job-1": SimpleNamespace(status="queued"),
                "job-2": SimpleNamespace(status="running"),
            },
            generation_queue=SimpleNamespace(qsize=lambda: 3),
        )
    )

    rendered = metrics.render_metrics(app)

    assert 'route="/api/projects/{project_id}/run"' in rendered
    assert 'canary_generation_jobs{status="queued"} 1' in rendered
    assert "canary_generation_queue_items 3" in rendered
    assert "canary_ai_provider_cost_usd_total" in rendered
    assert 'canary_ai_reasoning_tokens_total{provider="gemini",model="image-gpt-2",stage="draw"} 50' in rendered
    assert 'canary_ai_output_tokens_total{provider="gemini",model="image-gpt-2",stage="draw"} 80' in rendered
    assert 'canary_structured_call_attempts_total{feature="plan.scene_layout",attempt="retry"} 1' in rendered
    assert "user_id" not in rendered
    assert "project_id=\"" not in rendered


def test_operations_dashboard_surfaces_plan_cost_regression_signals():
    dashboard = (Path(__file__).parents[2] / "ops" / "grafana" / "canary-application.json").read_text()

    assert "canary_ai_reasoning_tokens_total" in dashboard
    assert "canary_ai_output_tokens_total" in dashboard
    assert "canary_structured_call_attempts_total" in dashboard
    assert "canary_stage_cost_ratio" in dashboard


def test_schema_contains_observability_tables_and_operator_views():
    schema = (Path(__file__).parents[2] / "docs" / "supabase-schema.sql").read_text()

    assert "create table if not exists public.product_events" in schema
    assert "create or replace view public.ops_usage_reconciliation" in schema
    assert "create or replace view public.ops_unit_economics_daily" in schema
    assert "revoke all on public.product_events from public, anon, authenticated" in schema


def test_metrics_scrape_bypasses_host_check_without_weakening_api(tmp_path, monkeypatch):
    monkeypatch.setenv("CANARY_ALLOWED_HOSTS", "app.scenewright.ink")
    client = TestClient(create_app(tmp_path, dev=True))

    metrics_response = client.get("/metrics", headers={"host": "fly-internal"})
    health_response = client.get("/api/health", headers={"host": "fly-internal"})

    assert metrics_response.status_code == 200
    assert "canary_generation_queue_items" in metrics_response.text
    assert health_response.status_code == 400


def test_stage_that_handles_its_exception_is_recorded_as_failed(tmp_path):
    state = create_initial_state("demo", "novel.txt")
    captured: list[tuple[str, dict]] = []

    async def fake_run_credited_stage(**_kwargs):
        state.stages["extract"].status = StageStatus.FAILED
        state.stages["extract"].error_code = "provider_timeout"

    metrics.reset_metrics_for_tests()
    with (
        patch.object(pipeline, "run_credited_stage", new=fake_run_credited_stage),
        patch.object(
            pipeline,
            "capture_server_event",
            side_effect=lambda name, **kwargs: captured.append(
                (name, kwargs.get("properties") or {})
            ),
        ),
    ):
        asyncio.run(
            pipeline._run_stage_with_credits(
                "extract",
                Config(),
                tmp_path,
                state,
                asyncio.Queue(),
                "user-1",
                "project-1",
                SimpleNamespace(),
                "user-1:project-1",
            )
        )

    assert [name for name, _properties in captured] == [
        "stage_started",
        "stage_failed",
    ]
    # A failed stage must still produce a recordable event: the properties the
    # pipeline emits have to satisfy the server allowlist.
    for name, properties in captured:
        _clean_properties(name, properties, source="server")
