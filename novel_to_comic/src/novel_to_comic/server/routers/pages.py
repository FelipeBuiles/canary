"""ComicPage JSON CRUD, HTML preview, and project file serving."""

import hashlib
import json
import mimetypes
import re
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import ValidationError

from novel_to_comic import artifacts
from novel_to_comic.config import Config, LANGUAGE_NAMES, save_config
from novel_to_comic.ai import ai_request_context
from novel_to_comic.assembly.html_renderer import build_page_html, resolve_theme, write_theme_css, THEMES, FONT_PAIRS
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
from novel_to_comic.models.comic_page import Bubble, ComicPage, Sfx, BUBBLE_PRESETS, CharacterVoice, normalize_sfx_text
from novel_to_comic.models.story_bible import StoryBible
from novel_to_comic.models.lettering import LetteringStyle
from novel_to_comic.assembly.lettering_style import load_lettering_style, save_lettering_style

from ..auth import get_current_user
from ..credits import debit_model_usage
from ..db import get_db
from ..deps import get_project

router = APIRouter()


def _pages_dir(project_dir: Path) -> Path:
    return artifacts.compose_pages_dir(project_dir)


def _load_page(project_dir: Path, page_num: int) -> ComicPage:
    if not artifacts.compose_page_path(project_dir, page_num).exists():
        raise HTTPException(404, f"Page {page_num} not found")
    return artifacts.read_compose_page(project_dir, page_num)


def _load_story_bible(project_dir: Path) -> StoryBible:
    if not artifacts.story_bible_path(project_dir).exists():
        raise HTTPException(404, "Story bible not found")
    return artifacts.read_story_bible(project_dir)


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
    "--bubble-padding",
    "--bubble-max-width",
    "--bubble-center-width",
    "--speaker-color",
    "--thought-border-style",
    "--thought-radius",
    "--sfx-color",
    "--sfx-shadow",
    "--page-num-color",
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
        "--caption-font-size": (14, 80),
        "--bubble-border-width": (1, 10),
        "--bubble-radius": (6, 120),
        "--thought-radius": (18, 180),
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


FONT_PAIR_MOODS = {
    "golden-age": "classic four-color comic - punchy display + clean comic lettering",
    "manga": "manga / anime ink - bold display + rounded gothic lettering",
    "horror": "gritty horror - dripping display + typewriter lettering",
    "painterly": "painterly / literary - brush display + elegant serif lettering",
    "kids": "friendly all-ages - rounded display + soft rounded lettering",
    "sci-fi": "technical sci-fi - angular geometric display + techy lettering",
}

PRESET_LABELS = {
    "default": ("Default", "Clean classic comic lettering."),
    "noir": ("Noir", "High-contrast monochrome - pale captions on dark ink."),
    "manga": ("Manga", "Crisp black-and-white manga lettering."),
    "vintage": ("Vintage", "Warm aged-paper Golden-Age treatment."),
    "painted": ("Painted", "Soft painterly tones for illustrated art."),
}

PRESET_FONT_PAIR = {
    "default": "golden-age",
    "noir": "golden-age",
    "manga": "manga",
    "vintage": "golden-age",
    "painted": "painterly",
}


def _style_hash(template: str) -> str:
    return hashlib.sha256((template or "").encode("utf-8")).hexdigest()[:16]


def _fallback_theme_and_pair(style_template: str) -> tuple[str, str]:
    """Keyword map from an image style to a (theme, font_pair) fallback."""
    low = (style_template or "").lower()
    if any(w in low for w in ("noir", "monochrome", "black and white", "grayscale", "shadow")):
        return "noir", "golden-age"
    if any(w in low for w in ("horror", "gothic", "grim", "eerie", "macabre", "creepy")):
        return "noir", "horror"
    if any(w in low for w in ("manga", "anime", "shonen", "shojo", "ink", "screentone", "japanese")):
        return "manga", "manga"
    if any(w in low for w in ("vintage", "retro", "golden age", "silver age", "risograph", "poster", "pulp")):
        return "vintage", "golden-age"
    if any(w in low for w in ("watercolor", "painted", "painterly", "gouache", "oil", "pastel")):
        return "painted", "painterly"
    if any(w in low for w in ("kids", "children", "cartoon", "cute", "whimsical", "all-ages")):
        return "default", "kids"
    if any(w in low for w in ("sci-fi", "scifi", "cyberpunk", "futuristic", "space", "mecha", "neon")):
        return "default", "sci-fi"
    return "default", "golden-age"


