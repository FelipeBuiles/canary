"""LiteLLM OpenAI-compatible HTTP image provider."""

from __future__ import annotations

import asyncio
import json
import re
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx

from novel_to_comic.ai.errors import AIRefusalError, AITransportError
from novel_to_comic.ai.providers.base import ProviderRawResult
from novel_to_comic.config import Config, is_gpt_image_2
from novel_to_comic.image_geometry import aspect_for_dimensions
from novel_to_comic.image_models import (
    IMAGE_PROVIDER_FAL_QUEUE,
    IMAGE_PROVIDER_OPENAI,
    IMAGE_PROVIDER_OPENAI_FAL,
    IMAGE_PROVIDER_OPENROUTER,
    IMAGE_PROVIDER_VERTEX_MULTIMODAL,
)
from novel_to_comic.image_route_fallback import openai_image_failure_marker
from novel_to_comic.provider_wire import (
    ProviderWireError,
    ProviderWireRequest,
    materialize_wire_references,
)


class LitellmHttpProvider:
    name = "litellm_http"

    def wire_request_params(self, wire: ProviderWireRequest) -> dict[str, Any]:
        serializer = _PROVIDER_SERIALIZERS.get(wire.provider_key)
        if serializer is None:
            raise ProviderWireError(f"unsupported image provider key: {wire.provider_key!r}")
        return serializer(wire)

    def prepare_wire_request(
        self, wire: ProviderWireRequest,
    ) -> tuple[dict[str, Any], list[tuple[str, tuple[str, bytes, str]]]]:
        """Consume the schema-discriminated exact path.

        Prompt text, reference order, and controls are already final here.
        """
        return serialize_wire_request(wire)

    async def generate_wire(
        self,
        *,
        wire: ProviderWireRequest,
        config: Config,
        event_id: str,
        metadata: dict[str, Any],
    ) -> ProviderRawResult:
        """Submit the exact frozen wire payload."""
        from novel_to_comic.ai import client as ai_client

        params, files = self.prepare_wire_request(wire)
        prompt = str(params.pop("prompt"))
        endpoint = "/v1/images/edits" if files else "/v1/images/generations"
        url = f"{ai_client._base_url(config)}{endpoint}"
        headers = ai_client._headers(config, event_id)
        started = time.perf_counter()
        try:
            if files:
                response = await ai_client._post_with_retry(
                    url, headers=headers,
                    data={"prompt": prompt, "metadata": ai_client._json_dumps(metadata), **{
                        key: str(value) for key, value in params.items() if value is not None
                    }},
                    files=files,
                    retry_ambiguous=False,
                )
            else:
                response = await ai_client._post_with_retry(
                    url, headers=headers,
                    json={"prompt": prompt, "metadata": metadata, **{
                        key: value for key, value in params.items() if value is not None
                    }},
                    retry_ambiguous=False,
                )
            if response.status_code >= 400:
                response.raise_for_status()
        except Exception as exc:
            _raise_safe_wire_phase_error("gateway_request", exc)
        try:
            data = response.json()
            if not isinstance(data, dict):
                raise ValueError("image response must be an object")
            refused = ai_client._is_refusal(data)
        except Exception as exc:
            _retain_ambiguous_hold()
            _raise_safe_wire_phase_error("response_json", exc)
        if refused:
            raise AIRefusalError(
                "AI image request was refused by gateway/provider",
                response_data=data, response_headers=response.headers, response=response,
            )
        try:
            image_bytes = await ai_client._decode_image_response(data)
        except asyncio.CancelledError:
            _retain_ambiguous_hold()
            raise
        except Exception as exc:
            _retain_ambiguous_hold()
            _raise_safe_decode_error(data, exc)
        return ProviderRawResult(
            image_bytes=image_bytes,
            mime="image/png",
            latency_ms=int((time.perf_counter() - started) * 1000),
            provider_request_id=data.get("provider_request_id") or data.get("id"), raw_response=data,
            response_headers=response.headers, request_params=params,
            actual_provider_model=(data.get("model") if isinstance(data.get("model"), str) else None),
        )



def _retain_ambiguous_hold() -> None:
    # A successful HTTP submission without a usable result still may be paid.
    from novel_to_comic.ai.context import current_ai_request_context
    from novel_to_comic.server.credits import retain_ambiguous_job
    retain_ambiguous_job(current_ai_request_context().job_id)


