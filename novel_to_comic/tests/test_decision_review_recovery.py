"""Crash/cancellation recovery must not silently replay potentially paid calls."""
import asyncio

import httpx
import pytest

from novel_to_comic.decision_models import DecisionPolicy
from novel_to_comic.labs import decision_review as review
from novel_to_comic.typesafe_decisions import TypeSafeDecisionClient, TypeSafeSettings
from .test_typesafe_decisions import response, sample_case


def test_cancellation_keeps_write_ahead_receipt_and_unknown_latency(tmp_path):
    path = tmp_path / "run.json"
    case = sample_case()
    settings = TypeSafeSettings(concurrency=1)
    calls = []

    async def scenario():
        started = asyncio.Event()

        async def handler(request):
            calls.append(request)
            pending = review.EvaluationRun.model_validate_json(path.read_text())
            assert pending.history[0].observation.reason == "submission_incomplete"
            started.set()
            await asyncio.Event().wait()
            pytest.fail("cancelled transport must not finish")

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            client = TypeSafeDecisionClient(api_key="test", settings=settings, http_client=http)
            task = asyncio.create_task(review.run_cases(
                [case], client=client, output=path, run=review.EvaluationRun(settings=settings),
            ))
            await asyncio.wait_for(started.wait(), 1)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            saved = review.EvaluationRun.model_validate_json(path.read_text())
            with pytest.raises(ValueError, match="unknown"):
                await review.run_cases([case], client=client, output=path, run=saved)
            report = review.summarize([case], saved, DecisionPolicy(model=settings.model))
            assert report["attempted_calls"] == report["incomplete_attempts"] == 1
            assert report["unknown_cost_attempts"] == 1
            assert report["total_cost_usd"] is None
            assert report["provider_elapsed_ms_p50"] is None
            assert report["provider_elapsed_ms_p95"] is None

    asyncio.run(scenario())
    assert len(calls) == 1


@pytest.mark.parametrize("failed_checkpoint", [1, 2])
def test_checkpoint_failure_prevents_unrecorded_resubmission(tmp_path, monkeypatch, failed_checkpoint):
    path = tmp_path / "run.json"
    case = sample_case()
    settings = TypeSafeSettings(concurrency=1)
    original = review.save_private
    checkpoints = 0
    calls = []

    def save(output, text):
        nonlocal checkpoints
        checkpoints += 1
        if checkpoints == failed_checkpoint:
            raise OSError("simulated disk failure")
        original(output, text)

    monkeypatch.setattr(review, "save_private", save)

    async def scenario():
        def handler(request):
            calls.append(request)
            return httpx.Response(200, json=response())

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            client = TypeSafeDecisionClient(api_key="test", settings=settings, http_client=http)
            with pytest.raises(OSError, match="disk failure"):
                await review.run_cases(
                    [case], client=client, output=path, run=review.EvaluationRun(settings=settings),
                )
            if failed_checkpoint == 1:
                assert not path.exists()
            else:
                saved = review.EvaluationRun.model_validate_json(path.read_text())
                assert saved.history[0].observation.reason == "submission_incomplete"
                with pytest.raises(ValueError, match="unknown"):
                    await review.run_cases([case], client=client, output=path, run=saved)

    asyncio.run(scenario())
    assert len(calls) == failed_checkpoint - 1
