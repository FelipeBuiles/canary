"""Provider-free cumulative admission, resume and ambiguous-outcome checks."""
import asyncio
import json

import pytest

from novel_to_comic.generation_budget import budgeted_generator, GenerationWorkLimitError
from novel_to_comic.generation_checkpoints import checkpointed_generator
from novel_to_comic.target_artifacts import TargetArtifacts
from novel_to_comic.usage import ApiResult, UsageRecord


def wrap(generate, path, *, model="test", inputs=None, max_calls=2, override=False):
    return budgeted_generator(generate, artifacts=TargetArtifacts(path), stage="adapt", model=model,
                              inputs=inputs or {"approved_source": "same"}, max_calls=max_calls,
                              override_limit=override)


def test_limit_persists_across_resumes_and_models_but_allows_checkpoint_hits(tmp_path):
    calls = []

    async def generate(**request):
        calls.append(request)
        return ApiResult(value={"ok": True})

    async def exercise():
        for n in range(2):
            call = wrap(generate, tmp_path)
            cached = checkpointed_generator(call, artifacts=TargetArtifacts(tmp_path), stage="adapt", model="test")
            await cached(feature="adapt.book", user_content=str(n))
        await cached(feature="adapt.book", user_content="0")
        # A different model/default computation cannot grant a fresh allowance.
        with pytest.raises(GenerationWorkLimitError):
            await wrap(generate, tmp_path, model="another", max_calls=20)(user_content="new")
        await wrap(generate, tmp_path, inputs={"approved_source": "changed"})(user_content="new")
        await wrap(generate, tmp_path, max_calls=3, override=True)(user_content="authorized larger limit")

    asyncio.run(exercise())
    assert len(calls) == 4


def test_concurrent_calls_and_unresolved_results_consume_slots(tmp_path):
    calls = []

    async def generate(**request):
        calls.append(request)
        await asyncio.sleep(0)
        raise TimeoutError("Outcome unknown")

    async def exercise():
        call = wrap(generate, tmp_path)
        results = await asyncio.gather(*(call(user_content=str(n)) for n in range(5)), return_exceptions=True)
        assert sum(isinstance(r, TimeoutError) for r in results) == 2
        assert sum(isinstance(r, GenerationWorkLimitError) for r in results) == 3
        with pytest.raises(GenerationWorkLimitError):
            await wrap(generate, tmp_path)(user_content="retry")

    asyncio.run(exercise())
    assert len(calls) == 2
    saved = json.loads(next((tmp_path / ".checkpoints/adapt/work").glob("*.json")).read_text())
    assert [c["status"] for c in saved["calls"]] == ["unresolved", "unresolved"]
    assert all(c["accounted_cost_usd"] is None for c in saved["calls"])


def test_plan_limit_increase_preserves_spent_calls_and_cached_work(tmp_path):
    calls = []
    artifacts = TargetArtifacts(tmp_path)

    async def generate(**request):
        calls.append(request)
        return ApiResult(value={"findings": []})

    def planner(limit, override=False):
        bounded = budgeted_generator(generate, artifacts=artifacts, stage="plan", model="test",
                                     inputs={"adaptation": "same"}, max_calls=limit, override_limit=override)
        return checkpointed_generator(bounded, artifacts=artifacts, stage="plan", model="test")

    async def exercise():
        original = planner(24)
        for n in range(24):
            await original(feature="plan.detail", user_content=str(n))
        with pytest.raises(GenerationWorkLimitError):
            await planner(64)(feature="plan.narrative_review", user_content="remaining window")
        path = next((tmp_path / ".checkpoints/plan/work").glob("*.json"))
        before = json.loads(path.read_text())["calls"]
        resumed = planner(64, override=True)
        await resumed(feature="plan.detail", user_content="0")
        await resumed(feature="plan.narrative_review", user_content="remaining window")
        after = json.loads(path.read_text())
        assert after["limit"] == 64
        assert after["calls"][:24] == before
        assert len(after["calls"]) == 25
        assert len(calls) == 25

    asyncio.run(exercise())


def test_known_and_additional_usage_are_distinct_from_unknown_outcomes(tmp_path):
    async def generate(**request):
        return ApiResult(value={}, usage=UsageRecord(provider="test", model="test", operation="text",
                         input_tokens=10, output_tokens=2, cost_usd=0.03),
                         additional_usage=(UsageRecord(provider="test", model="test", operation="text",
                         input_tokens=12, output_tokens=3, cost_usd=0.02),))
    asyncio.run(wrap(generate, tmp_path)(feature="adapt.narrative_review", user_content="words"))
    saved = json.loads(next((tmp_path / ".checkpoints/adapt/work").glob("*.json")).read_text())
    call = saved["calls"][0]
    assert call["input_tokens"] == 22
    assert call["output_tokens"] == 5
    assert call["accounted_cost_usd"] == pytest.approx(0.05)
    assert call["status"] == "completed"


def test_corrupt_budget_fails_before_any_generation(tmp_path):
    async def generate(**request):
        return ApiResult(value={})
    asyncio.run(wrap(generate, tmp_path)(user_content="first"))
    next((tmp_path / ".checkpoints/adapt/work").glob("*.json")).write_text('{"limit": 100}')
    with pytest.raises(Exception, match="incompatible"):
        asyncio.run(wrap(generate, tmp_path)(user_content="second"))


def test_explicit_restart_grants_new_allowance_without_reusing_or_erasing_old_work(tmp_path):
    calls = []

    async def generate(**request):
        calls.append(request)
        return ApiResult(value={"attempt": len(calls)})

    def generator():
        return checkpointed_generator(wrap(generate, tmp_path, max_calls=1),
            artifacts=TargetArtifacts(tmp_path), stage="adapt", model="test")

    asyncio.run(generator()(user_content="same inputs"))
    with pytest.raises(GenerationWorkLimitError):
        asyncio.run(generator()(user_content="repair"))
    budget = next((tmp_path / ".checkpoints/adapt/work").glob("*.json"))
    before = budget.read_bytes()
    archive = TargetArtifacts(tmp_path).archive_adaptation_work()
    result = asyncio.run(generator()(user_content="same inputs"))
    assert result.value == {"attempt": 2}
    assert len(calls) == 2
    assert (archive / budget.relative_to(tmp_path)).read_bytes() == before
    assert len(json.loads(budget.read_text())["calls"]) == 1


def test_ledger_separates_queued_from_executing_calls(tmp_path):
    from novel_to_comic.ai.context import notify_execution_started

    release = asyncio.Event()
    seen = {}

    async def generate(**request):
        seen["queued"] = TargetArtifacts(tmp_path).read_generation_budget("adapt", lineage()).calls[0].started_at
        await release.wait()
        notify_execution_started()
        notify_execution_started()  # schema retries re-notify; stamped once
        seen["started"] = TargetArtifacts(tmp_path).read_generation_budget("adapt", lineage()).calls[0].started_at
        return ApiResult(value={"ok": True})

    def lineage():
        from novel_to_comic.generation_budget import generation_lineage
        return generation_lineage({"approved_source": "same"})

    async def exercise():
        task = asyncio.create_task(wrap(generate, tmp_path)(feature="adapt.book"))
        await asyncio.sleep(0)
        release.set()
        await task

    asyncio.run(exercise())
    call = TargetArtifacts(tmp_path).read_generation_budget("adapt", lineage()).calls[0]
    assert seen["queued"] is None
    assert seen["started"] is not None and call.started_at == seen["started"]
    assert call.admitted_at <= call.started_at <= call.finished_at
