"""ComicPage JSON CRUD, HTML preview, and project file serving."""

import json
import mimetypes
import re
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse

from novel_to_comic.config import Config, LANGUAGE_NAMES, save_config
from novel_to_comic.assembly.html_renderer import build_page_html, resolve_theme, write_theme_css, THEMES
from novel_to_comic.layout_planning import (
    apply_page_layout_preset,
    apply_panel_override,
    dump_structural_response,
    load_layout_plan,
    persist_projected_pages,
    repaginate_layout_plan,
    reorder_planned_pages,
    save_layout_plan,
)
from novel_to_comic.models.comic_page import Bubble, ComicPage, Sfx, BUBBLE_PRESETS, CharacterVoice
from novel_to_comic.models.story_bible import StoryBible

from ..deps import get_project

router = APIRouter()


def _pages_dir(project_dir: Path) -> Path:
    return project_dir / "compose" / "pages"


def _load_page(project_dir: Path, page_num: int) -> ComicPage:
    path = _pages_dir(project_dir) / f"page_{page_num:03d}.json"
    if not path.exists():
        raise HTTPException(404, f"Page {page_num} not found")
    return ComicPage.model_validate_json(path.read_text())


def _load_story_bible(project_dir: Path) -> StoryBible:
    path = project_dir / "story_bible.json"
    if not path.exists():
        raise HTTPException(404, "Story bible not found")
    return StoryBible.model_validate_json(path.read_text())


def _project_structural_pages(project_dir: Path, config: Config) -> list[ComicPage]:
    story_bible = _load_story_bible(project_dir)
    return persist_projected_pages(project_dir, story_bible, resolve_theme(config))


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
    color_keys = {
        "--panel-border",
        "--panel-bg",
        "--caption-bg",
        "--caption-border",
        "--caption-color",
        "--bubble-bg",
        "--bubble-border",
        "--speaker-color",
        "--sfx-color",
        "--sfx-shadow",
        "--page-num-color",
    }
    px_ranges = {
        "--panel-border-width": (1, 12),
        "--caption-font-size": (12, 44),
        "--bubble-border-width": (1, 10),
        "--bubble-radius": (6, 120),
        "--bubble-font-size": (16, 54),
        "--speaker-font-size": (10, 36),
        "--thought-radius": (18, 180),
        "--sfx-font-size": (20, 180),
        "--page-num-font-size": (14, 96),
    }
    pct_ranges = {
        "--bubble-max-width": (38, 95),
        "--bubble-center-width": (45, 98),
    }

    def _fmt_num(value: float) -> str:
        return str(int(value)) if float(value).is_integer() else f"{value:.2f}".rstrip("0").rstrip(".")

    def _parse_px(text: str) -> float | None:
        match = re.fullmatch(r"(\d+(?:\.\d+)?)px", text)
        if not match:
            return None
        return float(match.group(1))

    def _parse_pct(text: str) -> float | None:
        match = re.fullmatch(r"(\d+(?:\.\d+)?)%", text)
        if not match:
            return None
        return float(match.group(1))

    def _is_color(text: str) -> bool:
        return bool(re.fullmatch(r"(?:#[0-9a-fA-F]{6}|#[0-9a-fA-F]{3}|transparent)", text))

    def _sanitize_value(key: str, text: str) -> str | None:
        if key in color_keys:
            return text if _is_color(text) else None
        if key in px_ranges:
            n = _parse_px(text)
            if n is None:
                return None
            lo, hi = px_ranges[key]
            if n < lo or n > hi:
                return None
            return f"{_fmt_num(n)}px"
        if key in pct_ranges:
            n = _parse_pct(text)
            if n is None:
                return None
            lo, hi = pct_ranges[key]
            if n < lo or n > hi:
                return None
            return f"{_fmt_num(n)}%"
        if key == "--bubble-padding":
            parts = text.split()
            if len(parts) not in (1, 2):
                return None
            parsed: list[float] = []
            for part in parts:
                n = _parse_px(part)
                if n is None or n < 3 or n > 28:
                    return None
                parsed.append(n)
            return " ".join(f"{_fmt_num(n)}px" for n in parsed)
        if key == "--thought-border-style":
            return text if text in {"solid", "dashed", "dotted"} else None
        return None

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
        sanitized = _sanitize_value(key, value)
        if sanitized is not None:
            clean[key] = sanitized
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
            "--bubble-font-size": "25px",
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
        "--bubble-font-size": "24px",
        "--speaker-color": "#664400",
        "--sfx-color": "#CC1111",
        "--sfx-shadow": "#000000",
    }


