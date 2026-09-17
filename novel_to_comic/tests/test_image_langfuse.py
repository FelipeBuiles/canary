from __future__ import annotations

import asyncio
import datetime
from unittest.mock import MagicMock

import httpx
import pytest

from novel_to_comic.ai import client, finalisation
from novel_to_comic.config import Config
from novel_to_comic.usage import UsageRecord


@pytest.fixture(autouse=True)
def _isolate_langfuse_environment(monkeypatch):
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "public")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "secret")
    monkeypatch.setenv("CANARY_LANGFUSE_HOST", "https://langfuse.test")
    monkeypatch.setenv("LANGFUSE_HOST", "https://langfuse.test")
    monkeypatch.delenv("CANARY_LOG_INCLUDE_PROMPTS", raising=False)


@pytest.fixture
def lifecycle_dependencies(monkeypatch):
    database = MagicMock()
    table = database.table.return_value
    table.insert.return_value = table
    table.update.return_value = table
    table.eq.return_value = table
    monkeypatch.setattr("novel_to_comic.server.db.get_db", lambda: database)
    monkeypatch.setattr(client, "_settle_event_usage", MagicMock())
    monkeypatch.setattr("novel_to_comic.server.metrics.record_ai_call", MagicMock())
    monkeypatch.setattr(client, "route_for", lambda *args: None)
    monkeypatch.setattr(finalisation, "route_for", lambda *args: None)
    monkeypatch.setenv("CANARY_AI_STREAM_TEXT", "0")
    return table


def _assert_running_batch(batch, *, event_id, operation):
    trace, generation = batch
    assert trace["type"] == "trace-create"
    assert generation["type"] == "generation-create"
    body = generation["body"]
    assert body["id"] == event_id
    assert body["traceId"] == trace["body"]["id"]
    assert body["metadata"]["status"] == "running"
    assert body["metadata"]["operation"] == operation
    assert body["level"] == "DEFAULT"
    assert generation["timestamp"] == body["startTime"]
    assert trace["body"]["timestamp"] == body["startTime"]
    assert {"endTime", "output", "usageDetails", "costDetails"}.isdisjoint(body)
    assert "output" not in trace["body"]


def _assert_terminal_batch(running, terminal, *, status):
    start_trace, start_generation = running
    end_trace, end_generation = terminal
    start = start_generation["body"]
    end = end_generation["body"]
    assert end_generation["type"] in {"generation-create", "generation-update"}
    assert end_trace["body"]["id"] == start_trace["body"]["id"]
    assert end["id"] == start["id"]
    assert end["traceId"] == start["traceId"]
    assert end["startTime"] == start["startTime"]
    assert end["metadata"]["status"] == status
    assert end["endTime"] > start["startTime"]
    # Upsert timestamps protect the terminal state even if HTTP arrival reverses.
    assert end_generation["timestamp"] > start_generation["timestamp"]
    assert end_trace["timestamp"] > start_trace["timestamp"]


