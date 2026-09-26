"""Logging helpers for the web server."""

from __future__ import annotations

import logging
import json
import os
import time
import uuid
from collections.abc import Callable

from fastapi import Request, Response
from rich.console import Console
from rich.logging import RichHandler

from novel_to_comic.server.env import bool_env
from novel_to_comic.server.telemetry import configure_telemetry
from novel_to_comic.server.metrics import increment, observe


api_logger = logging.getLogger("canary.api")


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
            RichHandler(
                console=Console(stderr=True),
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
    if any(fragment in path for fragment in _STATIC_FILE_PATH_FRAGMENTS):
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
    response.headers["X-Request-ID"] = request_id
    if _should_log_request(request, response.status_code, elapsed_ms):
        from .telemetry import log_event
        log_event("http.completed", route=route, method=request.method, http_status=response.status_code, latency_ms=elapsed_ms)
    if _should_log_request(request, response.status_code, elapsed_ms):
        api_logger.info(
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
    from .telemetry import operation_span
    request.state.request_id = str(uuid.uuid4())
    # Do not accept arbitrary public baggage, user identity or span names.
    if request.url.path in {"/metrics", "/api/health", "/api/health/ready"} or request.method == "GET":
        return await _request_log_middleware(request, call_next)
    with operation_span("http.request", request_id=request.state.request_id, method=request.method) as span:
        response = await _request_log_middleware(request, call_next)
        if span is not None:
            span.set_attribute("route", _route_template(request))
            span.set_attribute("http_status", response.status_code)
        return response
