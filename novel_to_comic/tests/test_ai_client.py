import asyncio
import base64
import json
from pathlib import Path
from urllib.parse import parse_qs

import httpx
import pytest

from novel_to_comic.ai import client
from novel_to_comic.ai.context import stream_observer
from novel_to_comic.ai.errors import AITransportError
from novel_to_comic.ai.providers.base import RefImage
from novel_to_comic.config import Config


class _FakeResponse:
    def __init__(self, payload: dict, status_code: int = 200):
        self._payload = payload
        self.status_code = status_code
        self.text = str(payload)
        self.content = self.text.encode()
        self.headers: dict = {}
        self.request = None

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


def _sse_lines(payload: dict) -> list[str]:
    """Render a buffered chat-completion body as the SSE lines the client parses.

    Lets tests keep declaring the familiar buffered shape while exercising the
    streaming code path the text client actually uses.
    """
    carried = {k: v for k, v in payload.items() if k not in {"choices", "usage"}}
    choices = payload.get("choices") or []
    lines: list[str] = []
    if choices:
        choice = choices[0]
        message = choice.get("message") or {}
        delta: dict = {"role": "assistant"}
        if message.get("content") is not None:
            delta["content"] = message["content"]
        if message.get("refusal"):
            delta["refusal"] = message["refusal"]
        rebuilt: dict = {
            "index": 0,
            "delta": delta,
            "finish_reason": choice.get("finish_reason"),
        }
        if choice.get("content_filter_results"):
            rebuilt["content_filter_results"] = choice["content_filter_results"]
        lines += [f"data: {json.dumps({**carried, 'choices': [rebuilt]})}", ""]
    else:
        lines += [f"data: {json.dumps({**carried, 'choices': []})}", ""]
    if payload.get("usage"):
        lines += [
            f"data: {json.dumps({'choices': [], 'usage': payload['usage']})}",
            "",
        ]
    lines += ["data: [DONE]", ""]
    return lines


class _FakeStreamResponse(_FakeResponse):
    async def aread(self):
        return self.content

    async def aiter_lines(self):
        for line in _sse_lines(self._payload):
            yield line


class _FakeStreamContext:
    def __init__(self, response: _FakeStreamResponse):
        self._response = response

    async def __aenter__(self):
        return self._response

    async def __aexit__(self, exc_type, exc, tb):
        return None


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
        return _FakeResponse(
            self.__class__.response_payload, status_code=self.__class__.status_code
        )

    async def get(self, url, **kwargs):
        self.__class__.last_request = {"url": url, **kwargs}
        return _FakeResponse({})

    def stream(self, method, url, **kwargs):
        self.__class__.last_request = {"url": url, "method": method, **kwargs}
        return _FakeStreamContext(
            _FakeStreamResponse(
                self.__class__.response_payload,
                status_code=self.__class__.status_code,
            )
        )


@pytest.fixture(autouse=True)
def _patch_events(monkeypatch):
    events = []
    monkeypatch.setattr(
        client, "_insert_event", lambda **kwargs: events.append(("insert", kwargs))
    )
    monkeypatch.setattr(
        client, "_finalize_event", lambda **kwargs: events.append(("finalize", kwargs))
    )
    return events


def _patch_http(monkeypatch, payload: dict):
    _FakeAsyncClient.response_payload = payload
    _FakeAsyncClient.status_code = 200
    _FakeAsyncClient.last_request = None
    monkeypatch.setattr(client, "_http", _FakeAsyncClient())


