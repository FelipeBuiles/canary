"""HTML/CSS comic page renderer.

Converts a ComicPage model into a self-contained HTML document, then
screenshots it with headless Chromium (Playwright) to produce a PNG.

Why this split matters for the web dashboard
--------------------------------------------
The same ``build_page_html()`` function can run:
  • server-side  → Playwright screenshots it → PNG/PDF export
  • browser-side → the frontend loads the same HTML template and renders it
                   live, allowing drag-and-drop bubble editing with no
                   translation layer between the editor and the export path.

Bubble position contract
------------------------
Bubble.x / Bubble.y == None  → CSS auto-layout (narration at top,
                                speech/thought stacked at bottom via flex)
Bubble.x / Bubble.y == float → pinned by web editor, rendered as
                                ``position: absolute; left: Xpx; top: Ypx``

One-time browser install
------------------------
    pip install playwright
    playwright install chromium
"""

from __future__ import annotations

import html as _html_mod
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Callable

from novel_to_comic.config import Config
from novel_to_comic.models.comic_page import Bubble, ComicPage, PagePanel, Sfx

PAGE_W = 2480
PAGE_H = 3508
FONTS_DIR = Path(__file__).parent.parent / "fonts"


# ── Theme system ──────────────────────────────────────────────────────────────

_BASE_VARS: dict[str, str] = {
    "--page-bg":              "#FFFFFF",
    "--gutter":               "16px",
    "--margin":               "30px",
    "--panel-border":         "#111111",
    "--panel-border-width":   "3px",
    "--panel-bg":             "#888888",
    "--caption-bg":           "#F7F0DC",
    "--caption-border":       "#9B8A5A",
    "--caption-color":        "#3A2A10",
    "--caption-font-size":    "17px",
    "--bubble-bg":            "#FFFFFF",
    "--bubble-border":        "#1A1A1A",
    "--bubble-border-width":  "2px",
    "--bubble-radius":        "14px",
    "--bubble-font-size":     "19px",
    "--bubble-padding":       "7px 11px",
    "--bubble-max-width":     "52%",
    "--bubble-center-width":  "68%",
    "--speaker-color":        "#664400",
    "--speaker-font-size":    "14px",
    "--thought-border-style": "dashed",
    "--thought-radius":       "50px",
    "--sfx-color":            "#CC1111",
    "--sfx-shadow":           "#000000",
    "--sfx-font-size":        "56px",
    "--page-num-color":       "#AAAAAA",
    "--page-num-font-size":   "26px",
}

THEMES: dict[str, dict[str, str]] = {
    "default": {},
    "noir": {
        "--page-bg":              "#1C1C1C",
        "--panel-border":         "#DDDDDD",
        "--panel-border-width":   "2px",
        "--panel-bg":             "#444444",
        "--caption-bg":           "#2A2A2A",
        "--caption-border":       "#666666",
        "--caption-color":        "#DDDDDD",
        "--bubble-bg":            "#F0F0F0",
        "--bubble-border":        "#111111",
        "--speaker-color":        "#444444",
        "--sfx-color":            "#FFFFFF",
        "--sfx-shadow":           "#000000",
        "--page-num-color":       "#555555",
    },
    "manga": {
        "--panel-border-width":   "2px",
        "--panel-border":         "#000000",
        "--caption-bg":           "#FFFFFF",
        "--caption-border":       "#000000",
        "--caption-color":        "#000000",
        "--bubble-border":        "#000000",
        "--bubble-font-size":     "21px",
        "--sfx-color":            "#000000",
        "--sfx-shadow":           "transparent",
        "--thought-border-style": "solid",
    },
    "vintage": {
        "--page-bg":              "#FFF8E7",
        "--panel-border":         "#8B4513",
        "--panel-border-width":   "4px",
        "--caption-bg":           "#FFE4B5",
        "--caption-border":       "#8B4513",
        "--caption-color":        "#5C2E00",
        "--bubble-bg":            "#FFFACD",
        "--bubble-border":        "#8B4513",
        "--speaker-color":        "#8B2500",
        "--sfx-color":            "#8B0000",
        "--sfx-shadow":           "#3A0000",
        "--page-num-color":       "#8B4513",
    },
    "painted": {
        "--page-bg":              "#F5F0E8",
        "--panel-border":         "#4A3728",
        "--panel-border-width":   "3px",
        "--caption-bg":           "#E8DCC8",
        "--caption-border":       "#4A3728",
        "--caption-color":        "#2A1A0A",
        "--bubble-border":        "#4A3728",
        "--sfx-color":            "#7B3B00",
        "--sfx-shadow":           "#2A1000",
    },
}


