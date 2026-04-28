"""Shared FastAPI dependencies for the web dashboard."""

from pathlib import Path

from fastapi import Depends, HTTPException, Request

from novel_to_comic.config import Config, load_config
from novel_to_comic.state import PipelineState, load_state

from .auth import get_current_user


def get_projects_dir(request: Request) -> Path:
    return request.app.state.projects_dir


def project_key(user_id: str, project_name: str) -> str:
    """Composite key used for all in-memory state dicts (event queues, running tasks, etc.)."""
    return f"{user_id}:{project_name}"


def get_project(
    project_name: str,
    request: Request,
    user_id: str = Depends(get_current_user),
) -> tuple[Path, Config, PipelineState]:
    d = request.app.state.projects_dir / user_id / project_name
    if not d.is_dir() or not (d / "state.json").exists():
        raise HTTPException(404, f"Project '{project_name}' not found")
    config, _ = load_config(d)
    state = load_state(d)
    return d, config, state
