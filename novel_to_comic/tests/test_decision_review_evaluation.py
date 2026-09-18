"""Provider-free saved-review export, replay metrics and controlled-spend tests."""
import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from novel_to_comic.decision_models import (
    RUBRIC_VERSION, ChoiceAnswer, DecisionPolicy, canonical_json, content_digest,
)
from novel_to_comic.labs.decision_review import (
    CaseObservation, EvaluationRun, latest_observations, live_run_lock, load_cases,
    main, narrative_cases, projected_input_cost, run_cases, save_private, summarize,
)
from novel_to_comic.typesafe_decisions import (
    DecisionObservation, TypeSafeDecisionClient, TypeSafeSettings, case_request,
)
from novel_to_comic.usage import UsageRecord
from .test_typesafe_decisions import answer, policy, response, sample_case


def saved_row(case=None, *, chosen=None, reason=None, attempted=True, tokens=1000, cost=0.000042):
    case = case or sample_case()
    return CaseObservation(
        case_id=case.id, group=case.group,
        observation=DecisionObservation(
            request_sha256=content_digest(case_request(case, TypeSafeSettings())),
            requested_model="jev-1.13.0", resolved_model="jev-1.13.0",
            answers={} if reason else {"decision": ChoiceAnswer.model_validate(chosen or answer())},
            usage=UsageRecord(provider="typesafe", model="jev-1.13.0", operation="text",
                              input_tokens=tokens, cost_usd=cost),
            attempted=attempted, elapsed_ms=100, reason=reason,
        ),
    )


def test_replay_computes_selective_risk_not_global_accuracy():
    good = sample_case(expected="supported", baseline_label="supported")
    bad = sample_case(id="bad", expected="contradicted", baseline_label="contradicted")
    unlabeled = sample_case(id="unlabeled")
    low = sample_case(id="low", expected="supported")
    cases = [good, bad, unlabeled, low]
    run = EvaluationRun(settings=TypeSafeSettings(), history=[
        saved_row(good), saved_row(bad), saved_row(unlabeled),
        saved_row(low, chosen=answer(confidence=0.3)),
    ])
    report = summarize(cases, run, policy())
    metrics = report["metrics"]
    assert metrics["coverage"] == 0.75
    assert metrics["accepted_labeled"] == 2
    assert metrics["accepted_errors"] == 1
    assert metrics["selective_error_rate"] == 0.5
    assert metrics["baseline_agreement"] == 0.5
    assert metrics["zero_error_upper_95_if_iid"] is None
    assert metrics["multiclass_brier"] > 0
    assert report["total_cost_usd"] == pytest.approx(0.000168)
    assert report["provider_elapsed_ms_p95"] == 100
    assert report["by_language"]["en"]["cases"] == 4


def test_zero_labels_is_unknown_quality_not_perfect_quality():
    case = sample_case()
    report = summarize([case], EvaluationRun(settings=TypeSafeSettings(), history=[saved_row(case)]), policy())
    assert report["metrics"]["selective_error_rate"] is None
    assert report["metrics"]["multiclass_brier"] is None
    assert report["metrics"]["accepted"] == 1


def test_zero_accepted_has_no_error_bound_and_labeled_success_uses_actual_denominator():
    case = sample_case(expected="supported")
    run = EvaluationRun(settings=TypeSafeSettings(), history=[saved_row(case)])
    metrics = summarize([case], run, DecisionPolicy(model="jev-1.13.0"))["metrics"]
    assert metrics["selective_error_rate"] is None and metrics["zero_error_upper_95_if_iid"] is None
    assert summarize([case], run, policy())["metrics"]["zero_error_upper_95_if_iid"] == pytest.approx(0.95)


def test_unknown_spend_is_not_zero_and_attempts_are_retained():
    case = sample_case()
    unknown = saved_row(case, reason="timeout", cost=None)
    run = EvaluationRun(settings=TypeSafeSettings(), history=[unknown, saved_row(case)])
    report = summarize([case], run, policy())
    assert report["attempted_calls"] == 2
    assert report["unknown_cost_attempts"] == 1
    assert report["total_cost_usd"] is None
    assert report["known_cost_usd"] == pytest.approx(0.000042)


@pytest.mark.parametrize("change", ["state", "rubric", "model", "labels"])
def test_replay_rejects_stale_or_corrupt_receipts(change):
    case = sample_case()
    row = saved_row(case)
    if change == "state":
        case = sample_case(state={"claim": "changed", "passages": []})
    elif change == "rubric":
        row = row.model_copy(update={"observation": row.observation.model_copy(update={"rubric_version": "old"})})
    elif change == "model":
        row = row.model_copy(update={"observation": row.observation.model_copy(update={"resolved_model": "jev-1.14.0"})})
    else:
        row = row.model_copy(update={"observation": row.observation.model_copy(update={
            "answers": {"decision": ChoiceAnswer.model_validate(answer(probabilities={"supported": 0.99, "wrong": 0.01}))}
        })})
    with pytest.raises(ValueError):
        latest_observations([case], EvaluationRun(settings=TypeSafeSettings(), history=[row]))


