"""ComicPage JSON CRUD, HTML preview, and project file serving."""

import json
import mimetypes
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse

from novel_to_comic.config import Config, LANGUAGE_NAMES, save_config
from novel_to_comic.assembly.html_renderer import build_page_html, resolve_theme, write_theme_css
from novel_to_comic.models.comic_page import Bubble, ComicPage, Sfx

from ..deps import get_project

router = APIRouter()


def _pages_dir(project_dir: Path) -> Path:
    return project_dir / "assembly" / "pages"


def _load_page(project_dir: Path, page_num: int) -> ComicPage:
    path = _pages_dir(project_dir) / f"page_{page_num:03d}.json"
    if not path.exists():
        raise HTTPException(404, f"Page {page_num} not found")
    return ComicPage.model_validate_json(path.read_text())


STYLE_VAR_ALLOWLIST = {
    "--panel-border",
    "--panel-border-width",
    "--panel-bg",
    "--caption-bg",
    "--caption-border",
    "--caption-color",
    "--caption-font-size",
    "--bubble-bg",
    "--bubble-border",
    "--bubble-border-width",
    "--bubble-radius",
    "--bubble-font-size",
    "--bubble-padding",
    "--bubble-max-width",
    "--bubble-center-width",
    "--speaker-color",
    "--speaker-font-size",
    "--thought-border-style",
    "--thought-radius",
    "--sfx-color",
    "--sfx-shadow",
    "--sfx-font-size",
    "--page-num-color",
    "--page-num-font-size",
}


def _sanitize_style_vars(raw: dict) -> dict[str, str]:
    clean: dict[str, str] = {}
    for key, value in raw.items():
        if key not in STYLE_VAR_ALLOWLIST:
            continue
        if not isinstance(value, str):
            continue
        value = value.strip()
        if not value or len(value) > 96:
            continue
        if any(token in value.lower() for token in ("url(", "expression(", "javascript:", "</")):
            continue
        clean[key] = value
    return clean


def _fallback_lettering_style(style_template: str) -> dict[str, str]:
    low = style_template.lower()
    if any(word in low for word in ("noir", "monochrome", "black and white", "shadow")):
        return {
            "--panel-border": "#E6E6E6",
            "--panel-border-width": "3px",
            "--caption-bg": "#1D1D1D",
            "--caption-border": "#7A7A7A",
            "--caption-color": "#F1F1F1",
            "--bubble-bg": "#F2F2F2",
            "--bubble-border": "#111111",
            "--bubble-border-width": "3px",
            "--speaker-color": "#444444",
            "--sfx-color": "#FFFFFF",
            "--sfx-shadow": "#000000",
        }
    if any(word in low for word in ("manga", "anime", "ink", "screentone")):
        return {
            "--panel-border": "#000000",
            "--panel-border-width": "2px",
            "--caption-bg": "#FFFFFF",
            "--caption-border": "#000000",
            "--caption-color": "#000000",
            "--bubble-bg": "#FFFFFF",
            "--bubble-border": "#000000",
            "--bubble-border-width": "2px",
            "--bubble-radius": "24px",
            "--bubble-font-size": "21px",
            "--sfx-color": "#000000",
            "--sfx-shadow": "transparent",
            "--thought-border-style": "solid",
        }
    if any(word in low for word in ("vintage", "risograph", "screen-print", "poster", "pulp")):
        return {
            "--panel-border": "#5C2E00",
            "--panel-border-width": "4px",
            "--caption-bg": "#FFE2A3",
            "--caption-border": "#8B4513",
            "--caption-color": "#4A2600",
            "--bubble-bg": "#FFF4C7",
            "--bubble-border": "#6E3511",
            "--bubble-border-width": "3px",
            "--speaker-color": "#8B2500",
            "--sfx-color": "#9E1B12",
            "--sfx-shadow": "#2B1000",
        }
    if any(word in low for word in ("watercolor", "paint", "gouache", "oil", "pastel")):
        return {
            "--panel-border": "#4A3728",
            "--panel-border-width": "3px",
            "--caption-bg": "#E8DCC8",
            "--caption-border": "#6C5847",
            "--caption-color": "#2A1A0A",
            "--bubble-bg": "#FFFDF7",
            "--bubble-border": "#4A3728",
            "--bubble-border-width": "2px",
            "--bubble-radius": "18px",
            "--sfx-color": "#7B3B00",
            "--sfx-shadow": "#2A1000",
        }
    return {
        "--panel-border": "#111111",
        "--panel-border-width": "3px",
        "--caption-bg": "#F7F0DC",
        "--caption-border": "#9B8A5A",
        "--caption-color": "#3A2A10",
        "--bubble-bg": "#FFFFFF",
        "--bubble-border": "#1A1A1A",
        "--bubble-border-width": "2px",
        "--bubble-radius": "14px",
        "--bubble-font-size": "19px",
        "--speaker-color": "#664400",
        "--sfx-color": "#CC1111",
        "--sfx-shadow": "#000000",
    }


