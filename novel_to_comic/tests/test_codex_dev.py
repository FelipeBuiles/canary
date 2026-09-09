"""Process authority and shared client lifecycle regressions; no live SDK calls."""
import asyncio
import importlib.util
import json
import sys
from pathlib import Path
from types import MappingProxyType, SimpleNamespace

import pytest

from novel_to_comic import codex_dev
from novel_to_comic.ai import client
from novel_to_comic.ai.context import ai_request_context
from novel_to_comic.config import Config


def _isolated_settings(monkeypatch, **settings):
    for key in codex_dev._KEYS:
        monkeypatch.delenv(key, raising=False)
    for key, value in settings.items():
        monkeypatch.setenv(key, value)
    name = "_test_codex_process_snapshot"
    spec = importlib.util.spec_from_file_location(name, Path(codex_dev.__file__))
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, module)
    spec.loader.exec_module(module)
    return module


def test_original_process_snapshot_cannot_be_enabled_by_dotenv(monkeypatch):
    routes = _isolated_settings(monkeypatch)
    monkeypatch.setenv("CANARY_CODEX_DEV_ENABLED", "1")
    monkeypatch.setenv("CANARY_ENV", "development")
    monkeypatch.setenv("CANARY_CODEX_DEV_TEXT_ROUTES", '{"plan-balanced":"gpt-5.6-terra"}')
    assert routes.route_for("text", "plan-balanced") is None
    with pytest.raises(routes.CodexRoutingError):
        routes.route_for("text", "codex-dev/gpt-5.6-terra")


@pytest.mark.parametrize("veto", [{"CANARY_ENV": "production"}, {"FLY_APP_NAME": "canary"}])
def test_hosted_activation_is_rejected_even_after_environment_changes(monkeypatch, veto):
    routes = _isolated_settings(monkeypatch, **{
        "CANARY_CODEX_DEV_ENABLED": "1", "CANARY_ENV": "development",
        "CANARY_CODEX_DEV_TEXT_ROUTES": '{"plan-balanced":"gpt-5.6-terra"}', **veto,
    })
    monkeypatch.setenv("CANARY_ENV", "development")
    monkeypatch.delenv("FLY_APP_NAME", raising=False)
    with pytest.raises(routes.CodexRoutingError):
        routes.route_for("text", "plan-balanced")


def test_classification_separates_complete_page_from_mixed_jobs_and_escalation(monkeypatch):
    routes = _isolated_settings(
        monkeypatch, CANARY_CODEX_DEV_ENABLED="1", CANARY_ENV="development",
        CANARY_CODEX_DEV_TEXT_ROUTES=json.dumps({"adapt-balanced": "gpt-5.6-terra", "adapt-quality": "gpt-5.4"}),
        CANARY_CODEX_DEV_IMAGE_ROUTES='["image-balanced"]',
    )
    assert routes.classify_operations(()) == "api"
    assert routes.classify_operations((("text", "adapt-balanced"),)) == "codex_subscription"
    assert routes.classify_operations((("complete_page", "image-balanced"),)) == "codex_subscription"
    for operations in (
        (("text", "adapt-balanced"), ("text", "plan-balanced")),
        (("complete_page", "image-balanced"), ("text", "ocr-balanced")),
    ):
        with pytest.raises(routes.CodexRoutingError):
            routes.classify_operations(operations)
    with pytest.raises(routes.CodexRoutingError):
        routes.require_same_text_target("adapt-balanced", "adapt-quality")
    with pytest.raises(routes.CodexRoutingError):
        routes.validate_startup("0.0.0.0")
    with routes.funding_scope("api"):
        with pytest.raises(routes.CodexRoutingError):
            routes.assert_request_funding("text", "adapt-balanced")
    with pytest.raises(routes.CodexRoutingError):
        routes.assert_request_funding("text", "adapt-balanced", require_admission=True)