async def _generate_lettering_style(config: Config, *, reroll: bool = False) -> tuple[dict, object | None]:
    """Ask the model for a base theme, a curated font pair, and CSS-var overrides
    that match the image-generation style. Returns (fields, usage)."""
    from novel_to_comic.clients import text

    fb_theme, fb_pair = _fallback_theme_and_pair(config.style_template)

    system = (
        "You are a comic book lettering and production designer. Given an image "
        "generation style, choose a base theme, a font pair, and CSS custom property "
        "values for panel borders, narration captions, speech bubbles, thought "
        "bubbles, SFX, and page numbers. Return JSON only. Use readable lettering "
        "with strong contrast. Do not set font sizes or font families directly - the "
        "font pair controls type. Do not use url(), external assets, gradients, or "
        "CSS functions except simple px/% values."
    )
    pairs = "\n".join(f"- {k}: {v}" for k, v in FONT_PAIR_MOODS.items())
    user = (
        f"Image generation style:\n{config.style_template}\n\n"
        f"Choose theme (one of): {', '.join(THEMES)}\n"
        f"Choose font_pair (one of):\n{pairs}\n\n"
        "Return an object with: label (short), rationale (one sentence on why it "
        "fits the art), theme, font_pair, and a vars object. The vars object may "
        "include only these keys:\n"
        f"{', '.join(sorted(STYLE_VAR_ALLOWLIST))}\n\n"
        'Example: {"label":"Noir Lettering","rationale":"Pale captions read against '
        'heavy blacks.","theme":"noir","font_pair":"golden-age","vars":'
        '{"--panel-border":"#E6E6E6","--bubble-bg":"#F2F2F2"}}'
    )
    try:
        api_result = await text.generate_json(
            config=config,
            model=config.effective_prompt_model(),
            system_prompt=system,
            user_content=user,
            temperature=0.85 if reroll else 0.45,
            max_output_tokens=4096,
            feature="compose.lettering_style",
        )
        result = api_result.value
        usage = api_result.usage
    except Exception:
        return {
            "theme": fb_theme,
            "font_pair": fb_pair,
            "vars": {},
            "label": "Auto Lettering",
            "rationale": "Tuned to your selected style.",
            "source": "fallback",
        }, None

    if not isinstance(result, dict):
        result = {}
    theme = result.get("theme")
    font_pair = result.get("font_pair")
    raw_vars = result.get("vars")
    return {
        "theme": theme if theme in THEMES else fb_theme,
        "font_pair": font_pair if font_pair in FONT_PAIRS else fb_pair,
        "vars": _sanitize_style_vars(raw_vars if isinstance(raw_vars, dict) else {}),
        "label": str(result.get("label") or "Matched Lettering")[:80],
        "rationale": str(result.get("rationale") or "")[:240],
        "source": "ai",
    }, usage


async def _translate_text_items(config: Config, items: list[dict]) -> tuple[dict[str, str], object | None]:
    """Translate editable lettering text items and return {id: translated_text}."""
    if not items:
        return {}, None

    from novel_to_comic.clients import text

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
    api_result = await text.generate_json(
        config=config,
        model=config.effective_prompt_model(),
        system_prompt=system,
        user_content=user,
        temperature=0.2,
        max_output_tokens=6000,
        feature="compose.translate_text",
    )
    result = api_result.value
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
        item_text = item.get("text")
        if item_id and isinstance(item_text, str):
            translations[item_id] = item_text
    return translations, api_result.usage


# ── Pages CRUD ───────────────────────────────────────────────────────────────


@router.get("/pages/")
def list_pages(project=Depends(get_project)):
    project_dir, config, state = project
    if not _pages_dir(project_dir).exists():
        return []
    return _page_summaries(project_dir)


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


# ── Fixed-path routes ─────────────────────────────────────────────────────────
# These MUST be registered before the dynamic /pages/{page_num} routes below:
# FastAPI matches in registration order, and /pages/{page_num} would otherwise
# swallow them and 422 on the int conversion.


@router.get("/pages/bubble-presets")
def get_bubble_presets(project=Depends(get_project)):
    """Return the current bubble preset map."""
    return BUBBLE_PRESETS


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
    try:
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
    except ValidationError as exc:
        raise HTTPException(422, str(exc)) from exc
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


# ── Per-page routes ───────────────────────────────────────────────────────────


@router.get("/pages/{page_num}")
def get_page(page_num: int, project=Depends(get_project)):
    project_dir, config, state = project
    cp = _load_page(project_dir, page_num)
    return cp.model_dump()


_VALID_LAYOUTS = {"1", "2", "3", "4", "5", "6", "many"}


def _next_bubble_id(panel) -> str:
    """Generate a bubble ID that cannot collide with existing ones.

    ``len(bubbles) + 1`` collides after deletions (b1,b3 + new "b3"), so scan
    for the highest existing ``-b<N>`` suffix instead.
    """
    max_idx = 0
    for b in panel.bubbles:
        m = re.search(r"-b(\d+)$", b.id)
        if m:
            max_idx = max(max_idx, int(m.group(1)))
    return f"{panel.id}-b{max_idx + 1}"


