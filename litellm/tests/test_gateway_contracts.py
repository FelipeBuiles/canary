"""Provider-free contracts against the installed gateway, not fallback stubs."""
import sys
from importlib import import_module, util
from importlib.metadata import version
from pathlib import Path

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


def test_proxy_preview_patch_compiles_and_is_idempotent():
    proxy = Path(import_module("litellm").__file__).parent / "proxy/proxy_server.py"
    patch = load_patch("patch_http_errors")
    source = patch.patch_proxy_source(proxy.read_text())
    assert source.count(patch.PREVIEW_MIDDLEWARE_MARKER) == 1
    assert patch.patch_proxy_source(source) == source
    compile(source, str(proxy), "exec")
    with pytest.raises(RuntimeError):
        patch.patch_proxy_source("unreviewed upstream layout")


def test_stream_metadata_patch_is_present_idempotent_and_fails_closed():
    module = import_module("litellm.litellm_core_utils.model_response_utils")
    source = Path(module.__file__).read_text()
    patch = load_patch("patch_model_response")
    original = source
    for old, new in patch.PATCHES:
        assert source.count(new) == 1
        original = original.replace(new, old)
    assert patch.patch_source(original) == source
    assert patch.patch_source(source) == source
    compile(source, module.__file__, "exec")
    with pytest.raises(RuntimeError):
        patch.patch_source("unreviewed upstream layout")
    with pytest.raises(RuntimeError):
        patch.patch_source(original.replace(patch.CHOICE_OLD, patch.CHOICE_NEW))
    with pytest.raises(RuntimeError):
        patch.patch_source(original + patch.DELTA_OLD)


@pytest.mark.filterwarnings("error::pydantic.warnings.PydanticDeprecatedSince211")
@pytest.mark.parametrize("content,empty", [(None, True), ("", True), (" ", False), ("\n", False), ("text", False)])
def test_empty_stream_inspection_preserves_whitespace_without_instance_metadata(content, empty):
    from litellm.litellm_core_utils.model_response_utils import is_model_response_stream_empty
    from litellm.types.utils import Delta, ModelResponseStream, StreamingChoices

    chunk = ModelResponseStream(choices=[StreamingChoices(delta=Delta(content=content))])
    assert is_model_response_stream_empty(chunk) is empty


@pytest.mark.filterwarnings("error::pydantic.warnings.PydanticDeprecatedSince211")
@pytest.mark.parametrize("delta_fields,choice_fields,stream_fields", [
    ({"tool_calls": [{"index": 0, "id": "tool-1", "type": "function", "function": {"name": "lookup", "arguments": "{}"}}]}, {}, {}),
    ({"provider_specific_fields": {"reasoning": "fixture"}}, {}, {}),
    ({}, {"finish_reason": "stop"}, {}),
    ({}, {"provider_specific_fields": {"stop_details": "fixture"}}, {}),
    ({}, {}, {"usage": {"prompt_tokens": 1, "completion_tokens": 0, "total_tokens": 1}}),
])
def test_empty_stream_inspection_retains_provider_tool_finish_and_usage_fields(delta_fields, choice_fields, stream_fields):
    from litellm.litellm_core_utils.model_response_utils import is_model_response_stream_empty
    from litellm.types.utils import Delta, ModelResponseStream, StreamingChoices

    chunk = ModelResponseStream(
        choices=[StreamingChoices(delta=Delta(content=None, **delta_fields), **choice_fields)],
        **stream_fields,
    )
    assert not is_model_response_stream_empty(chunk)


