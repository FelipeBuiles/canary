"""Provider-free native protocol, abstention, metering and cascade regressions."""
import asyncio
import json

import httpx
import pytest
from pydantic import ValidationError

from novel_to_comic.decision_models import (
    ChoiceAnswer, DecisionCase, DecisionPolicy, Thresholds,
    content_digest, eligibility_reason, question_for,
)
from novel_to_comic.typesafe_decisions import (
    ENDPOINT, DecisionFallbackError, TypeSafeDecisionClient, TypeSafeSettings,
    case_request, decide_case, strict_json,
)
from novel_to_comic.usage import ApiResult, UsageRecord, calculate_cost


def sample_case(**updates):
    return DecisionCase.model_validate({
        "id": "door-1", "group": "book-a", "task": "citation_support",
        "state": {"claim": "The door is closed.", "passages": [
            {"quote": "closed", "context": ["The door is closed."]}]},
        **updates,
    })


def answer(choice="supported", probabilities=None, confidence=0.99):
    return {"type": "choice", "choice": choice, "confidence": confidence,
            "probabilities": probabilities or {"supported": 0.99, "contradicted": 0.005, "insufficient": 0.005}}


def response(**updates):
    return {"model": "jev-1.13.0", "answers": {"decision": answer()},
            "usage": {"input_tokens": 1000, "output_tokens": 50}, **updates}


def policy():
    return DecisionPolicy(model="jev-1.13.0", accepted_labels={"citation_support": {"supported": Thresholds()}})


def evaluate(raw=None, *, status=200, case=None, settings=None, fallback=None, active_policy=None):
    calls = []

    async def scenario():
        def handler(request):
            calls.append(request)
            return httpx.Response(status, json=response() if raw is None else raw)
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            client = TypeSafeDecisionClient(api_key="test-key", settings=settings or TypeSafeSettings(), http_client=http)
            return await decide_case(case or sample_case(), client=client, policy=active_policy or policy(), fallback=fallback)
    result = asyncio.run(scenario())
    return result, calls


def test_native_request_is_not_chat_and_gold_labels_never_leak():
    case = sample_case(expected="contradicted", baseline_label="insufficient")
    result, calls = evaluate(case=case)
    assert result.value == "supported"
    request = calls[0]
    assert str(request.url) == ENDPOINT
    assert request.headers["Authorization"] == "Bearer test-key"
    body = json.loads(request.content)
    assert set(body) == {"state", "model", "questions"}
    assert body == case_request(case, TypeSafeSettings())
    assert "expected" not in body["state"] and "group" not in body["state"]
    assert "state.claim" in body["questions"]["decision"]["instructions"]
    assert result.usage.provider == "typesafe"
    assert result.usage.cost_source == "configured_typesafe_rate"
    assert result.usage.cost_usd == pytest.approx(0.000042)
    assert calculate_cost(result.usage) == pytest.approx(0.000042)


def test_default_policy_always_abstains_even_at_high_confidence():
    result, calls = evaluate(active_policy=DecisionPolicy(model="jev-1.13.0"))
    assert len(calls) == 1 and result.value is None
    assert result.response_metadata["route"] == "abstain"
    assert result.usage is not None


@pytest.mark.parametrize("raw,reason", [
    (response(model="jev-1.14.0"), "model_mismatch"),
    (response(usage=None), "missing_usage"),
    (response(usage={"input_tokens": True, "output_tokens": 0}), "missing_usage"),
    (response(usage={"input_tokens": "1000", "output_tokens": 0}), "missing_usage"),
    (response(usage={"input_tokens": -1, "output_tokens": 0}), "missing_usage"),
    (response(answers={}), "answer_ids_mismatch"),
    (response(answers={"decision": answer(), "invented": answer()}), "answer_ids_mismatch"),
    (response(answers={"decision": {**answer(), "type": "noul"}}), "invalid_response"),
    (response(answers={"decision": answer(confidence=1.1)}), "invalid_response"),
    (response(answers={"decision": answer(confidence=True)}), "invalid_response"),
    (response(answers={"decision": answer(probabilities={"supported": 0.9, "contradicted": 0.9})}), "invalid_response"),
    (response(answers={"decision": answer(choice="contradicted")}), "invalid_response"),
    (response(answers={"decision": answer(probabilities={"supported": 0.99, "bogus": 0.01})}), "labels_mismatch"),
    ([], "invalid_response"),
])
def test_bad_protocol_abstains_without_retry(raw, reason):
    result, calls = evaluate(raw)
    assert result.value is None and len(calls) == 1
    assert result.response_metadata["decision_observation"]["reason"] == reason
    if isinstance(raw, dict) and raw.get("usage") == {"input_tokens": 1000, "output_tokens": 50}:
        assert result.usage is not None  # retained despite invalid response


@pytest.mark.parametrize("status", [301, 401, 422, 429, 500, 529])
def test_http_failure_never_retries_or_follows_redirects_and_preserves_usage(status):
    result, calls = evaluate(status=status)
    assert result.value is None and len(calls) == 1
    assert result.response_metadata["decision_observation"]["reason"] == f"http_{status}"
    assert result.usage.cost_usd == pytest.approx(0.000042)


def test_changed_model_price_is_unknown_not_zero():
    result, _ = evaluate(response(model="jev-1.14.0"))
    assert result.usage.cost_usd is None
    assert result.usage.cost_source == "unknown_model_price"


@pytest.mark.parametrize("text", ['{"a":1,"a":2}', '{"a":NaN}', '{"a":Infinity}'])
def test_strict_json_rejects_duplicate_keys_and_nonfinite_numbers(text):
    with pytest.raises(ValueError):
        strict_json(text)


