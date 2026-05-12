"""LiteLLM-backed internal AI client."""

from __future__ import annotations

import asyncio
import base64
import datetime
import hashlib
import json
import logging
import os
import time
import uuid
from pathlib import Path
from typing import Any

import httpx

from novel_to_comic.ai.context import current_ai_request_context
from novel_to_comic.config import Config, is_gpt_image_2
from novel_to_comic.usage import (
    ApiResult,
    UsageRecord,
    calculate_cost_breakdown,
    estimate_image_cost,
    estimate_text_cost,
    estimate_text_usage,
    usage_has_billable_activity,
)

logger = logging.getLogger("canary.ai")

_RETRYABLE_STATUS_CODES = {429, 502, 503, 504}
_MAX_RETRIES = 3

# Anthropic deprecated the `temperature` request param on Claude Opus 4.7;
# sending it returns 400. Haiku 4.5 / Sonnet 4.6 still accept it.
_TEMPERATURE_DEPRECATED_ALIASES = frozenset({"screenplay-quality"})


async def _post_with_retry(url: str, *, headers: dict[str, str], json: dict[str, Any] | None = None, data: dict[str, Any] | None = None, files: list | None = None) -> httpx.Response:
    """POST with automatic retry on transient HTTP errors and connection failures."""
    last_exc: Exception | None = None
    for attempt in range(_MAX_RETRIES + 1):
        try:
            if files:
                response = await _http.post(url, headers=headers, data=data, files=files)
            else:
                response = await _http.post(url, headers=headers, json=json)
            if response.status_code not in _RETRYABLE_STATUS_CODES:
                return response
            last_exc = httpx.HTTPStatusError(
                f"Server returned {response.status_code}",
                request=response.request,
                response=response,
            )
        except (httpx.ConnectError, httpx.ReadError, httpx.WriteError, httpx.PoolTimeout) as exc:
            last_exc = exc
        if attempt < _MAX_RETRIES:
            await asyncio.sleep(min(2 ** attempt, 10))
    raise last_exc  # type: ignore[misc]


# Shared connection pool — LiteLLM runs as a local/nearby sidecar so keepalive
# connections give a meaningful speedup at high panel concurrency (50-200 images).
_http = httpx.AsyncClient(
    timeout=httpx.Timeout(connect=30, read=600, write=300, pool=5),
    limits=httpx.Limits(max_keepalive_connections=20, max_connections=100),
)


class AIRefusalError(RuntimeError):
    """Raised when LiteLLM/provider reports a safety or policy refusal."""


def _base_url(config: Config) -> str:
    return config.litellm_base_url.rstrip("/")


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
    # LiteLLM proxy returns cost in a response header — most reliable for HTTP calls.
    if headers is not None:
        raw = headers.get("x-litellm-response-cost")
        if raw is not None:
            try:
                return float(raw), "litellm_response_header"
            except (ValueError, TypeError):
                pass
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


def _is_refusal(data: dict[str, Any]) -> bool:
    # Only inspect provider-specific refusal fields, not the full payload — broad
    # substring matching produces false positives on story content (e.g. a character
    # named "Safety" or a scene where someone is "blocked").
    choices = data.get("choices") or []
    if choices:
        choice = choices[0]
        if choice.get("finish_reason") == "content_filter":
            return True
        message = choice.get("message") or {}
        if message.get("refusal"):
            return True
    error = data.get("error") or {}
    if isinstance(error, dict):
        code = str(error.get("code") or "").lower()
        if code in {"content_policy_violation", "content_filter", "policy_violation"}:
            return True
    return False


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
) -> ApiResult[dict]:
    if isinstance(user_content, bytes):
        raise ValueError(
            "Image-based PDFs are not supported by the LiteLLM gateway path. "
            "Extract text locally or add OCR preprocessing before Stage 1."
        )
    data = await _chat_completion(
        config=config,
        model=model,
        system_prompt=system_prompt,
        user_content=user_content,
        temperature=temperature,
        max_output_tokens=max_output_tokens,
        json_mode=True,
        json_schema=json_schema,
        feature=feature,
    )
    text = data["text"]
    if text.strip().startswith("```"):
        lines = text.strip().split("\n")
        text = "\n".join(lines[1:-1])
    return ApiResult(value=json.loads(text), usage=data["usage"])


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
    payload: dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": effective_system},
            {"role": "user", "content": user_content},
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
        response = await _post_with_retry(
            f"{_base_url(config)}/v1/chat/completions",
            headers=_headers(config, event_id),
            json=payload,
        )
        response.raise_for_status()
        data = response.json()
        if _is_refusal(data):
            raise AIRefusalError("AI request was refused by gateway/provider")
        text = (data.get("choices") or [{}])[0].get("message", {}).get("content")
        if not text:
            raise ValueError(f"Empty response from LiteLLM ({model})")
        usage = _extract_usage(data, event_id, model, operation, response.headers)
        if not usage.input_tokens and not usage.output_tokens:
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
        return {"text": text, "usage": usage}
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