def test_real_gateway_and_supported_custom_handlers_are_loaded():
    import yaml
    from litellm.llms.custom_llm import CustomLLM

    from litellm_handlers.fal_provider import FalQueueLLM
    from litellm_handlers.openai_image_stream import OpenAIImageStreamLLM
    from litellm_handlers.vertex_multimodal import VertexMultimodalLLM

    assert version("litellm") == "1.101.0"
    assert issubclass(FalQueueLLM, CustomLLM)
    assert issubclass(OpenAIImageStreamLLM, CustomLLM)
    assert issubclass(VertexMultimodalLLM, CustomLLM)
    config = yaml.safe_load((ROOT / "litellm/config.yaml").read_text())
    aliases = [route["model_name"] for route in config["model_list"]]
    assert len(aliases) == len(set(aliases)), "Each model alias must have exactly one route"
    assert {route["model_name"] for route in config["model_list"]} == {
        "gpt-6.1-sol", "gpt-6-sol", "gpt-6-luna", "claude-opus-5-5",
        "claude-sonnet-5-5", "mimo-v2.6-pro", "deepseek-v4.1-flash", "image-sunburst",
        "image-sunburst-openai", "image-flare", "image-nano-banana-2.1", "gemini-3.8-flash",
        "bedrock-claude-opus-5-5", "bedrock-claude-sonnet-5-5",
    }
    assert config["litellm_settings"]["custom_provider_map"] == [{
        "provider": "vertex-multimodal",
        "custom_handler": "litellm_handlers.vertex_multimodal.vertex_multimodal_llm",
    }, {
        "provider": "fal-queue",
        "custom_handler": "litellm_handlers.fal_provider.fal_queue_llm",
    }, {
        "provider": "openai-stream",
        "custom_handler": "litellm_handlers.openai_image_stream.openai_image_stream_llm",
    }]
    for dockerfile in ("Dockerfile", "litellm/Dockerfile"):
        source = (ROOT / dockerfile).read_text()
        for handler in ("fal_provider", "openai_image_stream", "vertex_multimodal"):
            assert f"litellm_handlers/{handler}.py" in source


def test_together_deepseek_route_disables_thinking_and_keeps_json_schema(monkeypatch):
    import json

    import yaml

    import litellm

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
    monkeypatch.setattr(litellm, "drop_params", _gateway_config()["litellm_settings"]["drop_params"])
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


@pytest.mark.parametrize("model", ["claude-opus-5-5", "claude-sonnet-5-5"])
def test_claude_5_5_route_keeps_client_effort_format_and_thinking_summaries(monkeypatch, model):
    """Thinking stays adaptive with visible summaries; effort rides in output_config.

    LiteLLM drops a route-level reasoning_effort when output_config is present,
    so the app sends effort beside the JSON format and the gateway must keep both.
    Runs on the bundled map with the configured drop_params, as in production.
    """
    import json

    import yaml

    import litellm

    route = next(
        item
        for item in yaml.safe_load((ROOT / "litellm/config.yaml").read_text())["model_list"]
        if item["model_name"] == model
    )
    sent = []

    def send(self, request, **kwargs):
        sent.append((str(request.url), json.loads(request.content)))
        return httpx.Response(200, request=request, json={
            "id": "m", "type": "message", "role": "assistant", "model": model,
            "content": [{"type": "text", "text": '{"ok":true}'}],
            "stop_reason": "end_turn", "usage": {"input_tokens": 1, "output_tokens": 1},
        })

    monkeypatch.setattr(httpx.Client, "send", send)
    monkeypatch.setattr(litellm, "drop_params", _gateway_config()["litellm_settings"]["drop_params"])
    schema = {"type": "object", "properties": {"ok": {"type": "boolean"}},
              "required": ["ok"], "additionalProperties": False}
    # Offline map only: the route's model_info, registered by the Router as the
    # proxy does, must carry the capabilities that keep effort on the wire.
    from importlib import resources
    bundled = resources.files("litellm").joinpath("model_prices_and_context_window_backup.json")
    monkeypatch.setattr(litellm, "model_cost", json.loads(bundled.read_text()))
    router = litellm.Router(model_list=[{
        **route, "litellm_params": {**route["litellm_params"], "api_key": "test-key"},
    }])
    router.completion(
        model=model,
        messages=[{"role": "system", "content": "s"}, {"role": "user", "content": "u"}],
        max_completion_tokens=4096,
        output_config={"effort": "low", "format": {"type": "json_schema", "schema": schema}},
    )

    url, body = sent[-1]
    assert url.startswith("https://api.anthropic.com/v1/messages")
    assert body["model"] == model
    assert body["thinking"] == {"type": "adaptive", "display": "summarized"}
    assert body["output_config"] == {
        "effort": "low", "format": {"type": "json_schema", "schema": schema},
    }
    assert body["max_tokens"] == 4096
    # Both reject non-default sampling controls, prefill and forced tool choice.
    assert "temperature" not in body
    assert "tool_choice" not in body
    assert body["messages"][-1]["role"] == "user"


