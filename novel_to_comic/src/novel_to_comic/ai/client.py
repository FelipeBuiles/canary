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
import re
import time
import uuid
from collections.abc import Callable
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any

import httpx

from novel_to_comic.ai.codex_schema import strict_output_schema
from novel_to_comic.ai.anthropic_schema import anthropic_output_schema
from novel_to_comic.ai.context import (
    current_ai_request_context,
    current_stream_observer,
    notify_execution_started,
)
from novel_to_comic.ai.errors import AIEmptyResponseError, AIRefusalError, AITransportError
from novel_to_comic.ai.finalisation import (
    begin_image_call,
    finalise_image_cancelled,
    finalise_image_failure,
    finalise_image_success,
)
from novel_to_comic.config import Config, mock_mode_active
from novel_to_comic.codex_dev import CodexRoute, CodexRoutingError, is_subscription, route_for
from novel_to_comic.provider_wire import ProviderWireRequest
from novel_to_comic.text_models import text_wire
from novel_to_comic.model_costs import get_pricing_resolver
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
    # TimeoutException covers Connect/Read/Write/PoolTimeout. Without it a
    # ReadTimeout escapes _post_with_retry unretried *and* unwrapped, killing
    # the whole stage and discarding every sibling shard's completed work.
    httpx.TimeoutException,
)
# Read/write timeouts already burned the full read budget before raising, so
# each retry costs another ~10 minutes of wall clock and re-bills the
# completion. One retry rides out a wedged connection; more just stalls.
_SLOW_TIMEOUT_ERRORS = (httpx.ReadTimeout, httpx.WriteTimeout)
_MAX_TIMEOUT_RETRIES = 1
_MAX_RETRIES = 3
# Text completions stream, so _READ_TIMEOUT becomes a per-chunk idle budget
# rather than a cap on the whole generation. That removes the cliff where a long
# adapt repair blocks on one read until the read timeout fires, but it also
# means a slowly-trickling response could run forever — hence a separate
# wall-clock ceiling on the whole stream.
_READ_TIMEOUT = 600.0
_STREAM_TOTAL_TIMEOUT = 1800.0
# Keepalive comments and empty chunks reset the per-chunk read timeout, so a
# gateway that accepts the request but never produces output would otherwise
# ride the total budget. Bound inactivity before the first answer separately —
# above _READ_TIMEOUT, so this only fires when non-content bytes are actively
# masking a stall. Time-to-first-content is legitimately long here: an observed
# adapt treatment call spent ~520s before emitting just 2k output tokens, so a
# bound under the read timeout would kill healthy requests. Actual reasoning
# deltas count as generation progress, but never as the requested answer.
_STREAM_FIRST_CONTENT_TIMEOUT = 900.0


def _stream_text_enabled() -> bool:
    """Whether text completions stream. Set CANARY_AI_STREAM_TEXT=0 to opt out.

    Streaming is what lets a generation outlive the read timeout, so it is the
    default — but it is one env var away from off if it ever misbehaves against
    a provider mid-run.
    """
    raw = os.environ.get("CANARY_AI_STREAM_TEXT", "1").strip().lower()
    return raw not in {"0", "false", "no", "off"}
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


class _RetryPacer:
    """Backoff bookkeeping shared by the buffered and streaming POST paths.

    429s get their own, longer budget; read/write timeouts get a shorter one
    because each of those attempts already burned the full read budget.
    """

    def __init__(self) -> None:
        self.last_exc: Exception | None = None
        self._transient_attempts = 0
        self._rate_limit_attempts = 0

    def record_retryable_status(self, response: httpx.Response) -> None:
        self.last_exc = httpx.HTTPStatusError(
            f"Server returned {response.status_code}",
            request=response.request,
            response=response,
        )

    def record_exception(self, exc: Exception) -> None:
        self.last_exc = exc

    async def pause_or_raise(
        self,
        *,
        rate_limited: bool,
        retry_after: float | None = None,
        slow_timeout: bool = False,
    ) -> None:
        """Sleep before the next attempt, or re-raise once the budget is spent."""
        if rate_limited:
            self._rate_limit_attempts += 1
            if self._rate_limit_attempts > _MAX_RATE_LIMIT_RETRIES:
                raise self.last_exc  # type: ignore[misc]
            if retry_after is not None:
                delay = retry_after + random.uniform(0.0, 1.0)
            else:
                delay = _jittered(
                    min(
                        _RATE_LIMIT_BASE_DELAY * 2 ** (self._rate_limit_attempts - 1),
                        _RATE_LIMIT_MAX_DELAY,
                    )
                )
            logger.warning(
                "Rate limited (429), waiting %.1fs before retry %d/%d",
                delay,
                self._rate_limit_attempts,
                _MAX_RATE_LIMIT_RETRIES,
            )
        else:
            self._transient_attempts += 1
            budget = _MAX_TIMEOUT_RETRIES if slow_timeout else _MAX_RETRIES
            if self._transient_attempts > budget:
                raise self.last_exc  # type: ignore[misc]
            if slow_timeout:
                logger.warning(
                    "Request timed out (%s), retry %d/%d",
                    self.last_exc or type(self.last_exc).__name__,
                    self._transient_attempts,
                    budget,
                )
            delay = _jittered(min(2.0 ** (self._transient_attempts - 1), 10.0))
        await asyncio.sleep(delay)


async def _post_with_retry(
    url: str,
    *,
    headers: dict[str, str],
    json: dict[str, Any] | None = None,
    data: dict[str, Any] | None = None,
    files: list | None = None,
    retry_ambiguous: bool = True,
) -> httpx.Response:
    """POST with automatic retry on transient HTTP errors and connection failures.

    429 responses are retried on a separate, longer budget and honor the
    server's Retry-After header when present.
    """
    pacer = _RetryPacer()
    while True:
        rate_limited = False
        slow_timeout = False
        retry_after: float | None = None
        try:
            if files:
                response = await _http.post(
                    url, headers=headers, data=data, files=files
                )
            elif data is not None:
                response = await _http.post(url, headers=headers, data=data)
            else:
                response = await _http.post(url, headers=headers, json=json)
            if not retry_ambiguous and response.status_code >= 500:
                if not _fal_definitely_unsubmitted(response):
                    from novel_to_comic.server.credits import retain_ambiguous_job
                    retain_ambiguous_job(current_ai_request_context().job_id)
                return response
            if response.status_code not in _RETRYABLE_STATUS_CODES:
                return response
            rate_limited = response.status_code == 429
            retry_after = _retry_after_seconds(response)
            pacer.record_retryable_status(response)
        except asyncio.CancelledError:
            if not retry_ambiguous:
                from novel_to_comic.server.credits import retain_ambiguous_job
                retain_ambiguous_job(current_ai_request_context().job_id)
            raise
        except _TRANSPORT_ERRORS as exc:
            if not retry_ambiguous and not isinstance(exc, (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout)):
                from novel_to_comic.server.credits import retain_ambiguous_job
                retain_ambiguous_job(current_ai_request_context().job_id)
                raise AITransportError(
                    "Page submission outcome is unknown; it was not automatically repeated. "
                    "Check the provider result before requesting another paid generation.",
                    phase="ambiguous_submission",
                ) from exc
            pacer.record_exception(exc)
            slow_timeout = isinstance(exc, _SLOW_TIMEOUT_ERRORS)
        except httpx.RequestError as exc:
            if not retry_ambiguous:
                from novel_to_comic.server.credits import retain_ambiguous_job
                retain_ambiguous_job(current_ai_request_context().job_id)
                raise AITransportError(
                    "Image submission outcome is unknown; inspect provider evidence before retrying.",
                    phase="ambiguous_submission",
                ) from exc
            raise
        await pacer.pause_or_raise(
            rate_limited=rate_limited,
            retry_after=retry_after,
            slow_timeout=slow_timeout,
        )


