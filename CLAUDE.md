Behavioral guidelines to reduce common LLM coding mistakes. Merge with project-specific instructions as needed.

**Tradeoff:** These guidelines bias toward caution over speed. For trivial tasks, use judgment.

## 1. Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:
- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them - don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

## 2. Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

## 3. Surgical Changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:
- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it - don't delete it.

When your changes create orphans:
- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: Every changed line should trace directly to the user's request.

## 4. Goal-Driven Execution

**Define success criteria. Loop until verified.**

Transform tasks into verifiable goals:
- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"
- "Refactor X" → "Ensure tests pass before and after"

For multi-step tasks, state a brief plan:
```
1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]
```

Strong success criteria let you loop independently. Weak criteria ("make it work") require constant clarification.

---

**These guidelines are working if:** fewer unnecessary changes in diffs, fewer rewrites due to overcomplication, and clarifying questions come before implementation rather than after mistakes.

# Canary — Agent Context

This file is the primary reference for agentic coding sessions. Read it before making changes.

---

## What this project is

A 7-stage Python CLI pipeline that converts novels (EPUB/TXT) into comic books (PDF/CBZ). It uses LLMs for story analysis and image generation models for panel artwork. Each stage is discrete, resumable, and produces inspectable JSON/file output.

**Status:** Early MVP. Breaking changes are frequent and expected. No test suite yet — this is intentional.

