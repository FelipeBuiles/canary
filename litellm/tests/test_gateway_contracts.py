"""Provider-free contracts against the installed gateway, not fallback stubs."""
from importlib import import_module, util
from importlib.metadata import version
from pathlib import Path
import sys

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def load_patch(name):
    spec = util.spec_from_file_location(name, ROOT / "litellm" / f"{name}.py")
    module = util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("buffered", [False, True])
def test_http_error_preserves_provider_response_without_request_body(buffered):
    from litellm.llms.custom_httpx.http_handler import MaskedHTTPStatusError

    body = b"private image bytes"
    request = httpx.Request("POST", "https://provider.invalid/images/edits",
                            content=body if buffered else iter([body]))
    response = httpx.Response(429, content=b'{"error":"quota"}', request=request)
    original = httpx.HTTPStatusError("quota", request=request, response=response)
    wrapped = MaskedHTTPStatusError(original, message="quota", text="quota")
    assert wrapped.response.status_code == 429
    assert wrapped.response.json() == {"error": "quota"}
    assert wrapped.request.content == b""
    assert wrapped.response.request is wrapped.request
    if not buffered:
        with pytest.raises(httpx.RequestNotRead):
            _ = request.content


def test_nonstreaming_anthropic_refusal_details_survive():
    from litellm.llms.anthropic.chat.transformation import AnthropicConfig

    details = {"type": "refusal", "reason": "fixture"}
    fields = AnthropicConfig()._build_provider_specific_fields(
        {"stop_details": details}, citations=None, thinking_blocks=None,
        web_search_results=None, tool_results=None, compaction_blocks=None,
        tool_calls=[],
    )
    assert fields["stop_details"] == details


def test_streaming_anthropic_refusal_details_survive():
    from litellm.llms.anthropic.chat.handler import ModelResponseIterator

    details = {"type": "refusal", "reason": "fixture"}
    iterator = ModelResponseIterator(iter(()), sync_stream=True)
    result = iterator.chunk_parser({
        "type": "message_delta",
        "delta": {"stop_reason": "refusal", "stop_sequence": None,
                  "stop_details": details},
        "usage": {"output_tokens": 1},
    })
    assert result.choices[0].delta.provider_specific_fields["stop_details"] == details


@pytest.mark.parametrize("kind", ["transformation", "handler"])
def test_anthropic_patch_is_present_idempotent_and_fails_closed(kind):
    module = import_module(f"litellm.llms.anthropic.chat.{kind}")
    source = Path(module.__file__).read_text()
    patch = load_patch("patch_anthropic_refusals")
    assert "# Canary: retain Anthropic refusal details." in source
    assert patch.patch_source(source, kind) == source
    with pytest.raises(RuntimeError):
        patch.patch_source("unreviewed upstream layout", kind)


def test_http_patch_is_present_idempotent_and_fails_closed():
    module = import_module("litellm.llms.custom_httpx.http_handler")
    source = Path(module.__file__).read_text()
    patch = load_patch("patch_http_errors")
    assert patch.MARKER in source
    assert patch.patch_source(source) == source
    with pytest.raises(RuntimeError):
        patch.patch_source("unreviewed upstream layout")


def test_real_gateway_and_only_supported_custom_handler_are_loaded():
    from litellm.llms.custom_llm import CustomLLM
    from litellm_handlers.fal_provider import FalQueueLLM
    import yaml

    assert version("litellm") == "1.101.0"
    assert issubclass(FalQueueLLM, CustomLLM)
    config = yaml.safe_load((ROOT / "litellm/config.yaml").read_text())
    assert {route["model_name"] for route in config["model_list"]} == {
        "gpt-6-sol", "gpt-6-luna", "claude-fable-5-1", "claude-opus-5-5",
        "mimo-v2.6-pro", "deepseek-v4.1-flash", "image-sunburst",
    }
    assert config["litellm_settings"]["custom_provider_map"] == [{
        "provider": "fal-queue",
        "custom_handler": "litellm_handlers.fal_provider.fal_queue_llm",
    }]


