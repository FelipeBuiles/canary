"""Exercise the configured Vertex image route against the real gateway SDK."""
import asyncio
import base64
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import struct
import sys
from types import SimpleNamespace

import pytest
import httpx
import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")


def _wire_payload(route, parent=None):
    manifest = {
        "discriminator": "canary.provider-wire/3", "schema_version": 3,
        "requested_alias": "image-nano-banana-2.1", "expected_route": "nano_banana_21",
        "provider_key": "vertex-multimodal", "configured_provider_model": route["litellm_params"]["model"],
        "prompt_parts": ["A red circle."], "references": [], "edit_parent_indices": [],
        "width": 1024, "height": 1024, "structured_aspect": None,
        "controls": [["quality", "medium"]], "compiled_request_sha256": "c" * 64,
    }
    if parent is not None:
        manifest["references"] = [{
            "index": 0, "source_path": "parent.png", "content_sha256": hashlib.sha256(parent).hexdigest(),
            "role": "edit_parent", "role_label": "Parent", "instruction": "Preserve this parent image.",
            "provider_binding": "0", "authority_scope": "page", "entity_id": None,
            "appearance_state_id": None, "preserve_facets": [], "ignore_facets": [],
        }]
        manifest["edit_parent_indices"] = [0]
    projection = deepcopy(manifest)
    for ref in projection["references"]:
        ref.pop("source_path")
    manifest["execution_fingerprint"] = hashlib.sha256(json.dumps(
        projection, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode()).hexdigest()
    return {"model": "image-nano-banana-2.1", "prompt": "A red circle.",
            "response_format": "b64_json", "quality": "medium",
            "metadata": {"feature": "cast.sheet" if parent is not None else "style.sample"},
            "canary_wire_request": json.dumps(manifest), "canary_requested_aspect": 1.0,
            "canary_requested_width": 1024, "canary_requested_height": 1024}


def test_nano_banana_gateway_preserves_native_controls_and_prices_reported_usage(monkeypatch):
    import litellm
    from litellm.utils import custom_llm_setup
    from google.genai import types
    from litellm_handlers import vertex_multimodal as handler

    route = next(r for r in yaml.safe_load((ROOT / "litellm/config.yaml").read_text())["model_list"]
                 if r["model_name"] == "image-nano-banana-2.1")
    monkeypatch.setenv("VERTEXAI_PROJECT", "offline-test")
    png = b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IHDR" + struct.pack(">II", 2048, 2048)
    sent = []

    def generate(**kwargs):
        sent.append(kwargs)
        return SimpleNamespace(
            candidates=[SimpleNamespace(content=SimpleNamespace(parts=[
                types.Part(inline_data=types.Blob(data=png, mime_type="image/png")),
            ]))],
            usage_metadata=types.GenerateContentResponseUsageMetadata(
                prompt_token_count=8, candidates_token_count=1680, thoughts_token_count=200,
                total_token_count=1888,
                candidates_tokens_details=[types.ModalityTokenCount(modality="IMAGE", token_count=1680)],
            ),
        )

    clients = []

    def client(**kwargs):
        clients.append(kwargs)
        return SimpleNamespace(models=SimpleNamespace(generate_content=generate))

    monkeypatch.setattr(handler.genai, "Client", client)
    monkeypatch.setattr(litellm, "custom_provider_map", [
        {"provider": "vertex-multimodal", "custom_handler": handler.vertex_multimodal_llm},
    ])
    custom_llm_setup()
    router = litellm.Router(model_list=[route], num_retries=0)
    # The configured route must deliver the resolved project and location;
    # ambient settings must not mask dropped custom-provider parameters.
    monkeypatch.delenv("VERTEXAI_PROJECT")
    monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)
    monkeypatch.setenv("VERTEXAI_LOCATION", "us-central1")
    monkeypatch.setenv("GOOGLE_CLOUD_LOCATION", "us-central1")
    payload = _wire_payload(route)
    response = asyncio.run(router.aimage_generation(**payload))
    assert len(sent) == 1
    assert clients[0]["vertexai"] is True
    assert clients[0]["project"] == "offline-test"
    assert clients[0]["location"] == "global"
    assert clients[0]["http_options"].retry_options.attempts == 1
    assert sent[0]["model"] == "gemini-nano-banana-2.1"
    config = sent[0]["config"].model_dump(exclude_none=True)
    assert config["image_config"] == {"image_size": "2K", "aspect_ratio": "1:1"}
    assert "thinking_config" not in config
    assert not {"temperature", "top_p", "top_k", "seed", "logprobs"} & config.keys()
    assert response.usage.cost == pytest.approx(1680 * 3e-5 + 8 * 1.5e-6 + 200 * 7.5e-6)
    assert response.usage.output_tokens == 1880
    assert response.model == "vertex_ai/gemini-nano-banana-2.1"


