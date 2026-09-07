"""Non-destructive story-change proposals and revision-scoped editorial decisions.

Story/script changes are never inline edits to Draw and never silent notes.
A preview compiles a persistent, reloadable proposal with truthful bookwide
cascade impact and cost information. Only an explicit apply feeds the approved
instruction into the owning canonical generation (Adapt or Plan) through the
existing StageRuntime/server orchestration — Plan is always constrained to
layout and pacing and can never rewrite Adapt's lettering.

Editorial decisions (keep/reopen) are scoped to the current artifact
fingerprint: an acknowledgment never hides newly recomputed or changed
evidence, because a decision only applies while both the editorial revision
and the individual issue fingerprint still match.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict, Field

from novel_to_comic.models.validation import EditorialIssue

if TYPE_CHECKING:
    from novel_to_comic.models.adaptation import BookAdaptation
    from novel_to_comic.models.page import BookPlan
    from novel_to_comic.models.source import SourceDocument
    from novel_to_comic.target_artifacts import TargetArtifacts

StoryStage = Literal["adapt", "plan"]
EditorialDisposition = Literal["kept", "reopened"]
StoryChangeStatus = Literal["proposed", "applied"]

#: Rejected rather than silently truncated: a shortened instruction would apply
#: a different author intent than the one reviewed in the preview.
MAX_STORY_INSTRUCTION_CHARS = 2000

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


class StoryChangeProposal(BaseModel):
    """A persisted, reloadable story-change request awaiting explicit apply."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1)
    # The editorial fingerprint the preview was compiled against. Apply
    # compares the client's echo and the current fingerprint against this
    # value, so any drift on either side is a stale 409, never a silent run.
    revision: str = Field(min_length=1)
    stage: StoryStage
    instruction: str = Field(min_length=1)
    status: StoryChangeStatus = "proposed"
    affected_page_numbers: tuple[int, ...] = ()
    impact_summary: str = Field(min_length=1)
    source_unit_ids: tuple[str, ...] = ()
    adapted_beat_ids: tuple[str, ...] = ()
    page_numbers: tuple[int, ...] = ()
    estimate_credits: int | None = None
    estimate_warnings: tuple[str, ...] = ()
    created_at: str = Field(min_length=1)