def detect_theme(style_template: str) -> str:
    low = style_template.lower()
    if any(w in low for w in ("noir", "black and white", "monochrome", "grayscale", "shadowy")):
        return "noir"
    if any(w in low for w in ("manga", "anime", "shonen", "shojo", "japanese")):
        return "manga"
    if any(w in low for w in ("vintage", "golden age", "retro", "silver age")):
        return "vintage"
    if any(w in low for w in ("watercolor", "painted", "painterly", "gouache")):
        return "painted"
    return "default"


def resolve_theme(config: Config) -> str:
    raw = getattr(config, "comic_theme", "auto") or "auto"
    if raw == "auto":
        return detect_theme(config.style_template)
    return raw if raw in THEMES else "default"


def _vars_css(theme_name: str) -> str:
    merged = {**_BASE_VARS, **THEMES.get(theme_name, {})}
    lines = "\n".join(f"  {k}: {v};" for k, v in merged.items())
    return f":root {{\n{lines}\n}}"


# ── Static CSS (layout + components) ─────────────────────────────────────────

_STATIC_CSS = """\
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

body {
  width: {PAGE_W}px;
  height: {PAGE_H}px;
  background: var(--page-bg);
  overflow: hidden;
  position: relative;
}

/* ── Page grid ── */
.comic-page {
  width: 100%;
  height: calc(100% - 48px);
  padding: var(--margin);
  display: grid;
  gap: var(--gutter);
}

.layout-1 { grid-template-rows: 1fr; grid-template-columns: 1fr; }
.layout-2 { grid-template-rows: 1fr 1fr; grid-template-columns: 1fr; }

.layout-3 { grid-template-rows: 1fr 1fr; grid-template-columns: 1fr 1fr; }
/* When grid_column is not set via inline style, nth-child handles it: */
.layout-3 .panel:not([style*="grid-column"]):nth-child(1) { grid-column: 1 / 3; }

.layout-4 { grid-template-rows: 1fr 1fr; grid-template-columns: 1fr 1fr; }

.layout-5 { grid-template-rows: 1fr 1fr; grid-template-columns: 1fr 1fr 1fr; }
.layout-5 .panel:not([style*="grid-column"]):nth-child(1) { grid-column: 1 / 3; }
.layout-5 .panel:not([style*="grid-column"]):nth-child(2) { grid-column: 3; }

.layout-6 { grid-template-rows: 1fr 1fr; grid-template-columns: 1fr 1fr 1fr; }

.layout-many { grid-auto-rows: 1fr; grid-template-columns: 1fr 1fr 1fr; }

/* ── Panel ── */
.panel {
  position: relative;
  overflow: hidden;
  border: var(--panel-border-width) solid var(--panel-border);
  background: var(--panel-bg);
}

/* object-position 20% keeps faces/action visible (top-biased) */
.panel-art {
  width: 100%;
  height: 100%;
  object-fit: cover;
  object-position: center 20%;
  display: block;
}

/* ── Narration captions — auto (top of panel) ── */
.captions {
  position: absolute;
  top: 6px;
  left: 6px;
  right: 6px;
  z-index: 2;
  display: flex;
  flex-direction: column;
  gap: 4px;
  pointer-events: none;
}

.caption {
  background: var(--caption-bg);
  border: 1px solid var(--caption-border);
  color: var(--caption-color);
  padding: 5px 9px;
  font-family: 'Bangers', 'Arial Narrow', fantasy, sans-serif;
  font-size: var(--caption-font-size);
  line-height: 1.35;
  letter-spacing: 0.02em;
}

/* ── Speech/thought bubbles — auto (flex-end at panel bottom) ── */
.bubble-auto {
  position: absolute;
  top: 0;
  bottom: 6px;
  left: 6px;
  right: 6px;
  z-index: 1;
  display: flex;
  flex-direction: column;
  justify-content: flex-end;
  gap: 5px;
  pointer-events: none;
}

/* ── All bubbles share these base styles ── */
.bubble {
  background: var(--bubble-bg);
  border: var(--bubble-border-width) solid var(--bubble-border);
  border-radius: var(--bubble-radius);
  padding: var(--bubble-padding);
  font-family: 'ComicNeue', 'Comic Neue', 'Comic Sans MS', cursive, sans-serif;
  font-size: var(--bubble-font-size);
  font-weight: bold;
  line-height: 1.35;
  max-width: var(--bubble-max-width);
  align-self: flex-start;
  word-break: break-word;
}
.bubble.right  { align-self: flex-end; }
.bubble.center { align-self: center; max-width: var(--bubble-center-width); }

/* Thought bubble */
.bubble.thought {
  border-radius: var(--thought-radius);
  border-style: var(--thought-border-style);
}

/* ── Upward tails (default — character is above bubble) ── */
.bubble.speech.tail-up.left::after,
.bubble.speech.tail-up.right::after,
.bubble.speech.tail-up.center::after {
  content: '';
  position: absolute;
  top: -14px;
  border: 8px solid transparent;
  border-bottom: 14px solid var(--bubble-border);
}
.bubble.speech.tail-up.left::before,
.bubble.speech.tail-up.right::before,
.bubble.speech.tail-up.center::before {
  content: '';
  position: absolute;
  top: -10px;
  border: 6px solid transparent;
  border-bottom: 12px solid var(--bubble-bg);
  z-index: 1;
}
.bubble.speech.tail-up.left::after   { left: 18px; }
.bubble.speech.tail-up.left::before  { left: 20px; }
.bubble.speech.tail-up.right::after  { right: 18px; }
.bubble.speech.tail-up.right::before { right: 20px; }
.bubble.speech.tail-up.center::after  { left: 50%; transform: translateX(-50%); }
.bubble.speech.tail-up.center::before { left: 50%; transform: translateX(-50%); }

/* ── Downward tails (character is below bubble) ── */
.bubble.speech.tail-down.left::after,
.bubble.speech.tail-down.right::after,
.bubble.speech.tail-down.center::after {
  content: '';
  position: absolute;
  bottom: -14px;
  border: 8px solid transparent;
  border-top: 14px solid var(--bubble-border);
}
.bubble.speech.tail-down.left::before,
.bubble.speech.tail-down.right::before,
.bubble.speech.tail-down.center::before {
  content: '';
  position: absolute;
  bottom: -10px;
  border: 6px solid transparent;
  border-top: 12px solid var(--bubble-bg);
  z-index: 1;
}
.bubble.speech.tail-down.left::after   { left: 18px; }
.bubble.speech.tail-down.left::before  { left: 20px; }
.bubble.speech.tail-down.right::after  { right: 18px; }
.bubble.speech.tail-down.right::before { right: 20px; }
.bubble.speech.tail-down.center::after  { left: 50%; transform: translateX(-50%); }
.bubble.speech.tail-down.center::before { left: 50%; transform: translateX(-50%); }

/* Speaker label */
.speaker {
  display: block;
  font-family: 'Bangers', fantasy, sans-serif;
  font-size: var(--speaker-font-size);
  color: var(--speaker-color);
  margin-bottom: 2px;
  font-weight: normal;
  letter-spacing: 0.04em;
}

/* ── Pinned bubble (x/y set by web editor drag-drop) ── */
.bubble.pinned {
  position: absolute;
  /* left, top, width set via inline style */
}

/* ── SVG tail (replaces CSS pseudo-element tails for pinned bubbles) ── */
.bubble.svg-tail::before,
.bubble.svg-tail::after { display: none; }
.bubble .tail-svg {
  position: absolute;
  width: 0;
  height: 0;
  overflow: visible;
  pointer-events: none;
  z-index: -1;
}

/* ── Narration caption — pinned variant ── */
.caption.pinned {
  position: absolute;
  /* left, top, width set via inline style */
  right: auto;
}

/* ── SFX ── */
.sfx {
  position: absolute;
  bottom: 18%;
  left: 50%;
  transform: translateX(-50%) rotate(-4deg);
  font-family: 'Bangers', fantasy, cursive;
  font-size: var(--sfx-font-size);
  color: var(--sfx-color);
  text-shadow:
    3px  3px 0 var(--sfx-shadow),
   -2px -2px 0 var(--sfx-shadow),
    2px -2px 0 var(--sfx-shadow),
   -2px  2px 0 var(--sfx-shadow);
  white-space: nowrap;
  z-index: 3;
  pointer-events: none;
}

/* ── SFX pinned by web editor (x/y set via inline style) ── */
.sfx.pinned {
  bottom: auto;
  left: auto;
  transform: none;  /* rotation applied via inline style instead */
}

/* ── Panel ID debug label ── */
.panel-id {
  position: absolute;
  bottom: 3px; right: 3px;
  background: rgba(0,0,0,0.6);
  color: rgba(220,220,220,0.85);
  font-family: monospace;
  font-size: 13px;
  padding: 1px 5px;
  z-index: 5;
}

/* ── Page number ── */
.page-number {
  position: absolute;
  bottom: 10px;
  left: 0; right: 0;
  text-align: center;
  font-family: 'Bangers', fantasy, sans-serif;
  font-size: var(--page-num-font-size);
  color: var(--page-num-color);
  letter-spacing: 0.08em;
}
"""


