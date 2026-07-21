# Stage I/O Contracts

> **Status: Current (2026-07-18).** Verify implementation details against
> `state.py`, `stages/__init__.py`, and `server/routers/pipeline.py`. This page
> is the focused contract reference; proposals and plans are not substitutes.

What each pipeline stage reads and writes. Each stage owns its artifact
contract and reads/writes project files; the server may orchestrate explicit
stage chains. Never collapse stages or bypass their artifact boundaries.

**Manually maintained.** Update when stage I/O changes.

---

## Stages at a Glance

| # | Stage | CLI/API name | LLM | Checkpoint? |
|---|-------|-------------|-----|-------------|
| 1 | Extract | `extract` | Configurable text alias (`extract-*`) | Yes |
| 2 | Style | `style` | Configurable prompt alias + image alias | Yes |
| 3 | Cast | `cast` | Image alias through LiteLLM | Yes |
| 4 | Adapt | `adapt` | Configurable screenplay alias (`screenplay-*`) | No |
| 5 | Plan | `plan` | Configurable panel alias (`panel-*`, `plan_mode: llm`) | No |
| 6 | Storyboard | `storyboard` | None (projection from layout plan) | No |
| 7 | Direct | `direct` | None (deterministic prompt spec assembly) | No |
| 8 | Draw | `draw` | Image alias through LiteLLM | Yes |
| 9 | Compose | `compose` | None (deterministic) | No |

**Checkpoint stages** (`CHECKPOINT_STAGES = {"extract", "style", "cast", "draw"}`):
pipeline pauses at `awaiting_review` after the stage completes. Advance with
`POST /api/projects/{project}/approve/{stage}` via the API. `direct` is not a
checkpoint: after cast approval the `adapt → plan → storyboard → direct` chain
runs unattended (see `STAGE_AUTO_CHAIN` in `server/routers/pipeline.py`).

---

## Stage 1 — Extract (`s1_extract.py`)

**Reads:**
- `input/<novel_file>` (`.txt`, `.epub`, or `.pdf`)

**Writes:**
- `story_bible.json` — central artifact; all downstream stages read this
- `scenes/scene_NNN.txt` — one file per extracted scene

**What it does:** Uses the configured extraction model alias
to extract characters, locations, scenes, narrative arcs, and props from the entire
novel. Also splits the novel into per-scene text files.

---

## Stage 2 — Style (`s2_style.py`)

**Reads:**
- `story_bible.json`

**Writes:**
- `samples/style_suggestions.json` — generated style templates and metadata
- `samples/style_N.png` — one sample image per suggestion

**What it does:** Generates five distinct visual style options and one sample
image per option, then pauses for review. The selected style is persisted into
`config.yaml` as `style_template`. Post-style stages are blocked until a style
is selected.

---

## Stage 3 — Cast (`s3_cast.py`)

**Reads:**
- `story_bible.json`
- `samples/style_suggestions.json` and matching `samples/style_N.png` when available
- `config.yaml` active `style_template`

**Writes:**
- `refs/char_NNN/sheet.png` — 2x2 character reference sheet
- `refs/char_NNN/sheet.png.meta.json` — generation metadata
- `refs/char_NNN/front.png`, `three_quarter.png`, `profile.png`, `gesture.png`
  — cropped pose refs derived from the sheet when available
- `refs/char_NNN/instructions.jsonl` — accepted instruction addenda for targeted regen
- `refs/props/{prop_id}/ref.png` — neutral-background prop reference image
- `refs/props/{prop_id}/ref.png.meta.json` — generation metadata
- `refs/props/{prop_id}/instructions.jsonl` — accepted instruction addenda for targeted regen
- `plates/loc_NNN.png` — location background plates
- `plates/loc_NNN.png.meta.json` — generation metadata
- `plates/loc_NNN.instructions.jsonl` — accepted instruction addenda for targeted regen

**What it does:** Generates character reference images (4 angles) and location
plates through the configured image alias, plus one reference image for each
recurring or plot-central story prop. Style samples are used as visual
references where supported. Character, prop, and location references feed
draw-stage requests, with provider-specific filtering in Stage 8.

---

## Stage 4 — Adapt (`s4_screenplay.py`)

**Reads:**
- `story_bible.json`
- `scenes/scene_NNN.txt` (per scene)

**Writes:**
- `screenplays/scene_NNN.json` — one `Screenplay` JSON per scene

**What it does:** Converts raw scene prose into screenplay format with beats
(action/dialogue/SFX/transition). Injects scene-specific Story Bible context
directly into the prompt.