class StoryChangeDirective(BaseModel):
    """One-shot generation input written by apply, consumed by the stage run."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    proposal_id: str = Field(min_length=1)
    stage: StoryStage
    instruction: str = Field(min_length=1)
    created_at: str = Field(min_length=1)


class StaleRevision(ValueError):
    """The canonical artifacts changed since the preview was compiled."""


class StoryDirectiveError(ValueError):
    """A pending story-change directive cannot be honored as written."""


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


def validate_story_instruction(instruction: str) -> str:
    """Return the stripped instruction, rejecting blank or overlong input."""

    cleaned = (instruction or "").strip()
    if not cleaned:
        raise ValueError("story-change instruction must not be blank")
    if len(cleaned) > MAX_STORY_INSTRUCTION_CHARS:
        raise ValueError(
            "story-change instruction exceeds "
            f"{MAX_STORY_INSTRUCTION_CHARS} characters; narrow the request "
            "instead of submitting text that would be truncated"
        )
    return cleaned


def story_instruction_section(instruction: str, *, stage: str) -> str:
    """Format the approved author revision appended to owning-stage prompts."""

    cleaned = (instruction or "").strip()
    if not cleaned:
        return ""
    if stage == "plan":
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


def _dedupe_page_numbers(page_numbers: list[int]) -> tuple[int, ...]:
    seen: set[int] = set()
    ordered: list[int] = []
    for number in page_numbers:
        if number in seen:
            continue
        seen.add(number)
        ordered.append(number)
    return tuple(ordered)


def build_story_change_proposal(
    *,
    instruction: str,
    stage: str,
    source: SourceDocument | None,
    adaptation: BookAdaptation | None,
    plan: BookPlan | None,
    source_unit_ids: tuple[str, ...] = (),
    adapted_beat_ids: tuple[str, ...] = (),
    page_numbers: tuple[int, ...] = (),
    estimate_credits: int | None = None,
) -> StoryChangeProposal:
    """Compile a persistent proposal without generating or mutating anything.

    Raises ValueError for blank/overlong instructions, ValueError for unknown
    immutable source references, UnknownReference for beat/page references that
    may simply be stale, and StaleRevision-style ValueError when the owning
    stage has no canonical input to change yet.
    """

    if stage not in ("adapt", "plan"):
        raise ValueError("story-change stage must be 'adapt' or 'plan'")
    cleaned = validate_story_instruction(instruction)

    if source_unit_ids:
        if source is None:
            raise ValueError("no source artifact exists to cite source units from")
        known_units = {unit.id for unit in source.units}
        unknown = [uid for uid in source_unit_ids if uid not in known_units]
        if unknown:
            raise ValueError(
                "unknown source unit ids: " + ", ".join(sorted(unknown))
            )

    if adapted_beat_ids:
        if adaptation is None:
            raise StaleRevision(
                "no book adaptation exists yet; run Adapt before citing beats"
            )
        known_beats = {beat.id for beat in adaptation.beats}
        unknown = [bid for bid in adapted_beat_ids if bid not in known_beats]
        if unknown:
            raise UnknownReference(
                "unknown adapted beat ids (the adaptation may have changed): "
                + ", ".join(sorted(unknown))
            )

    if stage == "plan" and adaptation is None:
        raise StaleRevision("no book adaptation exists yet; run Adapt first")
    if stage == "adapt" and source is None:
        raise StaleRevision("no source artifact exists yet; import a novel first")

    planned_pages = (
        tuple(entry.page_number for entry in plan.pages) if plan is not None else ()
    )
    requested_pages = _dedupe_page_numbers(list(page_numbers))
    if requested_pages:
        if plan is None:
            raise StaleRevision(
                "no book plan exists yet; run Plan before citing pages"
            )
        known_pages = set(planned_pages)
        unknown = [n for n in requested_pages if n not in known_pages]
        if unknown:
            raise UnknownReference(
                "unknown page numbers (the plan may have changed): "
                + ", ".join(str(n) for n in unknown)
            )
        if any(n < 1 for n in requested_pages):
            raise ValueError("page numbers must be positive")

    if stage == "adapt":
        affected = planned_pages
        if plan is None:
            impact = (
                "Re-running Adapt rebuilds every adapted beat from the updated "
                "instruction. No book plan exists yet, so the page impact is "
                "unknown until Plan runs. Nothing is generated or changed by "
                "this preview."
            )
        else:
            impact = (
                "Re-running Adapt rebuilds every adapted beat from the updated "
                "instruction and re-plans the whole book. All "
                f"{len(planned_pages)} planned page(s) may need regeneration, "
                "and the final page count is unknown until Plan completes. "
                "No pages are changed until you explicitly apply."
            )
    else:
        affected = planned_pages
        scope = (
            "Your focus pages: "
            + ", ".join(str(n) for n in requested_pages)
            + ". Selected pages guide the instruction, not the regeneration boundary. "
            if requested_pages
            else ""
        )
        impact = (
            "Re-running Plan rebuilds the whole book plan from the current "
            "adaptation under your layout instruction. All "
            f"{len(planned_pages)} existing planned page(s) may need regeneration, "
            "and the final page count is unknown until Plan completes. "
            + scope
            + "Lettering stays exactly as Adapt wrote it. "
            "No pages are changed until you explicitly apply."
        )

    warnings = [
        "Applying re-runs the owning stage; the credit estimate is a "
        "projection and actual cost is metered.",
    ]
    if affected:
        warnings.append(
            "Draw regeneration for affected pages is billed separately and is "
            "not included in this estimate."
        )
    else:
        warnings.append(
            "No pages exist yet, so downstream Draw cost cannot be projected."
        )

    return StoryChangeProposal(
        id=f"sc_{uuid.uuid4().hex[:12]}",
        revision=editorial_revision(adaptation, plan),
        stage=stage,  # type: ignore[assignment]
        instruction=cleaned,
        status="proposed",
        affected_page_numbers=affected,
        impact_summary=impact,
        source_unit_ids=tuple(source_unit_ids),
        adapted_beat_ids=tuple(adapted_beat_ids),
        page_numbers=requested_pages,
        estimate_credits=estimate_credits,
        estimate_warnings=tuple(warnings),
        created_at=_utc_now_iso(),
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


def load_story_directive(
    target: TargetArtifacts, stage: str
) -> StoryChangeDirective | None:
    """Return the pending directive after validating it is still appliable.

    The file is never consumed here: a failed generation retains the
    authorized instruction so the user can retry explicitly, and only a
    successful stage run clears it (see the owning stage's ``run``). A
    directive that exists but cannot be parsed, or whose proposal is gone or
    already applied, raises StoryDirectiveError before any paid call runs —
    a billed generation must never silently ignore its approved instruction.
    """

    from novel_to_comic.target_artifacts import ArtifactMissing

    directive = target.peek_story_directive(stage)
    if directive is None or directive.stage != stage:
        return None
    try:
        proposal = target.read_story_change(directive.proposal_id)
    except (ArtifactMissing, ValueError) as exc:
        raise StoryDirectiveError(
            "the approved story change is no longer stored; "
            "preview the change again to recreate its proposal"
        ) from exc
    if proposal.status == "applied":
        raise StoryDirectiveError(
            "the approved story change was already applied; "
            "preview a new change instead of reusing its directive"
        )
    return directive


def mark_story_change_applied(
    target: TargetArtifacts, proposal_id: str
) -> StoryChangeProposal | None:
    """Mark a proposal applied after its owning stage run succeeded."""

    from novel_to_comic.target_artifacts import ArtifactMissing

    try:
        proposal = target.read_story_change(proposal_id)
    except (ArtifactMissing, ValueError, OSError):
        return None
    if proposal.status == "applied":
        return proposal
    applied = proposal.model_copy(update={"status": "applied"})
    target.write_story_change(applied)
    return applied


__all__ = [
    "MAX_STORY_INSTRUCTION_CHARS",
    "StaleRevision",
    "StoredEditorialDecision",
    "StoryChangeDirective",
    "StoryChangeProposal",
    "StoryDirectiveError",
    "UnknownReference",
    "build_story_change_proposal",
    "collect_editorial_issues",
    "editorial_revision",
    "issue_fingerprint",
    "load_story_directive",
    "mark_story_change_applied",
    "record_decisions",
    "resolve_decisions",
    "story_instruction_section",
    "validate_story_instruction",
]