# ── Theme CSS file ────────────────────────────────────────────────────────────

_THEME_HEADER = """\
/*
 * novel-to-comic assembly theme  —  auto-generated, freely editable
 * Active theme: {theme_name}
 *
 * Changes take effect on the next:  pipeline export
 * Live preview: open assembly/html/page_*.html in any browser,
 *               edit this file, then hard-refresh the tab.
 *
 * All CSS variables (with base defaults):
 * ─────────────────────────────────────────────────────────────────
 *  Page
 *    --page-bg                 page background (#FFFFFF)
 *    --gutter                  gap between panels (16px)
 *    --margin                  outer page margin (30px)
 *
 *  Panels
 *    --panel-border            border colour (#111111)
 *    --panel-border-width      border thickness (3px)
 *    --panel-bg                placeholder when image is missing (#888888)
 *
 *  Narration captions (top of panel)
 *    --caption-bg              background (#F7F0DC)
 *    --caption-border          border (#9B8A5A)
 *    --caption-color           text colour (#3A2A10)
 *    --caption-font-size       (17px)
 *
 *  Speech / thought bubbles
 *    --bubble-bg               background (#FFFFFF)
 *    --bubble-border           border colour (#1A1A1A)
 *    --bubble-border-width     (2px)
 *    --bubble-radius           corner radius (14px)
 *    --bubble-font-size        (19px)
 *    --bubble-padding          (7px 11px)
 *    --bubble-max-width        max % of panel width (52%)
 *    --bubble-center-width     max % for centred bubbles (68%)
 *
 *  Speaker name labels (shown when 3+ characters in a panel)
 *    --speaker-color           (#664400)
 *    --speaker-font-size       (14px)
 *
 *  Thought bubbles
 *    --thought-border-style    "dashed" | "solid" | "dotted" (dashed)
 *    --thought-radius          corner radius (50px — very rounded)
 *
 *  Sound effects
 *    --sfx-color               fill (#CC1111)
 *    --sfx-shadow              outline (use "transparent" to disable) (#000000)
 *    --sfx-font-size           (56px)
 *
 *  Page number
 *    --page-num-color          (#AAAAAA)
 *    --page-num-font-size      (26px)
 * ─────────────────────────────────────────────────────────────────
 * Full CSS is supported. Add custom rules after the :root block.
 */

:root {{
{var_lines}
}}

/* Add custom CSS rules below: */
"""


