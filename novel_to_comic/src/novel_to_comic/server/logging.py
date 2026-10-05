"""Logging helpers for the web server."""

from __future__ import annotations

import logging
import copy
import json
import os
import re
import time
import uuid
from collections.abc import Callable

from fastapi import Request, Response
from rich.console import Console
from rich.logging import RichHandler
from rich.markup import escape

from novel_to_comic.server.env import bool_env
from novel_to_comic.server.telemetry import configure_telemetry, metric_count, metric_histogram
from novel_to_comic.server.metrics import increment, observe


api_logger = logging.getLogger("canary.api")


class TerminalFilter(logging.Filter):
    """Reduce console noise without dropping records from telemetry exporters."""

    def filter(self, record: logging.LogRecord) -> bool:
        verbose = logging.getLogger().isEnabledFor(logging.DEBUG)
        if record.name == "canary.observations":
            if str(record.msg).startswith(("http.", "job.")):
                return False  # Already represented by readable local records.
            return verbose or record.levelno >= logging.WARNING
        if record.name.startswith("procrastinate"):
            return verbose or record.levelno >= logging.WARNING
        return True


class TerminalHandler(RichHandler):
    """Render summaries; opt into full Rich tracebacks for debugging."""

    def emit(self, record: logging.LogRecord) -> None:
        from .telemetry import safe_fields
        record = copy.copy(record)  # Exporters must receive the original record.
        message = record.getMessage()
        fields = safe_fields(getattr(record, "telemetry", {}))
        if record.name == "canary.observations" and message == "ai.completed":
            message = "AI failed" if fields.get("status") == "failed" else "AI completed"
        if fields:
            keys = ("feature", "operation", "stage", "page_number", "status",
                    "error_type", "model_alias", "latency_ms", "operation_id", "request_id")
            message += " " + " ".join(f"{key}={fields[key]}" for key in keys if key in fields)
        if not bool_env("CANARY_LOG_TRACEBACKS", default=False):
            if record.exc_info and record.exc_info[1]:
                error = record.exc_info[1]
                detail = str(error).splitlines()
                message += " — " + escape(f"{type(error).__name__}: {detail[0][:240] if detail else ''}")
            record.exc_info = None
            record.exc_text = None
            record.stack_info = None
        record.msg = message
        record.args = ()
        super().emit(record)


class JsonFormatter(logging.Formatter):
    def format(self, record):
        from .telemetry import context_fields, safe_fields
        payload = {"level": record.levelname, "logger": record.name,
                   "message": record.getMessage(), **context_fields(),
                   **safe_fields(getattr(record, "telemetry", {}))}
        if record.exc_info and record.exc_info[0]:
            payload["error_type"] = record.exc_info[0].__name__
        return json.dumps(payload, ensure_ascii=True)


