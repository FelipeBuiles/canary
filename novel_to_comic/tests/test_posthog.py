import asyncio
import json
from unittest.mock import MagicMock

import httpx
import pytest
from novel_to_comic.server import telemetry as t
from novel_to_comic.server import analytics_delivery as delivery
from novel_to_comic.ai.context import ai_request_context
from novel_to_comic.ai import client
from novel_to_comic.usage import UsageRecord

USER = "b039877c-3d9b-46ec-988f-183972a14945"

@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    monkeypatch.setattr(t, "_client", None)
    monkeypatch.setattr(t, "_provider", None)
    monkeypatch.setattr(t, "_log_provider", None)
    monkeypatch.setattr(t, "_log_handler", None)
    monkeypatch.delenv("POSTHOG_PROJECT_TOKEN", raising=False)


def test_disabled_without_configuration():
    assert not t.configure_telemetry()
    t.capture("test")
    t.capture_exception(ValueError("private"))


def test_bootstrap_failure_does_not_prevent_application(monkeypatch):
    monkeypatch.setenv("POSTHOG_PROJECT_TOKEN", "phc_test")
    monkeypatch.setenv("POSTHOG_HOST", "https://us.i.posthog.com")
    monkeypatch.setattr("posthog.Posthog", MagicMock(side_effect=ValueError("invalid")))
    assert not t.configure_telemetry()


def test_error_scrubber_drops_payloads_but_keeps_locations():
    event = {"event": "$exception", "distinct_id": USER, "request": {"body": "secret"}, "properties": {
        "prompt": "secret", "$current_url": "https://private/secret", "error_message": "secret",
        "request_id": USER, "$exception_list": [{"type": "ValueError", "value": "secret", "stacktrace": {"frames": [
            {"filename": "/private/project/worker.py", "function": "generate", "lineno": 17,
             "context_line": "secret", "vars": {"token": "secret"}}
        ]}}]}}
    clean = t._before_send(event)
    assert "secret" not in json.dumps(clean)
    frame = clean["properties"]["$exception_list"][0]["stacktrace"]["frames"][0]
    assert frame == {"filename": "worker.py", "function": "generate", "lineno": 17}
    assert clean["properties"]["request_id"] == USER
    assert t._before_send({"event": "$exception", "properties": {"$exception_list": [None]}}) is None


def test_context_isolated_between_concurrent_jobs():
    async def run(value):
        with t.observation_context(operation_id=value):
            await asyncio.sleep(0)
            assert t.context_fields()["operation_id"] == value
            assert await asyncio.to_thread(lambda: t.context_fields()["operation_id"]) == value
    async def check():
        await asyncio.gather(run("one"), run("two"))
        assert t.context_fields() == {}
    asyncio.run(check())


@pytest.mark.parametrize("cost,source,expected", [(0.12,"provider_reported","reported"),(None,"unknown_provider_usage","unknown"),(0.1,"request_estimate","estimated")])
def test_manual_image_event_preserves_cost_semantics(monkeypatch, cost, source, expected):
    sdk = MagicMock()
    monkeypatch.setattr(t, "_client", sdk)
    usage = UsageRecord(provider="litellm", model="image-pro", operation="image", image_count=1, cost_usd=cost)
    with ai_request_context(user_id=USER, project_id=USER, project_name="private title", workspace_id="/private/manuscript"):
        t.observe_generation(event_id=USER, feature="draw", operation="image", model_alias="image-pro",
            provider_model="provider-image", status="failed" if cost is None else "succeeded", usage=usage,
            cost_usd=cost, cost_source=source, latency_ms=1250, error=ValueError("private prose"))
    args, kwargs = sdk.capture.call_args
    assert args == ("$ai_generation",)
    assert kwargs["distinct_id"] == USER
    p = kwargs["properties"]
    assert p["cost_status"] == expected
    assert p["image_count"] == 1
    assert p["$ai_latency"] == 1.25
    if cost is None:
        assert "$ai_total_cost_usd" not in p
        assert "$ai_cost_passthrough" not in p
        assert "cost_usd" not in p
    else:
        assert p["$ai_total_cost_usd"] == cost
        assert p["$ai_cost_passthrough"] is True
    assert "private" not in json.dumps(p)