async def _generate_lettering_style(config: Config) -> dict[str, str]:
    if not config.gemini_api_key:
        return _fallback_lettering_style(config.style_template)

    from novel_to_comic.clients import gemini

    system = (
        "You are a comic book lettering and production designer. Given an image generation style, "
        "choose CSS custom property values for panel borders, narration captions, speech bubbles, "
        "thought bubbles, SFX, and page numbers. Return JSON only. Use readable lettering with "
        "strong contrast. Do not use url(), external assets, gradients, or CSS functions except simple px/% values."
    )
    user = (
        f"Image generation style:\n{config.style_template}\n\n"
        "Return an object with a short label, rationale, and a vars object. "
        "The vars object may include only these keys:\n"
        f"{', '.join(sorted(STYLE_VAR_ALLOWLIST))}\n\n"
        "Example shape: "
        '{"label":"Noir Lettering","rationale":"...","vars":{"--panel-border":"#111111","--bubble-bg":"#FFFFFF"}}'
    )
    try:
        result = await gemini.generate_json(
            config=config,
            model=config.prompt_model,
            system_prompt=system,
            user_content=user,
            temperature=0.45,
            max_output_tokens=1400,
        )
    except Exception:
        return _fallback_lettering_style(config.style_template)

    vars_raw = result.get("vars", result) if isinstance(result, dict) else {}
    generated = _sanitize_style_vars(vars_raw)
    return generated or _fallback_lettering_style(config.style_template)


async def _translate_text_items(config: Config, items: list[dict]) -> dict[str, str]:
    """Translate editable lettering text items and return {id: translated_text}."""
    if not items:
        return {}
    if not config.gemini_api_key:
        raise HTTPException(400, "Gemini API key is required to translate existing page text")

    from novel_to_comic.clients import gemini

    system = (
        "You are a literary comic localization editor. Translate only user-facing comic lettering "
        f"into natural {config.language_name()}. Preserve tone, character voice, punctuation intent, "
        "speaker names, IDs, JSON keys, and item order. Do not summarize, omit, or add dialogue. "
        "Return JSON only."
    )
    user = (
        f"Target language: {config.language_name()} ({config.language_code()})\n\n"
        "Translate each item's text field. Return exactly this shape:\n"
        '{"items":[{"id":"same id","text":"translated text"}]}\n\n'
        f"Items:\n{json.dumps(items, ensure_ascii=False)}"
    )
    result = await gemini.generate_json(
        config=config,
        model=config.prompt_model,
        system_prompt=system,
        user_content=user,
        temperature=0.2,
        max_output_tokens=6000,
    )
    if isinstance(result, dict):
        raw_items = result.get("items", [])
    elif isinstance(result, list):
        raw_items = result
    else:
        raw_items = []
    translations: dict[str, str] = {}
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        item_id = str(item.get("id", ""))
        text = item.get("text")
        if item_id and isinstance(text, str):
            translations[item_id] = text
    return translations


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


