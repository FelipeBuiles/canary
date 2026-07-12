"""Labs-only paired visual evaluation contracts and report calculations.

The module is deliberately side-effect free.  It describes and analyzes an
experiment, but generation and model evaluation require a separately authorized
caller.  Retained baseline artifacts are the old side of each pair; production
routes never receive a legacy-compiler selector.
"""

from __future__ import annotations

import math
import statistics
from collections import defaultdict
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

VISUAL_EVALUATION_SCHEMA_VERSION = 1
VISUAL_EXPERIMENT_SCHEMA_VERSION = 1
VISUAL_RUBRIC_VERSION = "visual-evaluation-rubric-v1"

# Versioned semantic owners for evaluator prompts and blinded human review forms.
# Scores are 0..1; every score requires observable evidence in the record.
VISUAL_RUBRIC_V1 = {
    "character_identity": "stable immutable facial, body, and identifying features",
    "appearance_state": "requested mutable outfit, anatomy, age, condition, or restoration",
    "location_identity": "stable architecture, geography, and identifying environmental features",
    "location_state": "requested time, weather, damage, occupancy, or restoration",
    "prop_identity": "recurring prop shape, material, markings, and condition",
    "style_consistency": "selected medium, rendering language, palette, and line treatment",
    "composition_adherence": "requested framing, camera, staging, and spatial layout",
    "subject_errors": "missing, merged, duplicated, or extra visible subjects",
    "unwanted_readable_text": "any readable text embedded in generated art",
}


class EvidenceItem(BaseModel):
    kind: str
    detail: str = Field(min_length=1)
    region: dict[str, float] | None = None
    reference_id: str | None = None


class DimensionEvaluation(BaseModel):
    score: float = Field(ge=0.0, le=1.0)
    evidence: list[EvidenceItem] = Field(min_length=1)
    confidence: Literal["low", "medium", "high"] | None = None


class CharacterEvaluation(BaseModel):
    entity_id: str = Field(min_length=1)
    identity: DimensionEvaluation
    appearance_state: DimensionEvaluation


class SubjectErrors(BaseModel):
    missing_entity_ids: list[str] = Field(default_factory=list)
    merged_entity_groups: list[list[str]] = Field(default_factory=list)
    duplicated_entity_ids: list[str] = Field(default_factory=list)
    extra_subject_count: int = Field(default=0, ge=0)
    evidence: list[EvidenceItem]


class EvaluatorIdentity(BaseModel):
    kind: Literal["model", "human"]
    model: str | None = None
    reviewer_id: str | None = None
    blinded: bool = True

    @model_validator(mode="after")
    def require_attribution(self) -> EvaluatorIdentity:
        if self.kind == "model" and not self.model:
            raise ValueError("model evaluator requires model identity")
        if self.kind == "human" and not self.reviewer_id:
            raise ValueError("human evaluator requires reviewer_id")
        return self


class VisualEvaluationRecord(BaseModel):
    """One attributable evaluation of one generated or retained artifact."""

    model_config = ConfigDict(extra="forbid")

    schema_version: int = VISUAL_EVALUATION_SCHEMA_VERSION
    scenario_id: str = Field(min_length=1)
    route: str = Field(min_length=1)
    compiler_version: str = Field(min_length=1)
    wire_version: int = Field(ge=1)
    execution_fingerprint: str = Field(min_length=1)
    selected_references: list[dict[str, Any]]
    dropped_references: list[dict[str, Any]]
    rubric_version: str = VISUAL_RUBRIC_VERSION
    evaluator: EvaluatorIdentity
    characters: dict[str, CharacterEvaluation] = Field(min_length=1)
    location_identity: DimensionEvaluation
    location_state: DimensionEvaluation
    prop_identity: DimensionEvaluation
    style_consistency: DimensionEvaluation
    composition_adherence: DimensionEvaluation
    subject_errors: SubjectErrors
    unwanted_readable_text: bool
    text_evidence: list[EvidenceItem]
    reviewer_notes: list[str] = Field(default_factory=list)
    cost_usd: float = Field(ge=0.0)
    latency_ms: int = Field(ge=0)

    @model_validator(mode="after")
    def character_keys_match_entities(self) -> VisualEvaluationRecord:
        mismatched = [key for key, value in self.characters.items() if key != value.entity_id]
        if mismatched:
            raise ValueError("character evaluations must be keyed by entity_id")
        if self.unwanted_readable_text and not self.text_evidence:
            raise ValueError("readable text requires structured evidence")
        return self


