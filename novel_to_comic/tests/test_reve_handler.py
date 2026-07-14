"""LiteLLM Reve handler: ordinary v2 create wire format.

The application uses the direct adapter for layout-enabled panels. This file
covers the v2 create fallback used for ordinary generation/edit requests.
"""

import asyncio
import base64
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

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


def test_create_uses_v2_prompt_aspect_and_fit_postprocessing(monkeypatch, tmp_path):
    from test_provider_wire import _compiled
    from novel_to_comic.image_models import GATEWAY_IMAGE_REVE
    from novel_to_comic.provider_wire import compile_provider_wire_request

    captured = _capture_post(monkeypatch)
    wire = compile_provider_wire_request(
        _compiled(tmp_path, model=GATEWAY_IMAGE_REVE, count=0)
    )
    asyncio.run(reve_llm.aimage_generation(
        model="reve/create",
        prompt="ignored: wire owns the prompt",
        api_key="test_key",
        api_base=None,
        model_response=ImageResponse(),
        optional_params={
            "canary_wire_request": wire.to_json(),
        },
        logging_obj=None,
    ))
    assert captured["url"] == "https://api.reve.com/v2/image/create"
    payload = captured["payload"]
    assert payload["prompt"] == wire.prompt_parts[0]
    assert payload["aspect_ratio"] == "9:16"
    assert payload["postprocessing"] == [{"process": "fit_image", "max_dim": 2048}]
    assert "width" not in payload
    assert "height" not in payload


def test_edit_uses_v2_raw_references_and_frame_markers(monkeypatch, tmp_path):
    from test_provider_wire import _compiled
    from novel_to_comic.image_models import GATEWAY_IMAGE_REVE
    from novel_to_comic.provider_wire import compile_provider_wire_request

    captured = _capture_post(monkeypatch)
    wire = compile_provider_wire_request(
        _compiled(tmp_path, model=GATEWAY_IMAGE_REVE, count=2)
    )
    files = [
        (str(ref.source_path), Path(ref.source_path).read_bytes())
        for ref in wire.references
    ]
    asyncio.run(reve_llm.aimage_edit(
        model="reve/create",
        image=files,
        prompt="ignored: wire owns the prompt",
        model_response=ImageResponse(),
        api_key="test_key",
        optional_params={"canary_wire_request": wire.to_json()},
    ))
    assert captured["url"] == "https://api.reve.com/v2/image/create"
    payload = captured["payload"]
    assert [reference.keys() for reference in payload["references"]] == [
        {"data"}, {"data"}
    ]
    assert [reference["data"] for reference in payload["references"]] == [
        base64.b64encode(Path(ref.source_path).read_bytes()).decode("ascii")
        for ref in wire.references
    ]
    assert "<frame>0</frame>" in payload["prompt"]
    assert "<frame>1</frame>" in payload["prompt"]
    assert "width" not in payload
    assert "height" not in payload


def test_content_violation_raises(monkeypatch, tmp_path):
    from test_provider_wire import _compiled
    from novel_to_comic.image_models import GATEWAY_IMAGE_REVE
    from novel_to_comic.provider_wire import compile_provider_wire_request

    _capture_post(monkeypatch, payload={"content_violation": True, "request_id": "req_v"})
    wire = compile_provider_wire_request(
        _compiled(tmp_path, model=GATEWAY_IMAGE_REVE, count=0)
    )
    with pytest.raises(ValueError, match="content violation"):
        asyncio.run(reve_llm.aimage_generation(
            model="reve/create",
            prompt="p",
            api_key="test_key",
            api_base=None,
            model_response=ImageResponse(),
            optional_params={"canary_wire_request": wire.to_json()},
            logging_obj=None,
        ))
