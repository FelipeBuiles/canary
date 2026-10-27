"""Runware text route: request forwarding and billed-usage normalization."""
import asyncio

import httpx
import pytest

from litellm_handlers import runware_text as rt
from novel_to_comic.ai.text_requests import build_text_request
from novel_to_comic.config import Config


def test_forwards_app_controls_but_not_litellm_internals():
    body = rt.request_body("google-gemini-4-argon", [{"role": "user", "content": "u"}], {
        "response_format": {"type": "json_object"}, "reasoning_effort": "low",
        "max_tokens": 4096, "max_completion_tokens": 4096, "stream": False, "max_retries": 0,
    })
    assert body == {"model": "google-gemini-4-argon", "messages": [{"role": "user", "content": "u"}],
                    "response_format": {"type": "json_object"}, "reasoning_effort": "low",
                    "max_completion_tokens": 4096}
    with pytest.raises(rt.CustomLLMError, match="do not stream"):
        rt.request_body("m", [], {"stream": True})


@pytest.mark.parametrize(("usage", "completion", "reasoning"), [
    # Gemini passthrough: thinking only appears in total_tokens.
    ({"prompt_tokens": 178, "completion_tokens": 1071, "total_tokens": 4265}, 4087, 3016),
    # xAI: reasoning reported, yet outside completion_tokens.
    ({"prompt_tokens": 217, "completion_tokens": 12, "total_tokens": 709,
      "completion_tokens_details": {"reasoning_tokens": 480}}, 492, 480),
    # DeepSeek: reasoning already inside completion_tokens.
    ({"prompt_tokens": 114, "completion_tokens": 172, "total_tokens": 286,
      "completion_tokens_details": {"reasoning_tokens": 124}}, 172, 124),
])
def test_tokens_outside_completion_settle_as_reasoning_output(usage, completion, reasoning):
    normalized = rt.normalized_usage(usage)
    assert normalized["completion_tokens"] == completion
    assert normalized["completion_tokens_details"]["reasoning_tokens"] == reasoning
    assert normalized["total_tokens"] == usage["prompt_tokens"] + completion


def test_response_drops_thought_signatures_and_names_the_route_model(monkeypatch):
    sent = []

    async def post(self, url, json, headers):
        sent.append((url, json, headers))
        return httpx.Response(200, request=httpx.Request("POST", url), json={
            "id": "c", "object": "chat.completion", "created": 1, "model": "google:gemini@4-argon",
            "choices": [{"index": 0, "finish_reason": "stop", "message": {
                "role": "assistant", "content": '{"ok": true}',
                "extra_content": {"google": {"thought_signature": "sig"}}}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 40},
        })

    monkeypatch.setattr(httpx.AsyncClient, "post", post)
    response = asyncio.run(rt.RunwareTextLLM().acompletion(
        "google-gemini-4-argon", [{"role": "user", "content": "u"}], rt.RUNWARE_CHAT_URL, {}, None,
        None, None, "key", None, {"reasoning_effort": "low"}))
    assert sent[0][2] == {"Authorization": "Bearer key"}
    assert response["model"] == "google-gemini-4-argon"
    assert "extra_content" not in response["choices"][0]["message"]
    assert response["usage"]["completion_tokens"] == 30


@pytest.mark.parametrize(("status", "error"), [(429, None), (None, httpx.ReadTimeout("t")),
                                               (None, httpx.ConnectError("c"))])
def test_failures_are_reported_once_with_their_status(monkeypatch, status, error):
    calls = []

    async def post(self, url, json, headers):
        calls.append(url)
        if error:
            raise error
        return httpx.Response(status, request=httpx.Request("POST", url),
                              json={"error": {"message": "Rate limit exceeded"}})

    monkeypatch.setattr(httpx.AsyncClient, "post", post)
    with pytest.raises(rt.CustomLLMError) as raised:
        asyncio.run(rt.RunwareTextLLM().acompletion(
            "m", [], rt.RUNWARE_CHAT_URL, {}, None, None, None, "key", None, {}))
    assert len(calls) == 1
    assert raised.value.status_code == (status or (503 if isinstance(error, httpx.ConnectError) else 504))


def test_argon_route_sends_effort_json_mode_and_stays_under_runware_output_limit():
    request = build_text_request(
        config=Config(), model="runware-gemini-4-argon", system_prompt="Rules.", user_content="Source.",
        temperature=.3, max_output_tokens=24_000, json_mode=True, feature="plan.detail",
        json_schema={"type": "object", "properties": {"v": {"type": "string"}}, "required": ["v"]},
        metadata={},
    )
    assert request.payload["reasoning_effort"] == request.effort
    assert request.payload["response_format"] == {"type": "json_object"}
    assert request.payload["max_completion_tokens"] == 32_768
    assert "thinkingConfig" not in request.payload and not request.streaming
