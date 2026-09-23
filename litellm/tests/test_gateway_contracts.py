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
        "gpt-6-sol", "gpt-6-luna", "claude-fable-5-1", "claude-opus-5",
        "mimo-v2.6-pro", "image-sunburst",
    }
    assert config["litellm_settings"]["custom_provider_map"] == [{
        "provider": "fal-queue",
        "custom_handler": "litellm_handlers.fal_provider.fal_queue_llm",
    }]