def write_theme_css(project_dir: Path, theme_name: str) -> Path:
    """Write a self-documented theme.css on first run. Never overwrites."""
    path = project_dir / "assembly" / "theme.css"
    path.parent.mkdir(exist_ok=True)
    if not path.exists():
        theme_vars = THEMES.get(theme_name, {})
        if theme_vars:
            var_lines = "\n".join(f"  {k}: {v};" for k, v in theme_vars.items())
        else:
            var_lines = "  /* base defaults active — uncomment to override: */\n  /* --bubble-font-size: 21px; */"
        path.write_text(_THEME_HEADER.format(theme_name=theme_name, var_lines=var_lines))
    return path


# ── HTML builder ──────────────────────────────────────────────────────────────

def _e(text: str) -> str:
    return _html_mod.escape(str(text))


def _font_face(
    family: str,
    filename: str,
    weight: str = "normal",
    url_fn: Callable[[str], str] | None = None,
) -> str:
    """Return a @font-face rule for *filename*.

    ``url_fn``, when provided, maps the font filename to whatever URL the
    current rendering context needs (e.g. an HTTP path on the web server).
    Pass None (default) for CLI / Playwright export, which resolves fonts
    as ``file://`` URIs from the local fonts directory.
    """
    p = FONTS_DIR / filename
    if not p.exists():
        return ""
    src = url_fn(filename) if url_fn is not None else p.as_uri()
    return (
        f"@font-face {{\n"
        f"  font-family: '{family}';\n"
        f"  src: url('{src}');\n"
        f"  font-weight: {weight};\n"
        f"}}"
    )


