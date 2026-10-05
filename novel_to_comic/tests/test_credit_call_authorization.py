"""Provider submissions require a durable, funded call guarantee."""

import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
import httpx
from fastapi import HTTPException

from novel_to_comic.ai import client
from novel_to_comic.ai.context import ai_request_context
from novel_to_comic.config import Config
from novel_to_comic.server import credits
from novel_to_comic.usage import UsageRecord


class _FakeDB:
    def __init__(self, authorized: bool):
        self.authorized = authorized
        self.calls = []

    def rpc(self, name, params):
        self.calls.append((name, params))
        return SimpleNamespace(execute=lambda: SimpleNamespace(data=self.authorized))


def test_call_authorization_requires_a_job_and_known_price():
    db = _FakeDB(True)
    with pytest.raises(RuntimeError, match="no credit reservation job"):
        credits.authorize_model_call(
            db, user_id="user", job_id=None, call_id="call", estimated_cost_usd=1,
        )
    with pytest.raises(RuntimeError, match="no usable price estimate"):
        credits.authorize_model_call(
            db, user_id="user", job_id="job", call_id="call", estimated_cost_usd=0,
        )
    assert db.calls == []


def test_only_api_stages_need_a_minimum_hold(monkeypatch, tmp_path):
    monkeypatch.setattr(credits, "mock_mode_active", lambda _config: False)
    monkeypatch.setattr(credits, "stage_operations", lambda _config, stage: () if stage == "finish" else (("text", "model"),))
    monkeypatch.setattr(credits, "estimate_stage_provider_cost_usd", lambda *_args: 0)
    assert credits.estimate_stage_credit_reservation(Config(), tmp_path, None, "finish") == 0
    assert credits.estimate_stage_credit_reservation(Config(), tmp_path, None, "adapt") == 1


def test_call_authorization_uses_atomic_database_decision():
    db = _FakeDB(False)
    with pytest.raises(HTTPException) as error:
        credits.authorize_model_call(
            db, user_id="user", job_id="job", call_id="call", estimated_cost_usd=0.02,
        )
    assert error.value.status_code == 402
    assert db.calls[0][0] == "authorize_model_call_credits"
    assert db.calls[0][1]["p_amount_credits"] >= 4


def test_denied_authorization_never_reaches_text_provider(monkeypatch):
    monkeypatch.setenv("CANARY_AI_STREAM_TEXT", "0")
    monkeypatch.setattr(client, "_insert_event_async", AsyncMock())
    monkeypatch.setattr(client, "_finalize_event_shielded", AsyncMock())
    submit = AsyncMock()
    monkeypatch.setattr(client._http, "post", submit)
    monkeypatch.setattr("novel_to_comic.server.db.get_db", lambda: _FakeDB(False))

    with ai_request_context(user_id="00000000-0000-0000-0000-000000000001",
                            job_id="00000000-0000-0000-0000-000000000002"):
        with pytest.raises(HTTPException) as error:
            asyncio.run(client.generate_text(
                config=Config(), model="gpt-5.6-terra",
                system_prompt="Summarize", user_content="A short story.",
            ))

    assert error.value.status_code == 402
    submit.assert_not_awaited()


