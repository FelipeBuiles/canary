# Canary — Detailed Agent Context

Detailed reference for agentic coding sessions. The root `AGENTS.md` stays
compact. Open this file when work touches pipeline architecture, stage contracts,
generation, assembly, or project artifacts.

---

## Project Overview

**What it is:** A Python/React application that converts novels (EPUB/TXT/PDF) into
comic books (PDF/CBZ) via an 8-stage LLM + image-generation pipeline.

**Status:** Early MVP. The web server is the primary interface — the CLI only
has `init` and `serve`. All pipeline operations are HTTP API endpoints.

**Key constraint:** All model inference runs through external cloud APIs.
No local GPU execution.

---

## Codebase Map

```
novel_to_comic/src/novel_to_comic/
├── cli.py                  # Click CLI — init, serve (run/approve/status via API)
├── config.py               # Pydantic Config loaded from config.yaml + .env
├── state.py                # Pipeline state machine — state.json, stage status, cost
├── events.py               # Event callback system for SSE streaming
├── layout_planning.py      # LayoutPlan model + helpers for plan→pages projection
├── prompting.py            # Prompt-building for PlannedPanel + style samples
├── clients/
│   ├── gemini.py           # Async Gemini wrapper (Vertex AI or developer API)
│   ├── claude.py           # Anthropic Claude wrapper
│   ├── flux.py             # Image gen router: Gemini / OpenAI / OpenRouter / Together
│   └── embeddings.py       # Google Vertex / OpenAI embedding clients
├── stages/
│   ├── s1_extract.py       # Novel → Story Bible JSON
│   ├── s2_index.py         # Character refs + location plates (cast)
│   ├── s3_screenplay.py    # Scene prose → screenplay (adapt)
│   ├── s4_layout_plan.py   # Screenplay → page/panel layout plan (plan)
│   ├── s4_panels.py        # Layout plan → legacy PanelBreakdown (storyboard)
│   ├── s5_prompts.py       # Planned panels → image prompts (direct)
│   ├── s6_generate.py      # Image generation (draw)
│   └── s7_assemble.py      # ComicPage JSON → HTML → PNG → PDF/CBZ (compose)
├── models/
│   ├── story_bible.py      # Character, Location, Scene, NarrativeArc, Prop
│   ├── panel.py            # PanelBreakdown, DialogueLine, Screenplay, ScreenplayBeat
│   ├── prompt.py           # ImagePrompt
│   ├── layout_plan.py      # LayoutPlan, PlannedPanel, PlannedPage, PanelGeometry
│   └── comic_page.py       # ComicPage, PagePanel, Bubble, Sfx, BubbleTail
├── assembly/
│   └── html_renderer.py    # build_page_html(), browser_context(), render_html_to_png()
├── rag/
│   ├── store.py            # Optional Qdrant vector store
│   └── chunker.py          # Scene-boundary text chunking
└── server/
    ├── app.py              # FastAPI app factory (create_app)
    ├── routers/
    │   ├── pipeline.py     # run, approve, reset, events (SSE), stage errors
    │   ├── projects.py     # list, status, create
    │   ├── stages.py       # story-bible, screenplays, panels, prompts, images
    │   ├── pages.py        # page JSON read/write, preview PNG, static files
    │   ├── config.py       # config read/patch
    │   ├── export.py       # PDF/CBZ export trigger + download
    │   └── styles.py       # style suggestions, sample generation, active style, is_style_selected gate
    ├── generation_jobs.py  # Job queue for async image/style generation
    └── telemetry.py        # OpenTelemetry span emission
```

---

## The 8 Pipeline Stages

All stage names (used in state, API routes, and CLI paths):

