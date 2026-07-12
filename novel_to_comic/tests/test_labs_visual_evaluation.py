from __future__ import annotations

from copy import deepcopy

import pytest
from pydantic import ValidationError

from novel_to_comic.labs.visual_evaluation import (
    CharacterEvaluation,
    DimensionEvaluation,
    ExperimentArtifact,
    LabsVisualExperimentRecord,
    PairedScenarioRecord,
    SubjectErrors,
    VisualEvaluationRecord,
    VisualExperimentProposal,
    build_paired_report,
    validate_labs_comparison_mode,
)
from novel_to_comic.labs import storage


def _dimension(score: float = 0.8) -> DimensionEvaluation:
    return DimensionEvaluation(
        score=score,
        evidence=[{"kind": "visual_observation", "detail": "observable detail"}],
    )


def _evaluation(*, scenario_id: str = "minor-state", route: str = "draw") -> VisualEvaluationRecord:
    return VisualEvaluationRecord(
        scenario_id=scenario_id,
        route=route,
        compiler_version="canonical-prompt-ir-v1",
        wire_version=1,
        execution_fingerprint="a" * 64,
        selected_references=[{"role": "character_identity", "entity_id": "char_b"}],
        dropped_references=[{"reason": "provider_cap", "entity_id": "prop_a"}],
        rubric_version="visual-evaluation-rubric-v1",
        evaluator={"kind": "human", "reviewer_id": "reviewer-1", "blinded": True},
        characters={
            "char_b": CharacterEvaluation(
                entity_id="char_b",
                identity=_dimension(0.9),
                appearance_state=_dimension(0.7),
            ),
            "char_a": CharacterEvaluation(
                entity_id="char_a",
                identity=_dimension(0.8),
                appearance_state=_dimension(0.6),
            ),
        },
        location_identity=_dimension(),
        location_state=_dimension(),
        prop_identity=_dimension(),
        style_consistency=_dimension(),
        composition_adherence=_dimension(),
        subject_errors=SubjectErrors(evidence=[]),
        unwanted_readable_text=False,
        text_evidence=[],
        cost_usd=0.02,
        latency_ms=1200,
    )


def _artifact(*, scenario_id: str = "minor-state", route: str = "draw", status: str = "ok") -> ExperimentArtifact:
    return ExperimentArtifact(
        scenario_id=scenario_id,
        route=route,
        artifact_path=f"saved/{scenario_id}.png" if status == "ok" else None,
        request_provenance={"execution_fingerprint": "a" * 64},
        status=status,
        cost_usd=0.02 if status == "ok" else 0.0,
        latency_ms=1200 if status == "ok" else None,
        failure={"type": "generation_failed"} if status == "failed" else None,
    )


def test_visual_evaluation_rejects_aggregate_only_and_requires_identity():
    payload = _evaluation().model_dump()
    payload.pop("scenario_id")
    with pytest.raises(ValidationError):
        VisualEvaluationRecord.model_validate(payload)

    payload = _evaluation().model_dump()
    payload["characters"] = {}
    payload["aggregate_score"] = 0.9
    with pytest.raises(ValidationError):
        VisualEvaluationRecord.model_validate(payload)


def test_character_scores_are_keyed_by_entity_not_subject_order():
    record = _evaluation()
    reordered = VisualEvaluationRecord.model_validate(
        {**record.model_dump(), "characters": dict(reversed(record.characters.items()))}
    )
    assert reordered.characters["char_a"].identity.score == 0.8
    assert reordered.characters["char_b"].identity.score == 0.9


def test_identity_state_and_other_dimensions_remain_separate_with_evidence():
    record = _evaluation()
    assert record.characters["char_a"].identity != record.characters["char_a"].appearance_state
    assert record.location_identity is not record.location_state
    assert record.prop_identity.evidence
    assert record.composition_adherence.evidence
    assert record.rubric_version == "visual-evaluation-rubric-v1"


def test_pairing_rejects_mismatched_scenario_or_route():
    with pytest.raises(ValueError, match="scenario"):
        PairedScenarioRecord(
            pair_id="pair-1",
            failure_class="minor_character_state",
            baseline=_artifact(),
            candidate=_artifact(scenario_id="canonical"),
        )
    with pytest.raises(ValueError, match="route"):
        PairedScenarioRecord(
            pair_id="pair-1",
            failure_class="minor_character_state",
            baseline=_artifact(),
            candidate=_artifact(route="labs-non-panel"),
        )


def test_cost_estimate_dry_run_is_pure_and_documents_stopping_rule():
    proposal = VisualExperimentProposal.balanced_default(
        image_cost_usd_by_route={"draw": (0.02, 0.04)},
        evaluator_cost_usd_range=(0.001, 0.003),
        repeats=2,
    )
    before = deepcopy(proposal.model_dump())
    estimate = proposal.estimate()
    assert proposal.model_dump() == before
    assert estimate.prompt_calls == 0
    assert estimate.image_calls == len(proposal.scenarios) * 2
    assert estimate.evaluator_calls == estimate.image_calls * 2
    assert estimate.estimated_cost_usd_high >= estimate.estimated_cost_usd_low > 0
    assert proposal.decision_rule and proposal.stopping_condition