@pytest.mark.parametrize("edit", [False, True])
def test_fal_billed_cost_and_request_id_survive_litellm_image_wrappers(monkeypatch, edit):
    import asyncio
    import io
    import json

    from litellm.utils import custom_llm_setup

    import litellm
    from litellm_handlers import fal_provider

    async def submit(*args, **kwargs):
        return {"request_id": "req-9", "status_url": "s", "response_url": "r"}

    async def done(*args, **kwargs):
        return None

    async def fetch(*args, **kwargs):
        return {"images": [{"url": "data:image/png;base64,aGVsbG8="}]}

    async def billing(*args, **kwargs):
        return 0.0593

    monkeypatch.setattr(fal_provider, "_submit", submit)
    monkeypatch.setattr(fal_provider, "_poll", done)
    monkeypatch.setattr(fal_provider, "_fetch_result", fetch)
    monkeypatch.setattr(fal_provider, "_billing_cost", billing)
    monkeypatch.setattr(litellm, "custom_provider_map", [
        {"provider": "fal-queue", "custom_handler": fal_provider.fal_queue_llm},
    ])
    custom_llm_setup()
    model = "fal-queue/openai/gpt-image-2.5/sunburst"
    call = (
        litellm.aimage_edit(model=model, prompt="p", image=[io.BytesIO(b"\x89PNG")], api_key="k")
        if edit else litellm.aimage_generation(model=model, prompt="p", api_key="k", size="1024x1536")
    )
    response = asyncio.run(call)

    # The proxy sets x-litellm-response-cost from this and returns the body.
    assert response._hidden_params["response_cost"] == 0.0593
    body = json.loads(response.model_dump_json())
    assert body["provider_request_id"] == "req-9"
    assert body["provider_cost_usd"] == 0.0593
    assert body["provider_cost_source"] == "fal_billing_event"


def _gateway_config():
    import yaml

    return yaml.safe_load((ROOT / "litellm/config.yaml").read_text())


def _bundled_cost_map():
    import json
    from importlib import resources

    return json.loads(resources.files("litellm").joinpath("model_prices_and_context_window_backup.json").read_text())


def _vertex_adc(monkeypatch):
    import google.auth
    from google.oauth2.credentials import Credentials

    credentials = Credentials(token="fixture-token")
    monkeypatch.setattr(credentials, "refresh", lambda request: None)
    monkeypatch.setattr(google.auth, "default", lambda **kwargs: (credentials, "fixture-project"))


def _vertex_response():
    return {
        "modelVersion": "gemini-3.8-flash",
        "candidates": [{"index": 0, "finishReason": "STOP", "content": {
            "role": "model", "parts": [{"text": '{"ok":true}'}],
        }}],
        "usageMetadata": {"promptTokenCount": 1000, "candidatesTokenCount": 800,
                          "cachedContentTokenCount": 250,
                          "thoughtsTokenCount": 200, "totalTokenCount": 2000},
    }


def _app_price(alias):
    """Base token rates the app settles with when the gateway reports no cost."""
    import json

    import yaml

    pricing = yaml.safe_load((ROOT / "novel_to_comic/src/novel_to_comic/litellm_pricing_overrides.yaml").read_text())
    cached = json.loads((ROOT / "novel_to_comic/src/novel_to_comic/litellm_model_prices.cached.json").read_text())
    key = pricing["aliases"][alias]
    for table in (pricing["model_overrides"], cached):
        for candidate in (key, key.split("/", 1)[1]):
            if candidate in table and "input_cost_per_token" in table[candidate]:
                return table[candidate]
    raise AssertionError(f"no app price for {alias}")


TEXT_ROUTES = [route["model_name"] for route in _gateway_config()["model_list"]
               if not route["model_name"].startswith("image-")]