@pytest.fixture
def vertex_gateway(monkeypatch):
    import google.auth
    from google.oauth2.credentials import Credentials
    import litellm
    from litellm.utils import custom_llm_setup
    from litellm_handlers import vertex_multimodal as handler

    credentials = Credentials(token="fixture-token")
    monkeypatch.setattr(google.auth, "default", lambda **kwargs: (credentials, "offline-test"))
    monkeypatch.setenv("VERTEXAI_PROJECT", "offline-test")
    route = next(r for r in yaml.safe_load((ROOT / "litellm/config.yaml").read_text())["model_list"]
                 if r["model_name"] == "image-nano-banana-2.1")
    monkeypatch.setattr(litellm, "custom_provider_map", [
        {"provider": "vertex-multimodal", "custom_handler": handler.vertex_multimodal_llm},
    ])
    custom_llm_setup()
    router = litellm.Router(model_list=[route], num_retries=0)
    real_client = handler.genai.Client
    real_http_client = httpx.AsyncClient
    requests, clients = [], []

    def install(stream=None, *, error=None):
        def respond(request):
            requests.append(request)
            if error is not None:
                raise error
            return httpx.Response(200, headers={"content-type": "text/event-stream"}, stream=stream)

        def client(**kwargs):
            assert kwargs["http_options"].retry_options.attempts == 1
            # Exercise the transport chosen by production, rather than forcing
            # an HTTPX transport that bypasses the SDK's default 8 MiB limit.
            assert kwargs["http_options"].httpx_async_client is not None
            native = real_client(**kwargs)
            assert not native._api_client._use_aiohttp()
            clients.append(native)
            return native

        monkeypatch.setattr(handler.httpx, "AsyncClient", lambda **kwargs: real_http_client(
            transport=httpx.MockTransport(respond), **kwargs,
        ))
        monkeypatch.setattr(handler.genai, "Client", client)

    return SimpleNamespace(router=router, route=route, install=install, requests=requests, clients=clients)


def _image_chunk(data, *, thought=False):
    return {"candidates": [{"index": 0, "content": {"role": "model", "parts": [{
        "thought": thought, "inlineData": {"mimeType": "image/png", "data": base64.b64encode(data).decode()},
    }]}}]}


def _frame(chunk):
    return f"data: {json.dumps(chunk)}\n\n".encode()


async def _receive():
    return {"type": "http.request", "body": b"", "more_body": False}


def _scope(edit=False):
    return {"type": "http", "method": "POST", "path": "/v1/images/edits" if edit else "/v1/images/generations",
            "headers": [(b"x-canary-image-previews", b"3")]}


