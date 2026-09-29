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
    from litellm_handlers.openai_image_stream import OpenAIImageStreamLLM
    import yaml

    assert version("litellm") == "1.101.0"
    assert issubclass(FalQueueLLM, CustomLLM)
    assert issubclass(OpenAIImageStreamLLM, CustomLLM)
    config = yaml.safe_load((ROOT / "litellm/config.yaml").read_text())
    assert {route["model_name"] for route in config["model_list"]} == {
        "gpt-6.1-sol", "gpt-6-sol", "gpt-6-luna", "claude-opus-5-5",
        "claude-sonnet-5-5", "mimo-v2.6-pro", "deepseek-v4.1-flash", "image-sunburst",
        "image-sunburst-openai",
    }
    assert config["litellm_settings"]["custom_provider_map"] == [{
        "provider": "fal-queue",
        "custom_handler": "litellm_handlers.fal_provider.fal_queue_llm",
    }, {
        "provider": "openai-stream",
        "custom_handler": "litellm_handlers.openai_image_stream.openai_image_stream_llm",
    }]
    for dockerfile in ("Dockerfile", "litellm/Dockerfile"):
        assert "litellm_handlers/openai_image_stream.py" in (ROOT / dockerfile).read_text()


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
    import litellm
    import yaml

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
    import litellm
    from litellm.utils import custom_llm_setup
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
        if "anthropic" in str(request.url):
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
    router = litellm.Router(model_list=[{
        **route, "litellm_params": {**route["litellm_params"], "api_key": "test-key"},
    }])
    response = router.completion(model=model, **payload)

    body = sent[-1]
    if wire.claude_native_json:
        assert body["output_config"]["effort"] == wire.effort == "low"
    if "reasoning_effort" in route["litellm_params"]:
        assert body["reasoning_effort"] == route["litellm_params"]["reasoning_effort"]
    for key, value in route["litellm_params"].get("extra_body", {}).items():
        assert body[key] == value
    price = _app_price(model)
    expected = 1000 * price["input_cost_per_token"] + 1000 * price["output_cost_per_token"]
    assert response._hidden_params["response_cost"] == pytest.approx(expected)


@pytest.mark.parametrize("edit", [False, True])
def test_openai_stream_route_keeps_manifest_usage_and_reports_no_gateway_cost(monkeypatch, edit):
    """The Draw page transport's exact fields through the Router, as the proxy runs them."""
    import asyncio
    import base64
    import io
    import json
    import litellm
    from litellm.utils import custom_llm_setup
    from litellm_handlers import openai_image_stream

    png = base64.b64encode(b"\x89PNGfixture").decode()
    seen = []

    def respond(request):
        seen.append(request)
        event = {"type": "image_edit.completed" if edit else "image_generation.completed", "b64_json": png,
                 "usage": {"input_tokens": 3200, "output_tokens": 343, "total_tokens": 3543,
                           "input_tokens_details": {"image_tokens": 3000, "text_tokens": 200}}}
        return httpx.Response(200, headers={"content-type": "text/event-stream", "x-request-id": "req_9"},
                              content=f"data: {json.dumps(event)}\n\n".encode())

    real = httpx.AsyncClient
    monkeypatch.setattr(openai_image_stream.httpx, "AsyncClient",
                        lambda **kwargs: real(transport=httpx.MockTransport(respond), **kwargs))
    monkeypatch.setattr(litellm, "model_cost", _bundled_cost_map())
    monkeypatch.setattr(litellm, "drop_params", _gateway_config()["litellm_settings"]["drop_params"])
    monkeypatch.setattr(litellm, "custom_provider_map", [
        {"provider": "openai-stream", "custom_handler": openai_image_stream.openai_image_stream_llm},
    ])
    custom_llm_setup()
    route = next(item for item in _gateway_config()["model_list"] if item["model_name"] == "image-sunburst-openai")
    router = litellm.Router(model_list=[{**route, "litellm_params": {**route["litellm_params"], "api_key": "sk-test"}}])
    fields = {
        "prompt": "p", "size": "1024x1536", "n": 1, "quality": "medium", "output_format": "png",
        "canary_wire_request": json.dumps({"width": 1024, "height": 1536, "controls": [
            ["quality", "medium"], ["output_format", "png"], ["n", 1]]}),
    }
    call = (router.aimage_edit(model="image-sunburst-openai", image=[io.BytesIO(b"\x89PNGref")], **fields)
            if edit else router.aimage_generation(model="image-sunburst-openai", **fields))
    response = asyncio.run(call)

    sent = seen[-1].content
    assert (b'name="size"\r\n\r\n1024x1536' in sent) if edit else (json.loads(sent)["size"] == "1024x1536")
    body = json.loads(response.model_dump_json())
    assert body["usage"]["output_tokens"] == 343
    assert body["usage"]["input_tokens_details"]["image_tokens"] == 3000
    assert body["provider_request_id"] == "req_9"
    # The proxy's x-litellm-response-cost comes from here; 0.0 would settle as free.
    assert response._hidden_params.get("response_cost") is None
