"""Structured, redacted API call logging utilities."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
import uuid
from collections.abc import Mapping, Sequence
from typing import Any

_REDACT_KEYS = {
    "api_key",
    "apikey",
    "authorization",
    "token",
    "access_token",
    "refresh_token",
    "secret",
    "password",
}

_MAX_ITEMS = 20
_MAX_STRING = 300
_MAX_IMAGE_PROMPT_STRING = 1200
_MAX_SPAN_ATTR = 4000
_SPAN_CHUNK_SIZE = 3500
_ACTIVE_SPANS: dict[str, Any] = {}


def _bool_env(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _truncate(value: str, limit: int = _MAX_STRING) -> str:
    if len(value) <= limit:
        return value
    return f"{value[:limit]}...(+{len(value) - limit} chars)"


def _full_prompts_enabled() -> bool:
    return _bool_env("CANARY_LOG_FULL_PROMPTS", default=False)


def _is_sensitive_key(key: str) -> bool:
    lowered = key.lower()
    return any(marker in lowered for marker in _REDACT_KEYS)


def _sanitize(value: Any, *, key_hint: str | None = None) -> Any:
    if value is None or isinstance(value, (int, float, bool)):
        return value
    if isinstance(value, str):
        if _full_prompts_enabled():
            return value
        limit = _MAX_STRING
        if key_hint and key_hint.lower() in {
            "image_prompt",
            "image_prompt_preview",
            "user_preview",
            "system_preview",
        }:
            limit = _MAX_IMAGE_PROMPT_STRING
        return _truncate(value, limit=limit)
    if isinstance(value, Mapping):
        items = list(value.items())[:_MAX_ITEMS]
        sanitized: dict[str, Any] = {}
        for k, v in items:
            key = str(k)
            if _is_sensitive_key(key):
                sanitized[key] = "***REDACTED***"
            else:
                sanitized[key] = _sanitize(v, key_hint=key)
        if len(value) > _MAX_ITEMS:
            sanitized["_truncated_items"] = len(value) - _MAX_ITEMS
        return sanitized
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        items = list(value)[:_MAX_ITEMS]
        sanitized = [_sanitize(v) for v in items]
        if len(value) > _MAX_ITEMS:
            sanitized.append(f"...(+{len(value) - _MAX_ITEMS} items)")
        return sanitized
    return _truncate(str(value))


def _text_fingerprint(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]


def _current_trace_id() -> str | None:
    try:
        from opentelemetry import trace  # type: ignore[import-not-found]

        span = trace.get_current_span()
        ctx = span.get_span_context()
        if ctx and getattr(ctx, "is_valid", False):
            return format(ctx.trace_id, "032x")
    except Exception:
        return None
    return None


def _start_span(
    call_id: str,
    provider: str,
    operation: str,
    params: Mapping[str, Any] | None,
    payload: Mapping[str, Any] | None,
) -> str | None:
    try:
        from opentelemetry import trace

        tracer = trace.get_tracer("canary.api")
        span = tracer.start_span(f"{provider}.{operation}")
        span.set_attribute("canary.call_id", call_id)
        span.set_attribute("canary.provider", provider)
        span.set_attribute("canary.operation", operation)
        if params:
            safe = _sanitize(params)
            params_json = json.dumps(safe, ensure_ascii=True, sort_keys=True)
            span.set_attribute("canary.params_json", _truncate(params_json, _MAX_SPAN_ATTR))
        if payload:
            safe_payload = _sanitize(payload)
            payload_json = json.dumps(safe_payload, ensure_ascii=True, sort_keys=True)
            if _full_prompts_enabled() and len(payload_json) > _MAX_SPAN_ATTR:
                span.set_attribute("canary.payload_json_truncated", False)
                parts = [
                    payload_json[i : i + _SPAN_CHUNK_SIZE]
                    for i in range(0, len(payload_json), _SPAN_CHUNK_SIZE)
                ]
                span.set_attribute("canary.payload_json_parts", len(parts))
                for idx, part in enumerate(parts):
                    span.set_attribute(f"canary.payload_json_part_{idx:03d}", part)
            else:
                span.set_attribute("canary.payload_json", _truncate(payload_json, _MAX_SPAN_ATTR))
        _ACTIVE_SPANS[call_id] = span
        ctx = span.get_span_context()
        if ctx and getattr(ctx, "is_valid", False):
            return format(ctx.trace_id, "032x")
    except Exception:
        return None
    return None


def _finish_span(
    call_id: str,
    *,
    ok: bool,
    status_code: int | None = None,
    result: Mapping[str, Any] | None = None,
    error: BaseException | None = None,
) -> None:
    span = _ACTIVE_SPANS.pop(call_id, None)
    if span is None:
        return
    try:
        if status_code is not None:
            span.set_attribute("http.status_code", status_code)
        if result:
            result_json = json.dumps(_sanitize(result), ensure_ascii=True, sort_keys=True)
            span.set_attribute("canary.result_json", _truncate(result_json, _MAX_SPAN_ATTR))
        if error is not None:
            span.record_exception(error)
            try:
                from opentelemetry.trace import Status, StatusCode

                span.set_status(Status(StatusCode.ERROR, str(error)))
            except Exception:
                pass
        elif ok:
            try:
                from opentelemetry.trace import Status, StatusCode

                span.set_status(Status(StatusCode.OK))
            except Exception:
                pass
    finally:
        span.end()


def payload_summary(*, system_prompt: str | None = None, user_content: str | None = None) -> dict[str, Any]:
    include_text = _bool_env("CANARY_LOG_INCLUDE_PROMPTS", default=False)
    full_prompts = _full_prompts_enabled()
    out: dict[str, Any] = {}
    if system_prompt is not None:
        out["system_chars"] = len(system_prompt)
        out["system_sha"] = _text_fingerprint(system_prompt)
        if include_text and not full_prompts:
            out["system_preview"] = _truncate(system_prompt, 600)
    if user_content is not None:
        out["user_chars"] = len(user_content)
        out["user_sha"] = _text_fingerprint(user_content)
        if include_text and not full_prompts:
            out["user_preview"] = _truncate(user_content, 600)
    return out


def image_payload_summary(prompt: str) -> dict[str, Any]:
    """Summarize image prompts without logging prompt text unless explicitly enabled."""
    out = payload_summary(user_content=prompt)
    if _bool_env("CANARY_LOG_INCLUDE_PROMPTS", default=False) or _full_prompts_enabled():
        out["image_prompt"] = prompt
    return out


def log_call_start(
    logger: logging.Logger,
    *,
    provider: str,
    operation: str,
    params: Mapping[str, Any] | None = None,
    payload: Mapping[str, Any] | None = None,
) -> tuple[str, float]:
    call_id = uuid.uuid4().hex[:12]
    started = time.perf_counter()
    event: dict[str, Any] = {
        "event": "api_call_start",
        "call_id": call_id,
        "provider": provider,
        "operation": operation,
    }
    trace_id = _start_span(call_id, provider, operation, params, payload) or _current_trace_id()
    if trace_id:
        event["trace_id"] = trace_id
    if params:
        event["params"] = _sanitize(params)
    if payload:
        event["payload"] = _sanitize(payload)
    logger.info("[bold cyan]API call[/] %s", json.dumps(event, ensure_ascii=True, sort_keys=True))
    return call_id, started


def log_call_end(
    logger: logging.Logger,
    *,
    call_id: str,
    started: float,
    provider: str,
    operation: str,
    ok: bool,
    status_code: int | None = None,
    result: Mapping[str, Any] | None = None,
    error: BaseException | None = None,
) -> None:
    _finish_span(call_id, ok=ok, status_code=status_code, result=result, error=error)
    event: dict[str, Any] = {
        "event": "api_call_end",
        "call_id": call_id,
        "provider": provider,
        "operation": operation,
        "ok": ok,
        "elapsed_ms": round((time.perf_counter() - started) * 1000, 1),
    }
    trace_id = _current_trace_id()
    if trace_id:
        event["trace_id"] = trace_id
    if status_code is not None:
        event["status_code"] = status_code
    if result:
        event["result"] = _sanitize(result)
    if error is not None:
        event["error"] = {
            "type": error.__class__.__name__,
            "message": _truncate(str(error), 500),
        }
    level = logging.INFO if ok else logging.ERROR
    logger.log(level, "[bold green]API done[/] %s", json.dumps(event, ensure_ascii=True, sort_keys=True))