def _page_summaries(project_dir: Path) -> list[dict]:
    pd = _pages_dir(project_dir)
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
    if "style_vars" in body:
        cp.style_vars = _sanitize_style_vars(body["style_vars"])

    # Apply per-panel bubble/sfx updates
    if "panels" in body:
        panel_map = {p.id: p for p in cp.panels}
        for panel_patch in body["panels"]:
            panel = panel_map.get(panel_patch.get("id", ""))
            if not panel:
                continue

            # ── Remove bubbles ──
            remove_ids = panel_patch.get("remove_bubble_ids", [])
            if remove_ids:
                panel.bubbles = [b for b in panel.bubbles if b.id not in remove_ids]

            # ── Update or add bubbles ──
            if "bubbles" in panel_patch:
                bubble_map = {b.id: b for b in panel.bubbles}
                for bp in panel_patch["bubbles"]:
                    bubble = bubble_map.get(bp.get("id", ""))
                    if bubble:
                        for field in (
                            "x", "y", "width", "side", "text", "type",
                            "tail_x", "tail_y", "tail_direction",
                            "font_family", "font_size", "font_color",
                            "fill_color", "border_color", "border_width",
                            "border_radius",
                        ):
                            if field in bp:
                                setattr(bubble, field, bp[field])
                    else:
                        # New bubble — generate stable ID
                        next_idx = len(panel.bubbles) + 1
                        new_id = bp.get("id", "") or f"{panel.id}-b{next_idx}"
                        if new_id.startswith("new-"):
                            new_id = f"{panel.id}-b{next_idx}"
                        panel.bubbles.append(Bubble(
                            id=new_id,
                            type=bp.get("type", "speech"),
                            text=bp.get("text", ""),
                            side=bp.get("side", "left"),
                            font_family=bp.get("font_family"),
                            font_size=bp.get("font_size"),
                            font_color=bp.get("font_color"),
                            fill_color=bp.get("fill_color"),
                            border_color=bp.get("border_color"),
                            border_width=bp.get("border_width"),
                            border_radius=bp.get("border_radius"),
                        ))

            # ── Reorder bubbles ──
            if "bubble_order" in panel_patch:
                order = panel_patch["bubble_order"]
                id_to_bubble = {b.id: b for b in panel.bubbles}
                ordered = [id_to_bubble[bid] for bid in order if bid in id_to_bubble]
                remaining = [b for b in panel.bubbles if b.id not in set(order)]
                panel.bubbles = ordered + remaining

            # ── Remove SFX ──
            if panel_patch.get("remove_sfx"):
                panel.sfx = None

            # ── Update or create SFX ──
            elif "sfx" in panel_patch:
                sfx_data = panel_patch["sfx"]
                if panel.sfx:
                    for field in ("x", "y", "rotation", "font_size", "text"):
                        if field in sfx_data:
                            setattr(panel.sfx, field, sfx_data[field])
                else:
                    panel.sfx = Sfx(text=sfx_data.get("text", "SFX!"))

    path = _pages_dir(project_dir) / f"page_{page_num:03d}.json"
    path.write_text(cp.model_dump_json(indent=2))
    return cp.model_dump()


@router.post("/pages/style-vars/generate")
async def generate_page_style_vars(request: Request, project=Depends(get_project)):
    """Generate page-level lettering/panel CSS variables from the active image style."""
    project_dir, config, state = project

    style_vars = await _generate_lettering_style(config)
    pd = _pages_dir(project_dir)
    page_paths = sorted(pd.glob("page_*.json"))
    if not page_paths:
        raise HTTPException(404, "No pages found")

    for path in page_paths:
        cp = ComicPage.model_validate_json(path.read_text())
        cp.style_vars = style_vars
        path.write_text(cp.model_dump_json(indent=2))

    return {"status": "updated", "style_vars": style_vars, "pages": _page_summaries(project_dir)}


