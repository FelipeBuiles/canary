import asyncio
import base64
from pathlib import Path

import httpx
import pytest

from novel_to_comic.ai import client
from novel_to_comic.ai.providers.base import RefImage
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
            model="panel-balanced",
            system_prompt="Return JSON.",
            user_content="{}",
            feature="test.json",
        )
    )

    assert result.value == {"ok": True}
    assert result.usage is not None
    assert result.usage.call_id
    assert result.usage.provider == "openai"
    assert result.usage.model == "panel-balanced"
    assert result.usage.provider_model == "openai/gpt-5.4-mini"
    assert result.usage.input_tokens == 10
    assert result.usage.output_tokens == 3
    assert _patch_events[0][0] == "insert"
    assert _patch_events[-1][1]["status"] == "succeeded"


def test_generate_structured_object_retries_then_succeeds_on_malformed_json(monkeypatch, _patch_events):
    payloads = [
        {
            "id": "resp_1",
            "model": "openai/gpt-5.4-mini",
            "choices": [{"message": {"content": '{"ok": tru'}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 3, "total_tokens": 13},
        },
        {
            "id": "resp_2",
            "model": "openai/gpt-5.4-mini",
            "choices": [{"message": {"content": '{"ok": true}'}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 3, "total_tokens": 13},
        },
    ]
    calls = {"n": 0}

    class _SeqClient:
        async def post(self, url, **kwargs):
            i = calls["n"]
            calls["n"] += 1
            return _FakeResponse(payloads[i])

        async def get(self, url, **kwargs):
            return _FakeResponse({})

    monkeypatch.setattr(client, "_http", _SeqClient())

    result = asyncio.run(
        client.generate_structured_object(
            config=Config(),
            model="panel-balanced",
            system_prompt="Return JSON.",
            user_content="{}",
            feature="test.json",
        )
    )

    assert result.value == {"ok": True}
    assert calls["n"] == 2


def test_generate_structured_object_raises_with_context_after_exhausting_retries(monkeypatch, _patch_events):
    bad_content = '{"ok": tru'
    _patch_http(monkeypatch, {
        "id": "resp_1",
        "model": "openai/gpt-5.4-mini",
        "choices": [{"message": {"content": bad_content}}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 3, "total_tokens": 13},
    })

    with pytest.raises(ValueError) as exc_info:
        asyncio.run(
            client.generate_structured_object(
                config=Config(),
                model="panel-balanced",
                system_prompt="Return JSON.",
                user_content="{}",
                feature="test.json",
            )
        )

    msg = str(exc_info.value)
    assert "malformed JSON" in msg
    assert "panel-balanced" in msg
    assert "tru" in msg
    assert isinstance(exc_info.value.__cause__, __import__("json").JSONDecodeError)


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
            model="screenplay-balanced",
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
            model="image-balanced",
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
    assert request["json"]["model"] == "image-balanced"
    assert request["json"]["quality"] == "medium"
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
        "panel-balanced",
        "text",
    )

    assert usage.provider_model == "openai/gpt-5.4-mini"
    assert usage.cost_usd == 0.0042
    assert usage.cost_source == "litellm_response_cost"


def test_extract_usage_prefers_body_cost_over_litellm_header():
    usage = client._extract_usage(
        {
            "model": "image-fast",
            "usage": {
                "input_tokens": 3403,
                "output_tokens": 1120,
                "response_cost": 0.06868,
            },
        },
        "event_1",
        "image-fast",
        "image",
        httpx.Headers({"x-litellm-response-cost": "0.00056"}),
    )

    assert usage.cost_usd == 0.06868
    assert usage.cost_source == "litellm_usage_cost"


def test_pricing_estimate_drift_pct_only_for_provider_reported_image_cost():
    usage = client.UsageRecord(
        provider="openai",
        model="image-quality",
        provider_model="openai/gpt-image-2",
        operation="image",
        image_count=1,
        cost_usd=0.075,
        cost_source="litellm_response_header",
    )

    assert client._pricing_estimate_drift_pct(
        operation="image",
        estimated_cost_usd=0.05,
        usage=usage,
    ) == pytest.approx(50.0)
    assert client._pricing_estimate_drift_pct(
        operation="text",
        estimated_cost_usd=0.05,
        usage=usage,
    ) is None


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
            model="image-balanced",
            prompt="draw this",
            output_path=output_path,
            width=1024,
            height=1536,
            steps=28,
            refs=[RefImage(path=reference_path, role="subject")],
        )
    )

    request = _FakeAsyncClient.last_request
    assert request is not None
    assert request["url"].endswith("/v1/images/edits")
    assert request["data"]["model"] == "image-balanced"
    assert request["data"]["size"] == "1024x1536"
    # assert request["data"]["steps"] == "28"
    assert "response_format" not in request["data"]
    assert request["files"][0][0] == "image"
    assert request["files"][0][1][0] == "__role_subject__character.png"


def test_generate_image_reference_filename_includes_label(monkeypatch, tmp_path: Path):
    image_bytes = b"fake png"
    _patch_http(monkeypatch, {
        "id": "img_1",
        "model": "openai/gpt-image-1",
        "data": [{"b64_json": base64.b64encode(image_bytes).decode()}],
    })

    output_path = tmp_path / "panel.png"
    reference_path = tmp_path / "front.png"
    reference_path.write_bytes(b"reference png")

    asyncio.run(
        client.generate_image(
            config=Config(),
            model="image-balanced",
            prompt="draw this",
            output_path=output_path,
            width=1024,
            height=1536,
            refs=[RefImage(path=reference_path, role="subject", label="Mr. White")],
        )
    )

    request = _FakeAsyncClient.last_request
    assert request is not None
    assert request["files"][0][1][0] == "__role_subject__character_mr_white_front.png"


