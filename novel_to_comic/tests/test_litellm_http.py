import pytest

from novel_to_comic.ai.providers.litellm_http import serialize_wire_request
from novel_to_comic.image_models import ImageRoute
from novel_to_comic.provider_wire import (
    PROVIDER_WIRE_DISCRIMINATOR,
    PROVIDER_WIRE_SCHEMA_VERSION,
    ProviderWireError,
    ProviderWireRequest,
)


def _wire(
    *,
    alias: str,
    route: ImageRoute,
    provider_key: str,
    provider_model: str,
    structured_aspect: str | None = None,
) -> ProviderWireRequest:
    request = ProviderWireRequest(
        discriminator=PROVIDER_WIRE_DISCRIMINATOR,
        schema_version=PROVIDER_WIRE_SCHEMA_VERSION,
        requested_alias=alias,
        expected_route=route.value,
        provider_key=provider_key,
        configured_provider_model=provider_model,
        prompt_parts=("A test image",),
        references=(),
        width=1024,
        height=1536,
        structured_aspect=structured_aspect,
        controls=(("quality", "medium"),),
        compiled_request_sha256="compiled",
        execution_fingerprint="execution",
    )
    return request


def test_gpt_image_2_wire_request_uses_openai_image_api_fields():
    params, files = serialize_wire_request(
        _wire(
            alias="image-gpt-2",
            route=ImageRoute.GPT_IMAGE_2,
            provider_key="openai",
            provider_model="openai/gpt-image-2",
            structured_aspect="portrait",
        )
    )

    assert files == []
    assert params == {
        "model": "image-gpt-2",
        "prompt": "A test image",
        "size": "1024x1536",
        "n": 1,
        "quality": "medium",
    }


def test_muse_wire_request_uses_openrouter_image_fields():
    params, files = serialize_wire_request(
        _wire(
            alias="image-muse",
            route=ImageRoute.MUSE_IMAGE,
            provider_key="openrouter",
            provider_model="openrouter/meta/muse-image",
        )
    )

    assert files == []
    assert params == {
        "model": "image-muse",
        "prompt": "A test image",
        "size": "1024x1536",
        "n": 1,
        "quality": "medium",
    }


def test_custom_image_routes_keep_the_wire_manifest_for_handlers():
    params, files = serialize_wire_request(
        _wire(
            alias="image-gemini-pro",
            route=ImageRoute.GEMINI_PRO_IMAGE,
            provider_key="vertex-multimodal",
            provider_model="vertex_ai/gemini-3-pro-image",
            structured_aspect="portrait",
        )
    )

    assert files == []
    assert params["canary_wire_request"]
    assert params["canary_requested_width"] == 1024
    assert params["canary_requested_height"] == 1536
    assert params["canary_requested_aspect"] == 2 / 3
    assert params["aspect_ratio"] == "portrait"


def test_provider_key_controls_serializer_when_model_version_changes():
    params, files = serialize_wire_request(
        _wire(
            alias="image-gpt-2",
            route=ImageRoute.UNKNOWN,
            provider_key="openai",
            provider_model="openai/future-image-model",
        )
    )

    assert files == []
    assert params["size"] == "1024x1536"
    assert "canary_wire_request" not in params
    assert "response_format" not in params


def test_unknown_provider_key_fails_closed():
    with pytest.raises(ProviderWireError, match="unsupported image provider key"):
        serialize_wire_request(
            _wire(
                alias="future-quality",
                route=ImageRoute.UNKNOWN,
                provider_key="future-provider",
                provider_model="future/model",
            )
        )


@pytest.mark.parametrize("failure", ["decode", "cancel", "json", "shape", "refusal"])
def test_accepted_wire_result_retains_hold_unless_known_refusal(monkeypatch, failure):
    import asyncio
    import httpx
    from unittest.mock import AsyncMock, MagicMock
    from novel_to_comic.ai import client
    from novel_to_comic.ai.context import ai_request_context
    from novel_to_comic.ai.providers.litellm_http import LitellmHttpProvider
    from novel_to_comic.config import Config
    from novel_to_comic.server import credits

    monkeypatch.setattr(credits, "_unsettled_jobs", set())
    monkeypatch.setattr(credits, "_reservation_jobs", {"hold": "job"})
    wire = _wire(alias="image-gpt-2", route=ImageRoute.GPT_IMAGE_2,
                 provider_key="openai", provider_model="openai/gpt-image-2")
    response = httpx.Response(200, content=b"bad" if failure == "json" else b"{}")
    if failure == "shape":
        response = httpx.Response(200, json=[])
    post = AsyncMock(return_value=response)
    monkeypatch.setattr(client, "_post_with_retry", post)
    monkeypatch.setattr(client, "_is_refusal", lambda _: failure == "refusal")
    decode = AsyncMock(side_effect=asyncio.CancelledError() if failure == "cancel" else ValueError("decode failed"))
    monkeypatch.setattr(client, "_decode_image_response", decode)
    async def run():
        with ai_request_context(job_id="job"):
            with pytest.raises((ValueError, asyncio.CancelledError, client.AIRefusalError)):
                await LitellmHttpProvider().generate_wire(wire=wire, config=Config(), event_id="event", metadata={})
    asyncio.run(run())
    assert post.await_count == 1
    assert post.call_args.kwargs["retry_ambiguous"] is False
    db = MagicMock()
    credits.release_reservation(db, "hold")
    if failure == "refusal":
        assert "job" not in credits._unsettled_jobs
        db.rpc.assert_called_once()
    else:
        assert "job" in credits._unsettled_jobs
        db.rpc.assert_not_called()


