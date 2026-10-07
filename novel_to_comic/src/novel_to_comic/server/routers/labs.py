"""Local-development model experiments that read the user's projects.

Runs are operator-funded and never touch account credits; ``create_app`` mounts
this router only when ``CANARY_LABS_ENABLED`` is set in local development.
"""

from __future__ import annotations

import asyncio
import logging
import mimetypes
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from fastapi.responses import FileResponse

from novel_to_comic.labs import image_compare, stage_models, storage
from novel_to_comic.state import load_state

from ..auth import get_current_user
from ..deps import get_projects_dir
from .files import _is_denied

router = APIRouter()
log = logging.getLogger(__name__)


def _user_root(request: Request, user_id: str) -> Path:
    return get_projects_dir(request) / user_id


def _tasks(request: Request) -> dict[str, asyncio.Task[None]]:
    if not hasattr(request.app.state, "labs_tasks"):
        request.app.state.labs_tasks = {}
    return request.app.state.labs_tasks


def _project_dir(root: Path, project: str) -> Path:
    if not project or project != Path(project).name or project.startswith(("_", ".")):
        raise HTTPException(400, "Invalid project")
    return root / project


_MAX_IMAGE_ITEMS = 12


@router.get("/image-compare/options")
def image_compare_options(user_id: str = Depends(get_current_user)) -> dict[str, Any]:  # noqa: ARG001
    return {
        "targets": [
            {"id": target.id, "label": target.label, "provider": target.provider,
             "funding": target.funding, "available": target.available}
            for target in image_compare.image_targets()
        ],
        "prompts": list(image_compare.PROMPTS),
    }


@router.get("/image-compare/projects/{project}/items")
def image_compare_items(project: str, request: Request, user_id: str = Depends(get_current_user)) -> dict[str, Any]:
    directory = _project_dir(_user_root(request, user_id), project)
    if not (directory / "state.json").exists():
        raise HTTPException(404, "Project not found")
    return {"items": image_compare.list_items(directory)}


@router.post("/image-compare/preview")
def image_compare_preview(
    request: Request, body: dict[str, Any] = Body(...), user_id: str = Depends(get_current_user),
) -> dict[str, Any]:
    directory = _project_dir(_user_root(request, user_id), str(body.get("project") or ""))
    try:
        arms = image_compare.validate_arms(list(body.get("arms") or []))
        return {"arms": image_compare.preview(directory, str(body.get("item") or ""), arms)}
    except (ValueError, OSError) as exc:
        raise HTTPException(400, str(exc)) from exc


def _projects(root: Path) -> list[dict[str, Any]]:
    projects = []
    for directory in sorted(root.iterdir()) if root.exists() else ():
        if directory.name.startswith(("_", ".")) or not (directory / "state.json").exists():
            continue
        state = load_state(directory)
        statuses = {name: stage.status.value for name, stage in state.stages.items()}
        novel = directory / "input" / Path(state.novel_path).name
        projects.append({
            "id": directory.name, "title": state.project_name, "statuses": statuses,
            "words": len(novel.read_text(errors="ignore").split()) if novel.exists() else None,
        })
    return projects


@router.get("/projects")
def list_projects(request: Request, user_id: str = Depends(get_current_user)) -> dict[str, Any]:
    return {"projects": _projects(_user_root(request, user_id))}


@router.get("/projects/{project}/files/{path:path}")
def get_project_file(
    project: str, path: str, request: Request, user_id: str = Depends(get_current_user),
) -> FileResponse:
    """Read Labs source assets using its filesystem project identifier."""
    user_root = _user_root(request, user_id).resolve()
    directory = _project_dir(user_root, project).resolve()
    target = (directory / path).resolve()
    if (
        not directory.is_relative_to(user_root)
        or not target.is_relative_to(directory)
        or _is_denied(target.relative_to(directory))
    ):
        raise HTTPException(403, "Access denied")
    if not (directory / "state.json").is_file() or not target.is_file():
        raise HTTPException(404, "File not found")
    return FileResponse(
        target,
        media_type=mimetypes.guess_type(target.name)[0] or "application/octet-stream",
        headers={"Cache-Control": "private, max-age=60"},
    )


@router.get("/stage-models/options")
def stage_model_options(user_id: str = Depends(get_current_user)) -> dict[str, Any]:  # noqa: ARG001
    return {
        "models": stage_models.selectable_models(),
        "default_models": list(stage_models.DEFAULT_MODELS),
        "phases": {phase: list(stages) for phase, stages in stage_models.PHASES.items()},
    }


@router.post("/stage-models/estimate")
def stage_model_estimate(
    request: Request, body: dict[str, Any] = Body(...), user_id: str = Depends(get_current_user),
) -> dict[str, Any]:
    source = _project_dir(_user_root(request, user_id), str(body.get("project") or ""))
    phases, models = list(body.get("phases") or []), list(body.get("models") or [])
    try:
        stage_models.validate_spec(source, phases, models)
        stage_models.resolve_reasoning(phases, models, body.get("reasoning_efforts"))
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"estimated_cost_usd": stage_models.estimate_usd(source, phases, models)}


@router.post("/image-compare/estimate")
def image_compare_estimate(
    request: Request, body: dict[str, Any] = Body(...), user_id: str = Depends(get_current_user),
) -> dict[str, Any]:
    directory = _project_dir(_user_root(request, user_id), str(body.get("project") or ""))
    items = [str(value) for value in body.get("items") or []]
    if not items or len(items) > _MAX_IMAGE_ITEMS:
        raise HTTPException(400, f"Choose between 1 and {_MAX_IMAGE_ITEMS} items")
    try:
        return image_compare.estimate(directory, items, image_compare.validate_arms(list(body.get("arms") or [])))
    except (ValueError, OSError) as exc:
        raise HTTPException(400, str(exc)) from exc