def _svg_tail(bubble: Bubble) -> str:
    """Render an SVG tail triangle for a pinned bubble.

    The SVG is placed *outside* the bubble via negative offset so the
    tail does not overlap bubble content.  It draws a filled triangle
    from the bubble edge toward ``(tail_x, tail_y)`` in panel-relative
    coordinates.
    """
    if bubble.tail_x is None or bubble.tail_y is None:
        return ""
    if bubble.x is None or bubble.y is None:
        return ""

    bw = bubble.width or 200
    tx = bubble.tail_x - bubble.x
    ty = bubble.tail_y - bubble.y

    # Determine anchor edge: if target is below the bubble center, anchor
    # at the bottom edge; otherwise anchor at the top edge.
    target_below = ty > 20  # rough threshold: anything below ~20px from top
    hw = 10  # half-width of tail base

    if target_below:
        # Anchor at bottom-center, SVG extends downward
        anchor_css = "left: 50%; bottom: 0; transform: translate(-50%, 100%);"
        # Triangle points relative to anchor: base at y=0, tip toward target
        # Target relative to bottom-center of bubble (estimated height ~50px)
        tip_x = tx - bw / 2
        tip_y = ty - 50  # approximate bubble height
    else:
        # Anchor at top-center, SVG extends upward
        anchor_css = "left: 50%; top: 0; transform: translate(-50%, -100%);"
        # Triangle base at y=0 (bottom of SVG, which is the bubble top edge)
        # tip extends upward (negative y)
        tip_x = tx - bw / 2
        tip_y = ty  # already relative to bubble top

    return (
        f'<svg class="tail-svg" style="{anchor_css}" viewBox="0 0 0 0">'
        f'<polygon points="{-hw},0 {hw},0 {tip_x:.0f},{tip_y:.0f}" '
        f'fill="var(--bubble-bg)" stroke="var(--bubble-border)" '
        f'stroke-width="var(--bubble-border-width)" stroke-linejoin="round"/>'
        f'</svg>'
    )


