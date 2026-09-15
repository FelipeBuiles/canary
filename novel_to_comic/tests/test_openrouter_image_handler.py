"""Native OpenRouter Images API adapter contract."""

import base64

import pytest
import httpx

from litellm_handlers.openrouter_image import (
    _build_payload,
    _headers,
    _image_b64,
    _provider_http_error,
)


def test_openrouter_image_payload_uses_native_images_api_shape():
    payload = _build_payload(
        "openrouter-image/meta/muse-image",
        "A test image",
        [("reference.jpg", b"reference-bytes", "image/jpeg")],
        {"size": "1024x1280", "n": 1},
    )

    assert payload["model"] == "meta/muse-image"
    assert payload["prompt"] == "A test image"
    assert payload["size"] == "1024x1280"
    assert payload["n"] == 1
    assert payload["input_references"] == [{
        "type": "image_url",
        "image_url": {
            "url": "data:image/jpeg;base64," + base64.b64encode(b"reference-bytes").decode(),
        },
    }]


def test_openrouter_reference_declares_webp_when_artifact_uses_png_name():
    # Stable pipeline artifact names need not match a provider's output codec.
    webp = b"RIFF\x00\x00\x00\x00WEBPVP8 "
    payload = _build_payload(
        "openrouter-image/meta/muse-image",
        "A test image",
        [("style_1.png", webp, "image/png")],
        {},
    )

    assert payload["input_references"][0]["image_url"]["url"].startswith("data:image/webp;base64,")


def test_openrouter_image_response_requires_base64_image():
    assert _image_b64({"data": [{"b64_json": "encoded"}]}) == "encoded"
    with pytest.raises(ValueError, match="missing data\\[0\\].b64_json"):
        _image_b64({"data": [{}]})


def test_openrouter_image_requires_provider_api_key(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    with pytest.raises(ValueError, match="OPENROUTER_API_KEY"):
        _headers(None)
    assert _headers("test-key")["Authorization"] == "Bearer test-key"


def test_openrouter_known_provider_rejection_keeps_its_http_status():
    response = httpx.Response(400, text="bad reference", request=httpx.Request("POST", "https://openrouter.ai"))

    error = _provider_http_error(response, "openrouter-image/meta/muse-image")

    assert getattr(error, "status_code", None) == 400
    assert "OpenRouter image generation failed (400)" in str(error)
