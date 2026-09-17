"""Image call accounting and output finalisation."""

from __future__ import annotations

import asyncio
import datetime
import hashlib
import os
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from novel_to_comic.ai.errors import AIRefusalError
from novel_to_comic.ai.providers.base import ProviderRawResult
from novel_to_comic.config import Config
from novel_to_comic.codex_dev import route_for
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


def _subscription_usage(ctx: ImageCallContext, model: str, evidence: dict[str, Any], *, image_count: int | None = None) -> UsageRecord:
    completed = evidence.get("completed_result_metadata") or {}
    tokens = evidence.get("usage") or {
        **completed,
        **{key: value for key, value in evidence.items() if value is not None},
    }
    if image_count is None:
        image_count = int(any(
            item.get("image_status") == "completed"
            and isinstance(item.get("image"), dict)
            and isinstance(item["image"].get("sha256"), str)
            and len(item["image"]["sha256"]) == 64
            and all(character in "0123456789abcdef" for character in item["image"]["sha256"])
            and all(isinstance(item["image"].get(key), int) and item["image"][key] > 0
                    for key in ("width", "height", "bytes"))
            and item["image"].get("mime") in {"image/png", "image/jpeg", "image/webp"}
            for item in (evidence, completed)
        ))
    return UsageRecord(
        call_id=ctx.event_id, provider="codex", model=model, operation="image",
        input_tokens=tokens.get("prompt_tokens", tokens.get("input_tokens")) or 0,
        output_tokens=tokens.get("completion_tokens", tokens.get("output_tokens")) or 0,
        image_count=image_count, funding="codex_subscription",
        cost_usd=None, cost_source="codex_subscription", provider_model=None,
    )


def _subscription_response(usage: UsageRecord, evidence: dict[str, Any]) -> dict[str, Any]:
    return {
        "usage": {
            "prompt_tokens": usage.input_tokens,
            "completion_tokens": usage.output_tokens,
            "image_count": usage.image_count,
        },
        "codex_runtime": evidence,
    }