class ExperimentArtifact(BaseModel):
    scenario_id: str = Field(min_length=1)
    route: str = Field(min_length=1)
    artifact_path: str | None
    request_provenance: dict[str, Any]
    status: Literal["ok", "missing", "failed"]
    cost_usd: float = Field(ge=0.0)
    latency_ms: int | None = Field(default=None, ge=0)
    failure: dict[str, Any] | None = None

    @model_validator(mode="after")
    def validate_outcome(self) -> ExperimentArtifact:
        if self.status == "ok" and not self.artifact_path:
            raise ValueError("successful artifact requires artifact_path")
        if self.status == "failed" and not self.failure:
            raise ValueError("failed artifact requires failure evidence")
        return self


class PairedScenarioRecord(BaseModel):
    schema_version: int = VISUAL_EXPERIMENT_SCHEMA_VERSION
    pair_id: str = Field(min_length=1)
    failure_class: str = Field(min_length=1)
    baseline: ExperimentArtifact
    candidate: ExperimentArtifact
    baseline_evaluation: VisualEvaluationRecord | None = None
    candidate_evaluation: VisualEvaluationRecord | None = None
    reviewer_notes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def matching_pair_identity(self) -> PairedScenarioRecord:
        if self.baseline.scenario_id != self.candidate.scenario_id:
            raise ValueError("paired artifacts must have matching scenario metadata")
        if self.baseline.route != self.candidate.route:
            raise ValueError("paired artifacts must have matching route metadata")
        for evaluation in (self.baseline_evaluation, self.candidate_evaluation):
            if evaluation is None:
                continue
            if evaluation.scenario_id != self.baseline.scenario_id:
                raise ValueError("evaluation scenario metadata does not match pair")
            if evaluation.route != self.baseline.route:
                raise ValueError("evaluation route metadata does not match pair")
        return self


class ExperimentScenario(BaseModel):
    scenario_id: str
    failure_class: str
    route: str = "draw"


class ExperimentCostEstimate(BaseModel):
    prompt_calls: int
    image_calls: int
    evaluator_calls: int
    estimated_cost_usd_low: float
    estimated_cost_usd_high: float
    estimated_credits_low: int
    estimated_credits_high: int


class VisualExperimentProposal(BaseModel):
    schema_version: int = VISUAL_EXPERIMENT_SCHEMA_VERSION
    scenarios: list[ExperimentScenario]
    repeats: int = Field(ge=1)
    image_cost_usd_by_route: dict[str, tuple[float, float]]
    evaluator_cost_usd_range: tuple[float, float]
    credits_per_usd: float = Field(default=100.0, gt=0)
    provider_nondeterminism_limit: str
    decision_rule: str
    stopping_condition: str
    paid_calls_authorized: bool = False

    @classmethod
    def balanced_default(
        cls,
        *,
        image_cost_usd_by_route: dict[str, tuple[float, float]],
        evaluator_cost_usd_range: tuple[float, float],
        repeats: int = 2,
    ) -> VisualExperimentProposal:
        classes = (
            ("canonical", "canonical"),
            ("minor-state", "minor_character_state"),
            ("significant-state", "significant_character_state"),
            ("restored-state", "restored_character_state"),
            ("location-state", "location_state"),
            ("constrained-refs", "constrained_references"),
            ("recurring-prop", "prop_identity"),
            ("multi-subject", "multi_subject"),
        )
        return cls(
            scenarios=[ExperimentScenario(scenario_id=i, failure_class=c) for i, c in classes],
            repeats=repeats,
            image_cost_usd_by_route=image_cost_usd_by_route,
            evaluator_cost_usd_range=evaluator_cost_usd_range,
            provider_nondeterminism_limit=(
                "Pairs control request provenance, not pixels; provider sampling may vary. "
                "Use repeats and never claim deterministic image equality."
            ),
            decision_rule=(
                "Accept only if canonical identity/style/completeness/text mean deltas exceed "
                "the pre-registered material-regression floor, alternate-state correctness "
                "improves, and no route has a systematic failure."
            ),
            stopping_condition=(
                "Stop after the planned balanced repeats, or earlier for any safety/billing "
                "failure or two failures of the same route/class; do not add samples post hoc."
            ),
        )

    def estimate(self) -> ExperimentCostEstimate:
        """Pure estimate: reads pricing inputs and performs no generation/evaluation."""
        image_calls = len(self.scenarios) * self.repeats
        image_low = image_high = 0.0
        for scenario in self.scenarios:
            low, high = self.image_cost_usd_by_route[scenario.route]
            image_low += low * self.repeats
            image_high += high * self.repeats
        # Evaluate both retained baseline and candidate for every generated candidate.
        evaluator_calls = image_calls * 2
        eval_low, eval_high = self.evaluator_cost_usd_range
        low = image_low + evaluator_calls * eval_low
        high = image_high + evaluator_calls * eval_high
        return ExperimentCostEstimate(
            prompt_calls=0,
            image_calls=image_calls,
            evaluator_calls=evaluator_calls,
            estimated_cost_usd_low=low,
            estimated_cost_usd_high=high,
            estimated_credits_low=math.ceil(low * self.credits_per_usd),
            estimated_credits_high=math.ceil(high * self.credits_per_usd),
        )


