"""Image call accounting and output finalisation."""

from __future__ import annotations

import asyncio
import datetime
import hashlib
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from novel_to_comic.ai.errors import AIRefusalError
from novel_to_comic.ai.providers.base import ProviderRawResult
from novel_to_comic.config import Config
from novel_to_comic.usage import ApiResult, UsageRecord, estimate_image_cost


@dataclass
class ImageCallContext:
    event_id: str
    operation: str
    metadata: dict[str, Any]
    params: dict[str, Any]
    estimated_cost_usd: float | None
    started: float
    started_at: datetime.datetime
    langfuse_input: dict[str, Any]


def begin_image_call(
    *,
    config: Config,
    model: str,
    feature: str,
    prompt: str,
    params: dict[str, Any],
    ref_reads: list[tuple[Path, bytes | None]],
) -> ImageCallContext:
    from novel_to_comic.ai import client as ai_client

    event_id = str(uuid.uuid4())
    operation = "image"
    ref_data = [(p, d) for p, d in ref_reads if d is not None]
    metadata = ai_client._metadata(feature, operation, model, event_id)
    estimated_cost_usd = estimate_image_cost(
        model,
        1,
        quality=config.image_quality,
        ref_count=len(ref_data),
        prompt_text=prompt,
    ) or None
    reference_summary = ai_client._image_summary(ref_reads)
    ai_client._insert_event(
        event_id=event_id,
        model_alias=model,
        feature=feature,
        operation=operation,
        params_json=ai_client._redacted_params(params),
        request_summary_json={
            "prompt_sha256": ai_client._hash_payload(prompt),
            "prompt_bytes": ai_client._payload_size(prompt),
            "references": reference_summary,
        },
        metadata_json=metadata,
        estimated_cost_usd=estimated_cost_usd,
    )
    return ImageCallContext(
        event_id=event_id,
        operation=operation,
        metadata=metadata,
        params=params,
        estimated_cost_usd=estimated_cost_usd,
        started=time.perf_counter(),
        started_at=datetime.datetime.now(datetime.UTC),
        langfuse_input={
            "prompt": ai_client._truncate_for_log(prompt),
            "size": params.get("size"),
            "quality": params.get("quality"),
            "ref_count": len(ref_data),
            "references": reference_summary,
        },
    )


async def finalise_image_success(
    *,
    ctx: ImageCallContext,
    config: Config,
    model: str,
    feature: str,
    output_path: Path,
    raw: ProviderRawResult,
) -> ApiResult[Path]:
    from novel_to_comic.ai import client as ai_client

    raw_response = raw.raw_response or {}
    output_path.parent.mkdir(parents=True, exist_ok=True)
    await asyncio.to_thread(output_path.write_bytes, raw.image_bytes)
    if raw.layout_echo:
        from novel_to_comic import artifacts

        await asyncio.to_thread(artifacts.write_asset_layout_echo, output_path, raw.layout_echo)
    usage = ai_client._extract_usage(
        raw_response,
        ctx.event_id,
        model,
        ctx.operation,
        raw.response_headers,
    )
    langfuse_output = {
        "output_path": str(output_path),
        "image_bytes": len(raw.image_bytes),
        "image_sha256": hashlib.sha256(raw.image_bytes).hexdigest(),
        "size": ctx.params.get("size"),
        "actual_provider_model": raw.actual_provider_model,
    }
    ai_client._finalize_event(
        event_id=ctx.event_id,
        status="succeeded",
        feature=feature,
        model_alias=model,
        latency_ms=int((time.perf_counter() - ctx.started) * 1000),
        usage=usage,
        response_data=raw_response,
        config=config,
        operation=ctx.operation,
        metadata=ctx.metadata,
        estimated_cost_usd=ctx.estimated_cost_usd,
        langfuse_input=ctx.langfuse_input,
        langfuse_output=langfuse_output,
        started_at=ctx.started_at,
    )
    return ApiResult(value=output_path, usage=usage)


def finalise_image_cancelled(
    *,
    ctx: ImageCallContext,
    config: Config,
    model: str,
    feature: str,
    error: BaseException,
    error_response: httpx.Response | None = None,
) -> None:
    from novel_to_comic.ai import client as ai_client

    ai_client._finalize_event(
        event_id=ctx.event_id,
        status="cancelled",
        feature=feature,
        model_alias=model,
        latency_ms=int((time.perf_counter() - ctx.started) * 1000),
        error=error,
        error_response=error_response,
        config=config,
        operation=ctx.operation,
        metadata=ctx.metadata,
        estimated_cost_usd=ctx.estimated_cost_usd,
        langfuse_input=ctx.langfuse_input,
        started_at=ctx.started_at,
    )


def finalise_image_refusal(
    *,
    ctx: ImageCallContext,
    config: Config,
    model: str,
    feature: str,
    error: AIRefusalError,
) -> None:
    from novel_to_comic.ai import client as ai_client

    data = error.response_data or {}
    usage = (
        ai_client._extract_usage(data, ctx.event_id, model, ctx.operation, error.response_headers)
        if data
        else None
    )
    ai_client._finalize_event(
        event_id=ctx.event_id,
        status="refused",
        feature=feature,
        model_alias=model,
        latency_ms=int((time.perf_counter() - ctx.started) * 1000),
        usage=usage,
        response_data=data,
        error=error,
        error_response=error.response,
        config=config,
        operation=ctx.operation,
        metadata=ctx.metadata,
        estimated_cost_usd=ctx.estimated_cost_usd,
        langfuse_input=ctx.langfuse_input,
        started_at=ctx.started_at,
    )


def finalise_image_failure(
    *,
    ctx: ImageCallContext,
    config: Config,
    model: str,
    feature: str,
    error: BaseException,
    error_response: httpx.Response | None = None,
) -> None:
    from novel_to_comic.ai import client as ai_client

    usage = None
    if config.ai_bill_failed_requests == "estimate_all" and error_response is not None:
        usage = UsageRecord(
            call_id=ctx.event_id,
            provider="litellm",
            model=model,
            operation="image",
            image_count=1,
        )
    ai_client._finalize_event(
        event_id=ctx.event_id,
        status="failed",
        feature=feature,
        model_alias=model,
        latency_ms=int((time.perf_counter() - ctx.started) * 1000),
        usage=usage,
        error=error,
        error_response=error_response,
        config=config,
        operation=ctx.operation,
        metadata=ctx.metadata,
        estimated_cost_usd=ctx.estimated_cost_usd,
        langfuse_input=ctx.langfuse_input,
        started_at=ctx.started_at,
    )