def _resolve_tail_direction(bubble: Bubble) -> str:
    """Resolve 'auto' tail direction based on bubble position.

    For auto-layout bubbles (x/y=None), the default CSS tail always
    points up (characters are above, bubble at bottom).

    For pinned bubbles, auto checks whether the bubble is in the top or
    bottom half of the panel (using a 400px threshold — roughly half a
    typical panel height of ~800-1200px in the 2480x3508 page).
    """
    direction = getattr(bubble, "tail_direction", "auto")
    if direction != "auto":
        return direction
    if bubble.y is not None and bubble.y < 400:
        return "down"  # bubble near top → tail points down toward character below
    return "up"  # default: bubble at bottom → tail points up


def _bubble_html(bubble: Bubble) -> str:
    """Render one Bubble to an HTML element string."""
    classes = ["bubble", bubble.type, bubble.side]
    inline: list[str] = []
    has_svg_tail = False

    if bubble.x is not None and bubble.y is not None:
        classes.append("pinned")
        inline.append(f"left: {bubble.x:.0f}px")
        inline.append(f"top:  {bubble.y:.0f}px")
    if bubble.width is not None:
        inline.append(f"width: {bubble.width:.0f}px")

    if bubble.tail_x is not None and bubble.tail_y is not None:
        classes.append("svg-tail")
        has_svg_tail = True
    elif bubble.type == "speech":
        # Add tail direction class for CSS pseudo-element tails
        classes.append(f"tail-{_resolve_tail_direction(bubble)}")

    style_attr = f' style="{"; ".join(inline)}"' if inline else ""
    cls = " ".join(classes)

    speaker_html = ""
    if bubble.speaker_name:
        speaker_html = f'<span class="speaker">{_e(bubble.speaker_name)}:</span>'

    tail_html = _svg_tail(bubble) if has_svg_tail else ""
    return f'<div class="{cls}" data-id="{_e(bubble.id)}"{style_attr}>{speaker_html}{_e(bubble.text)}{tail_html}</div>'