def test_legacy_compiler_comparison_is_labs_only():
    validate_labs_comparison_mode(surface="labs", compiler="retained_baseline")
    with pytest.raises(ValueError, match="Labs"):
        validate_labs_comparison_mode(surface="production", compiler="retained_baseline")


def test_report_counts_failed_and_missing_pairs_instead_of_excluding_them():
    complete = PairedScenarioRecord(
        pair_id="pair-ok",
        failure_class="minor_character_state",
        baseline=_artifact(),
        candidate=_artifact(),
        baseline_evaluation=_evaluation(),
        candidate_evaluation=_evaluation(),
    )
    failed = PairedScenarioRecord(
        pair_id="pair-failed",
        failure_class="prop_identity",
        baseline=_artifact(scenario_id="prop"),
        candidate=_artifact(scenario_id="prop", status="failed"),
    )
    report = build_paired_report([complete, failed])
    assert report.total_pairs == 2
    assert report.complete_pairs == 1
    assert report.failed_pairs == 1
    assert report.by_route["draw"].total_pairs == 2
    assert report.by_route["draw"].complete_pairs == 1
    assert report.by_failure_class["prop_identity"].failed_pairs == 1
    assert report.decision == "pending"


def test_experiment_storage_round_trips_auditable_contracts(tmp_path):
    pair = PairedScenarioRecord(
        pair_id="pair-1",
        failure_class="minor_character_state",
        baseline=_artifact(),
        candidate=_artifact(),
        baseline_evaluation=_evaluation(),
        candidate_evaluation=_evaluation(),
        reviewer_notes=["blinded review agrees"],
    )
    report = build_paired_report([pair])
    experiment = LabsVisualExperimentRecord(
        experiment_id="experiment-1",
        authorization_status="pending",
        proposal=VisualExperimentProposal.balanced_default(
            image_cost_usd_by_route={"draw": (0.02, 0.04)},
            evaluator_cost_usd_range=(0.001, 0.003),
        ),
        pairs=[pair],
    )
    storage.write_visual_experiment(
        tmp_path,
        experiment,
    )
    storage.write_visual_report(tmp_path, "experiment-1", report.model_dump(mode="json"))

    saved = storage.read_visual_experiment(tmp_path, "experiment-1")
    assert saved.pairs[0].baseline.request_provenance
    assert saved.pairs[0].reviewer_notes == ["blinded review agrees"]
    assert storage.read_visual_report(tmp_path, "experiment-1")["total_pairs"] == 1


def test_report_executes_materiality_uncertainty_and_acceptance_rules():
    pairs = []
    failure_classes = [
        "canonical", "minor_character_state", "significant_character_state",
        "restored_character_state", "location_state", "constrained_references",
        "prop_identity", "multi_subject",
    ]
    for index, failure_class in enumerate(failure_classes):
        baseline = _evaluation(scenario_id=f"scenario-{index}")
        candidate = baseline.model_copy(deep=True)
        if "character_state" in failure_class or failure_class == "restored_character_state":
            for character in candidate.characters.values():
                character.appearance_state.score = min(1.0, character.appearance_state.score + 0.2)
        if failure_class == "location_state":
            candidate.location_state.score = min(1.0, candidate.location_state.score + 0.2)
        pairs.append(PairedScenarioRecord(
            pair_id=f"pair-{index}",
            failure_class=failure_class,
            baseline=_artifact(scenario_id=f"scenario-{index}"),
            candidate=_artifact(scenario_id=f"scenario-{index}"),
            baseline_evaluation=baseline,
            candidate_evaluation=candidate,
        ))

    report = build_paired_report(pairs)
    assert report.decision == "accepted"
    assert report.by_route["draw"].dimension_uncertainty["character_identity"].sample_size == 8
    assert report.material_regressions == []

    regressed = pairs[0].candidate_evaluation
    for character in regressed.characters.values():
        character.identity.score = 0.0
    rejected = build_paired_report(pairs)
    assert rejected.decision == "rejected"
    assert "character_identity" in rejected.material_regressions


def test_systematic_failure_uses_all_attempted_pairs_on_route_as_denominator():
    pairs = []
    for index in range(16):
        failure_class = "prop_identity" if index < 2 else "canonical"
        status = "failed" if index < 2 else "ok"
        pairs.append(PairedScenarioRecord(
            pair_id=f"pair-{index}",
            failure_class=failure_class,
            baseline=_artifact(scenario_id=f"scenario-{index}"),
            candidate=_artifact(scenario_id=f"scenario-{index}", status=status),
        ))
    assert build_paired_report(pairs).systematic_failures == []

    for index in (2, 3):
        pairs[index].failure_class = "prop_identity"
        pairs[index].candidate = _artifact(scenario_id=f"scenario-{index}", status="failed")
    assert build_paired_report(pairs).systematic_failures == ["draw:prop_identity"]
