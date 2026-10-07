import asyncio
import base64
import io
import json

import httpx
import pytest
from PIL import Image

from novel_to_comic.ai import client
from novel_to_comic.ai import admission
from novel_to_comic.ai.errors import AITransportError
from novel_to_comic.ai.image_previews import image_preview_events, image_preview_target, post_image_request
from novel_to_comic.server.event_channel import EventChannel


def preview():
    output = io.BytesIO()
    Image.new("RGB", (1024, 1536), "navy").save(output, format="PNG")
    return base64.b64encode(output.getvalue()).decode()


@pytest.mark.parametrize("alias", ["image-sunburst-openai", "image-flare", "image-nano-banana-2.1"])
def test_streamed_preview_has_scoped_target_and_keeps_final_response(alias, monkeypatch, tmp_path):
    events, calls = [], []
    final = {"data": [{"b64_json": preview()}], "usage": {"output_tokens": 678}}

    def respond(request):
        calls.append(request)
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content="".join(
            f"data: {json.dumps(event)}\n\n" for event in [
                {"type": "image_preview", "index": 0, "b64_json": preview()},
                {"type": "image_result", "status_code": 200, "headers": [["x-request-id", "req"]],
                 "body": json.dumps(final)},
            ]).encode())

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as transport:
            monkeypatch.setattr(client, "_http", transport)
            with image_preview_events(tmp_path, "cast", events.append), image_preview_target(tmp_path / "refs/a/sheet.png"):
                result = await post_image_request("https://gateway/v1/images/generations",
                    headers={"X-Canary-AI-Event-ID": "usage-1"}, json={"model": alias})
                assert result.json() == final
                assert result.headers["x-request-id"] == "req"
                assert [event["preview_index"] for event in events if event["type"] == "image_preview"] == [0, 3]
                assert events[-1]["target"] == "refs/a/sheet.png"
                assert events[-1]["request_id"] == "usage-1"
                encoded = events[-1]["image_url"].split(",")[1]
                with Image.open(io.BytesIO(base64.b64decode(encoded))) as image:
                    assert max(image.size) <= 768
            assert events[-1]["type"] == "image_preview_clear"

    asyncio.run(run())
    assert len(calls) == 1
    assert calls[0].headers["x-canary-image-previews"] == "3"


@pytest.mark.parametrize("alias", ["image-sunburst-openai", "image-nano-banana-2.1"])
def test_lost_stream_is_not_repeated_and_clears_preview(alias, monkeypatch, tmp_path):
    events, calls, retained = [], [], []
    monkeypatch.setattr("novel_to_comic.server.credits.retain_ambiguous_job", retained.append)

    def respond(request):
        calls.append(request)
        return httpx.Response(200, headers={"content-type": "text/event-stream"},
            content=f'data: {json.dumps({"type": "image_preview", "index": 0, "b64_json": preview()})}\n\n'.encode())

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as transport:
            monkeypatch.setattr(client, "_http", transport)
            with image_preview_events(tmp_path, "draw", events.append):
                with pytest.raises(AITransportError) as caught:
                    await post_image_request("https://gateway/v1/images/generations", target="page:1",
                        headers={}, json={"model": alias})
                assert caught.value.phase == "ambiguous_submission"
                assert events[-1]["type"] == "image_preview_clear"

    asyncio.run(run())
    assert len(calls) == 1
    assert len(retained) == 1


def test_vertex_gateway_stream_failure_retains_ambiguous_credit_hold(monkeypatch, tmp_path):
    events, calls, retained = [], [], []
    monkeypatch.setattr("novel_to_comic.server.credits.retain_ambiguous_job", retained.append)

    def respond(request):
        calls.append(request)
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content="".join(
            f"data: {json.dumps(event)}\n\n" for event in [
                {"type": "image_preview", "index": 0, "b64_json": preview()},
                {"type": "image_result", "status_code": 500, "headers": [],
                 "body": '{"error":"Vertex stream lost"}'},
            ]).encode())

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as transport:
            monkeypatch.setattr(client, "_http", transport)
            with image_preview_events(tmp_path, "style", events.append):
                result = await post_image_request("https://gateway/v1/images/generations", target="page:1",
                    headers={}, json={"model": "image-nano-banana-2.1"})
                assert result.status_code == 500
                assert events[-1]["type"] == "image_preview_clear"

    asyncio.run(run())
    assert len(calls) == 1
    assert len(retained) == 1


