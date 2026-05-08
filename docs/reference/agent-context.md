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
├── state.py                # Pipeline state machine — state.json, stage status, cost, usage_log
├── events.py               # Event callback system for SSE streaming
├── layout_planning.py      # LayoutPlan model + helpers for plan→pages projection
├── prompting.py            # Prompt-building for PlannedPanel + style samples
├── ai/
│   ├── client.py           # LiteLLM-backed AI client + ai_usage_events ledger
│   ├── context.py          # request-scoped user/project/stage metadata
├── clients/
│   ├── text.py             # Text compatibility wrapper → ai.client
│   ├── flux.py             # Image compatibility wrapper → ai.client
├── usage.py                    # UsageRecord, ApiResult, pricing, cost calculation
├── stages/
│   ├── s1_extract.py       # Novel → Story Bible JSON
│   ├── s2_index.py         # Character refs + location plates (cast) — no longer uses tenacity; retry handled by ai/client.py
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
└── server/
    ├── app.py              # FastAPI app factory (create_app)
    ├── env.py              # Shared environment variable helpers (bool_env)
    ├── routers/
    │   ├── pipeline.py     # run, approve, reset, events (SSE), stage errors
    │   ├── projects.py     # list, status, create
    │   ├── stages.py       # story-bible, screenplays, panels, prompts, images
    │   ├── pages.py        # page JSON read/write, preview PNG, static files
    │   ├── config.py       # config read/patch
    │   ├── export.py       # PDF/CBZ export trigger + download
    │   └── styles.py       # style suggestions, sample generation, active style, is_style_selected gate
    ├── generation_jobs.py  # Job queue for async image/style generation
    └── telemetry.py        # OpenTelemetry span emission (uses shared bool_env from env.py)
