import asyncio
import base64
from pathlib import Path

import pytest

from novel_to_comic.ai import client
from novel_to_comic.config import Config


class _FakeResponse:
    def __init__(self, payload: dict, status_code: int = 200):
        self._payload = payload
        self.status_code = status_code
        self.text = str(payload)
        self.content = self.text.encode()
        self.headers: dict = {}

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class _FakeAsyncClient:
    response_payload: dict = {}
    status_code: int = 200
    last_request: dict | None = None

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def post(self, url, **kwargs):
        self.__class__.last_request = {"url": url, **kwargs}
        return _FakeResponse(self.__class__.response_payload, status_code=self.__class__.status_code)

    async def get(self, url, **kwargs):
        self.__class__.last_request = {"url": url, **kwargs}
        return _FakeResponse({})


@pytest.fixture(autouse=True)
def _patch_events(monkeypatch):
    events = []
    monkeypatch.setattr(client, "_insert_event", lambda **kwargs: events.append(("insert", kwargs)))
    monkeypatch.setattr(client, "_finalize_event", lambda **kwargs: events.append(("finalize", kwargs)))
    return events


def _patch_http(monkeypatch, payload: dict):
    _FakeAsyncClient.response_payload = payload
    _FakeAsyncClient.status_code = 200
    _FakeAsyncClient.last_request = None
    monkeypatch.setattr(client, "_http", _FakeAsyncClient())


def test_generate_structured_object_returns_dict_and_usage(monkeypatch, _patch_events):
    _patch_http(monkeypatch, {
        "id": "resp_1",
        "model": "openai/gpt-5.4-mini",
        "choices": [{"message": {"content": '{"ok": true}'}}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 3, "total_tokens": 13},
    })

    result = asyncio.run(
        client.generate_structured_object(
            config=Config(),
            model="canary/panel",
            system_prompt="Return JSON.",
            user_content="{}",
            feature="test.json",
        )
    )

    assert result.value == {"ok": True}
    assert result.usage is not None
    assert result.usage.call_id
    assert result.usage.provider == "openai"
    assert result.usage.model == "canary/panel"
    assert result.usage.provider_model == "openai/gpt-5.4-mini"
    assert result.usage.input_tokens == 10
    assert result.usage.output_tokens == 3
    assert _patch_events[0][0] == "insert"
    assert _patch_events[-1][1]["status"] == "succeeded"


def test_generate_text_does_not_store_prompt_in_params(monkeypatch, _patch_events):
    _patch_http(monkeypatch, {
        "id": "resp_1",
        "model": "anthropic/claude-sonnet-4-6",
        "choices": [{"message": {"content": "hello"}}],
        "usage": {"prompt_tokens": 4, "completion_tokens": 1},
    })

    asyncio.run(
        client.generate_text(
            config=Config(),
            model="canary/screenplay",
            system_prompt="system secret",
            user_content="user secret",
            feature="test.text",
        )
    )

    inserted = _patch_events[0][1]
    assert "messages" not in inserted["params_json"]
    assert inserted["request_summary_json"]["system_prompt_sha256"]
    assert inserted["request_summary_json"]["user_content_sha256"]


def test_generate_image_writes_b64_response(monkeypatch, tmp_path: Path):
    image_bytes = b"fake png"
    _patch_http(monkeypatch, {
        "id": "img_1",
        "model": "openai/gpt-image-1",
        "data": [{"b64_json": base64.b64encode(image_bytes).decode()}],
    })

    output_path = tmp_path / "panel.png"
    result = asyncio.run(
        client.generate_image(
            config=Config(),
            model="canary/image-primary",
            prompt="draw this",
            output_path=output_path,
            width=1024,
            height=1024,
        )
    )

    assert result.value == output_path
    assert output_path.read_bytes() == image_bytes
    assert result.usage is not None
    assert result.usage.operation == "image"
    assert result.usage.image_count == 1
    request = _FakeAsyncClient.last_request
    assert request is not None
    assert request["url"].endswith("/v1/images/generations")
    assert request["json"]["model"] == "canary/image-primary"
    assert request["json"]["quality"] == "auto"
    assert "steps" not in request["json"]
    assert "response_format" not in request["json"]


def test_extract_usage_preserves_litellm_response_cost():
    usage = client._extract_usage(
        {
            "id": "resp_1",
            "model": "openai/gpt-5.4-mini",
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
            "_hidden_params": {"response_cost": 0.0042},
        },
        "event_1",
        "canary/panel",
        "text",
    )

    assert usage.provider_model == "openai/gpt-5.4-mini"
    assert usage.cost_usd == 0.0042
    assert usage.cost_source == "litellm_response_cost"


def test_generate_image_with_references_uses_image_edits(monkeypatch, tmp_path: Path):
    image_bytes = b"fake png"
    _patch_http(monkeypatch, {
        "id": "img_1",
        "model": "openai/gpt-image-1",
        "data": [{"b64_json": base64.b64encode(image_bytes).decode()}],
    })

    output_path = tmp_path / "panel.png"
    reference_path = tmp_path / "character.png"
    reference_path.write_bytes(b"reference png")

    asyncio.run(
        client.generate_image(
            config=Config(),
            model="canary/image-primary",
            prompt="draw this",
            output_path=output_path,
            width=1024,
            height=1536,
            steps=28,
            reference_paths=[reference_path],
        )
    )

    request = _FakeAsyncClient.last_request
    assert request is not None
    assert request["url"].endswith("/v1/images/edits")
    assert request["data"]["model"] == "canary/image-primary"
    assert request["data"]["size"] == "1024x1536"
    # assert request["data"]["steps"] == "28"
    assert "response_format" not in request["data"]
    assert request["files"][0][0] == "image"
    assert request["files"][0][1][0] == "character.png"


def test_failed_request_estimate_all_finalizes_billable_usage(monkeypatch, _patch_events):
    _patch_http(monkeypatch, {"error": {"message": "provider failed"}})
    _FakeAsyncClient.status_code = 500

    with pytest.raises(RuntimeError):
        asyncio.run(
            client.generate_text(
                config=Config(ai_bill_failed_requests="estimate_all"),
                model="canary/prompt",
                system_prompt="system",
                user_content="user",
                feature="test.failure",
            )
        )

    finalized = _patch_events[-1][1]
    assert finalized["status"] == "failed"
    assert finalized["usage"] is not None
    assert finalized["config"].ai_bill_failed_requests == "estimate_all"
