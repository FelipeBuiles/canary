"""Claude Code subscription transport regressions; a fake CLI, no live calls."""
import asyncio
import base64
import io
import json
import sys
from types import MappingProxyType, SimpleNamespace

import pytest
from PIL import Image

from novel_to_comic import codex_dev
from novel_to_comic.ai import claude_runtime, client
from novel_to_comic.ai.errors import AIRefusalError
from novel_to_comic.config import Config
from novel_to_comic.text_models import text_wire

MODEL = "claude-opus-5-5"


@pytest.fixture(params=["claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5"])
def selected_claude_model(request, monkeypatch):
    # Model selection, catalog membership and tariffs vary by model. Generic
    # transport failures, redaction and timeouts need one representative model.
    monkeypatch.setattr(sys.modules[__name__], "MODEL", request.param)

_DEVELOPMENT = {
    "CANARY_ENV": "development", "ENV": None, "FLY_APP_NAME": None, "FLY_MACHINE_ID": None,
    "RENDER": None, "RAILWAY_ENVIRONMENT": None, "K_SERVICE": None, "VERCEL": None,
}


def _init(**overrides):
    return {"type": "system", "subtype": "init", "session_id": "s-1", "model": MODEL,
            "tools": [], "mcp_servers": [], "apiKeySource": "none",
            "permissionMode": "dontAsk", **overrides}


def _assistant(**message):
    return {"type": "assistant", "message": {"model": MODEL, "stop_reason": "end_turn", **message}}


def _result(**overrides):
    return {"type": "result", "subtype": "success", "is_error": False, "result": "answer",
            "duration_ms": 1200, "duration_api_ms": 1100, "num_turns": 1, "total_cost_usd": 0.0123,
            "usage": {"input_tokens": 1, "output_tokens": 1},
            "modelUsage": {MODEL: {"inputTokens": 100, "outputTokens": 40,
                                   "cacheReadInputTokens": 20, "cacheCreationInputTokens": 5,
                                   "costUSD": 0.0123}},
            **overrides}


_FAKE = '''#!{python}
import json, sys, time
from pathlib import Path
scenario = json.loads({scenario!r})
capture = Path({capture!r})
args = sys.argv[1:]
if args == ["--version"]:
    print("9.9.9 (Claude Code)"); sys.exit(0)
if args[:2] == ["auth", "status"]:
    print(json.dumps(scenario["auth"])); sys.exit(0)
import os
capture.write_text(json.dumps({{"argv": args, "stdin": sys.stdin.read(), "env": dict(os.environ)}}))
for event in scenario["events"]:
    if event == "sleep":
        time.sleep(30)
        continue
    print(json.dumps(event), flush=True)
sys.stderr.write(scenario.get("stderr", ""))
sys.exit(scenario.get("exit", 0))
'''