def test_policy_mismatch_requires_new_evaluation_not_silent_threshold_reuse():
    with pytest.raises(ValueError, match="policy"):
        summarize([sample_case()], EvaluationRun(settings=TypeSafeSettings()), DecisionPolicy(model="jev-1.14.0"))


def test_new_gold_labels_allow_replay_without_resending_text():
    old = sample_case(expected="supported")
    new = sample_case(expected="contradicted")
    run = EvaluationRun(settings=TypeSafeSettings(), history=[saved_row(old)])
    assert summarize([new], run, policy())["metrics"]["accepted_errors"] == 1


def test_journal_resume_reuses_low_confidence_and_never_retries_failed_calls(tmp_path):
    good = sample_case(id="good")
    failed = sample_case(id="failed")
    run = EvaluationRun(settings=TypeSafeSettings(), history=[
        saved_row(good, chosen=answer(confidence=0.1)), saved_row(failed, reason="http_429"),
    ])
    async def scenario():
        def handler(request):
            pytest.fail("valid low-confidence and failed prior submissions must not be resampled")
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            client = TypeSafeDecisionClient(api_key="test", settings=TypeSafeSettings(), http_client=http)
            result = await run_cases([good, failed], client=client, output=tmp_path / "run.json", run=run)
            assert len(result.history) == 2
    asyncio.run(scenario())


def test_unknown_prior_spend_prevents_new_submissions(tmp_path):
    case = sample_case()
    run = EvaluationRun(settings=TypeSafeSettings(), history=[saved_row(case, reason="timeout", cost=None)])
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: pytest.fail("no request"))) as http:
            client = TypeSafeDecisionClient(api_key="test", settings=TypeSafeSettings(), http_client=http)
            with pytest.raises(ValueError, match="unknown"):
                await run_cases([case], client=client, output=tmp_path / "run.json", run=run)
    asyncio.run(scenario())


def test_live_runner_stops_next_batch_on_failure_and_persists_usage(tmp_path):
    cases = [sample_case(id=str(i)) for i in range(5)]
    path = tmp_path / "run.json"
    calls = []
    async def scenario():
        def handler(request):
            calls.append(request)
            return httpx.Response(429, json=response())
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            client = TypeSafeDecisionClient(api_key="test", settings=TypeSafeSettings(), http_client=http)
            result = await run_cases(cases, client=client, output=path, run=EvaluationRun(settings=TypeSafeSettings()))
            assert len(result.history) == 2
    asyncio.run(scenario())
    assert len(calls) == 2
    report = EvaluationRun.model_validate_json(path.read_text())
    assert len(report.history) == 2 and report.history[0].observation.usage.cost_usd > 0
    assert path.stat().st_mode & 0o777 == 0o600
    assert "claim" not in path.read_text() and "test-key" not in path.read_text()


def test_conservative_allowance_and_budget_stop_before_network(tmp_path):
    cases = [sample_case()]
    assert projected_input_cost(cases, TypeSafeSettings()) > 0
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: pytest.fail("no spend"))) as http:
            client = TypeSafeDecisionClient(api_key="key", settings=TypeSafeSettings(), http_client=http)
            with pytest.raises(ValueError, match="budget"):
                await run_cases(cases, client=client, output=tmp_path / "run.json",
                                run=EvaluationRun(settings=TypeSafeSettings()), max_cost_usd=0.000001)
    asyncio.run(scenario())


def test_dry_run_requires_no_credentials_and_writes_no_observation(tmp_path, monkeypatch, capsys):
    cases = tmp_path / "cases.jsonl"
    cases.write_text(canonical_json(sample_case().model_dump()) + "\n")
    output = tmp_path / "results.json"
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    main(["run", str(cases), "--output", str(output)])
    assert json.loads(capsys.readouterr().out)["provider_calls"] == 0
    assert not output.exists()


def test_live_requires_explicit_credentials_and_preserves_input(tmp_path, monkeypatch):
    cases = tmp_path / "cases.jsonl"
    cases.write_text(canonical_json(sample_case().model_dump()) + "\n")
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    with pytest.raises(SystemExit):
        main(["run", str(cases), "--output", str(tmp_path / "results.json"), "--allow-paid"])
    with pytest.raises(SystemExit):
        main(["run", str(cases), "--output", str(cases)])
    assert load_cases(cases) == [sample_case()]


def test_lock_blocks_concurrent_paid_run_and_cleans_up(tmp_path):
    path = tmp_path / "run.json"
    with live_run_lock(path):
        with pytest.raises(ValueError, match="locked"):
            with live_run_lock(path):
                pytest.fail("must not enter second paid session")
    assert not path.with_name("run.json.lock").exists()


def test_private_write_refuses_temporary_symlink(tmp_path):
    target = tmp_path / "important"
    target.write_text("preserve")
    path = tmp_path / "run.json"
    path.with_name("run.json.tmp").symlink_to(target)
    with pytest.raises(FileExistsError):
        save_private(path, "new")
    assert target.read_text() == "preserve"


