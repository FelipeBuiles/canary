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
            alias="image-quality",
            route=ImageRoute.GPT_IMAGE_2,
            provider_key="openai",
            provider_model="openai/gpt-image-2",
            structured_aspect="portrait",
        )
    )

    assert files == []
    assert params == {
        "model": "image-quality",
        "prompt": "A test image",
        "size": "1024x1536",
        "n": 1,
        "quality": "medium",
    }


def test_custom_image_routes_keep_the_wire_manifest_for_handlers():
    params, files = serialize_wire_request(
        _wire(
            alias="image-balanced",
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
            alias="image-quality",
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