async def _generate_lettering_style(config: Config) -> dict[str, str]:
    if not config.google_use_vertex_ai and not config.gemini_api_key:
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
    if not config.google_use_vertex_ai and not config.gemini_api_key:
        raise HTTPException(400, "Google Gemini auth is required to translate existing page text")

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
            if "image_offset_x" in panel_patch:
                panel.image_offset_x = panel_patch["image_offset_x"]
            if "image_offset_y" in panel_patch:
                panel.image_offset_y = panel_patch["image_offset_y"]

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


@router.post("/pages/set-theme")
def set_theme(body: dict, project=Depends(get_project)):
    """Bulk-set the theme for all pages at once."""
    project_dir, config, state = project
    theme = body.get("theme", "default")
    if theme not in THEMES:
        raise HTTPException(400, f"Invalid theme. Must be one of: {', '.join(THEMES.keys())}")

    pd = _pages_dir(project_dir)
    page_paths = sorted(pd.glob("page_*.json"))
    if not page_paths:
        raise HTTPException(404, "No pages found")

    updated = 0
    for path in page_paths:
        cp = ComicPage.model_validate_json(path.read_text())
        cp.theme = theme
        path.write_text(cp.model_dump_json(indent=2))
        updated += 1

    return {"status": "ok", "theme": theme, "updated": updated}


@router.get("/pages/bubble-presets")
def get_bubble_presets(project=Depends(get_project)):
    """Return the current bubble preset map."""
    return BUBBLE_PRESETS


@router.post("/pages/apply-bubble-preset")
def apply_bubble_preset(body: dict, project=Depends(get_project)):
    """Apply a bubble preset to all bubbles of that type across all pages."""
    project_dir, config, state = project
    preset_name = body.get("preset_name", "")
    if preset_name not in BUBBLE_PRESETS:
        raise HTTPException(400, f"Invalid preset. Must be one of: {', '.join(BUBBLE_PRESETS.keys())}")

    preset = BUBBLE_PRESETS[preset_name]
    pd = _pages_dir(project_dir)
    page_paths = sorted(pd.glob("page_*.json"))
    if not page_paths:
        raise HTTPException(404, "No pages found")

    updated_bubbles = 0
    for path in page_paths:
        cp = ComicPage.model_validate_json(path.read_text())
        changed = False
        for panel in cp.panels:
            for bubble in panel.bubbles:
                if bubble.type == preset_name:
                    for field, value in preset.items():
                        if field == "border_radius":
                            bubble.border_radius = int(value)
                        elif field == "border_width":
                            bubble.border_width = int(value)
                        elif field == "border_color":
                            bubble.border_color = value
                        elif field == "fill_color":
                            bubble.fill_color = value
                    changed = True
                    updated_bubbles += 1
        if changed:
            path.write_text(cp.model_dump_json(indent=2))

    return {"status": "ok", "preset_name": preset_name, "updated_bubbles": updated_bubbles}


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


