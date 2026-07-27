"""LiteLLM-backed internal AI client."""

from __future__ import annotations

import asyncio
import base64
import datetime
import hashlib
import json
import logging
import os
import random
import time
import uuid
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any

import httpx

from novel_to_comic.ai.context import current_ai_request_context
from novel_to_comic.ai.errors import AIRefusalError, AITransportError
from novel_to_comic.ai.finalisation import (
    begin_image_call,
    finalise_image_failure,
    finalise_image_success,
)
from novel_to_comic.config import Config, mock_mode_active
from novel_to_comic.provider_wire import ProviderWireRequest
from novel_to_comic.usage import (
    ApiResult,
    UsageRecord,
    calculate_cost_breakdown,
    estimate_text_cost,
    estimate_text_usage,
    usage_has_billable_activity,
)

logger = logging.getLogger("canary.ai")

_RETRYABLE_STATUS_CODES = {429, 502, 503, 504}
_TRANSPORT_ERRORS = (
    httpx.ConnectError,
    httpx.ReadError,
    httpx.WriteError,
    httpx.PoolTimeout,
)
_MAX_RETRIES = 3
# 429s get their own, longer retry budget: the provider is asking us to slow
# down, not reporting a failure. Backoff windows double from the base up to
# the cap (4/8/16/32/60s), so the full budget rides out a quota refill cycle.
_MAX_RATE_LIMIT_RETRIES = 5
_RATE_LIMIT_BASE_DELAY = 4.0
_RATE_LIMIT_MAX_DELAY = 60.0
# How many extra times to re-issue a structured-object call when the model
# returns malformed JSON. Set to 2 → up to 3 total attempts. Most JSON parse
# failures are one-off sampling artifacts (unescaped quote, truncated tail)
# that clear on a fresh draw at the same temperature.
_JSON_PARSE_MAX_RETRIES = 2

# Anthropic deprecated the `temperature` request param on Claude Opus 4.7;
# sending it returns 400. Haiku 4.5 / Sonnet 4.6 still accept it.
_TEMPERATURE_DEPRECATED_ALIASES = frozenset({"adapt-quality"})


def _retry_after_seconds(response: httpx.Response) -> float | None:
    """Parse a Retry-After header (delta-seconds or HTTP-date) into seconds."""
    raw = response.headers.get("retry-after", "").strip()
    if not raw:
        return None
    try:
        return max(0.0, float(raw))
    except ValueError:
        pass
    try:
        retry_at = parsedate_to_datetime(raw)
    except (TypeError, ValueError):
        return None
    if retry_at.tzinfo is None:
        retry_at = retry_at.replace(tzinfo=datetime.UTC)
    return max(0.0, (retry_at - datetime.datetime.now(datetime.UTC)).total_seconds())


def _jittered(window: float) -> float:
    # Equal jitter: half the window fixed, half random, so concurrent workers
    # desynchronize instead of retrying in lockstep.
    return window / 2 + random.uniform(0.0, window / 2)


async def _post_with_retry(url: str, *, headers: dict[str, str], json: dict[str, Any] | None = None, data: dict[str, Any] | None = None, files: list | None = None) -> httpx.Response:
    """POST with automatic retry on transient HTTP errors and connection failures.

    429 responses are retried on a separate, longer budget and honor the
    server's Retry-After header when present.
    """
    last_exc: Exception | None = None
    transient_attempts = 0
    rate_limit_attempts = 0
    while True:
        rate_limited = False
        retry_after: float | None = None
        try:
            if files:
                response = await _http.post(url, headers=headers, data=data, files=files)
            else:
                response = await _http.post(url, headers=headers, json=json)
            if response.status_code not in _RETRYABLE_STATUS_CODES:
                return response
            rate_limited = response.status_code == 429
            retry_after = _retry_after_seconds(response)
            last_exc = httpx.HTTPStatusError(
                f"Server returned {response.status_code}",
                request=response.request,
                response=response,
            )
        except _TRANSPORT_ERRORS as exc:
            last_exc = exc
        if rate_limited:
            rate_limit_attempts += 1
            if rate_limit_attempts > _MAX_RATE_LIMIT_RETRIES:
                raise last_exc  # type: ignore[misc]
            if retry_after is not None:
                delay = retry_after + random.uniform(0.0, 1.0)
            else:
                delay = _jittered(
                    min(_RATE_LIMIT_BASE_DELAY * 2 ** (rate_limit_attempts - 1), _RATE_LIMIT_MAX_DELAY)
                )
            logger.warning(
                "Rate limited (429), waiting %.1fs before retry %d/%d",
                delay,
                rate_limit_attempts,
                _MAX_RATE_LIMIT_RETRIES,
            )
        else:
            transient_attempts += 1
            if transient_attempts > _MAX_RETRIES:
                raise last_exc  # type: ignore[misc]
            delay = _jittered(min(2.0 ** (transient_attempts - 1), 10.0))
        await asyncio.sleep(delay)


# Shared connection pool — LiteLLM runs as a local/nearby sidecar so keepalive
# connections give a meaningful speedup at high panel concurrency (50-200 images).
_http = httpx.AsyncClient(
    timeout=httpx.Timeout(connect=30, read=600, write=300, pool=5),
    limits=httpx.Limits(max_keepalive_connections=20, max_connections=100),
)


