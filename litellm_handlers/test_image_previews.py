import asyncio
import base64
import json
from types import SimpleNamespace

import httpx
import pytest

from litellm_handlers import openai_image_stream as handler
from litellm_handlers.image_previews import ImagePreviewMiddleware, publish_partial_image, requested_partial_images


def scope():
    return {"type": "http", "method": "POST", "path": "/v1/images/generations",
            "headers": [(b"x-canary-image-previews", b"3")]}


async def receive():
    return {"type": "http.request", "body": b"", "more_body": False}


@pytest.mark.parametrize("status", [200, 502])
def test_preview_is_delivered_before_final_result_and_final_status_usage_headers_survive(status):
    async def run():
        delivered = asyncio.Event()
        sent = []
        final = json.dumps({"usage": {"output_tokens": 643}, "data": [{"b64_json": "final"}]})

        async def route(scope, receive, send):
            assert requested_partial_images() == 3
            publish_partial_image({"partial_image_index": 0, "b64_json": "AA=="})
            # A buffered relay would deadlock here: the consumer releases the final.
            await delivered.wait()
            await send({"type": "http.response.start", "status": status,
                        "headers": [(b"content-type", b"application/json"), (b"x-request-id", b"req-1")]})
            await send({"type": "http.response.body", "body": final.encode()})

        async def send(message):
            sent.append(message)
            if message["type"] == "http.response.body" and b'"image_preview"' in message["body"]:
                delivered.set()

        await asyncio.wait_for(ImagePreviewMiddleware(route)(scope(), receive, send), 1)
        events = [json.loads(message["body"].decode().removeprefix("data: ")) for message in sent
                  if message["type"] == "http.response.body"]
        assert [event["type"] for event in events] == ["image_preview", "image_result"]
        assert events[-1]["status_code"] == status
        assert events[-1]["body"] == final
        assert ["x-request-id", "req-1"] in events[-1]["headers"]
        assert requested_partial_images() == 0

    asyncio.run(run())


def test_rejection_without_preview_keeps_original_http_response():
    async def run():
        sent = []

        async def route(scope, receive, send):
            await send({"type": "http.response.start", "status": 401, "headers": []})
            await send({"type": "http.response.body", "body": b'{"error":"unauthorized"}'})

        async def send(message):
            sent.append(message)

        await ImagePreviewMiddleware(route)(scope(), receive, send)
        assert sent[0]["status"] == 401
        assert sent[1]["body"] == b'{"error":"unauthorized"}'

    asyncio.run(run())


def test_route_that_finishes_without_yielding_still_delivers_whole_response():
    async def run():
        sent = []

        async def route(scope, receive, send):
            # Both messages queue before the relay runs, then the route ends.
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"{}"})

        async def send(message):
            sent.append(message)

        await asyncio.wait_for(ImagePreviewMiddleware(route)(scope(), receive, send), 1)
        assert [message["type"] for message in sent] == ["http.response.start", "http.response.body"]

    asyncio.run(run())


def test_client_disconnect_never_cancels_the_paid_route():
    async def run():
        finished = asyncio.Event()
        release = asyncio.Event()

        async def route(scope, receive, send):
            publish_partial_image({"partial_image_index": 0, "b64_json": "AA=="})
            await release.wait()
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"{}"})
            finished.set()

        async def send(message):
            raise OSError("client disconnected")

        with pytest.raises(OSError):
            await ImagePreviewMiddleware(route)(scope(), receive, send)
        release.set()
        await asyncio.wait_for(finished.wait(), 1)

    asyncio.run(run())


@pytest.mark.parametrize("edit", [False, True])
def test_openai_handler_requests_three_previews_and_relays_them_once(monkeypatch, edit):
    seen = []
    real_client = httpx.AsyncClient
    final = base64.b64encode(b"\x89PNGfixture").decode()
    kind = "image_edit" if edit else "image_generation"

    def respond(request):
        seen.append(request)
        events = [{"type": f"{kind}.partial_image", "partial_image_index": 0, "b64_json": final},
                  {"type": f"{kind}.completed", "b64_json": final,
                   "usage": {"input_tokens": 200, "output_tokens": 478, "total_tokens": 678}}]
        return httpx.Response(200, headers={"content-type": "text/event-stream"},
                              content="".join(f"data: {json.dumps(event)}\n\n" for event in events).encode())

    monkeypatch.setattr(handler.httpx, "AsyncClient", lambda **kwargs: real_client(
        transport=httpx.MockTransport(respond), **kwargs))

    async def route(scope, receive, send):
        result = await handler.openai_image_stream_llm._generate_async(
            model="openai-stream/gpt-image-2.5-sunburst", prompt="draw", api_key="test",
            image=[("ref.png", b"ref", "image/png")] if edit else [],
            model_response=SimpleNamespace(_hidden_params={}), timeout=None,
            optional_params={"canary_wire_request": json.dumps({"width": 1024, "height": 1536, "controls": []})},
        )
        assert result.data[0].b64_json == final
        assert result.usage.output_tokens == 478
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b'{}'})

    sent = []

    async def send(message):
        sent.append(message)

    asyncio.run(ImagePreviewMiddleware(route)(scope(), receive, send))
    assert len(seen) == 1
    if edit:
        assert b'name="partial_images"\r\n\r\n3\r\n' in seen[0].content
    else:
        assert json.loads(seen[0].content)["partial_images"] == 3
    assert any(b'"image_preview"' in message.get("body", b"") for message in sent)
