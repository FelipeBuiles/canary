"""Carry an author's page note to every page it touches.

Preview resolves the pages for free; checks and apply are priced and funded
like the page checks and re-plans they are made of. See note_changes.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from novel_to_comic.note_scope import NoteClaim, NoteScopeError
from novel_to_comic.target_artifacts import ArtifactInvalid, ArtifactMissing, TargetArtifacts

from .. import note_changes
from ..auth import get_current_user
from ..deps import get_project
from ..page_outcomes import record_page_outcome
from ..ratelimit import cost_limit, limiter

router = APIRouter()


class NotePreview(BaseModel):
    page_number: int = Field(ge=1)
    note: str = Field(min_length=1, max_length=1000)
    claim: NoteClaim


class NoteApply(BaseModel):
    pages: list[int] | None = None


def _change(project_dir, change_id: str):
    try:
        return TargetArtifacts(project_dir).read_note_change(change_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    except (ArtifactMissing, ArtifactInvalid) as exc:
        raise HTTPException(404, "This change is no longer stored.") from exc


def _refused(exc: Exception) -> HTTPException:
    code = "stale_note" if isinstance(exc, note_changes.StaleNote) else "note_refused"
    return HTTPException(409, {"code": code, "message": str(exc)})


def _body(change) -> dict:
    return {**change.model_dump(mode="json"), "check_pages": list(note_changes.check_pages(change)),
            "default_pages": list(note_changes.default_pages(change))}


@router.get("/notes")
def list_notes(project=Depends(get_project)):
    project_dir = project[0]
    return {"notes": [_body(change) for change in TargetArtifacts(project_dir).list_note_changes()]}


@router.post("/notes/preview", openapi_extra={'x-canary-action': {'spends': False, 'dispatches': False}})
def preview_note(body: NotePreview, project=Depends(get_project)):
    """List every page the note touches. Nothing is generated or changed."""
    try:
        change = note_changes.preview(project[0], body.page_number, body.note, body.claim)
    except (note_changes.NoteRefused, NoteScopeError) as exc:
        raise _refused(exc) from exc
    return _body(change)


@router.get("/notes/{change_id}/checks/estimate")
def estimate_note_checks(change_id: str, project=Depends(get_project)):
    project_dir, config, _state = project
    try:
        return note_changes.quote_checks(project_dir, config, _change(project_dir, change_id))
    except (ArtifactMissing, ArtifactInvalid, ValueError) as exc:
        raise _refused(exc) from exc


@router.post("/notes/{change_id}/checks", openapi_extra={'x-canary-action': {'spends': True, 'dispatches': False}})
@limiter.limit(cost_limit)
async def check_note_pages(change_id: str, request: Request, project_id: str, project=Depends(get_project),
                           user_id: str = Depends(get_current_user)):
    """Look at each other drawn page in the run for art that breaks the fact."""
    project_dir, config, _state = project
    try:
        change = await note_changes.run_checks(project_dir, config, _change(project_dir, change_id),
                                               user_id=user_id, project_id=project_id)
    except (ArtifactMissing, ArtifactInvalid, ValueError) as exc:
        raise _refused(exc) from exc
    return _body(change)


@router.get("/notes/{change_id}/estimate")
def estimate_note_apply(change_id: str, project=Depends(get_project)):
    project_dir, config, _state = project
    try:
        return note_changes.quote_apply(project_dir, config, _change(project_dir, change_id))
    except (ArtifactMissing, ArtifactInvalid, ValueError) as exc:
        raise _refused(exc) from exc


@router.post("/notes/{change_id}/apply", openapi_extra={'x-canary-action': {'spends': True, 'dispatches': False}})
@limiter.limit(cost_limit)
async def apply_note(change_id: str, body: NoteApply, request: Request, project_id: str,
                     project=Depends(get_project), user_id: str = Depends(get_current_user)):
    """Write the change through the Story Bible, script and page plan, or nothing."""
    project_dir, config, _state = project
    change = _change(project_dir, change_id)
    try:
        applied = await note_changes.apply(
            project_dir, config, change, pages=tuple(body.pages) if body.pages is not None else None,
            user_id=user_id, project_id=project_id,
        )
    except (ArtifactMissing, ArtifactInvalid, ValueError) as exc:
        raise _refused(exc) from exc
    target = TargetArtifacts(project_dir)
    record_page_outcome(request.app, "note_carried", user_id=user_id, project_id=project_id, target=target,
                        page_number=applied.page_number, category=applied.claim.kind,
                        mode=f"{len(applied.pages)}_pages")
    return _body(applied)


@router.post("/notes/{change_id}/undo", openapi_extra={'x-canary-action': {'spends': False, 'dispatches': False}})
def undo_note(change_id: str, request: Request, project_id: str, project=Depends(get_project),
              user_id: str = Depends(get_current_user)):
    """Put the script and page plan back; drawn art stays in each page's history."""
    project_dir = project[0]
    try:
        undone = note_changes.undo(project_dir, _change(project_dir, change_id))
    except (ArtifactMissing, ArtifactInvalid, ValueError) as exc:
        raise _refused(exc) from exc
    record_page_outcome(request.app, "note_undone", user_id=user_id, project_id=project_id,
                        target=TargetArtifacts(project_dir), page_number=undone.page_number,
                        category=undone.claim.kind)
    return _body(undone)
