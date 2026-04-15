"""Project listing and pipeline status."""

from fastapi import APIRouter, Depends
from pathlib import Path

from novel_to_comic.config import load_config
from novel_to_comic.state import STAGE_NAMES, load_state

from ..deps import get_project, get_projects_dir

router = APIRouter()


@router.get("/")
def list_projects(projects_dir: Path = Depends(get_projects_dir)):
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
            if state.stages[name].status.value in ("complete", "awaiting_review"):
                furthest = name
        results.append({
            "name": d.name,
            "project_name": state.project_name,
            "created_at": state.created_at.isoformat(),
            "total_cost_usd": state.total_cost_usd,
            "furthest_stage": furthest,
        })
    return results


@router.get("/{project_name}/status")
def project_status(project=Depends(get_project)):
    project_dir, config, state = project
    stages = {}
    for name in STAGE_NAMES:
        s = state.stages[name]
        stages[name] = {
            "status": s.status.value,
            "items_done": s.items_done,
            "items_total": s.items_total,
            "items_failed": s.items_failed,
            "cost_usd": s.cost_usd,
            "error": s.error,
            "started_at": s.started_at.isoformat() if s.started_at else None,
            "finished_at": s.finished_at.isoformat() if s.finished_at else None,
        }
    return {
        "project_name": state.project_name,
        "created_at": state.created_at.isoformat(),
        "total_cost_usd": state.total_cost_usd,
        "stages": stages,
    }