@router.post("/pages/{page_num}/translate-bubbles")
async def translate_single_page_bubbles(page_num: int, body: dict, project=Depends(get_project)):
    """Translate bubble/narration text for a single page."""
    project_dir, config, state = project
    target_language = body.get("target_language")
    if target_language is not None:
        if target_language not in LANGUAGE_NAMES:
            raise HTTPException(400, "target_language must be one of: en, es, fr")
        config.target_language = target_language
        save_config(config, project_dir)

    cp = _load_page(project_dir, page_num)
    items: list[dict] = []
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
    for panel in cp.panels:
        for bubble in panel.bubbles:
            item_id = f"{cp.page_number}:{panel.id}:{bubble.id}"
            translated = translations.get(item_id)
            if translated and translated != bubble.text:
                bubble.text = translated
                updated += 1

    if updated:
        path = _pages_dir(project_dir) / f"page_{page_num:03d}.json"
        path.write_text(cp.model_dump_json(indent=2))

    return {
        "status": "ok",
        "target_language": config.language_code(),
        "updated": updated,
        "page": cp.model_dump(),
    }


LAYOUT_PRESETS: dict[str, list[tuple[str, str]]] = {
    "2x2": [("1/2", "1/2"), ("2/3", "1/2"), ("1/2", "2/3"), ("2/3", "2/3")],
    "2x3": [("1/2", "1/2"), ("2/3", "1/2"), ("1/2", "2/3"), ("2/3", "2/3"), ("1/2", "3/4"), ("2/3", "3/4")],
    "3x2": [("1/3", "1/2"), ("2/4", "1/2"), ("1/3", "2/3"), ("2/4", "2/3"), ("1/3", "3/4"), ("2/4", "3/4")],
    "splash+4": [("1/3", "1/3"), ("1/2", "3/4"), ("2/3", "3/4"), ("1/2", "4/5"), ("2/3", "4/5")],
    "vertical_trio": [("1/2", "1/2"), ("1/2", "2/3"), ("1/2", "3/4")],
    "wide_opening": [("1/3", "1/2")],
}


@router.post("/pages/{page_num}/reflow")
def reflow_single_page(page_num: int, body: dict, project=Depends(get_project)):
    """Apply a planner-backed layout preset to a single page, then reproject."""
    project_dir, config, state = project
    preset_name = body.get("layout_preset", "")
    if preset_name not in LAYOUT_PRESETS:
        raise HTTPException(400, f"Invalid layout preset. Must be one of: {', '.join(LAYOUT_PRESETS.keys())}")
    plan = load_layout_plan(project_dir)
    try:
        apply_page_layout_preset(plan, page_num, preset_name)
    except KeyError as exc:
        raise HTTPException(404, f"Page {page_num} not found in layout plan") from exc
    save_layout_plan(project_dir, plan)
    _project_structural_pages(project_dir, config)
    return _load_page(project_dir, page_num).model_dump()


@router.post("/pages/reflow")
def reflow_pages(body: dict, project=Depends(get_project)):
    """Repaginate through the planner, then regenerate projected pages."""
    project_dir, config, state = project
    panels_per_page = int(body.get("panels_per_page", 0))
    if panels_per_page < 1 or panels_per_page > 6:
        raise HTTPException(400, "panels_per_page must be between 1 and 6")
    plan = load_layout_plan(project_dir)
    repaginate_layout_plan(plan, panels_per_page=panels_per_page)
    save_layout_plan(project_dir, plan)
    _project_structural_pages(project_dir, config)
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

    plan = load_layout_plan(project_dir)
    reorder_planned_pages(plan, pages_spec)
    save_layout_plan(project_dir, plan)
    pages = _project_structural_pages(project_dir, config)
    return dump_structural_response(plan, pages)