def _fal_definitely_unsubmitted(response: httpx.Response) -> bool:
    """Recognize only FAL connection failures before its queue accepted a POST."""
    try:
        body = response.json()
    except (TypeError, ValueError):
        return False
    error = body.get("error") if isinstance(body, dict) else None
    message = error.get("message") if isinstance(error, dict) else None
    return isinstance(message, str) and bool(re.search(
        r"\bFal-queueException - FAL submit_connect failed for "
        r"[a-zA-Z0-9_./-]+; detail=(?:ConnectError|ConnectTimeout|PoolTimeout)\b",
        message,
    ))


# Top-level chunk fields worth keeping when collapsing a stream: cost extraction
# and refusal detection read these off the buffered body.
_STREAM_CARRIED_FIELDS = (
    "id",
    "object",
    "model",
    "system_fingerprint",
    "prompt_feedback",
    "prompt_filter_results",
    "error",
    "response_cost",
    "cost",
    "_hidden_params",
)


def _chunk_content_length(chunk: dict[str, Any]) -> int:
    choices = chunk.get("choices") or []
    if not choices:
        return 0
    content = (choices[0].get("delta") or {}).get("content")
    return len(content) if isinstance(content, str) else 0


def _chunk_has_reasoning(chunk: dict[str, Any]) -> bool:
    """Recognize substantive LiteLLM/OpenRouter reasoning, not role/keepalive events."""
    choices = chunk.get("choices") or []
    if not choices:
        return False
    delta = choices[0].get("delta") or {}
    if any(isinstance(delta.get(key), str) and delta[key].strip()
           for key in ("reasoning_content", "reasoning")):
        return True
    details = delta.get("reasoning_details")
    return isinstance(details, list) and any(
        isinstance(detail, dict) and any(
            isinstance(detail.get(key), str) and detail[key].strip()
            for key in ("text", "summary", "data")
        ) for detail in details
    )


def _collapse_chat_chunks(chunks: list[dict[str, Any]]) -> dict[str, Any]:
    """Reassemble streamed deltas into a non-streaming chat-completion body."""
    collapsed: dict[str, Any] = {}
    parts: list[str] = []
    finish_reason: str | None = None
    refusal: Any = None
    filter_results: Any = None
    stop_details: dict[str, Any] | None = None
    usage: dict[str, Any] = {}
    for chunk in chunks:
        if chunk.get("error") is not None:
            # HTTP 200 only acknowledges stream headers. An error can be the
            # first event or follow apparently complete JSON; never discard it.
            collapsed.setdefault("error", chunk["error"])
        for field in _STREAM_CARRIED_FIELDS:
            if chunk.get(field) is not None and field not in collapsed:
                collapsed[field] = chunk[field]
        if chunk.get("usage"):
            usage = chunk["usage"]
        choices = chunk.get("choices") or []
        if not choices:
            continue
        choice = choices[0]
        delta = choice.get("delta") or {}
        provider_fields = delta.get("provider_specific_fields") or {}
        if isinstance(provider_fields.get("stop_details"), dict):
            stop_details = provider_fields["stop_details"]
        if delta.get("content"):
            parts.append(str(delta["content"]))
        if delta.get("refusal"):
            refusal = (refusal or "") + str(delta["refusal"])
        if choice.get("finish_reason"):
            finish_reason = choice["finish_reason"]
        if choice.get("content_filter_results") and filter_results is None:
            filter_results = choice["content_filter_results"]
    message: dict[str, Any] = {"role": "assistant", "content": "".join(parts)}
    if refusal is not None:
        message["refusal"] = refusal
    if stop_details is not None:
        message["provider_specific_fields"] = {"stop_details": stop_details}
    rebuilt: dict[str, Any] = {
        "index": 0,
        "message": message,
        "finish_reason": finish_reason,
    }
    if filter_results is not None:
        rebuilt["content_filter_results"] = filter_results
    collapsed["choices"] = [rebuilt]
    if usage:
        collapsed["usage"] = usage
    return collapsed


async def _read_chat_stream(
    url: str,
    *,
    headers: dict[str, str],
    payload: dict[str, Any],
) -> tuple[dict[str, Any], httpx.Response]:
    """Run one streaming attempt, returning a buffered-shaped body plus response.

    Raises HTTPStatusError for retryable statuses; other error statuses come
    back fully read so the caller's raise_for_status/_gateway_http_error path
    can still inspect the body.
    """
    async with _http.stream("POST", url, headers=headers, json=payload) as response:
        if response.status_code >= 400:
            await response.aread()
            if response.status_code in _RETRYABLE_STATUS_CODES:
                raise httpx.HTTPStatusError(
                    f"Server returned {response.status_code}",
                    request=response.request,
                    response=response,
                )
            return {}, response
        chunks: list[dict[str, Any]] = []
        raw: list[str] = []
        observer = current_stream_observer()
        streamed_chars = 0
        dropped = 0
        opened = time.perf_counter()
        first_content_at: float | None = None
        last_progress_at = opened
        reasoning_events = 0
        stream_identity = (
            f"event_id={headers.get('X-Canary-AI-Event-ID', '-')} "
            f"model={payload.get('model', '-')} "
            f"scope={current_ai_request_context().source_scope or '-'}"
        )
        # `data:` lines accumulate until they parse, or until a blank line ends
        # the event. Dispatching as soon as the payload is valid JSON handles the
        # usual one-object-per-line shape even from a server that omits the
        # spec's blank-line separator; accumulating handles a genuinely
        # multi-line payload. A per-line parse would instead silently swallow
        # anything that didn't parse, leaving a hole in the reassembled text
        # that resurfaces as a JSON error far from its cause.
        event_data: list[str] = []

        def notify(chars: int) -> None:
            if observer is None:
                return
            # Never let progress reporting break a paid request.
            try:
                observer(chars)
            except Exception:
                logger.debug("stream observer raised", exc_info=True)

        def dispatch(blob: str) -> bool:
            """Consume one complete data payload; False if it isn't valid yet."""
            nonlocal streamed_chars, first_content_at, last_progress_at, reasoning_events
            if not blob or blob == "[DONE]":
                return True
            try:
                chunk = json.loads(blob)
            except ValueError:
                return False
            if not isinstance(chunk, dict):
                return False
            chunks.append(chunk)
            content_chars = _chunk_content_length(chunk)
            has_reasoning = _chunk_has_reasoning(chunk)
            if content_chars or has_reasoning:
                last_progress_at = time.perf_counter()
            if has_reasoning:
                reasoning_events += 1
                if reasoning_events == 1:
                    logger.info("Stream first reasoning after %.1fs %s",
                                last_progress_at - opened, stream_identity)
            if content_chars and first_content_at is None:
                first_content_at = last_progress_at
                logger.info(
                    "Stream first content after %.1fs (%d reasoning events) %s",
                    first_content_at - opened, reasoning_events, stream_identity,
                )
            streamed_chars += content_chars
            notify(streamed_chars)
            return True

        def end_event() -> None:
            nonlocal dropped
            if not event_data:
                return
            if not dispatch("\n".join(event_data)):
                dropped += 1
            event_data.clear()

        # Report before the first chunk so a stage waiting on a slow model shows
        # as in-flight rather than as a dead progress bar.
        notify(0)
        try:
            async with asyncio.timeout(_STREAM_TOTAL_TIMEOUT):
                async for line in response.aiter_lines():
                    line = line.rstrip("\r")
                    if not line:
                        end_event()
                    elif line.startswith("data:"):
                        event_data.append(line[len("data:") :].lstrip())
                        if dispatch("\n".join(event_data)):
                            event_data.clear()
                    elif line.startswith(":"):
                        pass  # Keepalives must still pass the inactivity check.
                    else:
                        raw.append(line)
                    if (
                        first_content_at is None
                        and time.perf_counter() - last_progress_at
                        > _STREAM_FIRST_CONTENT_TIMEOUT
                    ):
                        raise httpx.ReadTimeout(
                            "no answer or reasoning progress for "
                            f"{_STREAM_FIRST_CONTENT_TIMEOUT:.0f}s before first content "
                            f"({len(chunks)} events, {reasoning_events} reasoning events); "
                            + stream_identity,
                            request=response.request,
                        )
                end_event()
        except TimeoutError as exc:
            raise httpx.ReadTimeout(
                f"stream exceeded its {_STREAM_TOTAL_TIMEOUT:.0f}s total budget "
                f"({streamed_chars} answer chars, {reasoning_events} reasoning events); "
                + stream_identity,
                request=response.request,
            ) from exc
        if dropped:
            logger.warning(
                "Dropped %d unparsable stream event(s); reassembled text may "
                "have holes",
                dropped,
            )
        if not chunks:
            # A gateway that ignores `stream` answers with a buffered body; use
            # it rather than reporting an empty completion.
            try:
                buffered = json.loads("".join(raw))
            except ValueError:
                buffered = None
            if isinstance(buffered, dict) and (buffered.get("choices") or buffered.get("error") is not None):
                return buffered, response
        collapsed = _collapse_chat_chunks(chunks)
        # Carried so a downstream JSON parse failure can say whether the text
        # arrived intact. Private prefix: not a provider field.
        collapsed["_canary_stream"] = {
            "events": len(chunks), "dropped": dropped, "reasoning_events": reasoning_events,
        }
        return collapsed, response


