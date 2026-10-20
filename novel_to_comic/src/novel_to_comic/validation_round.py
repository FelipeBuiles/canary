"""Stage validation rounds: clean-candidate review, repair policy and history.

Adapt's progress-sensitive repair allowance and Plan's independent structural
and narrative allowances intentionally remain separate policies.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from novel_to_comic.models.validation import InvariantFailure, StageValidation, ValidationAttempt
from novel_to_comic.narrative_review import review_narrative, reviewed_validation


async def review_clean_candidate(validation, context, *, generate, ctx, artifacts, model,
                                 instruction="", concurrency=4, reviewer=None):
    """Only clean candidates may spend on review; merge its complete verdict."""
    if validation.invariant_failures:
        return validation
    failures = await (reviewer or review_narrative)(
        context, generate=generate, ctx=ctx, artifacts=artifacts, model=model,
        instruction=instruction, concurrency=concurrency,
    )
    return reviewed_validation(validation, failures, artifacts=artifacts,
                               phase=context["phase"], context=context)


def record_validation_attempt(attempt: int, validation) -> ValidationAttempt:
    return ValidationAttempt(
        attempt=attempt,
        invariant_codes=tuple(f.code for f in validation.invariant_failures),
        editorial_codes=tuple(i.code for i in validation.editorial_issues),
    )


def persist_validation(stage, artifacts, validation, *, attempts, history=()):
    recommendations = tuple(
        evidence for failure in validation.invariant_failures
        if stage == "plan" and failure.code == "target_page_range_conflict"
        for evidence in failure.evidence
    )
    artifacts.write_validation(StageValidation(
        owner_stage=stage, attempts=attempts,
        invariant_failures=validation.invariant_failures,
        editorial_issues=validation.editorial_issues,
        recommendations=recommendations, attempt_history=tuple(history),
    ))


def adapt_repair_allowed(attempt: int, history: Sequence[ValidationAttempt], *,
                         previous_failures: Sequence[InvariantFailure] = (),
                         current_failures: Sequence[InvariantFailure] = ()) -> bool:
    """One ordinary repair, then one for demonstrated progress or new review evidence."""
    if any(f.code == "narrative_review_invalid" for f in current_failures):
        return False
    if attempt < 2:
        return True
    if attempt != 2 or len(history) < 2:
        return False
    current = set(history[-1].invariant_codes)
    previous = set(history[-2].invariant_codes)
    if not current or current == {"narrative_review_invalid"}:
        return False

    def narrative(codes):
        return all(code.startswith("narrative_review_") for code in codes)

    narrative_only = narrative(current)
    if current != previous:
        review_regression = bool(previous) and narrative(previous) and not any(
            code.startswith("narrative_review_") for code in current
        )
        return current < previous or narrative_only or review_regression

    def identities(failures):
        return {(f.code, tuple(sorted(f.artifact_ids))) for f in failures}

    return narrative_only and bool(current_failures) and identities(current_failures) != identities(previous_failures)


@dataclass
class PlanRepairPolicy:
    """One repair per concern kind, including narrative work discovered after structure."""
    narrative_repaired: bool = False
    structure_repaired: bool = False

    @classmethod
    def from_history(cls, history):
        return cls(narrative_repaired=any(
            any(code.startswith("narrative_review_") for code in record.invariant_codes)
            for record in history
        ))

    @staticmethod
    def may_retry(failures, *, allow_mixed_owners=False):
        if any(f.code == "narrative_review_invalid" for f in failures):
            return False
        if allow_mixed_owners:
            return any(f.owner_stage == "plan" for f in failures)
        return bool(failures) and all(f.owner_stage == "plan" for f in failures)

    @staticmethod
    def rejects_response(failures):
        return any(f.owner_stage == "plan" and f.code != "narrative_review_invalid" for f in failures)

    def eligible(self, failures):
        return tuple(
            f for f in failures if f.owner_stage == "plan" and f.code != "narrative_review_invalid"
            and (not self.narrative_repaired if f.code.startswith("narrative_review_")
                 else not self.structure_repaired)
        )

    def repaired(self, failures):
        self.narrative_repaired |= any(f.code.startswith("narrative_review_") for f in failures)
        self.structure_repaired |= any(not f.code.startswith("narrative_review_") for f in failures)