def _base_url(config: Config) -> str:
    if config.mock_mode and not mock_mode_active(config):
        raise RuntimeError(
            "mock_mode is enabled for this project but the server operator has not set "
            "CANARY_MOCK_GENERATIONS_ENABLED=true; refusing to fall back to paid models"
        )
    base_url = config.mock_model_base_url if config.mock_mode else config.litellm_base_url
    return base_url.rstrip("/")


def _headers(config: Config, event_id: str) -> dict[str, str]:
    headers = {"X-Canary-AI-Event-ID": event_id}
    if config.litellm_api_key:
        headers["Authorization"] = f"Bearer {config.litellm_api_key}"
    return headers


def _json_dumps(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _hash_payload(value: str | bytes) -> str:
    raw = value if isinstance(value, bytes) else value.encode("utf-8", errors="replace")
    return hashlib.sha256(raw).hexdigest()


def _payload_size(value: str | bytes) -> int:
    return len(value if isinstance(value, bytes) else value.encode("utf-8", errors="replace"))


def _redacted_params(params: dict[str, Any]) -> dict[str, Any]:
    redacted = dict(params)
    for key in ("prompt", "messages", "input", "image", "images"):
        redacted.pop(key, None)
    return redacted


def _content_summary(system_prompt: str | None = None, user_content: str | bytes | None = None) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    if system_prompt is not None:
        summary["system_prompt_sha256"] = _hash_payload(system_prompt)
        summary["system_prompt_bytes"] = _payload_size(system_prompt)
    if user_content is not None:
        summary["user_content_sha256"] = _hash_payload(user_content)
        summary["user_content_bytes"] = _payload_size(user_content)
        summary["user_content_type"] = "bytes" if isinstance(user_content, bytes) else "text"
    return summary


def _image_summary(refs: list[tuple[Path, bytes | None]]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for path, data in refs:
        if data is None:
            items.append({"name": path.name, "missing": True})
        else:
            items.append({
                "name": path.name,
                "bytes": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
            })
    return items


def _metadata(feature: str, operation: str, model_alias: str, event_id: str) -> dict[str, Any]:
    ctx = current_ai_request_context()
    tags = [ctx.stage, operation]
    return {
        "trace_name": feature,
        "generation_name": model_alias,
        "trace_id": ctx.request_id or event_id,
        "session_id": ctx.project_id or ctx.project_name or ctx.workspace_id,
        "user_id": ctx.user_id,
        "tags": [tag for tag in tags if tag],
        "metadata": {
            "event_id": event_id,
            "model_alias": model_alias,
            "feature": feature,
            "operation": operation,
            "project_name": ctx.project_name,
            "project_id": ctx.project_id,
            "workspace_id": ctx.workspace_id,
            "stage": ctx.stage,
        },
    }


def _provider_from_model(model: str | None) -> str:
    if not model:
        return "litellm"
    lower = model.lower()
    if lower.startswith("reve"):
        return "reve"
    if "/" in lower:
        return lower.split("/", 1)[0]
    if lower.startswith("gemini"):
        return "gemini"
    if lower.startswith("claude"):
        return "anthropic"
    if lower.startswith("gpt") or lower.startswith("dall-e"):
        return "openai"
    # Bare gateway aliases (extract-fast, image-balanced, etc.) land here.
    return "litellm"


def _extract_response_cost(
    data: dict[str, Any],
    headers: httpx.Headers | None = None,
) -> tuple[float | None, str | None]:
    hidden = data.get("_hidden_params")
    if isinstance(hidden, dict):
        value = hidden.get("response_cost")
        if value is not None:
            return float(value), "litellm_response_cost"
    usage = data.get("usage")
    if isinstance(usage, dict):
        value = usage.get("cost") or usage.get("response_cost")
        if value is not None:
            return float(value), "litellm_usage_cost"
    value = data.get("response_cost") or data.get("cost")
    if value is not None:
        return float(value), "litellm_response_cost"
    # LiteLLM proxy returns cost in a response header — most reliable for HTTP calls.
    if headers is not None:
        raw = headers.get("x-litellm-response-cost")
        if raw is not None:
            try:
                return float(raw), "litellm_response_header"
            except (ValueError, TypeError):
                pass
    return None, None


def _extract_usage(
    data: dict[str, Any],
    event_id: str,
    model_alias: str,
    operation: str,
    headers: httpx.Headers | None = None,
) -> UsageRecord:
    usage = data.get("usage") or {}
    input_tokens = int(usage.get("prompt_tokens") or usage.get("input_tokens") or 0)
    output_tokens = int(usage.get("completion_tokens") or usage.get("output_tokens") or 0)
    total_tokens = int(usage.get("total_tokens") or input_tokens + output_tokens)
    if not input_tokens and total_tokens and output_tokens:
        input_tokens = max(0, total_tokens - output_tokens)
    provider_model = str(data.get("model") or model_alias)
    image_count = 1 if operation == "image" else 0
    response_cost, response_cost_source = _extract_response_cost(data, headers)
    if provider_model == "canary-mock":
        response_cost = 0.0
        response_cost_source = "mock"
    return UsageRecord(
        call_id=event_id,
        provider=_provider_from_model(provider_model),
        model=model_alias,
        provider_model=provider_model,
        operation=operation,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        image_count=image_count,
        cost_usd=response_cost,
        cost_source=response_cost_source,
    )


def _refusal_reason(data: dict[str, Any]) -> str | None:
    """The provider's refusal reason, or None if it did not refuse.

    Only inspects provider-specific refusal fields, not the full payload — broad
    substring matching produces false positives on story content (e.g. a character
    named "Safety" or a scene where someone is "blocked").
    """
    choices = data.get("choices") or []
    if choices:
        choice = choices[0]
        if choice.get("finish_reason") == "content_filter":
            return "finish_reason=content_filter"
        message = choice.get("message") or {}
        if message.get("refusal"):
            return f"message.refusal={str(message['refusal'])[:120]!r}"
    error = data.get("error") or {}
    if isinstance(error, dict):
        code = str(error.get("code") or "").lower()
        if code in {"content_policy_violation", "content_filter", "policy_violation"}:
            return f"error.code={code}"
    return None


def _is_refusal(data: dict[str, Any]) -> bool:
    return _refusal_reason(data) is not None


def _gateway_http_error(
    response: httpx.Response,
    *,
    feature: str,
    model: str,
    endpoint: str,
) -> AITransportError:
    """Build a bounded, useful error without echoing arbitrary response data."""
    detail = ""
    try:
        body = response.json()
    except Exception:
        body = None
    if isinstance(body, dict):
        error = body.get("error")
        if isinstance(error, dict) and isinstance(error.get("message"), str):
            detail = error["message"]
        elif isinstance(body.get("detail"), str):
            detail = body["detail"]
        elif isinstance(body.get("message"), str):
            detail = body["message"]
    detail = " ".join(detail.split())[:800]
    suffix = f" — {detail}" if detail else ""
    return AITransportError(
        f"AI gateway request failed for {feature} "
        f"(model={model}, endpoint={endpoint}): "
        f"{response.status_code} {response.reason_phrase}{suffix}",
        phase="gateway_request",
        response=response,
    )


def _gateway_transport_error(
    exc: BaseException,
    *,
    feature: str,
    model: str,
    endpoint: str,
) -> AITransportError:
    return AITransportError(
        f"AI gateway request failed for {feature} "
        f"(model={model}, endpoint={endpoint}): transport {type(exc).__name__} "
        f"after {_MAX_RETRIES + 1} attempts",
        phase="gateway_request",
    )


def _error_json(exc: BaseException | None = None, response: httpx.Response | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    if response is not None:
        payload["status_code"] = response.status_code
        payload["body"] = response.text[:2000]
    if exc is not None:
        payload["exception"] = type(exc).__name__
    return payload


def _should_bill_failed(config: Config, usage: UsageRecord | None) -> bool:
    if config.ai_bill_failed_requests == "never":
        return False
    return usage is not None and usage_has_billable_activity(usage)


def _insert_event(
    *,
    event_id: str,
    model_alias: str,
    feature: str,
    operation: str,
    params_json: dict[str, Any],
    request_summary_json: dict[str, Any],
    metadata_json: dict[str, Any],
    estimated_cost_usd: float | None = None,
) -> None:
    ctx = current_ai_request_context()
    try:
        from novel_to_comic.server.db import get_db

        get_db().table("ai_usage_events").insert({
            "id": event_id,
            "user_id": ctx.user_id,
            "project_id": ctx.project_id,
            "workspace_id": ctx.workspace_id,
            "project_name": ctx.project_name,
            "stage": ctx.stage,
            "feature": feature,
            "operation": operation,
            "status": "started",
            "model_alias": model_alias,
            "request_id": ctx.request_id,
            "params_json": params_json,
            "request_summary_json": request_summary_json,
            "metadata_json": metadata_json,
            "estimated_cost_usd": estimated_cost_usd,
        }).execute()
    except Exception as exc:
        logger.warning("ai_usage_events insert failed for %s: %s", event_id, exc)


def _finalize_event(
    *,
    event_id: str,
    status: str,
    feature: str,
    model_alias: str,
    latency_ms: int,
    usage: UsageRecord | None = None,
    response_data: dict[str, Any] | None = None,
    error: BaseException | None = None,
    error_response: httpx.Response | None = None,
    config: Config | None = None,
    operation: str = "text",
    metadata: dict[str, Any] | None = None,
    estimated_cost_usd: float | None = None,
    langfuse_input: Any = None,
    langfuse_output: Any = None,
    started_at: datetime.datetime | None = None,
) -> None:
    provider_model = str((response_data or {}).get("model") or (usage.provider_model if usage else None) or model_alias)
    cost = calculate_cost_breakdown(usage) if usage is not None else None
    cost_usd = cost.cost_usd if cost is not None else None
    billable = bool(
        usage
        and usage_has_billable_activity(usage)
        and (status == "succeeded" or (config is not None and _should_bill_failed(config, usage)))
    )
    try:
        from novel_to_comic.server.metrics import record_ai_call

        request_context = current_ai_request_context()
        response_usage = (response_data or {}).get("usage") or {}
        completion_details = response_usage.get("completion_tokens_details") or {}
        reasoning_tokens = int(completion_details.get("reasoning_tokens") or 0)
        record_ai_call(
            provider=usage.provider if usage else _provider_from_model(provider_model),
            model=model_alias,
            operation=operation,
            status=status,
            stage=request_context.stage,
            cost_usd=cost_usd,
            input_tokens=usage.input_tokens if usage else 0,
            output_tokens=usage.output_tokens if usage else 0,
            reasoning_tokens=reasoning_tokens,
        )
        if (
            request_context.stage == "plan"
            and usage is not None
            and usage.output_tokens > 0
            and reasoning_tokens / usage.output_tokens >= 0.25
        ):
            logger.warning(
                "High plan reasoning-token ratio model=%s reasoning=%d output=%d ratio=%.2f",
                model_alias,
                reasoning_tokens,
                usage.output_tokens,
                reasoning_tokens / usage.output_tokens,
            )
    except Exception:
        # Metrics are optional and must not interfere with usage settlement.
        pass
    update: dict[str, Any] = {
        "finished_at": datetime.datetime.now(datetime.UTC).isoformat(),
        "status": status,
        "billable": billable,
        "billing_policy": config.ai_bill_failed_requests if config else None,
        "provider": usage.provider if usage else _provider_from_model(provider_model),
        "provider_model": provider_model,
        "litellm_model": provider_model,
        "provider_response_id": (response_data or {}).get("id"),
        "input_tokens": usage.input_tokens if usage else 0,
        "output_tokens": usage.output_tokens if usage else 0,
        "total_tokens": (usage.input_tokens + usage.output_tokens) if usage else 0,
        "image_count": usage.image_count if usage else 0,
        "latency_ms": latency_ms,
        "cost_usd": cost_usd,
        "cost_source": cost.source if cost is not None else None,
        "provider_cost_usd": usage.cost_usd if usage else None,
        "estimated_cost_usd": estimated_cost_usd,
        "pricing_snapshot": cost.pricing_snapshot if cost is not None else None,
        "usage_json": (response_data or {}).get("usage") or {},
        "error_type": type(error).__name__ if error else None,
        "error_message": str(error)[:1000] if error else None,
        "error_json": _error_json(error, error_response),
    }
    drift_pct = _pricing_estimate_drift_pct(
        operation=operation,
        estimated_cost_usd=estimated_cost_usd,
        usage=usage,
    )
    if drift_pct is not None:
        update["metadata_json"] = {
            **(metadata or {}),
            "pricing_estimate_drift_pct": drift_pct,
        }
        logger.info(
            "pricing_estimate_drift_pct model_alias=%s provider_model=%s drift_pct=%.2f estimated_cost_usd=%.6f actual_cost_usd=%.6f",
            model_alias,
            provider_model,
            drift_pct,
            estimated_cost_usd,
            usage.cost_usd if usage else 0.0,
        )
    try:
        from novel_to_comic.server.db import get_db

        get_db().table("ai_usage_events").update(update).eq("id", event_id).execute()
    except Exception as exc:
        logger.warning("ai_usage_events update failed for %s: %s", event_id, exc)
        return
    if billable and usage is not None:
        _settle_event_usage(usage, feature=feature, status=status)
    if status != "cancelled" and metadata is not None:
        _log_langfuse_generation(
            metadata=metadata,
            feature=feature,
            operation=operation,
            model_alias=model_alias,
            provider_model=provider_model,
            status=status,
            generation_id=event_id,
            input_payload=langfuse_input,
            output_payload=langfuse_output,
            usage=usage,
            cost_usd=cost_usd,
            pricing_estimate_drift_pct=drift_pct,
            start_time=started_at or datetime.datetime.now(datetime.UTC),
            end_time=datetime.datetime.now(datetime.UTC),
            error=error,
        )


def _truncate_for_log(text: str, max_chars: int = 4000) -> str:
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + f"... [+{len(text) - max_chars} chars]"


def _langfuse_endpoint() -> tuple[str, str] | None:
    public = os.environ.get("LANGFUSE_PUBLIC_KEY")
    secret = os.environ.get("LANGFUSE_SECRET_KEY")
    host = os.environ.get("CANARY_LANGFUSE_HOST") or os.environ.get("LANGFUSE_HOST")
    if not (public and secret and host):
        return None
    auth = base64.b64encode(f"{public}:{secret}".encode()).decode()
    return host.rstrip("/"), auth


def _pricing_estimate_drift_pct(
    *,
    operation: str,
    estimated_cost_usd: float | None,
    usage: UsageRecord | None,
) -> float | None:
    if operation != "image" or estimated_cost_usd is None or estimated_cost_usd <= 0:
        return None
    if usage is None or usage.cost_usd is None:
        return None
    return ((float(usage.cost_usd) - float(estimated_cost_usd)) / float(estimated_cost_usd)) * 100.0


async def _post_langfuse_batch(host: str, auth: str, batch: list[dict[str, Any]]) -> None:
    try:
        await _http.post(
            f"{host}/api/public/ingestion",
            headers={
                "Authorization": f"Basic {auth}",
                "Content-Type": "application/json",
            },
            json={"batch": batch},
        )
    except Exception as exc:
        logger.warning("Langfuse ingestion failed: %s", exc)


def _log_langfuse_generation(
    *,
    metadata: dict[str, Any] | None,
    feature: str,
    operation: str,
    model_alias: str,
    provider_model: str,
    status: str,
    generation_id: str,
    input_payload: Any,
    output_payload: Any,
    usage: UsageRecord | None,
    cost_usd: float | None,
    start_time: datetime.datetime,
    end_time: datetime.datetime,
    pricing_estimate_drift_pct: float | None = None,
    error: BaseException | None = None,
) -> None:
    """Send one generation observation (and its trace) to Langfuse via REST.

    Replaces LiteLLM's built-in langfuse callback so we control input/output
    formatting (especially for image endpoints, where prompt/output don't fit
    the chat-completion shape LiteLLM assumes).
    """
    endpoint = _langfuse_endpoint()
    if endpoint is None or metadata is None:
        return
    host, auth = endpoint
    trace_id = metadata.get("trace_id") or generation_id
    tags = [tag for tag in (metadata.get("tags") or []) if tag]

    usage_details: dict[str, int] = {}
    if usage is not None:
        usage_details = {
            "input": int(usage.input_tokens or 0),
            "output": int(usage.output_tokens or 0),
            "total": int((usage.input_tokens or 0) + (usage.output_tokens or 0)),
        }
        if usage.image_count:
            usage_details["images"] = int(usage.image_count)

    cost_details: dict[str, float] = {}
    if cost_usd is not None:
        cost_details["total"] = float(cost_usd)

    obs_metadata = {
        "operation": operation,
        "feature": feature,
        "status": status,
        **(metadata.get("metadata") or {}),
    }
    if error is not None:
        obs_metadata["error_type"] = type(error).__name__
        obs_metadata["error_message"] = str(error)[:500]
    if pricing_estimate_drift_pct is not None:
        obs_metadata["pricing_estimate_drift_pct"] = pricing_estimate_drift_pct

    now = datetime.datetime.now(datetime.UTC).isoformat()
    batch = [
        {
            "id": str(uuid.uuid4()),
            "type": "trace-create",
            "timestamp": now,
            "body": {
                "id": trace_id,
                "name": metadata.get("trace_name") or feature,
                "sessionId": metadata.get("session_id"),
                "userId": metadata.get("user_id"),
                "tags": tags,
                "metadata": metadata.get("metadata") or {},
                "timestamp": start_time.isoformat(),
                "input": input_payload,
                "output": output_payload,
            },
        },
        {
            "id": str(uuid.uuid4()),
            "type": "generation-create",
            "timestamp": now,
            "body": {
                "id": generation_id,
                "traceId": trace_id,
                "name": metadata.get("generation_name") or model_alias,
                "model": provider_model or model_alias,
                "input": input_payload,
                "output": output_payload,
                "usageDetails": usage_details,
                "costDetails": cost_details,
                "metadata": obs_metadata,
                "startTime": start_time.isoformat(),
                "endTime": end_time.isoformat(),
                "level": "DEFAULT" if status == "succeeded" else "ERROR",
                "statusMessage": (str(error)[:500] if error else None) if status != "succeeded" else None,
            },
        },
    ]
    if pricing_estimate_drift_pct is not None:
        batch.append(
            {
                "id": str(uuid.uuid4()),
                "type": "score-create",
                "timestamp": now,
                "body": {
                    "traceId": trace_id,
                    "observationId": generation_id,
                    "name": "pricing_estimate_drift_pct",
                    "value": float(pricing_estimate_drift_pct),
                    "dataType": "NUMERIC",
                    "comment": f"model_alias={model_alias}",
                },
            }
        )

    try:
        asyncio.create_task(_post_langfuse_batch(host, auth, batch))
    except RuntimeError:
        # No running loop (synchronous test context, etc.); skip silently.
        pass


def _settle_event_usage(usage: UsageRecord, *, feature: str, status: str) -> None:
    """Debit the credit ledger for one AI call as soon as it finishes.

    Settling per-call (rather than at end-of-stage) means a server crash mid-stage
    only loses the in-flight request — every API call that returned has already
    been charged. The upsert is idempotent on usage_call_id so duplicate debits
    from upstream callers collapse to a single ledger row.
    """
    ctx = current_ai_request_context()
    if not ctx.user_id:
        return
    if status == "succeeded":
        description = f"Model call: {feature}"
    else:
        description = f"Model call {status}: {feature}"
    try:
        from novel_to_comic.server.credits import debit_model_usage
        from novel_to_comic.server.db import get_db

        debit_model_usage(
            get_db(),
            ctx.user_id,
            ctx.project_id,
            usage,
            stage=ctx.stage,
            description=description,
            job_id=ctx.job_id,
        )
    except Exception:
        # The provider was already charged for this call, so we must not fail
        # the user's request — but a dropped debit is a direct margin leak
        # (user gets the output, platform eats the cost). Log at error level
        # with enough detail to reconcile manually; operator should alert on
        # this logger path (canary.ai, "Credit debit failed").
        logger.error(
            "Credit debit failed — provider was charged but user %s was not "
            "debited for %s call_id=%s model=%s cost_usd=%.6f",
            ctx.user_id,
            feature,
            getattr(usage, "call_id", None),
            getattr(usage, "model", None),
            getattr(usage, "cost_usd", 0.0) or 0.0,
            exc_info=True,
        )
        try:
            from novel_to_comic.server.metrics import increment

            increment(
                "canary_credit_debit_failures_total",
                stage=ctx.stage or "none",
            )
        except Exception:
            pass
        return


async def generate_text(
    *,
    config: Config,
    model: str,
    system_prompt: str,
    user_content: str,
    temperature: float = 0.7,
    max_output_tokens: int | None = None,
    feature: str = "text.generate",
) -> ApiResult[str]:
    data = await _chat_completion(
        config=config,
        model=model,
        system_prompt=system_prompt,
        user_content=user_content,
        temperature=temperature,
        max_output_tokens=max_output_tokens,
        json_mode=False,
        feature=feature,
    )
    return ApiResult(value=data["text"], usage=data["usage"])


def _strip_code_fence(text: str) -> str:
    if not text.strip().startswith("```"):
        return text
    lines = text.strip().split("\n")
    return "\n".join(lines[1:-1])


def _format_json_parse_failure(
    exc: json.JSONDecodeError,
    raw_text: str,
    model: str,
    feature: str,
    attempts: int,
) -> ValueError:
    pos = exc.pos
    start = max(0, pos - 120)
    end = min(len(raw_text), pos + 120)
    prefix = "..." if start > 0 else ""
    suffix = "..." if end < len(raw_text) else ""
    snippet = raw_text[start:end].replace("\n", "\\n")
    return ValueError(
        f"LiteLLM ({model}) returned malformed JSON after {attempts} attempt(s) "
        f"for {feature}: {exc.msg} at line {exc.lineno} column {exc.colno} "
        f"(char {pos}). Context: {prefix}{snippet}{suffix}"
    )


async def generate_structured_object(
    *,
    config: Config,
    model: str,
    system_prompt: str,
    user_content: str | bytes,
    temperature: float = 0.7,
    max_output_tokens: int | None = None,
    json_schema: dict[str, Any] | None = None,
    feature: str = "text.generate_json",
    image_attachments: tuple[tuple[bytes, str], ...] = (),
) -> ApiResult[dict]:
    if isinstance(user_content, bytes):
        raise ValueError(
            "Image-based PDFs are not supported by the LiteLLM gateway path. "
            "Extract text locally or add OCR preprocessing before Stage 1."
        )
    base_user_content = user_content
    attempt_user_content = user_content
    last_exc: json.JSONDecodeError | None = None
    last_text: str = ""
    for attempt in range(_JSON_PARSE_MAX_RETRIES + 1):
        data = await _chat_completion(
            config=config,
            model=model,
            system_prompt=system_prompt,
            user_content=attempt_user_content,
            temperature=temperature,
            max_output_tokens=max_output_tokens,
            json_mode=True,
            json_schema=json_schema,
            feature=feature,
            image_attachments=image_attachments,
        )
        text = _strip_code_fence(data["text"])
        try:
            return ApiResult(value=json.loads(text), usage=data["usage"])
        except json.JSONDecodeError as exc:
            last_exc = exc
            last_text = text
            logger.warning(
                "JSON parse failed for %s (model=%s) on attempt %d/%d: %s at char %d",
                feature,
                model,
                attempt + 1,
                _JSON_PARSE_MAX_RETRIES + 1,
                exc.msg,
                exc.pos,
            )
            if attempt < _JSON_PARSE_MAX_RETRIES:
                limit_note = ""
                if str(data.get("finish_reason") or "").lower() in {
                    "length", "max_tokens", "max_token", "max_output_tokens"
                }:
                    limit_note = (
                        " Your previous response reached the output token limit; "
                        "use shorter field values so the complete object fits."
                    )
                attempt_user_content = (
                    f"{base_user_content}\n\n"
                    "Your previous response was not valid JSON. Return a fresh, complete "
                    "JSON object with no markdown or commentary."
                    f"{limit_note} JSON parser error: {exc.msg} at character {exc.pos}."
                )
    assert last_exc is not None  # loop runs at least once
    raise _format_json_parse_failure(
        last_exc, last_text, model, feature, _JSON_PARSE_MAX_RETRIES + 1
    ) from last_exc


async def _chat_completion(
    *,
    config: Config,
    model: str,
    system_prompt: str,
    user_content: str,
    temperature: float,
    max_output_tokens: int | None,
    json_mode: bool,
    feature: str,
    json_schema: dict[str, Any] | None = None,
    image_attachments: tuple[tuple[bytes, str], ...] = (),
) -> dict[str, Any]:
    event_id = str(uuid.uuid4())
    operation = "text"
    metadata = _metadata(feature, operation, model, event_id)
    response_format: dict[str, Any] | None
    if json_schema:
        response_format = {"type": "json_schema", "json_schema": json_schema}
    elif json_mode:
        response_format = {"type": "json_object"}
    else:
        response_format = None
    effective_system = system_prompt
    if json_mode and "json" not in (system_prompt + user_content).lower():
        effective_system += "\n\nRespond with valid JSON."
    # An image-reading call keeps ``user_content`` as its text part so cost
    # estimation, request summaries, and Langfuse logging stay comparable with
    # text-only calls; only the wire message becomes multimodal.
    message_content: str | list[dict[str, Any]] = user_content
    if image_attachments:
        message_content = [{"type": "text", "text": user_content}]
        for image_bytes, media_type in image_attachments:
            encoded = base64.b64encode(image_bytes).decode()
            message_content.append(
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{media_type};base64,{encoded}"},
                }
            )
    payload: dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": effective_system},
            {"role": "user", "content": message_content},
        ],
        "metadata": metadata,
    }
    if model not in _TEMPERATURE_DEPRECATED_ALIASES:
        payload["temperature"] = temperature
    if response_format is not None:
        payload["response_format"] = response_format
    if max_output_tokens is not None:
        payload["max_completion_tokens"] = max_output_tokens

    estimated_cost_usd = estimate_text_cost(model, effective_system + "\n" + user_content) or None
    _insert_event(
        event_id=event_id,
        model_alias=model,
        feature=feature,
        operation=operation,
        params_json=_redacted_params(payload),
        request_summary_json=_content_summary(effective_system, user_content),
        metadata_json=metadata,
        estimated_cost_usd=estimated_cost_usd,
    )
    started = time.perf_counter()
    started_at = datetime.datetime.now(datetime.UTC)
    langfuse_input = [
        {"role": "system", "content": _truncate_for_log(effective_system)},
        {"role": "user", "content": _truncate_for_log(user_content)},
    ]
    response: httpx.Response | None = None
    try:
        endpoint = "/v1/chat/completions"
        try:
            response = await _post_with_retry(
                f"{_base_url(config)}{endpoint}",
                headers=_headers(config, event_id),
                json=payload,
            )
        except httpx.HTTPStatusError as exc:
            raise _gateway_http_error(
                exc.response, feature=feature, model=model, endpoint=endpoint,
            ) from exc
        except _TRANSPORT_ERRORS as exc:
            raise _gateway_transport_error(
                exc, feature=feature, model=model, endpoint=endpoint,
            ) from exc
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise _gateway_http_error(
                response, feature=feature, model=model, endpoint=endpoint,
            ) from exc
        data = response.json()
        refusal = _refusal_reason(data)
        if refusal:
            raise AIRefusalError(f"AI request was refused by gateway/provider ({refusal})")
        choice = (data.get("choices") or [{}])[0]
        text = (choice.get("message") or {}).get("content")
        if not text:
            # Surface WHY it was empty so a safety block (finish_reason
            # content_filter/SAFETY) is distinguishable from thinking-budget
            # exhaustion (finish_reason length/MAX_TOKENS with high
            # completion_tokens). Otherwise every cause looks identical in logs.
            detail = f"finish_reason={choice.get('finish_reason')!r}"
            feedback = data.get("prompt_feedback") or choice.get("content_filter_results")
            if feedback:
                detail += f", feedback={feedback!r}"
            completion_tokens = (data.get("usage") or {}).get("completion_tokens")
            if completion_tokens is not None:
                detail += f", completion_tokens={completion_tokens}"
            raise ValueError(f"Empty response from LiteLLM ({model}; {detail})")
        usage = _extract_usage(data, event_id, model, operation, response.headers)
        if (
            not usage.input_tokens
            and not usage.output_tokens
            and usage.cost_source != "mock"
        ):
            usage = estimate_text_usage(
                provider=usage.provider,
                model=model,
                system_prompt=effective_system,
                user_content=user_content,
                output_text=text,
                call_id=event_id,
            )
        _finalize_event(
            event_id=event_id,
            status="succeeded",
            feature=feature,
            model_alias=model,
            latency_ms=int((time.perf_counter() - started) * 1000),
            usage=usage,
            response_data=data,
            config=config,
            operation=operation,
            metadata=metadata,
            estimated_cost_usd=estimated_cost_usd,
            langfuse_input=langfuse_input,
            langfuse_output=_truncate_for_log(text),
            started_at=started_at,
        )
        return {
            "text": text,
            "usage": usage,
            "finish_reason": choice.get("finish_reason"),
        }
    except asyncio.CancelledError as exc:
        _finalize_event(
            event_id=event_id,
            status="cancelled",
            feature=feature,
            model_alias=model,
            latency_ms=int((time.perf_counter() - started) * 1000),
            error=exc,
            error_response=response,
            config=config,
            operation=operation,
            metadata=metadata,
            estimated_cost_usd=estimated_cost_usd,
            langfuse_input=langfuse_input,
            started_at=started_at,
        )
        raise
    except AIRefusalError as exc:
        data = response.json() if response is not None and response.content else {}
        usage = _extract_usage(data, event_id, model, operation) if data else None
        _finalize_event(
            event_id=event_id,
            status="refused",
            feature=feature,
            model_alias=model,
            latency_ms=int((time.perf_counter() - started) * 1000),
            usage=usage,
            response_data=data,
            error=exc,
            error_response=response,
            config=config,
            operation=operation,
            metadata=metadata,
            estimated_cost_usd=estimated_cost_usd,
            langfuse_input=langfuse_input,
            started_at=started_at,
        )
        raise
    except Exception as exc:
        usage = None
        if config.ai_bill_failed_requests == "estimate_all" and response is not None:
            usage = estimate_text_usage(
                provider="litellm",
                model=model,
                system_prompt=effective_system,
                user_content=user_content,
                output_text="",
                call_id=event_id,
            )
        _finalize_event(
            event_id=event_id,
            status="failed",
            feature=feature,
            model_alias=model,
            latency_ms=int((time.perf_counter() - started) * 1000),
            usage=usage,
            error=exc,
            error_response=response,
            config=config,
            operation=operation,
            metadata=metadata,
            estimated_cost_usd=estimated_cost_usd,
            langfuse_input=langfuse_input,
            started_at=started_at,
        )
        raise


