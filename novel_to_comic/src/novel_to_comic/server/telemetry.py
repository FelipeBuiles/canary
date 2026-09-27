"""One privacy boundary for PostHog events and OTLP diagnostics.

Only explicit, content-free observations leave the app. No automatic request,
logging, prompt, local-variable, or HTTP-client instrumentation is installed.
The ledger and operation journal remain authoritative when export is lost.
"""
from __future__ import annotations

import contextlib
from contextvars import ContextVar
import logging
import math
import os
import re
import threading
import time
from typing import Any

_CONTEXT: ContextVar[dict[str, Any]] = ContextVar("telemetry_context", default={})
_client = None
_provider = None
_log_provider = None
_log_handler = None
_TOKEN = re.compile(r"^[A-Za-z0-9_./:{}@+-]{1,160}$")
_ID = re.compile(r"^[a-fA-F0-9-]{16,64}$")
_FIELDS = frozenset({
    "request_id", "operation_id", "job_id", "project_id", "stage", "feature", "operation",
    "status", "phase", "error_type", "model_alias", "provider_model", "provider", "funding",
    "cost_status", "cost_source", "cost_usd", "estimated_cost_usd", "latency_ms", "image_count",
    "input_tokens", "output_tokens", "page_number", "is_correction", "queue_ms", "http_status",
    "route", "method", "source", "file_type", "rerun", "retry_failed", "outcome", "style_id",
    "package_id", "gross_amount_cents", "currency", "credits", "amount_credits", "app_environment",
    "stripe_mode", "format", "cached", "station", "drawer", "mode", "schema_version",
    "feedback_id", "category", "rating", "trace_id", "span_id", "release", "environment",
    "posthogDistinctId", "source_event_id", "event_origin",
})
_AI_FIELDS = frozenset({"$ai_trace_id", "$ai_span_id", "$ai_parent_id", "$ai_model", "$ai_provider",
    "$ai_latency", "$ai_input_tokens", "$ai_output_tokens", "$ai_is_error", "$ai_error",
    "$ai_cost_passthrough", "$ai_total_cost_usd", "$ai_cache_read_input_tokens",
    "$ai_cache_creation_input_tokens", "$ai_cache_reporting_exclusive"})


def safe_fields(fields: dict[str, Any]) -> dict[str, Any]:
    result = {}
    for key, value in fields.items():
        if key not in _FIELDS | _AI_FIELDS:
            continue
        if isinstance(value, bool) or isinstance(value, int):
            result[key] = value
        elif isinstance(value, float) and math.isfinite(value):
            result[key] = value
        elif isinstance(value, str) and _TOKEN.fullmatch(value):
            result[key] = value
    return result


def context_fields() -> dict[str, Any]:
    return dict(_CONTEXT.get())


@contextlib.contextmanager
def observation_context(**fields):
    token = _CONTEXT.set({**_CONTEXT.get(), **safe_fields(fields)})
    try:
        yield
    finally:
        _CONTEXT.reset(token)


def trace_carrier() -> dict[str, str]:
    try:
        from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator
        carrier: dict[str, str] = {}
        TraceContextTextMapPropagator().inject(carrier)
        return {k: v for k, v in carrier.items() if k == "traceparent"}
    except Exception:
        return {}


@contextlib.contextmanager
def operation_span(name: str, *, carrier=None, **fields):
    """No implicit exception recording: exception strings may contain creative text."""
    with observation_context(**fields):
        manager = contextlib.nullcontext(None)
        try:
            from opentelemetry import trace
            from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator
            parent = TraceContextTextMapPropagator().extract(carrier) if carrier is not None else None
            manager = (_provider.get_tracer("canary") if _provider else trace.get_tracer("canary")).start_as_current_span(
                name, context=parent, attributes=context_fields(),
                record_exception=False, set_status_on_exception=False,
            )
        except Exception:
            pass
        with manager as span:
            try:
                identifiers = {}
                if span is not None:
                    span_context = span.get_span_context()
                    if span_context.is_valid:
                        identifiers = {"trace_id": format(span_context.trace_id, "032x"),
                                       "span_id": format(span_context.span_id, "016x")}
                with observation_context(**identifiers):
                    yield span
            except BaseException as exc:
                if span is not None:
                    from opentelemetry.trace import Status, StatusCode
                    span.set_attribute("error_type", type(exc).__name__)
                    span.set_status(Status(StatusCode.ERROR))
                raise


def _exception_list(items):
    """Preserve code locations for grouping, never values, source lines or locals."""
    result = []
    for item in (items or [])[:5]:
        kind = str(item.get("type", "Error"))
        frames = []
        for frame in item.get("stacktrace", {}).get("frames", [])[-40:]:
            clean = {key: frame[key] for key in ("lineno", "colno", "in_app") if key in frame}
            for key in ("filename", "function", "module"):
                value = str(frame.get(key, ""))
                if key == "filename":
                    value = value.replace("\\", "/").rsplit("/", 1)[-1]
                if _TOKEN.fullmatch(value):
                    clean[key] = value
            frames.append(clean)
        result.append({"type": kind if _TOKEN.fullmatch(kind) else "Error",
                       "value": "[redacted]", "stacktrace": {"frames": frames}})
    return result


