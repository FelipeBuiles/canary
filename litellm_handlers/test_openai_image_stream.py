import asyncio
import base64
import json
from types import SimpleNamespace

import httpx
import pytest

from litellm_handlers import openai_image_stream as handler
from litellm_handlers.openai_image_stream import OpenAIImageStreamError

PNG = base64.b64encode(b"\x89PNG\r\n\x1a\nfixture").decode()
MANIFEST = json.dumps({"width": 1024, "height": 1536,
                       "controls": [["quality", "medium"], ["output_format", "png"], ["n", 1]]})
USAGE = {"input_tokens": 3200, "output_tokens": 343, "total_tokens": 3543,
         "input_tokens_details": {"image_tokens": 3000, "text_tokens": 200}}


def sse(*events):
    return "".join(f"event: {event['type']}\ndata: {json.dumps(event)}\n\n" for event in events).encode()


def use_transport(monkeypatch, respond):
    seen = []

    def handle(request):
        seen.append(request)
        return respond(request)

    real = httpx.AsyncClient
    monkeypatch.setattr(handler.httpx, "AsyncClient",
                        lambda **kwargs: real(transport=httpx.MockTransport(handle), **kwargs))
    return seen


def run(image=(), params=None, model="openai-stream/gpt-image-2.5-sunburst"):
    response = SimpleNamespace(_hidden_params={})
    call = handler.openai_image_stream_llm._generate_async(
        model=model, image=list(image), prompt="draw the page", model_response=response,
        api_key="sk-test", optional_params={"canary_wire_request": MANIFEST, **(params or {})},
        timeout=None,
    )
    return asyncio.run(call)


def test_streamed_edit_returns_final_image_usage_and_no_gateway_cost(monkeypatch):
    seen = use_transport(monkeypatch, lambda request: httpx.Response(
        200, headers={"content-type": "text/event-stream", "x-request-id": "req_1"},
        content=sse({"type": "image_edit.completed", "b64_json": PNG, "created_at": 7, "usage": USAGE}),
    ))
    result = run(image=[("ref.png", b"ref-bytes", "image/png"), ("two.png", b"two", "image/png")])

    request = seen[0]
    assert str(request.url) == "https://api.openai.com/v1/images/edits"
    assert request.headers["authorization"] == "Bearer sk-test"
    body = request.content
    for field, value in (("model", "gpt-image-2.5-sunburst"), ("size", "1024x1536"), ("stream", "true"),
                         ("partial_images", "0"), ("quality", "medium"), ("output_format", "png")):
        assert f'name="{field}"\r\n\r\n{value}\r\n'.encode() in body
    assert body.count(b'name="image[]"') == 2
    assert b"canary_wire_request" not in body
    assert result.data[0].b64_json == PNG
    assert result.usage.output_tokens == 343
    assert result.usage.input_tokens_details.image_tokens == 3000
    assert result.model == "openai/gpt-image-2.5-sunburst"
    assert result.provider_request_id == "req_1"
    assert result._hidden_params["response_cost"] is None


def test_streamed_generation_sends_json(monkeypatch):
    seen = use_transport(monkeypatch, lambda request: httpx.Response(
        200, headers={"content-type": "text/event-stream"},
        content=sse({"type": "image_generation.partial_image", "b64_json": "AA==", "partial_image_index": 0},
                    {"type": "image_generation.completed", "b64_json": PNG, "usage": USAGE}),
    ))
    result = run()
    body = json.loads(seen[0].content)
    assert str(seen[0].url).endswith("/images/generations")
    assert body["stream"] is True and body["partial_images"] == 0 and body["n"] == 1
    assert result.data[0].b64_json == PNG


@pytest.mark.parametrize("status", [429, 401, 400, 500])
def test_rejection_before_stream_is_a_submit_phase_error(monkeypatch, status):
    use_transport(monkeypatch, lambda request: httpx.Response(
        status, headers={"x-request-id": "req_2"},
        json={"error": {"code": "rate_limit_exceeded", "message": "slow down", "type": "requests"}},
    ))
    with pytest.raises(OpenAIImageStreamError) as caught:
        run()
    error = caught.value
    assert (error.phase, error.upstream_status, error.request_id) == ("submit", status, "req_2")
    assert f"OpenAI image submit failed for gpt-image-2.5-sunburst; upstream_status={status}" in error.message


def test_connect_failure_is_never_submitted(monkeypatch):
    def refuse(request):
        raise httpx.ConnectError("refused", request=request)

    use_transport(monkeypatch, refuse)
    with pytest.raises(OpenAIImageStreamError) as caught:
        run()
    assert caught.value.phase == "submit_connect"


def test_stream_without_completed_event_is_lost_after_acceptance(monkeypatch):
    use_transport(monkeypatch, lambda request: httpx.Response(
        200, headers={"content-type": "text/event-stream", "x-request-id": "req_3"},
        content=sse({"type": "image_edit.partial_image", "b64_json": "AA=="}),
    ))
    with pytest.raises(OpenAIImageStreamError) as caught:
        run(image=[("ref.png", b"ref", "image/png")])
    assert (caught.value.phase, caught.value.request_id) == ("stream", "req_3")


def test_disconnect_after_acceptance_is_a_stream_phase_error(monkeypatch):
    class Broken(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b": keepalive\n\n"
            raise httpx.ReadError("connection reset")

    use_transport(monkeypatch, lambda request: httpx.Response(
        200, headers={"content-type": "text/event-stream"}, stream=Broken()))
    with pytest.raises(OpenAIImageStreamError) as caught:
        run()
    assert caught.value.phase == "stream"


def test_completed_event_without_image_is_a_result_error(monkeypatch):
    use_transport(monkeypatch, lambda request: httpx.Response(
        200, headers={"content-type": "text/event-stream"},
        content=sse({"type": "image_generation.completed", "usage": USAGE})))
    with pytest.raises(OpenAIImageStreamError) as caught:
        run()
    assert caught.value.phase == "result"


@pytest.mark.parametrize("params,detail", [
    ({"canary_wire_request": None}, "missing frozen wire manifest"),
    ({"canary_wire_request": json.dumps({"width": 1024, "height": 1536, "controls": [["seed", 1]]})},
     "unsupported controls"),
    ({"canary_wire_request": json.dumps({"width": 1000, "height": 1536, "controls": []})}, "invalid size"),
])
def test_invalid_requests_never_leave_the_gateway(monkeypatch, params, detail):
    seen = use_transport(monkeypatch, lambda request: httpx.Response(500))
    with pytest.raises(OpenAIImageStreamError, match=detail) as caught:
        run(params=params)
    assert caught.value.phase == "request_validation"
    assert not seen


def test_unreadable_reference_is_rejected_not_dropped(monkeypatch):
    seen = use_transport(monkeypatch, lambda request: httpx.Response(500))
    with pytest.raises(OpenAIImageStreamError, match="reference 1 has no readable image bytes"):
        run(image=[("ok.png", b"ok", "image/png"), ("bad.png", None, "image/png")])
    assert not seen


def test_unsupported_model_is_rejected(monkeypatch):
    use_transport(monkeypatch, lambda request: httpx.Response(500))
    with pytest.raises(OpenAIImageStreamError, match="unsupported OpenAI image model"):
        run(model="openai-stream/gpt-image-2")
