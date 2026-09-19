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


def test_real_gateway_and_google_sdk_are_loaded():
    from google.genai import types
    from litellm.llms.custom_llm import CustomLLM
    from litellm_handlers import vertex_multimodal as vertex
    from litellm_handlers.fal_provider import FalQueueLLM
    from litellm_handlers.openrouter_image import OpenRouterImageLLM

    assert version("litellm") == "1.101.0"
    assert version("google-genai") == "2.24.0"
    assert vertex.types is types
    for cls in (vertex.VertexMultimodalLLM, FalQueueLLM, OpenRouterImageLLM):
        assert issubclass(cls, CustomLLM)
    kwargs = vertex._image_config_kwargs(4 / 5, "medium")
    config = types.GenerateContentConfig(image_config=types.ImageConfig(**kwargs))
    assert config.image_config.aspect_ratio == "4:5"
    assert config.image_config.image_size == "2K"
    part = types.Part.from_bytes(data=b"fixture", mime_type="image/png")
    assert part.inline_data.data == b"fixture"


def test_google_usage_maps_into_real_litellm_usage_types():
    from google.genai import types
    from litellm.types.utils import ImageUsage
    from litellm_handlers.vertex_multimodal import _image_usage

    response = types.GenerateContentResponse(usage_metadata={
        "prompt_token_count": 12, "candidates_token_count": 20,
        "total_token_count": 32,
        "prompt_tokens_details": [
            {"modality": "TEXT", "token_count": 2},
            {"modality": "IMAGE", "token_count": 10},
        ],
    })
    usage = _image_usage(response, response_cost=0.125)
    assert isinstance(usage, ImageUsage)
    assert usage.input_tokens == 12
    assert usage.output_tokens == 20
    assert usage.total_tokens == 32
    assert usage.input_tokens_details.image_tokens == 10
    assert usage.input_tokens_details.text_tokens == 2
    assert usage.model_dump()["response_cost"] == 0.125


def test_google_errors_keep_retry_classification_without_making_requests():
    import litellm
    from litellm_handlers.vertex_multimodal import _translate_vertex_error

    class ProviderError(Exception):
        code = 429
        status = "RESOURCE_EXHAUSTED"
        message = "quota"

    translated = _translate_vertex_error(ProviderError(), "fixture-model")
    assert isinstance(translated, litellm.RateLimitError)
    assert translated.status_code == 429
    original = ValueError("invalid local input")
    assert _translate_vertex_error(original, "fixture-model") is original
