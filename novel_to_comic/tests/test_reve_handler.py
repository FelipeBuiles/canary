"""LiteLLM Reve handler: v1 wire format for create and remix.

Regression coverage for the UNRECOGNIZED_PARAMETER 400: Reve's create endpoint
has no exact-pixel sizing, so width/height must never appear in the payload —
exact requested dimensions only refine the aspect_ratio choice.
"""

import asyncio
import base64
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from litellm_handlers.reve_provider import (  # noqa: E402
    ImageResponse,
    reve_llm,
)

_PNG_B64 = base64.b64encode(b"\x89PNG\r\n\x1a\nfakepng").decode("ascii")


class _MockResponse:
    status_code = 200

    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload

    def raise_for_status(self):
        pass


def _capture_post(monkeypatch, payload=None):
    captured = {}

    async def mock_post(client, url, **kwargs):
        captured["url"] = url
        captured["payload"] = kwargs.get("json")
        return _MockResponse(payload or {"image": _PNG_B64, "request_id": "req_1"})

    monkeypatch.setattr("httpx.AsyncClient.post", mock_post)
    monkeypatch.setenv("REVE_API_KEY", "test_key")
    return captured


def test_create_never_sends_pixel_dimensions(monkeypatch):
    captured = _capture_post(monkeypatch)
    asyncio.run(reve_llm.aimage_generation(
        model="reve/create",
        prompt="a quiet stable interior",
        api_key="test_key",
        api_base=None,
        model_response=ImageResponse(),
        optional_params={
            "size": "1024x1024",
            "quality": "medium",
            "canary_requested_width": 819,
            "canary_requested_height": 1024,
        },
        logging_obj=None,
    ))
    assert captured["url"] == "https://api.reve.com/v1/image/create"
    payload = captured["payload"]
    assert payload["prompt"] == "a quiet stable interior"
    # Exact dims refine the aspect ratio but are never sent as parameters.
    assert payload["aspect_ratio"] == "3:4"
    assert payload["quality"] == "medium"
    assert "width" not in payload
    assert "height" not in payload


def test_create_truncates_prompt_to_8000(monkeypatch):
    captured = _capture_post(monkeypatch)
    asyncio.run(reve_llm.aimage_generation(
        model="reve/create",
        prompt="x" * 9000,
        api_key="test_key",
        api_base=None,
        model_response=ImageResponse(),
        optional_params={"size": "1024x1024"},
        logging_obj=None,
    ))
    assert len(captured["payload"]["prompt"]) == 8000


def test_remix_uploads_references_with_indexed_instructions(monkeypatch):
    captured = _capture_post(monkeypatch)
    image_bytes = b"\x89PNG\r\n\x1a\nrefbytes"
    files = [
        ("__role_subject__char_alice_front.png", image_bytes),
        ("__role_style__style_inkwash.png", image_bytes),
    ]
    asyncio.run(reve_llm.aimage_edit(
        model="reve/remix",
        image=files,
        prompt="Alice reads in the library.",
        model_response=ImageResponse(),
        api_key="test_key",
        optional_params={"size": "1024x1536"},
    ))
    assert captured["url"] == "https://api.reve.com/v1/image/remix"
    payload = captured["payload"]
    assert payload["reference_images"] == [base64.b64encode(image_bytes).decode("ascii")] * 2
    assert "width" not in payload
    assert "height" not in payload
    # No tags in the incoming prompt → the handler injects the indexed block.
    assert payload["prompt"].startswith("Reference images:\n")
    assert "Use <img>0</img>: Character identity reference for Alice" in payload["prompt"]
    assert "Use <img>1</img>: Art style reference" in payload["prompt"]
    assert payload["prompt"].endswith("Alice reads in the library.")


def test_remix_keeps_prompt_with_existing_tags(monkeypatch):
    captured = _capture_post(monkeypatch)
    files = [("__role_subject__char_alice_front.png", b"refbytes")]
    prompt = "Use <img>0</img> as the identity reference for Alice.\n\nAlice reads."
    asyncio.run(reve_llm.aimage_edit(
        model="reve/remix",
        image=files,
        prompt=prompt,
        model_response=ImageResponse(),
        api_key="test_key",
        optional_params={"size": "1024x1536"},
    ))
    assert captured["payload"]["prompt"] == prompt


def test_content_violation_raises(monkeypatch):
    _capture_post(monkeypatch, payload={"content_violation": True, "request_id": "req_v"})
    with pytest.raises(ValueError, match="content violation"):
        asyncio.run(reve_llm.aimage_generation(
            model="reve/create",
            prompt="p",
            api_key="test_key",
            api_base=None,
            model_response=ImageResponse(),
            optional_params={"size": "1024x1024"},
            logging_obj=None,
        ))