async def generate_image(
    *,
    config: Config,
    model: str,
    prompt: str,
    output_path: Path,
    width: int,
    height: int,
    steps: int | None = None,
    reference_paths: list[Path] | None = None,
    style_refs: list[Path] | None = None,
    feature: str = "image.generate",
) -> ApiResult[Path]:
    event_id = str(uuid.uuid4())
    operation = "image"
    ref_paths = [path for path in [*(reference_paths or []), *(style_refs or [])] if path]

    # Read reference files once — bytes are reused for the audit summary and upload.
    ref_reads: list[tuple[Path, bytes | None]] = []
    for ref in ref_paths:
        try:
            data = await asyncio.to_thread(ref.read_bytes)
            ref_reads.append((ref, data))
        except OSError:
            ref_reads.append((ref, None))
    ref_data = [(p, d) for p, d in ref_reads if d is not None]

    metadata = _metadata(feature, operation, model, event_id)
    # Keep this payload to the OpenAI-compatible image API surface. Provider-
    # specific controls such as diffusion steps belong in LiteLLM config; passing
    # them through aliases can make the proxy fail before the provider responds.
    params = {
        "model": model,
        "size": _image_size(model, width, height),
        "n": 1,
    }
    # if steps is not None:
    #     params["steps"] = steps
    if config.image_quality:
        params["quality"] = config.image_quality
    estimated_cost_usd = estimate_image_cost(
        model,
        1,
        quality=config.image_quality,
        ref_count=len(ref_data),
        prompt_text=prompt,
    ) or None
    _insert_event(
        event_id=event_id,
        model_alias=model,
        feature=feature,
        operation=operation,
        params_json=_redacted_params(params),
        request_summary_json={
            "prompt_sha256": _hash_payload(prompt),
            "prompt_bytes": _payload_size(prompt),
            "references": _image_summary(ref_reads),
        },
        metadata_json=metadata,
        estimated_cost_usd=estimated_cost_usd,
    )
    started = time.perf_counter()
    started_at = datetime.datetime.now(datetime.UTC)
    langfuse_input: dict[str, Any] = {
        "prompt": _truncate_for_log(prompt),
        "size": params.get("size"),
        "quality": params.get("quality"),
        "ref_count": len(ref_data),
        "references": _image_summary(ref_reads),
    }
    response: httpx.Response | None = None
    try:
        endpoint = "/v1/images/edits" if ref_data else "/v1/images/generations"
        if ref_data:
            files = [("image", (p.name, d, _mime_type(p))) for p, d in ref_data]
            form_params = {k: str(v) for k, v in params.items() if v is not None}
            response = await _post_with_retry(
                f"{_base_url(config)}{endpoint}",
                headers=_headers(config, event_id),
                data={"prompt": prompt, "metadata": _json_dumps(metadata), **form_params},
                files=files,
            )
        else:
            response = await _post_with_retry(
                f"{_base_url(config)}{endpoint}",
                headers=_headers(config, event_id),
                json={"prompt": prompt, "metadata": metadata, **{k: v for k, v in params.items() if v is not None}},
            )
        response.raise_for_status()
        data = response.json()
        if _is_refusal(data):
            raise AIRefusalError("AI image request was refused by gateway/provider")
        image_bytes = await _decode_image_response(data)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(output_path.write_bytes, image_bytes)
        usage = _extract_usage(data, event_id, model, operation, response.headers)
        langfuse_output = {
            "output_path": str(output_path),
            "image_bytes": len(image_bytes),
            "image_sha256": hashlib.sha256(image_bytes).hexdigest(),
            "size": params.get("size"),
        }
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
            langfuse_output=langfuse_output,
            started_at=started_at,
        )
        return ApiResult(value=output_path, usage=usage)
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
        usage = _extract_usage(data, event_id, model, operation, response.headers if response is not None else None) if data else None
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
            usage = UsageRecord(
                call_id=event_id,
                provider="litellm",
                model=model,
                operation="image",
                image_count=1,
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


def _valid_gpt_image_2_size(width: int, height: int) -> bool:
    if width <= 0 or height <= 0:
        return False
    if width % 16 != 0 or height % 16 != 0:
        return False
    if max(width, height) > 3840:
        return False
    if max(width, height) / min(width, height) > 3:
        return False
    pixels = width * height
    return 655_360 <= pixels <= 8_294_400


def _image_size(model: str, width: int, height: int) -> str:
    if is_gpt_image_2(model) and _valid_gpt_image_2_size(width, height):
        return f"{width}x{height}"

    # Thresholds map to the three OpenAI-supported sizes: portrait (1024×1536,
    # ratio≈0.67), square (1024×1024, ratio=1.0), landscape (1536×1024, ratio≈1.5).
    # 0.87 and 1.15 are the midpoints between those ratios.
    if height <= 0:
        return "1024x1024"
    ratio = width / height
    if ratio < 0.87:
        return "1024x1536"
    if ratio > 1.15:
        return "1536x1024"
    return "1024x1024"


def _mime_type(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in {".jpg", ".jpeg"}:
        return "image/jpeg"
    if suffix == ".webp":
        return "image/webp"
    return "image/png"


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
