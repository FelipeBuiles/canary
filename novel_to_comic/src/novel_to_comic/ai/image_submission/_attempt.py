"""One accounted image submission on one gateway route."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

import httpx

from novel_to_comic.ai import client as ai_client
from novel_to_comic.ai import finalisation
from novel_to_comic.ai.context import mark_generation_executing
from novel_to_comic.ai.errors import AIRefusalError
from novel_to_comic.ai.image_submission._envelopes import (
    CALL_METADATA,
    GatewayCall,
    PageSettlement,
)
from novel_to_comic.ai.image_submission._page_result import VerifiedPage, settle_page_image, verify_page_image
from novel_to_comic.ai.providers.base import ProviderRawResult
from novel_to_comic.ai.providers.litellm_http import _raise_safe_decode_error, _raise_safe_wire_phase_error
from novel_to_comic.config import Config
from novel_to_comic.image_route_fallback import Surface
from novel_to_comic.models.draw import CompletePageProviderResult
from novel_to_comic.usage import ApiResult


class CallAuthorization(Enum):
    """Who guarantees the credits one submission may spend."""

    PER_CALL_GUARANTEE = "per_call_guarantee"
    """Look. ``authorize_model_call`` takes a guarantee after the usage event
    starts and before the POST; a refusal there fails the call unspent."""

    JOB_RESERVATION = "job_reservation"
    """Draw. Each page is its own reserved job whose hold covers the call, so
    no guarantee is taken. A failed call's finalisation still releases the
    guarantee it never took."""


class ErrorDetail(Enum):
    """How much provider text a surface's errors and usage events carry.

    Stored error text differs per surface, so the two styles stay apart.
    """

    BOUNDED = "bounded"
    """Draw. Gateway errors keep a bounded provider message, decode errors
    propagate as raised, and a failed call records the HTTP response."""

    REDACTED = "redacted"
    """Look. Every failure is reduced to a structural descriptor, a refusal is
    an ``AIRefusalError``, and a failed call records only the response its
    error carries."""


@dataclass(frozen=True, slots=True)
class SubmissionSurface:
    name: Surface
    authorization: CallAuthorization
    errors: ErrorDetail


DRAW_PAGE = SubmissionSurface("draw", CallAuthorization.JOB_RESERVATION, ErrorDetail.BOUNDED)
LOOK_ASSET = SubmissionSurface("asset", CallAuthorization.PER_CALL_GUARANTEE, ErrorDetail.REDACTED)


@dataclass(slots=True)
class _Received:
    """What the gateway has returned so far, for the retention rule and the
    failure record when a later step fails."""

    response: httpx.Response | None = None
    payload: Any = None


async def attempt(
    call: GatewayCall, surface: SubmissionSurface, config: Config,
) -> CompletePageProviderResult | ApiResult[Path]:
    """Submit ``call`` once and settle its usage event. The only image POST."""
    ctx = await finalisation.begin_image_call(
        config=config, model=call.accounting_model, feature=call.feature,
        prompt=call.prompt, params=call.event_params, ref_reads=call.ref_reads,
    )
    received = _Received()

    async def send() -> httpx.Response:
        received.response = await _post(call, ctx, config)
        return received.response

    try:
        if surface.authorization is CallAuthorization.PER_CALL_GUARANTEE:
            await ai_client._authorize_model_submission(
                event_id=ctx.event_id, estimated_cost_usd=ctx.estimated_cost_usd,
                funding=ctx.metadata.get("funding", "api"), config=config,
            )
        # Telemetry only: a serialized runtime marks again when its queue releases.
        mark_generation_executing()
        image_bytes = await _READERS[surface.errors](call, received, send)
        verified = _verify(call, ctx, received, image_bytes)
    except BaseException as exc:
        retain_incomplete_response(received.response, received.payload)
        finalise = finalisation.finalise_image_failure
        if isinstance(exc, asyncio.CancelledError):
            finalise = finalisation.finalise_image_cancelled
        elif surface.authorization is CallAuthorization.JOB_RESERVATION:
            # No call guarantee names this attempt, so a fallback coordinator
            # reads the usage event it absorbs from the exception.
            _tag_usage_event(exc, ctx.event_id)
        await finalise(
            ctx=ctx, config=config, model=call.accounting_model, feature=call.feature, error=exc,
            error_response=(
                received.response if surface.errors is ErrorDetail.BOUNDED else getattr(exc, "response", None)
            ),
        )
        raise
    # Settlement runs outside the catcher: it owns its own failure record, and
    # a second terminal write here would overwrite it.
    if isinstance(verified, VerifiedPage):
        return await settle_page_image(call, ctx, verified, received.response, config)
    return await finalisation.finalise_image_success(
        ctx=ctx, config=config, model=call.accounting_model, feature=call.feature,
        output_path=call.settlement.output_path, raw=verified,
    )


async def _post(call: GatewayCall, ctx: finalisation.ImageCallContext, config: Config) -> httpx.Response:
    from novel_to_comic.ai.image_previews import post_image_request

    multipart = bool(call.files)
    metadata = ai_client._json_dumps(ctx.metadata) if multipart else ctx.metadata
    fields = {key: metadata if value is CALL_METADATA else value for key, value in call.fields.items()}
    url = f"{ai_client._base_url(config)}{call.endpoint}"
    headers = ai_client._headers(config, ctx.event_id)
    if multipart:
        return await post_image_request(
            url, headers=headers, data=fields, files=call.files, target=call.preview_target,
        )
    return await post_image_request(url, headers=headers, json=fields, target=call.preview_target)


async def _read_bounded(
    call: GatewayCall, received: _Received, send: Callable[[], Awaitable[httpx.Response]],
) -> bytes:
    response = await send()
    if response.status_code >= 400:
        raise ai_client._gateway_http_error(
            response, feature=call.feature, model=call.request_model, endpoint=call.endpoint,
        )
    received.payload = response.json()
    return await ai_client._decode_image_response(received.payload)


async def _read_redacted(
    call: GatewayCall, received: _Received, send: Callable[[], Awaitable[httpx.Response]],
) -> bytes:
    try:
        response = await send()
        if response.status_code >= 400:
            response.raise_for_status()
    except Exception as exc:
        _raise_safe_wire_phase_error("gateway_request", exc)
    try:
        received.payload = data = response.json()
        if not isinstance(data, dict):
            raise ValueError("image response must be an object")
        refused = ai_client._is_refusal(data)
    except Exception as exc:
        _raise_safe_wire_phase_error("response_json", exc)
    if refused:
        raise AIRefusalError(
            "AI image request was refused by gateway/provider",
            response_data=data, response_headers=response.headers, response=response,
        )
    try:
        return await ai_client._decode_image_response(data)
    except Exception as exc:
        _raise_safe_decode_error(data, exc)


_READERS = {ErrorDetail.BOUNDED: _read_bounded, ErrorDetail.REDACTED: _read_redacted}


def _verify(
    call: GatewayCall, ctx: finalisation.ImageCallContext, received: _Received, image_bytes: bytes,
) -> VerifiedPage | ProviderRawResult:
    response, payload = received.response, received.payload
    if isinstance(call.settlement, PageSettlement):
        return verify_page_image(call, call.settlement, ctx, response, payload, image_bytes)
    model = payload.get("model")
    return ProviderRawResult(
        image_bytes=image_bytes,
        provider_request_id=payload.get("provider_request_id") or payload.get("id"),
        raw_response=payload,
        response_headers=response.headers,
        actual_provider_model=model if isinstance(model, str) else None,
    )


def retain_incomplete_response(response: httpx.Response | None, payload: Any) -> None:
    """Keep the job hold for reconciliation when an accepted response did not
    end in a usable image, unless the provider is known to have refused."""
    from novel_to_comic.server.credits import retain_ambiguous_job

    if response is None or response.status_code >= 400:
        return
    try:
        refused = isinstance(payload, dict) and ai_client._is_refusal(payload)
    except Exception:
        refused = False  # Malformed refusal fields are not a known refusal.
    if not refused:
        retain_ambiguous_job(ai_client.current_ai_request_context().job_id)


def _tag_usage_event(exc: BaseException, event_id: str) -> None:
    if not hasattr(exc, "canary_usage_event_id"):
        try:
            exc.canary_usage_event_id = event_id  # type: ignore[attr-defined]
        except AttributeError:
            pass