async def _stream_with_retry(
    url: str,
    *,
    headers: dict[str, str],
    payload: dict[str, Any],
    retry_ambiguous: bool = True,
) -> tuple[dict[str, Any], httpx.Response]:
    """Streaming counterpart to _post_with_retry, with the same retry budgets."""
    pacer = _RetryPacer()
    while True:
        rate_limited = False
        slow_timeout = False
        retry_after: float | None = None
        try:
            return await _read_chat_stream(url, headers=headers, payload=payload)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code != 429 and (
                not retry_ambiguous or exc.response.status_code not in _RETRYABLE_STATUS_CODES
            ):
                if not retry_ambiguous and exc.response.status_code >= 500:
                    from novel_to_comic.server.credits import retain_ambiguous_job
                    retain_ambiguous_job(current_ai_request_context().job_id)
                raise
            rate_limited = exc.response.status_code == 429
            retry_after = _retry_after_seconds(exc.response)
            pacer.record_exception(exc)
        except _TRANSPORT_ERRORS as exc:
            if not retry_ambiguous and not isinstance(
                exc, (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout)
            ):
                from novel_to_comic.server.credits import retain_ambiguous_job
                retain_ambiguous_job(current_ai_request_context().job_id)
                raise AITransportError(
                    "Text submission outcome is unknown; it was not automatically repeated. "
                    "Check provider usage before requesting another paid call.",
                    phase="ambiguous_submission",
                ) from exc
            pacer.record_exception(exc)
            slow_timeout = isinstance(exc, _SLOW_TIMEOUT_ERRORS)
        except asyncio.CancelledError:
            if not retry_ambiguous:
                from novel_to_comic.server.credits import retain_ambiguous_job
                retain_ambiguous_job(current_ai_request_context().job_id)
            raise
        await pacer.pause_or_raise(
            rate_limited=rate_limited,
            retry_after=retry_after,
            slow_timeout=slow_timeout,
        )


# Shared connection pool — LiteLLM runs as a local/nearby sidecar so keepalive
# connections give a meaningful speedup at high panel concurrency (50-200 images).
_http = httpx.AsyncClient(
    timeout=httpx.Timeout(connect=30, read=_READ_TIMEOUT, write=300, pool=5),
    limits=httpx.Limits(max_keepalive_connections=20, max_connections=100),
)


def _base_url(config: Config) -> str:
    if config.mock_mode and not mock_mode_active(config):
        raise RuntimeError(
            "mock_mode is enabled for this project but the server operator has not set "
            "CANARY_MOCK_GENERATIONS_ENABLED=true; refusing to fall back to paid models"
        )
    base_url = (
        config.mock_model_base_url if config.mock_mode else config.litellm_base_url
    )
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
    return len(
        value if isinstance(value, bytes) else value.encode("utf-8", errors="replace")
    )


def _redacted_params(params: dict[str, Any]) -> dict[str, Any]:
    from .usage_payloads import compact_params

    return compact_params(params)


def _content_summary(
    system_prompt: str | None = None, user_content: str | bytes | None = None
) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    if system_prompt is not None:
        summary["system_prompt_sha256"] = _hash_payload(system_prompt)
        summary["system_prompt_bytes"] = _payload_size(system_prompt)
    if user_content is not None:
        summary["user_content_sha256"] = _hash_payload(user_content)
        summary["user_content_bytes"] = _payload_size(user_content)
        summary["user_content_type"] = (
            "bytes" if isinstance(user_content, bytes) else "text"
        )
    return summary


