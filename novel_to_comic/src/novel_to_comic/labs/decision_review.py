"""Operator-run, read-only review/classifier evaluation. No production gate changes.

Run with ``python -m novel_to_comic.labs.decision_review --help``. Export and
replay are provider-free; run requires an explicit paid flag and budget.
"""
from __future__ import annotations

import argparse
import asyncio
import math
import os
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import httpx
from pydantic import Field

from novel_to_comic.decision_models import (
    RUBRIC_VERSION, DecisionCase, DecisionModel, DecisionPolicy,
    canonical_json, content_digest, eligibility_reason,
)
from novel_to_comic.typesafe_decisions import (
    DecisionObservation, TypeSafeDecisionClient, TypeSafeSettings,
    case_request, decide_case, strict_json,
)

REPORT_VERSION = "decision-evaluation-v1"


class CaseObservation(DecisionModel):
    case_id: str
    group: str
    observation: DecisionObservation


class EvaluationRun(DecisionModel):
    version: str = REPORT_VERSION
    settings: TypeSafeSettings
    # Each attempt has one durable slot; completing it must not erase earlier bills.
    history: list[CaseObservation] = Field(default_factory=list)


def narrative_cases(context: dict, record, *, group: str, language: str = "en") -> list[DecisionCase]:
    """Project the exact evidence already supplied to a saved narrative reviewer.

    No gold labels are inferred from the LLM's verdict or the deterministic
    blocker check. The projection tests citation support, NOT missing-defect recall.
    """
    from novel_to_comic.narrative_review import (
        REVIEW_VERSION, _passage_texts, _review_contexts, review_digest,
    )
    if record.version != REVIEW_VERSION or record.input_sha256 != review_digest(context):
        raise ValueError("saved narrative review is stale; rerun its owning stage before export")
    if any(f.code == "narrative_review_invalid" for f in record.failures):
        raise ValueError("cannot evaluate an incomplete or invalid narrative review")
    windows = list(_review_contexts({**context, "approved_story_instruction": record.instruction}))
    if len(windows) != len(record.verdicts):
        raise ValueError("saved review/window counts differ; rerun its owning stage")
    cases = []
    for index, (window, verdict) in enumerate(zip(windows, record.verdicts, strict=True), 1):
        texts = _passage_texts(window)
        for number, finding in enumerate(verdict.findings, 1):
            complete = bool(finding.passages) and all(
                p.artifact_id in finding.artifact_ids
                and any(p.quote in text for text in texts.get(p.artifact_id, []))
                for p in finding.passages
            )
            cases.append(DecisionCase(
                id=f"{context['phase']}-{index}-{number}", group=group,
                task="citation_support", language=language,
                state={"claim": finding.evidence, "passages": [
                    {"artifact_id": p.artifact_id, "quote": p.quote,
                     "context": texts.get(p.artifact_id, [])}
                    for p in finding.passages
                ]},
                ineligible_reason=None if complete else "unverified_citations",
            ))
    return cases


def export_project(project: Path, phase: str, *, group: str, language: str, candidate: bool = False) -> list[DecisionCase]:
    from novel_to_comic.narrative_review import adaptation_context, planning_context
    from novel_to_comic.target_artifacts import TargetArtifacts

    artifacts = TargetArtifacts(project)
    adaptation = (artifacts.read_failed_adaptation_candidate() if candidate and phase == "adapt"
                  else artifacts.read_adaptation())
    if phase == "adapt":
        context = adaptation_context(artifacts.read_source(), artifacts.read_brief(), adaptation)
    else:
        plan = artifacts.read_plan_review_draft() if candidate else artifacts.read_plan()
        if plan.adaptation_sha256 != adaptation.content_sha256:
            raise ValueError("plan evidence belongs to a different adaptation")
        if candidate:
            pages = plan.pages
        else:
            # BookPlan.pages is a manifest, not ComicPage content. Read the exact
            # revisions it selects, never feed that manifest to a semantic reviewer.
            pages = [artifacts.read_page_revision(p.page_number, p.revision) for p in plan.pages]
            if any(page.content_sha256 != ref.content_sha256 for page, ref in zip(pages, plan.pages, strict=True)):
                raise ValueError("page evidence does not match the selected plan revision")
        context = planning_context(adaptation, pages)
    return narrative_cases(context, artifacts.read_narrative_review(phase), group=group, language=language)