def test_gateway_uses_bundled_map_and_rejects_unsupported_params():
    assert _gateway_config()["litellm_settings"]["drop_params"] is False
    for dockerfile in ("Dockerfile", "litellm/Dockerfile"):
        assert "ENV LITELLM_LOCAL_MODEL_COST_MAP=True" in (ROOT / dockerfile).read_text()


@pytest.mark.parametrize("model", TEXT_ROUTES)
def test_text_route_keeps_controls_and_app_price_on_the_bundled_map(monkeypatch, model):
    """Each route must work without the map LiteLLM would fetch at boot.

    An unmapped model prices at 0.0, which the app would settle as free, and
    loses capability-gated parameters such as effort.
    """
    import json

    import litellm

    sys.path.insert(0, str(ROOT / "novel_to_comic/src"))
    from novel_to_comic.text_models import text_wire

    route = next(item for item in _gateway_config()["model_list"] if item["model_name"] == model)
    wire = text_wire(model)
    # Providers answer with the upstream model name, which LiteLLM prices from.
    upstream = route["litellm_params"]["model"].split("/", 1)[1]
    sent = []

    def send(self, request, **kwargs):
        sent.append(json.loads(request.content))
        if "bedrock-runtime" in str(request.url):
            body = {"output": {"message": {"role": "assistant", "content": [{"text": '{"ok":true}'}]}},
                    "stopReason": "end_turn", "usage": {"inputTokens": 1000, "outputTokens": 1000,
                    "totalTokens": 2000}, "metrics": {"latencyMs": 1}}
        elif "aiplatform.googleapis.com" in str(request.url):
            body = _vertex_response()
        elif "anthropic" in str(request.url):
            body = {"id": "m", "type": "message", "role": "assistant", "model": upstream,
                    "content": [{"type": "text", "text": '{"ok":true}'}], "stop_reason": "end_turn",
                    "usage": {"input_tokens": 1000, "output_tokens": 1000}}
        else:
            body = {"id": "c", "object": "chat.completion", "created": 1, "model": upstream,
                    "choices": [{"index": 0, "finish_reason": "stop",
                                 "message": {"role": "assistant", "content": '{"ok":true}'}}],
                    "usage": {"prompt_tokens": 1000, "completion_tokens": 1000, "total_tokens": 2000}}
        return httpx.Response(200, request=request, json=body)

    monkeypatch.setattr(httpx.Client, "send", send)
    monkeypatch.setattr(litellm, "model_cost", _bundled_cost_map())
    monkeypatch.setattr(litellm, "drop_params", False)
    schema = {"type": "object", "properties": {"ok": {"type": "boolean"}},
              "required": ["ok"], "additionalProperties": False}
    # The app's request shape for this alias (see ai/client.py).
    payload = {"messages": [{"role": "system", "content": "s"}, {"role": "user", "content": "u"}],
               "metadata": {"feature": "contract"}, wire.token_limit_field: 4096}
    if wire.temperature:
        payload["temperature"] = 0.7
    if wire.claude_native_json:
        payload["output_config"] = {"effort": wire.effort, "format": {"type": "json_schema", "schema": schema}}
    else:
        payload["response_format"] = {"type": "json_schema",
                                      "json_schema": {"name": "contract", "strict": True, "schema": schema}}
        if wire.effort:
            payload["reasoning_effort"] = wire.effort
    if wire.provider_key == "vertex_ai":
        _vertex_adc(monkeypatch)
        params = {**route["litellm_params"], "vertex_project": "fixture-project", "vertex_location": "global"}
    elif wire.provider_key == "bedrock":
        params = {**route["litellm_params"], "api_key": "test-key", "aws_region_name": "us-east-1"}
    else:
        params = {**route["litellm_params"], "api_key": "test-key"}
    router = litellm.Router(model_list=[{**route, "litellm_params": params}])
    response = router.completion(model=model, **payload)

    body = sent[-1]
    if wire.provider_key == "bedrock":
        assert body["additionalModelRequestFields"]["output_config"]["effort"] == wire.effort == "medium"
        assert json.loads(body["outputConfig"]["textFormat"]["structure"]["jsonSchema"]["schema"]) == schema
    elif wire.claude_native_json:
        assert body["output_config"]["effort"] == wire.effort == "medium"
    if "reasoning_effort" in route["litellm_params"]:
        if wire.provider_key == "vertex_ai":
            assert body["generationConfig"]["thinkingConfig"]["thinkingLevel"] == "medium"
        else:
            assert body["reasoning_effort"] == route["litellm_params"]["reasoning_effort"]
    for key, value in route["litellm_params"].get("extra_body", {}).items():
        assert body[key] == value
    price = _app_price(model)
    expected = 1000 * price["input_cost_per_token"] + 1000 * price["output_cost_per_token"]
    if wire.provider_key == "vertex_ai":
        expected -= 250 * (price["input_cost_per_token"] - price["cache_read_input_token_cost"])
    assert response._hidden_params["response_cost"] == pytest.approx(expected)


