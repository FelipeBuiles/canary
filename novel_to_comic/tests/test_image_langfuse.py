from __future__ import annotations

import asyncio
import datetime
from unittest.mock import MagicMock

import pytest

from novel_to_comic.ai import client
from novel_to_comic.config import Config
from novel_to_comic.usage import UsageRecord


@pytest.mark.parametrize(
    ("model_alias", "provider", "provider_model"),
    [
        ("image-balanced", "gemini", "vertex_ai/gemini-3-pro-image"),
        ("image-quality", "openai", "openai/gpt-image-2"),
    ],
)
def test_image_langfuse_is_independent_of_usage_database(
    monkeypatch: pytest.MonkeyPatch,
    model_alias: str,
    provider: str,
    provider_model: str,
) -> None:
    def fail_db():
        raise RuntimeError("usage database unavailable")

    log_generation = MagicMock()
    monkeypatch.setattr("novel_to_comic.server.db.get_db", fail_db)
    monkeypatch.setattr(client, "_log_langfuse_generation", log_generation)

    client._finalize_event(
        event_id="image-event",
        status="succeeded",
        feature="test.image",
        model_alias=model_alias,
        latency_ms=25,
        usage=UsageRecord(
            call_id="image-event",
            provider=provider,
            model=model_alias,
            provider_model=provider_model,
            operation="image",
            image_count=1,
        ),
        response_data={"id": "provider-response", "model": provider_model},
        config=Config(),
        operation="image",
        metadata={
            "trace_id": "request-trace",
            "trace_name": "test.image",
            "generation_name": model_alias,
            "metadata": {},
        },
        langfuse_input={"prompt": "draw this"},
        langfuse_output={"actual_provider_model": provider_model},
        started_at=datetime.datetime.now(datetime.UTC),
    )

    assert log_generation.call_count == 1
    assert log_generation.call_args.kwargs["provider_model"] == provider_model


@pytest.mark.parametrize(
    ("model_alias", "provider_model"),
    [
        ("image-balanced", "vertex_ai/gemini-3-pro-image"),
        ("image-quality", "openai/gpt-image-2"),
    ],
)
def test_image_models_emit_langfuse_trace_and_generation_payloads(
    monkeypatch: pytest.MonkeyPatch,
    model_alias: str,
    provider_model: str,
) -> None:
    posted: list[list[dict]] = []

    async def capture_batch(host: str, auth: str, batch: list[dict]) -> None:
        assert host == "https://langfuse.test"
        assert auth
        posted.append(batch)

    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "public")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "secret")
    monkeypatch.setenv("LANGFUSE_HOST", "https://langfuse.test")
    monkeypatch.setattr(client, "_post_langfuse_batch", capture_batch)

    async def emit() -> None:
        now = datetime.datetime.now(datetime.UTC)
        client._log_langfuse_generation(
            metadata={
                "trace_id": "request-trace",
                "trace_name": "test.image",
                "generation_name": model_alias,
                "metadata": {},
            },
            feature="test.image",
            operation="image",
            model_alias=model_alias,
            provider_model=provider_model,
            status="succeeded",
            generation_id="image-event",
            input_payload={"prompt": "draw this"},
            output_payload={"actual_provider_model": provider_model},
            usage=None,
            cost_usd=None,
            start_time=now,
            end_time=now,
        )
        await asyncio.sleep(0)

    asyncio.run(emit())

    assert len(posted) == 1
    trace, generation = posted[0]
    assert trace["type"] == "trace-create"
    assert trace["body"]["id"] == "request-trace"
    assert generation["type"] == "generation-create"
    assert generation["body"]["traceId"] == "request-trace"
    assert generation["body"]["model"] == provider_model