class LabsVisualExperimentRecord(BaseModel):
    """Versioned, Labs-only durable experiment state."""

    model_config = ConfigDict(extra="forbid")

    schema_version: int = VISUAL_EXPERIMENT_SCHEMA_VERSION
    experiment_id: str = Field(min_length=1)
    authorization_status: Literal["pending", "authorized", "completed"]
    proposal: VisualExperimentProposal
    pairs: list[PairedScenarioRecord]

    @model_validator(mode="after")
    def authorization_matches_proposal(self) -> LabsVisualExperimentRecord:
        if self.authorization_status == "pending" and self.proposal.paid_calls_authorized:
            raise ValueError("pending experiment cannot claim paid-call authorization")
        if self.authorization_status != "pending" and not self.proposal.paid_calls_authorized:
            raise ValueError("authorized experiment requires explicit proposal authorization")
        return self


class DimensionUncertainty(BaseModel):
    sample_size: int
    mean_delta: float | None
    baseline_stddev: float | None
    material_regression_floor: float | None
    standard_error: float | None
    confidence_interval_95: tuple[float, float] | None


class RouteReport(BaseModel):
    total_pairs: int
    complete_pairs: int
    failed_pairs: int
    missing_pairs: int
    mean_dimension_deltas: dict[str, float | None]
    dimension_uncertainty: dict[str, DimensionUncertainty]
    uncertainty: str


class PairedVisualReport(BaseModel):
    schema_version: int = VISUAL_EXPERIMENT_SCHEMA_VERSION
    total_pairs: int
    complete_pairs: int
    failed_pairs: int
    missing_pairs: int
    by_route: dict[str, RouteReport]
    by_failure_class: dict[str, RouteReport]
    material_regressions: list[str]
    alternate_state_improvements: dict[str, float | None]
    systematic_failures: list[str]
    decision: Literal["accepted", "rejected", "pending"]


def _evaluation_dimensions(record: VisualEvaluationRecord) -> dict[str, float]:
    identities = [item.identity.score for item in record.characters.values()]
    states = [item.appearance_state.score for item in record.characters.values()]
    return {
        "character_identity": sum(identities) / len(identities),
        "appearance_state": sum(states) / len(states),
        "location_identity": record.location_identity.score,
        "location_state": record.location_state.score,
        "prop_identity": record.prop_identity.score,
        "style_consistency": record.style_consistency.score,
        "composition_adherence": record.composition_adherence.score,
        "subject_error_free": float(
            not record.subject_errors.missing_entity_ids
            and not record.subject_errors.merged_entity_groups
            and not record.subject_errors.duplicated_entity_ids
            and record.subject_errors.extra_subject_count == 0
        ),
        "unwanted_text_free": float(not record.unwanted_readable_text),
    }


def _route_report(pairs: list[PairedScenarioRecord]) -> RouteReport:
    deltas: dict[str, list[float]] = defaultdict(list)
    baselines: dict[str, list[float]] = defaultdict(list)
    failed = missing = complete = 0
    for pair in pairs:
        statuses = {pair.baseline.status, pair.candidate.status}
        if "failed" in statuses:
            failed += 1
            continue
        if "missing" in statuses or not pair.baseline_evaluation or not pair.candidate_evaluation:
            missing += 1
            continue
        complete += 1
        baseline = _evaluation_dimensions(pair.baseline_evaluation)
        candidate = _evaluation_dimensions(pair.candidate_evaluation)
        for name in baseline:
            deltas[name].append(candidate[name] - baseline[name])
            baselines[name].append(baseline[name])
    names = (
        "character_identity", "appearance_state", "location_identity", "location_state",
        "prop_identity", "style_consistency", "composition_adherence",
        "subject_error_free", "unwanted_text_free",
    )
    means = {name: (sum(deltas[name]) / len(deltas[name]) if deltas[name] else None) for name in names}
    uncertainty = {}
    for name in names:
        values = deltas[name]
        baseline_values = baselines[name]
        baseline_stddev = statistics.stdev(baseline_values) if len(baseline_values) >= 2 else None
        standard_error = (
            statistics.stdev(values) / math.sqrt(len(values)) if len(values) >= 2 else None
        )
        mean = means[name]
        uncertainty[name] = DimensionUncertainty(
            sample_size=len(values),
            mean_delta=mean,
            baseline_stddev=baseline_stddev,
            material_regression_floor=(
                max(0.10, baseline_stddev) if baseline_stddev is not None else 0.10
            ) if values else None,
            standard_error=standard_error,
            confidence_interval_95=(
                (mean - 1.96 * standard_error, mean + 1.96 * standard_error)
                if mean is not None and standard_error is not None else None
            ),
        )
    return RouteReport(
        total_pairs=len(pairs), complete_pairs=complete, failed_pairs=failed,
        missing_pairs=missing, mean_dimension_deltas=means,
        dimension_uncertainty=uncertainty,
        uncertainty=(
            f"descriptive paired means from n={complete}; no inferential claim below 8 complete pairs"
        ),
    )


