"""Project listing and pipeline status."""

from pathlib import Path

from fastapi import APIRouter, Depends, Request

from novel_to_comic.config import load_config
from novel_to_comic.state import STAGE_NAMES, load_state

from ..deps import get_project, get_projects_dir

router = APIRouter()


def _assemble_artifact_error(project_dir: Path) -> str | None:
    """Return a user-facing reason when a completed assemble stage is unusable."""
    page_json = list((project_dir / "assembly" / "pages").glob("page_*.json"))
    if page_json:
        return None

    legacy_png = list((project_dir / "pages").glob("page_*.png"))
    if legacy_png:
        return (
            "Missing editable page JSON in assembly/pages. Found legacy rendered "
            "PNGs in pages/. Re-run the assemble stage with the current pipeline."
        )

    return "Missing editable page JSON in assembly/pages. Re-run the assemble stage."


def _stage_payload(project_dir: Path, name: str, state) -> dict:
    s = state.stages[name]
    status = s.status.value
    error = s.error

    if name == "assemble" and status == "complete":
        artifact_error = _assemble_artifact_error(project_dir)
        if artifact_error:
            status = "failed"
            error = artifact_error

    return {
        "status": status,
        "items_done": s.items_done,
        "items_total": s.items_total,
        "items_failed": s.items_failed,
        "cost_usd": s.cost_usd,
        "error": error,
        "started_at": s.started_at.isoformat() if s.started_at else None,
        "finished_at": s.finished_at.isoformat() if s.finished_at else None,
    }


def _is_project_running(project_name: str, request: Request) -> bool:
    task = request.app.state.running_tasks.get(project_name)
    return task is not None and not task.done()


@router.get("/")
def list_projects(request: Request, projects_dir: Path = Depends(get_projects_dir)):
    """Scan projects_dir for subdirectories containing state.json."""
    results = []
    for d in sorted(projects_dir.iterdir()):
        state_file = d / "state.json"
        if not d.is_dir() or not state_file.exists():
            continue
        state = load_state(d)
        # Summarise: furthest completed stage
        furthest = None
        for name in STAGE_NAMES:
            if _stage_payload(d, name, state)["status"] in ("complete", "awaiting_review"):
                furthest = name
        results.append({
            "name": d.name,
            "project_name": state.project_name,
            "created_at": state.created_at.isoformat(),
            "total_cost_usd": state.total_cost_usd,
            "furthest_stage": furthest,
            "is_running": _is_project_running(d.name, request),
        })
    return results


@router.get("/{project_name}/status")
def project_status(request: Request, project=Depends(get_project)):
    project_dir, config, state = project
    stages = {}
    for name in STAGE_NAMES:
        stages[name] = _stage_payload(project_dir, name, state)
    return {
        "project_name": state.project_name,
        "created_at": state.created_at.isoformat(),
        "total_cost_usd": state.total_cost_usd,
        "is_running": _is_project_running(project_dir.name, request),
        "stages": stages,
    }
