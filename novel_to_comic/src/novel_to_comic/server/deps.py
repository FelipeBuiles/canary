"""Shared FastAPI dependencies for the web dashboard."""

import logging
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


def event_key(pkey: str, directory: Path | str | None = None, part_id: str | None = None) -> str:
    """The pipeline event stream for one part (or the series root).

    Parts can work at the same time, so each part's progress has its own stream.
    """
    from novel_to_comic.workspace import part_id_for_path

    part = part_id or (part_id_for_path(directory) if directory is not None else None)
    return pkey if part is None else f"{pkey}/{part}"


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
    """Resolve the project scope addressed by the route.

    Routes mounted under ``/parts/{part_id}`` receive that part's workspace and
    state (with the series Style/Cast stages overlaid). Series routes receive
    the series root and its state.
    """
    root = get_project_dir(project_id, request, user_id)
    config, _ = load_config(root)
    try:
        config = account_config(config, request.app.state.projects_dir, user_id)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    part_id = request.path_params.get("part_id")
    directory = root if part_id is None else get_part_dir(root, part_id)
    state = load_state(directory)
    return directory, config, state


def get_part_dir(root: Path, part_id: str) -> Path:
    """A part workspace that exists in the series manifest."""
    from novel_to_comic.target_artifacts import ArtifactMissing, TargetArtifacts
    from novel_to_comic.workspace import is_part_workspace, part_workspace

    try:
        TargetArtifacts(root).read_part_manifest().get(part_id)
        workspace = part_workspace(root, part_id)
    except (KeyError, ValueError, ArtifactMissing):
        raise HTTPException(404, f"Part '{part_id}' not found") from None
    if not is_part_workspace(workspace) or not (workspace / "state.json").exists():
        raise HTTPException(404, f"Part '{part_id}' not found")
    return workspace


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
    _ensure_series_layout(d)
    return d


def _ensure_series_layout(project_dir: Path) -> None:
    """Move a project created before parts into a one-part series, once.

    Deployments drain before upgrading, so no job references the old layout.
    A project whose state predates the current pipeline is left untouched for
    the destructive recovery routes that use ``get_project_dir``.
    """
    from novel_to_comic.series_migration import migrate_to_series, needs_series_migration

    if not needs_series_migration(project_dir):
        return
    try:
        load_state(project_dir)
    except Exception:
        return
    try:
        migrate_to_series(project_dir)
    except (OSError, ValueError) as exc:
        # Without readable source text there is no part to create; the project
        # could not be extracted either. Leave it as it is and say why.
        logging.getLogger("canary.series_migration").warning(
            "Project %s was not migrated into a series: %s", project_dir.name, exc,
        )
