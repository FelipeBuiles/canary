"""Text call lifecycle: admission, ambiguity retention, and one terminal accounting write."""
from __future__ import annotations

import asyncio
import datetime
import time
import uuid
from typing import Any

import httpx

from novel_to_comic.ai.admission import AdmissionRejected, cancelled_before_submission
from novel_to_comic.ai.context import current_ai_request_context, current_generation_probe
from novel_to_comic.ai.errors import AIEmptyResponseError, AIRefusalError, AITransportError
from novel_to_comic.ai.text_requests import build_text_request
from novel_to_comic.ai.text_routes import TextRouteResult, execute_text_route
from novel_to_comic.codex_dev import CodexRoutingError
from novel_to_comic.config import Config, mock_mode_active
from novel_to_comic.usage import estimate_text_cost, estimate_text_usage

import logging
logger = logging.getLogger("canary.ai")

async def complete_text(
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
    from novel_to_comic.ai import client

    event_id = str(uuid.uuid4())
    operation = "text"
    metadata = client._metadata(feature, operation, model, event_id)
    request = build_text_request(
        config=config, model=model, system_prompt=system_prompt, user_content=user_content,
        temperature=temperature, max_output_tokens=max_output_tokens, json_mode=json_mode,
        feature=feature, metadata=metadata, json_schema=json_schema,
        image_attachments=image_attachments, streaming_enabled=client._stream_text_enabled(),
    )
    payload = request.payload
    effective_system = request.system_prompt
    user_content = request.user_content
    json_schema = request.json_schema
    route = request.route
    streaming = request.streaming
    open_thinking = request.open_thinking
    if (probe := current_generation_probe()) is not None:
        from novel_to_comic.server.telemetry import content_capture_enabled

        probe.describe(
            system_prompt=effective_system, user_content=user_content, json_schema=json_schema,
            stream=streaming, keep_content=content_capture_enabled(),
        )

    estimated_cost_usd = (
        (estimate_text_cost(
            model, effective_system + "\n" + user_content,
            # The answer budget; the estimator adds the model's typical thinking.
            output_chars=((max_output_tokens or 16_384) + (4_096 if open_thinking else 0)) * 4,
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
    route_result = TextRouteResult()
    insert_task = asyncio.create_task(
        client._insert_event_async(
            event_id=event_id,
            model_alias=model,
            feature=feature,
            operation=operation,
            params_json=client._redacted_params(payload),
            request_summary_json=client._content_summary(effective_system, user_content),
            metadata_json=metadata,
            estimated_cost_usd=estimated_cost_usd,
            started_at=started_at,

        )
    )
    try:
        await client._await_usage_task(insert_task)
    except asyncio.CancelledError as exc:
        # The request was never issued, but the started row must still reach
        # a terminal state: wait out the insert, book the cancellation, then
        # propagate. Exactly once — the main try block is never entered.
        await client._finalize_event_shielded(
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
        await client._authorize_model_submission(
            event_id=event_id, estimated_cost_usd=estimated_cost_usd,
            funding=metadata.get("funding", "api"), config=config,
        )
        endpoint = "/v1/chat/completions"
        # Keep a local breadcrumb alongside the queued Langfuse observation.
        logger.debug(
            "AI request issued feature=%s model=%s streaming=%s event_id=%s",
            feature,
            model,
            streaming,
            event_id,
        )
        try:
            try:
                await execute_text_route(
                    request, config=config, event_id=event_id, image_attachments=image_attachments,
                    max_output_tokens=max_output_tokens, retry_transport=retry_transport,
                    paid_call=paid_call, state=route_result,
                )
            finally:
                data, response = route_result.data, route_result.response
            if route is not None:
                metadata["codex_runtime"] = route_result.runtime_metadata
                if route.runtime != "claude" and data.get("model") != route.reasoning_model:
                    raise CodexRoutingError("Codex returned a different reasoning model than requested")
            if response is not None and response.status_code >= 400:
                response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            if paid_call and exc.response.status_code >= 500:
                from novel_to_comic.server.credits import retain_ambiguous_job
                retain_ambiguous_job(current_ai_request_context().job_id)
            gateway_error = client._gateway_http_error(
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
        except client._TRANSPORT_ERRORS as exc:
            if paid_call and not isinstance(exc, (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout)):
                from novel_to_comic.server.credits import retain_ambiguous_job
                retain_ambiguous_job(current_ai_request_context().job_id)
            raise client._gateway_transport_error(
                exc,
                feature=feature,
                model=model,
                endpoint=endpoint,
            ) from exc
        refusal = client._refusal_reason(data)
        if refusal:
            raise client._text_refusal_error(
                data, reason=refusal, model=model, feature=feature,
                event_id=event_id, response=response,
            )
        choice = (data.get("choices") or [{}])[0]
        if data.get("error") is not None or str(choice.get("finish_reason") or "").lower() == "error":
            raise client._text_response_error(data, model=model, feature=feature,
                                       event_id=event_id, response=response)
        text = route_result.text
        if not text:
            # Output-cap exhaustion is not transient: another identical request
            # cannot be assumed to help. Refusals were already handled above.
            empty = str(choice.get("finish_reason") or "").lower() in {"", "stop"}
            raise client._text_response_error(data, model=model, feature=feature,
                                       event_id=event_id, response=response, empty=empty)
        usage = (
            client._codex_text_usage(event_id, model, route, data.get("usage") or {})
            if route is not None else client._extract_usage(data, event_id, model, operation, response.headers)
        )
        if route is not None and route.runtime == "claude":
            metadata["api_equivalent_cost_usd"] = client._api_equivalent_cost(route.reasoning_model, usage)
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
        if paid_call and route_result.submission_started and not cancelled_before_submission(exc):
            from novel_to_comic.server.credits import retain_ambiguous_job
            retain_ambiguous_job(current_ai_request_context().job_id)
        if route is not None:
            metadata["codex_runtime"] = getattr(exc, "metadata", {})
        # Shielded: the task must not return before billing persistence
        # completes, even if a second cancellation arrives mid-write. The
        # success write lives outside this catcher, so a late cancel can
        # never overwrite a completed success with a cancelled status.
        await client._finalize_event_shielded(
            event_id=event_id,
            status="cancelled",
            feature=feature,
            model_alias=model,
            latency_ms=int((time.perf_counter() - started) * 1000),
            error=exc,
            usage=client._codex_error_usage(event_id, model, route, exc) if route else None,
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
            client._codex_error_usage(event_id, model, route, exc)
            if route else (client._extract_usage(data, event_id, model, operation) if data else None)
        )
        await client._finalize_event_shielded(
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
        usage = client._codex_error_usage(event_id, model, route, exc) if route else None
        if isinstance(exc, AdmissionRejected):
            route_result.submission_started = False
        if route is None and data.get("usage"):
            usage = client._extract_usage(data, event_id, model, operation,
                                   response.headers if response is not None else None)
        if route is not None:
            metadata["codex_runtime"] = getattr(exc, "metadata", None) or metadata.get("codex_runtime", {})
            if data.get("usage"):
                usage = client._codex_text_usage(event_id, model, route, data["usage"])
        if usage is None and route is None and config.ai_bill_failed_requests == "estimate_all" and response is not None:
            usage = estimate_text_usage(
                provider="litellm",
                model=model,
                system_prompt=effective_system,
                user_content=user_content,
                output_text="",
                call_id=event_id,
            )
        if (paid_call and route_result.submission_started and usage is None
                and isinstance(exc, AITransportError)
                and exc.phase in {"provider_response", "empty_response", "ambiguous_submission"}):
            from novel_to_comic.server.credits import retain_ambiguous_job
            retain_ambiguous_job(current_ai_request_context().job_id)
        if isinstance(exc, AIEmptyResponseError):
            exc.usage = usage
        await client._finalize_event_shielded(
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
    if probe is not None and probe.input_messages is not None:
        probe.output_text = text
    # The success write runs outside the cancellation catcher: it is shielded,
    # so a cancel landing mid-write waits it out, then propagates without a
    # second terminal write overwriting the succeeded status.
    await client._finalize_event_shielded(
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
        "finish_reason": route_result.finish_reason,
        "stream": data.get("_canary_stream") or {},
    }

