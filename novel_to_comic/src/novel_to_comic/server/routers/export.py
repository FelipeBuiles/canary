"""Provider-free Finish trigger and verified export download."""

from __future__ import annotations


import asyncio

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from novel_to_comic.stage_runtime import StageRuntime
from novel_to_comic.stages import REGISTRY
from novel_to_comic.page_finishing import current_preflight, open_verified_package
from novel_to_comic.target_artifacts import (
    ArtifactInvalid,
    ArtifactMissing,
    TargetArtifacts,
)

from ..auth import get_current_user
from ..export_stream import download_response
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
        preflight = current_preflight(target)
    except (ArtifactMissing, ArtifactInvalid, ValueError) as exc:
        raise HTTPException(404, "No current Finish preflight is available") from exc
    return preflight


@router.post("/preflight", openapi_extra={'x-canary-action': {'spends': False, 'dispatches': False, 'replay': False}})
@limiter.limit(export_limit)
async def run_preflight(
    request: Request,
    project_id: str,
    project=Depends(get_project),
    user_id: str = Depends(get_current_user),  # noqa: ARG001 — auth gate
):
    """Run Finish checks without creating an export package."""

    project_dir, config, state = project
    lock = _get_export_lock(request.app, str(project_dir.resolve()))
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


@router.post("/", openapi_extra={'x-canary-action': {'spends': False, 'dispatches': False}})
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
    lock = _get_export_lock(request.app, str(project_dir.resolve()))
    if lock.locked():
        raise HTTPException(409, "An export for this project is already running")
    async with lock:
        if export_path.exists() and not force:
            try:
                stream, _package, _preflight = await asyncio.to_thread(open_verified_package, target, fmt)
                stream.close()
            except (ArtifactMissing, ArtifactInvalid, ValueError, OSError):
                pass  # Rebuild stale derived output through provider-free Finish.
            else:
                capture_server_event("export_package_ready", user_id=user_id, project_id=project_id, properties={"format": fmt, "cached": True})
                return {"status": "exists", "path": export_path.name, "url": None}
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

    capture_server_event(
        "export_package_ready",
        user_id=user_id,
        project_id=project_id,
        request_id=getattr(request.state, "request_id", None),
        properties={"format": fmt, "cached": False},
    )
    return {
        "status": "done",
        "path": export_path.name,
        "url": None,
        "preflight": result.preflight,
    }


@router.get("/{fmt}")
def download_export(
    fmt: str,
    project_id: str,
    project=Depends(get_project),
    user_id: str = Depends(get_current_user),
):
    project_dir, _config, _state = project
    if fmt not in {"pdf", "cbz"}:
        raise HTTPException(400, "Format must be 'pdf' or 'cbz'")
    try:
        stream, package, _preflight = open_verified_package(TargetArtifacts(project_dir), fmt)
    except (ArtifactMissing, ArtifactInvalid, ValueError, OSError) as exc:
        raise HTTPException(404, str(exc)) from exc
    capture_server_event("export_download_requested", user_id=user_id, project_id=project_id, properties={"format": fmt})
    media_type = "application/pdf" if fmt == "pdf" else "application/zip"
    return download_response(stream, size=package.byte_size, name=f"comic.{fmt}", media_type=media_type)