@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("effort", ["low", "medium", "high"])
def test_vertex_gemini_route_preserves_project_schema_vision_reasoning_and_usage(monkeypatch, stream, effort):
    import asyncio
    import json

    import litellm

    route = next(item for item in _gateway_config()["model_list"] if item["model_name"] == "gemini-3.8-flash")
    assert route["litellm_params"]["model"] == "vertex_ai/gemini-3.8-flash"
    assert "api_key" not in route["litellm_params"]
    _vertex_adc(monkeypatch)
    monkeypatch.setattr(litellm, "model_cost", _bundled_cost_map())
    monkeypatch.setattr(litellm, "drop_params", False)
    sent = []

    def respond(request):
        sent.append(request)
        if stream:
            return httpx.Response(200, request=request, headers={"content-type": "text/event-stream"},
                                  content=f"data: {json.dumps(_vertex_response())}\n\n".encode())
        return httpx.Response(200, request=request, json=_vertex_response())

    def send(self, request, **kwargs):
        return respond(request)

    async def async_send(self, request, **kwargs):
        return respond(request)

    monkeypatch.setattr(httpx.Client, "send", send)
    monkeypatch.setattr(httpx.AsyncClient, "send", async_send)
    schema = {"type": "object", "properties": {"ok": {"type": "boolean"}},
              "required": ["ok"], "additionalProperties": False}
    router = litellm.Router(model_list=[{**route, "litellm_params": {
        **route["litellm_params"], "vertex_project": "credited-project", "vertex_location": "global",
    }}], num_retries=0)
    payload = {
        "model": "gemini-3.8-flash", "reasoning_effort": effort, "max_completion_tokens": 20480,
        "messages": [{"role": "system", "content": "Return JSON."}, {"role": "user", "content": [
            {"type": "text", "text": "Read the image."},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}},
        ]}],
        "response_format": {"type": "json_schema", "json_schema": {
            "name": "contract", "strict": True, "schema": schema,
        }},
    }
    if stream:
        async def collect():
            result = await router.acompletion(**payload, stream=True, stream_options={"include_usage": True})
            return [chunk async for chunk in result]
        chunks = asyncio.run(collect())
        assert ''.join(chunk.choices[0].delta.content or '' for chunk in chunks if chunk.choices) == '{"ok":true}'
        usage = next(chunk.usage for chunk in reversed(chunks) if chunk.usage is not None)
    else:
        result = router.completion(**payload)
        assert result.choices[0].message.content == '{"ok":true}'
        usage = result.usage
    assert len(sent) == 1
    request = sent[0]
    assert request.url.host == "aiplatform.googleapis.com"
    assert "/projects/credited-project/locations/global/publishers/google/models/gemini-3.8-flash:" in request.url.path
    assert request.headers["authorization"] == "Bearer fixture-token"
    body = json.loads(request.content)
    generation = body["generationConfig"]
    assert generation["thinkingConfig"] == {"thinkingLevel": effort, "includeThoughts": True}
    assert generation["max_output_tokens"] == 20480
    assert generation["response_mime_type"] == "application/json"
    assert generation.get("response_json_schema", generation.get("response_schema"))["properties"]["ok"]["type"].lower() == "boolean"
    assert body["system_instruction"]["parts"][0]["text"] == "Return JSON."
    assert body["contents"][0]["parts"][1]["inline_data"] == {"mime_type": "image/png", "data": "AAAA"}
    assert usage.prompt_tokens == 1000
    assert usage.prompt_tokens_details.cached_tokens == 250
    assert usage.completion_tokens == 1000
    assert usage.completion_tokens_details.reasoning_tokens == 200