@router.post("/pages/translate-bubbles")
async def translate_page_bubbles(body: dict, project=Depends(get_project)):
    """Translate all existing editable bubble/narration text across assembled pages."""
    project_dir, config, state = project
    target_language = body.get("target_language")
    if target_language is not None:
        if target_language not in LANGUAGE_NAMES:
            raise HTTPException(400, "target_language must be one of: en, es, fr")
        config.target_language = target_language
        save_config(config, project_dir)

    pd = _pages_dir(project_dir)
    page_paths = sorted(pd.glob("page_*.json"))
    if not page_paths:
        raise HTTPException(404, "No pages found")

    pages = [ComicPage.model_validate_json(path.read_text()) for path in page_paths]
    items: list[dict] = []
    for cp in pages:
        for panel in cp.panels:
            for bubble in panel.bubbles:
                text = bubble.text.strip()
                if text:
                    items.append({
                        "id": f"{cp.page_number}:{panel.id}:{bubble.id}",
                        "type": bubble.type,
                        "speaker": bubble.speaker_name,
                        "text": bubble.text,
                    })

    translations = await _translate_text_items(config, items)
    updated = 0
    for cp, path in zip(pages, page_paths):
        changed = False
        for panel in cp.panels:
            for bubble in panel.bubbles:
                item_id = f"{cp.page_number}:{panel.id}:{bubble.id}"
                translated = translations.get(item_id)
                if translated and translated != bubble.text:
                    bubble.text = translated
                    changed = True
                    updated += 1
        if changed:
            path.write_text(cp.model_dump_json(indent=2))

    return {
        "status": "updated",
        "target_language": config.language_code(),
        "updated": updated,
        "pages": _page_summaries(project_dir),
    }


@router.post("/pages/reflow")
def reflow_pages(body: dict, project=Depends(get_project)):
    """Redistribute all panels into pages with N panels per page."""
    project_dir, config, state = project
    panels_per_page = int(body.get("panels_per_page", 0))
    if panels_per_page < 1 or panels_per_page > 6:
        raise HTTPException(400, "panels_per_page must be between 1 and 6")

    pd = _pages_dir(project_dir)
    page_paths = sorted(pd.glob("page_*.json"))
    if not page_paths:
        raise HTTPException(404, "No pages found")

    source_pages = [ComicPage.model_validate_json(path.read_text()) for path in page_paths]
    all_panels = []
    for cp in source_pages:
        for panel in cp.panels:
            panel.grid_column = None
            panel.grid_row = None
            all_panels.append(panel)

    theme = source_pages[0].theme
    layout = str(panels_per_page)
    new_count = 0
    for start in range(0, len(all_panels), panels_per_page):
        new_count += 1
        chunk = all_panels[start:start + panels_per_page]
        cp = ComicPage(
            page_number=new_count,
            theme=theme,
            layout=layout,
            panels=chunk,
        )
        (pd / f"page_{new_count:03d}.json").write_text(cp.model_dump_json(indent=2))

    for stale in page_paths[new_count:]:
        stale.unlink()

    return _page_summaries(project_dir)


@router.put("/pages/{page_num}")
def replace_page(page_num: int, body: dict, project=Depends(get_project)):
    """Full page replacement (used by undo/redo)."""
    project_dir, config, state = project
    cp = ComicPage.model_validate(body)
    cp.page_number = page_num
    path = _pages_dir(project_dir) / f"page_{page_num:03d}.json"
    if not path.exists():
        raise HTTPException(404, f"Page {page_num} not found")
    path.write_text(cp.model_dump_json(indent=2))
    return cp.model_dump()


@router.post("/pages/reorder")
def reorder_panels(body: dict, project=Depends(get_project)):
    """Reorder panels within and across pages.

    Body: { "pages": [{ "page_number": N, "panel_ids": ["id1", "id2"] }, ...] }
    """
    project_dir, config, state = project
    pages_spec = body.get("pages", [])
    if not pages_spec:
        raise HTTPException(400, "Provide non-empty 'pages' list")

    pd = _pages_dir(project_dir)

    # Collect all panels from affected pages into a flat map
    affected_nums = {p["page_number"] for p in pages_spec}
    all_panels = {}
    for num in affected_nums:
        path = pd / f"page_{num:03d}.json"
        if not path.exists():
            raise HTTPException(404, f"Page {num} not found")
        cp = ComicPage.model_validate_json(path.read_text())
        for panel in cp.panels:
            all_panels[panel.id] = panel

    # Redistribute panels
    for page_spec in pages_spec:
        num = page_spec["page_number"]
        panel_ids = page_spec["panel_ids"]
        path = pd / f"page_{num:03d}.json"
        cp = ComicPage.model_validate_json(path.read_text())
        new_panels = [all_panels[pid] for pid in panel_ids if pid in all_panels]
        cp.panels = new_panels
        count = len(new_panels)
        cp.layout = str(min(count, 6)) if count <= 6 else "many"
        path.write_text(cp.model_dump_json(indent=2))

    return {"status": "ok"}


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