def _start(request: Request, user_root: Path, run_id: str, work) -> None:
    tasks = _tasks(request)

    async def execute() -> None:
        try:
            await work
            storage.update_run(user_root, run_id, status="complete", finished_at=storage.now())
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - recorded on the run for the reader
            log.exception("Labs run %s failed", run_id)
            storage.update_run(user_root, run_id, status="failed", error=str(exc), finished_at=storage.now())
        finally:
            tasks.pop(run_id, None)

    tasks[run_id] = asyncio.create_task(execute())


@router.post("/runs")
async def create_run(
    request: Request, body: dict[str, Any] = Body(...), user_id: str = Depends(get_current_user),
) -> dict[str, Any]:
    root = _user_root(request, user_id)
    kind = body.get("kind")
    if kind == image_compare.KIND:
        project = str(body.get("project") or "")
        source = _project_dir(root, project)
        items = [str(value) for value in body.get("items") or []]
        try:
            arms = image_compare.validate_arms(list(body.get("arms") or []))
            known = {item["id"] for item in image_compare.list_items(source)}
        except (ValueError, OSError) as exc:
            raise HTTPException(400, str(exc)) from exc
        if not items or len(items) > _MAX_IMAGE_ITEMS or not set(items) <= known:
            raise HTTPException(400, f"Choose between 1 and {_MAX_IMAGE_ITEMS} items from this project")
        spec: dict[str, Any] = {"project": project, "items": items, "arms": arms}
        run = storage.create_run(root, kind=kind, label=str(body.get("label") or "Image comparison")[:200], spec=spec)
        _start(request, root, run["run_id"], image_compare.run(root, run["run_id"], project, items, arms))
    elif kind == stage_models.KIND:
        project = str(body.get("project") or "")
        source = _project_dir(root, project)
        phases, models = list(body.get("phases") or []), list(body.get("models") or [])
        try:
            stage_models.validate_spec(source, phases, models)
            reasoning = stage_models.resolve_reasoning(phases, models, body.get("reasoning_efforts"))
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        spec = {"project": project, "phases": phases, "models": models, "reasoning_efforts": reasoning,
                "estimated_cost_usd": stage_models.estimate_usd(source, phases, models)}
        run = storage.create_run(root, kind=kind, label=str(body.get("label") or "Stage models")[:200], spec=spec)
        _start(request, root, run["run_id"], stage_models.run(root, run["run_id"], project, phases, models, reasoning))
    else:
        raise HTTPException(400, f"Unknown experiment kind: {kind!r}")
    return run


@router.post("/runs/{run_id}/retry")
async def retry_cells(
    run_id: str, request: Request, body: dict[str, Any] = Body(default={}), user_id: str = Depends(get_current_user),
) -> dict[str, Any]:
    """Resubmit failed cells with their recorded inputs; ``cells`` omitted retries all.

    Image cells resend the same request; text-stage arms rerun their phase.
    """
    root = _user_root(request, user_id)
    if run_id in _tasks(request):
        raise HTTPException(409, "This run is still in progress")
    try:
        run = storage.read_run(root, run_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    experiment = {image_compare.KIND: image_compare, stage_models.KIND: stage_models}.get((run or {}).get("kind"))
    if experiment is None:
        raise HTTPException(404, "Run not found")
    requested = body.get("cells")
    try:
        cells = experiment.failed_cells(root, run_id, None if requested is None else [str(c) for c in requested])
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if not cells:
        raise HTTPException(400, "No failed cells to retry")
    storage.update_run(root, run_id, status="running", finished_at=None, error=None)
    _start(request, root, run_id, experiment.retry(root, run_id, cells))
    return {"status": "running", "cells": [cell["cell_id"] for cell in cells]}


@router.get("/runs")
def list_runs(request: Request, user_id: str = Depends(get_current_user)) -> dict[str, Any]:
    return {"runs": storage.list_runs(_user_root(request, user_id))}


@router.get("/runs/{run_id}")
def get_run(run_id: str, request: Request, user_id: str = Depends(get_current_user)) -> dict[str, Any]:
    root = _user_root(request, user_id)
    try:
        run = storage.read_run(root, run_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if run is None:
        raise HTTPException(404, "Run not found")
    if run["status"] == "running" and run_id not in _tasks(request):
        # The server restarted mid-run; unfinished cells never completed here.
        storage.update_run(root, run_id, status="interrupted", finished_at=storage.now())
        run = storage.read_run(root, run_id)
    return run


@router.delete("/runs/{run_id}")
async def delete_run(run_id: str, request: Request, user_id: str = Depends(get_current_user)) -> dict[str, str]:
    task = _tasks(request).pop(run_id, None)
    if task is not None:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    try:
        deleted = storage.delete_run(_user_root(request, user_id), run_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if not deleted:
        raise HTTPException(404, "Run not found")
    return {"status": "deleted", "run_id": run_id}


@router.get("/runs/{run_id}/files/{path:path}")
def get_run_file(
    run_id: str, path: str, request: Request, user_id: str = Depends(get_current_user),
) -> FileResponse:
    try:
        target = storage.run_file(_user_root(request, user_id), run_id, path)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if not target.is_file() or target.suffix.lower() not in {".png", ".jpg", ".webp", ".json"}:
        raise HTTPException(404, "File not found")
    return FileResponse(target, media_type=mimetypes.guess_type(target.name)[0] or "application/octet-stream")
