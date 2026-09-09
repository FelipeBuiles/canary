"""Local-only native complete-page execution over the restricted Codex runtime."""
from __future__ import annotations

import asyncio
import time
from pathlib import Path

from novel_to_comic.ai import codex_runtime
from novel_to_comic.codex_dev import assert_request_funding, route_for
from novel_to_comic.config import COMPLETE_PAGE_GATEWAY_MODEL, Config
from novel_to_comic.models.draw import CompletePageProviderResult
from novel_to_comic.page_drawing import (
    CompiledPageGeneration, PreparedCompletePageRequest, _prepare_complete_page,
    _validate_prepared_page, current_page_capability_profile,
    page_profile_uses_native_dimensions,
)
from novel_to_comic.usage import UsageRecord


def _runtime_metadata(metadata: dict) -> dict[str, object]:
    """Retain execution evidence, not runtime paths or arbitrary tool payloads."""
    scalar_keys = (
        "thread_id", "turn_id", "tool_id", "submitted", "indeterminate", "image_status",
        "turn_status", "execution_fingerprint", "recovered_after_timeout",
        "process_group_terminated", "reference_mode", "input_tokens", "output_tokens",
        "usage_scope", "image_tool_usage_available",
    )
    result: dict[str, object] = {
        key: value for key in scalar_keys
        if isinstance((value := metadata.get(key)), (str, int, bool))
    }
    image = metadata.get("image")
    if isinstance(image, dict):
        result["image"] = {
            key: value for key in ("width", "height", "mime", "sha256", "bytes")
            if isinstance((value := image.get(key)), (str, int))
        }
    references = metadata.get("references")
    if isinstance(references, list):
        result["references"] = [
            {
                key: value for key in ("index", "width", "height", "mime", "sha256", "bytes")
                if isinstance((value := reference.get(key)), (str, int))
            }
            for reference in references if isinstance(reference, dict)
        ]
    return result