```

---

## The 8 Pipeline Stages

All stage names (used in state, API routes, and CLI paths):

| # | Stage name | Module | Checkpoint? | LLM used |
|---|-----------|--------|-------------|----------|
| 1 | `extract` | `s1_extract.py` | Yes | Configurable text model (default: Gemini 3.1 Pro) |
| 2 | `cast` | `s2_index.py` | Yes | Gemini (image gen) |
| 3 | `adapt` | `s3_screenplay.py` | No | Configurable text model (default: Gemini 3.1 Pro) |
| 4 | `plan` | `s4_layout_plan.py` | No | Configurable text model (default: Gemini Pro, `plan_mode: llm`) |
| 5 | `storyboard` | `s4_panels.py` | No | None (projection from layout plan) |
| 6 | `direct` | `s5_prompts.py` | No | Configurable text model (default: Gemini Flash-Lite) |
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

### Unified AI client (`ai/client.py`)

All runtime text and image generation goes through `novel_to_comic.ai.client`,
which calls LiteLLM Proxy using OpenAI-compatible HTTP endpoints, records
`ai_usage_events`, and returns existing `ApiResult[T]` values through thin
`clients/text.py` and `clients/flux.py` compatibility wrappers.

The client includes application-level retry logic: 3 retries with exponential
backoff (delay doubles each attempt, capped at 10s) on transient HTTP errors
(status 429, 502, 503, 504) and connection errors (`ConnectError`, `ReadError`,
`WriteError`, `PoolTimeout`). After all retries are exhausted, the last error
is raised.

The shared `httpx.AsyncClient` pool is closed on FastAPI shutdown via the app
lifespan handler in `server/app.py`.

The `generateImage()` function passes a `steps` parameter through to the image
API when provided, allowing per-request control of diffusion steps.

### Quality presets

`quality_preset: "fast" | "balanced" | "quality" | null` overrides all four text
model fields at once. `dev_mode` forces `"fast"` regardless. When set, individual
model fields are ignored (with a warning if they were explicitly changed from defaults).

**Note:** All three presets currently resolve to the same gateway aliases. This is
transitional during the LiteLLM migration — the actual model routing is controlled
by the LiteLLM `config.yaml` per deployment.

Config exposes `effective_extraction_model()`, `effective_screenplay_model()`,
`effective_panel_model()`, `effective_prompt_model()` — always use these instead
of reading the raw fields.

### Usage tracking (`usage.py`)

Every API call returns an `ApiResult[T]` pairing the value with a `UsageRecord`.
State accumulates real costs via `record_item_done(usage=...)` and
`record_api_usage(...)`. Before a stage runs, `estimate_text_cost()` /
`estimate_image_cost()` set `estimated_cost_usd` on the stage state.

`pricing.yaml` has been removed. Pricing now uses
`litellm_model_prices.cached.json` (LiteLLM model pricing cache) plus
`litellm_pricing_overrides.yaml` (project-specific overrides). `audit_pricing()`
checks for missing entries on startup. Unknown models log a warning (once per
model) and return $0.00.

### Text composited in post

Speech bubbles, narration, SFX are rendered in Stage 8 (`compose`), never
generated inside images. This avoids OCR issues and allows bubble editing without
regenerating images.

### Visual anchors are sacred

`visual_anchor` fields on `Character` and `Location` are injected verbatim at the
very beginning of every image prompt. Never paraphrase or summarize them.

### Image-based PDFs are rejected

Stage 1 (`extract`) supports text-based PDFs (extracted with `pypdf`), EPUB, and
plain text. Image-based (scanned) PDFs are rejected with a clear error message:
the LiteLLM gateway does not support raw PDF bytes, so the app cannot pass them
to Gemini's native PDF processing. Users must convert scanned PDFs to text
first or add OCR preprocessing.

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
tail_x, tail_y: float | None # SVG tail target point in panel coordinates
tail_direction: Literal["auto", "up", "down"] # CSS-tail direction fallback
font_family, font_size, font_color: optional per-bubble typography
fill_color, border_color, border_width, border_radius: optional shape overrides
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

### Bubble tails

Pinned bubbles can use SVG tails by setting `tail_x` and `tail_y` to a
panel-relative target point. The React editor (`SvgTail.tsx`) and Python
renderer (`html_renderer.py`) both render those target-point tails and suppress
the CSS pseudo-element tail. Bubbles without target points use CSS tails and
`tail_direction`; `auto` points down when a pinned bubble sits near the top of
the panel and up otherwise.

### Compose room modes

The web editor is split into four modes:
- Script — page-indexed bubble text review, per-page translation, and "reveal in
  layout" deep-linking.
- Layout — page canvas, element selection, bubble/SFX dragging, floating or fixed
  property inspector, undo/redo, zoom, page reflow, and planner-backed
  structural overrides.
- Style — lettering/theme generation, project-wide translation, style variables,
  bubble presets, and character voice presets.
- Preview — spread preview using page HTML iframes, fit-to-screen scaling,
  command/meta-wheel zoom, panning while zoomed, and PDF/CBZ export.

---

## Current Model Config

Defaults in `config.py`, overridable via project `config.yaml` or `quality_preset`.

### Text models

Four configurable fields route through LiteLLM gateway aliases:

| Stage | Field | Default (balanced) | Notes |
|-------|-------|--------------------|-------|
| `extract` | `extraction_model` | `extract-balanced` | Full-novel extraction |
| `adapt` | `screenplay_model` | `screenplay-balanced` | Screenplay writing |
| `plan` | `panel_model` | `panel-balanced` | Scene-level beat merging and layout planning |
| `direct` (prompts) | `prompt_model` | `prompt-balanced` | Prompt assembly |

Aliases follow `<intent>-<preset>` (e.g. `extract-fast`, `screenplay-quality`).
Provider routing lives in `litellm/config.yaml`.
When `quality_preset` is set, all five intents (the four above plus `image`) route to that preset's aliases.
`dev_mode` forces the `fast` preset.
Always use `config.effective_*_model()` methods to get the resolved model.

### Image generation (`image_model`)

Runtime image calls go through LiteLLM OpenAI-compatible image endpoints.
`image_provider` is legacy metadata and should not be used for routing new code.

Defaults:
- `image_model: "image-balanced"`
- `fallback_image_model: "image-fast"`

`dev_mode: true` substitutes `fallback_image_model` when `image_model` is at its default.

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
`approve_stage`, `record_item_done`, `record_item_failed`, `record_api_usage`.

Each `StageState` tracks `estimated_cost_usd` (set before run), `cost_usd`
(accumulated from real usage), and `usage_log` (append-only list of `UsageRecord`
dicts for audit).

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
