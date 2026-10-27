"""Revision-scoped editorial decisions, and the prompt section for an author revision.

Author story changes are carried by note_scope, scoped to the beats and pages
they touch; nothing here re-runs Adapt or Plan.

Editorial decisions (keep/reopen) are scoped to the current artifact
fingerprint: an acknowledgment never hides newly recomputed or changed
evidence, because a decision only applies while both the editorial revision
and the individual issue fingerprint still match.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict, Field

from novel_to_comic.models.validation import EditorialIssue

if TYPE_CHECKING:
    from novel_to_comic.models.adaptation import BookAdaptation
    from novel_to_comic.models.page import BookPlan

EditorialDisposition = Literal["kept", "reopened"]

def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


class StoredEditorialDecision(BaseModel):
    """One reviewed disposition, valid only for the evidence it reviewed."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    issue_id: str = Field(min_length=1)
    disposition: EditorialDisposition
    issue_fingerprint: str = Field(min_length=1)
    revision: str = Field(min_length=1)
    updated_at: str = Field(min_length=1)


class StaleRevision(ValueError):
    """The canonical artifacts changed since the preview was compiled."""


class UnknownReference(ValueError):
    """A cited source unit, beat, or page does not exist in current artifacts."""


def editorial_revision(
    adaptation: BookAdaptation | None,
    plan: BookPlan | None,
) -> str:
    """Fingerprint the current Adapt/Plan evidence for decision scoping."""

    adapt_part = (
        f"{adaptation.revision}:{adaptation.content_sha256[:12]}"
        if adaptation is not None
        else "none"
    )
    plan_part = (
        f"{plan.revision}:{plan.content_sha256[:12]}" if plan is not None else "none"
    )
    return f"adapt={adapt_part} plan={plan_part}"


def issue_fingerprint(issue: EditorialIssue) -> str:
    """Hash one issue's evidence so changed findings resurface as unreviewed."""

    payload = "|".join(
        [
            issue.owner_stage,
            issue.code,
            issue.message,
            *issue.evidence,
            *issue.source_unit_ids,
            *issue.artifact_ids,
        ]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]


def collect_editorial_issues(
    adaptation: BookAdaptation | None,
    plan: BookPlan | None,
) -> tuple[EditorialIssue, ...]:
    """Return the current Adapt- and Plan-owned findings in stable order."""

    issues: list[EditorialIssue] = []
    if adaptation is not None:
        issues.extend(adaptation.editorial_issues)
    if plan is not None:
        issues.extend(plan.editorial_issues)
    return tuple(issues)


def resolve_decisions(
    issues: tuple[EditorialIssue, ...],
    stored: tuple[StoredEditorialDecision, ...],
    revision: str,
) -> list[dict]:
    """Merge current issues with revision-scoped dispositions for GET /editorial.

    A stored decision surfaces only while both the editorial revision and the
    individual issue fingerprint still match; anything else renders ``open`` so
    recomputed or reworded evidence is never hidden by an old acknowledgment.
    """

    by_id = {record.issue_id: record for record in stored}
    resolved: list[dict] = []
    for issue in issues:
        record = by_id.get(issue.id)
        if (
            record is not None
            and record.revision == revision
            and record.issue_fingerprint == issue_fingerprint(issue)
        ):
            disposition: str = record.disposition
            updated_at: str | None = record.updated_at
        else:
            disposition = "open"
            updated_at = None
        resolved.append(
            {
                "issue_id": issue.id,
                "owner_stage": issue.owner_stage,
                "code": issue.code,
                "message": issue.message,
                "evidence": list(issue.evidence),
                "source_unit_ids": list(issue.source_unit_ids),
                "artifact_ids": list(issue.artifact_ids),
                "disposition": disposition,
                "updated_at": updated_at,
            }
        )
    return resolved


def story_instruction_section(instruction: str, *, stage: str, fixed_page_map: bool = False) -> str:
    """Format the approved author revision appended to owning-stage prompts."""

    cleaned = (instruction or "").strip()
    if not cleaned:
        return ""
    if stage == "plan" and fixed_page_map:
        guardrails = (
            "The approved page map has already resolved global allocation. Apply "
            "this request through panel composition, staging, and approved appearance "
            "states within each target page. Preserve each page's assigned beat and "
            "lettering IDs exactly; do not move words between pages or change page "
            "count. Earlier instructions to reallocate pages apply to the map pass, "
            "not this detail pass. Never rewrite Adapt's lettering."
        )
    elif stage == "plan":
        guardrails = (
            "Reallocate pages, panels, rhythm, and emphasis to honor this "
            "request. Never rewrite, shorten, reorder, or reassign Adapt's "
            "lettering wording; cite LetteringItem IDs exactly as the "
            "adaptation allocates them. Do not change story content, only its "
            "page allocation."
        )
    else:
        guardrails = (
            "This request may restore previously omitted material, change "
            "dialogue or captions, or adjust emphasis; treat those as "
            "legitimate author revisions, not contradictions. It never "
            "authorizes breaking blocking invariants, dropping approved brief "
            "requirements, or inventing unattested story facts."
        )
    return (
        "\n\nAPPROVED STORY-CHANGE REQUEST (authoritative author revision — "
        f"honor it within all contract rules): {cleaned}\n{guardrails}"
    )


def record_decisions(
    *,
    issues: tuple[EditorialIssue, ...],
    stored: tuple[StoredEditorialDecision, ...],
    revision: str,
    expected_revision: str,
    issue_ids: list[str],
    disposition: str,
) -> tuple[StoredEditorialDecision, ...]:
    """Apply keep/reopen dispositions scoped to the current revision."""

    if expected_revision != revision:
        raise StaleRevision(
            "editorial evidence changed since this view was loaded; "
            "reload and review the current findings"
        )
    if disposition not in ("kept", "reopened"):
        raise ValueError("disposition must be 'kept' or 'reopened'")
    if not issue_ids:
        raise ValueError("at least one issue id is required")
    current_ids = {issue.id for issue in issues}
    unknown = [iid for iid in issue_ids if iid not in current_ids]
    if unknown:
        raise UnknownReference(
            "unknown editorial issue ids (the evidence may have changed): "
            + ", ".join(sorted(unknown))
        )
    fingerprints = {issue.id: issue_fingerprint(issue) for issue in issues}
    now = _utc_now_iso()
    updated = {record.issue_id: record for record in stored}
    for issue_id in issue_ids:
        updated[issue_id] = StoredEditorialDecision(
            issue_id=issue_id,
            disposition=disposition,  # type: ignore[assignment]
            issue_fingerprint=fingerprints[issue_id],
            revision=revision,
            updated_at=now,
        )
    return tuple(updated.values())


__all__ = [
    "StaleRevision",
    "StoredEditorialDecision",
    "UnknownReference",
    "collect_editorial_issues",
    "editorial_revision",
    "issue_fingerprint",
    "record_decisions",
    "resolve_decisions",
    "story_instruction_section",
]