@pytest.mark.parametrize("edit", [False, True])
@pytest.mark.parametrize("drafts", [False, True])
def test_native_vertex_stream_relays_drafts_before_final_and_keeps_terminal_usage(vertex_gateway, edit, drafts):
    from litellm_handlers.image_previews import ImagePreviewMiddleware

    # Distinct pixels prove the saved image cannot be an interim thought.
    final = (b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IHDR" + struct.pack(">II", 2048, 2048)
             + b"pixels" * (1100 * 1024))
    final_frame = _frame(_image_chunk(final))
    assert len(final_frame) > 8 * 1024 * 1024
    messages, results = [], []

    async def run():
        delivered = asyncio.Event()

        class Frames(httpx.AsyncByteStream):
            async def __aiter__(self):
                if drafts:
                    first = _image_chunk(b"draft one", thought=True)
                    first["candidates"][0]["content"]["parts"].insert(0, {"thought": True, "text": "private reasoning"})
                    first["usageMetadata"] = {"promptTokenCount": 8, "thoughtsTokenCount": 100, "totalTokenCount": 108}
                    yield _frame(first)
                    # A buffered implementation deadlocks until the UI gets a preview.
                    await delivered.wait()
                    yield _frame(_image_chunk(b"draft two", thought=True))
                # The final base64 image is one large SSE line delivered in
                # small network chunks, as in the reported production failure.
                for offset in range(0, len(final_frame), 64 * 1024):
                    yield final_frame[offset:offset + 64 * 1024]
                # Usage and finish metadata can arrive after the final image.
                yield _frame({
                    "modelVersion": "gemini-nano-banana-2.1", "responseId": "vertex-response",
                    "candidates": [{"index": 0, "finishReason": "STOP"}],
                    "usageMetadata": {"promptTokenCount": 8, "candidatesTokenCount": 1680,
                        "thoughtsTokenCount": 200, "totalTokenCount": 1888,
                        "candidatesTokensDetails": [{"modality": "IMAGE", "tokenCount": 1680}]},
                })

        vertex_gateway.install(Frames())

        async def route(scope, receive, send):
            payload = _wire_payload(vertex_gateway.route, parent=b"parent pixels" if edit else None)
            result = (await vertex_gateway.router.aimage_edit(image=[("parent.png", b"parent pixels", "image/png")], **payload)
                      if edit else await vertex_gateway.router.aimage_generation(**payload))
            results.append(result)
            await send({"type": "http.response.start", "status": 200, "headers": [(b"x-request-id", b"original")]})
            await send({"type": "http.response.body", "body": result.model_dump_json().encode()})

        async def send(message):
            messages.append(message)
            if b'"image_preview"' in message.get("body", b""):
                delivered.set()

        await asyncio.wait_for(ImagePreviewMiddleware(route)(_scope(edit), _receive, send), 5)

    asyncio.run(run())
    assert len(vertex_gateway.requests) == 1
    request = vertex_gateway.requests[0]
    assert request.url.host == "aiplatform.googleapis.com"
    assert request.url.path.endswith("/gemini-nano-banana-2.1:streamGenerateContent")
    assert "/projects/offline-test/locations/global/" in request.url.path
    assert request.headers["authorization"] == "Bearer fixture-token"
    body = json.loads(request.content)
    config = body["generationConfig"]
    assert config["thinkingConfig"] == {"include_thoughts": True}
    assert config["imageConfig"] == {"imageSize": "2K", "aspectRatio": "1:1"}
    assert body["contents"][-1]["parts"][-1]["text"] == "A red circle."
    if edit:
        assert body["contents"][0]["parts"][0]["inlineData"]["data"] == base64.b64encode(b"parent pixels").decode()
        assert body["contents"][0]["parts"][1]["text"] == "Preserve this parent image."
    result = results[0]
    assert base64.b64decode(result.data[0].b64_json) == final
    assert result.usage.output_tokens == 1880
    assert result.usage.total_tokens == 1888
    assert result.usage.cost == pytest.approx(1680 * 3e-5 + 8 * 1.5e-6 + 200 * 7.5e-6)
    assert "private reasoning" not in result.model_dump_json()
    if drafts:
        events = [json.loads(message["body"].decode().removeprefix("data: ")) for message in messages
                  if message["type"] == "http.response.body"]
        assert [event["type"] for event in events] == ["image_preview", "image_preview", "image_result"]
        assert [base64.b64decode(event["b64_json"]) for event in events[:-1]] == [b"draft one", b"draft two"]
        assert events[-1]["status_code"] == 200
        assert ["x-request-id", "original"] in events[-1]["headers"]
    else:
        assert messages[0]["status"] == 200
        assert json.loads(messages[-1]["body"])["data"][0]["b64_json"] == result.data[0].b64_json
    assert vertex_gateway.clients[0]._api_client._async_httpx_client.is_closed


