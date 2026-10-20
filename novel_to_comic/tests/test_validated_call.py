"""Validated calls exercise paid attempts, replay and explicit job routing."""
import asyncio

import pytest

from novel_to_comic.clients.validated_call import CallCheckpoint, RetryPolicy, ValidatedCall
from novel_to_comic.config import Config
from novel_to_comic.text_models import TextModelJob, request_reasoning
from novel_to_comic.usage import ApiResult, UsageRecord


def test_correction_preserves_request_and_observes_every_paid_result():
    config = Config(text_reasoning_efforts={"adapt": "low", "prompt": "high"})
    calls, observed = [], []
    usage = UsageRecord(provider="test", model="test", operation="text")

    async def generate(**request):
        assert request_reasoning(config, "test", request["feature"]) == "low"
        calls.append(request)
        return ApiResult("invalid" if len(calls) == 1 else "42", usage=usage)

    schema = {"type": "integer"}
    request = dict(user_content="first", system_prompt="rules", feature="style.telemetry_label", json_schema=schema)
    outcome = asyncio.run(ValidatedCall(
        TextModelJob("adapt", "test"), RetryPolicy(2), int,
        lambda raw, error: "correct the number",
    ).run(generate, request, observe=observed.append))
    assert outcome.value == 42 and outcome.attempts == 2
    assert [r.usage for r in observed] == [usage, usage]
    assert calls == [request, {**request, "user_content": "correct the number"}]
    assert request["user_content"] == "first"
    # The explicit owner is scoped to the call, including after failure.
    assert request_reasoning(config, "test", "style.telemetry_label") == "high"


@pytest.mark.parametrize("error", [RuntimeError("transport failed"), TimeoutError("ambiguous submission")])
def test_transport_failure_never_authorizes_another_attempt(error):
    calls = []

    async def generate(**request):
        calls.append(request)
        raise error

    with pytest.raises(type(error)):
        asyncio.run(ValidatedCall(TextModelJob("adapt", "test"), RetryPolicy(3), int,
                                  lambda raw, error: "repair").run(
            generate, {"user_content": "first"}, observe=lambda result: None,
        ))
    assert len(calls) == 1


@pytest.mark.parametrize("cached,paid", [(42, True), (-1, False), (None, False)])
def test_estimate_and_run_use_the_same_current_checkpoint_validator(cached, paid):
    saved, requests = [], []

    def validate(value):
        if value < 0:
            raise ValueError("negative values no longer satisfy the contract")

    checkpoint = CallCheckpoint(lambda: cached, validate, lambda value: value, saved.append)
    assert checkpoint.is_paid_for() is paid

    async def generate(**request):
        requests.append(request)
        return ApiResult("42")

    outcome = asyncio.run(ValidatedCall(TextModelJob("adapt", "test"), RetryPolicy(), int,
                                      lambda raw, error: f"repair {raw}").run(
        generate, {"user_content": "original"}, observe=lambda result: None, checkpoint=checkpoint,
    ))
    assert outcome.value == 42
    assert len(requests) == (0 if paid else 1)
    assert saved == ([] if paid else [42])
    if cached == -1:
        assert requests[0]["user_content"] == "repair -1"


def test_job_selects_its_own_model_and_rejects_a_mismatched_request():
    config = Config()
    job = TextModelJob.from_config(config, "visual_review")
    assert job.model == config.effective_visual_review_model()
    with job.bind(), pytest.raises(ValueError, match="bound to"):
        request_reasoning(config, "other-model", "style.direction_naming")


def test_style_direction_naming_uses_visual_review_effort_instead_of_prompt_effort(monkeypatch):
    from novel_to_comic.clients import text

    config = Config(text_reasoning_efforts={"prompt": "enabled", "visual_review": "low"})
    job = TextModelJob.from_config(config, "visual_review")

    async def gateway(**request):
        assert request_reasoning(request["config"], request["model"], request["feature"]) == "low"
        return ApiResult({"label": "Claymation snowfall"})

    monkeypatch.setattr(text, "generate_structured_object", gateway)
    result = asyncio.run(text.generate_job_json(
        config, job, system_prompt="Name the direction", user_content="A proof",
        feature="style.direction_naming",
    ))
    assert result.value["label"] == "Claymation snowfall"