def test_narrative_export_is_fresh_exact_unlabeled_and_nonmutating(monkeypatch):
    import novel_to_comic.narrative_review as review
    context = {"phase": "adapt", "source": "evidence"}
    finding = SimpleNamespace(
        evidence="The door is closed.", artifact_ids=("unit-1",),
        passages=(SimpleNamespace(artifact_id="unit-1", quote="closed"),),
    )
    record = SimpleNamespace(version=review.REVIEW_VERSION, input_sha256=review.review_digest(context),
                             instruction="preserve words", failures=(),
                             verdicts=(SimpleNamespace(findings=(finding,)),))
    monkeypatch.setattr(review, "_review_contexts", lambda _: iter([{"window": 1}]))
    monkeypatch.setattr(review, "_passage_texts", lambda _: {"unit-1": ["The door is closed. Never open it."]})
    cases = narrative_cases(context, record, group="book-1")
    assert len(cases) == 1 and cases[0].expected is None and cases[0].baseline_label is None
    assert cases[0].ineligible_reason is None
    assert cases[0].state["passages"][0]["context"] == ["The door is closed. Never open it."]
    finding.passages = (SimpleNamespace(artifact_id="unit-1", quote="fabricated"),)
    assert narrative_cases(context, record, group="book-1")[0].ineligible_reason == "unverified_citations"
    record.input_sha256 = "0" * 64
    with pytest.raises(ValueError, match="stale"):
        narrative_cases(context, record, group="book-1")


def test_narrative_export_uses_real_review_windows_and_preserves_quote_authority():
    from novel_to_comic.narrative_review import (
        REVIEW_VERSION, NarrativeFinding, NarrativePassage, NarrativeReviewRecord, NarrativeVerdict,
        adaptation_context, review_digest,
    )
    from .test_book_adaptation import _source_document, _approved_brief, _book_adaptation
    source = _source_document()
    context = adaptation_context(source, _approved_brief(), _book_adaptation())
    unit = source.units[0]
    finding = NarrativeFinding(
        code="unsupported_event", repair_stage="adapt", artifact_ids=(unit.id,),
        evidence="This passage describes the opening scene.", repair="Review the scene.",
        passages=(NarrativePassage(artifact_id=unit.id, quote=unit.text),),
    )
    record = NarrativeReviewRecord(version=REVIEW_VERSION, input_sha256=review_digest(context),
                                   model="test", failures=(), verdicts=(NarrativeVerdict(findings=(finding,), signal_assessments=()),))
    cases = narrative_cases(context, record, group="real-fixture")
    assert cases[0].state["passages"][0]["context"] == [unit.text]
    assert cases[0].ineligible_reason is None


def test_seed_fixture_is_labeled_examples_not_measured_results():
    path = Path(__file__).parents[1] / "src/novel_to_comic/labs/fixtures/decision_cases.jsonl"
    cases = load_cases(path)
    assert len(cases) >= 20
    assert {c.task for c in cases} == {"citation_support", "participation", "correction_route"}
    assert {c.language for c in cases} >= {"en", "es", "fr"}
    assert all(c.group.startswith("synthetic-") and c.expected for c in cases)
    assert RUBRIC_VERSION


@pytest.mark.parametrize("candidate", [False, True])
def test_plan_export_resolves_real_page_evidence_not_manifest(monkeypatch, tmp_path, candidate):
    import novel_to_comic.narrative_review as review
    import novel_to_comic.target_artifacts as target
    from novel_to_comic.labs.decision_review import export_project
    adaptation = SimpleNamespace(content_sha256="a" * 64)
    page = SimpleNamespace(content_sha256="b" * 64)
    manifest = SimpleNamespace(page_number=1, revision=2, content_sha256="b" * 64)
    plan = SimpleNamespace(adaptation_sha256="a" * 64, pages=[page if candidate else manifest])
    seen = []
    artifacts = SimpleNamespace(
        read_adaptation=lambda: adaptation,
        read_plan=lambda: plan,
        read_plan_review_draft=lambda: plan,
        read_page_revision=lambda number, revision: seen.append((number, revision)) or page,
        read_narrative_review=lambda phase: "record",
    )
    monkeypatch.setattr(target, "TargetArtifacts", lambda _: artifacts)
    monkeypatch.setattr(review, "planning_context", lambda a, pages: {"pages": pages})
    monkeypatch.setattr("novel_to_comic.labs.decision_review.narrative_cases",
                        lambda context, record, **kwargs: context["pages"])
    result = export_project(tmp_path, "plan", group="book", language="en", candidate=candidate)
    assert result == [page]
    assert seen == ([] if candidate else [(1, 2)])
    plan.adaptation_sha256 = "c" * 64
    with pytest.raises(ValueError, match="different adaptation"):
        export_project(tmp_path, "plan", group="book", language="en", candidate=candidate)