def test_vertex_disconnect_after_submission_is_not_retried(vertex_gateway):
    from litellm_handlers.image_previews import ImagePreviewMiddleware

    vertex_gateway.install(error=httpx.RemoteProtocolError("Disconnected after submission"))
    messages = []

    async def run():
        async def route(scope, receive, send):
            with pytest.raises(Exception) as caught:
                await vertex_gateway.router.aimage_generation(**_wire_payload(vertex_gateway.route))
            assert caught.value.status_code == 500
            await send({"type": "http.response.start", "status": 500, "headers": []})
            await send({"type": "http.response.body", "body": b'{"error":"stream lost"}'})

        async def send(message):
            messages.append(message)

        await ImagePreviewMiddleware(route)(_scope(), _receive, send)

    asyncio.run(run())
    assert len(vertex_gateway.requests) == 1
    assert vertex_gateway.clients[0]._api_client._async_httpx_client.is_closed
    assert messages[0]["status"] == 500


@pytest.mark.parametrize("outcome", ["refusal", "refusal_after_final", "prompt_refusal", "empty", "lost", "lost_after_final", "cancel"])
def test_vertex_preview_failure_never_saves_draft_or_resubmits(vertex_gateway, outcome):
    from litellm_handlers.image_previews import ImagePreviewMiddleware

    messages, results = [], []

    async def run():
        delivered = asyncio.Event()

        class Frames(httpx.AsyncByteStream):
            async def __aiter__(self):
                yield _frame(_image_chunk(b"draft pixels", thought=True))
                await delivered.wait()
                if outcome == "cancel":
                    await asyncio.Event().wait()
                if outcome in {"lost_after_final", "refusal_after_final"}:
                    final = b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IHDR" + struct.pack(">II", 2048, 2048)
                    yield _frame(_image_chunk(final))
                if outcome in {"lost", "lost_after_final"}:
                    raise httpx.ReadError("Disconnected after submission")
                if outcome == "prompt_refusal":
                    yield _frame({"promptFeedback": {"blockReason": "OTHER"}})
                else:
                    refused = outcome in {"refusal", "refusal_after_final"}
                    yield _frame({"candidates": [{"index": 0,
                        "finishReason": "IMAGE_SAFETY" if refused else "STOP",
                        "finishMessage": "Blocked" if refused else "Ended without image",
                        "safetyRatings": [{"category": "HARM_CATEGORY_DANGEROUS_CONTENT",
                                           "probability": "HIGH", "blocked": True}] if refused else [],
                    }]})

        vertex_gateway.install(Frames())

        async def route(scope, receive, send):
            try:
                results.append(await vertex_gateway.router.aimage_generation(**_wire_payload(vertex_gateway.route)))
            except Exception as error:
                await send({"type": "http.response.start", "status": getattr(error, "status_code", 500), "headers": []})
                await send({"type": "http.response.body", "body": json.dumps({"error": str(error)}).encode()})

        async def send(message):
            messages.append(message)
            if b'"image_preview"' in message.get("body", b""):
                delivered.set()

        task = asyncio.create_task(ImagePreviewMiddleware(route)(_scope(), _receive, send))
        await asyncio.wait_for(delivered.wait(), 5)
        if outcome == "cancel":
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        else:
            await asyncio.wait_for(task, 5)

    asyncio.run(run())
    assert len(vertex_gateway.requests) == 1
    assert not results
    events = [json.loads(message["body"].decode().removeprefix("data: ")) for message in messages
              if message["type"] == "http.response.body"]
    assert events[0]["type"] == "image_preview"
    if outcome == "cancel":
        assert len(events) == 1
    else:
        assert events[-1]["type"] == "image_result"
        assert events[-1]["status_code"] == (400 if outcome in {"refusal", "refusal_after_final", "prompt_refusal"} else 500)
        if outcome == "prompt_refusal":
            assert "block_reason=BlockedReason.OTHER" in events[-1]["body"]
        if outcome in {"refusal", "refusal_after_final"}:
            assert "IMAGE_SAFETY" in events[-1]["body"]
            assert "blocked=True" in events[-1]["body"]
        assert "draft pixels" not in events[-1]["body"]
    assert vertex_gateway.clients[0]._api_client._async_httpx_client.is_closed