def serialize_wire_request(
    wire: ProviderWireRequest,
) -> tuple[dict[str, Any], list[tuple[str, tuple[str, bytes, str]]]]:
    """Serialize using the provider selected by the frozen wire request.

    Product aliases choose a model in the catalog; they do not choose the
    serializer. New providers add a key to ``_PROVIDER_SERIALIZERS`` without
    adding another model-name branch here.
    """
    serializer = _PROVIDER_SERIALIZERS.get(wire.provider_key)
    if serializer is None:
        raise ProviderWireError(
            f"unsupported image provider key: {wire.provider_key!r}"
        )
    params = serializer(wire)
    blobs = materialize_wire_references(wire)
    files = [
        ("image", (f"wire-ref-{ref.index}", data, _mime_type(Path(ref.source_path))))
        for ref, data in zip(wire.references, blobs, strict=True)
    ]
    return params, files


def _serialize_openai_image(wire: ProviderWireRequest) -> dict[str, Any]:
    """Serialize the OpenAI Images API envelope."""
    if "gpt-image-2.5-" in wire.configured_provider_model:
        quality = dict(wire.controls).get("quality", "auto")
        if quality not in {"auto", "low", "medium", "high", "xhigh", "max"}:
            raise ValueError("Unsupported GPT Image 2.5 quality")
        if not _valid_gpt_image_2_size(wire.width, wire.height):
            raise ValueError("Invalid GPT Image 2.5 dimensions; choose valid dimensions before generating")
    params = {
        "model": wire.requested_alias,
        "prompt": wire.prompt_parts[0],
        "size": _image_size(
            wire.configured_provider_model,
            wire.width,
            wire.height,
        ),
        "n": 1,
        **dict(wire.controls),
    }
    if wire.requested_alias in {"image-sunburst-openai", "image-flare"}:
        # The streaming OpenAI handler needs the frozen dimensions/controls;
        # LiteLLM removes standard Images fields for custom providers.
        params["canary_wire_request"] = wire.to_json()
    return params


def _serialize_openrouter_image(wire: ProviderWireRequest) -> dict[str, Any]:
    """Serialize the gateway envelope consumed by the OpenRouter image handler.

    The handler maps it to OpenRouter's native Images API. Muse has no
    advertised quality control, so its compiled profile normally supplies no
    controls; keep this serializer generic for future OpenRouter image aliases
    that do expose the shared quality field.
    """
    controls = dict(wire.controls)
    quality = controls.get("quality")
    if quality is not None and quality not in {"auto", "low", "medium", "high"}:
        raise ValueError("Unsupported OpenRouter image quality")
    return {
        "model": wire.requested_alias,
        "prompt": wire.prompt_parts[0],
        "size": _image_size(
            wire.configured_provider_model,
            wire.width,
            wire.height,
        ),
        "n": 1,
        **controls,
    }


def _serialize_canary_wire(wire: ProviderWireRequest) -> dict[str, Any]:
    """Serialize the manifest envelope consumed by custom LiteLLM handlers."""
    params: dict[str, Any] = {
        "model": wire.requested_alias,
        "prompt": wire.prompt_parts[0],
        # Keep generated bytes in the HTTP response. LiteLLM's URL default may
        # point at a proxy-local temporary file that the Canary process cannot
        # access (for example var/... across the Docker boundary).
        "response_format": "b64_json",
        "canary_wire_request": wire.to_json(),
        "canary_requested_width": wire.width,
        "canary_requested_height": wire.height,
        "canary_requested_aspect": aspect_for_dimensions(wire.width, wire.height),
        **dict(wire.controls),
    }
    if wire.structured_aspect is not None:
        params["aspect_ratio"] = wire.structured_aspect
    return params


# This registry is keyed by provider integration, not by product quality
# alias or concrete model version. Multiple providers can share the manifest
# serializer; a provider can register its own function when its gateway shape
# differs.
_PROVIDER_SERIALIZERS: dict[str, Callable[[ProviderWireRequest], dict[str, Any]]] = {
    IMAGE_PROVIDER_OPENAI: _serialize_openai_image,
    IMAGE_PROVIDER_OPENROUTER: _serialize_openrouter_image,
    IMAGE_PROVIDER_VERTEX_MULTIMODAL: _serialize_canary_wire,
    IMAGE_PROVIDER_FAL_QUEUE: _serialize_canary_wire,
    # Both Sunburst routes' gateway handlers consume the frozen manifest.
    IMAGE_PROVIDER_OPENAI_FAL: _serialize_canary_wire,
}