@pytest.fixture
def selected_client(monkeypatch):
    monkeypatch.setattr(codex_dev, "_PROCESS", MappingProxyType({
        **codex_dev._PROCESS, "CANARY_CODEX_DEV_ENABLED": "1", "CANARY_ENV": "development",
        "ENV": None, "FLY_APP_NAME": None, "FLY_MACHINE_ID": None,
        "RENDER": None, "RAILWAY_ENVIRONMENT": None, "K_SERVICE": None, "VERCEL": None,
    }))
    monkeypatch.setattr(codex_dev, "_TEXT", {"plan-balanced": "gpt-5.6-terra"})
    monkeypatch.setattr(codex_dev, "_SETTINGS_ERROR", None)
    events = []
    monkeypatch.setattr(client, "_insert_event", lambda **kw: events.append(("insert", kw)))
    monkeypatch.setattr(client, "_finalize_event", lambda **kw: events.append(("finalize", kw)))
    def forbidden(*args, **kwargs):
        pytest.fail("selected Codex call reached API transport or pricing")
    monkeypatch.setattr(client, "_base_url", forbidden)
    monkeypatch.setattr(client, "estimate_text_cost", forbidden)
    monkeypatch.setattr(client, "estimate_text_usage", forbidden)
    return events


def _runtime(monkeypatch, run):
    monkeypatch.setitem(sys.modules, "novel_to_comic.ai.codex_runtime", SimpleNamespace(run_text=run))


