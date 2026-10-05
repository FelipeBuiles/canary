from pathlib import Path
from unittest.mock import MagicMock

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from novel_to_comic.config import Config
from novel_to_comic.server import telemetry as t
from novel_to_comic.server.job_commands import command
from novel_to_comic.server.logging import request_log_middleware

REQUEST = "01234567-89ab-4cde-89ab-0123456789ab"
SESSION = "01234567-89ab-4cde-89ab-0123456789ac"
TRACE = "0123456789abcdef0123456789abcdef"
PARENT = "0123456789abcdef"


def test_browser_request_and_session_reach_the_durable_job(monkeypatch):
    provider = TracerProvider()
    exporter = InMemorySpanExporter()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    monkeypatch.setattr(t, "_provider", provider)
    monkeypatch.setattr(t, "_client", None)
    app = FastAPI()
    app.middleware("http")(request_log_middleware)
    commands = []

    @app.post("/api/projects/{project_id}/run")
    async def run(project_id: str, request: Request):
        # Simulate the identity supplied by the validated auth dependency.
        request.state.user_id = REQUEST
        commands.append(command("pipeline", Path("/tmp/project"), Config()))
        return {"ok": True}

    with TestClient(app) as client:
        response = client.post("/api/projects/PRIVATE_ID/run", headers={
            "X-Request-ID": REQUEST, "X-Canary-Session-ID": SESSION,
            "traceparent": f"00-{TRACE}-{PARENT}-01", "baggage": "manuscript=PRIVATE_CONTENT",
        })
    assert response.headers["X-Request-ID"] == REQUEST
    assert response.headers["X-Trace-ID"] == TRACE
    [spec] = commands
    assert spec.request_id == REQUEST and spec.browser_session_id == SESSION
    assert spec.traceparent.split("-")[1] == TRACE
    with t.operation_span("job.execute", carrier={"traceparent": spec.traceparent},
                          request_id=spec.request_id, browser_session_id=spec.browser_session_id):
        assert t.context_fields()["trace_id"] == TRACE
        assert t.context_fields()["browser_session_id"] == SESSION
    request, job = exporter.get_finished_spans()
    assert request.parent.span_id == int(PARENT, 16)
    assert request.attributes["posthogDistinctId"] == REQUEST
    assert job.parent.span_id == request.context.span_id
    assert "PRIVATE" not in repr([dict(span.attributes) for span in exporter.get_finished_spans()])
    provider.shutdown()


def test_untrusted_header_values_are_not_exported(monkeypatch):
    monkeypatch.setattr(t, "_provider", None)
    monkeypatch.setattr(t, "_client", None)
    app = FastAPI()
    app.middleware("http")(request_log_middleware)

    @app.get("/api/check")
    async def check():
        return t.context_fields()

    with TestClient(app) as client:
        response = client.get("/api/check", headers={"X-Request-ID": "PRIVATE",
            "X-Canary-Session-ID": "PRIVATE", "traceparent": "PRIVATE"})
    assert "PRIVATE" not in repr(response.json())
    assert response.json()["request_id"] != "PRIVATE"
    assert "browser_session_id" not in response.json()


def test_safe_exception_templates_preserve_replay_correlation(monkeypatch):
    sdk = MagicMock()
    monkeypatch.setattr(t, "_client", sdk)
    with t.observation_context(browser_session_id=SESSION, request_id=REQUEST):
        t.capture_exception(TimeoutError("PRIVATE_PROVIDER_CONTENT"))
    properties = sdk.capture_exception.call_args.kwargs["properties"]
    wire = t._before_send({"event": "$exception", "properties": {
        **properties, "$exception_list": [{"type": "TimeoutError", "value": "PRIVATE_PROVIDER_CONTENT"}],
    }})
    assert wire["properties"]["$session_id"] == SESSION
    assert wire["properties"]["$exception_list"][0]["value"] == "Operation timed out"
    assert "PRIVATE_PROVIDER_CONTENT" not in repr(wire)