@pytest.mark.parametrize("first", ["connect", "rate_limit", "preview_error"])
@pytest.mark.parametrize("alias", ["image-sunburst-openai", "image-nano-banana-2.1"])
def test_stream_reuses_safe_retry_budget_but_never_retries_after_pixels(first, alias, monkeypatch, tmp_path):
    calls, pauses, retained = [], [], []
    monkeypatch.setattr("novel_to_comic.server.credits.retain_ambiguous_job", retained.append)
    # The pacer and admission share Retry-After. Advance admission's clock
    # along with the fake pacer instead of waiting seven real seconds.
    now = [0.0]
    monkeypatch.setattr(admission._controller, "clock", lambda: now[0])

    async def pause(self, **kwargs):
        pauses.append(kwargs)
        now[0] += kwargs.get("retry_after") or 0

    monkeypatch.setattr(client._RetryPacer, "pause_or_raise", pause)

    def respond(request):
        calls.append(request)
        if len(calls) == 1:
            if first == "connect":
                raise httpx.ConnectError("Not connected", request=request)
            if first == "rate_limit":
                return httpx.Response(429, headers={"retry-after": "7"}, json={"error": "limit"})
            return httpx.Response(200, headers={"content-type": "text/event-stream"}, content="".join(
                f"data: {json.dumps(event)}\n\n" for event in [
                    {"type": "image_preview", "index": 0, "b64_json": preview()},
                    {"type": "image_result", "status_code": 429, "headers": [], "body": '{"error":"late"}'},
                ]).encode())
        return httpx.Response(200, json={"data": [{"b64_json": preview()}]})

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as transport:
            monkeypatch.setattr(client, "_http", transport)
            with image_preview_events(tmp_path, "draw", lambda event: None):
                result = await post_image_request("https://gateway/v1/images/generations", target="page:1",
                    headers={}, json={"model": alias})
                assert result.status_code == (429 if first == "preview_error" else 200)

    asyncio.run(run())
    assert len(calls) == (1 if first == "preview_error" else 2)
    assert len(pauses) == (0 if first == "preview_error" else 1)
    if first == "rate_limit":
        assert pauses[0] == {"rate_limited": True, "retry_after": 7.0}
    assert not retained


def test_event_channel_reconnect_keeps_only_latest_preview_and_clears_it():
    channel = EventChannel()
    for index in range(3):
        channel.put_nowait({"type": "image_preview", "target": "page:1", "request_id": "one",
                           "preview_index": index, "image_url": "pixels"})
    assert not channel.history
    queue = channel.subscribe()
    assert queue.qsize() == 1
    assert queue.get_nowait()["preview_index"] == 2
    channel.put_nowait({"type": "image_preview_clear", "target": "page:1", "request_id": "old"})
    assert channel.previews
    channel.put_nowait({"type": "image_preview_clear", "target": "page:1", "request_id": "one"})
    assert not channel.previews


def test_nonstreaming_fallback_clears_completed_openai_pixels_before_submission(monkeypatch, tmp_path):
    events = []

    def respond(request):
        if request.headers.get("x-canary-image-previews"):
            return httpx.Response(200, json={"data": [{"b64_json": preview()}]})
        assert events[-1] == {"type": "image_preview_clear", "stage": "draw", "target": "page:1",
                             "request_id": "fal", "reset": True}
        return httpx.Response(200, json={"data": [{"b64_json": preview()}]})

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as transport:
            monkeypatch.setattr(client, "_http", transport)
            with image_preview_events(tmp_path, "draw", events.append):
                await post_image_request("https://gateway/v1/images/generations", target="page:1",
                    headers={"X-Canary-AI-Event-ID": "openai"}, json={"model": "image-sunburst-openai"})
                assert events[-1]["preview_index"] == 3
                await post_image_request("https://gateway/v1/images/generations", target="page:1",
                    headers={"X-Canary-AI-Event-ID": "fal"}, json={"model": "image-sunburst"})

    asyncio.run(run())


def test_series_asset_preview_from_a_part_job_targets_its_series_path(monkeypatch, tmp_path):
    part = tmp_path / "parts" / "part_0002"
    part.mkdir(parents=True)
    (part / "part.json").write_text("{}")
    events = []

    def respond(request):
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content="".join(
            f"data: {json.dumps(event)}\n\n" for event in [
                {"type": "image_preview", "index": 0, "b64_json": preview()},
                {"type": "image_result", "status_code": 200, "headers": [],
                 "body": json.dumps({"data": [{"b64_json": preview()}]})},
            ]).encode())

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as transport:
            monkeypatch.setattr(client, "_http", transport)
            with image_preview_events(part, "cast", events.append), image_preview_target(tmp_path / "refs/a/sheet.png"):
                await post_image_request("https://gateway/v1/images/generations",
                    headers={"X-Canary-AI-Event-ID": "usage-2"}, json={"model": "image-flare"})

    asyncio.run(run())
    assert {event["target"] for event in events if event["type"] == "image_preview"} == {"refs/a/sheet.png"}


@pytest.mark.parametrize("succeeded", [True, False])
def test_job_exit_settles_completed_pixels_only_after_success(succeeded, tmp_path):
    events = []

    def run():
        with image_preview_events(tmp_path, "style", events.append):
            observer_emit = __import__("novel_to_comic.ai.image_previews", fromlist=["_emit"])._emit
            observer_emit("image_preview", target="page:1", request_id="done",
                          preview_index=3, preview_total=3, image_url="data:image/webp;base64,x")
            observer_emit("image_preview", target="page:2", request_id="draft",
                          preview_index=1, preview_total=3, image_url="data:image/webp;base64,x")
            observer_emit("image_preview", target="page:3", request_id="failed",
                          preview_index=3, preview_total=3, image_url="data:image/webp;base64,x")
            observer_emit("image_preview_clear", target="page:3", request_id="failed")
            if not succeeded:
                raise RuntimeError("stage failed")

    if succeeded:
        run()
    else:
        with pytest.raises(RuntimeError):
            run()
    final = {event["target"]: event for event in events[4:]}
    assert set(final) == {"page:1", "page:2"}
    assert final["page:1"].get("settled") is (True if succeeded else None)
    assert "settled" not in final["page:2"]
