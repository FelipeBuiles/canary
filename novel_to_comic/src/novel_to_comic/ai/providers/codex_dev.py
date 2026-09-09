"""Opt-in builtin image transport; a frozen API request is never rerouted here."""

from __future__ import annotations

import time
from typing import Any


from novel_to_comic.ai import codex_runtime
from novel_to_comic.ai.providers.base import ProviderRawResult
from novel_to_comic.codex_dev import assert_request_funding, route_for
from novel_to_comic.config import Config
from novel_to_comic.image_models import ImageRoute, image_model_profile
from novel_to_comic.provider_wire import ProviderWireError, ProviderWireRequest, materialize_wire_references


def validate_codex_wire(wire: ProviderWireRequest) -> str:
    """Reject fingerprint, authorization, capabilities and runtime drift before submit."""
    if wire.execution_fingerprint != wire.recompute_execution_fingerprint():
        raise ProviderWireError("Codex image execution fingerprint mismatch")
    route = route_for("image", wire.requested_alias or "")
    if route is None:
        raise ProviderWireError("Codex image route is not enabled")
    expected_controls = tuple(sorted((("reasoning_model", route.reasoning_model), *codex_runtime.image_execution_controls())))
    profile = image_model_profile(wire.requested_alias or "")
    if (
        wire.provider_key != "codex-dev"
        or wire.expected_route != ImageRoute.CODEX_BUILTIN.value
        or wire.configured_provider_model != route.image_model
        or wire.controls != expected_controls
        or wire.structured_aspect is not None
        or not wire.prompt_parts
        or any(not isinstance(part, str) or not part.strip() for part in wire.prompt_parts)
        or len(wire.references) > profile.max_references
        or any(ref.index != index or ref.provider_binding != str(index) or ref.role not in profile.supported_roles
               for index, ref in enumerate(wire.references))
    ):
        raise ProviderWireError("Codex image wire/profile/runtime drift; compile a new request")
    return route.reasoning_model


def _image_mime(data: bytes) -> str:
    try:
        return codex_runtime.validate_image_bytes(data)["mime"]
    except codex_runtime.CodexRuntimeError as exc:
        raise ProviderWireError("Codex image artifact is not a valid supported image") from exc


class CodexDevImageProvider:
    name = "codex-dev"

    def wire_request_params(self, wire: ProviderWireRequest) -> dict[str, Any]:
        validate_codex_wire(wire)
        return {
            "model": wire.configured_provider_model,
            "provider_key": wire.provider_key,
            "prompt": "\n\n".join(wire.prompt_parts),
            "requested_width": wire.width,
            "requested_height": wire.height,
            "dimension_control": "prompt_intent",
            "execution_fingerprint": wire.execution_fingerprint,
            **dict(wire.controls),
        }

    async def generate_wire(
        self, *, wire: ProviderWireRequest, config: Config,
        event_id: str, metadata: dict[str, Any],
    ) -> ProviderRawResult:
        reasoning_model = validate_codex_wire(wire)
        assert_request_funding("image", wire.requested_alias or "")
        blobs = materialize_wire_references(wire)
        references = tuple((data, _image_mime(data)) for data in blobs)
        started = time.perf_counter()
        result = await codex_runtime.run_image(
            reasoning_model=reasoning_model,
            prompt="\n\n".join(wire.prompt_parts),
            references=references,
            reference_roles=tuple(ref.role for ref in wire.references),
            reference_instructions=tuple(ref.instruction for ref in wire.references),
            edit_parent_indices=wire.edit_parent_indices,
            requested_model=wire.configured_provider_model,
            request_id=event_id,
        )
        # Decode validation must not resize, transcode, or replace native bytes.
        try:
            mime = _image_mime(result.image_bytes)
        except ProviderWireError as exc:
            raise codex_runtime.CodexRuntimeError(
                "invalid_image_artifact",
                metadata={
                    **result.metadata,
                    "input_tokens": result.input_tokens,
                    "output_tokens": result.output_tokens,
                },
            ) from exc
        return ProviderRawResult(
            image_bytes=result.image_bytes,
            mime=mime,
            latency_ms=int((time.perf_counter() - started) * 1000),
            provider_request_id=result.metadata.get("turn_id"),
            actual_provider_model=None,
            provider_cost_usd=None,
            request_params=self.wire_request_params(wire),
            raw_response={
                "usage": {"prompt_tokens": result.input_tokens, "completion_tokens": result.output_tokens},
                "funding": "codex_subscription",
                "codex_runtime": result.metadata,
            },
        )
