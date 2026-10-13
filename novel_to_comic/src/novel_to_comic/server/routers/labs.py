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
from novel_to_comic.workspace import workspace_part_id

from ..auth import get_current_user
from ..deps import get_projects_dir
from .files import _is_denied

router = APIRouter()
log = logging.getLogger(__name__)


def _user_root(request: Request, user_id: str) -> Path:
    return get_projects_dir(request) / user_id


def _tasks(request: Request) -> dict[str, asyncio.Task[None]]:
    """In-flight work keyed ``run_id`` for a run, ``run_id:retry:N`` for each retry."""
    if not hasattr(request.app.state, "labs_tasks"):
        request.app.state.labs_tasks = {}
    return request.app.state.labs_tasks


def _task_cells(request: Request) -> dict[str, frozenset[str]]:
    """The cells each retry task is rerunning."""
    if not hasattr(request.app.state, "labs_task_cells"):
        request.app.state.labs_task_cells = {}
    return request.app.state.labs_task_cells


def _run_task_keys(request: Request, run_id: str) -> list[str]:
    return [key for key in _tasks(request) if key == run_id or key.startswith(f"{run_id}:")]


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
        source = stage_models.source_workspace(directory)
        state = load_state(source)
        statuses = {name: stage.status.value for name, stage in state.stages.items()}
        novel = Path(state.novel_path)
        if not novel.is_absolute():
            novel = source / novel
        projects.append({
            "id": directory.name, "title": state.project_name, "statuses": statuses,
            "part_id": workspace_part_id(source),
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
    phases = body.get("phases") or []
    try:
        source = stage_models.source_workspace(source, body.get("part_id"))
        arms = stage_models.resolve_arms(phases, body.get("arms"))
        stage_models.validate_spec(source, phases, stage_models.arm_models(arms))
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"estimated_cost_usd": stage_models.estimate_arms_usd(source, phases, arms)}


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


def _start(request: Request, user_root: Path, run_id: str, work, cells: frozenset[str] | None = None) -> None:
    """Run ``work`` in the background; ``cells`` marks it as a retry of those cells.

    Retries of different cells run side by side. The run stays ``running``
    until its last task ends, then records ``failed`` if any task raised.
    """
    tasks, task_cells = _tasks(request), _task_cells(request)
    key = run_id
    if cells is not None:
        number = 1
        while f"{run_id}:retry:{number}" in tasks:
            number += 1
        key = f"{run_id}:retry:{number}"
        task_cells[key] = cells

    async def execute() -> None:
        error = None
        try:
            await work
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - recorded on the run for the reader
            log.exception("Labs run %s failed", run_id)
            error = str(exc)
            storage.update_run(user_root, run_id, error=error)
        finally:
            tasks.pop(key, None)
            task_cells.pop(key, None)
        if not _run_task_keys(request, run_id):
            failed = error is not None or bool((storage.read_run(user_root, run_id) or {}).get("error"))
            storage.update_run(user_root, run_id, status="failed" if failed else "complete", finished_at=storage.now())

    tasks[key] = asyncio.create_task(execute())


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
        phases = body.get("phases") or []
        try:
            source = stage_models.source_workspace(source, body.get("part_id"))
            arms = stage_models.resolve_arms(phases, body.get("arms"))
            stage_models.validate_spec(source, phases, stage_models.arm_models(arms))
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        part_id = workspace_part_id(source)
        spec = {"project": project, "part_id": part_id, "phases": phases, "arms": arms,
                "estimated_cost_usd": stage_models.estimate_arms_usd(source, phases, arms)}
        run = storage.create_run(root, kind=kind, label=str(body.get("label") or "Stage models")[:200], spec=spec)
        _start(request, root, run["run_id"], stage_models.run(root, run["run_id"], project, phases, arms, part_id))
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
    # A failed cell has finished; only a retry already rerunning it is in flight.
    retrying = set().union(*(_task_cells(request).get(key, frozenset()) for key in _run_task_keys(request, run_id)))
    cells = [cell for cell in cells if cell["cell_id"] not in retrying]
    if not cells:
        raise HTTPException(409 if retrying else 400, "Already retrying" if retrying else "No failed cells to retry")
    storage.update_run(root, run_id, status="running", finished_at=None,
                       **({} if _run_task_keys(request, run_id) else {"error": None}))
    _start(request, root, run_id, experiment.retry(root, run_id, cells), frozenset(cell["cell_id"] for cell in cells))
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
    if run["status"] == "running" and not _run_task_keys(request, run_id):
        # The server restarted mid-run; unfinished cells never completed here.
        # Marking them failed keeps them retryable, with any partial spend shown.
        for cell in run["cells"]:
            if cell.get("status") == "running":
                storage.write_cell(root, run_id, cell["cell_id"], cell | {
                    "status": "failed", "error": "Interrupted by a server restart",
                })
        storage.update_run(root, run_id, status="interrupted", finished_at=storage.now())
        run = storage.read_run(root, run_id)
    return run


@router.delete("/runs/{run_id}")
async def delete_run(run_id: str, request: Request, user_id: str = Depends(get_current_user)) -> dict[str, str]:
    tasks = [_tasks(request).pop(key) for key in _run_task_keys(request, run_id)]
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
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