def test_telemetry_failure_cannot_break_finalization(monkeypatch):
    db = MagicMock()
    monkeypatch.setattr("novel_to_comic.server.db.get_db", lambda: db)
    monkeypatch.setattr(client, "_settle_event_usage", MagicMock())
    monkeypatch.setattr(t, "observe_generation", MagicMock(side_effect=RuntimeError("export failed")))
    usage = UsageRecord(provider="litellm", model="image-pro", operation="image", image_count=1, cost_usd=0.1)
    client._finalize_event(event_id=USER, status="succeeded", feature="draw", model_alias="image-pro",
                           latency_ms=50, usage=usage, metadata={}, operation="image")
    client._settle_event_usage.assert_called_once()
    db.table.return_value.update.assert_called_once()


def test_delivery_retries_same_insert_id_after_ack_failure(monkeypatch):
    row = {"id": USER, "event_name": "project_created", "user_id": USER,
           "occurred_at": "2026-09-26T00:00:00Z", "source": "server",
           "properties_json": {"source": "upload", "prompt": "private"}}
    monkeypatch.setattr(delivery, "_pending", lambda: [row])
    ack = MagicMock(side_effect=[RuntimeError("database down"), None])
    monkeypatch.setattr(delivery, "_ack", ack)
    monkeypatch.setenv("POSTHOG_HOST", "https://us.i.posthog.com")
    monkeypatch.setenv("POSTHOG_PROJECT_TOKEN", "test")
    batches = []
    def handler(request):
        batches.append(json.loads(request.content))
        return httpx.Response(200, json={"status": 1})
    async def check():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            with pytest.raises(RuntimeError):
                await delivery.deliver_once(http)
            assert await delivery.deliver_once(http) == 1
    asyncio.run(check())
    assert batches[0] == batches[1]
    assert batches[0]["batch"][0]["properties"]["$insert_id"] == USER
    assert batches[0]["batch"][0]["properties"]["source"] == "upload"
    assert batches[0]["batch"][0]["properties"]["event_origin"] == "server"
    assert "private" not in json.dumps(batches)


def test_exception_wire_labels_match_other_events(monkeypatch):
    monkeypatch.setenv("CANARY_ENV", "development")
    monkeypatch.setenv("CANARY_VERSION", "abc123-dirty")
    sdk = MagicMock()
    monkeypatch.setattr(t, "_client", sdk)
    with t.observation_context(operation_id=USER):
        t.capture_exception(ValueError("private"), user_id=USER)
    props = sdk.capture_exception.call_args.kwargs["properties"]
    wire = t._before_send({"event": "$exception", "properties": props})["properties"]
    assert wire["environment"] == "development"
    assert wire["release"] == wire["$release_id"] == "abc123-dirty"
    assert wire["schema_version"] == 1
    assert wire["operation_id"] == USER


def test_runtime_error_code_groups_exceptions_without_message(monkeypatch):
    from novel_to_comic.ai.codex_runtime import CodexRuntimeError
    sdk = MagicMock()
    monkeypatch.setattr(t, "_client", sdk)
    wires = []
    for code in ("runtime_capacity", "image_output_missing"):
        t.capture_exception(CodexRuntimeError(code, {"provider_error": {"message": "private"}}), user_id=USER)
        props = sdk.capture_exception.call_args.kwargs["properties"]
        wires.append(t._before_send({"event": "$exception", "properties": props})["properties"])
    assert [w["code"] for w in wires] == ["runtime_capacity", "image_output_missing"]
    assert [w["$exception_fingerprint"] for w in wires] == [
        "CodexRuntimeError:runtime_capacity", "CodexRuntimeError:image_output_missing"]
    assert "private" not in json.dumps(wires)
    t.capture_exception(ValueError("private"), user_id=USER)
    assert "$exception_fingerprint" not in sdk.capture_exception.call_args.kwargs["properties"]


def test_delayed_delivery_preserves_capture_release(monkeypatch):
    monkeypatch.setenv("CANARY_VERSION", "new-release")
    row = {"id": USER, "event_name": "station_viewed", "user_id": USER,
           "occurred_at": "2026-09-26T00:00:00Z", "source": "web",
           "properties_json": {"station": "pages", "environment": "production", "release": "old-release"}}
    props = delivery.wire_event(row)["properties"]
    assert props["release"] == props["$release_id"] == "old-release"
    assert props["environment"] == "production"
    assert props["event_origin"] == "web"
    assert "source" not in props


