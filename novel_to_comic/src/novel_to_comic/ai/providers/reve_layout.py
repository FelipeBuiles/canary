"""Direct Reve v2 layout renderer.

Reve's layout flow is a two-step contract: the application supplies a
structured layout and ``POST /v2/image/render_layout`` renders it. The
compiled provider wire has already resolved region reference bindings, so this
adapter only serializes immutable wire data and frozen reference bytes. It
does not rediscover files, select references, or rewrite prompt semantics.
"""

from __future__ import annotations

import base64
import binascii
import os
import time
from typing import Any

from novel_to_comic.ai.errors import AIRefusalError
from novel_to_comic.ai.providers.base import ProviderRawResult
from novel_to_comic.config import Config
from novel_to_comic.provider_wire import ProviderWireRequest

REVE_API_URL = "https://api.reve.com"
REVE_LAYOUT_ENDPOINT = "/v2/image/render_layout"
_MAX_REFERENCES = 8
_POSTPROCESSING = [{"process": "fit_image", "max_dim": 2048}]


def _api_base() -> str:
    return (os.environ.get("REVE_API_HOST") or REVE_API_URL).rstrip("/")


def _api_key() -> str:
    key = (os.environ.get("REVE_API_KEY") or os.environ.get("REVE_API_TOKEN") or "").strip()
    if not key:
        raise ValueError(
            "REVE_API_TOKEN or REVE_API_KEY is not set — layout-aware generation "
            "calls api.reve.com directly and needs a token in the pipeline server environment."
        )
    return key


def _headers() -> dict[str, str]:
    headers = {
        "Authorization": f"Bearer {_api_key()}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    proxy_authorization = os.environ.get("REVE_PROXY_AUTHORIZATION", "").strip()
    if proxy_authorization:
        headers["Proxy-Authorization"] = proxy_authorization
    return headers


class ReveLayoutProvider:
    """Transport for the exact Reve v2 layout render request."""

    name = "reve_layout"

    @staticmethod
    def request_params_for_wire(wire: ProviderWireRequest) -> dict[str, Any]:
        layout = wire.layout_payload() or {}
        return {
            "model": wire.requested_alias or wire.configured_provider_model,
            "endpoint": REVE_LAYOUT_ENDPOINT,
            "size": f"{wire.width}x{wire.height}",
            "aspect_ratio": wire.structured_aspect,
            "reference_count": len(wire.references),
            "layout_region_count": len(layout.get("regions", [])),
            "layout_frame": {
                "width": layout.get("width"),
                "height": layout.get("height"),
            },
            "postprocessing": [*(_POSTPROCESSING)],
        }

    async def generate_wire(
        self,
        *,
        wire: ProviderWireRequest,
        reference_bytes: tuple[bytes, ...],
        config: Config,  # noqa: ARG002
        event_id: str,  # noqa: ARG002
        metadata: dict[str, Any],  # noqa: ARG002
    ) -> ProviderRawResult:
        """Render the frozen layout with the frozen ordered reference bytes."""
        if not wire.layout or not wire.layout.get("regions"):
            raise ValueError("ReveLayoutProvider requires a non-empty layout")
        if len(reference_bytes) != len(wire.references):
            raise ValueError("wire references and materialized bytes are not one-to-one")
        if len(reference_bytes) > _MAX_REFERENCES:
            raise ValueError(
                f"Reve layout render accepts at most {_MAX_REFERENCES} references"
            )

        layout_payload = wire.layout_payload()
        if layout_payload is None:
            raise ValueError("ReveLayoutProvider requires a layout object")
        payload: dict[str, Any] = {
            "layout": layout_payload,
            # v2 layout output is substantially larger than the panel asset
            # needs. Keep the high-resolution coordinate frame for layout
            # fidelity, then cap the returned bitmap before it reaches storage.
            "postprocessing": [*(_POSTPROCESSING)],
        }
        if reference_bytes:
            payload["references"] = [
                {
                    "image": {"data": base64.b64encode(data).decode("ascii")},
                    # The compiler's exact role/authority instruction is the
                    # descriptive prompt for this compound reference.
                    "prompt": ref.instruction,
                }
                for ref, data in zip(wire.references, reference_bytes, strict=True)
            ]

        from novel_to_comic.ai import client as ai_client

        started = time.perf_counter()
        try:
            response = await ai_client._post_with_retry(
                f"{_api_base()}{REVE_LAYOUT_ENDPOINT}",
                headers=_headers(),
                json=payload,
            )
        except Exception:
            # Preserve the provider response on HTTPStatusError so the shared
            # finalization path can classify/refuse it without logging payloads.
            raise

        data: dict[str, Any] = {}
        try:
            parsed = response.json()
            if isinstance(parsed, dict):
                data = parsed
        except Exception:
            pass

        if _is_content_violation(data):
            raise AIRefusalError(
                "Reve flagged a content violation for this panel",
                response_data={key: value for key, value in data.items() if key != "image"},
                response_headers=response.headers,
                response=response,
            )
        if response.status_code >= 400:
            response.raise_for_status()

        image_bytes = _decode_image(data.get("image"))
        if not image_bytes:
            raise ValueError(
                "Reve v2 render response contained no image "
                f"(request_id={data.get('request_id')})"
            )

        raw_response = {key: value for key, value in data.items() if key != "image"}
        layout_echo = data.get("layout") if isinstance(data.get("layout"), dict) else None
        version = data.get("version") if isinstance(data.get("version"), str) else None
        return ProviderRawResult(
            image_bytes=image_bytes,
            mime="image/png",
            latency_ms=int((time.perf_counter() - started) * 1000),
            provider_request_id=data.get("request_id"),
            raw_response=raw_response,
            response_headers=response.headers,
            request_params=self.request_params_for_wire(wire),
            layout_echo=layout_echo,
            actual_provider_model=version,
        )


def _is_content_violation(data: dict[str, Any]) -> bool:
    value = data.get("content_violation")
    if isinstance(value, bool):
        return value
    return str(value or "").lower() in {"true", "1", "yes"}


def _decode_image(value: Any) -> bytes:
    if not isinstance(value, str) or not value:
        return b""
    encoded = value.split(",", 1)[1] if value.startswith("data:") and "," in value else value
    try:
        return base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError):
        raise ValueError("Reve v2 render response contained invalid image data") from None


__all__ = ["REVE_API_URL", "REVE_LAYOUT_ENDPOINT", "ReveLayoutProvider"]
