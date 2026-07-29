"""Stage-owned validation vocabulary without synthetic quality scores."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


StageName = Literal["extract", "brief", "style", "cast", "adapt", "plan", "draw", "finish"]


class _ValidationResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1)
    owner_stage: StageName
    code: str = Field(min_length=1)
    message: str = Field(min_length=1)
    source_unit_ids: tuple[str, ...] = ()
    artifact_ids: tuple[str, ...] = ()
    evidence: tuple[str, ...] = Field(min_length=1)


class InvariantFailure(_ValidationResult):
    """A provable contract violation that cannot be accepted."""

    kind: Literal["invariant_failure"] = "invariant_failure"
    blocking: Literal[True] = True


class EditorialIssue(_ValidationResult):
    """An evidence-backed concern that remains a human judgment."""

    kind: Literal["editorial_issue"] = "editorial_issue"
    blocking: Literal[False] = False


class ValidationAttempt(BaseModel):
    """What one repair round actually failed on.

    Only the final verdict used to be persisted, so a stage that repaired and
    then passed left no record of what triggered the repair — which is exactly
    the information needed to decide whether a check should be computed rather
    than generated.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    attempt: int = Field(ge=1)
    invariant_codes: tuple[str, ...] = ()
    editorial_codes: tuple[str, ...] = ()


class StageValidation(BaseModel):
    """One stage's own verdict on its artifact, persisted for review.

    An invariant failure that only ever exists as a raised exception reaches the
    user as a stage error string: the evidence, the cited IDs, and any
    recommendation are lost. Stages that block therefore persist this first.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    owner_stage: StageName
    attempts: int = Field(default=1, ge=1)
    invariant_failures: tuple[InvariantFailure, ...] = ()
    editorial_issues: tuple[EditorialIssue, ...] = ()
    recommendations: tuple[str, ...] = ()
    attempt_history: tuple[ValidationAttempt, ...] = ()

    @property
    def blocked(self) -> bool:
        return bool(self.invariant_failures)