| # | Stage name | Module | Checkpoint? | LLM used |
|---|-----------|--------|-------------|----------|
| 1 | `extract` | `s1_extract.py` | Yes | Gemini 3.1 Pro |
| 2 | `cast` | `s2_index.py` | Yes | Gemini (image gen) |
| 3 | `adapt` | `s3_screenplay.py` | No | Gemini 3.1 Pro |
| 4 | `plan` | `s4_layout_plan.py` | No | Gemini Pro by default (`plan_mode: llm`) |
| 5 | `storyboard` | `s4_panels.py` | No | None (projection from layout plan) |
| 6 | `direct` | `s5_prompts.py` | No | Gemini Flash-Lite (prompt assembly only) |
| 7 | `draw` | `s6_generate.py` | Yes | Gemini / OpenAI / OpenRouter / Together |
| 8 | `compose` | `s7_assemble.py` | No | None (deterministic) |

**Checkpoint stages** (`CHECKPOINT_STAGES = {"extract", "cast", "direct", "draw"}`):
pipeline pauses at `awaiting_review` after the stage completes. Advance with
`POST /api/projects/{project}/approve/{stage}` or the web UI.

---

## Architecture Decisions

### Pipeline is API-only, not CLI

There is no `pipeline run <stage>` command. The CLI (`cli.py`) only has `init`
and `serve`. All pipeline operations are HTTP endpoints. This means:
- `pipeline serve --projects-dir .` starts the web server
- Pipeline is controlled via the web UI or direct API calls
- See `server/routers/pipeline.py` for all endpoints

### Decomposition over end-to-end

Each LLM call does exactly one thing. This enables targeted re-runs, clean error
recovery, and human review at boundaries. Never collapse stages.

### Text composited in post

Speech bubbles, narration, SFX are rendered in Stage 8 (`compose`), never
generated inside images. This avoids OCR issues and allows bubble editing without
regenerating images.

### Visual anchors are sacred

`visual_anchor` fields on `Character` and `Location` are injected verbatim at the
very beginning of every image prompt. Never paraphrase or summarize them.

### Event system for web dashboard

Every stage `run()` accepts `on_event: EventCallback | None`. The web server
injects a callback that streams events to the browser over SSE. See `events.py`
for the event schema. Always add `emit()` calls alongside `console.print()`
calls in stage code.

### Style gate (backend-enforced)

After extract completes, the backend blocks `POST /run` for any post-extract stage
unless a style is selected. The check lives in `is_style_selected()` in
`server/routers/styles.py` and is called from `pipeline.py`'s `run_pipeline()`.
The status API returns `style_selected: bool` (sourced from `config.yaml`) so the
frontend can gate navigation without depending on stale React Query cache.

### Layout plan as planner-owned artifact

Stage 4 (`plan`) produces `plan/layout_plan.json` — a `LayoutPlan` containing
`PlannedPage` and `PlannedPanel` records. Downstream stages (storyboard, direct,
draw) read from this plan and project it into their own artifacts. The plan is
the source of truth for page/panel structure.

Default planning mode is `plan_mode: "llm"`: Stage 4 calls Gemini once per scene
to merge screenplay beats into panels, add shot/lighting/mood metadata, and flag
rare page breaks. If a scene-level LLM call fails, that scene falls back to the
heuristic one-beat-per-panel planner. Use `plan_mode: "heuristic"` to force the
deterministic fallback behavior.

### ComicPage JSON as editing surface

`compose/pages/page_NNN.json` is the canonical artifact for Stage 8. It is
read, edited manually or via the web editor, and re-rendered by the export API.
Never write rendering logic that bypasses this JSON.

---

## The Assembly System (Stage 8 — compose)

### Position contract (Bubble and Sfx)

| Value of x/y | Behaviour |
|---|---|
| `None` | CSS auto-layout. Narration → top of panel. Speech/thought → bottom. SFX → centered at bottom 18%. |
| `float` (pixels) | Pinned — rendered as `position: absolute; left: Xpx; top: Ypx`. Set by web editor drag-and-drop. |

### Bubble model (`models/comic_page.py`)