def build_paired_report(pairs: list[PairedScenarioRecord]) -> PairedVisualReport:
    grouped: dict[str, list[PairedScenarioRecord]] = defaultdict(list)
    by_class_pairs: dict[str, list[PairedScenarioRecord]] = defaultdict(list)
    for pair in pairs:
        grouped[pair.baseline.route].append(pair)
        by_class_pairs[pair.failure_class].append(pair)
    by_route = {route: _route_report(items) for route, items in grouped.items()}
    by_failure_class = {
        failure_class: _route_report(items)
        for failure_class, items in by_class_pairs.items()
    }
    complete = sum(item.complete_pairs for item in by_route.values())
    failed = sum(item.failed_pairs for item in by_route.values())
    missing = sum(item.missing_pairs for item in by_route.values())
    canonical_dimensions = (
        "character_identity", "location_identity", "style_consistency",
        "subject_error_free", "unwanted_text_free",
    )
    material_regressions = []
    for dimension in canonical_dimensions:
        values = [
            report.dimension_uncertainty[dimension]
            for report in by_route.values()
            if report.dimension_uncertainty[dimension].sample_size
        ]
        if any(
            item.mean_delta is not None
            and item.material_regression_floor is not None
            and item.mean_delta < -item.material_regression_floor
            for item in values
        ):
            material_regressions.append(dimension)

    char_classes = {
        "minor_character_state", "significant_character_state", "restored_character_state",
    }
    char_values = [
        by_failure_class[name].mean_dimension_deltas["appearance_state"]
        for name in char_classes if name in by_failure_class
    ]
    char_values = [value for value in char_values if value is not None]
    location_value = (
        by_failure_class["location_state"].mean_dimension_deltas["location_state"]
        if "location_state" in by_failure_class else None
    )
    alternate_improvements = {
        "appearance_state": sum(char_values) / len(char_values) if char_values else None,
        "location_state": location_value,
    }

    systematic_failures = []
    for route, route_pairs in grouped.items():
        for failure_class, class_pairs in by_class_pairs.items():
            relevant = [pair for pair in class_pairs if pair.baseline.route == route]
            failed_count = sum(pair.candidate.status == "failed" for pair in relevant)
            if relevant and failed_count >= 2 and failed_count / len(route_pairs) >= 0.25:
                systematic_failures.append(f"{route}:{failure_class}")

    planned_classes = {
        "canonical", "minor_character_state", "significant_character_state",
        "restored_character_state", "location_state", "constrained_references",
        "prop_identity", "multi_subject",
    }
    reject = bool(material_regressions or systematic_failures)
    enough_evidence = (
        complete >= 8 and not failed and not missing
        and planned_classes.issubset(by_failure_class)
        and alternate_improvements["appearance_state"] is not None
        and alternate_improvements["appearance_state"] >= 0.15
        and alternate_improvements["location_state"] is not None
        and alternate_improvements["location_state"] >= 0.15
    )
    decision: Literal["accepted", "rejected", "pending"] = (
        "rejected" if reject else "accepted" if enough_evidence else "pending"
    )
    return PairedVisualReport(
        total_pairs=len(pairs), complete_pairs=complete, failed_pairs=failed,
        missing_pairs=missing, by_route=by_route, by_failure_class=by_failure_class,
        material_regressions=material_regressions,
        alternate_state_improvements=alternate_improvements,
        systematic_failures=systematic_failures,
        decision=decision,
    )


def validate_labs_comparison_mode(*, surface: str, compiler: str) -> None:
    if compiler == "retained_baseline" and surface != "labs":
        raise ValueError("retained baseline comparison is available only in Labs")
