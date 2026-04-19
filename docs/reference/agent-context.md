# Canary — Detailed Agent Context

This file is the detailed reference for agentic coding sessions. The root
`AGENTS.md` and `CLAUDE.md` files intentionally stay short to reduce repeated
context cost. Open this file when work touches pipeline architecture, stage
contracts, generation, assembly, or project artifacts.

---

## What this project is

A 7-stage Python CLI pipeline that converts novels (EPUB/TXT) into comic books
(PDF/CBZ). It uses LLMs for story analysis and image generation models for panel
artwork. Each stage is discrete, resumable, and produces inspectable
JSON/file output.

**Status:** Early MVP. Breaking changes are frequent and expected. No test suite
yet — this is intentional.

**Long-term goal:** Release as a product. Roadmap:

1. Polish generation (stage 6) and assembly (stage 7) — current focus
2. Web dashboard with per-stage manual control and visual output review
3. Visual drag-and-drop editor for speech bubbles, panel layout
4. User insertion into story (inject user's likeness into character references)

---

## Codebase map

```text
novel_to_comic/src/novel_to_comic/
├── cli.py                  # Click CLI entry point — init, run, approve, status, export
├── config.py               # Pydantic config loaded from config.yaml + .env
├── state.py                # Pipeline state machine — state.json, stage status, cost tracking
├── events.py               # Event callback system for SSE/WebSocket streaming
├── clients/
│   ├── gemini.py           # Async Gemini wrapper with retry
│   ├── claude.py           # Anthropic Claude wrapper
│   ├── flux.py             # Image gen router: Gemini native or Together AI
│   └── embeddings.py       # Google / OpenAI embedding clients
├── stages/
│   ├── s1_extract.py       # Novel → Story Bible JSON
│   ├── s2_index.py         # RAG index + character refs + location plates
│   ├── s3_screenplay.py    # Scene prose → screenplay
│   ├── s4_panels.py        # Screenplay → panel breakdown JSON
│   ├── s5_prompts.py       # Panel breakdown → image prompts
│   ├── s6_generate.py      # Image generation
│   └── s7_assemble.py      # ComicPage JSON → HTML → Playwright PNG → PDF/CBZ
├── models/
│   ├── story_bible.py      # Character, Location, Scene, NarrativeArc
│   ├── panel.py            # PanelBreakdown, DialogueLine, Screenplay
│   ├── prompt.py           # Image prompt template
│   └── comic_page.py       # ComicPage, PagePanel, Bubble, Sfx
├── assembly/
│   └── html_renderer.py    # build_page_html(), browser_context(), render_html_to_png()
├── rag/
│   ├── store.py            # Qdrant hybrid search
│   └── chunker.py          # Scene-boundary text chunking
└── prompts/                # LLM prompt templates
```

---

## Architecture decisions

### Decomposition over end-to-end

Each LLM call does exactly one thing. This enables targeted re-runs
(`pipeline run panels --scene scene_012`), clean error recovery, and human
review at boundaries. Never collapse stages.

### Human checkpoints

Pipeline pauses at stages 1 (story bible), 2 (character design), and 6
(generated panels). `approve_stage()` in `state.py` advances `AWAITING_REVIEW`
to `COMPLETE`. The web dashboard will replace `pipeline approve` with UI
buttons.

### Text composited in post

Speech bubbles, narration, SFX are rendered in Stage 7, never generated inside
images. This avoids OCR issues and allows bubble editing without regenerating
images.

### Visual anchors are sacred

`visual_anchor` fields on Character and Location are injected verbatim at the
very beginning of prompt identity. Never paraphrase or summarize them. They must
be comma-separated physical/visual tags only:

- Characters need 15-20 appearance tags ending with
  `", Same character, same appearance."`
- Locations need at least 15 environment tags.

### Event system for web dashboard

Every stage `run()` accepts `on_event: EventCallback | None`. The CLI passes
`None`. The future web server injects a callback that streams to the browser
over SSE. See `events.py` for the event schema and FastAPI SSE example. Always
add `emit()` calls alongside `console.print()` calls in stage code.

### ComicPage JSON as editing surface

`assembly/pages/page_NNN.json` is the canonical artifact for Stage 7. It is
read, edited manually or via future web editor, and re-rendered by
`pipeline export`. Never write rendering logic that bypasses this JSON.

---

## The assembly system (Stage 7)

Current focus: Stage 6 generation and Stage 7 assembly.

### Position contract

Applies to both `Bubble` and `Sfx`.

```text
x, y = None   -> CSS auto-layout (default)
                  Bubble narration -> .captions container at panel top
                  Bubble speech/thought -> .bubble-auto flex at panel bottom
                  Sfx -> centered, bottom 18% of panel

x, y = float  -> Pinned by web editor (absolute px from panel top-left)
                  Rendered as position:absolute; left:Xpx; top:Ypx
                  CSS class "pinned" added
```

This contract is the foundation of the visual editor. The same JSON fields that
the Python renderer uses will be set by drag-and-drop in the browser.

### Bubble model (`models/comic_page.py`)

- `id`: deterministic string `"{scene_id}-p{panel_number}-b{dialogue_index}"`
- `type`: `"speech"` | `"thought"` | `"narration"`
- `side`: `"left"` | `"right"` | `"center"`
- `x`, `y`, `width`: `None` = auto, float = pinned

### Sfx model (`models/comic_page.py`)

- `text`: SFX string, uppercased at render time
- `x`, `y`: `None` = auto, float = pinned
- `rotation`: degrees, default `-4.0`
- `font_size`: px override; `None` = use `--sfx-font-size`

### Theme system (`assembly/html_renderer.py`)

- CSS variables in `_BASE_VARS` define defaults for visual elements.
- `THEMES` overrides variables per named theme.
- `write_theme_css()` writes `assembly/theme.css` on first run.
- `detect_theme()` auto-selects theme from `style_template` keywords.
- To add a theme: add to `THEMES`, then update `detect_theme()`.

### Playwright rendering

- `browser_context()` yields a reusable browser. Use it when rendering multiple
  pages.
- `render_html_to_png(html, path, *, browser=None, source_path=None)` should
  load via `page.goto("file://...")`, not `page.set_content()`, so Chromium can
  access `file://` images and fonts.
- `build_page_html(page, project_dir, custom_css, image_url_fn, font_url_fn)`
  accepts URL hooks. Use `None` for CLI/Playwright file URLs; use HTTP builders
  for the web server.

### Known limitation — bubble tails

Current CSS `::before/::after` tails always point upward. This is wrong for
pinned bubbles where the character can be anywhere. The planned fix is SVG tails
with `tail_x/tail_y` target points on the `Bubble` model. Do not build the
drag-and-drop editor until this is implemented.

---

## Current model config

Defaults live in `config.py` and may be overridden by project `config.yaml`.
Do not push model version choices into prompt templates.

| Stage | Model |
|---|---|
| Extraction | `gemini-3.1-pro-preview` |
| Screenplay | `gemini-3.1-pro-preview` |
| Panel breakdown | `gemini-3.1-flash-lite-preview` |
| Image prompts | `gemini-3.1-flash-lite-preview` |
| Embeddings | `gemini-embedding-001` |
| Image generation primary | `gemini-3-pro-image-preview` |
| Dev-mode image fallback | `gemini-3.1-flash-image-preview` |

Image model routing in `clients/flux.py`:

- no `/` in model name -> Gemini native `generateContent`
- contains `/` -> Together AI
- `imagen-*` is no longer supported

---

## Event schema

```python
{"type": "stage_begin",    "stage": str, "total": int}
{"type": "stage_progress", "stage": str, "done": int, "total": int}
{"type": "stage_complete", "stage": str, "done": int, "total": int}
{"type": "stage_fail",     "stage": str, "message": str}
{"type": "log",            "stage": str, "level": str, "message": str}
# level: "info" | "warn" | "error" | "dim" | "bold"
```

FastAPI SSE example is in `events.py`.

---

## State machine

`state.json` is the source of truth. Stages:

`pending` -> `running` -> `awaiting_review` (checkpoint stages only) ->
`complete` / `failed`.

Checkpoint stages: `extract`, `index`, `generate`.

Key helpers in `state.py`: `begin_stage`, `complete_stage`, `fail_stage`,
`approve_stage`, `record_item_done`, `record_item_failed`.

State writes are atomic: temp file + rename prevents corruption on crash.

---

## Configuration priority

Highest to lowest:

1. Shell environment variables
2. Nearest `.env` file, walked up from `project_dir`
3. `config.yaml` in project directory
4. Pydantic field defaults in `config.py`

---

## Next planned work

1. SVG bubble tails: add `tail_x/tail_y: float | None` to `Bubble`; render SVG
   `<path>` tail pointing from bubble edge toward target point when pinned.
2. Web dashboard: FastAPI server, SSE streaming, REST API for `ComicPage` JSON,
   export endpoint, static serving for images and fonts.
3. Visual drag-and-drop editor: browser loads the same HTML/CSS from
   `build_page_html`; JS sets `Bubble.x/y` and `Sfx.x/y`; PATCHes JSON back to
   server.

---

## What not to do

- Do not add backwards-compatibility shims for old JSON formats. Existing
  projects can be rebuilt.
- Do not add speculative abstractions for hypothetical future requirements.
- Do not collapse stages or add cross-stage logic.
- Do not add error handling for scenarios that cannot happen in the current
  pipeline.
- Do not mock the event system for testing; it is a pass-through lambda.
- Do not push model version choices into prompt templates.

---

## Project directory structure

```text
projects/my-novel/
├── config.yaml
├── state.json
├── story_bible.json
├── input/novel.epub
├── scenes/
├── qdrant_data/
├── refs/
├── plates/
├── screenplays/
├── panels/
├── prompts/
├── images/
├── assembly/
│   ├── theme.css
│   ├── pages/
│   │   ├── page_001.json
│   │   └── page_001.png
│   └── html/
│       └── page_001.html
└── exports/
    ├── comic.pdf
    └── comic.cbz
```
