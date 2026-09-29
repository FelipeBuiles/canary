"""Small low-cardinality Prometheus registry for Fly's managed scraper."""

from __future__ import annotations

import threading
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from fastapi.responses import PlainTextResponse


@dataclass
class _Histogram:
    buckets: tuple[float, ...]
    counts: list[int] = field(init=False)
    total: float = 0.0
    count: int = 0

    def __post_init__(self) -> None:
        self.counts = [0] * len(self.buckets)

    def observe(self, value: float) -> None:
        self.total += value
        self.count += 1
        for index, boundary in enumerate(self.buckets):
            if value <= boundary:
                self.counts[index] += 1


_lock = threading.Lock()
_counters: dict[tuple[str, tuple[tuple[str, str], ...]], float] = defaultdict(float)
_histograms: dict[tuple[str, tuple[tuple[str, str], ...]], _Histogram] = {}

_COUNTERS: dict[str, tuple[str, tuple[str, ...]]] = {
    "canary_http_requests_total": ("HTTP requests handled", ("method", "route", "status_class")),
    "canary_stage_runs_total": ("Pipeline stage runs", ("stage", "outcome")),
    "canary_ai_calls_total": ("AI provider calls", ("provider", "model", "operation", "status")),
    "canary_ai_provider_cost_usd_total": ("Recent provider cost in USD", ("provider", "model", "stage")),
    "canary_ai_input_tokens_total": ("AI input tokens", ("provider", "model", "stage")),
    "canary_ai_output_tokens_total": ("AI completion tokens including reasoning", ("provider", "model", "stage")),
    "canary_ai_reasoning_tokens_total": ("AI hidden reasoning tokens", ("provider", "model", "stage")),
    "canary_structured_call_attempts_total": ("Structured model call attempts", ("feature", "attempt")),
    "canary_credit_debit_failures_total": ("Provider charges that failed customer debit", ("stage",)),
    "canary_image_route_fallbacks_total": ("Sunburst images that fell back from their primary route", ("reason", "surface")),
    "canary_absorbed_image_attempts_total": ("Unknown-outcome image attempts Canary absorbed", ("route", "surface")),
    "canary_image_route_circuit_opened_total": ("Sunburst routes skipped after repeated failures", ("route",)),
}

_HISTOGRAMS: dict[str, tuple[str, tuple[str, ...], tuple[float, ...]]] = {
    "canary_http_request_duration_seconds": (
        "HTTP request duration",
        ("method", "route"),
        (0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60),
    ),
    "canary_stage_duration_seconds": (
        "Pipeline stage duration",
        ("stage", "outcome"),
        (1, 5, 15, 30, 60, 120, 300, 600, 900, 1800),
    ),
    "canary_stage_cost_ratio": (
        "Actual provider cost divided by estimated provider cost",
        ("stage",),
        (0.5, 0.75, 1, 1.25, 1.5, 2, 3, 5, 10),
    ),
}


def _labels(name: str, values: dict[str, Any], expected: tuple[str, ...]) -> tuple[tuple[str, str], ...]:
    if set(values) != set(expected):
        raise ValueError(f"Metric {name} labels must be {expected}")
    return tuple((key, str(values[key])[:120]) for key in expected)


def increment(name: str, amount: float = 1.0, **labels: Any) -> None:
    _help, expected = _COUNTERS[name]
    key = (name, _labels(name, labels, expected))
    with _lock:
        _counters[key] += amount


def observe(name: str, value: float, **labels: Any) -> None:
    _help, expected, buckets = _HISTOGRAMS[name]
    key = (name, _labels(name, labels, expected))
    with _lock:
        histogram = _histograms.setdefault(key, _Histogram(buckets))
        histogram.observe(max(0.0, float(value)))