@pytest.mark.parametrize("outcome", ["succeeded", "failed", "cancelled"])
def test_text_langfuse_running_call_closes_same_observation(
    monkeypatch, lifecycle_dependencies, outcome,
):
    async def exercise():
        import json

        entered = asyncio.Event()
        release = asyncio.Event()
        exports = asyncio.Queue()
        batches = []

        async def handle(request):
            if request.url == httpx.URL("https://langfuse.test/api/public/ingestion"):
                batch = json.loads(request.content)["batch"]
                batches.append(batch)
                exports.put_nowait(batch)
                return httpx.Response(200, json={})
            assert request.url == httpx.URL("https://provider.test/v1/chat/completions")
            entered.set()
            await release.wait()
            if outcome == "failed":
                return httpx.Response(400, json={"error": {"message": "rejected"}})
            return httpx.Response(200, json={
                "model": "openai/gpt-5.4-mini",
                "choices": [{"message": {"content": "finished answer"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 7, "completion_tokens": 3},
                "_hidden_params": {"response_cost": 0.02},
            })

        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
            monkeypatch.setattr(client, "_http", http)
            task = asyncio.create_task(client.generate_text(
                config=Config(litellm_base_url="https://provider.test"),
                model="gpt-5.6-terra",
                system_prompt="system secret",
                user_content="user secret",
                feature="test.text.lifecycle",
            ))
            try:
                await asyncio.wait_for(entered.wait(), timeout=2)
                running = await asyncio.wait_for(exports.get(), timeout=2)
                assert not task.done()
                event = lifecycle_dependencies.insert.call_args.args[0]
                event_id = event["id"]
                _assert_running_batch(running, event_id=event_id, operation="text")
                assert running[1]["body"]["traceId"] == event["metadata_json"]["trace_id"]
                assert "user secret" not in json.dumps(running)
                assert "system secret" not in json.dumps(running)
                if outcome == "cancelled":
                    task.cancel()
                    with pytest.raises(asyncio.CancelledError):
                        await task
                elif outcome == "failed":
                    release.set()
                    with pytest.raises(client.AITransportError):
                        await task
                else:
                    release.set()
                    result = await task
                    assert result.value == "finished answer"
                    assert result.usage.call_id == event_id
                terminal = await asyncio.wait_for(exports.get(), timeout=2)
                _assert_terminal_batch(running, terminal, status=outcome)
                if outcome == "succeeded":
                    assert terminal[1]["body"]["usageDetails"] == {"input": 7, "output": 3, "total": 10}
                    assert terminal[1]["body"]["costDetails"] == {"total": 0.02}
                assert lifecycle_dependencies.update.call_args.args[0]["status"] == outcome
                assert len(batches) == 2
                assert {event["body"]["id"] for batch in batches for event in batch
                        if event["type"].startswith("generation-")} == {event_id}
            finally:
                if not task.done():
                    task.cancel()
                await asyncio.gather(task, return_exceptions=True)

    asyncio.run(exercise())


def test_image_langfuse_begin_and_cancel_closes_same_observation(
    monkeypatch, lifecycle_dependencies,
):
    async def exercise():
        import json

        exports = asyncio.Queue()
        batches = []

        async def handle(request):
            assert request.url == httpx.URL("https://langfuse.test/api/public/ingestion")
            batch = json.loads(request.content)["batch"]
            batches.append(batch)
            exports.put_nowait(batch)
            return httpx.Response(200, json={})

        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
            monkeypatch.setattr(client, "_http", http)
            config = Config()
            ctx = await finalisation.begin_image_call(
                config=config, model="image-gpt-2", feature="test.image.lifecycle",
                prompt="secret image prompt", params={"size": "1024x1024"}, ref_reads=[],
            )
            running = await asyncio.wait_for(exports.get(), timeout=2)
            _assert_running_batch(running, event_id=ctx.event_id, operation="image")
            assert running[1]["body"]["startTime"] == ctx.started_at.isoformat()
            assert running[1]["body"]["traceId"] == ctx.metadata["trace_id"]
            assert "secret image prompt" not in json.dumps(running)
            await finalisation.finalise_image_cancelled(
                ctx=ctx, config=config, model="image-gpt-2", feature="test.image.lifecycle",
                error=asyncio.CancelledError(),
            )
            terminal = await asyncio.wait_for(exports.get(), timeout=2)
            _assert_terminal_batch(running, terminal, status="cancelled")
            assert lifecycle_dependencies.update.call_args.args[0]["status"] == "cancelled"
            assert len(batches) == 2
            assert {event["body"]["id"] for batch in batches for event in batch
                    if event["type"].startswith("generation-")} == {ctx.event_id}

    asyncio.run(exercise())


@pytest.mark.parametrize(
    ("model_alias", "provider", "provider_model"),
    [
        ("image-gemini-pro", "gemini", "vertex_ai/gemini-3-pro-image"),
        ("image-gpt-2", "openai", "openai/gpt-image-2"),
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
        ("image-gemini-pro", "vertex_ai/gemini-3-pro-image"),
        ("image-gpt-2", "openai/gpt-image-2"),
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


def _emit_text_generation() -> list[list[dict]]:
    posted: list[list[dict]] = []

    async def capture_batch(host: str, auth: str, batch: list[dict]) -> None:
        posted.append(batch)

    return posted, capture_batch


def test_langfuse_redacts_prompt_content_by_default(monkeypatch):
    import json

    posted, capture_batch = _emit_text_generation()
    monkeypatch.delenv("CANARY_LOG_INCLUDE_PROMPTS", raising=False)
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "public")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "secret")
    monkeypatch.setenv("LANGFUSE_HOST", "https://langfuse.test")
    monkeypatch.setattr(client, "_post_langfuse_batch", capture_batch)

    async def emit() -> None:
        now = datetime.datetime.now(datetime.UTC)
        client._log_langfuse_generation(
            metadata={"trace_id": "trace-1", "metadata": {}},
            feature="test.text",
            operation="text",
            model_alias="gpt-5.6-terra",
            provider_model="openai/gpt-5.4-mini",
            status="succeeded",
            generation_id="event-1",
            input_payload=[
                {"role": "user", "content": "secret prompt body"},
            ],
            output_payload="secret response body",
            usage=None,
            cost_usd=None,
            start_time=now,
            end_time=now,
        )
        await asyncio.sleep(0)

    asyncio.run(emit())

    assert len(posted) == 1
    dumped = json.dumps(posted[0])
    assert "secret prompt body" not in dumped
    assert "secret response body" not in dumped


def test_langfuse_exports_prompt_content_with_explicit_opt_in(monkeypatch):
    import json

    posted, capture_batch = _emit_text_generation()
    monkeypatch.setenv("CANARY_LOG_INCLUDE_PROMPTS", "1")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "public")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "secret")
    monkeypatch.setenv("LANGFUSE_HOST", "https://langfuse.test")
    monkeypatch.setattr(client, "_post_langfuse_batch", capture_batch)

    async def emit() -> None:
        now = datetime.datetime.now(datetime.UTC)
        client._log_langfuse_generation(
            metadata={"trace_id": "trace-1", "metadata": {}},
            feature="test.text",
            operation="text",
            model_alias="gpt-5.6-terra",
            provider_model="openai/gpt-5.4-mini",
            status="succeeded",
            generation_id="event-1",
            input_payload=[
                {"role": "user", "content": "visible prompt body"},
            ],
            output_payload="visible response body",
            usage=None,
            cost_usd=None,
            start_time=now,
            end_time=now,
        )
        await asyncio.sleep(0)

    asyncio.run(emit())

    assert len(posted) == 1
    dumped = json.dumps(posted[0])
    assert "visible prompt body" in dumped
    assert "visible response body" in dumped