def test_together_deepseek_route_disables_thinking_and_keeps_json_schema(monkeypatch):
    import json
    import litellm
    import yaml

    route = next(
        item["litellm_params"]
        for item in yaml.safe_load((ROOT / "litellm/config.yaml").read_text())["model_list"]
        if item["model_name"] == "deepseek-v4.1-flash"
    )
    sent = []

    def send(self, request, **kwargs):
        sent.append((str(request.url), json.loads(request.content)))
        return httpx.Response(200, request=request, json={
            "id": "r", "object": "chat.completion", "created": 0,
            "model": "deepseek-ai/DeepSeek-V4.1-Flash",
            "choices": [{"index": 0, "finish_reason": "stop",
                         "message": {"role": "assistant", "content": '{"ok":true}'}}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        })

    monkeypatch.setattr(httpx.Client, "send", send)
    monkeypatch.setattr(litellm, "drop_params", True)
    schema = {"name": "x", "strict": True, "schema": {
        "type": "object", "properties": {"ok": {"type": "boolean"}},
        "required": ["ok"], "additionalProperties": False,
    }}
    litellm.completion(
        **{**route, "api_key": "test-key"},
        messages=[{"role": "user", "content": [
            {"type": "text", "text": "Read."},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}},
        ]}],
        temperature=0.2, max_tokens=128,
        response_format={"type": "json_schema", "json_schema": schema},
    )

    url, body = sent[-1]
    assert url == "https://api.together.ai/v1/chat/completions"
    assert body["model"] == "deepseek-ai/DeepSeek-V4.1-Flash"
    assert body["reasoning"] == {"enabled": False}
    assert body["max_tokens"] == 128
    assert body["response_format"] == {"type": "json_schema", "json_schema": schema}
    assert body["messages"][0]["content"][1]["type"] == "image_url"


def test_opus_5_5_route_keeps_client_effort_format_and_thinking_summaries(monkeypatch):
    """Thinking stays adaptive with visible summaries; effort rides in output_config.

    LiteLLM drops a route-level reasoning_effort when output_config is present,
    so the app sends effort beside the JSON format and the gateway must keep both.
    """
    import json
    import litellm
    import yaml

    route = next(
        item["litellm_params"]
        for item in yaml.safe_load((ROOT / "litellm/config.yaml").read_text())["model_list"]
        if item["model_name"] == "claude-opus-5-5"
    )
    sent = []

    def send(self, request, **kwargs):
        sent.append((str(request.url), json.loads(request.content)))
        return httpx.Response(200, request=request, json={
            "id": "m", "type": "message", "role": "assistant", "model": "claude-opus-5-5",
            "content": [{"type": "text", "text": '{"ok":true}'}],
            "stop_reason": "end_turn", "usage": {"input_tokens": 1, "output_tokens": 1},
        })

    monkeypatch.setattr(httpx.Client, "send", send)
    monkeypatch.setattr(litellm, "drop_params", True)
    schema = {"type": "object", "properties": {"ok": {"type": "boolean"}},
              "required": ["ok"], "additionalProperties": False}
    litellm.completion(
        **{**route, "api_key": "test-key"},
        messages=[{"role": "system", "content": "s"}, {"role": "user", "content": "u"}],
        max_completion_tokens=4096,
        output_config={"effort": "high", "format": {"type": "json_schema", "schema": schema}},
    )

    url, body = sent[-1]
    assert url.startswith("https://api.anthropic.com/v1/messages")
    assert body["model"] == "claude-opus-5-5"
    assert body["thinking"] == {"type": "adaptive", "display": "summarized"}
    assert body["output_config"] == {
        "effort": "high", "format": {"type": "json_schema", "schema": schema},
    }
    assert body["max_tokens"] == 4096
    # Opus 5.5 rejects sampling controls, prefill and forced tool choice.
    assert "temperature" not in body
    assert "tool_choice" not in body
    assert body["messages"][-1]["role"] == "user"
