"""Shared FastAPI dependencies for the web dashboard."""

from pathlib import Path

from fastapi import HTTPException, Request

from novel_to_comic.config import Config, load_config
from novel_to_comic.state import PipelineState, load_state


def get_projects_dir(request: Request) -> Path:
    return request.app.state.projects_dir


def get_project_dir(project_name: str, request: Request) -> Path:
    d = request.app.state.projects_dir / project_name
    if not d.is_dir() or not (d / "state.json").exists():
        raise HTTPException(404, f"Project '{project_name}' not found")
    return d


def get_project(
    project_name: str, request: Request
) -> tuple[Path, Config, PipelineState]:
    project_dir = get_project_dir(project_name, request)
    config, _ = load_config(project_dir)
    state = load_state(project_dir)
    return project_dir, config, state