@pytest.mark.parametrize("edit", [False, True])
@pytest.mark.parametrize("previews", [False, True])
@pytest.mark.parametrize("alias,model", [
    ("image-sunburst-openai", "gpt-image-2.5-sunburst"),
    ("image-flare", "gpt-image-2.5-flare"),
])
def test_openai_stream_route_keeps_manifest_usage_and_reports_no_gateway_cost(monkeypatch, edit, previews, alias, model):
    """The Draw page transport's exact fields through the Router, as the proxy runs them."""
    import asyncio
    import base64
    import io
    import json

    from litellm.utils import custom_llm_setup

    import litellm
    from litellm_handlers import openai_image_stream

    png = base64.b64encode(b"\x89PNGfixture").decode()
    seen = []

    def respond(request):
        seen.append(request)
        event = {"type": "image_edit.completed" if edit else "image_generation.completed", "b64_json": png,
                 "usage": {"input_tokens": 3200, "output_tokens": 343, "total_tokens": 3543,
                           "input_tokens_details": {"image_tokens": 3000, "text_tokens": 200}}}
        partial = {"type": "image_edit.partial_image" if edit else "image_generation.partial_image",
                   "partial_image_index": 0, "b64_json": png}
        return httpx.Response(200, headers={"content-type": "text/event-stream", "x-request-id": "req_9"},
                              content=f"data: {json.dumps(partial)}\n\ndata: {json.dumps(event)}\n\n".encode())

    real = httpx.AsyncClient
    monkeypatch.setattr(openai_image_stream.httpx, "AsyncClient",
                        lambda **kwargs: real(transport=httpx.MockTransport(respond), **kwargs))
    monkeypatch.setattr(litellm, "model_cost", _bundled_cost_map())
    monkeypatch.setattr(litellm, "drop_params", _gateway_config()["litellm_settings"]["drop_params"])
    monkeypatch.setattr(litellm, "custom_provider_map", [
        {"provider": "openai-stream", "custom_handler": openai_image_stream.openai_image_stream_llm},
    ])
    custom_llm_setup()
    route = next(item for item in _gateway_config()["model_list"] if item["model_name"] == alias)
    router = litellm.Router(model_list=[{**route, "litellm_params": {**route["litellm_params"], "api_key": "sk-test"}}])
    fields = {
        "prompt": "p", "size": "1024x1536", "n": 1, "quality": "medium", "output_format": "png",
        "canary_wire_request": json.dumps({"width": 1024, "height": 1536, "controls": [
            ["quality", "medium"], ["output_format", "png"], ["n", 1]]}),
    }
    call = (router.aimage_edit(model=alias, image=[io.BytesIO(b"\x89PNGref")], **fields)
            if edit else router.aimage_generation(model=alias, **fields))
    if previews:
        from litellm_handlers.image_previews import ImagePreviewMiddleware
        messages = []
        result = []

        async def route(scope, receive, send):
            result.append(await call)
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": result[0].model_dump_json().encode()})

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(message):
            messages.append(message)

        asyncio.run(ImagePreviewMiddleware(route)({"type": "http", "method": "POST",
            "path": "/v1/images/edits" if edit else "/v1/images/generations",
            "headers": [(b"x-canary-image-previews", b"3")]}, receive, send))
        assert any(b'"image_preview"' in message.get("body", b"") for message in messages)
        response = result[0]
    else:
        response = asyncio.run(call)

    sent = seen[-1].content
    count = 3 if previews else 0
    assert (f'name="partial_images"\r\n\r\n{count}'.encode() in sent) if edit else (json.loads(sent)["partial_images"] == count)
    assert (b'name="size"\r\n\r\n1024x1536' in sent) if edit else (json.loads(sent)["size"] == "1024x1536")
    assert (f'name="model"\r\n\r\n{model}'.encode() in sent) if edit else (json.loads(sent)["model"] == model)
    body = json.loads(response.model_dump_json())
    assert body["model"] == f"openai/{model}"
    assert body["usage"]["output_tokens"] == 343
    assert body["usage"]["input_tokens_details"]["image_tokens"] == 3000
    assert body["provider_request_id"] == "req_9"
    # The proxy's x-litellm-response-cost comes from here; 0.0 would settle as free.
    assert response._hidden_params.get("response_cost") is None


