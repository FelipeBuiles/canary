"""ComicPage JSON CRUD, HTML preview, and project file serving."""

import mimetypes
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, HTMLResponse

from novel_to_comic.assembly.html_renderer import build_page_html, resolve_theme, write_theme_css
from novel_to_comic.models.comic_page import ComicPage

from ..deps import get_project

router = APIRouter()


def _pages_dir(project_dir: Path) -> Path:
    return project_dir / "assembly" / "pages"


def _load_page(project_dir: Path, page_num: int) -> ComicPage:
    path = _pages_dir(project_dir) / f"page_{page_num:03d}.json"
    if not path.exists():
        raise HTTPException(404, f"Page {page_num} not found")
    return ComicPage.model_validate_json(path.read_text())


# ── Pages CRUD ───────────────────────────────────────────────────────────────


@router.get("/pages/")
def list_pages(project=Depends(get_project)):
    project_dir, config, state = project
    pd = _pages_dir(project_dir)
    if not pd.exists():
        return []
    pages = []
    for f in sorted(pd.glob("page_*.json")):
        cp = ComicPage.model_validate_json(f.read_text())
        pages.append({
            "page_number": cp.page_number,
            "panel_count": len(cp.panels),
            "layout": cp.layout,
            "theme": cp.theme,
        })
    return pages


@router.get("/pages/{page_num}")
def get_page(page_num: int, project=Depends(get_project)):
    project_dir, config, state = project
    cp = _load_page(project_dir, page_num)
    return cp.model_dump()


@router.patch("/pages/{page_num}")
def update_page(page_num: int, body: dict, project=Depends(get_project)):
    project_dir, config, state = project
    cp = _load_page(project_dir, page_num)

    # Apply top-level fields
    if "theme" in body:
        cp.theme = body["theme"]
    if "layout" in body:
        cp.layout = body["layout"]

    # Apply per-panel bubble/sfx position updates
    if "panels" in body:
        panel_map = {p.id: p for p in cp.panels}
        for panel_patch in body["panels"]:
            panel = panel_map.get(panel_patch.get("id", ""))
            if not panel:
                continue
            if "bubbles" in panel_patch:
                bubble_map = {b.id: b for b in panel.bubbles}
                for bp in panel_patch["bubbles"]:
                    bubble = bubble_map.get(bp.get("id", ""))
                    if not bubble:
                        continue
                    for field in ("x", "y", "width", "side", "text"):
                        if field in bp:
                            setattr(bubble, field, bp[field])
            if "sfx" in panel_patch and panel.sfx:
                for field in ("x", "y", "rotation", "font_size", "text"):
                    if field in panel_patch["sfx"]:
                        setattr(panel.sfx, field, panel_patch["sfx"][field])

    path = _pages_dir(project_dir) / f"page_{page_num:03d}.json"
    path.write_text(cp.model_dump_json(indent=2))
    return cp.model_dump()


# ── HTML preview ─────────────────────────────────────────────────────────────


@router.get("/pages/{page_num}/preview")
def page_preview(page_num: int, project_name: str, project=Depends(get_project)):
    project_dir, config, state = project
    cp = _load_page(project_dir, page_num)

    theme_name = resolve_theme(config)
    css_path = write_theme_css(project_dir, theme_name)
    custom_css = css_path.read_text()

    html = build_page_html(
        cp,
        project_dir,
        custom_css,
        image_url_fn=lambda rel: f"/api/projects/{project_name}/files/{rel}",
        font_url_fn=lambda filename: f"/static/fonts/{filename}",
    )
    return HTMLResponse(html)


# ── File serving (images, refs, plates, etc.) ────────────────────────────────


@router.get("/files/{file_path:path}")
def serve_file(file_path: str, project=Depends(get_project)):
    project_dir, config, state = project
    full = (project_dir / file_path).resolve()

    # Path traversal guard
    if not str(full).startswith(str(project_dir.resolve())):
        raise HTTPException(403, "Access denied")
    if not full.is_file():
        raise HTTPException(404, "File not found")

    media_type = mimetypes.guess_type(str(full))[0] or "application/octet-stream"
    return FileResponse(full, media_type=media_type)