def record_ai_call(
    *,
    provider: str | None,
    model: str,
    operation: str,
    status: str,
    stage: str | None,
    cost_usd: float | None,
    input_tokens: int = 0,
    output_tokens: int = 0,
    reasoning_tokens: int = 0,
) -> None:
    safe_provider = provider or "unknown"
    safe_stage = stage or "none"
    increment(
        "canary_ai_calls_total",
        provider=safe_provider,
        model=model,
        operation=operation,
        status=status,
    )
    if cost_usd and cost_usd > 0:
        increment(
            "canary_ai_provider_cost_usd_total",
            amount=cost_usd,
            provider=safe_provider,
            model=model,
            stage=safe_stage,
        )
    token_labels = {"provider": safe_provider, "model": model, "stage": safe_stage}
    if input_tokens > 0:
        increment("canary_ai_input_tokens_total", amount=input_tokens, **token_labels)
    if output_tokens > 0:
        increment("canary_ai_output_tokens_total", amount=output_tokens, **token_labels)
    if reasoning_tokens > 0:
        increment("canary_ai_reasoning_tokens_total", amount=reasoning_tokens, **token_labels)


def record_structured_attempt(*, feature: str, retry: bool) -> None:
    increment(
        "canary_structured_call_attempts_total",
        feature=feature,
        attempt="retry" if retry else "initial",
    )


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


def _format_labels(labels: tuple[tuple[str, str], ...], extra: tuple[str, str] | None = None) -> str:
    values = list(labels)
    if extra:
        values.append(extra)
    if not values:
        return ""
    return "{" + ",".join(f'{key}="{_escape(value)}"' for key, value in values) + "}"


def render_metrics(app) -> str:
    lines: list[str] = []
    with _lock:
        counters = dict(_counters)
        histograms = {
            key: (hist.buckets, list(hist.counts), hist.total, hist.count)
            for key, hist in _histograms.items()
        }

    for name, (help_text, _expected) in _COUNTERS.items():
        lines.extend((f"# HELP {name} {help_text}", f"# TYPE {name} counter"))
        for (metric_name, labels), value in sorted(counters.items()):
            if metric_name == name:
                lines.append(f"{name}{_format_labels(labels)} {value:g}")

    for name, (help_text, _expected, _configured_buckets) in _HISTOGRAMS.items():
        lines.extend((f"# HELP {name} {help_text}", f"# TYPE {name} histogram"))
        for (metric_name, labels), (buckets, counts, total, count) in sorted(histograms.items()):
            if metric_name != name:
                continue
            for boundary, bucket_count in zip(buckets, counts, strict=True):
                lines.append(f"{name}_bucket{_format_labels(labels, ('le', f'{boundary:g}'))} {bucket_count}")
            lines.append(f"{name}_bucket{_format_labels(labels, ('le', '+Inf'))} {count}")
            lines.append(f"{name}_sum{_format_labels(labels)} {total:g}")
            lines.append(f"{name}_count{_format_labels(labels)} {count}")

    jobs = list(getattr(app.state, "generation_jobs", {}).values())
    job_counts = {status: sum(1 for job in jobs if job.status == status) for status in ("queued", "running")}
    queue_size = getattr(getattr(app.state, "generation_queue", None), "qsize", lambda: 0)()
    lines.extend((
        "# HELP canary_generation_jobs Current generation jobs",
        "# TYPE canary_generation_jobs gauge",
        *(f'canary_generation_jobs{{status="{status}"}} {count}' for status, count in job_counts.items()),
        "# HELP canary_generation_queue_items Current generation queue depth",
        "# TYPE canary_generation_queue_items gauge",
        f"canary_generation_queue_items {queue_size}",
    ))
    return "\n".join(lines) + "\n"


def metrics_response(app) -> PlainTextResponse:
    return PlainTextResponse(
        render_metrics(app),
        media_type="text/plain; version=0.0.4; charset=utf-8",
    )


def reset_metrics_for_tests() -> None:
    with _lock:
        _counters.clear()
        _histograms.clear()
