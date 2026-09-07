"""Provider-free Finish trigger and verified export download."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse, RedirectResponse

from novel_to_comic.stage_runtime import StageRuntime
from novel_to_comic.stages import REGISTRY
from novel_to_comic.storage import r2_configured, upload_export
from novel_to_comic.models.finish import FINISH_PREFLIGHT_VALIDATOR_VERSION
from novel_to_comic.page_finishing import package_is_current
from novel_to_comic.target_artifacts import (
    ArtifactInvalid,
    ArtifactMissing,
    TargetArtifacts,
)

from ..auth import get_current_user
from ..deps import get_project
from ..product_events import capture_server_event
from ..ratelimit import export_limit, limiter


router = APIRouter()
_EXPORT_LOCKS_ATTR = "_export_locks"


def _get_export_lock(app, project_name: str) -> asyncio.Lock:
    locks = getattr(app.state, _EXPORT_LOCKS_ATTR, None)
    if locks is None:
        locks = {}
        setattr(app.state, _EXPORT_LOCKS_ATTR, locks)
    return locks.setdefault(project_name, asyncio.Lock())


@router.get("/preflight")
def get_preflight(
    project=Depends(get_project),
    user_id: str = Depends(get_current_user),  # noqa: ARG001 — auth gate
):
    """Return the persisted current preflight without running it again."""

    project_dir, _config, _state = project
    try:
        target = TargetArtifacts(project_dir)
        preflight = target.read_preflight()
    except (ArtifactMissing, ArtifactInvalid) as exc:
        raise HTTPException(404, "No current Finish preflight is available") from exc
    if preflight.validator_version != FINISH_PREFLIGHT_VALIDATOR_VERSION:
        raise HTTPException(404, "Finish preflight must be refreshed")
    if any(not package_is_current(target, package) for package in preflight.packages):
        raise HTTPException(404, "An export package is unavailable; refresh Finish preflight")
    return preflight


@router.post("/preflight")
@limiter.limit(export_limit)
async def run_preflight(
    request: Request,
    project_id: str,
    project=Depends(get_project),
    user_id: str = Depends(get_current_user),  # noqa: ARG001 — auth gate
):
    """Run Finish checks without creating an export package."""

    project_dir, config, state = project
    lock = _get_export_lock(request.app, project_dir.name)
    if lock.locked():
        raise HTTPException(
            409, "An export or preflight for this project is already running"
        )
    async with lock:
        try:
            result = await REGISTRY["finish"].run(
                config,
                project_dir,
                StageRuntime("finish", state, project_dir),
                formats=(),
                clear_derived_outputs=False,
            )
        except Exception as exc:
            raise HTTPException(422, str(exc)) from exc
    return {"status": "done", "preflight": result.preflight}


@router.post("/")
@limiter.limit(export_limit)
async def trigger_export(
    request: Request,
    project_id: str,
    format: str = Query("pdf"),
    force: bool = Query(False),
    project=Depends(get_project),
    user_id: str = Depends(get_current_user),
):
    project_dir, config, state = project
    fmt = format.lower()
    if fmt not in {"pdf", "cbz"}:
        raise HTTPException(400, "Format must be 'pdf' or 'cbz'")
    target = TargetArtifacts(project_dir)
    export_path = target.export_path(fmt)
    if export_path.exists() and not force:
        data = export_path.read_bytes()
        return {
            "status": "exists",
            "path": export_path.name,
            "url": (
                upload_export(user_id, project_dir.name, export_path.name, data)
                if r2_configured()
                else None
            ),
        }

    lock = _get_export_lock(request.app, project_dir.name)
    if lock.locked():
        raise HTTPException(409, "An export for this project is already running")
    async with lock:
        try:
            result = await REGISTRY["finish"].run(
                config,
                project_dir,
                StageRuntime("finish", state, project_dir),
                formats=(fmt,),
            )
        except Exception as exc:
            raise HTTPException(422, str(exc)) from exc
        if not result.preflight.ready_to_export or not export_path.exists():
            raise HTTPException(
                422,
                {
                    "error": "finish_preflight_blocked",
                    "preflight": result.preflight.model_dump(mode="json"),
                },
            )

    url = None
    if r2_configured():
        url = upload_export(
            user_id,
            project_dir.name,
            export_path.name,
            export_path.read_bytes(),
        )
    capture_server_event(
        "export_succeeded",
        user_id=user_id,
        project_id=project_id,
        request_id=getattr(request.state, "request_id", None),
        properties={"format": fmt, "cached": False},
    )
    return {
        "status": "done",
        "path": export_path.name,
        "url": url,
        "preflight": result.preflight,
    }


@router.get("/{fmt}")
def download_export(
    fmt: str,
    project=Depends(get_project),
    user_id: str = Depends(get_current_user),
):
    project_dir, _config, _state = project
    if fmt not in {"pdf", "cbz"}:
        raise HTTPException(400, "Format must be 'pdf' or 'cbz'")
    export_path = TargetArtifacts(project_dir).export_path(fmt)
    if not export_path.exists():
        raise HTTPException(404, f"No {fmt} export found. Run Finish first.")
    if r2_configured():
        return RedirectResponse(upload_export(
            user_id,
            project_dir.name,
            export_path.name,
            export_path.read_bytes(),
        ))
    media_type = "application/pdf" if fmt == "pdf" else "application/zip"
    return FileResponse(
        export_path,
        media_type=media_type,
        filename=export_path.name,
    )
