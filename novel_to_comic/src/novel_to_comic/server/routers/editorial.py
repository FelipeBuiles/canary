"""Editorial findings, on-demand source excerpts, and story-change workflow.

Preview compiles a persistent, reloadable proposal with truthful impact and
cost information and never generates or mutates canonical artifacts. Only an
explicit apply writes a one-shot directive and re-runs the owning stage
through the standard pipeline orchestration (credit authorization, busy and
stale guards, StageRuntime execution).
"""

from __future__ import annotations


from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from novel_to_comic import editorial
from novel_to_comic.briefing import require_approved_brief
from novel_to_comic.target_artifacts import (
    ArtifactInvalid,
    ArtifactMissing,
    TargetArtifacts,
)
from ..auth import get_current_user
from ..codex_admission import admit_stage_action
from ..credits import (
    assert_sufficient_credits,
    estimate_stage_credit_cost,
    estimate_stage_credit_reservation,
)
from ..db import get_db
from ..deps import get_project, project_key
from ..ratelimit import cost_limit, limiter
from .pipeline import STAGE_AUTO_CHAIN, _start_stage


router = APIRouter()


class DecisionBody(BaseModel):
    expected_revision: str = Field(min_length=1)
    issue_ids: list[str] = Field(min_length=1)
    disposition: Literal["kept", "reopened"]


class StoryChangePreviewBody(BaseModel):
    instruction: str = Field(min_length=1)
    stage: Literal["adapt", "plan"]
    source_unit_ids: list[str] = Field(default_factory=list)
    adapted_beat_ids: list[str] = Field(default_factory=list)
    page_numbers: list[int] = Field(default_factory=list)


class StoryChangeApplyBody(BaseModel):
    expected_revision: str = Field(min_length=1)


def _not_found(exc: ArtifactMissing) -> HTTPException:
    return HTTPException(404, str(exc))


def _load_evidence(project_dir):
    """Return (source, adaptation, plan), with missing artifacts as None."""

    target = TargetArtifacts(project_dir)
    try:
        source = target.read_source()
    except ArtifactMissing:
        source = None
    try:
        adaptation = target.read_adaptation()
    except ArtifactMissing:
        adaptation = None
    try:
        plan = target.read_plan()
    except ArtifactMissing:
        plan = None
    return source, adaptation, plan


def _unreadable(exc: ArtifactInvalid, *, revision: str) -> HTTPException:
    """Map a corrupt editorial file to a recoverable 409, never a 500.

    Canonical story artifacts are untouched by these files, so recovery is
    always: re-preview the story change (or remove the named file to reset
    acknowledged findings) and continue.
    """

    if exc.name == "editorial_decisions":
        recovery = (
            "Remove editorial/decisions.json to reset acknowledged findings; "
            "current evidence resurfaces as open."
        )
    else:
        recovery = (
            f"Remove {exc.path.name} or re-preview the story change to "
            "recreate its proposal."
        )
    return HTTPException(
        409,
        {
            "detail": (
                f"Stored {exc.name.replace('_', ' ')} is unreadable. "
                "Canonical story artifacts are unaffected. " + recovery
            ),
            "file": exc.path.name,
            "revision": revision,
        },
    )


def _editorial_body(project_dir) -> dict:
    target = TargetArtifacts(project_dir)
    _source, adaptation, plan = _load_evidence(project_dir)
    revision = editorial.editorial_revision(adaptation, plan)
    issues = editorial.collect_editorial_issues(adaptation, plan)
    try:
        stored = target.read_editorial_decisions()
        proposals = target.list_story_changes()
    except ArtifactInvalid as exc:
        raise _unreadable(exc, revision=revision) from exc
    return {
        "revision": revision,
        "decisions": editorial.resolve_decisions(issues, stored, revision),
        "story_changes": [
            proposal.model_dump(mode="json") for proposal in proposals
        ],
    }


@router.get("/editorial")
def get_editorial(project=Depends(get_project)):
    project_dir, _config, _state = project
    return _editorial_body(project_dir)


@router.get("/editorial/source")
def get_editorial_source(
    ids: str = Query(...),
    project=Depends(get_project),
):
    project_dir, _config, _state = project
    wanted = [part.strip() for part in (ids or "").split(",") if part.strip()]
    if not wanted:
        raise HTTPException(400, "at least one source unit id is required")
    try:
        source = TargetArtifacts(project_dir).read_source()
    except ArtifactMissing as exc:
        raise _not_found(exc) from exc
    by_id = {unit.id: unit for unit in source.units}
    unknown = [uid for uid in wanted if uid not in by_id]
    if unknown:
        raise HTTPException(
            404, "unknown source unit ids: " + ", ".join(sorted(unknown))
        )
    return {"units": [{"id": uid, "text": by_id[uid].text} for uid in wanted]}


@router.post("/editorial/decisions", openapi_extra={'x-canary-action': {'spends': False, 'dispatches': False}})
def post_editorial_decisions(body: DecisionBody, project=Depends(get_project)):
    project_dir, _config, _state = project
    target = TargetArtifacts(project_dir)
    _source, adaptation, plan = _load_evidence(project_dir)
    revision = editorial.editorial_revision(adaptation, plan)
    issues = editorial.collect_editorial_issues(adaptation, plan)
    try:
        updated = editorial.record_decisions(
            issues=issues,
            stored=target.read_editorial_decisions(),
            revision=revision,
            expected_revision=body.expected_revision,
            issue_ids=body.issue_ids,
            disposition=body.disposition,
        )
    except editorial.StaleRevision as exc:
        raise HTTPException(
            409, {"detail": str(exc), "revision": revision}
        ) from exc
    except editorial.UnknownReference as exc:
        raise HTTPException(
            404, {"detail": str(exc), "revision": revision}
        ) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    target.write_editorial_decisions(updated)
    return _editorial_body(project_dir)