@pytest.mark.parametrize("changes", [
    {"state": {"claim": "x", "passages": []}},
    {"state": {"claim": "x", "passages": [{"quote": "invented", "context": ["not here"]}]}},
    {"ineligible_reason": "unverified_citations"},
])
def test_missing_evidence_never_spends(changes):
    case = sample_case(**changes)
    assert eligibility_reason(case) == "unverified_citations"
    result, calls = evaluate(case=case)
    assert result.value is None and calls == [] and result.usage is None


def test_large_unicode_request_is_rejected_not_truncated():
    case = sample_case(state={"claim": "x", "passages": [{"quote": "猫", "context": ["猫" * 10000]}]})
    result, calls = evaluate(case=case)
    assert calls == []
    assert result.response_metadata["decision_observation"]["reason"] == "context_too_large"
    assert len(case.state["passages"][0]["context"][0]) == 10000


def test_timeout_includes_queue_and_does_not_invoke_implicit_fallback():
    async def scenario():
        calls = 0
        async def handler(request):
            nonlocal calls
            calls += 1
            await asyncio.sleep(0.1)
            return httpx.Response(200, json=response())
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            client = TypeSafeDecisionClient(api_key="key", settings=TypeSafeSettings(deadline_seconds=0.01, concurrency=1), http_client=http)
            results = await asyncio.gather(*(decide_case(sample_case(), client=client, policy=policy()) for _ in range(2)))
        assert calls == 1
        assert all(r.value is None for r in results)
        assert all(r.response_metadata["decision_observation"]["reason"] == "timeout" for r in results)
        assert sum(r.response_metadata["decision_observation"]["attempted"] for r in results) == 1
    asyncio.run(scenario())


def test_caller_cancellation_propagates_without_fallback():
    async def scenario():
        entered = asyncio.Event()
        async def handler(request):
            entered.set()
            await asyncio.sleep(10)
        async def fallback():
            pytest.fail("cancellation must not start another paid call")
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            client = TypeSafeDecisionClient(api_key="key", settings=TypeSafeSettings(), http_client=http)
            task = asyncio.create_task(decide_case(sample_case(), client=client, policy=policy(), fallback=fallback))
            await entered.wait()
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
    asyncio.run(scenario())


def test_explicit_fallback_receipts_are_preserved():
    primary = UsageRecord(provider="gateway", model="test", operation="text", cost_usd=0.01)
    extra = UsageRecord(provider="gateway", model="test", operation="text", cost_usd=0.02)
    async def fallback():
        return ApiResult("contradicted", usage=primary, additional_usage=(extra,))
    result, calls = evaluate(active_policy=DecisionPolicy(model="jev-1.13.0"), fallback=fallback)
    assert len(calls) == 1 and result.value == "contradicted"
    assert result.usage is primary and result.additional_usage[-1] is extra
    assert result.additional_usage[0].provider == "typesafe"
    assert len({r.call_id for r in (result.usage, *result.additional_usage)}) == 3
    assert result.response_metadata["route"] == "fallback"


def test_failed_fallback_carries_primary_usage():
    async def fallback():
        raise RuntimeError("do not expose provider text")
    with pytest.raises(DecisionFallbackError) as error:
        evaluate(active_policy=DecisionPolicy(model="jev-1.13.0"), fallback=fallback)
    assert len(error.value.usage_records) == 1
    assert error.value.usage_records[0].provider == "typesafe"
    assert "provider text" not in str(error.value)


def test_invalid_fallback_label_is_not_accepted_and_keeps_usage():
    async def fallback():
        return ApiResult("looks fine", usage=UsageRecord(provider="x", model="x", operation="text", cost_usd=0.01))
    result, _ = evaluate(active_policy=DecisionPolicy(model="jev-1.13.0"), fallback=fallback)
    assert result.value is None and result.usage.cost_usd == 0.01
    assert result.response_metadata["fallback_label_valid"] is False


def test_policy_is_bound_to_model_rubric_and_class_thresholds():
    a = ChoiceAnswer.model_validate(answer())
    assert policy().accepts("citation_support", a, model="jev-1.13.0")
    assert not policy().accepts("citation_support", a, model="jev-1.14.0")
    assert not policy().model_copy(update={"rubric_version": "stale"}).accepts("citation_support", a, model="jev-1.13.0")
    assert not policy().accepts("participation", a, model="jev-1.13.0")
    assert not policy().accepts("citation_support", a.model_copy(update={"confidence": 0.5}), model="jev-1.13.0")


@pytest.mark.parametrize("label", ["unknown", "insufficient"])
def test_unknown_and_uncertain_labels_cannot_be_auto_accepted(label):
    with pytest.raises(ValidationError):
        DecisionPolicy(model="jev-1.13.0", accepted_labels={"citation_support": {label: Thresholds()}})


def test_aliases_and_silent_price_rollover_rejected():
    with pytest.raises(ValidationError):
        TypeSafeSettings(model="jev-latest")
    with pytest.raises(ValidationError):
        TypeSafeSettings(model="jev-1.14.0")


def test_request_identity_changes_with_evidence_and_criteria_not_gold():
    settings = TypeSafeSettings()
    original = content_digest(case_request(sample_case(), settings))
    assert original == content_digest(case_request(sample_case(expected="supported"), settings))
    assert original != content_digest(case_request(sample_case(state={"claim": "The door is open.", "passages": []}), settings))
    assert question_for("participation").criteria["background_only"]


def test_unknown_typesafe_cost_cannot_be_settled_as_zero():
    result, _ = evaluate(response(model="jev-1.14.0"))
    with pytest.raises(ValueError, match="unknown"):
        calculate_cost(result.usage)


def test_unvalidated_language_abstains_under_english_only_policy():
    result, _ = evaluate(case=sample_case(language="es"))
    assert result.value is None