def _panel_html(
    panel: PagePanel,
    project_dir: Path,
    image_url_fn: Callable[[str], str] | None = None,
) -> str:
    """Render one PagePanel to an HTML element string.

    ``image_url_fn``, when provided, maps a relative image path (as stored in
    ``panel.image_path``) to whatever URL the current rendering context needs.
    The web dashboard passes an HTTP URL builder; CLI/Playwright passes None
    and falls back to ``file://`` URIs.
    """
    # Grid placement (inline style beats CSS nth-child rules)
    grid_parts: list[str] = []
    if panel.grid_column:
        grid_parts.append(f"grid-column: {panel.grid_column}")
    if panel.grid_row:
        grid_parts.append(f"grid-row: {panel.grid_row}")
    style_attr = f' style="{"; ".join(grid_parts)}"' if grid_parts else ""

    # Panel image — resolve src depending on rendering context:
    #   image_url_fn=None  → file:// URI (Playwright server-side export)
    #   image_url_fn=fn    → HTTP URL provided by web server
    if image_url_fn is not None:
        art_html = f'  <img class="panel-art" src="{_e(image_url_fn(panel.image_path))}" alt="">'
    else:
        img_path = project_dir / panel.image_path
        art_html = (
            f'  <img class="panel-art" src="{img_path.as_uri()}" alt="">'
            if img_path.exists() else ""
        )

    # Separate auto-positioned narration from the rest
    auto_narration = [b for b in panel.bubbles
                      if b.type == "narration" and b.x is None]
    auto_speech    = [b for b in panel.bubbles
                      if b.type != "narration" and b.x is None]
    pinned         = [b for b in panel.bubbles if b.x is not None]

    # Auto narration → .captions container at top
    captions_html = ""
    if auto_narration:
        items = "\n".join(
            f'    <div class="caption" data-id="{_e(b.id)}">{_e(b.text)}</div>'
            for b in auto_narration
        )
        captions_html = f'  <div class="captions">\n{items}\n  </div>'

    # Auto speech/thought → .bubble-auto flex container at bottom
    auto_html = ""
    if auto_speech:
        items = "\n".join(f"    {_bubble_html(b)}" for b in auto_speech)
        auto_html = f'  <div class="bubble-auto">\n{items}\n  </div>'

    # Pinned bubbles → absolute within panel
    pinned_html = "\n".join(f"  {_bubble_html(b)}" for b in pinned)

    # SFX
    sfx_html = ""
    if panel.sfx:
        sfx = panel.sfx
        classes = ["sfx"]
        inline: list[str] = []
        if sfx.x is not None and sfx.y is not None:
            classes.append("pinned")
            inline += [
                f"left: {sfx.x:.0f}px",
                f"top: {sfx.y:.0f}px",
                f"transform: rotate({sfx.rotation:.1f}deg)",
            ]
        elif sfx.rotation != -4.0:
            inline.append(f"transform: translateX(-50%) rotate({sfx.rotation:.1f}deg)")
        if sfx.font_size is not None:
            inline.append(f"font-size: {sfx.font_size}px")
        style_attr = f' style="{"; ".join(inline)}"' if inline else ""
        sfx_html = f'  <div class="{" ".join(classes)}" data-sfx="true"{style_attr}>{_e(sfx.text.upper())}</div>'

    # Debug label
    pid_html = (
        f'  <div class="panel-id" data-panel-id="{_e(panel.id)}">'
        f'{_e(panel.scene_id)}/{panel.panel_number}</div>'
    )

    inner = "\n".join(filter(None, [
        art_html,
        captions_html,
        auto_html,
        pinned_html,
        sfx_html,
        pid_html,
    ]))

    return f'<div class="panel" data-panel-id="{_e(panel.id)}"{style_attr}>\n{inner}\n</div>'


def build_page_html(
    comic_page: ComicPage,
    project_dir: Path,
    custom_css: str = "",
    image_url_fn: Callable[[str], str] | None = None,
    font_url_fn: Callable[[str], str] | None = None,
) -> str:
    """Return a complete, self-contained HTML document for one comic page.

    The document can be:
    • Screenshotted by Playwright → PNG (server-side export)
    • Opened directly in a browser → live preview / web editor host

    ``image_url_fn``, when given, maps each panel's relative ``image_path``
    to an HTTP URL.  Pass None (default) for CLI / Playwright export, which
    resolves images as ``file://`` URIs from ``project_dir``.

    ``font_url_fn``, when given, maps each font filename (e.g.
    ``"Bangers-Regular.ttf"``) to an HTTP URL served by the web server.
    Pass None (default) for CLI / Playwright export, which uses ``file://``
    URIs from the local fonts directory.
    """
    layout_cls = (
        f"layout-{comic_page.layout}"
        if comic_page.layout in ("1","2","3","4","5","6")
        else "layout-many"
    )

    panels_html = "\n".join(
        _panel_html(panel, project_dir, image_url_fn)
        for panel in comic_page.panels
    )

    font_css = "\n".join(filter(None, [
        _font_face("Bangers",    "Bangers-Regular.ttf",         url_fn=font_url_fn),
        _font_face("ComicNeue",  "ComicNeue-Bold.ttf", "bold",  url_fn=font_url_fn),
        _font_face("Comic Neue", "ComicNeue-Bold.ttf", "bold",  url_fn=font_url_fn),
    ]))

    vars_css   = _vars_css(comic_page.theme)
    static_css = _STATIC_CSS.replace("{PAGE_W}", str(PAGE_W)).replace("{PAGE_H}", str(PAGE_H))
    user_block = f"\n/* ── theme.css ── */\n{custom_css}" if custom_css.strip() else ""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="page-number"  content="{comic_page.page_number}">