def _preview_estimate_credits(config, project_dir, state, stage: str) -> int:
    """Project the unbuffered chain cost using the existing stage estimates."""

    admit_stage_action(config, stage)
    chain = [stage, *STAGE_AUTO_CHAIN.get(stage, ())]
    try:
        return sum(
            estimate_stage_credit_cost(config, project_dir, state, name)
            for name in chain
        )
    except ArtifactMissing as exc:
        raise HTTPException(409, str(exc)) from exc
    except editorial.StoryDirectiveError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post("/story-changes/preview", openapi_extra={'x-canary-action': {'spends': False, 'dispatches': False}})
def preview_story_change(body: StoryChangePreviewBody, project=Depends(get_project)):
    project_dir, config, state = project
    target = TargetArtifacts(project_dir)
    if body.stage == "adapt":
        try:
            require_approved_brief(target.read_brief())
        except (ArtifactMissing, ValueError, FileNotFoundError) as exc:
            raise HTTPException(409, str(exc)) from exc
    source, adaptation, plan = _load_evidence(project_dir)
    try:
        proposal = editorial.build_story_change_proposal(
            instruction=body.instruction,
            stage=body.stage,
            source=source,
            adaptation=adaptation,
            plan=plan,
            source_unit_ids=tuple(body.source_unit_ids),
            adapted_beat_ids=tuple(body.adapted_beat_ids),
            page_numbers=tuple(body.page_numbers),
            estimate_credits=_preview_estimate_credits(
                config, project_dir, state, body.stage
            ),
        )
    except editorial.StaleRevision as exc:
        raise HTTPException(
            409,
            {
                "detail": str(exc),
                "revision": editorial.editorial_revision(adaptation, plan),
            },
        ) from exc
    except editorial.UnknownReference as exc:
        raise HTTPException(
            409,
            {
                "detail": str(exc),
                "revision": editorial.editorial_revision(adaptation, plan),
            },
        ) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    # Preview persists only the proposal. No generation runs and no canonical
    # artifact is created, modified, or deleted.
    target.write_story_change(proposal)
    return proposal.model_dump(mode="json")


@router.post("/story-changes/{proposal_id}/apply", openapi_extra={'x-canary-action': {'spends': True, 'dispatches': True}})
@limiter.limit(cost_limit)
async def apply_story_change(
    proposal_id: str,
    body: StoryChangeApplyBody,
    request: Request,
    project_id: str,
    project=Depends(get_project),
    user_id: str = Depends(get_current_user),
):
    project_dir, config, state = project
    target = TargetArtifacts(project_dir)
    _source, adaptation, plan = _load_evidence(project_dir)
    revision = editorial.editorial_revision(adaptation, plan)
    try:
        proposal = target.read_story_change(proposal_id)
    except ArtifactInvalid as exc:
        raise _unreadable(exc, revision=revision) from exc
    except (ArtifactMissing, ValueError) as exc:
        raise HTTPException(404, str(exc)) from exc
    if proposal.status == "applied":
        raise HTTPException(
            409,
            {"detail": "story change was already applied", "revision": revision},
        )
    # The proposal revision is the editorial fingerprint the preview was
    # compiled against: a client echo from a superseded preview and canonical
    # drift since previewing are both stale. No constant tokens, no shims.
    if body.expected_revision != proposal.revision:
        raise HTTPException(
            409,
            {
                "detail": (
                    "story change preview is stale; preview again against "
                    "the current evidence"
                ),
                "revision": revision,
            },
        )
    if proposal.revision != revision:
        raise HTTPException(
            409,
            {
                "detail": (
                    "canonical story artifacts changed since this preview; "
                    "preview again against the current evidence"
                ),
                "revision": revision,
            },
        )
    pkey = project_key(user_id, project_id)
    from ..admission import project_busy
    from novel_to_comic.workspace import part_id_for_path
    if project_busy(request.app, pkey, part_id_for_path(project_dir)):
        raise HTTPException(
            409,
            {"detail": "a stage is already running for this project", "revision": revision},
        )
    admit_stage_action(config, proposal.stage)
    # The directive lives outside the stage clean cascade, so the explicit
    # re-run below cannot delete it before the stage run reads it. It is
    # written before gating so the reservation prices the actual instructed
    # run; any refusal below rolls it back, leaving no orphan instruction.
    from novel_to_comic.editorial import StoryChangeDirective

    target.write_story_directive(
        StoryChangeDirective(
            proposal_id=proposal.id,
            stage=proposal.stage,
            instruction=proposal.instruction,
            created_at=proposal.created_at,
        )
    )
    # The re-run covers exactly these stages: Adapt auto-chains Plan and
    # stops. Gate the summed chain reservation — with the directive already
    # written, each stage prices the actual instructed run — so an apply can
    # never strand a half-applied book (new adaptation, starved plan). Draw
    # is never queued here; its redraw stays separately estimated.
    chain = [proposal.stage, *STAGE_AUTO_CHAIN.get(proposal.stage, ())]
    try:
        required = sum(
            estimate_stage_credit_reservation(config, project_dir, state, name)
            for name in chain
        )
        assert_sufficient_credits(get_db(), user_id, required, stage=proposal.stage)
        started = await _start_stage(
            request, project_id, proposal.stage, True, project, user_id
        )
    except Exception:
        target.clear_story_directive(proposal.stage)
        raise
    return {
        **started,
        "queued_stage": proposal.stage,
        "queued_stages": chain,
        "story_change_id": proposal.id,
        "job": None,
    }