def test_generate_structured_object_returns_dict_and_usage(monkeypatch, _patch_events):
    _patch_http(
        monkeypatch,
        {
            "id": "resp_1",
            "model": "openai/gpt-5.4-mini",
            "choices": [{"message": {"content": '{"ok": true}'}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 3, "total_tokens": 13},
        },
    )

    result = asyncio.run(
        client.generate_structured_object(
            config=Config(),
            model="gpt-5.6-terra",
            system_prompt="Return JSON.",
            user_content="{}",
            feature="test.json",
            json_schema={
                "type": "object",
                "properties": {"ok": {"type": "boolean"}},
                "required": ["ok"],
            },
        )
    )

    assert result.value == {"ok": True}
    assert result.usage is not None
    assert result.usage.call_id
    assert result.usage.provider == "openai"
    assert result.usage.model == "gpt-5.6-terra"
    assert result.usage.provider_model == "openai/gpt-5.4-mini"
    assert result.usage.input_tokens == 10
    assert result.usage.output_tokens == 3
    response_format = _FakeAsyncClient.last_request["json"]["response_format"]
    assert response_format["type"] == "json_schema"
    assert response_format["json_schema"]["name"] == "test_json"
    assert response_format["json_schema"]["strict"] is True
    assert response_format["json_schema"]["schema"]["required"] == ["ok"]
    assert _patch_events[0][0] == "insert"
    assert _patch_events[-1][1]["status"] == "succeeded"


def test_openrouter_structured_request_uses_supported_max_tokens_field(
    monkeypatch, _patch_events
):
    _patch_http(
        monkeypatch,
        {
            "id": "glm-response",
            "model": "z-ai/glm-5.3-flash",
            "choices": [{"message": {"content": '{"ok": true}'}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 3, "total_tokens": 13},
        },
    )

    result = asyncio.run(
        client.generate_structured_object(
            config=Config(),
            model="glm-5.3-flash",
            system_prompt="Return JSON.",
            user_content="{}",
            max_output_tokens=128,
            feature="extract.story_bible",
            json_schema={
                "type": "object",
                "properties": {"ok": {"type": "boolean"}},
                "required": ["ok"],
            },
        )
    )

    assert result.value == {"ok": True}
    request = _FakeAsyncClient.last_request["json"]
    assert request["max_tokens"] == 128
    assert "max_completion_tokens" not in request


def test_generate_structured_object_retries_then_succeeds_on_malformed_json(
    monkeypatch, _patch_events
):
    payloads = [
        {
            "id": "resp_1",
            "model": "openai/gpt-5.4-mini",
            "choices": [
                {"message": {"content": '{"ok": tru'}, "finish_reason": "length"}
            ],
            "usage": {"prompt_tokens": 10, "completion_tokens": 3, "total_tokens": 13},
        },
        {
            "id": "resp_2",
            "model": "openai/gpt-5.4-mini",
            "choices": [{"message": {"content": '{"ok": true}'}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 3, "total_tokens": 13},
        },
    ]
    calls = {"n": 0, "payloads": []}

    class _SeqClient:
        async def get(self, url, **kwargs):
            return _FakeResponse({})

        def stream(self, method, url, **kwargs):
            calls["payloads"].append(kwargs["json"])
            i = calls["n"]
            calls["n"] += 1
            return _FakeStreamContext(_FakeStreamResponse(payloads[i]))

    monkeypatch.setattr(client, "_http", _SeqClient())

    result = asyncio.run(
        client.generate_structured_object(
            config=Config(),
            model="gpt-5.6-terra",
            system_prompt="Return JSON.",
            user_content="{}",
            feature="test.json",
        )
    )

    assert result.value == {"ok": True}
    assert calls["n"] == 2
    assert len(result.additional_usage) == 1
    assert result.additional_usage[0].input_tokens == 10
    retry_message = calls["payloads"][1]["messages"][1]["content"]
    assert "previous response was not valid JSON" in retry_message
    assert "reached the output token limit" in retry_message
    assert "Expecting value" in retry_message


def test_structured_response_retains_malformed_paid_text_without_resubmission(
    monkeypatch, tmp_path, _patch_events,
):
    raw_text = '```json\n{"lettering": [\n```'
    _patch_http(monkeypatch, {
        "id": "ocr-response",
        "model": "google/gemini-3.8-flash",
        "choices": [{"message": {"content": raw_text}}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 3, "total_tokens": 13},
    })
    retained_path = tmp_path / "response.json"

    def retain(response):
        retained_path.write_text(json.dumps({
            "text": response.value,
            "usage": response.usage.model_dump(),
        }))

    with pytest.raises(ValueError):
        asyncio.run(client.generate_structured_object(
            config=Config(),
            model="gemini-3.8-flash",
            system_prompt="Transcribe visible text.",
            user_content="Read this page.",
            response_sink=retain,
            retry_invalid_json=False,
        ))

    retained = json.loads(retained_path.read_text())
    assert retained["text"] == raw_text
    assert retained["usage"]["output_tokens"] == 3
    assert sum(kind == "insert" for kind, _ in _patch_events) == 1


def test_response_persistence_failure_does_not_resubmit_paid_request(
    monkeypatch, _patch_events,
):
    _patch_http(monkeypatch, {
        "id": "ocr-response",
        "model": "google/gemini-3.8-flash",
        "choices": [{"message": {"content": '{"lettering": []}'}}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 3, "total_tokens": 13},
    })

    def cannot_persist(_response):
        raise OSError("storage unavailable")

    with pytest.raises(OSError, match="storage unavailable"):
        asyncio.run(client.generate_structured_object(
            config=Config(),
            model="gemini-3.8-flash",
            system_prompt="Transcribe visible text.",
            user_content="Read this page.",
            response_sink=cannot_persist,
        ))

    assert sum(kind == "insert" for kind, _ in _patch_events) == 1


def test_generate_structured_object_raises_with_context_after_exhausting_retries(
    monkeypatch, _patch_events
):
    bad_content = '{"ok": tru'
    _patch_http(
        monkeypatch,
        {
            "id": "resp_1",
            "model": "openai/gpt-5.4-mini",
            "choices": [{"message": {"content": bad_content}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 3, "total_tokens": 13},
        },
    )

    with pytest.raises(ValueError) as exc_info:
        asyncio.run(
            client.generate_structured_object(
                config=Config(),
                model="gpt-5.6-terra",
                system_prompt="Return JSON.",
                user_content="{}",
                feature="test.json",
            )
        )

    msg = str(exc_info.value)
    assert "malformed JSON" in msg
    assert "gpt-5.6-terra" in msg
    assert "tru" in msg
    assert isinstance(exc_info.value.__cause__, __import__("json").JSONDecodeError)


def test_generate_text_does_not_store_prompt_in_params(monkeypatch, _patch_events):
    _patch_http(
        monkeypatch,
        {
            "id": "resp_1",
            "model": "anthropic/claude-sonnet-4-6",
            "choices": [{"message": {"content": "hello"}}],
            "usage": {"prompt_tokens": 4, "completion_tokens": 1},
        },
    )

    asyncio.run(
        client.generate_text(
            config=Config(),
            model="gpt-5.6-terra",
            system_prompt="system secret",
            user_content="user secret",
            feature="test.text",
        )
    )

    inserted = _patch_events[0][1]
    assert "messages" not in inserted["params_json"]
    assert inserted["request_summary_json"]["system_prompt_sha256"]
    assert inserted["request_summary_json"]["user_content_sha256"]


@pytest.mark.skip(reason="removed raw image transport; covered by provider-wire tests")
def test_generate_image_writes_b64_response(monkeypatch, tmp_path: Path):
    image_bytes = b"fake png"
    _patch_http(
        monkeypatch,
        {
            "id": "img_1",
            "model": "openai/gpt-image-1",
            "data": [{"b64_json": base64.b64encode(image_bytes).decode()}],
        },
    )

    output_path = tmp_path / "panel.png"
    result = asyncio.run(
        client.generate_image(
            config=Config(),
            model="image-gemini-pro",
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
    assert request["json"]["model"] == "image-gemini-pro"
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
        "gpt-5.6-terra",
        "text",
    )

    assert usage.provider_model == "openai/gpt-5.4-mini"
    assert usage.cost_usd == 0.0042
    assert usage.cost_source == "litellm_response_cost"


def test_extract_usage_prefers_body_cost_over_litellm_header():
    usage = client._extract_usage(
        {
            "model": "image-gemini-flash-lite",
            "usage": {
                "input_tokens": 3403,
                "output_tokens": 1120,
                "response_cost": 0.06868,
            },
        },
        "event_1",
        "image-gemini-flash-lite",
        "image",
        httpx.Headers({"x-litellm-response-cost": "0.00056"}),
    )

    assert usage.cost_usd == 0.06868
    assert usage.cost_source == "litellm_usage_cost"


def test_pricing_estimate_drift_pct_only_for_provider_reported_image_cost():
    usage = client.UsageRecord(
        provider="openai",
        model="image-gpt-2",
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
    assert (
        client._pricing_estimate_drift_pct(
            operation="text",
            estimated_cost_usd=0.05,
            usage=usage,
        )
        is None
    )


@pytest.mark.skip(reason="removed raw image transport; covered by provider-wire tests")
def test_generate_image_with_references_uses_image_edits(monkeypatch, tmp_path: Path):
    image_bytes = b"fake png"
    _patch_http(
        monkeypatch,
        {
            "id": "img_1",
            "model": "openai/gpt-image-1",
            "data": [{"b64_json": base64.b64encode(image_bytes).decode()}],
        },
    )

    output_path = tmp_path / "panel.png"
    reference_path = tmp_path / "character.png"
    reference_path.write_bytes(b"reference png")

    asyncio.run(
        client.generate_image(
            config=Config(),
            model="image-gemini-pro",
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
    assert request["data"]["model"] == "image-gemini-pro"
    assert request["data"]["size"] == "1024x1536"
    # assert request["data"]["steps"] == "28"
    assert "response_format" not in request["data"]
    assert request["files"][0][0] == "image"
    assert request["files"][0][1][0] == "__role_subject__character.png"


@pytest.mark.skip(reason="reference filenames no longer carry semantics")
def test_generate_image_reference_filename_includes_label(monkeypatch, tmp_path: Path):
    image_bytes = b"fake png"
    _patch_http(
        monkeypatch,
        {
            "id": "img_1",
            "model": "openai/gpt-image-1",
            "data": [{"b64_json": base64.b64encode(image_bytes).decode()}],
        },
    )

    output_path = tmp_path / "panel.png"
    reference_path = tmp_path / "front.png"
    reference_path.write_bytes(b"reference png")

    asyncio.run(
        client.generate_image(
            config=Config(),
            model="image-gemini-pro",
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


@pytest.mark.skip(reason="removed raw image transport; geometry is compiler-owned")
def test_gpt_image_2_alias_uses_exact_valid_panel_size(monkeypatch, tmp_path: Path):
    image_bytes = b"fake png"
    _patch_http(
        monkeypatch,
        {
            "id": "img_1",
            "model": "openai/gpt-image-2",
            "data": [{"b64_json": base64.b64encode(image_bytes).decode()}],
        },
    )

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


def test_failed_request_estimate_all_finalizes_billable_usage(
    monkeypatch, _patch_events
):
    _patch_http(monkeypatch, {"error": {"message": "provider failed"}})
    _FakeAsyncClient.status_code = 500

    with pytest.raises(RuntimeError):
        asyncio.run(
            client.generate_text(
                config=Config(ai_bill_failed_requests="estimate_all"),
                model="gpt-5.6-luna",
                system_prompt="system",
                user_content="user",
                feature="test.failure",
            )
        )

    finalized = _patch_events[-1][1]
    assert finalized["status"] == "failed"
    assert finalized["usage"] is not None
    assert finalized["config"].ai_bill_failed_requests == "estimate_all"


def test_text_gateway_error_identifies_feature_model_and_provider_detail(
    monkeypatch,
    _patch_events,
):
    def handler(request):
        return httpx.Response(
            404,
            request=request,
            json={
                "error": {
                    "message": "Publisher model gemini-preview was not found in global",
                    "code": "NOT_FOUND",
                }
            },
        )

    _mock_transport(monkeypatch, handler)

    with pytest.raises(AITransportError) as exc_info:
        asyncio.run(
            client.generate_text(
                config=Config(),
                model="gpt-5.6-luna",
                system_prompt="system",
                user_content="user",
                feature="style.suggestions",
            )
        )

    message = str(exc_info.value)
    assert "style.suggestions" in message
    assert "gpt-5.6-luna" in message
    assert "/v1/chat/completions" in message
    assert "404 Not Found" in message
    assert "Publisher model gemini-preview was not found in global" in message
    assert exc_info.value.phase == "gateway_request"
    assert exc_info.value.response is not None
    assert _patch_events[-1][1]["status"] == "failed"


def test_text_gateway_read_error_identifies_operation_after_retries(
    monkeypatch,
    _patch_events,
):
    delays = _patch_sleep(monkeypatch)
    calls = {"count": 0}

    def handler(request):
        calls["count"] += 1
        raise httpx.ReadError("", request=request)

    _mock_transport(monkeypatch, handler)

    with pytest.raises(AITransportError) as exc_info:
        asyncio.run(
            client.generate_text(
                config=Config(),
                model="gpt-5.6-luna",
                system_prompt="system",
                user_content="user",
                feature="style.suggestions",
            )
        )

    message = str(exc_info.value)
    assert "style.suggestions" in message
    assert "gpt-5.6-luna" in message
    assert "/v1/chat/completions" in message
    assert "transport ReadError" in message
    assert "after 4 attempts" in message
    assert calls["count"] == 4
    assert len(delays) == 3
    assert exc_info.value.phase == "gateway_request"
    assert _patch_events[-1][1]["status"] == "failed"


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
    def test_preserves_form_data_when_no_files_are_present(self, monkeypatch):
        captured: dict[str, str] = {}

        def handler(request):
            captured.update(parse_qs(request.content.decode()))
            return httpx.Response(200, json={"ok": True})

        _mock_transport(monkeypatch, handler)
        response = asyncio.run(
            client._post_with_retry(
                "http://gw/v1/images/edits",
                headers={},
                data={"model": "image-gemini-pro", "prompt": "page 11"},
                files=[],
            )
        )

        assert response.status_code == 200
        assert captured == {"model": ["image-gemini-pro"], "prompt": ["page 11"]}

    def test_recovers_after_rate_limit_and_honors_retry_after(self, monkeypatch):
        delays = _patch_sleep(monkeypatch)
        calls = {"n": 0}

        def handler(request):
            calls["n"] += 1
            if calls["n"] <= 2:
                return httpx.Response(429, headers={"retry-after": "7"})
            return httpx.Response(200, json={"ok": True})

        _mock_transport(monkeypatch, handler)
        response = asyncio.run(
            client._post_with_retry("http://gw/v1/x", headers={}, json={})
        )
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
        # Without Retry-After, each equal-jitter delay stays inside its
        # exponential window. Independent jitter can make a sampled delay
        # smaller than the previous sample once the final window is capped.
        windows = [
            min(
                client._RATE_LIMIT_BASE_DELAY * 2**attempt,
                client._RATE_LIMIT_MAX_DELAY,
            )
            for attempt in range(client._MAX_RATE_LIMIT_RETRIES)
        ]
        for delay, window in zip(delays, windows, strict=True):
            assert window / 2 <= delay <= window

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

    def test_read_timeout_is_retried(self, monkeypatch):
        _patch_sleep(monkeypatch)
        calls = {"n": 0}

        def handler(request):
            calls["n"] += 1
            if calls["n"] == 1:
                raise httpx.ReadTimeout("timed out", request=request)
            return httpx.Response(200, json={"ok": True})

        _mock_transport(monkeypatch, handler)
        response = asyncio.run(
            client._post_with_retry("http://gw/v1/x", headers={}, json={})
        )
        assert response.status_code == 200
        assert calls["n"] == 2

    def test_read_timeout_budget_is_smaller_than_transient(self, monkeypatch):
        delays = _patch_sleep(monkeypatch)
        calls = {"n": 0}

        def handler(request):
            calls["n"] += 1
            raise httpx.ReadTimeout("timed out", request=request)

        _mock_transport(monkeypatch, handler)
        with pytest.raises(httpx.ReadTimeout):
            asyncio.run(client._post_with_retry("http://gw/v1/x", headers={}, json={}))
        # Each attempt costs the full read budget, so timeouts get one retry
        # rather than the transient-error budget.
        assert client._MAX_TIMEOUT_RETRIES < client._MAX_RETRIES
        assert calls["n"] == client._MAX_TIMEOUT_RETRIES + 1
        assert len(delays) == client._MAX_TIMEOUT_RETRIES


def _sse_body(*events: dict) -> bytes:
    lines = [f"data: {json.dumps(e)}\n\n" for e in events]
    return ("".join(lines) + "data: [DONE]\n\n").encode()


class TestStreamingChatCompletion:
    def test_collapse_joins_deltas_and_keeps_terminal_usage(self):
        collapsed = client._collapse_chat_chunks(
            [
                {"id": "c1", "model": "m", "choices": [{"delta": {"content": '{"ok"'}}]},
                {"choices": [{"delta": {"content": ": true}"}}]},
                {"choices": [{"delta": {}, "finish_reason": "stop"}]},
                {"choices": [], "usage": {"prompt_tokens": 7, "completion_tokens": 2}},
            ]
        )
        choice = collapsed["choices"][0]
        assert choice["message"]["content"] == '{"ok": true}'
        assert choice["finish_reason"] == "stop"
        assert collapsed["usage"]["completion_tokens"] == 2
        assert collapsed["id"] == "c1"
        assert collapsed["model"] == "m"

    def test_text_request_streams_and_reassembles_chunks(
        self, monkeypatch, _patch_events
    ):
        sent: dict = {}

        def handler(request):
            sent.update(json.loads(request.content))
            return httpx.Response(
                200,
                content=_sse_body(
                    {"model": "openai/gpt-5.4-mini", "choices": [{"delta": {"content": '{"ok":'}}]},
                    {"choices": [{"delta": {"content": " true}"}}]},
                    {"choices": [{"delta": {}, "finish_reason": "stop"}]},
                    {
                        "choices": [],
                        "usage": {
                            "prompt_tokens": 11,
                            "completion_tokens": 4,
                            "total_tokens": 15,
                        },
                    },
                ),
            )

        _mock_transport(monkeypatch, handler)
        result = asyncio.run(
            client.generate_structured_object(
                config=Config(),
                model="gpt-5.6-terra",
                system_prompt="Return JSON.",
                user_content="{}",
                feature="test.stream",
                json_schema={"type": "object", "properties": {"ok": {"type": "boolean"}}},
            )
        )

        assert result.value == {"ok": True}
        assert result.usage.output_tokens == 4
        assert sent["stream"] is True
        assert sent["stream_options"] == {"include_usage": True}

    def test_no_content_within_the_first_content_budget_times_out(self, monkeypatch):
        monkeypatch.setattr(client, "_STREAM_FIRST_CONTENT_TIMEOUT", 0.0)

        def handler(request):
            # Keepalives reset the per-chunk read timeout, so only the
            # first-content bound can stop this.
            return httpx.Response(200, content=b": keepalive\n\n" * 4)

        _mock_transport(monkeypatch, handler)
        with pytest.raises(httpx.ReadTimeout, match="no content in the first"):
            asyncio.run(
                client._read_chat_stream("http://gw/v1/x", headers={}, payload={})
            )

    def test_first_content_bound_sits_above_the_read_timeout(self):
        # Below it, a slow-but-healthy request (observed: ~520s before first
        # content) would be killed by the guard meant for masked stalls.
        assert client._STREAM_FIRST_CONTENT_TIMEOUT > client._READ_TIMEOUT
        assert client._STREAM_FIRST_CONTENT_TIMEOUT < client._STREAM_TOTAL_TIMEOUT

    def test_content_free_chunks_do_not_trip_the_first_content_bound(
        self, monkeypatch
    ):
        monkeypatch.setattr(client, "_STREAM_FIRST_CONTENT_TIMEOUT", 30.0)

        def handler(request):
            return httpx.Response(
                200,
                content=_sse_body(
                    {"choices": [{"delta": {"role": "assistant"}}]},
                    {"choices": [{"delta": {"content": "ok"}}]},
                ),
            )

        _mock_transport(monkeypatch, handler)
        data, _ = asyncio.run(
            client._read_chat_stream("http://gw/v1/x", headers={}, payload={})
        )
        assert data["choices"][0]["message"]["content"] == "ok"

    def test_parse_failure_log_names_the_cause(self, monkeypatch, caplog):
        # A truncated string looks the same whether the model hit its cap or the
        # stream lost an event, so the log has to carry both signals.
        def handler(request):
            return httpx.Response(
                200,
                content=_sse_body(
                    {"choices": [{"delta": {"content": '{"ok": "unterminated'}}]},
                    {"choices": [{"delta": {}, "finish_reason": "length"}]},
                ),
            )

        _mock_transport(monkeypatch, handler)
        with caplog.at_level("WARNING"):
            with pytest.raises(Exception):
                asyncio.run(
                    client.generate_structured_object(
                        config=Config(),
                        model="gpt-5.6-terra",
                        system_prompt="Return JSON.",
                        user_content="{}",
                        feature="test.truncated",
                    )
                )

        assert "finish_reason=length" in caplog.text
        assert "dropped_events=0" in caplog.text
        assert "stream_events=2" in caplog.text
        assert f"chars={len('{\"ok\": \"unterminated')}" in caplog.text

    def test_stream_exceeding_total_budget_raises_read_timeout(self, monkeypatch):
        monkeypatch.setattr(client, "_STREAM_TOTAL_TIMEOUT", 0.05)

        async def trickle():
            yield b'data: {"choices": [{"delta": {"content": "x"}}]}\n\n'
            # Chunks keep arriving, so the per-chunk read timeout never fires —
            # only the wall-clock ceiling stops this.
            while True:
                await asyncio.sleep(0.01)
                yield b'data: {"choices": [{"delta": {"content": "x"}}]}\n\n'

        def handler(request):
            return httpx.Response(200, content=trickle())

        _mock_transport(monkeypatch, handler)
        with pytest.raises(httpx.ReadTimeout, match="total budget"):
            asyncio.run(
                client._read_chat_stream("http://gw/v1/x", headers={}, payload={})
            )

    def test_streaming_retries_retryable_status(self, monkeypatch):
        _patch_sleep(monkeypatch)
        calls = {"n": 0}

        def handler(request):
            calls["n"] += 1
            if calls["n"] == 1:
                return httpx.Response(503)
            return httpx.Response(
                200, content=_sse_body({"choices": [{"delta": {"content": "hi"}}]})
            )

        _mock_transport(monkeypatch, handler)
        data, response = asyncio.run(
            client._stream_with_retry("http://gw/v1/x", headers={}, payload={})
        )
        assert calls["n"] == 2
        assert response.status_code == 200
        assert data["choices"][0]["message"]["content"] == "hi"

    def test_parses_events_without_blank_line_separators(self, monkeypatch):
        # A server that skips the spec's blank line still has to work: each
        # data line is dispatched as soon as it parses.
        body = (
            b'data: {"choices": [{"delta": {"content": "ab"}}]}\n'
            b'data: {"choices": [{"delta": {"content": "cd"}}]}\n'
            b"data: [DONE]\n"
        )

        def handler(request):
            return httpx.Response(200, content=body)

        _mock_transport(monkeypatch, handler)
        data, _ = asyncio.run(
            client._read_chat_stream("http://gw/v1/x", headers={}, payload={})
        )
        assert data["choices"][0]["message"]["content"] == "abcd"
        assert data["_canary_stream"] == {"events": 2, "dropped": 0}

    def test_parses_a_payload_split_across_data_lines(self, monkeypatch):
        body = (
            b'data: {"choices": [{"delta":\n'
            b'data:  {"content": "split"}}]}\n'
            b"\n"
            b"data: [DONE]\n\n"
        )

        def handler(request):
            return httpx.Response(200, content=body)

        _mock_transport(monkeypatch, handler)
        data, _ = asyncio.run(
            client._read_chat_stream("http://gw/v1/x", headers={}, payload={})
        )
        assert data["choices"][0]["message"]["content"] == "split"
        assert data["_canary_stream"]["dropped"] == 0

    def test_unparsable_event_is_counted_not_swallowed(self, monkeypatch, caplog):
        body = (
            b'data: {"choices": [{"delta": {"content": "kept"}}]}\n\n'
            b"data: {not json at all\n\n"
            b"data: [DONE]\n\n"
        )

        def handler(request):
            return httpx.Response(200, content=body)

        _mock_transport(monkeypatch, handler)
        with caplog.at_level("WARNING"):
            data, _ = asyncio.run(
                client._read_chat_stream("http://gw/v1/x", headers={}, payload={})
            )
        # The hole is reported rather than surfacing later as a mystery JSON error.
        assert data["_canary_stream"]["dropped"] == 1
        assert "unparsable stream event" in caplog.text

    def test_sse_comments_are_ignored(self, monkeypatch):
        body = (
            b": keepalive\n\n"
            b'data: {"choices": [{"delta": {"content": "hi"}}]}\n\n'
            b"data: [DONE]\n\n"
        )

        def handler(request):
            return httpx.Response(200, content=body)

        _mock_transport(monkeypatch, handler)
        data, _ = asyncio.run(
            client._read_chat_stream("http://gw/v1/x", headers={}, payload={})
        )
        assert data["choices"][0]["message"]["content"] == "hi"
        assert data["_canary_stream"]["dropped"] == 0

    def test_observer_sees_cumulative_characters(self, monkeypatch):
        seen: list[int] = []

        def handler(request):
            return httpx.Response(
                200,
                content=_sse_body(
                    {"choices": [{"delta": {"content": "abc"}}]},
                    {"choices": [{"delta": {"content": "de"}}]},
                    {"choices": [{"delta": {}, "finish_reason": "stop"}]},
                ),
            )

        _mock_transport(monkeypatch, handler)
        with stream_observer(seen.append):
            asyncio.run(
                client._read_chat_stream("http://gw/v1/x", headers={}, payload={})
            )
        # Leading 0 is the "request in flight" signal, before any content.
        assert seen == [0, 3, 5, 5]

    def test_observer_failure_does_not_break_the_request(self, monkeypatch):
        def handler(request):
            return httpx.Response(
                200, content=_sse_body({"choices": [{"delta": {"content": "hi"}}]})
            )

        def boom(_chars):
            raise RuntimeError("observer exploded")

        _mock_transport(monkeypatch, handler)
        with stream_observer(boom):
            data, _ = asyncio.run(
                client._read_chat_stream("http://gw/v1/x", headers={}, payload={})
            )
        assert data["choices"][0]["message"]["content"] == "hi"

    def test_buffered_reply_to_a_stream_request_is_still_parsed(self, monkeypatch):
        def handler(request):
            return httpx.Response(
                200,
                json={
                    "model": "m",
                    "choices": [{"message": {"content": "hi"}, "finish_reason": "stop"}],
                },
            )

        _mock_transport(monkeypatch, handler)
        data, _ = asyncio.run(
            client._read_chat_stream("http://gw/v1/x", headers={}, payload={})
        )
        assert data["choices"][0]["message"]["content"] == "hi"

    def test_streaming_leaves_non_retryable_status_to_caller(self, monkeypatch):
        def handler(request):
            return httpx.Response(400, json={"error": {"message": "bad schema"}})

        _mock_transport(monkeypatch, handler)
        data, response = asyncio.run(
            client._stream_with_retry("http://gw/v1/x", headers={}, payload={})
        )
        # Body is read so _gateway_http_error can still quote the provider detail.
        assert data == {}
        assert response.status_code == 400
        assert response.json()["error"]["message"] == "bad schema"


class TestStreamingOptOut:
    def test_stream_text_enabled_reads_the_env_var(self, monkeypatch):
        monkeypatch.delenv("CANARY_AI_STREAM_TEXT", raising=False)
        assert client._stream_text_enabled() is True
        for value in ("0", "false", "no", "off", "OFF"):
            monkeypatch.setenv("CANARY_AI_STREAM_TEXT", value)
            assert client._stream_text_enabled() is False
        monkeypatch.setenv("CANARY_AI_STREAM_TEXT", "1")
        assert client._stream_text_enabled() is True

    def test_opting_out_falls_back_to_a_buffered_request(
        self, monkeypatch, _patch_events
    ):
        monkeypatch.setenv("CANARY_AI_STREAM_TEXT", "0")
        _patch_http(
            monkeypatch,
            {
                "model": "gpt-5.6-terra",
                "choices": [{"message": {"content": '{"ok": true}'}}],
                "usage": {"prompt_tokens": 5, "completion_tokens": 2, "total_tokens": 7},
            },
        )

        result = asyncio.run(
            client.generate_structured_object(
                config=Config(),
                model="gpt-5.6-terra",
                system_prompt="Return JSON.",
                user_content="{}",
                feature="adapt.book",
            )
        )

        assert result.value == {"ok": True}
        assert result.usage.output_tokens == 2
        # The buffered path must not advertise streaming to the gateway.
        sent = _FakeAsyncClient.last_request["json"]
        assert "stream" not in sent
        assert "stream_options" not in sent
        assert "temperature" not in sent


class TestRetryAfterSeconds:
    def _response(self, headers: dict[str, str]) -> httpx.Response:
        return httpx.Response(429, headers=headers)

    def test_delta_seconds(self):
        assert client._retry_after_seconds(self._response({"retry-after": "7"})) == 7.0

    def test_http_date(self):
        import email.utils
        from datetime import UTC, datetime, timedelta

        future = email.utils.format_datetime(
            datetime.now(UTC) + timedelta(seconds=30), usegmt=True
        )
        value = client._retry_after_seconds(self._response({"retry-after": future}))
        assert value is not None
        assert 25.0 < value < 31.0

    def test_garbage_returns_none(self):
        assert (
            client._retry_after_seconds(self._response({"retry-after": "soonish"}))
            is None
        )

    def test_missing_returns_none(self):
        assert client._retry_after_seconds(self._response({})) is None

    def test_negative_delta_clamps_to_zero(self):
        assert client._retry_after_seconds(self._response({"retry-after": "-5"})) == 0.0


def test_bounded_submission_does_not_repeat_ambiguous_paid_request(monkeypatch):
    calls = []

    def handler(request):
        calls.append(request)
        raise httpx.ReadTimeout('response lost after submission', request=request)

    _mock_transport(monkeypatch, handler)
    with pytest.raises(client.AITransportError) as error:
        asyncio.run(client._post_with_retry(
            'http://gw/v1/images', headers={}, json={}, retry_ambiguous=False,
        ))
    assert error.value.phase == 'ambiguous_submission'
    assert len(calls) == 1


def test_bounded_submission_does_not_repeat_server_failure(monkeypatch):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(503, json={'error': 'upstream response lost'})

    _mock_transport(monkeypatch, handler)
    response = asyncio.run(client._post_with_retry(
        'http://gw/v1/images', headers={}, json={}, retry_ambiguous=False,
    ))
    assert response.status_code == 503
    assert len(calls) == 1


def test_finalize_shielded_completes_billing_before_cancellation_surfaces(
    monkeypatch,
):
    """Repeated cancellation cannot return ahead of the authoritative write."""
    import threading

    async def main():
        started = asyncio.Event()
        release = threading.Event()
        finished = threading.Event()
        loop = asyncio.get_running_loop()

        def finalize(**kwargs):
            loop.call_soon_threadsafe(started.set)
            assert release.wait(timeout=5), "test did not release persistence"
            finished.set()

        monkeypatch.setattr(client, "_finalize_event", finalize)
        task = asyncio.create_task(
            client._finalize_event_shielded(
                event_id="evt-cancel",
                status="succeeded",
                feature="test.cancel",
                model_alias="gpt-5.6-terra",
                latency_ms=1,
            )
        )
        try:
            await asyncio.wait_for(started.wait(), timeout=5)
            for _ in range(3):
                task.cancel()
                await asyncio.sleep(0)
                await asyncio.sleep(0)
                assert not task.done()
        finally:
            release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        # Assert before asyncio.run's executor shutdown can hide detached work.
        assert finished.is_set()

    asyncio.run(main())


def test_chat_completion_cancellation_records_cancelled_status(
    monkeypatch, _patch_events
):
    async def hang(url, *, headers, payload):
        await asyncio.sleep(60)
        raise AssertionError("unreachable")

    monkeypatch.setattr(client, "_stream_with_retry", hang)

    async def main():
        task = asyncio.create_task(
            client._chat_completion(
                config=Config(),
                model="gpt-5.6-terra",
                system_prompt="Return JSON.",
                user_content="{}",
                temperature=0.0,
                max_output_tokens=None,
                json_mode=False,
                feature="test.cancel",
            )
        )
        await asyncio.sleep(0.05)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(main())

    kinds = [kind for kind, _ in _patch_events]
    assert kinds[0] == "insert"
    assert _patch_events[-1][0] == "finalize"
    assert _patch_events[-1][1]["status"] == "cancelled"


def test_chat_completion_cancel_during_insert_still_records_cancelled(
    monkeypatch, _patch_events
):
    """Cancelling the newly offloaded insert await must not break bookkeeping."""
    import time

    def slow_insert(**kwargs):
        time.sleep(0.3)
        _patch_events.append(("insert", kwargs))

    monkeypatch.setattr(client, "_insert_event", slow_insert)
    _patch_http(
        monkeypatch,
        {
            "id": "resp_1",
            "model": "openai/gpt-5.4-mini",
            "choices": [{"message": {"content": "hello"}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 3},
        },
    )

    async def main():
        task = asyncio.create_task(
            client._chat_completion(
                config=Config(),
                model="gpt-5.6-terra",
                system_prompt="Say hi.",
                user_content="hi",
                temperature=0.0,
                max_output_tokens=None,
                json_mode=False,
                feature="test.cancel",
            )
        )
        await asyncio.sleep(0.05)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(main())

    assert _patch_events[-1][0] == "finalize"
    assert _patch_events[-1][1]["status"] == "cancelled"


def test_finalise_image_cancelled_records_cancelled_status(_patch_events):
    import datetime
    import time

    from novel_to_comic.ai.finalisation import (
        ImageCallContext,
        finalise_image_cancelled,
    )

    ctx = ImageCallContext(
        event_id="img-evt-cancel",
        operation="image",
        metadata={},
        params={},
        estimated_cost_usd=None,
        started=time.perf_counter(),
        started_at=datetime.datetime.now(datetime.UTC),
        langfuse_input={},
    )
    asyncio.run(
        finalise_image_cancelled(
            ctx=ctx,
            config=Config(),
            model="image-gemini-pro",
            feature="test.img",
            error=asyncio.CancelledError(),
        )
    )

    assert _patch_events[-1][0] == "finalize"
    assert _patch_events[-1][1]["status"] == "cancelled"
    assert _patch_events[-1][1]["event_id"] == "img-evt-cancel"


def test_chat_completion_late_cancel_does_not_overwrite_success(
    monkeypatch, _patch_events
):
    """A cancel landing during the success write keeps the succeeded status."""
    import threading
    import time

    entered = threading.Event()

    def slow_finalize(**kwargs):
        _patch_events.append(("finalize", kwargs))
        entered.set()
        time.sleep(0.3)

    monkeypatch.setattr(client, "_finalize_event", slow_finalize)
    _patch_http(
        monkeypatch,
        {
            "id": "resp_1",
            "model": "openai/gpt-5.4-mini",
            "choices": [{"message": {"content": "hello"}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 3},
        },
    )

    async def main():
        task = asyncio.create_task(
            client._chat_completion(
                config=Config(),
                model="gpt-5.6-terra",
                system_prompt="Say hi.",
                user_content="hi",
                temperature=0.0,
                max_output_tokens=None,
                json_mode=False,
                feature="test.cancel",
            )
        )
        for _ in range(500):
            if entered.is_set():
                break
            await asyncio.sleep(0.01)
        assert entered.is_set()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(main())

    finalizes = [kwargs for kind, kwargs in _patch_events if kind == "finalize"]
    assert len(finalizes) == 1
    assert finalizes[0]["status"] == "succeeded"


@pytest.mark.parametrize("failure", ["timeout", "cancel", "server_error", "protocol", "decoding"])
def test_ambiguous_paid_submission_retains_credit_hold(monkeypatch, failure):
    from novel_to_comic.ai.context import ai_request_context
    from novel_to_comic.server import credits
    from unittest.mock import MagicMock
    monkeypatch.setattr(credits, "_unsettled_jobs", set())
    monkeypatch.setattr(credits, "_reservation_jobs", {"hold": "job"})
    calls = []
    def handler(request):
        calls.append(request)
        if failure == "cancel": raise asyncio.CancelledError()
        if failure == "server_error": return httpx.Response(503)
        if failure == "protocol": raise httpx.RemoteProtocolError("disconnected", request=request)
        if failure == "decoding": raise httpx.DecodingError("invalid encoding", request=request)
        raise httpx.ReadTimeout("lost response", request=request)
    _mock_transport(monkeypatch, handler)
    async def run():
        with ai_request_context(job_id="job"):
            try:
                await client._post_with_retry("http://gw/v1/images", headers={}, json={}, retry_ambiguous=False)
            except (client.AITransportError, asyncio.CancelledError):
                pass
    asyncio.run(run())
    db = MagicMock()
    credits.release_reservation(db, "hold")
    db.rpc.assert_not_called()
    assert calls and len(calls) == 1
    assert "job" in credits._unsettled_jobs