def _image_summary(refs: list[tuple[Path, bytes | None]]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for path, data in refs:
        if data is None:
            items.append({"name": path.name, "missing": True})
        else:
            items.append(
                {
                    "name": path.name,
                    "bytes": len(data),
                    "sha256": hashlib.sha256(data).hexdigest(),
                }
            )
    return items


def _metadata(
    feature: str, operation: str, model_alias: str, event_id: str
) -> dict[str, Any]:
    ctx = current_ai_request_context()
    tags = [ctx.stage, operation]
    return {
        "trace_name": feature,
        "generation_name": model_alias,
        "trace_id": ctx.request_id or event_id,
        "session_id": ctx.project_id or ctx.project_name or ctx.workspace_id,
        "user_id": ctx.user_id,
        "tags": [tag for tag in tags if tag],
        "page_number": ctx.page_number,
        "is_correction": ctx.is_correction,
        "metadata": {
            "event_id": event_id,
            "model_alias": model_alias,
            "feature": feature,
            "operation": operation,
            "project_name": ctx.project_name,
            "project_id": ctx.project_id,
            "workspace_id": ctx.workspace_id,
            "stage": ctx.stage,
            "source_scope": ctx.source_scope,
            "source_unit_ids": list(ctx.source_unit_ids),
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
    # Bare gateway aliases (gpt-6-luna, image-sunburst, etc.) land here.
    return "litellm"


def _extract_response_cost(
    data: dict[str, Any],
    headers: httpx.Headers | None = None,
) -> tuple[float | None, str | None]:
    # A custom gateway handler that knows the provider's actual charge (the
    # FAL billing event) reports it with its own source label.
    provider_cost = data.get("provider_cost_usd")
    if provider_cost is not None and data.get("provider_cost_source"):
        return float(provider_cost), str(data["provider_cost_source"])
    hidden = data.get("_hidden_params")
    if isinstance(hidden, dict):
        value = hidden.get("response_cost")
        if value is not None:
            return float(value), "litellm_response_cost"
    usage = data.get("usage")
    if isinstance(usage, dict):
        value = usage.get("cost") if usage.get("cost") is not None else usage.get("response_cost")
        if value is not None:
            return float(value), "litellm_usage_cost"
    value = data.get("response_cost") if data.get("response_cost") is not None else data.get("cost")
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
    output_tokens = int(
        usage.get("completion_tokens") or usage.get("output_tokens") or 0
    )
    total_tokens = int(usage.get("total_tokens") or input_tokens + output_tokens)
    if not input_tokens and total_tokens and output_tokens:
        input_tokens = max(0, total_tokens - output_tokens)
    provider_model = str(data.get("model") or model_alias)
    image_count = 1 if operation == "image" else 0
    response_cost, response_cost_source = _extract_response_cost(data, headers)
    if provider_model == "canary-mock":
        response_cost = 0.0
        response_cost_source = "mock"
    details = usage.get("input_tokens_details") or {}
    cached = details.get("cached_tokens_details") or {}
    cached_total = details.get("cached_tokens", 0)
    # Preserve modality detail; never assign aggregate cached tokens to text.
    cache_known = not cached_total or bool(cached)
    if cached and "cached_tokens" in details:
        cache_known = cached.get("text_tokens", 0) + cached.get("image_tokens", 0) == cached_total
    output_details = usage.get("output_tokens_details") or {}
    return UsageRecord(
        call_id=event_id,
        provider=_provider_from_model(provider_model),
        model=model_alias,
        provider_model=provider_model,
        operation=operation,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        image_count=image_count,
        input_text_tokens=details.get("text_tokens"),
        input_image_tokens=details.get("image_tokens"),
        cached_text_tokens=cached.get("text_tokens", 0) if cache_known else None,
        cached_image_tokens=cached.get("image_tokens", 0) if cache_known else None,
        image_output_tokens=output_details.get("image_tokens", usage.get("output_tokens")),
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
        reasons = []
        if choice.get("finish_reason") == "content_filter":
            reasons.append("finish_reason=content_filter")
        message = choice.get("message") or {}
        if message.get("refusal"):
            reasons.append(f"message.refusal={str(message['refusal'])[:1000]!r}")
        if reasons:
            return "; ".join(reasons)
    error = data.get("error") or {}
    if isinstance(error, dict):
        code = str(error.get("code") or "").lower()
        if code in {"content_policy_violation", "content_filter", "policy_violation"}:
            return f"error.code={code}"
    return None


def _text_refusal_error(
    data: dict[str, Any], *, reason: str, model: str, feature: str, event_id: str,
    response: httpx.Response | None,
) -> AIRefusalError:
    """Retain refusal evidence without copying source prose or request headers."""

    ctx = current_ai_request_context()
    choice = (data.get("choices") or [{}])[0]
    message = choice.get("message") or {}
    diagnostics = {
        "event_id": event_id,
        "feature": feature,
        "model_alias": model,
        "provider_model": data.get("model") or model,
        "provider": _provider_from_model(str(data.get("model") or model)),
        "source_scope": ctx.source_scope,
        "source_unit_ids": list(ctx.source_unit_ids),
        "finish_reason": choice.get("finish_reason"),
        "refusal": str(message["refusal"])[:4000] if message.get("refusal") else None,
    }
    provider_fields = message.get("provider_specific_fields") or {}
    stop_details = provider_fields.get("stop_details")
    if isinstance(stop_details, dict):
        diagnostics["stop_details"] = {
            key: str(stop_details[key])[:1000] if stop_details.get(key) is not None else None
            for key in ("type", "category", "explanation")
        }
        explanation = diagnostics["stop_details"]["explanation"]
        if explanation:
            reason += f"; provider_explanation={explanation!r}"
    for field, value in (
        ("content_filter_results", choice.get("content_filter_results")),
        ("prompt_filter_results", data.get("prompt_filter_results")),
        ("prompt_feedback", data.get("prompt_feedback")),
    ):
        if value is not None:
            # Keep bounded metadata only; never log the generated story as a reason.
            encoded = json.dumps(value, ensure_ascii=False, default=str)
            diagnostics[field] = value if len(encoded) <= 4000 else encoded[:4000]
    scope = f"; source_scope={ctx.source_scope}" if ctx.source_scope else ""
    return AIRefusalError(
        f"AI request was refused by gateway/provider ({reason}); "
        f"provider={diagnostics['provider']}; model={model}; feature={feature}"
        f"{scope}; event_id={event_id}",
        response_data=data, response=response, diagnostics=diagnostics,
    )


def _is_refusal(data: dict[str, Any]) -> bool:
    return _refusal_reason(data) is not None


def _gateway_http_error(
    response: httpx.Response,
    *,
    feature: str,
    model: str,
    endpoint: str,
) -> AITransportError:
    """Build a bounded error that preserves provider diagnostics, not payload data."""
    detail = ""
    provider_code = ""
    error_type = ""
    try:
        body = response.json()
    except Exception:
        body = None
    if isinstance(body, dict):
        error = body.get("error")
        if isinstance(error, dict):
            if isinstance(error.get("message"), str):
                detail = error["message"]
            metadata = error.get("metadata")
            if isinstance(metadata, dict):
                provider_code = str(metadata.get("provider_code") or "")[:120]
                error_type = str(metadata.get("error_type") or "")[:120]
        elif isinstance(body.get("detail"), str):
            detail = body["detail"]
        elif isinstance(body.get("message"), str):
            detail = body["message"]
    detail = " ".join(detail.split())[:800]
    suffix_parts = [part for part in (detail, provider_code, error_type) if part]
    suffix = f" — {'; '.join(suffix_parts)}" if suffix_parts else ""
    reason = getattr(response, "reason_phrase", "")
    status_text = f"{response.status_code} {reason}".strip()
    return AITransportError(
        f"AI gateway request failed for {feature} "
        f"(model={model}, endpoint={endpoint}): "
        f"{status_text}{suffix}",
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
    # Read/write timeouts run on the shorter _MAX_TIMEOUT_RETRIES budget, so
    # reporting _MAX_RETRIES + 1 for them overstates what was actually tried.
    if isinstance(exc, _SLOW_TIMEOUT_ERRORS):
        attempts = _MAX_TIMEOUT_RETRIES + 1
        detail = (
            f" (per-chunk read timeout {_READ_TIMEOUT:.0f}s, "
            f"stream budget {_STREAM_TOTAL_TIMEOUT:.0f}s)"
        )
    else:
        attempts = _MAX_RETRIES + 1
        detail = ""
    return AITransportError(
        f"AI gateway request failed for {feature} "
        f"(model={model}, endpoint={endpoint}): transport {type(exc).__name__} "
        f"after {attempts} attempts{detail}",
        phase="gateway_request",
    )


def _text_response_error(data, *, model, feature, event_id, response, empty=False):
    """Retain bounded failure evidence without copying story or reasoning text."""
    choice = (data.get("choices") or [{}])[0]
    error = data.get("error")
    diagnostics = {
        "event_id": event_id, "feature": feature, "model": model,
        "source_scope": current_ai_request_context().source_scope,
        "provider_response_id": data.get("id"),
        "finish_reason": choice.get("finish_reason"),
        "stream": data.get("_canary_stream"),
    }
    if isinstance(error, dict):
        diagnostics["provider_error"] = {
            key: " ".join(str(error[key]).split())[:800]
            for key in ("code", "type", "message") if error.get(key) is not None
        }
    elif error is not None:
        diagnostics["provider_error"] = {"message": " ".join(str(error).split())[:800]}
    usage = data.get("usage") or {}
    if usage:
        diagnostics["completion_tokens"] = usage.get("completion_tokens")
    error_type = AIEmptyResponseError if empty else AITransportError
    description = "Empty text response" if empty else "Provider text response failed"
    return error_type(
        f"{description} for {feature} (model={model}, "
        f"source_scope={diagnostics['source_scope']!r}, "
        f"finish_reason={diagnostics['finish_reason']!r}, "
        f"event_id={event_id}): "
        + json.dumps({k: v for k, v in diagnostics.items()
                      if k in {"provider_error", "stream", "completion_tokens"}}, ensure_ascii=False),
        phase="empty_response" if empty else "provider_response",
        response=response, diagnostics=diagnostics,
    )


def _error_json(
    exc: BaseException | None = None, response: httpx.Response | None = None
) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    if response is not None:
        payload["status_code"] = response.status_code
        try:
            payload["body"] = response.text[:2000]
        except httpx.ResponseNotRead:
            # A streamed response is consumed chunk-by-chunk, so there is no
            # buffered body to log; the collapsed body goes to response_data.
            payload["body"] = None
    if exc is not None:
        payload["exception"] = type(exc).__name__
        if isinstance(exc, AIRefusalError) and exc.diagnostics:
            payload["refusal_diagnostics"] = exc.diagnostics
        if isinstance(exc, AITransportError) and exc.diagnostics:
            payload["transport_diagnostics"] = exc.diagnostics
        if getattr(exc, "phase", None) == "ambiguous_submission":
            payload["phase"] = "ambiguous_submission"
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
    from .usage_payloads import compact_metadata

    ctx = current_ai_request_context()
    try:
        from novel_to_comic.server.db import get_db

        get_db().table("ai_usage_events").insert(
            {
                "id": event_id,
                "user_id": ctx.user_id,
                "project_id": ctx.project_id,
                "workspace_id": ctx.workspace_id,
                "project_name": ctx.project_name,
                "stage": ctx.stage,
                "feature": feature,
                "operation": operation,
                "status": "started",
                "funding": metadata_json.get("funding", "api"),
                "model_alias": model_alias,
                "request_id": ctx.request_id,
                "params_json": params_json,
                "request_summary_json": request_summary_json,
                "metadata_json": compact_metadata(metadata_json),
                "estimated_cost_usd": estimated_cost_usd,
            }, returning="minimal",
        ).execute()
    except Exception as exc:
        # Error details can include an entire failed row with creative content.
        # Only recognize known constraint names; never print the database row.
        message = getattr(exc, "message", "")
        funding_constraint = isinstance(message, str) and '"ai_usage_events_funding_check"' in message
        remedy = ("apply docs/sql/2026-09-25-claude-subscription-funding.sql"
                  if funding_constraint else "check database schema/migrations")
        logger.warning("Usage record insert failed event_id=%s error_type=%s code=%s; %s",
                       event_id, type(exc).__name__, getattr(exc, "code", "unknown"), remedy)

async def _insert_event_async(*, started_at=None, **kwargs: Any) -> None:
    """Await authoritative usage persistence off the event loop."""
    await asyncio.to_thread(_insert_event, **kwargs)



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
    started_at: datetime.datetime | None = None,
) -> None:
    funding = usage.funding if usage is not None else (metadata or {}).get("funding", "api")
    if is_subscription(funding) and usage is None:
        usage = UsageRecord(
            provider="claude" if funding == "claude_subscription" else "codex",
            model=model_alias, call_id=event_id,
            provider_model=(metadata or {}).get("codex_reasoning_model") if operation == "text" else None,
            operation=operation, cost_usd=None, cost_source=funding,
            funding=funding,
        )
    provider_model = str(
        (response_data or {}).get("model")
        or (usage.provider_model if usage else None)
        or model_alias
    )
    if funding == "codex_subscription" and operation == "image":
        provider_model = usage.provider_model if usage else None
    cost = calculate_cost_breakdown(usage) if usage is not None else None
    cost_usd = usage.cost_usd if is_subscription(funding) else (cost.cost_usd if cost is not None else None)
    if cost is not None and cost.source == "unknown_provider_usage":
        cost_usd = None
    billable = bool(
        usage
        and (cost is None or cost.source != "unknown_provider_usage")
        and usage_has_billable_activity(usage)
        and (
            status == "succeeded"
            or (config is not None and _should_bill_failed(config, usage))
        )
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
        "funding": funding,
        "billing_policy": config.ai_bill_failed_requests if config else None,
        "provider": usage.provider if usage else _provider_from_model(provider_model),
        "provider_model": provider_model,
        "litellm_model": provider_model,
        "provider_response_id": (
            (response_data or {}).get("provider_request_id") or (response_data or {}).get("id")
        ),
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
    if metadata is not None:
        update["metadata_json"] = metadata
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

        from .usage_payloads import compact_metadata

        if "metadata_json" in update:
            update["metadata_json"] = compact_metadata(update["metadata_json"])
        get_db().table("ai_usage_events").update(update, returning="minimal").eq("id", event_id).execute()
    except Exception as exc:
        logger.warning("Usage record update failed event_id=%s error_type=%s code=%s; check database schema/migrations",
                       event_id, type(exc).__name__, getattr(exc, "code", "unknown"))
    if usage is not None and billable and not is_subscription(funding):
        _settle_event_usage(usage, feature=feature, status=status)
    elif funding == "api" and not (config is not None and mock_mode_active(config)):
        from novel_to_comic.server.credits import (
            is_ambiguous_job, release_model_call_authorization,
            retain_ambiguous_job,
        )

        ctx = current_ai_request_context()
        if cost is not None and cost.source == "unknown_provider_usage":
            retain_ambiguous_job(ctx.job_id)
        if ctx.user_id and not is_ambiguous_job(ctx.job_id):
            try:
                from novel_to_comic.server.db import get_db

                release_model_call_authorization(get_db(), user_id=ctx.user_id, call_id=event_id)
            except Exception:
                retain_ambiguous_job(ctx.job_id)
                logger.exception("Credit call authorization release failed call_id=%s", event_id)
    try:
        from novel_to_comic.server.telemetry import observe_generation
        observe_generation(
            event_id=event_id, feature=feature, operation=operation,
            model_alias=model_alias, provider_model=provider_model, status=status,
            usage=usage, cost_usd=cost_usd, cost_source=cost.source if cost else None,
            latency_ms=latency_ms, started_at=started_at, error=error,
            funding=funding, provider=update["provider"],
        )
    except Exception:
        # Export cannot alter authoritative settlement or trigger paid retries.
        pass


async def _finalize_event_async(**kwargs: Any) -> None:
    """Finalize usage off the event loop while awaiting durability and billing."""
    await asyncio.to_thread(_finalize_event, **kwargs)


async def _await_usage_task(task: asyncio.Task[None]) -> None:
    """Drain an authoritative write despite repeated cancellation requests."""
    cancellation: asyncio.CancelledError | None = None
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError as exc:
            cancellation = exc
    task.result()
    if cancellation is not None:
        raise cancellation


async def _finalize_event_shielded(**kwargs: Any) -> None:
    """Await authoritative billing persistence even if cancellation intervenes.

    Offloading finalisation to a worker thread introduced an interruptible
    await where the old synchronous call could not be interrupted. Shielding
    alone would detach the write on cancel, so run it as a task and — if
    cancellation wins the race — wait out the task before re-raising. The
    caller never returns ahead of persistence, and no second terminal write
    can start concurrently with the in-flight one.
    """
    task = asyncio.create_task(_finalize_event_async(**kwargs))
    await _await_usage_task(task)


def _truncate_for_log(text: str, max_chars: int = 4000) -> str:
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + f"... [+{len(text) - max_chars} chars]"


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
    return (
        (float(usage.cost_usd) - float(estimated_cost_usd)) / float(estimated_cost_usd)
    ) * 100.0


def _settle_event_usage(usage: UsageRecord, *, feature: str, status: str) -> None:
    """Debit the credit ledger for one AI call as soon as it finishes.

    Settling per-call (rather than at end-of-stage) means a server crash mid-stage
    only loses the in-flight request — every API call that returned has already
    been charged. The upsert is idempotent on usage_call_id so duplicate debits
    from upstream callers collapse to a single ledger row.
    """
    ctx = current_ai_request_context()
    if not ctx.user_id or is_subscription(usage.funding):
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
        from novel_to_comic.server.credits import retain_ambiguous_job

        retain_ambiguous_job(ctx.job_id)
        try:
            from novel_to_comic.server.metrics import increment

            increment(
                "canary_credit_debit_failures_total",
                stage=ctx.stage or "none",
            )
        except Exception:
            pass
        return


async def _authorize_model_submission(
    *, event_id: str, estimated_cost_usd: float | None,
    funding: str, config: Config,
) -> None:
    ctx = current_ai_request_context()
    if not ctx.user_id or funding != "api" or mock_mode_active(config):
        return
    from novel_to_comic.server.credits import authorize_model_call
    from novel_to_comic.server.db import get_db

    await asyncio.to_thread(
        authorize_model_call, get_db(), user_id=ctx.user_id,
        job_id=ctx.job_id, call_id=event_id,
        estimated_cost_usd=estimated_cost_usd,
    )


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


def _close_json_containers(text: str) -> str | None:
    """Close containers only, without completing strings, literals, or values."""
    text = text.rstrip()
    if not text or text.lstrip()[0] not in "[{" or text[-1] not in '"]}':
        return None
    stack: list[str] = []
    quoted = escaped = False
    for char in text:
        if quoted:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quoted = False
        elif char == '"':
            quoted = True
        elif char in "[{":
            stack.append("]" if char == "[" else "}")
        elif char in "]}":
            if not stack or stack.pop() != char:
                return None
    if quoted or not stack:
        return None
    candidate = text + "".join(reversed(stack))
    try:
        json.loads(candidate)
    except json.JSONDecodeError:
        return None
    return candidate


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
    response_sink: Callable[[ApiResult[str]], None] | None = None,
    retry_invalid_json: bool = True,
    retry_transport: bool = True,
) -> ApiResult[dict]:
    """Generate JSON, optionally retaining paid response bytes before parsing.

    The synchronous sink receives exact response text and finalized usage.
    Persistence failures propagate without another provider call. Callers with
    durable recovery can disable paid JSON repair attempts independently.
    """
    if isinstance(user_content, bytes):
        raise ValueError(
            "Image-based PDFs are not supported by the LiteLLM gateway path. "
            "Extract text locally or add OCR preprocessing before Stage 1."
        )
    base_user_content = user_content
    attempt_user_content = user_content
    last_exc: json.JSONDecodeError | None = None
    last_text: str = ""
    prior_usage: list[UsageRecord] = []
    empty_retried = False
    max_parse_retries = _JSON_PARSE_MAX_RETRIES if retry_invalid_json else 0
    for attempt in range(max_parse_retries + 1):
        try:
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
                retry_transport=retry_transport,
            )
        except AIEmptyResponseError as exc:
            # Share the existing structured-recovery allowance, with at most
            # one empty-answer retry. Durable raw-response recovery can opt out.
            if empty_retried or attempt >= max_parse_retries:
                raise
            empty_retried = True
            if exc.usage is not None:
                prior_usage.append(exc.usage)
            logger.warning("Retrying empty structured response once: %s", exc)
            continue
        if response_sink is not None:
            response_sink(ApiResult(
                value=data["text"],
                usage=data["usage"],
                additional_usage=tuple(prior_usage),
            ))
        text = _strip_code_fence(data["text"])
        try:
            return ApiResult(
                value=json.loads(text),
                usage=data["usage"],
                additional_usage=tuple(prior_usage),
            )
        except json.JSONDecodeError as exc:
            # Preserve authored content; callers still validate the schema.
            # Output-cap truncation is not a finished answer with missing braces.
            capped = str(data.get("finish_reason") or "").lower() in {
                "length", "max_tokens", "max_token", "max_output_tokens",
            }
            dropped = (data.get("stream") or {}).get("dropped", 0)
            closed = _close_json_containers(text) if not capped and not dropped else None
            if closed is not None:
                logger.info("Closed missing JSON containers locally for %s", feature)
                return ApiResult(
                    value=json.loads(closed), usage=data["usage"],
                    additional_usage=tuple(prior_usage),
                )
            if data["usage"] is not None:
                prior_usage.append(data["usage"])
            last_exc = exc
            last_text = text
            # finish_reason and the stream counters separate the two causes that
            # look identical here: the model hit its output cap (finish_reason
            # length/max_tokens — a real truncation), or the stream lost an
            # event (dropped > 0 — reassembly left a hole).
            stream_info = data.get("stream") or {}
            logger.warning(
                "JSON parse failed for %s (model=%s) on attempt %d/%d: %s at "
                "char %d (finish_reason=%s, chars=%d, stream_events=%s, "
                "dropped_events=%s)",
                feature,
                model,
                attempt + 1,
                max_parse_retries + 1,
                exc.msg,
                exc.pos,
                data.get("finish_reason"),
                len(text),
                stream_info.get("events", "n/a"),
                stream_info.get("dropped", "n/a"),
            )
            if attempt < max_parse_retries:
                limit_note = ""
                if str(data.get("finish_reason") or "").lower() in {
                    "length",
                    "max_tokens",
                    "max_token",
                    "max_output_tokens",
                }:
                    limit_note = (
                        " Your previous response reached the output token limit; "
                        "shorten optional explanations so the complete object fits, "
                        "but preserve exact lettering, protected language, visual "
                        "anchors, and continuity guards verbatim."
                    )
                attempt_user_content = (
                    f"{base_user_content}\n\n"
                    "Your previous response was not valid JSON. Return a fresh, complete "
                    "JSON object with no markdown or commentary."
                    f"{limit_note} JSON parser error: {exc.msg} at character {exc.pos}."
                )
    assert last_exc is not None  # loop runs at least once
    raise _format_json_parse_failure(
        last_exc, last_text, model, feature, max_parse_retries + 1
    ) from last_exc


def _claude_token_usage(usage: dict[str, Any]) -> dict[str, Any]:
    # Anthropic reports cache reads and writes outside input_tokens; count
    # them in, as the gateway does for the API route.
    return {
        "prompt_tokens": sum(usage.get(field) or 0 for field in (
            "input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")),
        "completion_tokens": usage.get("output_tokens"),
        "cached_tokens": usage.get("cache_read_input_tokens"),
        "cache_creation_input_tokens": usage.get("cache_creation_input_tokens"),
    }


def _codex_text_usage(
    event_id: str, model: str, route: CodexRoute, tokens: dict[str, Any],
) -> UsageRecord:
    if isinstance(tokens.get("usage"), dict):
        # Claude runtime evidence nests Anthropic usage.
        tokens = _claude_token_usage(tokens["usage"])
    cached = tokens.get("cached_tokens")
    return UsageRecord(
        provider="claude" if route.runtime == "claude" else "codex",
        model=model, provider_model=route.reasoning_model,
        call_id=event_id, operation="text",
        input_tokens=int(tokens.get("prompt_tokens") or tokens.get("input_tokens") or 0),
        output_tokens=int(tokens.get("completion_tokens") or tokens.get("output_tokens") or 0),
        cached_text_tokens=cached if type(cached) is int else None,
        cache_creation_input_tokens=tokens.get("cache_creation_input_tokens"),
        cost_usd=None, cost_source=route.funding, funding=route.funding,
    )


def _codex_error_usage(
    event_id: str, model: str, route: CodexRoute, error: BaseException,
) -> UsageRecord:
    return _codex_text_usage(event_id, model, route, getattr(error, "metadata", {}) or {})


def _api_equivalent_cost(model: str, usage: UsageRecord) -> float | None:
    """What the same tokens cost on the API route, for side-by-side comparison.

    Priced exactly as an API call's usage is, never settled or reserved.
    """
    breakdown = get_pricing_resolver().calculate(
        model_alias=model, operation="text", input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens, provider_model=usage.provider_model,
    )
    return None if breakdown.source == "unknown_pricing" else breakdown.cost_usd


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
    retry_transport: bool = True,
) -> dict[str, Any]:
    route = route_for("text", model)
    if config.mock_mode and (route is not None or not mock_mode_active(config)):
        raise CodexRoutingError("Mock projects cannot execute live Codex requests")
    event_id = str(uuid.uuid4())
    operation = "text"
    metadata = _metadata(feature, operation, model, event_id)
    if route is not None:
        metadata.update({
            "funding": route.funding,
            "subscription_runtime": route.runtime,
            "codex_reasoning_model": route.reasoning_model,
            "unsupported_controls": {
                "temperature": temperature,
                "max_output_tokens": max_output_tokens,
            },
        })
    wire = text_wire(model)
    response_format: dict[str, Any] | None
    effective_system = system_prompt
    if json_schema:
        schema_name = re.sub(r"[^a-zA-Z0-9_-]", "_", feature)[:64]
        response_format = {
            "type": "json_schema",
            "json_schema": {
                "name": schema_name,
                "strict": True,
                "schema": (
                    strict_output_schema(json_schema)
                    if route is None and not wire.claude_native_json
                    else json_schema
                ),
            },
        }
    elif json_mode:
        response_format = {"type": "json_object"}
    else:
        response_format = None
    if json_mode and "json" not in (system_prompt + user_content).lower():
        effective_system += "\n\nRespond with valid JSON."
    # An image-reading call keeps ``user_content`` as its text part so cost
    # estimation, request summaries, and Langfuse logging stay comparable with
    # text-only calls; only the wire message becomes multimodal.
    message_content: str | list[dict[str, Any]] = user_content
    if image_attachments and route is None:
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
    if route is None and wire.temperature:
        payload["temperature"] = temperature
    if route is None and wire.claude_native_json:
        output_config: dict[str, Any] = {}
        # The gateway drops a route's reasoning_effort once output_config is
        # present, so effort travels with the format it would otherwise lose to.
        if wire.effort:
            output_config["effort"] = wire.effort
        # Schema-less JSON uses the instruction and parser above.
        if json_schema:
            output_config["format"] = {
                "type": "json_schema", "schema": anthropic_output_schema(json_schema),
            }
        if output_config:
            payload["output_config"] = output_config
    elif response_format is not None:
        payload["response_format"] = response_format
    effective_max_output_tokens = (max_output_tokens or 16_384) + wire.thinking_headroom_tokens
    if wire.max_output_tokens:
        effective_max_output_tokens = min(effective_max_output_tokens, wire.max_output_tokens)
    if route is None:
        payload[wire.token_limit_field] = effective_max_output_tokens
    # Stream so the read timeout is per-chunk: long adapt repairs exceed the
    # read budget as a single blocking response. include_usage puts the usage
    # block on a final chunk, which streaming otherwise omits.
    streaming = route is None and _stream_text_enabled()
    if streaming:
        payload["stream"] = True
        payload["stream_options"] = {"include_usage": True}

    estimated_cost_usd = (
        (estimate_text_cost(
            model, effective_system + "\n" + user_content,
            # The answer budget; the estimator adds the model's typical thinking.
            output_chars=(max_output_tokens or 16_384) * 4,
        ) or None)
        if route is None else None
    )
    # Everything the terminal handlers reference must exist before the first
    # cancellable await: offloading the insert to a thread means cancellation
    # can now land here, and the CancelledError handler reads all of these.
    started = time.perf_counter()
    started_at = datetime.datetime.now(datetime.UTC)
    response: httpx.Response | None = None
    data: dict[str, Any] = {}
    paid_call = bool(
        route is None and current_ai_request_context().user_id and not mock_mode_active(config)
    )
    provider_submission_started = False
    insert_task = asyncio.create_task(
        _insert_event_async(
            event_id=event_id,
            model_alias=model,
            feature=feature,
            operation=operation,
            params_json=_redacted_params(payload),
            request_summary_json=_content_summary(effective_system, user_content),
            metadata_json=metadata,
            estimated_cost_usd=estimated_cost_usd,
            started_at=started_at,

        )
    )
    try:
        await _await_usage_task(insert_task)
    except asyncio.CancelledError as exc:
        # The request was never issued, but the started row must still reach
        # a terminal state: wait out the insert, book the cancellation, then
        # propagate. Exactly once — the main try block is never entered.
        await _finalize_event_shielded(
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

            started_at=started_at,
        )
        raise
    try:
        await _authorize_model_submission(
            event_id=event_id, estimated_cost_usd=estimated_cost_usd,
            funding=metadata.get("funding", "api"), config=config,
        )
        endpoint = "/v1/chat/completions"
        if route is None:
            # The Codex runtime notifies when its serialized queue releases.
            notify_execution_started()
        # Keep a local breadcrumb alongside the queued Langfuse observation.
        logger.debug(
            "AI request issued feature=%s model=%s streaming=%s event_id=%s",
            feature,
            model,
            streaming,
            event_id,
        )
        try:
            if route is not None and route.runtime == "claude":
                from novel_to_comic.ai.claude_runtime import run_text as run_claude_text

                # The API route's model controls, so the two runs are comparable.
                claude_wire = text_wire(route.reasoning_model)
                claude_limit = (max_output_tokens or 16_384) + claude_wire.thinking_headroom_tokens
                if claude_wire.max_output_tokens:
                    claude_limit = min(claude_limit, claude_wire.max_output_tokens)
                claude_result = await run_claude_text(
                    model=route.reasoning_model,
                    system_prompt=effective_system,
                    user_content=user_content,
                    json_schema=json_schema,
                    image_attachments=image_attachments,
                    effort=claude_wire.effort,
                    max_output_tokens=claude_limit,
                )
                metadata["codex_runtime"] = claude_result.metadata
                data = {
                    "model": claude_result.model,
                    "choices": [{"message": {"content": claude_result.text}, "finish_reason": "stop"}],
                    "usage": _claude_token_usage({
                        "input_tokens": claude_result.input_tokens,
                        "output_tokens": claude_result.output_tokens,
                        "cache_read_input_tokens": claude_result.cache_read_input_tokens,
                        "cache_creation_input_tokens": claude_result.cache_creation_input_tokens,
                    }),
                }
            elif route is not None:
                from novel_to_comic.ai.codex_runtime import run_text

                result = await run_text(
                    model=route.reasoning_model,
                    system_prompt=effective_system,
                    user_content=user_content,
                    json_schema=json_schema,
                    image_attachments=image_attachments,
                )
                metadata["codex_runtime"] = result.metadata
                data = {
                    "model": result.model,
                    "choices": [{"message": {"content": result.text}, "finish_reason": "stop"}],
                    "usage": {"prompt_tokens": result.input_tokens, "completion_tokens": result.output_tokens},
                }
                if result.model != route.reasoning_model:
                    raise CodexRoutingError("Codex returned a different reasoning model than requested")
            elif streaming:
                provider_submission_started = True
                if retry_transport:
                    data, response = await _stream_with_retry(
                        f"{_base_url(config)}{endpoint}",
                        headers=_headers(config, event_id),
                        payload=payload,
                        **({"retry_ambiguous": False} if paid_call else {}),
                    )
                else:
                    data, response = await _read_chat_stream(
                        f"{_base_url(config)}{endpoint}",
                        headers=_headers(config, event_id),
                        payload=payload,
                    )
            else:
                provider_submission_started = True
                if retry_transport:
                    response = await _post_with_retry(
                        f"{_base_url(config)}{endpoint}",
                        headers=_headers(config, event_id),
                        json=payload,
                        **({"retry_ambiguous": False} if paid_call else {}),
                    )
                else:
                    response = await _http.post(
                        f"{_base_url(config)}{endpoint}",
                        headers=_headers(config, event_id),
                        json=payload,
                    )
                data = {}
            if response is not None and response.status_code >= 400:
                response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            if paid_call and exc.response.status_code >= 500:
                from novel_to_comic.server.credits import retain_ambiguous_job
                retain_ambiguous_job(current_ai_request_context().job_id)
            gateway_error = _gateway_http_error(
                exc.response,
                feature=feature,
                model=model,
                endpoint=endpoint,
            )
            logger.error(
                "AI gateway rejected request feature=%s model=%s event_id=%s status=%s error=%s",
                feature,
                model,
                event_id,
                exc.response.status_code,
                gateway_error,
            )
            raise gateway_error from exc
        except _TRANSPORT_ERRORS as exc:
            if paid_call and not isinstance(exc, (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout)):
                from novel_to_comic.server.credits import retain_ambiguous_job
                retain_ambiguous_job(current_ai_request_context().job_id)
            raise _gateway_transport_error(
                exc,
                feature=feature,
                model=model,
                endpoint=endpoint,
            ) from exc
        if route is None and not streaming:
            data = response.json()
        refusal = _refusal_reason(data)
        if refusal:
            raise _text_refusal_error(
                data, reason=refusal, model=model, feature=feature,
                event_id=event_id, response=response,
            )
        choice = (data.get("choices") or [{}])[0]
        if data.get("error") is not None or str(choice.get("finish_reason") or "").lower() == "error":
            raise _text_response_error(data, model=model, feature=feature,
                                       event_id=event_id, response=response)
        text = (choice.get("message") or {}).get("content")
        if not text:
            # Output-cap exhaustion is not transient: another identical request
            # cannot be assumed to help. Refusals were already handled above.
            empty = str(choice.get("finish_reason") or "").lower() in {"", "stop"}
            raise _text_response_error(data, model=model, feature=feature,
                                       event_id=event_id, response=response, empty=empty)
        usage = (
            _codex_text_usage(event_id, model, route, data.get("usage") or {})
            if route is not None else _extract_usage(data, event_id, model, operation, response.headers)
        )
        if route is not None and route.runtime == "claude":
            metadata["api_equivalent_cost_usd"] = _api_equivalent_cost(route.reasoning_model, usage)
        if (
            route is None
            and not usage.input_tokens
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
    except asyncio.CancelledError as exc:
        if paid_call and provider_submission_started:
            from novel_to_comic.server.credits import retain_ambiguous_job
            retain_ambiguous_job(current_ai_request_context().job_id)
        if route is not None:
            metadata["codex_runtime"] = getattr(exc, "metadata", {})
        # Shielded: the task must not return before billing persistence
        # completes, even if a second cancellation arrives mid-write. The
        # success write lives outside this catcher, so a late cancel can
        # never overwrite a completed success with a cancelled status.
        await _finalize_event_shielded(
            event_id=event_id,
            status="cancelled",
            feature=feature,
            model_alias=model,
            latency_ms=int((time.perf_counter() - started) * 1000),
            error=exc,
            usage=_codex_error_usage(event_id, model, route, exc) if route else None,
            error_response=response,
            config=config,
            operation=operation,
            metadata=metadata,
            estimated_cost_usd=estimated_cost_usd,

            started_at=started_at,
        )
        raise
    except AIRefusalError as exc:
        # `data` is the collapsed stream body — a streamed response has no
        # buffered content to re-parse here.
        logger.warning("AI text refusal diagnostics=%s", exc.diagnostics)
        usage = (
            _codex_error_usage(event_id, model, route, exc)
            if route else (_extract_usage(data, event_id, model, operation) if data else None)
        )
        await _finalize_event_shielded(
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

            started_at=started_at,
        )
        raise
    except Exception as exc:
        usage = _codex_error_usage(event_id, model, route, exc) if route else None
        if route is None and data.get("usage"):
            usage = _extract_usage(data, event_id, model, operation,
                                   response.headers if response is not None else None)
        if route is not None:
            metadata["codex_runtime"] = getattr(exc, "metadata", None) or metadata.get("codex_runtime", {})
            if data.get("usage"):
                usage = _codex_text_usage(event_id, model, route, data["usage"])
        if usage is None and route is None and config.ai_bill_failed_requests == "estimate_all" and response is not None:
            usage = estimate_text_usage(
                provider="litellm",
                model=model,
                system_prompt=effective_system,
                user_content=user_content,
                output_text="",
                call_id=event_id,
            )
        if (paid_call and provider_submission_started and usage is None
                and isinstance(exc, AITransportError)
                and exc.phase in {"provider_response", "empty_response", "ambiguous_submission"}):
            from novel_to_comic.server.credits import retain_ambiguous_job
            retain_ambiguous_job(current_ai_request_context().job_id)
        if isinstance(exc, AIEmptyResponseError):
            exc.usage = usage
        await _finalize_event_shielded(
            event_id=event_id,
            status="failed",
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

            started_at=started_at,
        )
        raise
    # The success write runs outside the cancellation catcher: it is shielded,
    # so a cancel landing mid-write waits it out, then propagates without a
    # second terminal write overwriting the succeeded status.
    await _finalize_event_shielded(
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


        started_at=started_at,
    )
    return {
        "text": text,
        "usage": usage,
        "finish_reason": choice.get("finish_reason"),
        "stream": data.get("_canary_stream") or {},
    }


async def generate_wire_image(
    *,
    config: Config,
    wire: "ProviderWireRequest",
    output_path: Path,
    feature: str = "image.generate_wire",
) -> ApiResult[Path]:
    """Submit an immutable exact-wire request through the isolated adapter.

    A multi-route Sunburst wire runs OpenAI first with one FAL attempt as
    backup (``image_route_fallback``); each route is its own usage event.
    """
    from novel_to_comic.image_route_fallback import SUNBURST_FALLBACK_PROVIDER

    if wire.execution_fingerprint != wire.recompute_execution_fingerprint():
        raise ValueError("ProviderWireRequest execution fingerprint mismatch")
    if wire.provider_key == SUNBURST_FALLBACK_PROVIDER:
        return await _generate_sunburst_wire_image(
            config=config, wire=wire, output_path=output_path, feature=feature,
        )
    return await _generate_wire_image_once(
        config=config, wire=wire, output_path=output_path, feature=feature,
    )


async def _generate_sunburst_wire_image(
    *, config: Config, wire: "ProviderWireRequest", output_path: Path, feature: str,
) -> ApiResult[Path]:
    from dataclasses import replace

    from novel_to_comic.image_route_fallback import (
        FAL_SUNBURST_GATEWAY_MODEL,
        OPENAI_SUNBURST_GATEWAY_MODEL,
        run_openai_first,
    )
    from novel_to_comic.usage import estimate_image_cost

    def attempt(gateway_model: str):
        # The frozen request, addressed to one route's gateway deployment.
        routed = replace(wire, requested_alias=gateway_model)
        routed = replace(routed, execution_fingerprint=routed.recompute_execution_fingerprint())
        return _generate_wire_image_once(config=config, wire=routed, output_path=output_path, feature=feature)

    result, route, fallback = await run_openai_first(
        primary=lambda: attempt(OPENAI_SUNBURST_GATEWAY_MODEL),
        backup=lambda: attempt(FAL_SUNBURST_GATEWAY_MODEL),
        surface="asset", request_key=wire.execution_fingerprint,
        estimate_openai_usd=lambda: estimate_image_cost(
            OPENAI_SUNBURST_GATEWAY_MODEL, 1, quality=dict(wire.controls).get("quality"),
            ref_count=len(wire.references), prompt_text=wire.prompt_parts[0],
            width=wire.width, height=wire.height, basis="expected",
        ),
    )
    metadata: dict[str, Any] = {**(result.response_metadata or {}), "route": route}
    if fallback is not None:
        metadata["fallback"] = fallback
    return replace(result, response_metadata=metadata)


async def _generate_wire_image_once(
    *, config: Config, wire: "ProviderWireRequest", output_path: Path, feature: str,
) -> ApiResult[Path]:
    from novel_to_comic.ai.providers import selector
    from novel_to_comic.provider_wire import materialize_wire_references

    transport_wire = wire
    blobs = materialize_wire_references(transport_wire)
    ref_reads = [
        (Path(ref.source_path), data)
        for ref, data in zip(transport_wire.references, blobs, strict=True)
    ]
    provider = selector.pick(
        transport_wire.requested_alias or "", config, provider_key=transport_wire.provider_key
    )
    params = provider.wire_request_params(transport_wire)
    ctx = await begin_image_call(
        config=config,
        model=transport_wire.requested_alias
        or transport_wire.configured_provider_model,
        feature=feature,
        prompt=transport_wire.prompt_parts[0],
        params=params,
        ref_reads=ref_reads,
    )
    try:
        await _authorize_model_submission(
            event_id=ctx.event_id, estimated_cost_usd=ctx.estimated_cost_usd,
            funding=ctx.metadata.get("funding", "api"), config=config,
        )
        raw = await provider.generate_wire(
            wire=transport_wire,
            config=config,
            event_id=ctx.event_id,
            metadata=ctx.metadata,
        )
    except asyncio.CancelledError as exc:
        await finalise_image_cancelled(
            ctx=ctx,
            config=config,
            model=transport_wire.requested_alias
            or transport_wire.configured_provider_model,
            feature=feature,
            error=exc,
            error_response=getattr(exc, "response", None),
        )
        raise
    except Exception as exc:
        await finalise_image_failure(
            ctx=ctx,
            config=config,
            model=transport_wire.requested_alias
            or transport_wire.configured_provider_model,
            feature=feature,
            error=exc,
            error_response=getattr(exc, "response", None),
        )
        raise
    # Finalization owns output-write failures and their already-generated usage.
    # Do not catch and finalize again: that would erase the provider evidence.
    return await finalise_image_success(
        ctx=ctx,
        config=config,
        model=transport_wire.requested_alias
        or transport_wire.configured_provider_model,
        feature=feature,
        output_path=output_path,
        raw=raw,
    )


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
                r.get("category")
                for r in ratings
                if isinstance(r, dict) and r.get("blocked")
            ]
            if blocked:
                crumbs.append(
                    f"safety_ratings blocked: {', '.join(str(c) for c in blocked)}"
                )

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