@router.post("/pages/structural")
def apply_structural_operation(body: dict, project=Depends(get_project)):
    """Apply planner-backed structural edits from Compose and reproject pages."""
    project_dir, config, state = project
    operation = body.get("operation", "")
    if not operation:
        raise HTTPException(400, "Missing operation")

    plan = load_layout_plan(project_dir)

    try:
        if operation == "panel_override":
            panel_id = body.get("planned_panel_id", "")
            if not panel_id:
                raise HTTPException(400, "planned_panel_id is required")
            apply_panel_override(
                plan,
                panel_id,
                importance=body.get("importance"),
                shape_intent=body.get("shape_intent"),
                generation_mode=body.get("generation_mode"),
            )
        elif operation == "page_layout_preset":
            page_number = int(body.get("page_number", 0))
            preset_name = body.get("layout_preset", "")
            if preset_name not in LAYOUT_PRESETS:
                raise HTTPException(400, f"Invalid layout preset. Must be one of: {', '.join(LAYOUT_PRESETS.keys())}")
            apply_page_layout_preset(plan, page_number, preset_name)
        elif operation == "repaginate":
            panels_per_page = int(body.get("panels_per_page", 0))
            if panels_per_page < 1 or panels_per_page > 6:
                raise HTTPException(400, "panels_per_page must be between 1 and 6")
            repaginate_layout_plan(plan, panels_per_page=panels_per_page)
        elif operation == "reorder":
            pages_spec = body.get("pages", [])
            if not pages_spec:
                raise HTTPException(400, "Provide non-empty 'pages' list")
            reorder_planned_pages(plan, pages_spec)
        else:
            raise HTTPException(400, f"Unknown operation: {operation}")
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc

    save_layout_plan(project_dir, plan)
    pages = _project_structural_pages(project_dir, config)
    response = dump_structural_response(plan, pages)
    page_number = body.get("page_number")
    if isinstance(page_number, (int, float)):
        page = next((page for page in pages if page.page_number == int(page_number)), None)
        if page is not None:
            response["page"] = page.model_dump()
    return response


# ── Character Voices ──────────────────────────────────────────────────────────


def _voices_path(project_dir: Path) -> Path:
    return project_dir / "assembly" / "character_voices.json"


def _load_voices(project_dir: Path) -> dict[str, dict]:
    path = _voices_path(project_dir)
    if not path.exists():
        return {}
    return json.loads(path.read_text())


def _save_voices(project_dir: Path, voices: dict[str, dict]) -> None:
    path = _voices_path(project_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(voices, indent=2))


@router.get("/pages/character-voices")
def get_character_voices(project=Depends(get_project)):
    """Return all character voice presets."""
    project_dir, config, state = project
    return _load_voices(project_dir)


@router.put("/pages/character-voices/{character_id}")
def put_character_voice(character_id: str, body: dict, project=Depends(get_project)):
    """Upsert a voice style for a character."""
    project_dir, config, state = project
    voice = CharacterVoice(
        character_id=character_id,
        character_name=body.get("character_name", character_id),
        font_family=body.get("font_family"),
        font_size=body.get("font_size"),
        font_color=body.get("font_color"),
        fill_color=body.get("fill_color"),
        border_color=body.get("border_color"),
        border_width=body.get("border_width"),
        border_radius=body.get("border_radius"),
    )
    voices = _load_voices(project_dir)
    voices[character_id] = voice.model_dump(exclude_none=True)
    voices[character_id]["character_id"] = character_id
    voices[character_id]["character_name"] = voice.character_name
    _save_voices(project_dir, voices)
    return voice.model_dump()


@router.delete("/pages/character-voices/{character_id}")
def delete_character_voice(character_id: str, project=Depends(get_project)):
    """Remove a character voice preset."""
    project_dir, config, state = project
    voices = _load_voices(project_dir)
    if character_id in voices:
        del voices[character_id]
        _save_voices(project_dir, voices)
    return {"status": "ok"}


# ── HTML preview ─────────────────────────────────────────────────────────────


@router.get("/pages/{page_num}/preview")
def page_preview(page_num: int, project_name: str, project=Depends(get_project)):
    project_dir, config, state = project
    cp = _load_page(project_dir, page_num)

    theme_name = resolve_theme(config)
    css_path = write_theme_css(project_dir, theme_name)
    custom_css = css_path.read_text()
    character_voices = _load_voices(project_dir)

    html = build_page_html(
        cp,
        project_dir,
        custom_css,
        character_voices=character_voices,
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