**Long-term goal:** Release as a product. Roadmap:
1. Polish generation (stage 6) and assembly (stage 7) — **current focus**
2. Web dashboard with per-stage manual control and visual output review
3. Visual drag-and-drop editor for speech bubbles, panel layout
4. User insertion into story (inject user's likeness into character references)

---

## Codebase map

```
novel_to_comic/src/novel_to_comic/
├── cli.py                  # Click CLI entry point — init, run, approve, status, export
├── config.py               # Pydantic config loaded from config.yaml + .env
├── state.py                # Pipeline state machine — state.json, stage status, cost tracking
├── events.py               # Event callback system for SSE/WebSocket streaming (web dashboard hook)
├── clients/
│   ├── gemini.py           # Async Gemini wrapper with retry
│   ├── claude.py           # Anthropic Claude wrapper
│   ├── flux.py             # Multi-provider image gen router (Gemini native, Imagen 4, Together AI)
│   └── embeddings.py       # Google / OpenAI embedding clients
├── stages/
│   ├── s1_extract.py       # Novel → Story Bible JSON         [Gemini 3.1 Pro, 1M context]
│   ├── s2_index.py         # RAG index + character refs + location plates
│   ├── s3_screenplay.py    # Scene prose → screenplay         [Claude Sonnet 4.6]
│   ├── s4_panels.py        # Screenplay → panel breakdown JSON [Gemini Flash-Lite]
│   ├── s5_prompts.py       # Panel breakdown → image prompts  [Gemini Flash-Lite]
│   ├── s6_generate.py      # Image generation (async, rate-limited, multi-provider fallback)
│   └── s7_assemble.py      # ComicPage JSON → HTML → Playwright PNG → PDF/CBZ
├── models/
│   ├── story_bible.py      # Character, Location, Scene, NarrativeArc
│   ├── panel.py            # PanelBreakdown, DialogueLine, Screenplay
│   ├── prompt.py           # Image prompt template
│   └── comic_page.py       # ComicPage, PagePanel, Bubble, Sfx — the assembly editing surface
├── assembly/
│   └── html_renderer.py    # build_page_html(), browser_context(), render_html_to_png()
├── rag/
│   ├── store.py            # Qdrant hybrid search (dense + BM25)
│   └── chunker.py          # Scene-boundary text chunking
└── prompts/                # LLM prompt templates (.txt)
```

---

## Architecture decisions

### Decomposition over end-to-end
Each LLM call does exactly one thing. This enables targeted re-runs (`pipeline run panels --scene scene_012`), clean error recovery, and human review at boundaries. Never collapse stages.

### Human checkpoints
Pipeline pauses at stages 1 (story bible), 2 (character design), and 6 (generated panels). `approve_stage()` in `state.py` advances `AWAITING_REVIEW` → `COMPLETE`. The web dashboard will replace `pipeline approve` with UI buttons.

### Text composited in post
Speech bubbles, narration, SFX are rendered in Stage 7, never generated inside images. This avoids OCR issues and allows bubble editing without regenerating images.

### Visual anchors are sacred
`visual_anchor` fields on Character and Location are injected **verbatim** into every image prompt. Never paraphrase or summarize them. They must be 60–80 words (characters) or 40–60 words (locations) of purely physical/visual description, ending with `"Same character, same appearance."` for characters.

### Event system for web dashboard
Every stage `run()` accepts `on_event: EventCallback | None`. The CLI passes `None`. The future web server injects a callback that streams to the browser over SSE. See `events.py` for the event schema and a FastAPI SSE example. **Always add `emit()` calls alongside `console.print()` calls in stage code** — the emit is what the web dashboard will see.

### ComicPage JSON as editing surface
`assembly/pages/page_NNN.json` is the canonical artifact for Stage 7. It is read, edited (manually or via future web editor), and re-rendered by `pipeline export`. Never write rendering logic that bypasses this JSON.

---

## The assembly system (Stage 7) — current focus

### Position contract (critical — applies to both Bubble and Sfx)

```
x, y = None   → CSS auto-layout (default)
                  Bubble narration  → .captions container at panel top
                  Bubble speech/thought → .bubble-auto flex at panel bottom
                  Sfx → centered, bottom 18% of panel

x, y = float  → Pinned by web editor (absolute px from panel top-left)
                  Rendered as position: absolute; left: Xpx; top: Ypx
                  CSS class "pinned" added — overrides auto-layout rules
```

This contract is the foundation of the visual editor. The same JSON fields that the Python renderer uses will be set by drag-and-drop in the browser — no translation layer needed.

### Bubble model (`models/comic_page.py`)
- `id`: deterministic string `"{scene_id}-p{panel_number}-b{dialogue_index}"` — stable across re-renders, resets on full rebuild
- `type`: `"speech"` | `"thought"` | `"narration"`
- `side`: `"left"` | `"right"` | `"center"` — controls tail direction and alignment
- `x`, `y`, `width`: None = auto, float = pinned

### Sfx model (`models/comic_page.py`)
- `text`: the SFX string (uppercased at render time)
- `x`, `y`: None = auto, float = pinned (same contract as Bubble)
- `rotation`: degrees, default −4.0 (matches CSS default)
- `font_size`: px override; None = use `--sfx-font-size` CSS variable

### Theme system (`assembly/html_renderer.py`)
- CSS variables in `_BASE_VARS` define defaults for every visual element
- `THEMES` dict overrides variables per named theme
- `write_theme_css()` writes `assembly/theme.css` on first run — user can edit this freely
- `detect_theme()` auto-selects theme from `style_template` keywords
- To add a new theme: add an entry to `THEMES`, update `detect_theme()`

### Playwright rendering
- `browser_context()` — async context manager, yields a reusable browser. Use this in any loop that renders multiple pages. Never launch a new browser per page.
- `render_html_to_png(html, path, *, browser=None, source_path=None)` — pass `browser=` to reuse, `source_path=` to load from an existing file on disk. **Never use `page.set_content()`** — it gives the page a null origin and Chromium blocks all `file://` sub-resources (images, fonts). Always load via `page.goto("file://...")` which gives the page a real `file://` origin. The `source_path` parameter handles this; when omitted a temp file is used automatically.
- `build_page_html(page, project_dir, custom_css, image_url_fn, font_url_fn)` — both URL function hooks are None for CLI/Playwright (uses `file://` URIs), provide HTTP builders for the web server

### Known limitation — bubble tails
Current CSS `::before/::after` tails always point upward (character above bubble). Fine for auto-layout. **Wrong for pinned bubbles** where the character can be anywhere. The fix is SVG tails with a `tail_x/tail_y` target point on the `Bubble` model. **Do not build the drag-and-drop editor until this is implemented.** See next planned work below.

---

## Current model config (config.py defaults)

| Stage | Model |
|---|---|
| Extraction | `gemini-3.1-pro-preview` |
| Screenplay | `gemini-3.1-pro-preview` |
| Panel breakdown | `gemini-3.1-flash-lite-preview` |
| Image prompts | `gemini-3.1-flash-lite-preview` |
| Embeddings | `gemini-embedding-2-preview` (3072 dims) |
| Image generation (primary) | `gemini-3-pro-image-preview` (Gemini 3 native, free) |
| Image generation (fallback on 429) | `gemini-3.1-flash-image-preview` |
| Screenplay (Claude) | `claude-sonnet-4-6-20250514` |

Image model routing in `clients/flux.py`:
- `imagen-*` prefix → Imagen 4 endpoint
- no `/` in model name → Gemini native (`generateContent`)
- contains `/` → Together AI (FLUX via async client)

---

## Event schema (for web dashboard integration)

```python
{"type": "stage_begin",    "stage": str, "total": int}
{"type": "stage_progress", "stage": str, "done": int, "total": int}
{"type": "stage_complete", "stage": str, "done": int, "total": int}
{"type": "stage_fail",     "stage": str, "message": str}
{"type": "log",            "stage": str, "level": str, "message": str}
# level: "info" | "warn" | "error" | "dim" | "bold"
```

FastAPI SSE example is in `events.py` docstring.

---

## State machine

`state.json` is the source of truth. Stages: `pending` → `running` → `awaiting_review` (checkpoint stages only) → `complete` / `failed`.

Checkpoint stages (pause for human review): `extract`, `index`, `generate`.

Key helpers in `state.py`: `begin_stage`, `complete_stage`, `fail_stage`, `approve_stage`, `record_item_done`, `record_item_failed`.

State writes are atomic: temp file + rename prevents corruption on crash.

---

## Configuration priority (highest → lowest)

1. Shell environment variables (`GEMINI_API_KEY=xxx pipeline run ...`)
2. Nearest `.env` file (walked up from project_dir)
3. `config.yaml` in project directory
4. Pydantic field defaults in `config.py`

---

## Next planned work

1. **SVG bubble tails** — add `tail_x/tail_y: float | None` to `Bubble` model; render SVG `<path>` tail pointing from bubble edge toward target point when pinned. Required before building the visual editor.
2. **Web dashboard** — FastAPI server, SSE streaming via event system, REST API for `ComicPage` JSON (`GET/PATCH /api/pages/{n}`), `POST /api/export`, static file serving for images and fonts (use `image_url_fn` and `font_url_fn` hooks already in `build_page_html`).
3. **Visual drag-and-drop editor** — browser loads same HTML/CSS from `build_page_html`; JS sets `Bubble.x/y` and `Sfx.x/y` on drag; PATCHes JSON back to server.

---

## What NOT to do

- Do not add backwards-compatibility shims for old JSON formats — just change the model and note that existing projects need to be rebuilt
- Do not add speculative abstractions for hypothetical future requirements
- Do not collapse stages or add cross-stage logic — each stage reads its inputs from disk and writes its outputs to disk
- Do not add error handling for scenarios that can't happen in the current pipeline
- Do not mock the event system for testing — it is a pass-through lambda by design
- Do not push model version choices into prompt templates — keep them in `config.py` where they can be overridden

---

## Project directory structure

```
projects/my-novel/
├── config.yaml             # API keys + pipeline settings
├── state.json              # Stage progress, costs, failed items
├── story_bible.json        # Central artifact — ALL downstream stages read this
├── input/novel.epub
├── scenes/                 # Extracted scene text (scene_001.txt …)
├── qdrant_data/            # Qdrant vector store (local Docker)
├── refs/                   # Character reference sheets
│   └── char_001/           #   front.png, three_quarter.png, side.png, action.png
├── plates/                 # Location background plates (loc_001.png …)
├── screenplays/            # Per-scene screenplay JSON
├── panels/                 # Per-panel PanelBreakdown JSON
│   └── scene_001/panel_001.json
├── prompts/                # Assembled image prompts
│   └── scene_001/panel_001.json
├── images/                 # Generated panel images
│   └── scene_001/panel_001.png
├── assembly/
│   ├── theme.css           # Editable CSS variables — run `pipeline export` to apply
│   ├── pages/              # ComicPage JSON (editing surface) + rendered PNGs
│   │   ├── page_001.json
│   │   └── page_001.png
│   └── html/               # HTML previews — open in browser, edit theme.css, hard-refresh
│       └── page_001.html
└── exports/
    ├── comic.pdf
    └── comic.cbz
```