def _before_send(event):
    # SDK hooks may fail open on an exception. This hook explicitly fails closed.
    try:
        properties = event.get("properties", {})
        clean = safe_fields(properties)
        for key in ("$exception_list",):
            if key in properties:
                clean[key] = _exception_list(properties[key])
        for key in ("$exception_type", "$exception_level", "$exception_personURL"):
            if key in properties and key != "$exception_personURL":
                value = str(properties[key])
                if _TOKEN.fullmatch(value):
                    clean[key] = value
        clean["$exception_message"] = "[redacted]" if event.get("event") == "$exception" else None
        clean.update({"$geoip_disable": True, "$process_person_profile": True, "$is_server": True})
        for key in ("$lib", "$lib_version"):
            if key in properties and _TOKEN.fullmatch(str(properties[key])):
                clean[key] = properties[key]
        if properties.get("$insert_id"):
            clean["$insert_id"] = str(properties["$insert_id"])
        # Persisted product events retain the release that produced them, even
        # when a later process delivers the outbox.
        clean.setdefault("environment", os.environ.get("CANARY_ENV", "development"))
        clean.setdefault("release", os.environ.get("CANARY_VERSION", "unknown"))
        clean.setdefault("schema_version", 1)
        clean["$release_id"] = clean["release"]
        event["properties"] = {k: v for k, v in clean.items() if v is not None}
        return {key: event[key] for key in ("event", "properties", "distinct_id", "timestamp", "uuid") if key in event}
    except Exception:
        return None


def capture(event: str, *, user_id: str | None = None, properties=None, event_id=None, timestamp=None) -> None:
    if _client is None:
        return
    try:
        identity = user_id if user_id and _ID.fullmatch(user_id) else "canary-server"
        props = safe_fields({**context_fields(), **(properties or {})})
        props.update(environment=os.environ.get("CANARY_ENV", "development"),
                     release=os.environ.get("CANARY_VERSION", "unknown"), schema_version=1)
        if event_id:
            props["$insert_id"] = str(event_id)
        _client.capture(event, distinct_id=identity, properties=props, timestamp=timestamp)
    except Exception:
        # No exporter failure can turn a paid action into a retry.
        pass


def capture_exception(error: BaseException, *, user_id=None, **fields):
    if _client is None:
        return
    try:
        identity = user_id if user_id and _ID.fullmatch(user_id) else "canary-server"
        _client.capture_exception(error, distinct_id=identity,
                                  properties=safe_fields({**context_fields(), "$ai_trace_id": context_fields().get("operation_id"), **fields}))
    except Exception:
        pass


def log_event(name: str, *, level=logging.INFO, **fields):
    """Selected bounded logs only; never attach this exporter to the root logger."""
    fields = safe_fields({**context_fields(), **fields})
    logging.getLogger("canary.observations").log(level, name, extra={"telemetry": fields})


class SafeLogHandler(logging.Handler):
    def emit(self, record):
        try:
            from opentelemetry._logs import SeverityNumber
            from opentelemetry._logs import LogRecord
            from opentelemetry import trace
            ctx = trace.get_current_span().get_span_context()
            name = record.msg if isinstance(record.msg, str) and _TOKEN.fullmatch(record.msg) else "observation"
            _log_provider.get_logger("canary").emit(LogRecord(
                body=name, attributes=safe_fields(getattr(record, "telemetry", {})),
                severity_text=record.levelname,
                severity_number=SeverityNumber.ERROR if record.levelno >= logging.ERROR else SeverityNumber.INFO,
                trace_id=ctx.trace_id, span_id=ctx.span_id, trace_flags=ctx.trace_flags,
            ))
        except Exception:
            pass


def configure_telemetry() -> bool:
    global _client, _provider, _log_provider, _log_handler
    if _client is not None:
        return True
    key = os.environ.get("POSTHOG_PROJECT_TOKEN", "").strip()
    host = os.environ.get("POSTHOG_HOST", "").rstrip("/")
    if not key or host not in {"https://us.i.posthog.com", "https://eu.i.posthog.com"}:
        return False
    try:
        from posthog import Posthog
        _client = Posthog(key, host=host, enable_exception_autocapture=False, log_captured_exceptions=False,
                          capture_exception_code_variables=False, disable_geoip=True,
                          before_send=_before_send, max_queue_size=256,
                          flush_at=256, flush_interval=5, timeout=3, max_retries=0)
    except Exception:
        logging.getLogger(__name__).warning("PostHog event initialization unavailable")
        return False
    try:
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.sampling import ParentBased, TraceIdRatioBased
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk._logs import LoggerProvider
        from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
        from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
        resource = Resource({"service.name": "canary", "service.version": os.getenv("CANARY_VERSION", "unknown"),
                             "deployment.environment": os.getenv("CANARY_ENV", "development")})
        try:
            rate = min(1., max(0., float(os.getenv("POSTHOG_TRACE_SAMPLE_RATE", "1"))))
        except ValueError:
            rate = 1.
        headers = {"Authorization": f"Bearer {key}"}
        _provider = TracerProvider(resource=resource, shutdown_on_exit=False, sampler=ParentBased(TraceIdRatioBased(rate)))
        _provider.add_span_processor(BatchSpanProcessor(
            OTLPSpanExporter(endpoint=host + "/i/v1/traces", headers=headers, timeout=3),
            max_queue_size=256, max_export_batch_size=256, schedule_delay_millis=5000,
        ))
        _log_provider = LoggerProvider(resource=resource, shutdown_on_exit=False)
        _log_provider.add_log_record_processor(BatchLogRecordProcessor(
            OTLPLogExporter(endpoint=host + "/i/v1/logs", headers=headers, timeout=3),
            max_queue_size=256, max_export_batch_size=256, schedule_delay_millis=5000,
        ))
        _log_handler = SafeLogHandler()
        logging.getLogger("canary.observations").addHandler(_log_handler)
    except Exception:
        logging.getLogger(__name__).warning("PostHog OTLP initialization unavailable")
    return True


