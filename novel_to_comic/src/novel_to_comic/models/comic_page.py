"""Comic page layout data model.

ComicPage is the canonical editing surface for stage 8 (compose) and the
web dashboard. Each page is serialised as ``compose/pages/page_NNN.json``.

Rendering pipeline:
    ComicPage JSON  →  html_renderer.build_page_html()  →  HTML string
                    →  Playwright screenshot  →  PNG
                    →  PDF / CBZ export

Web dashboard pipeline (future):
    ComicPage JSON  →  browser renders same HTML/CSS  →  live preview
    Drag bubble     →  set Bubble.x / Bubble.y  →  PATCH JSON  →  re-render
    Drag SFX        →  set Sfx.x / Sfx.y        →  PATCH JSON  →  re-render
    Export button   →  POST /export  →  same Playwright path above
"""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

SfxKind = Literal["impact", "mechanical", "voice", "ambient", "environment"]
SfxAnchor = Literal[
    "auto",
    "bottom-center",
    "top-center",
    "bottom-left",
    "bottom-right",
    "top-left",
    "top-right",
]

_SFX_BRACKETS_RE = re.compile(r"^\s*\[\s*(.*?)\s*\]\s*$", re.DOTALL)
_SFX_PREFIX_RE = re.compile(r"^\s*sfx\s*[:\-]\s*", re.IGNORECASE)

# Values below end up inside style="..." attributes in rendered HTML, so they
# are restricted to shapes that cannot break out of the attribute or smuggle
# CSS functions (url(), expression(), ...).
_COLOR_RE = re.compile(r"^(#[0-9a-fA-F]{3}|#[0-9a-fA-F]{6}|#[0-9a-fA-F]{8}|transparent)$")
_FONT_FAMILY_RE = re.compile(r"^[\w\s,'\-]+$")
_CLIP_PATH_RE = re.compile(r"^polygon\([0-9.%\s,\-]+\)$")
_GRID_PLACEMENT_RE = re.compile(r"^\d+(\s*/\s*\d+)?$")


