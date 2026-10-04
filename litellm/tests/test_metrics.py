"""Provider-free checks for the gateway's shared application metrics."""
import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
import re
import sys

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "litellm"))

import canary_metrics  # noqa: E402
from canary_metrics import PostHogMetricsMiddleware, configure_metrics  # noqa: E402
from canary_metrics_callback import metrics_callback  # noqa: E402


class FakeMetrics:
    def __init__(self):
        self.calls = []

    def count(self, name, value=1, unit=None, attributes=None):
        self.calls.append(("count", name, value, attributes))

    def gauge(self, name, value, unit=None, attributes=None):
        self.calls.append(("gauge", name, value, attributes))

    def histogram(self, name, value, unit=None, attributes=None):
        self.calls.append(("histogram", name, value, unit, attributes))


class FakeClient:
    def __init__(self):
        self.metrics = FakeMetrics()


class BrokenClient:
    class metrics:
        @staticmethod
        def count(*args, **kwargs):
            raise RuntimeError("metrics down")

        gauge = histogram = count


@pytest.fixture(autouse=True)
def reset_client():
    yield
    configure_metrics(canary_metrics._UNSET)


async def no_content(scope, receive, send):
    await send({"type": "http.response.start", "status": 204, "headers": []})
    await send({"type": "http.response.body", "body": b""})


def call(middleware):
    sent = []
    asyncio.run(middleware({"type": "http", "method": "POST", "path": "/unrecorded"}, lambda: None, _append(sent)))
    return sent


def _append(sent):
    async def send(message):
        sent.append(message)
    return send


def test_http_middleware_records_request_duration_and_active_gauge():
    client = FakeClient()
    configure_metrics(client)
    call(PostHogMetricsMiddleware(no_content))
    names = [call[1] for call in client.metrics.calls]
    assert names == [
        "http.server.active_requests",
        "http.server.requests",
        "http.server.duration",
        "http.server.active_requests",
    ]
    assert client.metrics.calls[1][3] == {"method": "POST", "status_class": "2xx"}
    assert client.metrics.calls[-1][2] == 0
    assert "/unrecorded" not in repr(client.metrics.calls)


def test_metric_failures_never_fail_gateway_requests():
    configure_metrics(BrokenClient())
    sent = call(PostHogMetricsMiddleware(no_content))
    assert sent[0]["status"] == 204
    assert canary_metrics._active_requests == 0


def test_missing_posthog_configuration_disables_metrics(monkeypatch):
    monkeypatch.delenv("POSTHOG_PROJECT_TOKEN", raising=False)
    monkeypatch.setenv("POSTHOG_HOST", "https://us.i.posthog.com")
    assert canary_metrics.metrics_client() is None
    assert call(PostHogMetricsMiddleware(no_content))[0]["status"] == 204


def test_gateway_uses_app_posthog_configuration(monkeypatch):
    monkeypatch.setenv("POSTHOG_PROJECT_TOKEN", "phc_test")
    monkeypatch.setenv("POSTHOG_HOST", "https://us.i.posthog.com")
    client = canary_metrics.metrics_client()
    try:
        assert client is not None and client.api_key == "phc_test"
    finally:
        client.shutdown()


def test_exception_reports_keep_code_locations_without_provider_text():
    event = canary_metrics._redact_exception({"event": "$exception", "properties": {
        "$exception_message": "private prompt",
        "$exception_list": [{"type": "BadRequestError", "value": "private prompt", "stacktrace": {"frames": [{
            "filename": "proxy_server.py", "lineno": 3, "function": "chat", "context_line": "private",
            "code_variables": {"prompt": "private"},
        }]}}],
    }})
    assert "private" not in repr(event)
    assert event["properties"]["$exception_list"][0]["stacktrace"]["frames"] == [
        {"filename": "proxy_server.py", "function": "chat", "lineno": 3},
    ]


def test_litellm_callback_records_provider_and_business_metrics():
    client = FakeClient()
    configure_metrics(client)
    started = datetime.now(timezone.utc)
    kwargs = {
        "call_type": "acompletion",
        "model": "gpt-6-sol",
        "litellm_params": {"custom_llm_provider": "openai"},
    }

    asyncio.run(
        metrics_callback.async_log_success_event(
            kwargs, object(), started, started + timedelta(milliseconds=125)
        )
    )

    assert [call[1] for call in client.metrics.calls] == [
        "llm.provider.calls",
        "llm.provider.duration",
        "gateway.completions",
    ]
    assert client.metrics.calls[0][3] == {
        "operation": "completion",
        "provider": "openai",
        "outcome": "success",
    }
    assert client.metrics.calls[1][2] == pytest.approx(125)
    assert client.metrics.calls[2][3] == {"operation": "completion", "model": "gpt-6-sol"}


def test_callback_models_match_gateway_routes():
    from canary_metrics_callback import _MODELS

    config = yaml.safe_load((ROOT / "litellm/config.yaml").read_text())
    assert _MODELS == {route["model_name"] for route in config["model_list"]}


@pytest.mark.parametrize("model", ["bedrock-claude-opus-5-5", "bedrock-claude-sonnet-5-5"])
@pytest.mark.parametrize("provider", ["bedrock", "bedrock_converse"])
def test_bedrock_metrics_retain_selected_model_and_provider(model, provider):
    client = FakeClient()
    configure_metrics(client)
    started = datetime.now(timezone.utc)
    asyncio.run(metrics_callback.async_log_success_event({
        "call_type": "acompletion", "model": model,
        "litellm_params": {"custom_llm_provider": provider},
    }, object(), started, started + timedelta(milliseconds=125)))
    assert client.metrics.calls[0][3]["provider"] == provider
    assert client.metrics.calls[2][3]["model"] == model


@pytest.mark.parametrize("dockerfile", ["Dockerfile", "litellm/Dockerfile"])
def test_every_gateway_image_ships_the_metrics_modules(dockerfile):
    # The patched proxy imports canary_metrics and config.yaml loads the
    # callback; an image without them cannot start the gateway.
    source = (ROOT / dockerfile).read_text()
    copies = " ".join(re.findall(r"^COPY (?:\\\n|[^\n])*", source, re.M))
    for module in ("litellm/canary_metrics.py", "litellm/canary_metrics_callback.py"):
        assert module in copies, f"{dockerfile} must copy {module}"