def test_selected_json_sink_precedes_parse_and_preserves_vision(monkeypatch, selected_client):
    calls = []
    async def run(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(text="broken JSON", model=kwargs["model"], input_tokens=8, output_tokens=2, metadata={})
    _runtime(monkeypatch, run)
    retained = []
    with pytest.raises(ValueError):
        asyncio.run(client.generate_structured_object(
            config=Config(), model="plan-balanced", system_prompt="Read JSON", user_content="Read",
            image_attachments=((b"pixels", "image/png"),), json_schema={"type": "object"},
            response_sink=retained.append, retry_invalid_json=False,
        ))
    assert len(calls) == 1
    assert calls[0]["image_attachments"] == ((b"pixels", "image/png"),)
    assert retained[0].value == "broken JSON"
    assert retained[0].usage.funding == "codex_subscription"
    assert retained[0].usage.cost_usd is None
    assert retained[0].usage.provider_model == "gpt-5.6-terra"
    assert selected_client[-1][1]["status"] == "succeeded"


@pytest.mark.parametrize("cancel", [False, True])
def test_runtime_failure_and_cancel_retain_subscription_evidence(monkeypatch, selected_client, cancel):
    error = asyncio.CancelledError() if cancel else RuntimeError("sanitized runtime failure")
    error.metadata = {"input_tokens": 9, "output_tokens": 1, "submitted": True}
    async def run(**kwargs):
        raise error
    _runtime(monkeypatch, run)
    with pytest.raises(type(error)):
        asyncio.run(client.generate_text(config=Config(), model="plan-balanced", system_prompt="s", user_content="u"))
    terminal = selected_client[-1][1]
    assert terminal["status"] == ("cancelled" if cancel else "failed")
    assert terminal["usage"].input_tokens == 9
    assert terminal["usage"].funding == "codex_subscription"
    assert terminal["estimated_cost_usd"] is None


def test_declared_job_and_mock_cannot_bypass_authority(monkeypatch, selected_client):
    async def run(**kwargs):
        pytest.fail("unadmitted call reached runtime")
    _runtime(monkeypatch, run)
    with ai_request_context(job_id="declared-job"):
        with pytest.raises(codex_dev.CodexRoutingError):
            asyncio.run(client.generate_text(config=Config(), model="plan-balanced", system_prompt="s", user_content="u"))
    with pytest.raises(codex_dev.CodexRoutingError):
        asyncio.run(client.generate_text(config=Config(mock_mode=True), model="plan-balanced", system_prompt="s", user_content="u"))
    assert selected_client == []


def test_selected_repairs_keep_exact_target_and_sink_failure_never_retries(monkeypatch, selected_client):
    calls = []
    replies = iter(["bad JSON", '{"ok": true}'])
    async def run(**kwargs):
        calls.append(kwargs["model"])
        return SimpleNamespace(text=next(replies), model=kwargs["model"], input_tokens=3, output_tokens=2, metadata={})
    _runtime(monkeypatch, run)
    result = asyncio.run(client.generate_structured_object(
        config=Config(), model="plan-balanced", system_prompt="JSON", user_content="u",
    ))
    assert result.value == {"ok": True}
    assert calls == ["gpt-5.6-terra", "gpt-5.6-terra"]
    assert result.additional_usage[0].funding == "codex_subscription"
    replies = iter(['{"ok": true}'])
    calls.clear()
    def sink(_response):
        raise OSError("response storage failed")
    with pytest.raises(OSError):
        asyncio.run(client.generate_structured_object(
            config=Config(), model="plan-balanced", system_prompt="JSON", user_content="u",
            response_sink=sink,
        ))
    assert calls == ["gpt-5.6-terra"]


def test_wire_client_dispatches_by_frozen_provider_key(monkeypatch, tmp_path):
    from novel_to_comic.ai.providers import selector
    from novel_to_comic import provider_wire
    from novel_to_comic.usage import ApiResult, UsageRecord

    wire = SimpleNamespace(
        requested_alias="image-custom", configured_provider_model="custom-image",
        provider_key="custom-wire", execution_fingerprint="frozen",
        recompute_execution_fingerprint=lambda: "frozen",
        references=(), prompt_parts=("draw",),
    )
    seen = []
    raw = object()
    class Provider:
        def wire_request_params(self, request):
            assert request is wire
            return {"custom_control": "preserved"}

        async def generate_wire(self, *, wire, config, event_id, metadata):
            seen.append((wire, event_id, metadata))
            return raw

    def pick(alias, config, *, provider_key):
        assert (alias, provider_key) == ("image-custom", "custom-wire")
        return Provider()
    async def begin(**kwargs):
        assert kwargs["params"] == {"custom_control": "preserved"}
        return SimpleNamespace(event_id="event", metadata={"request": "unchanged"})
    output = tmp_path / "output.png"
    expected = ApiResult(value=output, usage=UsageRecord(provider="custom", model="image-custom", operation="image"))
    async def success(**kwargs):
        assert kwargs["raw"] is raw
        return expected
    monkeypatch.setattr(selector, "pick", pick)
    monkeypatch.setattr(provider_wire, "materialize_wire_references", lambda wire: ())
    monkeypatch.setattr(client, "begin_image_call", begin)
    monkeypatch.setattr(client, "finalise_image_success", success)
    result = asyncio.run(client.generate_wire_image(config=Config(), wire=wire, output_path=output))
    assert result is expected
    assert seen == [(wire, "event", {"request": "unchanged"})]


def test_wire_output_write_failure_finalizes_once_with_generated_usage(monkeypatch, tmp_path, selected_client):
    from novel_to_comic.ai import finalisation
    from novel_to_comic.ai.providers import selector
    from novel_to_comic.ai.providers.base import ProviderRawResult
    from novel_to_comic import provider_wire

    monkeypatch.setattr(codex_dev, "_IMAGES", frozenset({"image-quality"}))
    wire = SimpleNamespace(
        requested_alias="image-quality", configured_provider_model="gpt-image-2",
        provider_key="codex-dev", execution_fingerprint="frozen",
        recompute_execution_fingerprint=lambda: "frozen",
        references=(), prompt_parts=("draw",),
    )
    class Provider:
        def wire_request_params(self, request):
            return {}

        async def generate_wire(self, **kwargs):
            return ProviderRawResult(
                image_bytes=b"generated image bytes",
                raw_response={"usage": {"prompt_tokens": 17, "completion_tokens": 23}},
            )

    def fail_write(*args):
        raise OSError("output disk is full")

    monkeypatch.setattr(selector, "pick", lambda *args, **kwargs: Provider())
    monkeypatch.setattr(provider_wire, "materialize_wire_references", lambda wire: ())
    monkeypatch.setattr(finalisation, "_write_image_outputs", fail_write)
    with pytest.raises(OSError, match="output disk is full"):
        asyncio.run(client.generate_wire_image(config=Config(), wire=wire, output_path=tmp_path / "image.png"))
    terminal = [event for name, event in selected_client if name == "finalize"]
    assert len(terminal) == 1
    assert terminal[0]["status"] == "failed"
    usage = terminal[0]["usage"]
    assert (usage.input_tokens, usage.output_tokens, usage.image_count) == (17, 23, 1)
    assert usage.funding == "codex_subscription"
    assert usage.cost_usd is None


def test_standalone_runtime_veto_allows_unconfigured_local_probe(monkeypatch):
    routes = _isolated_settings(monkeypatch)
    routes.validate_local_runtime()
    routes = _isolated_settings(monkeypatch, CANARY_ENV="production")
    with pytest.raises(routes.CodexRoutingError):
        routes.validate_local_runtime()
    routes = _isolated_settings(monkeypatch, FLY_MACHINE_ID="hosted-machine")
    with pytest.raises(routes.CodexRoutingError):
        routes.validate_local_runtime()
