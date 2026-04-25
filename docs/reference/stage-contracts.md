# Stage I/O Contracts

What each pipeline stage reads and writes. Each stage runs independently —
it reads its inputs from disk and writes its own outputs. Never add cross-stage logic.

**Manually maintained.** Update when stage I/O changes.

---

## Stages at a Glance

| # | Stage | CLI/API name | LLM | Checkpoint? |
|---|-------|-------------|-----|-------------|
| 1 | Extract | `extract` | Gemini 3.1 Pro | Yes |
| 2 | Cast | `cast` | Image gen (config.provider) | Yes |
| 3 | Adapt | `adapt` | Gemini 3.1 Pro | No |
| 4 | Plan | `plan` | Gemini Pro by default (`plan_mode: llm`) | No |
| 5 | Storyboard | `storyboard` | None (projection from layout plan) | No |
| 6 | Direct | `direct` | Gemini Flash-Lite | No |
| 7 | Draw | `draw` | Image gen (config.provider) | Yes |
| 8 | Compose | `compose` | None (deterministic) | No |

**Checkpoint stages** (`CHECKPOINT_STAGES = {"extract", "cast", "direct", "draw"}`):
pipeline pauses at `awaiting_review` after the stage completes. Advance with
`POST /api/projects/{project}/approve/{stage}` via the API.

---

## Stage 1 — Extract (`s1_extract.py`)

**Reads:**
- `input/<novel_file>` (`.txt`, `.epub`, or `.pdf`)

**Writes:**
- `story_bible.json` — central artifact; all downstream stages read this
- `scenes/scene_NNN.txt` — one file per extracted scene

**What it does:** Uses Gemini 3.1 Pro (1M context) to extract characters,
locations, scenes, narrative arcs, and props from the entire novel. Also splits
the novel into per-scene text files.

---

## Stage 2 — Cast (`s2_index.py`)

**Reads:**
- `story_bible.json`
- `scenes/scene_NNN.txt`

**Writes:**
- `refs/char_NNN/` — character reference sheets: `front.png`, `three_quarter.png`, `side.png`, `action.png`
- `plates/loc_NNN.png` — location background plates
- Optional Qdrant collection when `enable_rag_index: true`

**What it does:** Generates character reference images (4 angles) and location
plates via the configured image provider. These reference images are injected
into Stage 7 prompts. RAG indexing is skipped by default because downstream
stages read scene files directly.

---

## Stage 3 — Adapt (`s3_screenplay.py`)

**Reads:**
- `story_bible.json`
- `scenes/scene_NNN.txt` (per scene)

**Writes:**
- `screenplays/scene_NNN.json` — one `Screenplay` JSON per scene

**What it does:** Converts raw scene prose into screenplay format with beats
(action/dialogue/SFX/transition). Injects scene-specific Story Bible context
directly into the prompt.

---

## Stage 4 — Plan (`s4_layout_plan.py`)

**Reads:**
- `story_bible.json`
- `screenplays/scene_NNN.json` (all scenes)

**Writes:**
- `plan/layout_plan.json` — planner-owned `LayoutPlan` JSON

**What it does:** Produces the authoritative page/panel structure for the comic.
In default `plan_mode: "llm"`, calls Gemini once per scene to merge consecutive
beats into comic panels, vary shot language, set lighting/mood, and mark rare
narrative page breaks. If the LLM call fails for a scene, that scene falls back
to the deterministic heuristic planner. `plan_mode: "heuristic"` keeps the
one-beat-per-panel behavior.

After scene planning, Stage 4 applies a cross-scene transition pass and an
importance-aware paginator. The paginator selects `layout_template` values from
`LAYOUT_PRESET_GEOMETRIES`, respects `page_break_after`, and gives `hero` /
`splash` panels more visual space. This plan is the source of truth for all
downstream stage ordering.

---

## Stage 5 — Storyboard (`s4_panels.py`)

**Reads:**
- `plan/layout_plan.json`

**Writes:**
- `storyboard/scene_NNN/panel_NNN.json` — one `PanelBreakdown` JSON per panel

**What it does:** Converts `PlannedPanel` records from the layout plan into
legacy `PanelBreakdown` files. Maintains compatibility with any storyboard-facing
tools during the migration period.

---

## Stage 6 — Direct (`s5_prompts.py`)

**Reads:**
- `plan/layout_plan.json`
- `story_bible.json` (for character/location visual anchors)
- `refs/char_NNN/*.png` (reference image paths)
- `plates/loc_NNN.png` (plate paths)

**Writes:**
- `direct/scene_NNN/panel_NNN.json` — one `ImagePrompt` JSON per panel

**What it does:** Assembles the complete image generation prompt for each panel.
Injects `visual_anchor` fields verbatim, style template, and project-relative
reference image paths. Prompt metadata carries `planned_panel_id`, shape intent,
generation mode, crop/framing contract, transition hints, and optional
`continuity_note`.

---

## Stage 7 — Draw (`s6_generate.py`)

**Reads:**
- `direct/scene_NNN/panel_NNN.json`
- `refs/char_NNN/*.png` (loaded as binary for multi-reference)
- `plates/loc_NNN.png`

**Writes:**
- `draw/scene_NNN/panel_NNN.png`

**What it does:** Runs image generation against the planner-owned prompt
contracts. Routes to the configured `image_provider`. Subject references are
loaded from project-relative prompt paths, while style/continuity references use
the adjacent previous panel for smooth transitions or the style sample plus
location plate otherwise. Generated image metadata records `planned_panel_id`.
Pauses for human review before Stage 8.

---

## Stage 8 — Compose (`s7_assemble.py`)

**Reads:**
- `draw/scene_NNN/panel_NNN.png`
- `plan/layout_plan.json`
- `storyboard/scene_NNN/panel_NNN.json` (compatibility fallback only)
- `story_bible.json` (character names for bubble attribution)

**Writes:**
- `compose/pages/page_NNN.json` — **canonical editing surface** (`ComicPage` model)
- `compose/pages/page_NNN.png` — rendered preview
- `compose/html/page_NNN.html` — HTML preview (open in browser, edit `theme.css`, hard-refresh)
- `compose/theme.css` — CSS variables (written on first run; user-editable)
- `exports/comic.pdf` and/or `exports/comic.cbz` (on export)

**What it does:** Projects the layout plan into `ComicPage` JSON, then renders
HTML via the theme system and screenshots to PNG via Playwright. The
`page_NNN.json` file is the canonical Stage 8 editing surface.

---

## Re-running Stages

Use the web UI or the pipeline API (not the CLI):

```bash
# Run all stages from current state
curl -X POST "http://localhost:8000/api/projects/my-novel/run"

# Run a specific stage (clears downstream outputs)
curl -X POST "http://localhost:8000/api/projects/my-novel/run?stage=draw"

# Retry failed items within a stage
curl -X POST "http://localhost:8000/api/projects/my-novel/run?stage=draw&retry_failed=true"

# Approve a checkpoint stage
curl -X POST "http://localhost:8000/api/projects/my-novel/approve/draw"

# Reset a stale stage
curl -X POST "http://localhost:8000/api/projects/my-novel/reset/draw"

# Re-export without regenerating images
curl -X POST "http://localhost:8000/api/projects/my-novel/export"
```

The state machine respects partial completion — already-done items are skipped
unless `--force` or `retry_failed=true` is used.
