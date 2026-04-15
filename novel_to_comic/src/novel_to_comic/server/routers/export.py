"""Export trigger and file download."""

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse

from novel_to_comic.stages import s7_assemble

from ..deps import get_project

router = APIRouter()


@router.post("/")
async def trigger_export(
    format: str = Query("pdf"),
    project=Depends(get_project),
):
    project_dir, config, state = project
    fmt = format.lower()
    if fmt not in ("pdf", "cbz"):
        raise HTTPException(400, "Format must be 'pdf' or 'cbz'")

    # Render existing JSON (rebuild=False) — respects any page edits
    await s7_assemble.run(config, project_dir, state, formats=[fmt], rebuild=False)

    export_path = project_dir / "exports" / f"comic.{fmt}"
    if not export_path.exists():
        raise HTTPException(500, f"Export failed — {fmt} file not created")
    return {"status": "done", "path": f"comic.{fmt}"}


@router.get("/{fmt}")
def download_export(fmt: str, project=Depends(get_project)):
    project_dir, config, state = project
    if fmt not in ("pdf", "cbz"):
        raise HTTPException(400, "Format must be 'pdf' or 'cbz'")

    export_path = project_dir / "exports" / f"comic.{fmt}"
    if not export_path.exists():
        raise HTTPException(404, f"No {fmt} export found. Run export first.")

    media = "application/pdf" if fmt == "pdf" else "application/zip"
    return FileResponse(
        export_path,
        media_type=media,
        filename=f"comic.{fmt}",
    )