def _image_response_descriptor(data: dict[str, Any]) -> dict[str, Any]:
    """Return a redaction-safe shape summary for post-provider decode errors."""
    descriptor: dict[str, Any] = {"response_keys": sorted(data)}
    items = data.get("data")
    first = items[0] if isinstance(items, list) and items else None
    if not isinstance(first, dict):
        descriptor["item_type"] = type(first).__name__
        return descriptor
    descriptor["item_keys"] = sorted(first)
    b64 = first.get("b64_json")
    if isinstance(b64, str):
        descriptor["b64_length"] = len(b64)
    url = first.get("url")
    if isinstance(url, str):
        parsed = urlsplit(url)
        descriptor.update({
            "url_scheme": parsed.scheme,
            "url_host": parsed.hostname,
        })
    return descriptor


def _safe_decode_error_descriptor(exc: BaseException) -> dict[str, Any]:
    """Describe a decode failure without copying URLs or provider messages."""
    descriptor: dict[str, Any] = {"error_type": type(exc).__name__}
    errno = getattr(exc, "errno", None)
    if isinstance(errno, int):
        descriptor["errno"] = errno
    return descriptor


def _raise_safe_decode_error(data: dict[str, Any], exc: BaseException) -> None:
    descriptor = _image_response_descriptor(data)
    descriptor.update(_safe_decode_error_descriptor(exc))
    raise ValueError(
        f"image response decode failed ({json.dumps(descriptor, sort_keys=True)})"
    ) from None


def _raise_safe_wire_phase_error(phase: str, exc: BaseException) -> None:
    if isinstance(exc, AITransportError) and exc.phase == "ambiguous_submission":
        raise exc
    descriptor = {"phase": phase, **_safe_decode_error_descriptor(exc)}
    if phase == "gateway_request":
        if isinstance(exc, httpx.ReadError):
            descriptor["failure"] = "gateway disconnected before sending a response"
        elif isinstance(exc, httpx.ConnectError):
            descriptor["failure"] = "gateway connection could not be established"
        elif isinstance(exc, httpx.TimeoutException):
            descriptor["failure"] = "gateway request timed out"
    response = getattr(exc, "response", None)
    if response is not None:
        descriptor["status_code"] = response.status_code
        descriptor["reason"] = response.reason_phrase
        # The body is intentionally excluded: provider responses can contain
        # prompts, signed URLs, or other sensitive request context.
        try:
            body = response.json()
        except Exception:
            body = None
        if isinstance(body, dict):
            descriptor["response_keys"] = sorted(body)
            error = body.get("error")
            if isinstance(error, dict) and isinstance(error.get("code"), str):
                descriptor["provider_error_code"] = error["code"]
            if isinstance(error, dict) and isinstance(error.get("message"), str):
                message = " ".join(error["message"].split())
                # The proxy wraps custom-provider exceptions in a generic
                # HTTP 500. Copy only these bounded, structural FAL fields;
                # the full upstream message can include prompts or URLs.
                fal = re.search(
                    r"\bFAL (?P<phase>[a-z_]+) failed for "
                    r"(?P<endpoint>[a-zA-Z0-9_./-]+)"
                    r"(?:; request_id=(?P<request_id>[a-zA-Z0-9_-]+))?",
                    message,
                )
                # The streaming OpenAI handler's phase marker is bounded the
                # same way; the Sunburst fallback classifies failures by it.
                openai_marker = openai_image_failure_marker(message)
                if openai_marker:
                    descriptor["openai_failure"] = openai_marker
                if fal:
                    descriptor["fal_phase"] = fal.group("phase")
                    descriptor["fal_endpoint"] = fal.group("endpoint")
                    if fal.group("request_id"):
                        descriptor["fal_request_id"] = fal.group("request_id")
                marker = "Vertex image SDK does not support native aspect ratio controls"
                if marker in message:
                    detail = message[message.index(marker):]
                    detail = detail.split(". Received Model Group=", 1)[0]
                    descriptor["provider_detail"] = detail[:300]
    raise AITransportError(
        f"wire image transport failed ({json.dumps(descriptor, sort_keys=True)})",
        phase=phase,
        response=response if hasattr(response, "status_code") else None,
    ) from None


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

    # Thresholds map to OpenAI-supported sizes: portrait, square, landscape.
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