def shutdown_telemetry():
    """Called off-loop at shutdown; finite HTTP timeouts and bounded queues."""
    global _client, _log_provider, _provider, _log_handler
    if _log_handler:
        logging.getLogger("canary.observations").removeHandler(_log_handler)
    # Never spend Fly's entire shutdown budget draining diagnostic queues.
    def close(provider):
        try:
            provider.shutdown()
        except Exception:
            pass
    threads = [threading.Thread(target=close, args=(provider,), daemon=True)
               for provider in (_log_provider, _provider, _client) if provider]
    for thread in threads:
        thread.start()
    deadline = time.monotonic() + 5
    for thread in threads:
        thread.join(max(0, deadline - time.monotonic()))
    _client = _log_provider = _provider = _log_handler = None


def observe_generation(*, event_id, feature, operation, model_alias, provider_model,
                       status, usage, cost_usd, cost_source, latency_ms, started_at=None, error=None,
                       funding=None, provider=None):
    from novel_to_comic.ai.context import current_ai_request_context
    ctx = current_ai_request_context()
    fields = safe_fields({**context_fields(), "project_id": ctx.project_id, "job_id": ctx.job_id,
        "stage": ctx.stage, "feature": feature, "operation": operation, "model_alias": model_alias,
        "provider_model": provider_model, "status": status, "latency_ms": latency_ms,
        "cost_status": "unknown" if cost_usd is None else ("reported" if usage and usage.cost_usd is not None and cost_source != "request_estimate" else "estimated"), "cost_source": cost_source,
        "cost_usd": cost_usd, "page_number": ctx.page_number, "is_correction": ctx.is_correction,
        "error_type": type(error).__name__ if error else None,
        "image_count": usage.image_count if usage else None,
        "funding": usage.funding if usage else funding,
        "provider": usage.provider if usage else provider})
    trace_id = context_fields().get("operation_id") or ctx.job_id or event_id
    fields.update({"$ai_trace_id": trace_id, "$ai_span_id": event_id,
                   "$ai_model": provider_model or model_alias, "$ai_latency": latency_ms / 1000,
                   "$ai_is_error": status != "succeeded"})
    if cost_usd is not None:
        fields["$ai_total_cost_usd"] = cost_usd
        fields["$ai_cost_passthrough"] = True
    # Without a total, PostHog may calculate a catalog estimate even with
    # passthrough enabled. cost_status and cost_usd remain Canary's authority;
    # our cost-confidence view never sums the vendor's inferred total.
    if usage:
        fields.update({"$ai_provider": usage.provider, "$ai_input_tokens": usage.input_tokens,
                       "$ai_output_tokens": usage.output_tokens,
                       # Canary normalizes input totals to INCLUDE cache reads
                       # and writes, including Claude's originally exclusive usage.
                       "$ai_cache_reporting_exclusive": False})
        if usage.cached_text_tokens is not None:
            fields["$ai_cache_read_input_tokens"] = usage.cached_text_tokens + (usage.cached_image_tokens or 0)
        if usage.cache_creation_input_tokens is not None:
            fields["$ai_cache_creation_input_tokens"] = usage.cache_creation_input_tokens
    elif provider:
        fields["$ai_provider"] = provider
    if error:
        fields["$ai_error"] = type(error).__name__
    capture("$ai_generation", user_id=ctx.user_id, properties=fields, event_id=event_id, timestamp=started_at)
    log_event("ai.completed", level=logging.INFO if status == "succeeded" else logging.ERROR, **fields)
    try:
        from opentelemetry import trace
        from opentelemetry.trace import Status, StatusCode
        start = int(started_at.timestamp() * 1e9) if started_at else None
        span = (_provider.get_tracer("canary.ai") if _provider else trace.get_tracer("canary.ai")).start_span("ai." + operation, start_time=start,
            attributes=safe_fields({**fields, "posthogDistinctId": ctx.user_id}))
        if status != "succeeded":
            span.set_status(Status(StatusCode.ERROR))
        span.end()
    except Exception:
        pass
