"""OpenTelemetry bootstrap for `pipeline serve` and CLI runs."""

from __future__ import annotations

import atexit
import logging
import os

logger = logging.getLogger("canary.telemetry")

_CONFIGURED = False


def _bool_env(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def configure_telemetry() -> bool:
    """Configure OTLP trace export when explicitly enabled."""
    global _CONFIGURED
    if _CONFIGURED:
        return True
    if not _bool_env("CANARY_OTEL_ENABLED", default=False):
        return False

    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
    except Exception as e:
        logger.warning("OpenTelemetry requested but packages are missing: %s", e)
        return False

    resource = Resource.create(
        {
            "service.name": os.environ.get("OTEL_SERVICE_NAME", "canary"),
            "service.version": os.environ.get("CANARY_VERSION", "0.1.0"),
            "deployment.environment": os.environ.get("CANARY_ENV", "dev"),
        }
    )

    provider = TracerProvider(resource=resource)
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    try:
        trace.set_tracer_provider(provider)
    except Exception:
        logger.warning("OpenTelemetry tracer provider already configured; skipping override.")
        return True
    atexit.register(provider.shutdown)
    _CONFIGURED = True
    logger.info(
        "[bold blue]OTel enabled[/] endpoint=%s protocol=%s service=%s",
        os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "(default)"),
        os.environ.get("OTEL_EXPORTER_OTLP_PROTOCOL", "(default)"),
        os.environ.get("OTEL_SERVICE_NAME", "canary"),
    )
    return True