def _open_output_parent(output_path: Path) -> int:
    """Open/create the output parent without following directory symlinks."""
    absolute = Path(os.path.abspath(output_path))
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | nofollow
    parent = absolute.parent
    descriptor = os.open(parent.anchor or ".", directory_flags)
    try:
        relative_parent = parent.relative_to(Path(parent.anchor or "."))
        for component in relative_parent.parts:
            try:
                os.mkdir(component, dir_fd=descriptor)
            except FileExistsError:
                pass
            child_descriptor = os.open(component, directory_flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child_descriptor
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _atomic_write_output(parent_fd: int, filename: str, data: bytes) -> None:
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    temporary_name = f".{filename}.{uuid.uuid4().hex}.tmp"
    temporary_fd = -1
    try:
        temporary_fd = os.open(
            temporary_name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | nofollow,
            0o600,
            dir_fd=parent_fd,
        )
        with os.fdopen(temporary_fd, "wb") as handle:
            temporary_fd = -1
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(
            temporary_name,
            filename,
            src_dir_fd=parent_fd,
            dst_dir_fd=parent_fd,
        )
        os.fsync(parent_fd)
        temporary_name = ""
    except BaseException:
        if temporary_fd >= 0:
            os.close(temporary_fd)
        if temporary_name:
            try:
                os.unlink(temporary_name, dir_fd=parent_fd)
            except FileNotFoundError:
                pass
        raise


def _write_image_outputs(
    output_path: Path,
    image_bytes: bytes,
) -> None:
    parent_fd = _open_output_parent(output_path)
    try:
        _atomic_write_output(parent_fd, output_path.name, image_bytes)
    finally:
        os.close(parent_fd)


async def begin_image_call(
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
    funding = "codex_subscription" if route_for("image", model) else "api"
    metadata["funding"] = funding
    estimated_cost_usd = None if funding == "codex_subscription" else estimate_image_cost(
        model,
        1,
        quality=config.image_quality,
        ref_count=len(ref_data),
        prompt_text=prompt,
    ) or None
    reference_summary = ai_client._image_summary(ref_reads)
    started = time.perf_counter()
    started_at = datetime.datetime.now(datetime.UTC)
    langfuse_input = {
        "prompt": ai_client._truncate_for_log(prompt),
        "size": params.get("size"),
        "quality": params.get("quality"),
        "ref_count": len(ref_data),
        "references": reference_summary,
    }
    insert_task = asyncio.create_task(
        ai_client._insert_event_async(
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
            started_at=started_at,
            langfuse_input=langfuse_input,
        )
    )
    try:
        await ai_client._await_usage_task(insert_task)
    except asyncio.CancelledError as exc:
        # The request was never issued, but the started row must still reach
        # a terminal state: wait out the insert, book the cancellation, then
        # propagate. Exactly once — the callers' catchers never see a ctx.
        await ai_client._finalize_event_shielded(
            event_id=event_id,
            status="cancelled",
            feature=feature,
            model_alias=model,
            latency_ms=int((time.perf_counter() - started) * 1000),
            error=exc,
            config=config,
            operation=operation,
            metadata=metadata,
            estimated_cost_usd=estimated_cost_usd,
            langfuse_input=langfuse_input,
            started_at=started_at,
        )
        raise
    return ImageCallContext(
        event_id=event_id,
        operation=operation,
        metadata=metadata,
        params=params,
        estimated_cost_usd=estimated_cost_usd,
        started=started,
        started_at=started_at,
        langfuse_input=langfuse_input,
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
    runtime_evidence = raw_response.get("codex_runtime")
    if runtime_evidence:
        ctx.metadata = {**ctx.metadata, "codex_runtime": runtime_evidence}
    usage = _subscription_usage(ctx, model, raw_response, image_count=1) if ctx.metadata.get("funding") == "codex_subscription" else ai_client._extract_usage(
        raw_response,
        ctx.event_id,
        model,
        ctx.operation,
        raw.response_headers,
    )
    try:
        await asyncio.to_thread(
            _write_image_outputs,
            output_path,
            raw.image_bytes,
        )
    except BaseException as exc:
        # Finalization owns write failures too: paid/subscription execution
        # already completed, so retain its evidence even if saving fails.
        if runtime_evidence:
            exc.metadata = {
                **getattr(exc, "metadata", {}),
                **runtime_evidence,
                "completed_result_available": True,
                "completed_result_metadata": runtime_evidence,
            }
        await ai_client._finalize_event_shielded(
            event_id=ctx.event_id,
            status="cancelled" if isinstance(exc, asyncio.CancelledError) else "failed",
            feature=feature,
            model_alias=model,
            latency_ms=int((time.perf_counter() - ctx.started) * 1000),
            error=exc,
            error_response=None,
            usage=usage,
            response_data=raw_response,
            config=config,
            operation=ctx.operation,
            metadata=ctx.metadata,
            estimated_cost_usd=ctx.estimated_cost_usd,
            langfuse_input=ctx.langfuse_input,
            started_at=ctx.started_at,
        )
        raise
    langfuse_output = {
        "output_path": str(output_path),
        "image_bytes": len(raw.image_bytes),
        "image_sha256": hashlib.sha256(raw.image_bytes).hexdigest(),
        "size": ctx.params.get("size"),
        "actual_provider_model": raw.actual_provider_model,
    }
    await ai_client._finalize_event_shielded(
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
    return ApiResult(
        value=output_path,
        usage=usage,
        provider_request_id=raw.provider_request_id,
        actual_provider_model=raw.actual_provider_model,
        response_metadata=raw_response.get("codex_runtime"),
    )


async def finalise_image_cancelled(
    *,
    ctx: ImageCallContext,
    config: Config,
    model: str,
    feature: str,
    error: BaseException,
    error_response: httpx.Response | None = None,
) -> None:
    from novel_to_comic.ai import client as ai_client

    evidence = getattr(error, "metadata", {})
    usage = _subscription_usage(ctx, model, evidence) if ctx.metadata.get("funding") == "codex_subscription" else None
    await ai_client._finalize_event_shielded(
        event_id=ctx.event_id,
        status="cancelled",
        feature=feature,
        model_alias=model,
        latency_ms=int((time.perf_counter() - ctx.started) * 1000),
        error=error,
        usage=usage,
        response_data=_subscription_response(usage, evidence) if usage is not None else None,
        error_response=error_response,
        config=config,
        operation=ctx.operation,
        metadata={**ctx.metadata, "codex_runtime": evidence} if evidence else ctx.metadata,
        estimated_cost_usd=ctx.estimated_cost_usd,
        langfuse_input=ctx.langfuse_input,
        started_at=ctx.started_at,
    )


async def finalise_image_refusal(
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
    await ai_client._finalize_event_shielded(
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


async def finalise_image_failure(
    *,
    ctx: ImageCallContext,
    config: Config,
    model: str,
    feature: str,
    error: BaseException,
    error_response: httpx.Response | None = None,
) -> None:
    from novel_to_comic.ai import client as ai_client

    evidence = getattr(error, "metadata", {})
    usage = _subscription_usage(ctx, model, evidence) if ctx.metadata.get("funding") == "codex_subscription" else None
    if usage is None and config.ai_bill_failed_requests == "estimate_all" and error_response is not None:
        usage = UsageRecord(
            call_id=ctx.event_id,
            provider="litellm",
            model=model,
            operation="image",
            image_count=1,
        )
    await ai_client._finalize_event_shielded(
        event_id=ctx.event_id,
        status="failed",
        feature=feature,
        model_alias=model,
        latency_ms=int((time.perf_counter() - ctx.started) * 1000),
        usage=usage,
        response_data=_subscription_response(usage, evidence) if usage is not None and usage.funding == "codex_subscription" else None,
        error=error,
        error_response=error_response,
        config=config,
        operation=ctx.operation,
        metadata={**ctx.metadata, "codex_runtime": evidence} if evidence else ctx.metadata,
        estimated_cost_usd=ctx.estimated_cost_usd,
        langfuse_input=ctx.langfuse_input,
        started_at=ctx.started_at,
    )
