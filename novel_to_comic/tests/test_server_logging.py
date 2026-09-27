from types import SimpleNamespace
import io
import logging
import sys
import asyncio

from fastapi import Response
import pytest

from rich.console import Console

from novel_to_comic.server.logging import TerminalFilter, TerminalHandler, _should_log_request


def _request(path: str, method: str = "GET"):
    return SimpleNamespace(method=method, url=SimpleNamespace(path=path))


def test_non_static_failures_are_logged():
    request = _request("/api/projects/demo/images")

    assert _should_log_request(request, 404, 12)


def test_missing_draw_file_failures_are_suppressed():
    request = _request("/api/projects/demo/files/draw/scene_001/panel_001.png")

    assert not _should_log_request(request, 404, 12)


def test_not_yet_generated_style_sample_failures_are_suppressed():
    sample = _request("/api/projects/demo/files/samples/style_1.png")
    metadata = _request("/api/projects/demo/files/samples/style_1.png.meta.json")

    assert not _should_log_request(sample, 404, 12)
    assert not _should_log_request(metadata, 404, 12)


def test_no_active_event_stream_is_suppressed_but_server_failure_is_logged():
    request = _request("/api/projects/demo/events")

    assert not _should_log_request(request, 404, 12)
    assert _should_log_request(request, 500, 12)


def test_static_server_errors_are_not_hidden():
    assert _should_log_request(_request("/api/projects/demo/files/draw/page.png"), 500, 12)


def test_terminal_filter_removes_duplicate_success_but_preserves_failures(monkeypatch):
    monkeypatch.setattr(logging.getLogger(), "level", logging.INFO)
    output_filter = TerminalFilter()
    def record(name, level, message):
        return logging.LogRecord(name, level, "", 0, message, (), None)
    assert not output_filter.filter(record("canary.observations", logging.INFO, "ai.completed"))
    assert not output_filter.filter(record("canary.observations", logging.ERROR, "http.failed"))
    assert not output_filter.filter(record("procrastinate.worker", logging.INFO, "Success"))
    assert output_filter.filter(record("procrastinate.worker", logging.ERROR, "Worker failed"))
    assert output_filter.filter(record("canary.observations", logging.ERROR, "ai.completed"))
    assert output_filter.filter(record("canary.jobs", logging.INFO, "Job complete"))


def test_terminal_error_summary_keeps_context_without_mutating_export_record(monkeypatch):
    monkeypatch.delenv("CANARY_LOG_TRACEBACKS", raising=False)
    stream = io.StringIO()
    handler = TerminalHandler(console=Console(file=stream, width=140), markup=True,
                              rich_tracebacks=True, show_path=False, show_time=False)
    try:
        raise ValueError("[missing] session limit\nlong provider payload")
    except ValueError:
        record = logging.LogRecord("canary.observations", logging.ERROR, __file__, 1,
                                   "ai.completed", (), sys.exc_info())
    record.telemetry = {"feature": "draw.page_ocr", "page_number": 1, "status": "failed", "prompt": "secret"}
    handler.handle(record)
    text = stream.getvalue()
    assert "draw.page_ocr" in text
    assert "page_number=1" in text
    assert "ValueError: [missing] session limit" in text
    assert "Traceback" not in text
    assert "long provider payload" not in text
    assert "secret" not in text
    assert record.exc_info is not None
    assert record.msg == "ai.completed"


def test_terminal_tracebacks_are_opt_in(monkeypatch):
    monkeypatch.setenv("CANARY_LOG_TRACEBACKS", "true")
    stream = io.StringIO()
    handler = TerminalHandler(console=Console(file=stream, width=100), rich_tracebacks=True,
                              show_path=False, show_time=False)
    try:
        raise RuntimeError("example failure")
    except RuntimeError:
        record = logging.LogRecord("canary.test", logging.ERROR, __file__, 1,
                                   "Failed", (), sys.exc_info())
    handler.handle(record)
    assert "Traceback" in stream.getvalue()