def _validate_css_color(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    if not _COLOR_RE.match(value):
        raise ValueError(f"invalid color value: {value!r}")
    return value


def _validate_font_family(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    if not value:
        return None
    if not _FONT_FAMILY_RE.match(value):
        raise ValueError(f"invalid font-family value: {value!r}")
    return value

_SFX_KIND_KEYWORDS: dict[str, SfxKind] = {
    # mechanical / electronic
    "beep": "mechanical", "buzz": "mechanical", "tick": "mechanical",
    "click": "mechanical", "whirr": "mechanical", "hum": "mechanical",
    "ring": "mechanical", "ding": "mechanical", "rrrr": "mechanical",
    # voice / vocal
    "aah": "voice", "ahh": "voice", "ooh": "voice", "ooo": "voice",
    "gasp": "voice", "scream": "voice", "groan": "voice", "moan": "voice",
    "yelp": "voice", "shriek": "voice", "wail": "voice", "sigh": "voice",
    "huff": "voice", "puff": "voice", "haha": "voice", "uggh": "voice",
    # ambient / environmental
    "rustle": "ambient", "whisper": "ambient", "patter": "ambient",
    "drip": "ambient", "creak": "ambient", "wind": "environment",
    "rain": "environment", "thunder": "environment",
}


def normalize_sfx_text(raw: str | None) -> str | None:
    """Strip ``[SFX: ...]`` / ``SFX:`` markup leaked from LLM output.

    Returns ``None`` for empty or pure-markup input so callers can drop the
    SFX entirely instead of rendering literal brackets on the page.
    """
    if not raw:
        return None
    s = str(raw).strip()
    for _ in range(3):
        m = _SFX_BRACKETS_RE.match(s)
        if m:
            s = m.group(1).strip()
            continue
        m2 = _SFX_PREFIX_RE.match(s)
        if m2:
            s = s[m2.end():].strip()
            continue
        break
    return s or None


def infer_sfx_kind(text: str) -> SfxKind:
    """Heuristic mapping from onomatopoeia to ``SfxKind``.

    Falls back to ``"impact"`` — the safest default for a single SFX, and
    the mode that uses the existing ``--sfx-color`` theme variable.
    """
    low = text.lower()
    for needle, kind in _SFX_KIND_KEYWORDS.items():
        if needle in low:
            return kind
    return "impact"


def infer_sfx_intensity(text: str) -> Literal[1, 2, 3]:
    """Heuristic mapping from a cleaned SFX string to intensity 1-3.

    3 = big sounds (all caps + emphasis or repeated vowels).
    2 = standard onomatopoeia.
    1 = quiet / lowercase / descriptive prose that slipped through.
    """
    if not text:
        return 2
    has_upper = any(c.isupper() for c in text)
    has_lower = any(c.islower() for c in text)
    if has_upper and not has_lower:
        if "!" in text or any(text.count(c) >= 3 for c in "OAEIUM"):
            return 3
        return 2
    return 1


class Bubble(BaseModel):
    """One speech, thought, or narration element within a panel.

    Position contract
    -----------------
    x, y, width are in pixels relative to the panel's top-left corner.

    • None  →  CSS auto-layout:
                 narration  → stacked in .captions container at the top
                 speech / thought → stacked in .bubble-auto flex container
                                    at the bottom (justify-content: flex-end)
    • float →  The web editor has pinned this bubble.  Rendered as
                 ``position: absolute; left: Xpx; top: Ypx`` inside the panel.
                 The same data is sent as-is to the frontend; no translation needed.

    ID stability contract
    ---------------------
    IDs are deterministic within a given ComicPage JSON file:
    ``"{scene_id}-p{panel_number}-b{dialogue_index}"``.

    They are stable across re-renders (``POST /export``).  They reset on
    a full rebuild (``POST /api/projects/{project}/run/{stage}`` with
    ``--rebuild``), which also resets all bubble positions to None — so
    stale web-editor pin data is never silently applied to the wrong
    bubble.

    The web dashboard must treat IDs as opaque strings valid only for the
    lifetime of the current JSON file.
    """

    model_config = ConfigDict(validate_assignment=True)

    id: str                                             # stable within JSON lifetime
    type: Literal["speech", "thought", "narration"] = "speech"
    text: str
    speaker_id: str | None = None                       # character ID
    speaker_name: str | None = None                     # first name label
    source_beat_id: str | None = None
    source_text: str | None = None
    narration_mode: str | None = None
    preferred_zone: str | None = None
    side: Literal["left", "right", "center"] = "left"  # tail / alignment
    full_width: bool | None = None                       # True = span panel width
    # Explicit position — null = CSS auto-layout; float = pinned by web editor
    x: float | None = None
    y: float | None = None
    width: float | None = None                          # explicit width override
    # SVG tail target — null = use CSS upward-pointing tail; float = draw SVG
    # triangle from bubble edge toward this panel-relative point
    tail_x: float | None = None
    tail_y: float | None = None
    # Tail direction: "auto" picks up/down based on bubble position in panel,
    # "up"/"down" forces direction. Only affects CSS tails (non-SVG).
    tail_direction: Literal["auto", "up", "down"] = "auto"
    # Optional per-bubble typography and shape overrides. None means inherit
    # the active page/theme CSS variables.
    font_family: str | None = None
    font_size: int | None = None
    font_color: str | None = None
    fill_color: str | None = None
    border_color: str | None = None
    border_width: int | None = None
    border_radius: int | None = None

    @field_validator("font_color", "fill_color", "border_color")
    @classmethod
    def _check_colors(cls, v: str | None) -> str | None:
        return _validate_css_color(v)

    @field_validator("font_family")
    @classmethod
    def _check_font_family(cls, v: str | None) -> str | None:
        return _validate_font_family(v)


class Sfx(BaseModel):
    """A sound effect overlay on a panel.

    Position contract:
    • x, y = None  → CSS layout: ``anchor`` controls which corner/edge
                     the SFX is glued to (``"auto"`` lets the renderer pick
                     based on order in ``PagePanel.sfx``).
    • x, y = float → pinned by web editor (absolute px from panel top-left)

    ``kind`` selects the colour theme (``--sfx-color`` for impact, plus
    per-kind variables for mechanical/voice/ambient/environment).
    ``intensity`` 1-3 scales the rendered font size.
    ``rotation`` is in degrees. ``font_size`` overrides the per-intensity
    size when set.
    """

    model_config = ConfigDict(validate_assignment=True)

    text: str
    kind: SfxKind = "impact"
    intensity: Literal[1, 2, 3] = 2
    anchor: SfxAnchor = "auto"
    x: float | None = None
    y: float | None = None
    rotation: float = -4.0
    font_size: int | None = None

    @field_validator("text", mode="before")
    @classmethod
    def _clean_text(cls, v: Any) -> Any:
        if isinstance(v, str):
            cleaned = normalize_sfx_text(v)
            if cleaned is None:
                raise ValueError("Sfx.text is empty after stripping markup")
            return cleaned
        return v


class PagePanel(BaseModel):
    """One panel cell on a comic page."""

    model_config = ConfigDict(validate_assignment=True)

    id: str                                     # e.g. "scene_001-003"
    planned_panel_id: str | None = None
    image_path: str                             # relative to project_dir
    scene_id: str
    panel_number: int
    importance: str | None = None
    generation_mode: str | None = None
    bubbles: list[Bubble] = Field(default_factory=list)
    sfx: list[Sfx] = Field(default_factory=list)
    # Optional panel image offset in px from the default object-position.
    image_offset_x: float | None = None
    image_offset_y: float | None = None
    # Optional art scale for crop reframing. None keeps the default 1x crop.
    image_scale: float | None = Field(default=None, ge=1.0, le=2.5)
    # CSS Grid placement — None = CSS nth-child rules handle it automatically.
    # The web editor sets these when the user rearranges panels on a page.
    grid_column: str | None = None              # e.g. "1 / 3"
    grid_row: str | None = None
    # Absolute page geometry, used for planner-driven and irregular layouts.
    x: float | None = None
    y: float | None = None
    width: float | None = None
    height: float | None = None
    clip_path: str | None = None
    z_index: int | None = None
    shape_intent: str | None = None

    @field_validator("sfx", mode="before")
    @classmethod
    def _migrate_sfx(cls, v: Any) -> Any:
        if v is None:
            return []
        if isinstance(v, (dict, Sfx)):
            return [v]
        return v

    @field_validator("clip_path")
    @classmethod
    def _check_clip_path(cls, v: str | None) -> str | None:
        if v is None:
            return None
        if not _CLIP_PATH_RE.match(v.strip()):
            raise ValueError(f"invalid clip-path value: {v!r}")
        return v.strip()

    @field_validator("grid_column", "grid_row")
    @classmethod
    def _check_grid_placement(cls, v: str | None) -> str | None:
        if v is None:
            return None
        if not _GRID_PLACEMENT_RE.match(v.strip()):
            raise ValueError(f"invalid grid placement: {v!r}")
        return v.strip()


class ComicPage(BaseModel):
    """One assembled comic page.

    This is what ``pipeline export --from-json`` reads, and what the web
    dashboard loads, edits, and saves back via the pages REST API.
    """

    model_config = ConfigDict(validate_assignment=True)

    page_number: int
    source_page_id: str | None = None
    layout: str = "4"                           # "1"–"6" or "many"
    layout_mode: Literal["grid", "freeform"] = "grid"
    panels: list[PagePanel] = Field(default_factory=list)


# ── Bubble presets ─────────────────────────────────────────────────────────────

BUBBLE_PRESETS: dict[str, dict[str, str]] = {
    "speech": {
        "border_radius": "10",
        "border_width": "2",
        "border_color": "#1a1b15",
        "fill_color": "#ffffff",
    },
    "thought": {
        "border_radius": "22",
        "border_width": "2",
        "border_color": "#1a1b15",
        "fill_color": "#ffffff",
    },
    "narration": {
        "border_radius": "2",
        "border_width": "2",
        "border_color": "#1a1b15",
        "fill_color": "#f0ebe0",
    },
    "whisper": {
        "border_radius": "10",
        "border_width": "1",
        "border_color": "#1a1b1580",
        "fill_color": "#ffffffcc",
    },
    "shout": {
        "border_radius": "2",
        "border_width": "3",
        "border_color": "#1a1b15",
        "fill_color": "#e8c840",
    },
}


# ── Character voices ──────────────────────────────────────────────────────────

class CharacterVoice(BaseModel):
    """Per-character bubble style preset applied automatically at render time."""
    character_id: str
    character_name: str
    font_family: str | None = None
    font_size: int | None = None
    font_color: str | None = None
    fill_color: str | None = None
    border_color: str | None = None
    border_width: int | None = None
    border_radius: int | None = None

    @field_validator("font_color", "fill_color", "border_color")
    @classmethod
    def _check_colors(cls, v: str | None) -> str | None:
        return _validate_css_color(v)

    @field_validator("font_family")
    @classmethod
    def _check_font_family(cls, v: str | None) -> str | None:
        return _validate_font_family(v)