@router.patch("/pages/{page_num}")
def update_page(page_num: int, body: dict, project=Depends(get_project)):
    project_dir, config, state = project
    cp = _load_page(project_dir, page_num)

    try:
        _apply_page_patch(cp, body)
    except ValidationError as exc:
        # Field assignments are validated (validate_assignment) so a bad patch
        # is rejected here instead of being written to disk, where it would
        # make the page JSON permanently unloadable.
        raise HTTPException(422, str(exc)) from exc

    artifacts.write_compose_page(project_dir, page_num, cp)
    return cp.model_dump()


def _apply_page_patch(cp: ComicPage, body: dict) -> None:
    # Apply top-level fields
    if "theme" in body:
        if body["theme"] not in THEMES:
            raise HTTPException(400, f"Invalid theme. Must be one of: {', '.join(THEMES.keys())}")
        cp.theme = body["theme"]
    if "layout" in body:
        if str(body["layout"]) not in _VALID_LAYOUTS:
            raise HTTPException(400, f"Invalid layout. Must be one of: {', '.join(sorted(_VALID_LAYOUTS))}")
        cp.layout = str(body["layout"])
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
                            "full_width",
                            "font_family", "font_size", "font_color",
                            "fill_color", "border_color", "border_width",
                            "border_radius",
                        ):
                            if field in bp:
                                setattr(bubble, field, bp[field])
                    else:
                        # New bubble — generate a non-colliding stable ID
                        new_id = bp.get("id", "")
                        if not new_id or new_id.startswith("new-"):
                            new_id = _next_bubble_id(panel)
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
            # remove_sfx: true            → clear all SFX on the panel
            # remove_sfx: <int index>     → remove a single SFX by index
            if "remove_sfx" in panel_patch:
                target = panel_patch["remove_sfx"]
                if target is True:
                    panel.sfx = []
                elif isinstance(target, int) and 0 <= target < len(panel.sfx):
                    panel.sfx.pop(target)

            # ── Update or create SFX ──
            # sfx: { ...fields }                → update SFX at sfx_index (default 0),
            #                                     create one if list is empty
            # sfx: [ {...}, {...} ]             → replace whole list
            elif "sfx" in panel_patch:
                sfx_data = panel_patch["sfx"]
                if isinstance(sfx_data, list):
                    panel.sfx = [Sfx.model_validate(item) for item in sfx_data]
                else:
                    idx = panel_patch.get("sfx_index", 0)
                    if 0 <= idx < len(panel.sfx):
                        target_sfx = panel.sfx[idx]
                        for field in ("x", "y", "rotation", "font_size", "text", "kind", "intensity", "anchor"):
                            if field in sfx_data:
                                value = sfx_data[field]
                                if field == "text":
                                    value = normalize_sfx_text(value) or value
                                setattr(target_sfx, field, value)
                    else:
                        sfx_text = normalize_sfx_text(sfx_data.get("text")) or "SFX!"
                        new_sfx = Sfx.model_validate({**sfx_data, "text": sfx_text})
                        panel.sfx.append(new_sfx)


@router.get("/lettering-style")
def get_lettering_style(project=Depends(get_project)):
    """Return the project-level lettering style (golden-age default if unset)."""
    project_dir, config, state = project
    return load_lettering_style(project_dir).model_dump()


@router.post("/lettering-style/generate")
async def generate_lettering_style(
    project_id: str,
    body: dict | None = None,
    project=Depends(get_project),
    user_id: str = Depends(get_current_user),
):
    """Auto-match lettering to the active image style. Cached by style-template
    hash; re-selecting the same style is free unless reroll is set."""
    project_dir, config, state = project
    reroll = bool((body or {}).get("reroll"))
    cur_hash = _style_hash(config.style_template)
    existing = load_lettering_style(project_dir)
    if (
        not reroll
        and existing.mode == "auto"
        and existing.source == "ai"
        and existing.style_template_hash == cur_hash
    ):
        return existing.model_dump()

    with ai_request_context(
        user_id=user_id,
        project_id=project_id,
        project_name=project_dir.name,
        workspace_id=str(project_dir.parent),
        stage="style",
    ):
        gen, usage = await _generate_lettering_style(config, reroll=reroll)
    if usage:
        debit_model_usage(
            get_db(),
            user_id,
            project_id,
            usage,
            stage="style",
            description="Model call: lettering style",
        )

    ls = LetteringStyle(
        mode="auto",
        preset=None,
        theme=gen["theme"],
        font_pair=gen["font_pair"],
        vars=gen["vars"],
        label=gen["label"],
        rationale=gen["rationale"],
        source=gen["source"],
        style_template_hash=cur_hash,
        generated_at=datetime.now(timezone.utc).isoformat(),
    )
    save_lettering_style(project_dir, ls)
    return ls.model_dump()


