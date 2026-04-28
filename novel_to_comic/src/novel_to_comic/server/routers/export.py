"""Export trigger and file download."""

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse, RedirectResponse

from novel_to_comic.stages import s7_assemble
from novel_to_comic.storage import export_url, r2_configured, upload_export

from ..auth import get_current_user
from ..deps import get_project

router = APIRouter()


@router.post("/")
async def trigger_export(
    format: str = Query("pdf"),
    project=Depends(get_project),
    user_id: str = Depends(get_current_user),
):
    project_dir, config, state = project
    fmt = format.lower()
    if fmt not in ("pdf", "cbz"):
        raise HTTPException(400, "Format must be 'pdf' or 'cbz'")

    await s7_assemble.run(config, project_dir, state, formats=[fmt], rebuild=False)

    export_path = project_dir / "exports" / f"comic.{fmt}"
    if not export_path.exists():
        raise HTTPException(500, f"Export failed — {fmt} file not created")

    url = None
    if r2_configured():
        url = upload_export(user_id, project_dir.name, f"comic.{fmt}", export_path.read_bytes())

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
