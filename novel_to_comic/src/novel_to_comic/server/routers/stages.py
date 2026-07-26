"""Read and edit canonical artifacts owned by target pipeline stages."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from novel_to_comic import artifacts
from novel_to_comic.briefing import revise_persisted_brief
from novel_to_comic.models.story_bible import StoryBible
from novel_to_comic.stages import REGISTRY
from novel_to_comic.state import StageState, StageStatus, save_state
from novel_to_comic.target_artifacts import ArtifactMissing, TargetArtifacts

from ..deps import get_project


router = APIRouter()


class BriefEdit(BaseModel):
    expected_revision: int = Field(ge=1)
    changes: dict


def _not_found(exc: ArtifactMissing) -> HTTPException:
    return HTTPException(404, str(exc))


@router.get("/story")
def get_story(project=Depends(get_project)):
    project_dir, _config, _state = project
    target = TargetArtifacts(project_dir)
    try:
        brief = target.read_brief()
    except ArtifactMissing:
        brief = None
    return {
        "story_bible": artifacts.read_story_bible(project_dir),
        "brief": brief,
    }


@router.get("/story-bible")
def get_story_bible(project=Depends(get_project)):
    project_dir, _config, _state = project
    return artifacts.read_story_bible(project_dir)


@router.put("/story-bible")
def update_story_bible(body: dict, project=Depends(get_project)):
    project_dir, _config, state = project
    bible = StoryBible.model_validate(body)
    artifacts.write_story_bible(project_dir, bible)
    for path in (
        project_dir / "brief",
        project_dir / "samples",
        project_dir / "refs",
        project_dir / "plates",
        project_dir / "adapt",
        project_dir / "plan",
        project_dir / "draw",
        project_dir / "finish",
        project_dir / "exports",
    ):
        if path.is_dir():
            import shutil

            shutil.rmtree(path)
        elif path.exists():
            path.unlink()
    for stage in ("brief", "style", "cast", "adapt", "plan", "draw", "finish"):
        state.stages[stage] = StageState()
    save_state(state, project_dir)
    return {"story_bible": bible, "brief": None}


@router.get("/brief")
def get_brief(project=Depends(get_project)):
    project_dir, _config, _state = project
    try:
        return TargetArtifacts(project_dir).read_brief()
    except ArtifactMissing as exc:
        raise _not_found(exc) from exc


@router.put("/brief")
def update_brief(body: BriefEdit, project=Depends(get_project)):
    project_dir, _config, state = project
    target = TargetArtifacts(project_dir)
    try:
        brief = revise_persisted_brief(
            target,
            expected_revision=body.expected_revision,
            **body.changes,
        )
    except (ArtifactMissing, ValueError) as exc:
        raise HTTPException(409, str(exc)) from exc
    state.stages["brief"].status = StageStatus.AWAITING_REVIEW
    state.stages["brief"].approved = None
    for stage in ("adapt", "plan", "draw", "finish"):
        state.stages[stage] = StageState()
    for path in REGISTRY["adapt"].clean_paths(project_dir):
        if path.is_dir():
            import shutil

            shutil.rmtree(path)
        elif path.exists():
            path.unlink()
    save_state(state, project_dir)
    return brief


@router.get("/adaptation")
def get_book_adaptation(project=Depends(get_project)):
    project_dir, _config, _state = project
    try:
        return TargetArtifacts(project_dir).read_adaptation()
    except ArtifactMissing as exc:
        raise _not_found(exc) from exc


@router.get("/book-plan")
def get_book_plan(project=Depends(get_project)):
    project_dir, _config, _state = project
    try:
        return TargetArtifacts(project_dir).read_plan()
    except ArtifactMissing as exc:
        raise _not_found(exc) from exc


@router.get("/comic-pages")
def list_comic_pages(project=Depends(get_project)):
    project_dir, _config, _state = project
    target = TargetArtifacts(project_dir)
    try:
        plan = target.read_plan()
        return [target.read_page(item.page_number) for item in plan.pages]
    except ArtifactMissing as exc:
        raise _not_found(exc) from exc


@router.get("/comic-pages/{page_number}")
def get_comic_page(page_number: int, project=Depends(get_project)):
    project_dir, _config, _state = project
    try:
        return TargetArtifacts(project_dir).read_page(page_number)
    except ArtifactMissing as exc:
        raise _not_found(exc) from exc


@router.get("/cast/primary-refs")
def get_primary_refs(project=Depends(get_project)):
    project_dir, _config, _state = project
    return {"primary_refs": artifacts.read_primary_refs(project_dir)}


@router.put("/cast/{char_id}/primary-ref")
def set_primary_ref(char_id: str, body: dict, project=Depends(get_project)):
    project_dir, _config, _state = project
    pose = body.get("pose")
    if pose not in artifacts.CHARACTER_REF_POSES:
        raise HTTPException(400, "pose must be 'portrait' or 'full_body'")
    data = artifacts.read_primary_refs(project_dir)
    data[char_id] = pose
    artifacts.write_primary_refs(project_dir, data)
    return {"char_id": char_id, "pose": pose, "primary_refs": data}