async def generate_wire_image(
    *, config: Config, wire: "ProviderWireRequest", output_path: Path,
    feature: str = "image.generate_wire",
) -> ApiResult[Path]:
    """Submit an immutable exact-wire request through the isolated adapter."""
    from novel_to_comic.ai.providers import selector
    from novel_to_comic.ai.providers.litellm_http import LitellmHttpProvider
    from novel_to_comic.provider_wire import materialize_wire_references

    if wire.execution_fingerprint != wire.recompute_execution_fingerprint():
        raise ValueError("ProviderWireRequest execution fingerprint mismatch")

    transport_wire = wire
    blobs = materialize_wire_references(transport_wire)
    ref_reads = [
        (Path(ref.source_path), data)
        for ref, data in zip(transport_wire.references, blobs, strict=True)
    ]
    provider = selector.pick(transport_wire.requested_alias or "", config)
    if isinstance(provider, LitellmHttpProvider):
        params, _files = provider.prepare_wire_request(transport_wire)
    else:
        raise ValueError(f"wire transport is not implemented for adapter {provider.name}")
    ctx = begin_image_call(
        config=config,
        model=transport_wire.requested_alias or transport_wire.configured_provider_model,
        feature=feature,
        prompt=transport_wire.prompt_parts[0],
        params=params,
        ref_reads=ref_reads,
    )
    try:
        raw = await provider.generate_wire(
            wire=transport_wire,
            config=config,
            event_id=ctx.event_id,
            metadata=ctx.metadata,
        )
        return await finalise_image_success(
            ctx=ctx, config=config,
            model=transport_wire.requested_alias or transport_wire.configured_provider_model,
            feature=feature, output_path=output_path, raw=raw,
        )
    except Exception as exc:
        finalise_image_failure(
            ctx=ctx, config=config,
            model=transport_wire.requested_alias or transport_wire.configured_provider_model,
            feature=feature, error=exc, error_response=getattr(exc, "response", None),
        )
        raise


