"""Shared PostHog application metrics for the Canary LiteLLM gateway.

The client is created lazily inside the gateway process (after any server
fork) from the same ``POSTHOG_PROJECT_TOKEN``/``POSTHOG_HOST`` pair the app
uses. Metric failures never affect a gateway request, and exception reports
keep types and code locations only: provider error text can echo submitted
content, so messages are redacted before send.
"""
from __future__ import annotations

import atexit
import os
import sys
from threading import Lock
from time import perf_counter
from typing import Any


_HOSTS = frozenset({"https://us.i.posthog.com", "https://eu.i.posthog.com"})
_UNSET = object()
_client: Any = _UNSET
_client_lock = Lock()
_active_requests = 0
_active_requests_lock = Lock()
_ALLOWED_METHODS = frozenset({"GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"})
_FRAME_KEYS = ("filename", "abs_path", "module", "function", "lineno", "colno", "in_app", "platform")


def configure_metrics(client: Any) -> None:
    """Attach an explicit client (tests); ``None`` disables metrics."""
    global _client
    _client = client


def _redact_exception(event: dict[str, Any]) -> dict[str, Any] | None:
    try:
        properties = event.get("properties") or {}
        if event.get("event") == "$exception":
            exceptions = []
            for item in (properties.get("$exception_list") or [])[:5]:
                frames = ((item.get("stacktrace") or {}).get("frames") or [])[-40:]
                exceptions.append({
                    "type": str(item.get("type") or "Exception")[:120],
                    "value": "[redacted]",
                    "mechanism": item.get("mechanism"),
                    "stacktrace": {
                        "type": "raw",
                        "frames": [{key: frame[key] for key in _FRAME_KEYS if key in frame} for frame in frames],
                    },
                })
            properties["$exception_list"] = exceptions
            properties["$exception_message"] = "[redacted]"
        properties["$geoip_disable"] = True
        event["properties"] = properties
        return event
    except Exception:
        return None


def _create_client() -> Any:
    key = os.environ.get("POSTHOG_PROJECT_TOKEN", "").strip()
    host = os.environ.get("POSTHOG_HOST", "").rstrip("/")
    if not key or host not in _HOSTS:
        print("PostHog gateway metrics disabled: POSTHOG_PROJECT_TOKEN/POSTHOG_HOST unset", file=sys.stderr)
        return None
    try:
        from posthog import Posthog

        client = Posthog(
            key,
            host=host,
            metrics={"service_name": "canary-gateway"},
            enable_exception_autocapture=True,
            capture_exception_code_variables=False,
            log_captured_exceptions=False,
            disable_geoip=True,
            before_send=_redact_exception,
            timeout=3,
            max_retries=0,
        )
    except Exception as exc:
        print(f"PostHog gateway metrics unavailable: {type(exc).__name__}", file=sys.stderr)
        return None
    atexit.register(client.shutdown)
    return client


def metrics_client() -> Any | None:
    global _client
    if _client is _UNSET:
        with _client_lock:
            if _client is _UNSET:
                _client = _create_client()
    return _client


def record(kind: str, name: str, value: float = 1, **options: Any) -> None:
    """Emit one metric; telemetry failures never reach the caller."""
    client = metrics_client()
    if client is None:
        return
    try:
        getattr(client.metrics, kind)(name, value, **options)
    except Exception:
        pass


def _method(value: object) -> str:
    normalized = str(value).upper()
    return normalized if normalized in _ALLOWED_METHODS else "OTHER"


def _status_class(status: int) -> str:
    return f"{status // 100}xx" if 100 <= status <= 599 else "unknown"


class PostHogMetricsMiddleware:
    """Record every HTTP request at the gateway's single ASGI choke point."""

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        global _active_requests
        method = _method(scope.get("method", "OTHER"))
        status = 500
        started = perf_counter()
        with _active_requests_lock:
            _active_requests += 1
            active_requests = _active_requests
        record("gauge", "http.server.active_requests", active_requests)

        async def observe_start(message: dict[str, Any]) -> None:
            nonlocal status
            if message.get("type") == "http.response.start":
                status = int(message.get("status", 500))
            await send(message)

        try:
            await self.app(scope, receive, observe_start)
        finally:
            with _active_requests_lock:
                _active_requests -= 1
                active_requests = _active_requests
            attributes = {"method": method, "status_class": _status_class(status)}
            record("count", "http.server.requests", attributes=attributes)
            record(
                "histogram",
                "http.server.duration",
                (perf_counter() - started) * 1000,
                unit="ms",
                attributes=attributes,
            )
            record("gauge", "http.server.active_requests", active_requests)