def test_wire_wrapper_preserves_ambiguous_transport_phase():
    from novel_to_comic.ai.errors import AITransportError
    from novel_to_comic.ai.providers.litellm_http import _raise_safe_wire_phase_error
    error = AITransportError("Outcome unknown", phase="ambiguous_submission")
    with pytest.raises(AITransportError) as captured:
        _raise_safe_wire_phase_error("gateway_request", error)
    assert captured.value is error
    assert captured.value.phase == "ambiguous_submission"


def test_wire_error_reports_safe_fal_phase_and_request_id():
    import httpx
    from novel_to_comic.ai.errors import AITransportError
    from novel_to_comic.ai.providers.litellm_http import _raise_safe_wire_phase_error

    response = httpx.Response(500, json={"error": {
        "code": "500",
        "message": (
            "litellm.InternalServerError: Fal-queueException - FAL result failed "
            "for openai/gpt-image-2.5/sunburst/text-to-image; request_id=req-123; "
            "detail=see https://example.invalid/signed?token=secret and prompt text"
        ),
    }})
    error = httpx.HTTPStatusError(
        "gateway error",
        request=httpx.Request("POST", "https://gateway.invalid/v1/images/generations"),
        response=response,
    )

    with pytest.raises(AITransportError) as captured:
        _raise_safe_wire_phase_error("gateway_request", error)

    message = str(captured.value)
    assert '"fal_phase": "result"' in message
    assert '"fal_request_id": "req-123"' in message
    assert "signed" not in message
    assert "prompt text" not in message


@pytest.mark.parametrize("endpoint", ["generations", "edits"])
@pytest.mark.parametrize("wrapped", [False, True])
def test_wire_error_identifies_missing_gateway_model_without_copying_response(endpoint, wrapped):
    import httpx
    from novel_to_comic.ai.errors import AITransportError
    from novel_to_comic.ai.providers.litellm_http import _raise_safe_wire_phase_error
    from novel_to_comic.image_failure import classify_image_failure

    detail = (
        f"/image/{endpoint}: Invalid model name passed in model=image-nano-banana-2.1. "
        "Call `/v1/models` to view available models for your key."
    )
    error = {"message": str({"error": detail}) + " private prompt https://example.invalid/?token=secret",
             "code": "400"} if wrapped else detail
    response = httpx.Response(400, json={"error": error, "private": "sensitive request context"})
    with pytest.raises(AITransportError) as captured:
        _raise_safe_wire_phase_error("gateway_request", httpx.HTTPStatusError(
            "gateway error", request=httpx.Request("POST", f"https://gateway.invalid/v1/images/{endpoint}"),
            response=response,
        ))

    message = str(captured.value)
    assert captured.value.phase == "gateway_request"
    assert captured.value.response is response
    assert '"gateway_failure": "model_not_loaded"' in message
    assert '"model_alias": "image-nano-banana-2.1"' in message
    assert "reload the gateway configuration" in message
    assert classify_image_failure(captured.value) == "configuration_error"
    assert "private prompt" not in message
    assert "sensitive request context" not in message
    assert "https://" not in message
    assert "secret" not in message


def test_wire_error_does_not_treat_every_bad_request_as_a_missing_model():
    import httpx
    from novel_to_comic.ai.errors import AITransportError
    from novel_to_comic.ai.providers.litellm_http import _raise_safe_wire_phase_error

    response = httpx.Response(400, json={"error": {"message": "invalid quality; private prompt", "code": "400"}})
    with pytest.raises(AITransportError) as captured:
        _raise_safe_wire_phase_error("gateway_request", httpx.HTTPStatusError(
            "gateway error", request=httpx.Request("POST", "https://gateway.invalid/v1/images/generations"),
            response=response,
        ))
    assert "model_not_loaded" not in str(captured.value)
    assert "private prompt" not in str(captured.value)