def configure_logging() -> None:
    """Configure concise terminal logs for `pipeline serve`."""
    import sys

    level_name = os.environ.get("CANARY_LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    show_time = bool_env("CANARY_LOG_SHOW_TIME", default=False)

    # Suppress verbose traceback frames from third-party libraries and venv
    suppress_list = [
        "httpx",
        "asyncio",
        "fastapi",
        "uvicorn",
        "starlette",
        "anyio",
        "click",
        "jinja2",
        "sqlalchemy",
        "pydantic",
        "http",
        "litellm",
    ]
    try:
        for path in sys.path:
            if "site-packages" in path or ".venv" in path:
                suppress_list.append(path)
    except Exception:
        pass

    logging.basicConfig(
        level=level,
        format="%(message)s",
        handlers=[
            TerminalHandler(
                console=Console(stderr=True, width=min(Console().width, 140)),
                markup=True,
                rich_tracebacks=True,
                tracebacks_extra_lines=1,
                tracebacks_suppress=suppress_list,
                show_path=False,
                show_level=True,
                show_time=show_time,
            )
        ],
        force=True,
    )
    if os.environ.get("CANARY_ENV") == "production":
        handler = logging.StreamHandler()
        handler.setFormatter(JsonFormatter())
        logging.getLogger().handlers = [handler]
    else:
        logging.getLogger().handlers[0].addFilter(TerminalFilter())
    logging.getLogger("uvicorn.access").disabled = True
    logging.getLogger("httpx").setLevel(logging.WARNING)
    from .diagnostics import local_diagnostics_enabled

    if local_diagnostics_enabled():
        logging.getLogger("canary.diagnostics").info(
            "[bold blue]Local diagnostics[/] enabled; failures are recorded in "
            "the project .canary/diagnostics.jsonl journal."
        )
    configure_telemetry()


_STATIC_FILE_PATH_FRAGMENTS = (
    "/files/refs/",
    "/files/plates/",
    "/files/pages/",
    "/files/draw/",
    "/files/samples/",
)


def _should_log_request(request: Request, status_code: int, elapsed_ms: float) -> bool:
    path = request.url.path
    # Suppress noisy polling for asset files (auth failures, not-yet-generated, etc.)
    if status_code < 500 and any(fragment in path for fragment in _STATIC_FILE_PATH_FRAGMENTS):
        return False
    # EventSource reconnects while no pipeline run is active. The endpoint's
    # 404 means "no active event queue", not that the route or project is
    # missing, so logging every retry obscures actionable failures.
    if path.endswith("/events") and status_code == 404:
        return False
    if status_code >= 400:
        return True
    if path.endswith("/events"):
        return False
    if path.endswith("/generation-jobs"):
        return False
    if path.endswith("/status"):
        return False
    if request.method != "GET" or elapsed_ms >= 1000:
        return True
    return False


async def _request_log_middleware(
    request: Request,
    call_next: Callable[[Request], Response],
) -> Response:
    request_id = getattr(request.state, "request_id", None) or str(uuid.uuid4())
    request.state.request_id = request_id
    started = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception as exc:
        from .telemetry import capture_exception, log_event
        capture_exception(exc, user_id=getattr(request.state, "user_id", None), route=_route_template(request))
        log_event("http.failed", level=logging.ERROR, route=_route_template(request), error_type=type(exc).__name__)
        elapsed_ms = (time.perf_counter() - started) * 1000
        route = _route_template(request)
        increment(
            "canary_http_requests_total",
            method=request.method,
            route=route,
            status_class="5xx",
        )
        observe(
            "canary_http_request_duration_seconds",
            elapsed_ms / 1000,
            method=request.method,
            route=route,
        )
        metric_attributes = {
            "method": request.method,
            "route": route,
            "status_class": "5xx",
        }
        metric_count("http.server.requests", attributes=metric_attributes)
        metric_histogram(
            "http.server.duration", elapsed_ms, unit="ms", attributes=metric_attributes
        )
        api_logger.exception(
            "[bold red]API failed[/] %s [white]%s[/] elapsed=[bold]%.0fms[/] request_id=%s",
            request.method,
            route,
            elapsed_ms,
            request_id,
        )
        raise

    elapsed_ms = (time.perf_counter() - started) * 1000
    route = _route_template(request)
    if route not in {"/metrics", "/api/health", "/api/health/ready"}:
        increment(
            "canary_http_requests_total",
            method=request.method,
            route=route,
            status_class=f"{response.status_code // 100}xx",
        )
        observe(
            "canary_http_request_duration_seconds",
            elapsed_ms / 1000,
            method=request.method,
            route=route,
        )
        metric_attributes = {
            "method": request.method,
            "route": route,
            "status_class": f"{response.status_code // 100}xx",
        }
        metric_count("http.server.requests", attributes=metric_attributes)
        metric_histogram(
            "http.server.duration", elapsed_ms, unit="ms", attributes=metric_attributes
        )
    response.headers["X-Request-ID"] = request_id
    if _should_log_request(request, response.status_code, elapsed_ms):
        from .telemetry import log_event
        log_event("http.completed", route=route, method=request.method, http_status=response.status_code, latency_ms=elapsed_ms)
    if _should_log_request(request, response.status_code, elapsed_ms):
        expected_artifact_read = (
            request.method in {"GET", "HEAD"}
            and response.status_code in {404, 409}
            and getattr(request.state, "artifact_unavailable", False)
            and os.environ.get("CANARY_ENV") != "production"
        )
        if expected_artifact_read:
            log_level = logging.DEBUG
        elif response.status_code >= 500:
            log_level = logging.ERROR
        elif response.status_code >= 400:
            log_level = logging.WARNING
        else:
            log_level = logging.INFO if os.environ.get("CANARY_ENV") == "production" else logging.DEBUG
        api_logger.log(
            log_level,
            "[bold magenta]API[/] %s [white]%s[/] -> [bold]%s[/] elapsed=%.0fms request_id=%s",
            request.method,
            route,
            response.status_code,
            elapsed_ms,
            request_id,
        )
    return response


def _route_template(request: Request) -> str:
    route = request.scope.get("route")
    path = getattr(route, "path", None)
    # Never fall back to the raw URL: project/scene IDs would create unbounded
    # Prometheus cardinality. Unmatched requests share one stable label.
    return str(path) if path else "unmatched"


async def request_log_middleware(request: Request, call_next):
    from .telemetry import operation_span, context_fields
    uuid_pattern = r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}"
    incoming_id = request.headers.get("X-Request-ID", "")
    request.state.request_id = incoming_id if re.fullmatch(uuid_pattern, incoming_id) else str(uuid.uuid4())
    session_id = request.headers.get("X-Canary-Session-ID", "")
    session_id = session_id if re.fullmatch(uuid_pattern, session_id) else None
    traceparent = request.headers.get("traceparent", "")
    carrier = {"traceparent": traceparent} if re.fullmatch(r"00-[0-9a-f]{32}-[0-9a-f]{16}-0[01]", traceparent) else {}
    # Do not accept arbitrary public baggage, user identity or span names.
    if request.url.path in {"/metrics", "/api/health", "/api/health/ready"} or not request.url.path.startswith("/api/"):
        return await _request_log_middleware(request, call_next)
    with operation_span("http.request", carrier=carrier, request_id=request.state.request_id,
                        browser_session_id=session_id, method=request.method) as span:
        response = await _request_log_middleware(request, call_next)
        if trace_id := context_fields().get("trace_id"):
            response.headers["X-Trace-ID"] = trace_id
        if span is not None:
            span.set_attribute("route", _route_template(request))
            span.set_attribute("http_status", response.status_code)
            user_id = getattr(request.state, "user_id", None)
            if isinstance(user_id, str) and re.fullmatch(uuid_pattern, user_id):
                span.set_attribute("posthogDistinctId", user_id)
        return response