---

## Stage 5 — Plan (`s5_layout_plan.py`)

**Reads:**
- `story_bible.json`
- `screenplays/scene_NNN.json` (all scenes)

**Writes:**
- `plan/layout_plan.json` — planner-owned `LayoutPlan` JSON

**What it does:** Produces the authoritative page/panel structure for the comic.
In default `plan_mode: "llm"`, calls the configured text model once per scene to
merge consecutive beats into comic panels, vary shot language, set lighting/mood,
and mark rare narrative page breaks. If the LLM call fails for a scene, that scene
falls back to the deterministic heuristic planner. `plan_mode: "heuristic"` keeps
the one-beat-per-panel behavior.

After scene planning, Stage 5 applies a cross-scene transition pass and an
importance-aware paginator. The paginator selects `layout_template` values from
`LAYOUT_PRESET_GEOMETRIES`, respects `page_break_after`, and gives `hero` /
`splash` panels more visual space. This plan is the source of truth for all
downstream stage ordering.

---

## Stage 6 — Storyboard (`s5_panels.py`)

**Reads:**
- `plan/layout_plan.json`

**Writes:**
- `storyboard/scene_NNN/panel_NNN.json` — one `PanelBreakdown` JSON per panel

**What it does:** Converts `PlannedPanel` records from the layout plan into
legacy `PanelBreakdown` files. Maintains compatibility with any storyboard-facing
tools during the migration period.

---

## Stage 7 — Direct (`s6_storyboard.py`)

**Reads:**
- `plan/layout_plan.json`
- `story_bible.json` (for character/location visual anchors)
- `refs/char_NNN/sheet.png` and cropped pose images when present
- `refs/props/{prop_id}/ref.png` for story props matched to active panel context
- `plates/loc_NNN.png` (plate paths)

**Writes:**
- `direct/scene_NNN/panel_NNN.json` — one `ImagePrompt` JSON per panel

**What it does:** Builds deterministic `ImagePrompt` specs for each planned
panel. Prompts keep the style out of `full_prompt` for review; draw prepends the
current active `style_template` at generation time so style changes do not
require rebuilding prompt artifacts. Metadata carries `planned_panel_id`,
caption hints, shape intent, generation mode, crop/framing contract, transition
hints, and optional `continuity_note`.
Story props are only carried into `props`/`reference_image_paths` when panel
context indicates the prop is actively used, held, touched, or shown; ambient
similar material alone should not trigger a prop ref.

---

## Stage 8 — Draw (`s7_draw.py`)

**Reads:**
- `direct/scene_NNN/panel_NNN.json`
- `refs/char_NNN/sheet.png` (loaded as binary subject reference)
- `refs/char_NNN/{front,three_quarter,profile,gesture}.png` when available
- `refs/props/{prop_id}/ref.png` for confirmed active story props
- `plates/loc_NNN.png`
- `samples/style_N.png` matching the active style when available

**Writes:**
- `draw/scene_NNN/panel_NNN.png`
- `draw/scene_NNN/panel_NNN.png.meta.json`
- `draw/scene_NNN/panel_NNN.png.failure.json` for provider/policy failures
- `draw/panel_acceptance.json` for explicit panel acceptance state

**What it does:** Runs image generation against the planner-owned prompt
contracts through the LiteLLM gateway image alias. The active style template is
prepended at generation time. Subject references are loaded from project-relative
prompt paths. For Gemini/Together-style routes, draw can add the active style
sample, a location plate, or the previous panel for an explicit `match_cut`.
For Reve (`image-reve`), draw selects up to 4 refs via
`_reve_refs()`: up to 3 subject crops (one per character, framing-selected),
then continuity, prop, style, and location plate to fill remaining slots.
Ordinary requests use v2 `/image/create` with raw ordered references and
`<frame>N</frame>` markers. When `layout_prompts_enabled` is enabled, the
compiled layout is rendered through v2 `/image/render_layout`; region types,
parent hierarchy, normalized boxes, and `image_index` bindings are sent
structurally, and the returned layout echo is persisted beside the panel.
For GPT Image 2 (literal `gpt-image-2` — no longer a gateway alias), draw
keeps style/location/previous-panel context text-only and uploads a minimal
subject ref set: one preferred character crop per visible character, or one
prop ref only when no character refs exist.
Generated image metadata records `planned_panel_id`. Pauses for human review
before compose.