def test_gpt_image_2_alias_uses_exact_valid_panel_size(monkeypatch, tmp_path: Path):
    image_bytes = b"fake png"
    _patch_http(monkeypatch, {
        "id": "img_1",
        "model": "openai/gpt-image-2",
        "data": [{"b64_json": base64.b64encode(image_bytes).decode()}],
    })

    output_path = tmp_path / "panel.png"
    asyncio.run(
        client.generate_image(
            config=Config(),
            model="openai/gpt-image-2",
            prompt="draw this",
            output_path=output_path,
            width=768,
            height=1344,
        )
    )

    request = _FakeAsyncClient.last_request
    assert request is not None
    assert request["json"]["size"] == "768x1344"


def test_failed_request_estimate_all_finalizes_billable_usage(monkeypatch, _patch_events):
    _patch_http(monkeypatch, {"error": {"message": "provider failed"}})
    _FakeAsyncClient.status_code = 500

    with pytest.raises(RuntimeError):
        asyncio.run(
            client.generate_text(
                config=Config(ai_bill_failed_requests="estimate_all"),
                model="prompt-balanced",
                system_prompt="system",
                user_content="user",
                feature="test.failure",
            )
        )

    finalized = _patch_events[-1][1]
    assert finalized["status"] == "failed"
    assert finalized["usage"] is not None
    assert finalized["config"].ai_bill_failed_requests == "estimate_all"


# ── _post_with_retry: rate-limit-aware backoff ──────────────────────────────


def _patch_sleep(monkeypatch) -> list[float]:
    delays: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        delays.append(seconds)

    monkeypatch.setattr(client.asyncio, "sleep", fake_sleep)
    return delays


def _mock_transport(monkeypatch, handler) -> None:
    monkeypatch.setattr(
        client, "_http", httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )


class TestPostWithRetry:
    def test_recovers_after_rate_limit_and_honors_retry_after(self, monkeypatch):
        delays = _patch_sleep(monkeypatch)
        calls = {"n": 0}

        def handler(request):
            calls["n"] += 1
            if calls["n"] <= 2:
                return httpx.Response(429, headers={"retry-after": "7"})
            return httpx.Response(200, json={"ok": True})

        _mock_transport(monkeypatch, handler)
        response = asyncio.run(client._post_with_retry("http://gw/v1/x", headers={}, json={}))
        assert response.status_code == 200
        assert calls["n"] == 3
        # Both waits honor the advertised Retry-After (plus up to 1s jitter).
        assert all(7.0 <= d <= 8.0 for d in delays)

    def test_rate_limit_budget_exhausted_raises(self, monkeypatch):
        delays = _patch_sleep(monkeypatch)
        calls = {"n": 0}

        def handler(request):
            calls["n"] += 1
            return httpx.Response(429)

        _mock_transport(monkeypatch, handler)
        with pytest.raises(httpx.HTTPStatusError):
            asyncio.run(client._post_with_retry("http://gw/v1/x", headers={}, json={}))
        assert calls["n"] == client._MAX_RATE_LIMIT_RETRIES + 1
        assert len(delays) == client._MAX_RATE_LIMIT_RETRIES
        # Without Retry-After the jittered windows grow monotonically and stay
        # within the configured cap.
        assert delays == sorted(delays)
        assert delays[0] >= client._RATE_LIMIT_BASE_DELAY / 2
        assert delays[-1] <= client._RATE_LIMIT_MAX_DELAY

    def test_transient_errors_keep_smaller_budget(self, monkeypatch):
        delays = _patch_sleep(monkeypatch)
        calls = {"n": 0}

        def handler(request):
            calls["n"] += 1
            return httpx.Response(503)

        _mock_transport(monkeypatch, handler)
        with pytest.raises(httpx.HTTPStatusError):
            asyncio.run(client._post_with_retry("http://gw/v1/x", headers={}, json={}))
        assert calls["n"] == client._MAX_RETRIES + 1
        assert len(delays) == client._MAX_RETRIES


class TestRetryAfterSeconds:
    def _response(self, headers: dict[str, str]) -> httpx.Response:
        return httpx.Response(429, headers=headers)

    def test_delta_seconds(self):
        assert client._retry_after_seconds(self._response({"retry-after": "7"})) == 7.0

    def test_http_date(self):
        import email.utils
        from datetime import UTC, datetime, timedelta

        future = email.utils.format_datetime(datetime.now(UTC) + timedelta(seconds=30), usegmt=True)
        value = client._retry_after_seconds(self._response({"retry-after": future}))
        assert value is not None
        assert 25.0 < value < 31.0

    def test_garbage_returns_none(self):
        assert client._retry_after_seconds(self._response({"retry-after": "soonish"})) is None

    def test_missing_returns_none(self):
        assert client._retry_after_seconds(self._response({})) is None

    def test_negative_delta_clamps_to_zero(self):
        assert client._retry_after_seconds(self._response({"retry-after": "-5"})) == 0.0