@pytest.fixture
def fake_cli(monkeypatch, tmp_path):
    """Install a scripted ``claude`` on the allowlisted PATH."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    capture = tmp_path / "capture.json"
    monkeypatch.setattr(codex_dev, "_PROCESS", MappingProxyType({
        **codex_dev._PROCESS, **_DEVELOPMENT, "PATH": str(bin_dir),
        "HOME": str(tmp_path), "USER": "tester",
    }))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-must-not-leak")

    def install(events, auth=None, **extra):
        scenario = {"events": events, "auth": auth or {
            "loggedIn": True, "authMethod": "claude.ai", "apiProvider": "firstParty",
            "subscriptionType": "max", "email": "someone@example.com"}, **extra}
        script = bin_dir / "claude"
        script.write_text(_FAKE.format(python=sys.executable, scenario=json.dumps(scenario),
                                       capture=str(capture)))
        script.chmod(0o755)
        return capture
    return install


def _run(**kwargs):
    kwargs = {"model": MODEL, "system_prompt": "System.", "user_content": "Write.",
              "effort": "high", "max_output_tokens": 32_768, **kwargs}
    return asyncio.run(claude_runtime.run_text(**kwargs))


@pytest.mark.usefixtures("selected_claude_model")
def test_isolated_invocation_carries_model_controls_and_subscription_usage(fake_cli):
    capture = fake_cli([_init(), _assistant(), _result()])
    result = _run()
    sent = json.loads(capture.read_text())
    argv = sent["argv"]
    for flag in ("--print", "--safe-mode", "--strict-mcp-config", "--no-session-persistence",
                 "--disable-slash-commands"):
        assert flag in argv
    assert argv[argv.index("--model") + 1] == MODEL
    assert argv[argv.index("--effort") + 1] == "high"
    assert argv[argv.index("--tools") + 1] == ""
    assert argv[argv.index("--setting-sources") + 1] == "local"
    assert argv[argv.index("--system-prompt") + 1] == "System."
    assert "--fallback-model" not in argv and "--json-schema" not in argv
    # The prompt travels on stdin, never argv, and no API credential is inherited.
    assert "Write." not in argv
    assert json.loads(sent["stdin"])["message"]["content"] == [{"type": "text", "text": "Write."}]
    assert not any(key.startswith("ANTHROPIC") for key in sent["env"])
    assert sent["env"]["CLAUDE_CODE_MAX_OUTPUT_TOKENS"] == "32768"
    assert "MAX_THINKING_TOKENS" not in sent["env"]
    assert result.text == "answer"
    assert (result.input_tokens, result.output_tokens) == (100, 40)
    assert (result.cache_read_input_tokens, result.cache_creation_input_tokens) == (20, 5)
    evidence = result.metadata
    assert evidence["funding"] == "claude_subscription"
    assert evidence["cli_reported_cost_usd"] == 0.0123
    assert evidence["auth"] == {"loggedIn": True, "authMethod": "claude.ai",
                                "apiProvider": "firstParty", "subscriptionType": "max"}
    assert evidence["submitted"] is True and evidence["indeterminate"] is False


@pytest.mark.parametrize("auth", [
    {"loggedIn": False, "authMethod": "none", "apiProvider": "firstParty"},
    {"loggedIn": True, "authMethod": "api_key", "apiProvider": "firstParty"},
    {"loggedIn": True, "authMethod": "claude.ai", "apiProvider": "bedrock"},
])
def test_non_subscription_login_fails_before_the_prompt_is_sent(fake_cli, auth):
    capture = fake_cli([_init(), _result()], auth=auth)
    with pytest.raises(claude_runtime.ClaudeRuntimeError) as caught:
        _run()
    assert caught.value.metadata.get("submitted") is not True
    assert not capture.exists()


@pytest.mark.parametrize("init,code", [
    ({"apiKeySource": "ANTHROPIC_API_KEY"}, "effective_api_key_conflict"),
    ({"model": "claude-opus-5"}, "effective_model_conflict"),
    ({"tools": ["Bash"]}, "effective_tool_isolation_failed"),
    ({"mcp_servers": [{"name": "x"}]}, "mcp_isolation_failed"),
])
def test_effective_session_conflicts_fail_closed(fake_cli, init, code):
    fake_cli([_init(**init), _assistant(), _result()])
    with pytest.raises(claude_runtime.ClaudeRuntimeError) as caught:
        _run()
    assert caught.value.code == code
    assert caught.value.metadata["process_group_terminated"] is True


def test_a_different_served_model_is_rejected(fake_cli):
    fake_cli([_init(), _assistant(model="claude-opus-5"), _result()])
    with pytest.raises(claude_runtime.ClaudeRuntimeError, match="effective_model_conflict"):
        _run()


def test_schema_uses_cli_structured_output_with_the_api_route_normalization(fake_cli):
    capture = fake_cli([
        _init(tools=["StructuredOutput"]), _assistant(),
        _result(result="", structured_output={"ok": True}),
    ])
    schema = {"type": "object", "properties": {"ok": {"type": "boolean"},
              "n": {"type": "integer", "minimum": 1}}, "required": ["ok"]}
    result = _run(json_schema=schema)
    argv = json.loads(capture.read_text())["argv"]
    from novel_to_comic.ai.anthropic_schema import anthropic_output_schema
    assert json.loads(argv[argv.index("--json-schema") + 1]) == anthropic_output_schema(schema)
    assert json.loads(result.text) == {"ok": True}
    assert result.metadata["structured_output_source"] == "structured_output"


def test_refusal_is_an_ai_refusal_with_usage_evidence(fake_cli):
    fake_cli([_init(), _assistant(stop_reason="refusal"), _result()])
    with pytest.raises(claude_runtime.ClaudeRuntimeRefusalError) as caught:
        _run()
    assert isinstance(caught.value, AIRefusalError)
    assert caught.value.metadata["usage"]["input_tokens"] == 100


def test_auxiliary_models_never_count_as_the_requested_model(fake_cli):
    usage = _result()["modelUsage"] | {"claude-haiku-4-5": {"inputTokens": 900, "outputTokens": 9}}
    fake_cli([_init(), _assistant(), _result(modelUsage=usage)])
    result = _run()
    assert (result.input_tokens, result.output_tokens) == (100, 40)
    assert result.metadata["auxiliary_model_usage"]["claude-haiku-4-5"]["inputTokens"] == 900


def test_failed_turn_keeps_a_sanitized_reason(fake_cli):
    fake_cli([_init(), _result(subtype="error_during_execution", is_error=True,
                               errors=["Usage limit reached. Authorization: Bearer abc.def.ghi"])])
    with pytest.raises(claude_runtime.ClaudeRuntimeError) as caught:
        _run()
    assert caught.value.code == "turn_not_completed"
    message = caught.value.metadata["provider_error"]["message"]
    assert "Usage limit reached" in message and "abc.def" not in message


def test_stored_account_without_a_usable_token_is_an_unsubmitted_auth_error(fake_cli):
    # Observed live: auth status reports a claude.ai login, the turn does not.
    notice = "Not logged in \u00b7 Please run /login"
    fake_cli([_init(), {"type": "assistant", "message": {
        "model": "<synthetic>", "content": [{"type": "text", "text": notice}]}},
        _result(is_error=True, result=notice, modelUsage={})])
    with pytest.raises(claude_runtime.ClaudeRuntimeError) as caught:
        _run()
    assert caught.value.code == "claude_subscription_auth_required"
    assert caught.value.metadata["submitted"] is False
    assert "claude auth login" in str(caught.value)


def test_timeout_terminates_without_resubmitting(fake_cli, monkeypatch):
    capture = fake_cli([_init(), "sleep"])
    monkeypatch.setattr(claude_runtime, "TEXT_TIMEOUT_SECONDS", 1)
    with pytest.raises(claude_runtime.ClaudeRuntimeError) as caught:
        _run()
    assert caught.value.code == "runtime_timeout"
    assert caught.value.metadata["submitted"] is True
    assert caught.value.metadata["indeterminate"] is True
    assert json.loads(capture.read_text())["argv"]


def test_image_attachments_travel_as_base64_blocks(fake_cli):
    capture = fake_cli([_init(), _assistant(), _result()])
    buffer = io.BytesIO()
    Image.new("RGB", (4, 4)).save(buffer, format="PNG")
    png = buffer.getvalue()
    _run(image_attachments=((png, "image/png"),))
    content = json.loads(json.loads(capture.read_text())["stdin"])["message"]["content"]
    assert content[1] == {"type": "image", "source": {
        "type": "base64", "media_type": "image/png", "data": base64.b64encode(png).decode()}}


def test_invalid_controls_are_rejected_before_any_process(fake_cli):
    capture = fake_cli([_init(), _result()])
    with pytest.raises(claude_runtime.ClaudeRuntimeError, match="invalid_effort"):
        _run(effort="none")
    with pytest.raises(claude_runtime.ClaudeRuntimeError, match="invalid_model_selector"):
        _run(model="gpt-6-sol")
    assert not capture.exists()


# Routing authority.

def _claude_process(monkeypatch, **settings):
    monkeypatch.setattr(codex_dev, "_PROCESS", MappingProxyType({
        **codex_dev._PROCESS, **_DEVELOPMENT, "CANARY_CLAUDE_DEV_ENABLED": "1",
        "CANARY_CLAUDE_DEV_MODELS": None, **settings,
    }))


@pytest.mark.usefixtures("selected_claude_model")
def test_explicit_claude_selector_routes_text_only(monkeypatch):
    _claude_process(monkeypatch)
    route = codex_dev.route_for("text", f"claude-dev/text/{MODEL}")
    assert (route.reasoning_model, route.runtime, route.funding) == (MODEL, "claude", "claude_subscription")
    for kind in ("image", "complete_page"):
        with pytest.raises(codex_dev.CodexRoutingError):
            codex_dev.route_for(kind, f"claude-dev/text/{MODEL}")
    with pytest.raises(codex_dev.CodexRoutingError):
        codex_dev.route_for("text", "claude-dev/text/claude-opus-5")
    assert codex_dev.route_for("text", MODEL) is None


@pytest.mark.parametrize("settings", [
    {"CANARY_CLAUDE_DEV_ENABLED": None},
    {"CANARY_ENV": "production"},
    {"FLY_APP_NAME": "canary"},
])
def test_claude_selector_requires_the_local_gate(monkeypatch, settings):
    _claude_process(monkeypatch, **settings)
    with pytest.raises(codex_dev.CodexRoutingError):
        codex_dev.route_for("text", f"claude-dev/text/{MODEL}")


@pytest.mark.usefixtures("selected_claude_model")
def test_classification_treats_claude_routes_as_zero_credit(monkeypatch):
    _claude_process(monkeypatch)
    selector = f"claude-dev/text/{MODEL}"
    assert codex_dev.classify_operations((("text", selector),)) == "claude_subscription"
    assert codex_dev.classify_operations((("text", selector), ("text", MODEL))) == "api"
    assert codex_dev.is_subscription("claude_subscription")
    from novel_to_comic.model_catalog import allowed_models
    assert selector in allowed_models("adapt")
    assert selector in allowed_models("visual_review")
    assert selector not in allowed_models("image")


# Client integration.

@pytest.fixture
def claude_client(monkeypatch):
    _claude_process(monkeypatch)
    events = []
    monkeypatch.setattr(client, "_insert_event", lambda **kw: events.append(("insert", kw)))
    monkeypatch.setattr(client, "_finalize_event", lambda **kw: events.append(("finalize", kw)))

    def forbidden(*args, **kwargs):
        pytest.fail("selected Claude Code call reached API transport or estimation")
    monkeypatch.setattr(client, "_base_url", forbidden)
    monkeypatch.setattr(client, "estimate_text_cost", forbidden)
    calls = []

    async def run(**kwargs):
        calls.append(kwargs)
        return claude_runtime.ClaudeTextResult(
            '{"ok": true}', 100, 40, 20, 5, MODEL, {"funding": "claude_subscription"})
    monkeypatch.setitem(sys.modules, "novel_to_comic.ai.claude_runtime",
                        SimpleNamespace(run_text=run))
    return SimpleNamespace(events=events, calls=calls)


@pytest.mark.usefixtures("selected_claude_model")
def test_client_sends_api_route_controls_and_records_comparable_usage(claude_client):
    result = asyncio.run(client.generate_structured_object(
        config=Config(), model=f"claude-dev/text/{MODEL}", system_prompt="JSON please",
        user_content="u", max_output_tokens=4_000, json_schema={"type": "object"},
    ))
    call = claude_client.calls[0]
    wire = text_wire(MODEL)
    assert call["model"] == MODEL
    # The API route's controls: explicit effort, and the answer budget plus
    # the thinking headroom Claude 5.5 bills against the same limit.
    assert wire.effort is not None and call["effort"] == wire.effort
    assert call["max_output_tokens"] == 4_000 + wire.thinking_headroom_tokens
    assert call["json_schema"] == {"type": "object"}
    assert result.value == {"ok": True}
    usage = result.usage
    assert (usage.provider, usage.funding, usage.cost_usd) == ("claude", "claude_subscription", None)
    assert (usage.input_tokens, usage.output_tokens, usage.cached_text_tokens) == (125, 40, 20)
    terminal = claude_client.events[-1][1]
    assert terminal["status"] == "succeeded"
    assert terminal["estimated_cost_usd"] is None
    assert terminal["metadata"]["api_equivalent_cost_usd"] == pytest.approx(125 * {"claude-opus-5-5": 4e-6, "claude-sonnet-5-5": 2e-6, "claude-haiku-5-5": 1e-7}[MODEL]
        + 40 * {"claude-opus-5-5": 20e-6, "claude-sonnet-5-5": 10e-6, "claude-haiku-5-5": 5e-7}[MODEL])


def test_subscription_usage_never_reaches_the_credit_ledger():
    from novel_to_comic.server.credits import usage_to_credit_debit
    from novel_to_comic.usage import UsageRecord

    usage = UsageRecord(provider="claude", model=f"claude-dev/text/{MODEL}", operation="text",
                        input_tokens=10_000, output_tokens=10_000, funding="claude_subscription")
    assert usage_to_credit_debit(usage) == (0, 0.0)


@pytest.mark.parametrize("budget,expected_limit", [(None, 32_768), (200_000, 128_000)])
def test_subscription_thinking_budget_defaults_and_caps(claude_client, budget, expected_limit):
    asyncio.run(client.generate_text(
        config=Config(), model=f"claude-dev/text/{MODEL}", system_prompt="s",
        user_content="u", max_output_tokens=budget,
    ))
    call = claude_client.calls[0]
    assert call["effort"] == "medium"
    assert call["max_output_tokens"] == expected_limit