@pytest.mark.parametrize("model", ["mimo-v2.6-pro", "deepseek-v4.1-flash"])
@pytest.mark.parametrize("enabled", [False, True])
def test_open_model_request_overrides_gateway_reasoning_default(monkeypatch, model, enabled):
    import json

    import litellm
    route = next(item for item in _gateway_config()["model_list"] if item["model_name"] == model)
    sent = []
    def send(self, request, **kwargs):
        sent.append(json.loads(request.content))
        return httpx.Response(200, request=request, json={
            "id": "r", "object": "chat.completion", "created": 0, "model": model,
            "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": "answer"}}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        })
    monkeypatch.setattr(httpx.Client, "send", send)
    router = litellm.Router(model_list=[{**route, "litellm_params": {**route["litellm_params"], "api_key": "test-key"}}])
    payload = {"extra_body": {"reasoning": {"enabled": enabled}}}
    if model == "mimo-v2.6-pro":
        payload["extra_body"]["provider"] = {"require_parameters": True}
    router.completion(model=model, messages=[{"role": "user", "content": "Hello"}], max_tokens=32768, **payload)
    assert sent[-1]["reasoning"]["enabled"] is enabled
    if model == "mimo-v2.6-pro":
        assert sent[-1]["provider"]["require_parameters"] is True


@pytest.mark.parametrize("constrained", [True, False])
def test_gemini_vertex_route_uses_adc_schema_effort_and_pinned_price(monkeypatch, constrained):
    import json

    import litellm
    route = next(item for item in _gateway_config()["model_list"]
                 if item["model_name"] == "gemini-3.8-flash")
    assert "api_key" not in route["litellm_params"]
    _vertex_adc(monkeypatch)
    seen = []
    def send(self, request, **kwargs):
        seen.append(request)
        return httpx.Response(200, request=request, json={
            "candidates": [{"content": {"role": "model", "parts": [{"text": '{"a":"x"}'}]},
                            "finishReason": "STOP"}],
            "usageMetadata": {"promptTokenCount": 1000, "candidatesTokenCount": 100,
                              "thoughtsTokenCount": 50, "totalTokenCount": 1150},
        })
    monkeypatch.setattr(httpx.Client, "send", send)
    router = litellm.Router(model_list=[{**route, "litellm_params": {
        **route["litellm_params"], "vertex_project": "fixture-project", "vertex_location": "global",
    }}])
    schema = {"type": "object", "properties": {"a": {"type": "string"}},
              "required": ["a"], "additionalProperties": False}
    response = router.completion(
        model="gemini-3.8-flash", messages=[{"role": "user", "content": "Hello"}],
        reasoning_effort="medium", max_completion_tokens=32768,
        response_format=({"type": "json_schema", "json_schema": {"name": "x", "strict": True, "schema": schema}}
                         if constrained else {"type": "json_object"}),
    )
    request = seen[-1]
    assert request.url.host == "aiplatform.googleapis.com"
    assert "/projects/fixture-project/locations/global/" in request.url.path
    assert request.headers["authorization"] == "Bearer fixture-token"
    assert "x-goog-api-key" not in request.headers
    generation = json.loads(request.content)["generationConfig"]
    assert generation["max_output_tokens"] == 32768
    assert generation["response_mime_type"] == "application/json"
    if constrained:
        assert generation["response_json_schema"] == schema
    else:
        assert "response_json_schema" not in generation
        assert "response_schema" not in generation
    assert generation["thinkingConfig"] == {"thinkingLevel": "medium", "includeThoughts": True}
    # Thinking bills as output: 1000 * $0.75/M + 150 * $3.75/M.
    assert response._hidden_params["response_cost"] == pytest.approx(0.0013125)