def test_usage_insert_failure_does_not_dump_failed_row(monkeypatch, caplog):
    from novel_to_comic.ai import client
    class DatabaseError(Exception):
        code = "23514"
    def unavailable():
        raise DatabaseError("Failing row contains private manuscript and request payload")
    monkeypatch.setattr("novel_to_comic.server.db.get_db", unavailable)
    with caplog.at_level(logging.WARNING):
        client._insert_event(event_id="event-123", model_alias="test", feature="draw.page_ocr",
                             operation="text", params_json={}, request_summary_json={}, metadata_json={})
    assert "event-123" in caplog.text
    assert "23514" in caplog.text
    assert "private manuscript" not in caplog.text


def test_successful_requests_keep_telemetry_without_info_console_noise(monkeypatch, caplog):
    from novel_to_comic.server import logging as server_logging
    from novel_to_comic.server import telemetry
    monkeypatch.setenv("CANARY_ENV", "development")
    observations = []
    monkeypatch.setattr(telemetry, "log_event", lambda name, **fields: observations.append((name, fields)))
    request = _request("/api/projects/demo/run", "POST")
    request.state = SimpleNamespace()
    request.scope = {"route": SimpleNamespace(path="/api/projects/{project_id}/run")}
    async def success(_):
        return Response(status_code=200)
    with caplog.at_level(logging.INFO):
        asyncio.run(server_logging._request_log_middleware(request, success))
    assert observations[0][0] == "http.completed"
    assert "API" not in caplog.text
    async def failure(_):
        return Response(status_code=500)
    with caplog.at_level(logging.INFO):
        asyncio.run(server_logging._request_log_middleware(request, failure))
    assert any(record.levelno == logging.ERROR and "500" in record.getMessage() for record in caplog.records)


@pytest.mark.parametrize("invalid", [False, True])
def test_stage_artifact_reads_are_quiet_but_keep_recovery_response(tmp_path, monkeypatch, caplog, invalid):
    from fastapi import FastAPI, HTTPException
    from fastapi.testclient import TestClient
    from pydantic import BaseModel, ValidationError
    from novel_to_comic.server.app import create_app
    from novel_to_comic.server.logging import request_log_middleware
    from novel_to_comic.server.routers.pages import list_pages
    from novel_to_comic.target_artifacts import ArtifactInvalid, TargetArtifacts

    monkeypatch.setenv("CANARY_ENV", "development")
    handlers = create_app(tmp_path).exception_handlers
    app = FastAPI(exception_handlers=handlers)
    app.middleware("http")(request_log_middleware)
    if invalid:
        class Example(BaseModel):
            count: int
        try:
            Example(count="bad")
        except ValidationError as exc:
            error = ArtifactInvalid("comic_page", tmp_path / "page.json", exc)
        def rejected(_):
            raise error
        monkeypatch.setattr(TargetArtifacts, "read_plan", rejected)

    @app.get("/pages")
    def pages():
        return list_pages(project=(tmp_path, None, None))

    @app.get("/other")
    def other():
        raise HTTPException(409, "Unexpected conflict")

    with TestClient(app) as client, caplog.at_level(logging.WARNING):
        for _ in range(3):
            response = client.get("/pages")
            assert response.status_code == (409 if invalid else 404)
            assert "detail" in response.json()
            if invalid:
                assert "Rerun Plan" in response.json()["detail"]
        assert not caplog.records
        client.get("/other")
        assert any("409" in record.getMessage() for record in caplog.records)


def test_usage_funding_constraint_failure_identifies_migration_without_row(monkeypatch, caplog):
    from novel_to_comic.ai import client
    class DatabaseError(Exception):
        code = '23514'
        message = 'new row violates check constraint "ai_usage_events_funding_check"'
    def unavailable():
        raise DatabaseError('Failing row contains private manuscript')
    monkeypatch.setattr('novel_to_comic.server.db.get_db', unavailable)
    with caplog.at_level(logging.WARNING):
        client._insert_event(event_id='event', model_alias='test', feature='draw.page_ocr',
                             operation='text', params_json={}, request_summary_json={}, metadata_json={})
    assert '2026-09-25-claude-subscription-funding.sql' in caplog.text
    assert 'private manuscript' not in caplog.text