@router.put("/lettering-style")
def set_lettering_style(body: dict, project=Depends(get_project)):
    """Set lettering intent: a named preset (no AI) or flip back to auto."""
    project_dir, config, state = project
    mode = body.get("mode", "auto")
    if mode == "preset":
        preset = body.get("preset", "default")
        if preset not in THEMES:
            raise HTTPException(400, f"Invalid preset. Must be one of: {', '.join(THEMES.keys())}")
        label, rationale = PRESET_LABELS.get(preset, (preset.title(), ""))
        ls = LetteringStyle(
            mode="preset",
            preset=preset,
            theme=preset,
            font_pair=PRESET_FONT_PAIR.get(preset, "golden-age"),
            vars={},
            label=label,
            rationale=rationale,
            source="preset",
            style_template_hash=_style_hash(config.style_template),
            generated_at=datetime.now(timezone.utc).isoformat(),
        )
        save_lettering_style(project_dir, ls)
        return ls.model_dump()

    existing = load_lettering_style(project_dir)
    existing.mode = "auto"
    save_lettering_style(project_dir, existing)
    return existing.model_dump()


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
async def translate_page_bubbles(
    body: dict,
    project_id: str,
    project=Depends(get_project),
    user_id: str = Depends(get_current_user),
):
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

    with ai_request_context(
        user_id=user_id,
        project_id=project_id,
        project_name=project_dir.name,
        workspace_id=str(project_dir.parent),
        stage="compose",
    ):
        translations, usage = await _translate_text_items(config, items)
    if usage:
        debit_model_usage(
            get_db(),
            user_id,
            project_id,
            usage,
            stage="compose",
            description="Model call: translate bubbles",
        )
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
async def translate_single_page_bubbles(
    page_num: int,
    body: dict,
    project_id: str,
    project=Depends(get_project),
    user_id: str = Depends(get_current_user),
):
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

    with ai_request_context(
        user_id=user_id,
        project_id=project_id,
        project_name=project_dir.name,
        workspace_id=str(project_dir.parent),
        stage="compose",
    ):
        translations, usage = await _translate_text_items(config, items)
    if usage:
        debit_model_usage(
            get_db(),
            user_id,
            project_id,
            usage,
            stage="compose",
            description=f"Model call: translate page {page_num}",
        )
    updated = 0
    for panel in cp.panels:
        for bubble in panel.bubbles:
            item_id = f"{cp.page_number}:{panel.id}:{bubble.id}"
            translated = translations.get(item_id)
            if translated and translated != bubble.text:
                bubble.text = translated
                updated += 1

    if updated:
        artifacts.write_compose_page(project_dir, page_num, cp)

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
    try:
        cp = ComicPage.model_validate(body)
    except ValidationError as exc:
        raise HTTPException(422, str(exc)) from exc
    cp.page_number = page_num
    if not artifacts.compose_page_path(project_dir, page_num).exists():
        raise HTTPException(404, f"Page {page_num} not found")
    artifacts.write_compose_page(project_dir, page_num, cp)
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
    try:
        reorder_planned_pages(plan, pages_spec)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    except (TypeError, ValueError) as exc:
        raise HTTPException(400, f"Invalid pages spec: {exc}") from exc
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


# ── HTML preview ─────────────────────────────────────────────────────────────


@router.get("/pages/{page_num}/preview")
def page_preview(page_num: int, project_id: str, project=Depends(get_project)):
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
        image_url_fn=lambda rel: f"/api/projects/{project_id}/files/{rel}",
        font_url_fn=lambda filename: f"/static/fonts/{filename}",
    )
    return HTMLResponse(html)


# ── File serving (images, refs, plates, etc.) ────────────────────────────────


@router.get("/files/{file_path:path}")
def serve_file(file_path: str, project=Depends(get_project)):
    project_dir, config, state = project
    full = (project_dir / file_path).resolve()

    # Path traversal guard — is_relative_to, not a string prefix check, so a
    # sibling dir like "demo-private" can't slip past the guard for "demo".
    if not full.is_relative_to(project_dir.resolve()):
        raise HTTPException(403, "Access denied")
    if not full.is_file():
        raise HTTPException(404, "File not found")

    media_type = mimetypes.guess_type(str(full))[0] or "application/octet-stream"
    return FileResponse(full, media_type=media_type, headers={"Cache-Control": "no-cache"})
