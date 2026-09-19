"""Shared FastAPI dependencies for the web dashboard."""

from pathlib import Path

import httpx
from fastapi import Depends, HTTPException, Request

from novel_to_comic.config import Config, load_config
from novel_to_comic.state import PipelineState, load_state

from .auth import get_current_user
from .account_models import account_config
from .db import get_db
from .project_paths import project_directory


def get_projects_dir(request: Request) -> Path:
    return request.app.state.projects_dir


def project_key(user_id: str, project_id: str) -> str:
    """Composite key used for all in-memory state dicts (event queues, running tasks, etc.)."""
    return f"{user_id}:{project_id}"


def _db_query_projects(user_id: str, project_id: str):
    return (
        get_db()
        .table("projects")
        .select("name")
        .eq("user_id", user_id)
        .eq("id", project_id)
        .execute()
    )


def _resolve_project_slug(user_id: str, project_id: str) -> str:
    """Look up the filesystem slug for a project UUID."""
    try:
        result = _db_query_projects(user_id, project_id)
    except httpx.ConnectError:
        # Retry this read on the live pool. Closing the singleton here also
        # closes the client retained by credit leases and admitted paid jobs.
        # A failed connection does not require replacing the HTTP client.
        result = _db_query_projects(user_id, project_id)
    if not result.data:
        raise HTTPException(404, f"Project '{project_id}' not found")
    return result.data[0]["name"]


def get_project(
    project_id: str,
    request: Request,
    user_id: str = Depends(get_current_user),
) -> tuple[Path, Config, PipelineState]:
    d = get_project_dir(project_id, request, user_id)
    config, _ = load_config(d)
    try:
        config = account_config(config, request.app.state.projects_dir, user_id)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    state = load_state(d)
    return d, config, state


def get_project_dir(
    project_id: str,
    request: Request,
    user_id: str = Depends(get_current_user),
) -> Path:
    """Resolve a project directory without validating its pipeline state.

    Destructive recovery actions need to reach projects whose state belongs to
    a retired pipeline contract. Normal project routes should continue using
    ``get_project`` so they only receive fully validated current projects.
    """
    slug = _resolve_project_slug(user_id, project_id)
    try:
        d = project_directory(request.app.state.projects_dir, user_id, slug)
    except ValueError as exc:
        raise HTTPException(404, f"Project '{project_id}' not found") from exc
    if not d.is_dir() or not (d / "state.json").exists():
        raise HTTPException(404, f"Project '{project_id}' not found")
    return d
