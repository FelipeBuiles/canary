"""Editorial findings, on-demand source excerpts, and story-change workflow.

Preview compiles a persistent, reloadable proposal with truthful impact and
cost information and never generates or mutates canonical artifacts. Only an
explicit apply writes a one-shot directive and re-runs the owning stage
through the standard pipeline orchestration (credit authorization, busy and
stale guards, StageRuntime execution).
"""

from __future__ import annotations


from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from novel_to_comic import editorial
from novel_to_comic.target_artifacts import (
    ArtifactInvalid,
    ArtifactMissing,
    TargetArtifacts,
)
from ..deps import get_project


router = APIRouter()


class DecisionBody(BaseModel):
    expected_revision: str = Field(min_length=1)
    issue_ids: list[str] = Field(min_length=1)
    disposition: Literal["kept", "reopened"]


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