def test_otlp_logs_receive_only_selected_safe_fields(monkeypatch):
    provider = MagicMock()
    monkeypatch.setattr(t, "_log_provider", provider)
    import logging
    record = logging.LogRecord("canary.observations", logging.ERROR, "", 1, "job.failed", (), None)
    record.telemetry = {"operation_id": USER, "prompt": "private"}
    t.SafeLogHandler().emit(record)
    emitted = provider.get_logger.return_value.emit.call_args.args[0]
    assert emitted.body == "job.failed"
    assert emitted.attributes == {"operation_id": USER}


def test_queue_context_serializes_without_changing_arguments():
    from novel_to_comic.server.job_commands import JobCommand
    spec = JobCommand(operation="page_draw", project_dir="/tmp/project", config={},
        traceparent="00-0123456789abcdef0123456789abcdef-0123456789abcdef-01", request_id=USER)
    assert JobCommand.model_validate_json(spec.model_dump_json()) == spec
    assert spec.arguments == {}


def test_claude_cache_breakdown_survives_wire_scrubber(monkeypatch):
    from types import SimpleNamespace
    route = SimpleNamespace(runtime="claude", reasoning_model="claude-opus-5-5", funding="claude_subscription")
    usage = client._codex_text_usage(USER, "claude-dev/text/claude-opus-5-5", route, {
        "usage": {"input_tokens": 100, "cache_read_input_tokens": 800,
                  "cache_creation_input_tokens": 50, "output_tokens": 20}})
    assert usage.input_tokens == 950
    sdk = MagicMock()
    monkeypatch.setattr(t, "_client", sdk)
    t.observe_generation(event_id=USER, feature="plan.detail", operation="text",
        model_alias=usage.model, provider_model=usage.provider_model, status="succeeded",
        usage=usage, cost_usd=None, cost_source="claude_subscription", latency_ms=100)
    properties = t._before_send({"event": "$ai_generation", "properties": sdk.capture.call_args.kwargs["properties"]})["properties"]
    assert properties["$ai_input_tokens"] == 950
    assert properties["$ai_cache_read_input_tokens"] == 800
    assert properties["$ai_cache_creation_input_tokens"] == 50
    assert properties["$ai_cache_reporting_exclusive"] is False
    assert properties["cost_status"] == "unknown"
    assert "$ai_total_cost_usd" not in properties


def test_failed_call_keeps_funding_and_provider_without_usage(monkeypatch):
    db = MagicMock()
    monkeypatch.setattr("novel_to_comic.server.db.get_db", lambda: db)
    monkeypatch.setattr("novel_to_comic.server.credits.is_ambiguous_job", lambda _: True)
    sdk = MagicMock()
    monkeypatch.setattr(t, "_client", sdk)
    client._finalize_event(event_id=USER, status="failed", feature="plan.book",
        model_alias="claude-opus-5-5", latency_ms=100, usage=None, metadata={}, operation="text")
    properties = sdk.capture.call_args.kwargs["properties"]
    assert properties["funding"] == "api"
    assert properties["provider"] == properties["$ai_provider"] == "anthropic"
    assert properties["cost_status"] == "unknown"
    assert "$ai_input_tokens" not in properties
    assert "$ai_total_cost_usd" not in properties


def test_person_properties_cross_the_wire_only_when_allowlisted():
    row = {"id": USER, "event_name": "account_created", "user_id": USER,
           "occurred_at": "2026-09-26T00:00:00Z", "source": "server",
           "properties_json": {"acquisition_source": "reddit", "$set_once": {
               "signed_up_at": "2026-09-26T00:00:00+00:00", "acquisition_source": "reddit",
               "email": "private@example.com", "referring_domain": "not a token"}}}
    props = delivery.wire_event(row)["properties"]
    assert props["acquisition_source"] == "reddit"
    assert props["$set_once"] == {"signed_up_at": "2026-09-26T00:00:00+00:00", "acquisition_source": "reddit"}
    assert "private" not in json.dumps(props)
    wire = t._before_send({"event": "$set", "properties": {"$set": {"$internal_or_test_user": True, "name": "x"}}})
    assert wire["properties"]["$set"] == {"$internal_or_test_user": True}