<meta name="page-theme"   content="{_e(comic_page.theme)}">
<meta name="page-layout"  content="{_e(comic_page.layout)}">
<style>
{font_css}
{vars_css}
{static_css}{user_block}
</style>
</head>
<body>
<div class="comic-page {layout_cls}" data-page="{comic_page.page_number}">
{panels_html}
</div>
<div class="page-number">{comic_page.page_number}</div>
</body>
</html>"""


# ── Playwright renderer ───────────────────────────────────────────────────────

def _require_playwright():
    try:
        from playwright.async_api import async_playwright
        return async_playwright
    except ImportError:
        raise RuntimeError(
            "Playwright is not installed.\n"
            "Run:  pip install playwright && playwright install chromium"
        )


@asynccontextmanager
async def browser_context():
    """Async context manager that yields a reusable Playwright Browser.

    Use this when rendering multiple pages to avoid the overhead of launching
    and closing a browser for every single page::

        async with browser_context() as browser:
            for html, path in pages:
                await render_html_to_png(html, path, browser=browser)
    """
    async_playwright = _require_playwright()
    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        try:
            yield browser
        finally:
            await browser.close()


async def render_html_to_png(
    html_content: str,
    output_path: Path,
    *,
    browser=None,
    source_path: Path | None = None,
) -> None:
    """Screenshot an HTML string to a hi-res PNG using headless Chromium.

    Pass ``browser`` (a Playwright Browser object, obtained from
    :func:`browser_context`) to reuse an existing instance across multiple
    renders.  When omitted, a one-shot browser is launched and closed
    automatically — convenient for single renders, expensive in a loop.

    Pass ``source_path`` when the HTML has already been written to disk (e.g.
    the HTML preview file in stage 7).  The renderer loads it via
    ``file://`` URI so that Chromium allows the page to fetch other local
    ``file://`` resources (panel images, fonts).  When omitted, a temporary
    file is written and cleaned up automatically.

    Why not ``page.set_content()``?
    Playwright's set_content() gives the page a null/opaque origin.  Chromium
    then blocks all file:// sub-resource requests (images, fonts) as a
    cross-origin violation.  Loading via page.goto("file://...") gives the
    page a real file:// origin and lifts that restriction.
    """
    async def _render(b) -> None:
        ctx = await b.new_context(
            viewport={"width": PAGE_W, "height": PAGE_H},
            device_scale_factor=1,
        )
        page = await ctx.new_page()

        if source_path is not None:
            await page.goto(source_path.as_uri(), wait_until="networkidle")
        else:
            # Write to a temp file so the page has a file:// origin
            with tempfile.NamedTemporaryFile(
                suffix=".html", mode="w", encoding="utf-8", delete=False
            ) as tf:
                tf.write(html_content)
                tmp = Path(tf.name)
            try:
                await page.goto(tmp.as_uri(), wait_until="networkidle")
            finally:
                tmp.unlink(missing_ok=True)

        output_path.parent.mkdir(parents=True, exist_ok=True)
        await page.screenshot(
            path=str(output_path),
            clip={"x": 0, "y": 0, "width": PAGE_W, "height": PAGE_H},
            type="png",
        )
        await ctx.close()

    if browser is not None:
        await _render(browser)
    else:
        async with browser_context() as b:
            await _render(b)