def load_cases(path: Path) -> list[DecisionCase]:
    if path.stat().st_size > 20_000_000:
        raise ValueError("evaluation dataset exceeds 20 MB")
    cases = [DecisionCase.model_validate(strict_json(line))
             for line in path.read_text().splitlines() if line.strip()]
    if not cases or len(cases) > 1000:
        raise ValueError("evaluation requires between 1 and 1000 cases")
    if len({(case.group, case.id) for case in cases}) != len(cases):
        raise ValueError("case IDs must be unique within each group")
    return cases


def save_private(path: Path, text: str) -> None:
    """Atomically replace a private local file; never print source text or keys."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    # Exclusive creation avoids following a pre-existing temporary symlink.
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def latest_observations(cases: list[DecisionCase], run: EvaluationRun) -> dict[tuple[str, str], DecisionObservation]:
    if run.version != REPORT_VERSION:
        raise ValueError("unsupported evaluation report version")
    expected = {(case.group, case.id): content_digest(case_request(case, run.settings)) for case in cases}
    result = {}
    for row in run.history:
        key = (row.group, row.case_id)
        if key not in expected:
            continue
        observation = row.observation
        if (observation.request_sha256 != expected[key]
                or observation.requested_model != run.settings.model
                or observation.rubric_version != RUBRIC_VERSION):
            raise ValueError("saved observation does not match current evidence/model/rubric")
        # Revalidate the dynamic protocol too; replay must not trust edited JSON.
        if observation.reason is None:
            from novel_to_comic.decision_models import question_for
            case = next(case for case in cases if (case.group, case.id) == key)
            if (set(observation.answers) != {"decision"}
                    or observation.resolved_model != run.settings.model
                    or observation.usage is None
                    or set(observation.answers["decision"].probabilities) != set(question_for(case.task).criteria)):
                raise ValueError("saved observation contains an invalid decision protocol")
        result[key] = observation
    return result


def _percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, math.ceil(fraction * len(ordered)) - 1)]


def _metrics(cases: list[DecisionCase], observations: dict, policy: DecisionPolicy) -> dict:
    accepted = labeled_accepted = errors = labeled_predictions = 0
    baseline_compared = baseline_agreed = 0
    brier = log_loss = 0.0
    bins: list[list[tuple[float, int]]] = [[] for _ in range(10)]
    per_label: dict[str, dict[str, int]] = {}
    confusion: dict[str, int] = {}
    for case in cases:
        observed = observations.get((case.group, case.id))
        answer = observed.answers.get("decision") if observed and not observed.reason else None
        chosen = bool(answer and not eligibility_reason(case)
                      and policy.accepts(case.task, answer, model=observed.resolved_model or "", language=case.language))
        accepted += int(chosen)
        if answer and case.baseline_label is not None:
            baseline_compared += 1
            baseline_agreed += int(answer.choice == case.baseline_label)
        if case.expected is not None:
            prediction = answer.choice if answer else "abstain"
            key = f"{case.expected} -> {prediction}"
            confusion[key] = confusion.get(key, 0) + 1
        if answer and case.expected is not None:
            labeled_predictions += 1
            probability = answer.probabilities[answer.choice]
            bins[min(9, int(probability * 10))].append((probability, int(answer.choice == case.expected)))
            brier += sum((p - int(label == case.expected)) ** 2 for label, p in answer.probabilities.items())
            log_loss -= math.log(max(1e-15, answer.probabilities[case.expected]))
            if chosen:
                labeled_accepted += 1
                wrong = int(answer.choice != case.expected)
                errors += wrong
                counts = per_label.setdefault(answer.choice, {"accepted_labeled": 0, "errors": 0})
                counts["accepted_labeled"] += 1
                counts["errors"] += wrong
    ece = sum(abs(sum(p for p, _ in bucket) / len(bucket) - sum(y for _, y in bucket) / len(bucket))
              * len(bucket) for bucket in bins if bucket)
    return {
        "cases": len(cases), "labeled": sum(c.expected is not None for c in cases),
        "accepted": accepted, "coverage": accepted / len(cases) if cases else 0,
        "abstained": len(cases) - accepted, "accepted_labeled": labeled_accepted,
        "accepted_errors": errors,
        "selective_error_rate": errors / labeled_accepted if labeled_accepted else None,
        "zero_error_upper_95_if_iid": (1 - 0.05 ** (1 / labeled_accepted)
                                       if labeled_accepted and errors == 0 else None),
        "multiclass_brier": brier / labeled_predictions if labeled_predictions else None,
        "log_loss": log_loss / labeled_predictions if labeled_predictions else None,
        "top_probability_ece_10_bins": ece / labeled_predictions if labeled_predictions else None,
        "accepted_by_label": per_label, "raw_prediction_confusion": confusion,
        "baseline_compared": baseline_compared,
        "baseline_agreement": baseline_agreed / baseline_compared if baseline_compared else None,
    }


def summarize(cases: list[DecisionCase], run: EvaluationRun, policy: DecisionPolicy) -> dict[str, Any]:
    if policy.model != run.settings.model or policy.rubric_version != RUBRIC_VERSION:
        raise ValueError("evaluation policy model/rubric does not match the saved run")
    observations = latest_observations(cases, run)
    # Rows reference real provider calls; never double-count a reused receipt.
    usages = {row.observation.usage.call_id: row.observation.usage
              for row in run.history if row.observation.usage is not None}
    unknown = sum(row.observation.attempted and (row.observation.usage is None
                  or row.observation.usage.cost_usd is None) for row in run.history)
    attempted = [row.observation for row in run.history if row.observation.attempted]
    incomplete = sum(o.reason == "submission_incomplete" for o in attempted)
    latencies = [o.elapsed_ms for o in attempted if o.reason != "submission_incomplete"]
    return {
        "version": REPORT_VERSION, "model": run.settings.model, "rubric_version": RUBRIC_VERSION,
        "dataset_sha256": content_digest([case.model_dump(mode="json") for case in cases]),
        "policy": policy.model_dump(mode="json"), "metrics": _metrics(cases, observations, policy),
        "by_task": {task: _metrics([c for c in cases if c.task == task], observations, policy)
                    for task in sorted({c.task for c in cases})},
        "by_language": {language: _metrics([c for c in cases if c.language == language], observations, policy)
                        for language in sorted({c.language for c in cases})},
        "attempted_calls": len(attempted), "incomplete_attempts": incomplete, "unknown_cost_attempts": unknown,
        "known_cost_usd": sum(u.cost_usd for u in usages.values() if u.cost_usd is not None),
        "total_cost_usd": None if unknown else sum(u.cost_usd or 0 for u in usages.values()),
        "input_tokens": sum(u.input_tokens for u in usages.values()),
        "output_tokens": sum(u.output_tokens for u in usages.values()),
        "provider_elapsed_ms_p50": _percentile(latencies, 0.5),
        "provider_elapsed_ms_p95": _percentile(latencies, 0.95),
        "note": "Shadow/replay metrics do not change production gates or demonstrate end-to-end savings. "
                "Gold labels must be human-adjudicated; split by book before selecting thresholds.",
    }


def projected_input_cost(cases: list[DecisionCase], settings: TypeSafeSettings) -> float:
    # One token per UTF-8 byte is a deliberately loose planning allowance, NOT
    # a verified Jev token count or a provider-enforced dollar cap.
    return sum(len(canonical_json(case_request(c, settings)).encode("utf-8"))
               for c in cases if not eligibility_reason(c)) * settings.input_usd_per_million / 1e6


async def run_cases(cases: list[DecisionCase], *, client: TypeSafeDecisionClient,
                    output: Path, run: EvaluationRun, max_cost_usd: float = 0.05) -> EvaluationRun:
    if run.settings != client.settings:
        raise ValueError("resume settings differ; use a new output file")
    previous = latest_observations(cases, run)
    if any(row.observation.attempted and (row.observation.usage is None
           or row.observation.usage.cost_usd is None) for row in run.history):
        raise ValueError("prior spend is unknown; inspect it before starting a separate paid experiment")
    known_cost = sum(row.observation.usage.cost_usd for row in run.history
                     if row.observation.usage and row.observation.usage.cost_usd is not None)
    # Replay valid responses, including low-confidence responses. Repeatedly
    # sampling until a convenient confident answer appears would bias the gate.
    # Failed or ambiguous submissions are retained too. Use a separate output
    # file for an explicitly authorized new experiment, never automatic replay.
    pending = [c for c in cases if (c.group, c.id) not in previous]
    if known_cost + projected_input_cost(pending, client.settings) > max_cost_usd:
        raise ValueError("remaining input allowance plus prior recorded cost exceeds run budget")
    policy = DecisionPolicy(model=client.settings.model)  # shadow: always abstain
    history = list(run.history)

    def checkpoint():
        snapshot = EvaluationRun(settings=client.settings, history=list(history))
        save_private(output, canonical_json(snapshot.model_dump(mode="json")) + "\n")

    async def one(case):
        # Write intent before any network await. Cancellation, process death, or
        # a failed completion checkpoint must never make a possible paid call
        # disappear. An incomplete receipt blocks automatic resubmission.
        index = len(history)
        history.append(CaseObservation(case_id=case.id, group=case.group,
            observation=DecisionObservation(
                request_sha256=content_digest(case_request(case, client.settings)),
                requested_model=client.settings.model, attempted=True,
                elapsed_ms=0, reason="submission_incomplete",
            )))
        checkpoint()
        result = await decide_case(case, client=client, policy=policy)
        observation = DecisionObservation.model_validate(result.response_metadata["decision_observation"])
        history[index] = CaseObservation(case_id=case.id, group=case.group, observation=observation)
        checkpoint()
        return observation

    for start in range(0, len(pending), client.settings.concurrency):
        next_cases = pending[start:start + client.settings.concurrency]
        if known_cost + projected_input_cost(next_cases, client.settings) > max_cost_usd:
            break
        batch = await asyncio.gather(*(one(c) for c in next_cases))
        # Stop new submissions after ambiguous spend, auth, provider overload, or
        # protocol failure. Completed concurrent calls remain in the journal.
        known_cost += sum(o.usage.cost_usd for o in batch if o.usage and o.usage.cost_usd is not None)
        if known_cost >= max_cost_usd or any(o.attempted and o.reason is not None for o in batch):
            break
    return EvaluationRun(settings=client.settings, history=history)


@contextmanager
def live_run_lock(output: Path):
    """Exclude simultaneous paid runs sharing one receipt file, across processes."""
    output.parent.mkdir(parents=True, exist_ok=True)
    lock = output.with_name(output.name + ".lock")
    try:
        fd = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as error:
        raise ValueError("evaluation output is locked; inspect the existing run before recovery") from error
    try:
        os.close(fd)
        yield
    finally:
        lock.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    export = commands.add_parser("export", help="Export saved narrative citation evidence; no model calls")
    export.add_argument("project", type=Path)
    export.add_argument("--phase", choices=["adapt", "plan"], required=True)
    export.add_argument("--group", required=True, help="Opaque book ID used for train/test separation")
    export.add_argument("--language", default="en")
    export.add_argument("--candidate", action="store_true", help="Read the saved failed Adapt candidate or Plan review draft")
    export.add_argument("--output", required=True, type=Path)
    live = commands.add_parser("run", help="Dry-run by default; live requests require --allow-paid")
    live.add_argument("cases", type=Path)
    live.add_argument("--output", required=True, type=Path)
    live.add_argument("--settings", type=Path)
    live.add_argument("--allow-paid", action="store_true")
    live.add_argument("--max-cost-usd", type=float, default=0.05,
                      help="Conservative input planning allowance, not a provider-enforced dollar cap")
    replay = commands.add_parser("replay", help="Score a saved run against human labels without provider calls")
    replay.add_argument("cases", type=Path)
    replay.add_argument("observations", type=Path)
    replay.add_argument("--policy", type=Path, required=True)
    replay.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.command == "export":
        if args.output.resolve().is_relative_to(args.project.resolve()):
            parser.error("export outside the project; evaluation must not modify production artifacts")
        cases = export_project(args.project, args.phase, group=args.group, language=args.language, candidate=args.candidate)
        save_private(args.output, "".join(canonical_json(c.model_dump(mode="json")) + "\n" for c in cases))
        print(f"Exported {len(cases)} unlabeled cases. Source text is private; review before sharing.")
        return
    cases = load_cases(args.cases)
    if args.command == "replay":
        if args.output.resolve() in {args.cases.resolve(), args.observations.resolve(), args.policy.resolve()}:
            parser.error("output must not overwrite evaluation inputs")
        run = EvaluationRun.model_validate(strict_json(args.observations.read_text()))
        policy = DecisionPolicy.model_validate(strict_json(args.policy.read_text()))
        save_private(args.output, canonical_json(summarize(cases, run, policy)) + "\n")
        return
    if args.output.resolve() in {args.cases.resolve(), *([args.settings.resolve()] if args.settings else [])}:
        parser.error("output must not overwrite the input dataset")
    settings = TypeSafeSettings.model_validate(strict_json(args.settings.read_text())) if args.settings else TypeSafeSettings()
    if not math.isfinite(args.max_cost_usd) or args.max_cost_usd <= 0:
        parser.error("--max-cost-usd must be positive and finite")
    if settings.output_usd_per_million != 0:
        parser.error("live planning currently supports only the documented free-output pricing")
    allowance = projected_input_cost(cases, settings)
    if allowance > args.max_cost_usd:
        parser.error("conservative input allowance exceeds --max-cost-usd; reduce the dataset")
    if not args.allow_paid:
        print(canonical_json({"dry_run": True, "cases": len(cases), "model": settings.model,
                              "input_cost_allowance_usd": allowance, "provider_calls": 0}))
        return
    if not os.environ.get("TYPESAFE_API_KEY", "").strip():
        parser.error("explicit live runs require TYPESAFE_API_KEY")
    run = (EvaluationRun.model_validate(strict_json(args.output.read_text())) if args.output.exists()
           else EvaluationRun(settings=settings))
    # Validate before constructing a network client; old observations cannot be
    # reused under new inputs even when case IDs happen to match.
    latest_observations(cases, run)

    async def execute():
        async with httpx.AsyncClient(trust_env=False) as http:
            client = TypeSafeDecisionClient(api_key=os.environ["TYPESAFE_API_KEY"], settings=settings, http_client=http)
            return await run_cases(cases, client=client, output=args.output, run=run, max_cost_usd=args.max_cost_usd)

    with live_run_lock(args.output):
        # Re-read under the lock: another completed invocation may have added receipts.
        if args.output.exists():
            run = EvaluationRun.model_validate(strict_json(args.output.read_text()))
        completed = asyncio.run(execute())
    report = summarize(cases, completed, DecisionPolicy(model=settings.model))
    print(canonical_json({k: report[k] for k in ("attempted_calls", "known_cost_usd", "unknown_cost_attempts")}))


if __name__ == "__main__":
    main()