```python
id: str              # "{scene_id}-p{panel_num}-b{dialogue_index}"
type: Literal["speech", "thought", "narration"]
text: str
speaker_id: str | None
speaker_name: str | None
side: Literal["left", "right", "center"]
x, y, width: float | None   # None = auto, float = pinned
tail: BubbleTail | None     # SVG tail with tail_x, tail_y target points
```

### Sfx model

```python
text: str            # Uppercased at render time
x, y: float | None   # None = auto, float = pinned
rotation: float      # degrees, default -4.0
font_size: int | None
```

### Theme system (`assembly/html_renderer.py`)

- CSS variables in `_BASE_VARS` define defaults for all visual elements.
- `THEMES` dict overrides variables per named theme.
- `write_theme_css()` writes `compose/theme.css` on first run.
- `detect_theme()` auto-selects theme from `style_template` keywords.
- Available themes: `default`, `noir`, `manga`, `vintage`, `painted`.

### Playwright rendering notes

- `browser_context()` yields a reusable Playwright browser instance.
- `render_html_to_png()` must load via `page.goto("file://...")` not
  `page.set_content()` so Chromium can access local images and fonts.
- `build_page_html()` accepts `image_url_fn` and `font_url_fn` hooks — pass
  `None` for CLI/file URLs, HTTP builders for the web server.

### Bubble tails (planned)

Current CSS `::before/::after` tails always point upward. The planned fix adds
`BubbleTail` with `tail_x`/`tail_y` target points. Do not build the visual
drag-and-drop editor until SVG tails are implemented.

---

## Current Model Config

Defaults in `config.py`, overridable via project `config.yaml`.

### LLM models (text)

| Stage | Model | Notes |
|-------|-------|-------|
| `extract` | `gemini-3.1-pro-preview` | 1M context, full-novel extraction |
| `adapt` | `gemini-3.1-pro-preview` | Screenplay writing |
| `plan` | `gemini-3.1-pro-preview` | Scene-level beat merging and layout planning |
| `storyboard` | None | Projection from layout plan |
| `direct` (prompts) | `gemini-3.1-flash-lite-preview` | Prompt assembly |

### Embeddings

`gemini-embedding-001` via Google Vertex AI (3072 dims). Qdrant RAG index is
optional (`enable_rag_index: false` by default).

### Image generation (`image_provider` + `image_model`)

Configured via two fields:
- `image_provider: "gemini" | "openai" | "openrouter" | "together"`
- `image_model: str` — provider-specific model ID

Defaults:
- `image_provider: "gemini"`
- `image_model: "gemini-3-pro-image-preview"` (Gemini 3 Pro Image, "Nano Banana Pro")
- `fallback_image_model: "gemini-3.1-flash-image-preview"` (Gemini 3.1 Flash Image)

Routing in `clients/flux.py`:
- `image_provider == "gemini"` → Vertex AI or developer API
- `/` in model name (e.g. `"black-forest-labs/flux-1-dev"`) → Together AI
- `gpt-image-*` → OpenAI
- Otherwise → OpenRouter

`dev_mode: true` substitutes `fallback_image_model` for faster iteration.

---

## Event Schema

```python
{"type": "stage_begin",    "stage": str, "total": int}
{"type": "stage_progress", "stage": str, "done": int, "total": int}
{"type": "stage_complete", "stage": str, "done": int, "total": int}
{"type": "stage_fail",     "stage": str, "message": str}
{"type": "log",            "stage": str, "level": str, "message": str}
# level: "info" | "warn" | "error" | "dim" | "bold"
```

SSE endpoint: `GET /api/projects/{project}/events`

---

## State Machine

`state.json` is the source of truth. Stage states:

```
pending → running → awaiting_review (checkpoint stages only) → complete / failed
```

**Stage names:** `["extract", "cast", "adapt", "plan", "storyboard", "direct", "draw", "compose"]`

**Checkpoint stages:** `{"extract", "cast", "direct", "draw"}`