**Notes:**
- `inter_request_delay` has been removed from the draw stage (it was always 0.0).
- `POST /run?stage=draw&retry_failed=true` regenerates failed panels without a
  full draw rerun. It is mutually exclusive with `rerun=true`.
- Provider failures write `.failure.json` files classified as
  `provider_blocked` or `generation_error`; the images API exposes a short
  message and longer `failure_detail` for review.
- Draw stage reconciliation (`_reconcile_completed_draw_stage` in
  `server/routers/projects.py`) only runs when no generation task is currently
  running, not on every `GET /status` poll. This avoids unnecessary state
  mutations during active polling.

---

## Stage 9 — Compose (`s8_compose.py`)

**Reads:**
- `draw/scene_NNN/panel_NNN.png`
- `plan/layout_plan.json`
- `storyboard/scene_NNN/panel_NNN.json` (compatibility fallback only)
- `story_bible.json` (character names for bubble attribution)
- `assembly/lettering_style.json` (project lettering style: theme, font pair, CSS-var overrides)

**Writes:**
- `compose/pages/page_NNN.json` — **canonical editing surface** (`ComicPage` model)
- `compose/pages/page_NNN.png` — rendered preview
- `compose/html/page_NNN.html` — HTML preview (open in browser, hard-refresh)
- `exports/comic.pdf` and/or `exports/comic.cbz` (on export)

**What it does:** Projects the layout plan into `ComicPage` JSON, then renders
HTML via the project lettering style and screenshots to PNG via Playwright. The
`page_NNN.json` file is the canonical Stage 9 editing surface. All page-editor
edits must persist through this JSON instead of bypassing it with renderer-only
state.

**Contract and responsibilities:**
- Compose is deterministic assembly. It does not call image models and does not
  change panel art except for page placement, cropping offsets, and overlays.
- It owns lettering and production elements: speech/thought/narration bubbles,
  SFX, bubble tails, per-bubble typography, panel borders, page numbers, and
  export. The book-wide look (theme, font pair, color/border overrides) comes
  from the project `LetteringStyle`, chosen at the Look stage.
- It reads planner-owned structure from `plan/layout_plan.json`. Structural
  edits such as panel importance, shape intent, generation mode, page reorder,
  layout presets, and repagination are applied back to the layout plan, then
  projected into fresh `ComicPage` files.
- It preserves generated panel images as project-relative paths. The HTML
  renderer receives URL builders for web previews and local file URLs for
  export.
- It treats `Bubble.x/y` and `Sfx.x/y` as panel-relative pixel coordinates.
  `null` means CSS auto-layout; numbers mean the editor pinned the element.
- Speech and thought indicators share measured SVG geometry. `tail_x` / `tail_y`
  are exact panel-relative speaker targets and can be dragged in the page editor.
  When missing, the indicator stays compact and aims toward the planner-owned
  speaker side; `tail_direction` (`auto`, `up`, or `down`) controls its vertical
  fallback direction.
- It exposes three web-editor tabs: Pages for page/bubble/SFX placement, Script
  for text review and translation, and Export for spread review and PDF/CBZ.
  Book-wide lettering is chosen at the Look stage and re-tuned from the Book
  header's lettering menu.
- It must invalidate or replace cached page data carefully. Dragging elements
  updates the specific page cache directly so the editor does not snap back
  during optimistic interaction.
- Stage reruns may rebuild `compose/pages/page_NNN.json` from upstream artifacts.
  Manual page edits are stable across export, but not guaranteed across a
  rebuild from earlier stages.

---

## Re-running Stages

Use the web UI or the pipeline API (not the CLI):

```bash
# Run a specific stage
curl -X POST "http://localhost:8000/api/projects/my-novel/run?stage=draw"

# Rerun a stage from scratch and clear its downstream outputs
curl -X POST "http://localhost:8000/api/projects/my-novel/run?stage=draw&rerun=true"

# Retry only failed draw panels
curl -X POST "http://localhost:8000/api/projects/my-novel/run?stage=draw&retry_failed=true"

# Approve a checkpoint stage
curl -X POST "http://localhost:8000/api/projects/my-novel/approve/draw"

# Reset a stale stage
curl -X POST "http://localhost:8000/api/projects/my-novel/reset/draw"

# Re-export without regenerating images
curl -X POST "http://localhost:8000/api/projects/my-novel/export"
```

The state machine respects partial completion — already-done items are skipped
by stage code unless the stage is explicitly rerun with `rerun=true`, which
resets the selected stage and downstream state/output paths first.