def test_denied_authorization_never_reaches_image_provider(monkeypatch, tmp_path):
    from novel_to_comic.ai.providers import selector
    from novel_to_comic import provider_wire

    submit = AsyncMock()
    provider = SimpleNamespace(wire_request_params=lambda _wire: {}, generate_wire=submit)
    monkeypatch.setattr(selector, "pick", lambda *args, **kwargs: provider)
    monkeypatch.setattr(provider_wire, "materialize_wire_references", lambda _wire: ())
    monkeypatch.setattr(client, "begin_image_call", AsyncMock(return_value=SimpleNamespace(
        event_id="00000000-0000-0000-0000-000000000003",
        metadata={"funding": "api"}, estimated_cost_usd=0.02,
    )))
    monkeypatch.setattr(client, "finalise_image_failure", AsyncMock())
    monkeypatch.setattr("novel_to_comic.server.db.get_db", lambda: _FakeDB(False))
    wire = SimpleNamespace(
        schema_version=provider_wire.PROVIDER_WIRE_SCHEMA_VERSION,
        execution_fingerprint="frozen",
        recompute_execution_fingerprint=lambda: "frozen",
        references=(), requested_alias="image-sunburst",
        configured_provider_model="image-sunburst", provider_key="litellm",
        prompt_parts=("draw",),
    )

    with ai_request_context(user_id="00000000-0000-0000-0000-000000000001",
                            job_id="00000000-0000-0000-0000-000000000002"):
        with pytest.raises(HTTPException) as error:
            asyncio.run(client.generate_wire_image(
                config=Config(), wire=wire, output_path=Path(tmp_path / "image.png"),
            ))

    assert error.value.status_code == 402
    submit.assert_not_awaited()


def test_paid_stream_timeout_is_not_resubmitted(monkeypatch):
    submissions = AsyncMock(side_effect=httpx.ReadTimeout("response stalled"))
    monkeypatch.setattr(client, "_read_chat_stream", submissions)
    retained = []
    monkeypatch.setattr(credits, "retain_ambiguous_job", retained.append)

    with ai_request_context(job_id="00000000-0000-0000-0000-000000000002"):
        with pytest.raises(client.AITransportError, match="outcome is unknown"):
            asyncio.run(client._stream_with_retry(
                "http://gateway/v1/chat/completions", headers={}, payload={},
                retry_ambiguous=False,
            ))

    assert submissions.await_count == 1
    assert retained == ["00000000-0000-0000-0000-000000000002"]


def test_paid_provider_error_without_usage_retains_hold(monkeypatch):
    monkeypatch.setenv("CANARY_AI_STREAM_TEXT", "0")
    monkeypatch.setattr(client, "_insert_event_async", AsyncMock())
    monkeypatch.setattr(client, "_finalize_event_shielded", AsyncMock())
    response = httpx.Response(
        200, json={"error": {"message": "request failed"}},
        request=httpx.Request("POST", "http://gateway/v1/chat/completions"),
    )
    monkeypatch.setattr(client._http, "post", AsyncMock(return_value=response))
    monkeypatch.setattr("novel_to_comic.server.db.get_db", lambda: _FakeDB(True))
    retained = []
    monkeypatch.setattr(credits, "retain_ambiguous_job", retained.append)

    with ai_request_context(user_id="00000000-0000-0000-0000-000000000001",
                            job_id="00000000-0000-0000-0000-000000000002"):
        with pytest.raises(client.AITransportError, match="Provider text response failed"):
            asyncio.run(client.generate_text(
                config=Config(), model="gpt-5.6-terra",
                system_prompt="Summarize", user_content="A short story.",
            ))

    assert retained == ["00000000-0000-0000-0000-000000000002"]


def test_usage_settles_even_if_optional_event_update_fails(monkeypatch):
    class _UnavailableEvents:
        def table(self, _name):
            raise RuntimeError("usage telemetry unavailable")

    monkeypatch.setattr("novel_to_comic.server.db.get_db", lambda: _UnavailableEvents())
    settle = Mock()
    monkeypatch.setattr(client, "_settle_event_usage", settle)
    usage = UsageRecord(
        call_id="call", provider="openai", model="gpt-5.6-terra",
        operation="text", input_tokens=10, cost_usd=0.01,
        cost_source="provider_reported_cost",
    )

    with ai_request_context(user_id="00000000-0000-0000-0000-000000000001"):
        client._finalize_event(
            event_id="call", status="succeeded", feature="test.billing",
            model_alias="gpt-5.6-terra", latency_ms=1, usage=usage,
        )

    settle.assert_called_once_with(usage, feature="test.billing", status="succeeded")
