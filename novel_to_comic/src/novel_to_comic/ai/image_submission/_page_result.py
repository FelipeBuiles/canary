"""Draw settlement: verify a returned page against its frozen request, then record it."""

from __future__ import annotations

import io
import time
from dataclasses import dataclass
from typing import Any

import httpx

from novel_to_comic.ai import client as ai_client
from novel_to_comic.ai import finalisation
from novel_to_comic.ai.image_submission._envelopes import GatewayCall, PageSettlement
from novel_to_comic.config import Config
from novel_to_comic.models.draw import CompletePageProviderResult
from novel_to_comic.usage import UsageRecord

# Per route provider: its label in errors and the suffixes its response may
# add to the frozen model. Vertex's check runs after settlement, in Draw.
_ACCEPTED_RESPONSE_MODELS = {
    "openai": ("OpenAI", ("", "-2026-09-08")),
    "fal-queue": ("FAL", ("", "/text-to-image", "/edit")),
    "runware": ("Runware", ("",)),
    "openrouter": ("OpenRouter", ("",)),
}


@dataclass(frozen=True, slots=True)
class VerifiedPage:
    image_bytes: bytes
    width: int
    height: int
    latency_ms: int
    usage: UsageRecord
    actual_provider_model: str
    provider_request_id: str | None
    response_data: dict[str, Any]


def verify_page_image(
    call: GatewayCall, settlement: PageSettlement, ctx: finalisation.ImageCallContext,
    response: httpx.Response, payload: dict[str, Any], image_bytes: bytes,
) -> VerifiedPage:
    from PIL import Image

    with Image.open(io.BytesIO(image_bytes)) as image:
        source_format = image.format
        if source_format not in {"PNG", "JPEG", "WEBP"}:
            raise ValueError("Complete-page output must be PNG, JPEG, or WebP")
        width, height = image.size
        # Muse does not advertise a supported output-format control,
        # and OpenRouter may therefore return a valid JPEG or WebP.
        # The frozen edition still promises a PNG artifact, so
        # normalize successful raster output locally rather than
        # rejecting a completed, chargeable image submission.
        if source_format != "PNG":
            image.load()
            normalized = io.BytesIO()
            image.save(normalized, format="PNG")
            image_bytes = normalized.getvalue()
    if (width, height) != (settlement.width, settlement.height):
        raise ValueError(
            "Complete-page output dimensions do not match frozen profile: "
            f"actual={width}x{height} expected={settlement.width}x{settlement.height}"
        )
    latency_ms = int((time.perf_counter() - ctx.started) * 1000)
    route = call.route
    usage = finalisation.with_request_estimate(
        ai_client._extract_usage(payload, ctx.event_id, route.gateway_model, "image", response.headers), ctx,
    )
    response_model = str(payload.get("model") or "")
    route_model = route.provider_model or call.request_model
    route_prefix = "vertex_ai" if route.provider == "vertex-multimodal" else route.provider
    actual_provider_model = (
        f"{route_prefix}/{route_model}"
        if response_model == route.gateway_model
        else response_model or f"{route_prefix}/{route_model}"
    )
    if route.provider in _ACCEPTED_RESPONSE_MODELS:
        label, suffixes = _ACCEPTED_RESPONSE_MODELS[route.provider]
        if actual_provider_model.removeprefix(f"{route.provider}/") not in {
            route_model + suffix for suffix in suffixes
        }:
            raise ValueError(f"{label} response model does not match frozen page profile")
    return VerifiedPage(
        image_bytes=image_bytes, width=width, height=height, latency_ms=latency_ms,
        usage=usage.model_copy(update={
            "model": route.gateway_model,
            "provider_model": actual_provider_model,
            "provider": route.provider,
        }),
        actual_provider_model=actual_provider_model,
        provider_request_id=payload.get("provider_request_id") or payload.get("id"),
        response_data={
            **{key: value for key, value in payload.items() if key != "data"},
            "model": actual_provider_model,
        },
    )


async def settle_page_image(
    call: GatewayCall, ctx: finalisation.ImageCallContext, page: VerifiedPage,
    response: httpx.Response, config: Config,
) -> CompletePageProviderResult:
    # Only real errors route to failure here. The success write is shielded,
    # so a cancel landing mid-write waits it out and then propagates without
    # a second terminal write overwriting success.
    try:
        await ai_client._finalize_event_shielded(
            event_id=ctx.event_id,
            status="succeeded",
            feature=call.feature,
            model_alias=call.accounting_model,
            latency_ms=page.latency_ms,
            usage=page.usage,
            response_data=page.response_data,
            config=config,
            operation=ctx.operation,
            metadata=ctx.metadata,
            estimated_cost_usd=ctx.estimated_cost_usd,
            expected_cost_usd=ctx.settlement_estimate_usd,
            started_at=ctx.started_at,
        )
    except Exception as exc:
        await finalisation.finalise_image_failure(
            ctx=ctx, config=config, model=call.accounting_model, feature=call.feature,
            error=exc, error_response=response,
        )
        raise
    return CompletePageProviderResult(
        artifact_kind="complete_page",
        image_bytes=page.image_bytes,
        media_type="image/png",
        width=page.width,
        height=page.height,
        latency_ms=page.latency_ms,
        provider_request_id=page.provider_request_id,
        actual_provider_model=page.actual_provider_model,
        usage=page.usage,
    )
