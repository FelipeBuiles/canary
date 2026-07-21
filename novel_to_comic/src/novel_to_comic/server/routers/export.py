"""Export trigger and file download."""

import asyncio

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse, RedirectResponse

from novel_to_comic.assembly.lettering_style import lettering_style_path
from novel_to_comic.assembly.lettering_preflight import (
    has_blocking_lettering_issues,
    inspect_project_lettering,
)
from novel_to_comic.stage_runtime import StageRuntime
from novel_to_comic.stages import s8_compose
from novel_to_comic.storage import export_url, r2_configured, upload_export

from ..auth import get_current_user
from ..deps import get_project
from ..ratelimit import export_limit, limiter
from ..product_events import capture_server_event

router = APIRouter()


@router.post("/")
@limiter.limit(export_limit)
async def trigger_export(
    request: Request,
    project_id: str,
    format: str = Query("pdf"),
    force: bool = Query(False),
    allow_issues: bool = Query(False),
    project=Depends(get_project),
    user_id: str = Depends(get_current_user),
):
    project_dir, config, state = project
    fmt = format.lower()
    if fmt not in ("pdf", "cbz"):
        raise HTTPException(400, "Format must be 'pdf' or 'cbz'")

    lettering_issues = await inspect_project_lettering(project_dir)
    if not allow_issues and has_blocking_lettering_issues(lettering_issues):
        blocking = [issue.as_dict() for issue in lettering_issues if issue.severity == "error"]
        locations = sorted({
            (issue.page_number, issue.panel_number)
            for issue in lettering_issues
            if issue.severity == "error"
        })
        location_summary = ", ".join(
            f"page {page}, panel {panel}" for page, panel in locations[:3]
        )
        if len(locations) > 3:
            location_summary += f", and {len(locations) - 3} more"
        raise HTTPException(
            422,
            {
                "message": (
                    f"Export is blocked by {len(blocking)} lettering "
                    f"issue{'s' if len(blocking) != 1 else ''} at {location_summary}. "
                    "Review them or choose Export Anyway."
                ),
                "issues": blocking,
            },
        )

    export_path = project_dir / "exports" / f"comic.{fmt}"

    # Dedup: if an export already exists and is at least as new as the latest
    # compose page artifact, hand it back instead of re-rendering the whole
    # book. Caller passes force=true to bypass (e.g. after editing pages).
    if not force and export_path.exists() and _export_is_fresh(project_dir, export_path):
        url = None
        if r2_configured():
            url = upload_export(user_id, project_dir.name, f"comic.{fmt}", export_path.read_bytes())
        capture_server_event(
            "export_succeeded",
            user_id=user_id,
            project_id=project_id,
            request_id=getattr(request.state, "request_id", None),
            properties={"format": fmt, "cached": True},
        )
        return {"status": "exists", "path": f"comic.{fmt}", "url": url}

    # Concurrency guard: composing the same project concurrently is wasted work
    # (and the renderer is CPU/memory bound). One export per project at a time.
    lock = _get_export_lock(request.app, project_dir.name)
    if lock.locked():
        raise HTTPException(409, "An export for this project is already running")
    async with lock:
        # The stage expects a StageRuntime, not a raw PipelineState — passing the
        # state directly crashes on the first ctx.log() call.
        ctx = StageRuntime("compose", state, project_dir)
        await s8_compose.run(config, project_dir, ctx, formats=[fmt], rebuild=False)

        if not export_path.exists():
            raise HTTPException(500, f"Export failed — {fmt} file not created")

        url = None
        if r2_configured():
            url = upload_export(user_id, project_dir.name, f"comic.{fmt}", export_path.read_bytes())

    capture_server_event(
        "export_succeeded",
        user_id=user_id,
        project_id=project_id,
        request_id=getattr(request.state, "request_id", None),
        properties={"format": fmt, "cached": False},
    )
    return {"status": "done", "path": f"comic.{fmt}", "url": url}


@router.get("/{fmt}")
def download_export(
    fmt: str,
    project=Depends(get_project),
    user_id: str = Depends(get_current_user),
):
    project_dir, config, state = project
    if fmt not in ("pdf", "cbz"):
        raise HTTPException(400, "Format must be 'pdf' or 'cbz'")

    export_path = project_dir / "exports" / f"comic.{fmt}"
    if not export_path.exists():
        raise HTTPException(404, f"No {fmt} export found. Run export first.")

    if r2_configured():
        return RedirectResponse(export_url(user_id, project_dir.name, f"comic.{fmt}"))

    media = "application/pdf" if fmt == "pdf" else "application/zip"
    return FileResponse(export_path, media_type=media, filename=f"comic.{fmt}")


def _latest_artifact_mtime(project_dir) -> float:
    """Most recent mtime across artifacts that feed PDF/CBZ rendering.

    Used to decide whether a cached export file is still fresh: if any source
    artifact changed after the export was built, we must re-render.
    """
    latest = 0.0
    compose_dir = project_dir / "compose"
    if compose_dir.is_dir():
        for sub in ("pages", "panels"):
            d = compose_dir / sub
            if d.is_dir():
                for p in d.rglob("*"):
                    if p.is_file():
                        try:
                            latest = max(latest, p.stat().st_mtime)
                        except OSError:
                            pass
    # The renderer loads project-level lettering style from assembly/, outside
    # the compose tree. A lettering preset/reroll must invalidate old exports.
    style_path = lettering_style_path(project_dir)
    if style_path.exists():
        try:
            latest = max(latest, style_path.stat().st_mtime)
        except OSError:
            pass
    return latest


def _export_is_fresh(project_dir, export_path) -> bool:
    """True if the export file is newer than every artifact that feeds it."""
    try:
        export_mtime = export_path.stat().st_mtime
    except OSError:
        return False
    return export_mtime >= _latest_artifact_mtime(project_dir)


_EXPORT_LOCKS_ATTR = "_export_locks"


def _get_export_lock(app, project_name: str) -> asyncio.Lock:
    """One asyncio lock per project name, scoped to the app instance."""
    locks = getattr(app.state, _EXPORT_LOCKS_ATTR, None)
    if locks is None:
        locks = {}
        setattr(app.state, _EXPORT_LOCKS_ATTR, locks)
    lock = locks.get(project_name)
    if lock is None:
        lock = asyncio.Lock()
        locks[project_name] = lock
    return lock