Key helpers in `state.py`: `begin_stage`, `complete_stage`, `fail_stage`,
`approve_stage`, `record_item_done`, `record_item_failed`.

State writes are atomic: temp file + rename prevents corruption on crash.

---

## Configuration Priority

(highest wins)

1. Shell environment variables
2. Nearest `.env` file, walked up from `project_dir`
3. `config.yaml` in project directory
4. Pydantic field defaults in `config.py`

---

## Key Models

### LayoutPlan (`models/layout_plan.py`)

Planner-owned artifact produced by stage 4 (`plan`). Contains:
- `planned_pages: list[PlannedPage]` — page structure with panel geometries
- `planned_panels: list[PlannedPanel]` — per-panel metadata (scene, shot type,
  shape intent, generation mode, crop/framing contract, camera note, lighting,
  page-break hints)
- `user_overrides: dict` — panel-level overrides set by the web editor
- `regeneration_impact: dict` — tracks which panels need regeneration

Key helpers in `layout_planning.py`:
- `planned_panel_index(plan)` → `dict[panel_id, PlannedPanel]`
- `scene_panel_map(plan)` → `dict[scene_id, list[PlannedPanel]]`
- `project_layout_plan_to_pages(...)` — projects layout plan into ComicPage JSON

### ComicPage (`models/comic_page.py`)

Canonical editing surface for Stage 8. Contains page-level data plus per-panel
`PagePanel` objects, each with `Bubble` list and optional `Sfx`.

### ImagePrompt (`models/prompt.py`)

Produced by Stage 6 (`direct`). Contains `full_prompt` (assembled string),
project-relative `reference_image_paths`, transition hints, `continuity_note`,
and generation dimensions.

---

## Project Directory Structure

```
projects/my-novel/
├── config.yaml              # API keys + pipeline config
├── state.json               # Stage progress, costs, failed items
├── story_bible.json         # Central artifact — all downstream stages read this
├── input/
│   └── novel.epub
├── scenes/                  # Extracted scene text files (scene_001.txt …)
├── refs/                    # Character reference sheets
│   └── char_NNN/
│       ├── front.png
│       ├── three_quarter.png
│       ├── side.png
│       └── action.png
├── plates/                  # Location background plates (loc_NNN.png …)
├── adapt/                   # Per-scene screenplay JSON
│   └── scene_NNN.json
├── plan/
│   └── layout_plan.json     # Planner-owned page/panel structure
├── storyboard/              # Per-panel breakdown JSON (legacy compat)
│   └── scene_NNN/
│       └── panel_NNN.json
├── direct/                  # Per-panel image prompt JSON
│   └── scene_NNN/
│       └── panel_NNN.json
├── draw/                    # Generated panel images
│   └── scene_NNN/
│       └── panel_NNN.png
├── compose/                 # Stage 8 output
│   ├── theme.css            # Editable CSS — regenerate with export
│   ├── pages/
│   │   ├── page_NNN.json    # Canonical editing surface (ComicPage)
│   │   └── page_NNN.png     # Rendered preview
│   └── html/
│       └── page_NNN.html    # HTML preview — open in browser, edit CSS, hard-refresh
└── exports/
    ├── comic.pdf
    └── comic.cbz
```

---

## What Not To Do

- Do not add a `pipeline run <stage>` CLI command — the architecture is API-first.
- Do not add backwards-compatibility shims for old JSON formats.
- Do not add speculative abstractions for hypothetical future requirements.
- Do not collapse stages or add cross-stage logic.
- Do not push model version choices into prompt templates.
- Do not mock the event system for testing (pass-through lambda).

---

## Next Planned Work

1. **SVG bubble tails:** Add `tail_x`/`tail_y` to `Bubble`; render SVG `<path>`
   tail pointing from bubble edge toward target point when pinned.
2. **Web dashboard improvements:** Live SSE activity drawer, per-action cost
   previews, bulk panel regeneration.
3. **Visual page editor:** Drag-and-drop panel reordering across pages,
   persistent version history.
