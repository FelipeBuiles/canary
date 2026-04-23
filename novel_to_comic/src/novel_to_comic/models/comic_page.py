"""Comic page layout data model.

ComicPage is the canonical editing surface for stage 7 and the future web
dashboard.  Each page is serialised as ``assembly/pages/page_NNN.json``.

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

from typing import Literal

from pydantic import BaseModel, Field


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

    They are stable across re-renders (``pipeline export``).  They reset on
    a full rebuild (``pipeline run assemble`` or ``--rebuild``), which also
    resets all bubble positions to None — so stale web-editor pin data is
    never silently applied to the wrong bubble.

    The web dashboard must treat IDs as opaque strings valid only for the
    lifetime of the current JSON file.
    """

    id: str                                             # stable within JSON lifetime
    type: Literal["speech", "thought", "narration"] = "speech"
    text: str
    speaker_id: str | None = None                       # character ID
    speaker_name: str | None = None                     # first name label
    side: Literal["left", "right", "center"] = "left"  # tail / alignment
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


class Sfx(BaseModel):
    """A sound effect overlay on a panel.

    Position contract (mirrors Bubble):
    • x, y = None  → CSS default: centered horizontally, bottom 18% of panel
    • x, y = float → pinned by web editor (absolute px from panel top-left)

    ``rotation`` is in degrees; default matches the CSS −4 ° tilt.
    ``font_size`` overrides ``--sfx-font-size`` when set.
    """

    text: str
    x: float | None = None
    y: float | None = None
    rotation: float = -4.0          # degrees; matches CSS default
    font_size: int | None = None    # px override; None = use --sfx-font-size var


class PagePanel(BaseModel):
    """One panel cell on a comic page."""

    id: str                                     # e.g. "scene_001-003"
    image_path: str                             # relative to project_dir
    scene_id: str
    panel_number: int
    bubbles: list[Bubble] = Field(default_factory=list)
    sfx: Sfx | None = None
    # Optional panel image offset in px from the default object-position.
    image_offset_x: float | None = None
    image_offset_y: float | None = None
    # CSS Grid placement — None = CSS nth-child rules handle it automatically.
    # The web editor sets these when the user rearranges panels on a page.
    grid_column: str | None = None              # e.g. "1 / 3"
    grid_row: str | None = None


class ComicPage(BaseModel):
    """One assembled comic page.

    This is what ``pipeline export --from-json`` reads, and what the web
    dashboard will load, edit, and save back via a REST API.
    """

    page_number: int
    theme: str = "default"
    layout: str = "4"                           # "1"–"6" or "many"
    style_vars: dict[str, str] = Field(default_factory=dict)
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
