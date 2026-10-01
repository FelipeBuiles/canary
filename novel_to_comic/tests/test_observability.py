import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from novel_to_comic.config import Config
from novel_to_comic.server import metrics
from tests.queue_fixtures import create_app
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


def test_server_product_event_persists_only_bounded_scalar_properties(monkeypatch):
    monkeypatch.setenv("CANARY_ENV", "test")
    monkeypatch.setenv("CANARY_VERSION", "test-release")
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

    payload = (table.upsert.call_args or table.insert.call_args).args[0]
    assert payload["event_name"] == "project_created"
    assert payload["source"] == "server"
    assert payload["properties_json"] == {
        "source": "upload",
        "file_type": "x" * 200,
        "environment": "test",
        "release": "test-release",
        "schema_version": 1,
    }
    table.insert.return_value.execute.assert_called_once_with()


def test_server_product_event_failure_never_escapes_customer_action():
    with patch(
        "novel_to_comic.server.product_events.record_product_event",
        side_effect=RuntimeError("database unavailable"),
    ):
        capture_server_event("stage_started", user_id="user", properties={"stage": "draw"})


@pytest.mark.parametrize(
    ("stage", "status", "expected_job_id"),
    [
        ("draw", StageStatus.COMPLETE, None),
        ("extract", StageStatus.AWAITING_REVIEW, "00000000-0000-0000-0000-000000000003"),
    ],
)
def test_stage_success_is_accepted_with_nullable_uuid_job_id(
    tmp_path, stage, status, expected_job_id
):
    state = create_initial_state("demo", "novel.txt")
    accepted = []
    table = MagicMock()
    db = MagicMock()
    db.table.return_value = table

    def accept_event():
        payload = (table.upsert.call_args or table.insert.call_args).args[0]
        # Match the database's nullable UUID contract, including capture's
        # best-effort behavior when an invalid identity rejects the write.
        if payload["job_id"] is not None:
            UUID(payload["job_id"])
        accepted.append(payload)

    table.insert.return_value.execute.side_effect = accept_event
    table.upsert.return_value.execute.side_effect = accept_event

    async def finish_stage(*_args, **_kwargs):
        state.stages[stage].status = status

    async def run_credited_stage(**kwargs):
        await kwargs["run"]()
        return "00000000-0000-0000-0000-000000000003"

    with (
        patch.object(pipeline, "_run_stage", new=finish_stage),
        patch.object(pipeline, "run_credited_stage", new=run_credited_stage),
        patch("novel_to_comic.server.product_events.get_db", return_value=db),
    ):
        asyncio.run(
            pipeline._run_stage_with_credits(
                stage,
                Config(),
                tmp_path,
                state,
                asyncio.Queue(),
                "00000000-0000-0000-0000-000000000001",
                "00000000-0000-0000-0000-000000000002",
            )
        )

    assert [event["event_name"] for event in accepted] == [
        "stage_started", "stage_dispatched" if stage == "draw" else "stage_succeeded"
    ]
    assert accepted[-1]["job_id"] == expected_job_id


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

    async def fake_run_credited_stage(**kwargs):
        await kwargs["run"]()

    async def fail_stage(*_args, **_kwargs):
        state.stages["extract"].status = StageStatus.FAILED
        state.stages["extract"].error_code = "provider_timeout"

    metrics.reset_metrics_for_tests()
    with (
        patch.object(pipeline, "run_credited_stage", new=fake_run_credited_stage),
        patch.object(pipeline, "_run_stage", new=fail_stage),
        patch.object(
            pipeline,
            "capture_lifecycle",
            side_effect=lambda app, name, identity, **kwargs: captured.append(
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


def _account_db(metadata, created_at="2026-09-28T00:01:02.345+00:00"):
    table = MagicMock()
    db = MagicMock()
    db.table.return_value = table
    user = SimpleNamespace(created_at=created_at, user_metadata=metadata)
    db.auth.admin.get_user_by_id.return_value = SimpleNamespace(user=user)
    return db, table


def test_account_observed_is_idempotent_and_not_backdated(monkeypatch):
    from novel_to_comic.server import product_events

    account = "00000000-0000-0000-0000-0000000000a1"
    monkeypatch.setattr(product_events, "_accounts_recorded", set())
    monkeypatch.setenv("CANARY_INTERNAL_ACCOUNT_IDS", f" {account.upper()} ,other")
    db, table = _account_db({"studio_name": "Private Studio", "acquisition": {
        "source": "Reddit", "medium": "social", "campaign": "launch week!", "referring_domain": "reddit.com",
    }})
    capture = MagicMock()
    with patch.object(product_events, "get_db", return_value=db), \
         patch("novel_to_comic.server.telemetry.capture", capture):
        product_events.record_account_observed(account)
        product_events.record_account_observed(account)

    db.auth.admin.get_user_by_id.assert_called_once_with(account)
    payload = table.upsert.call_args.args[0]
    assert table.upsert.call_args.kwargs == {"on_conflict": "id", "ignore_duplicates": True}
    assert payload["id"] == str(UUID(payload["id"]))
    assert payload["event_name"] == "account_observed"
    assert "occurred_at" not in payload
    props = payload["properties_json"]
    # Invalid campaign tokens are dropped rather than truncated or escaped.
    assert {k: props[k] for k in ("acquisition_source", "acquisition_medium", "referring_domain")} == {
        "acquisition_source": "reddit", "acquisition_medium": "social", "referring_domain": "reddit.com"}
    assert "acquisition_campaign" not in props
    assert props["$set_once"]["signed_up_at"] == "2026-09-28T00:01:02.345+00:00"
    assert "Private Studio" not in str(payload)
    capture.assert_called_once_with("$set", user_id=account,
                                    properties={"$set": {"$internal_or_test_user": True}})


def test_account_created_labels_book_referrals_and_unknown_sources(monkeypatch):
    from novel_to_comic.server import product_events

    assert product_events._acquisition({"referred_by_book": "a" * 32}) == {
        "referred_by_book": True, "acquisition_source": "book_referral"}
    assert product_events._acquisition({}) == {"acquisition_source": "unknown"}
    assert product_events._acquisition({"acquisition": {}}) == {"acquisition_source": "direct"}


def test_account_endpoint_never_fails_app_load(tmp_path):
    from novel_to_comic.server.auth import get_current_user
    from novel_to_comic.server.routers import events

    app = create_app(tmp_path, dev=True)
    app.dependency_overrides[get_current_user] = lambda: "00000000-0000-0000-0000-0000000000a2"
    with patch.object(events, "record_account_observed", side_effect=RuntimeError("auth admin down")):
        response = TestClient(app).post("/api/events/account")
    assert response.status_code == 202