class CodexCompletePageAdapter:
    """Never reroute a frozen production request or retry an ambiguous submission."""

    def __init__(self, config: Config) -> None:
        self._config = config

    def prepare(self, compiled: CompiledPageGeneration) -> PreparedCompletePageRequest:
        profile = current_page_capability_profile()
        if not page_profile_uses_native_dimensions(profile):
            raise ValueError("Codex complete-page routing is not enabled")
        prepared = _prepare_complete_page(compiled, profile)
        self._references(prepared)
        return prepared

    @staticmethod
    def _references(prepared: PreparedCompletePageRequest) -> tuple[tuple[bytes, str], ...]:
        references = []
        if prepared.edit_source_bytes is not None:
            codex_runtime.validate_image_bytes(prepared.edit_source_bytes, "image/png")
            references.append((prepared.edit_source_bytes, "image/png"))
        for reference, data in zip(prepared.references, prepared.reference_bytes, strict=True):
            codex_runtime.validate_image_bytes(data, reference.media_type)
            references.append((data, reference.media_type))
        return tuple(references)

    async def generate(self, prepared: PreparedCompletePageRequest) -> CompletePageProviderResult:
        from novel_to_comic.ai import client as ai_client
        from novel_to_comic.ai.finalisation import (
            begin_image_call, finalise_image_cancelled, finalise_image_failure,
        )

        profile = current_page_capability_profile()
        if not page_profile_uses_native_dimensions(profile):
            raise ValueError("Codex complete-page routing is not enabled")
        _validate_prepared_page(prepared, profile)
        route = route_for("complete_page", COMPLETE_PAGE_GATEWAY_MODEL)
        if route is None:
            raise ValueError("Codex complete-page routing is not enabled")
        assert_request_funding("complete_page", COMPLETE_PAGE_GATEWAY_MODEL)
        references = self._references(prepared)
        feature = "complete_page_draw"
        params = {
            "model": prepared.model, "provider_key": "codex-dev",
            "artifact_kind": "complete_page", "dimension_control": "prompt_intent",
            "requested_width": prepared.width, "requested_height": prepared.height,
            "request_sha256": prepared.request_sha256, "profile_id": profile.id,
            "reasoning_model": route.reasoning_model,
            **dict(codex_runtime.image_execution_controls()),
        }
        ctx = await begin_image_call(
            config=self._config, model=COMPLETE_PAGE_GATEWAY_MODEL, feature=feature,
            prompt=prepared.prompt, params=params,
            ref_reads=[(Path(f"complete-page-input-{index}"), data)
                       for index, (data, _) in enumerate(references)],
        )
        try:
            result = await codex_runtime.run_image(
                reasoning_model=route.reasoning_model, prompt=prepared.prompt,
                references=references, requested_model=prepared.model, request_id=ctx.event_id,
                reference_roles=(
                    (("edit_parent",) if prepared.edit_source_bytes is not None else ())
                    + tuple("approved_asset" for _ in prepared.references)
                ),
                reference_instructions=(
                    (("Preserve untouched artwork; canonical page authorities outrank conflicting pixels.",)
                     if prepared.edit_source_bytes is not None else ())
                    + tuple("Apply this approved asset only to its assigned entity and state in the page specification."
                            for _ in prepared.references)
                ),
                edit_parent_indices=(0,) if prepared.edit_source_bytes is not None else (),
            )
            metadata = _runtime_metadata(result.metadata)
            metadata.update(reasoning_model=route.reasoning_model, profile_id=profile.id,
                            request_sha256=prepared.request_sha256)
            provider_request_id = result.metadata.get("tool_id") or result.metadata.get("turn_id")
            try:
                geometry = codex_runtime.validate_image_bytes(result.image_bytes, "image/png")
            except codex_runtime.CodexRuntimeError as exc:
                raise codex_runtime.CodexRuntimeError(
                    "invalid_image_artifact", {
                        **metadata, "input_tokens": result.input_tokens,
                        "output_tokens": result.output_tokens,
                    },
                ) from exc
            latency_ms = int((time.perf_counter() - ctx.started) * 1000)
            usage = UsageRecord(
                call_id=ctx.event_id, provider="codex", model=COMPLETE_PAGE_GATEWAY_MODEL,
                operation="image", input_tokens=result.input_tokens or 0,
                output_tokens=result.output_tokens or 0, image_count=1,
                provider_model=None, cost_usd=None, cost_source="codex_subscription",
                funding="codex_subscription",
            )
            ctx.metadata = {**ctx.metadata, "codex_runtime": metadata}
        except asyncio.CancelledError as exc:
            await finalise_image_cancelled(
                ctx=ctx, config=self._config, model=COMPLETE_PAGE_GATEWAY_MODEL,
                feature=feature, error=exc,
            )
            raise
        except BaseException as exc:
            await finalise_image_failure(
                ctx=ctx, config=self._config, model=COMPLETE_PAGE_GATEWAY_MODEL,
                feature=feature, error=exc,
            )
            raise
        # Match Vertex's shielded success boundary: cancellation cannot overwrite success.
        try:
            await ai_client._finalize_event_shielded(
                event_id=ctx.event_id, status="succeeded", feature=feature,
                model_alias=COMPLETE_PAGE_GATEWAY_MODEL, latency_ms=latency_ms, usage=usage,
                response_data={"id": provider_request_id, "codex_runtime": metadata, "funding": usage.funding,
                               "usage": {"prompt_tokens": usage.input_tokens,
                                         "completion_tokens": usage.output_tokens}},
                config=self._config, operation=ctx.operation, metadata=ctx.metadata,
                estimated_cost_usd=ctx.estimated_cost_usd, langfuse_input=ctx.langfuse_input,
                langfuse_output={"artifact_kind": "complete_page", **geometry,
                                 "actual_provider_model": None},
                started_at=ctx.started_at,
            )
        except Exception as exc:
            await finalise_image_failure(
                ctx=ctx, config=self._config, model=COMPLETE_PAGE_GATEWAY_MODEL,
                feature=feature, error=exc,
            )
            raise
        return CompletePageProviderResult(
            artifact_kind="complete_page", image_bytes=result.image_bytes,
            media_type="image/png", width=geometry["width"], height=geometry["height"],
            latency_ms=latency_ms, provider_request_id=provider_request_id,
            actual_provider_model=None, usage=usage, response_metadata=metadata,
        )