def _diagnose_empty_image_response(data: dict[str, Any]) -> str:
    """Build a human-readable hint from a 200-OK image response that carries no image.

    Providers (notably Gemini via LiteLLM) sometimes return 200 with empty data
    instead of an error when a safety filter silently rejects the prompt. Look
    for the standard places that carry diagnostic crumbs and surface them so the
    user sees *why* — and so the failure classifier can route the message into
    the "provider_blocked" bucket when applicable.
    """
    crumbs: list[str] = []

    err = data.get("error")
    if isinstance(err, dict):
        msg = err.get("message") or err.get("error_message")
        if isinstance(msg, str) and msg.strip():
            crumbs.append(msg.strip())
        code = err.get("code") or err.get("type")
        if isinstance(code, str) and code.strip():
            crumbs.append(f"code={code.strip()}")

    choices = data.get("choices") or []
    if isinstance(choices, list) and choices:
        first_choice = choices[0] or {}
        reason = first_choice.get("finish_reason")
        if isinstance(reason, str) and reason.strip():
            crumbs.append(f"finish_reason={reason.strip()}")
        message = first_choice.get("message") or {}
        refusal = message.get("refusal") if isinstance(message, dict) else None
        if isinstance(refusal, str) and refusal.strip():
            crumbs.append(refusal.strip())

    candidates = data.get("candidates") or []
    if isinstance(candidates, list) and candidates:
        first_cand = candidates[0] or {}
        reason = first_cand.get("finish_reason") or first_cand.get("finishReason")
        if isinstance(reason, str) and reason.strip():
            crumbs.append(f"finish_reason={reason.strip()}")
        ratings = first_cand.get("safety_ratings") or first_cand.get("safetyRatings")
        if isinstance(ratings, list):
            blocked = [
                r.get("category") for r in ratings
                if isinstance(r, dict) and r.get("blocked")
            ]
            if blocked:
                crumbs.append(f"safety_ratings blocked: {', '.join(str(c) for c in blocked)}")

    pf = data.get("prompt_feedback") or data.get("promptFeedback")
    if isinstance(pf, dict):
        reason = pf.get("block_reason") or pf.get("blockReason")
        if isinstance(reason, str) and reason.strip():
            crumbs.append(f"block_reason={reason.strip()}")

    if not crumbs:
        return (
            "The image provider returned an empty response with no diagnostic info. "
            "This usually means the prompt was silently rejected by a safety filter, "
            "or the provider was temporarily unable to render the request."
        )
    return "The image provider returned no image — " + "; ".join(crumbs)


async def _decode_image_response(data: dict[str, Any]) -> bytes:
    items = data.get("data") or []
    if not items:
        raise ValueError(_diagnose_empty_image_response(data))
    first = items[0]
    if first.get("b64_json"):
        return base64.b64decode(first["b64_json"])
    if first.get("url"):
        response = await _http.get(first["url"])
        response.raise_for_status()
        return response.content
    raise ValueError(
        "The image provider returned a response with neither inline image data nor a URL "
        "to download. This is an unexpected provider response format."
    )
