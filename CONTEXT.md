# Canary — Domain Glossary

Canonical terms for this codebase. When code or docs use a term that conflicts
with a definition here, the conflict should be surfaced and resolved — one term,
one meaning.

---

## Core pipeline concepts

**Stage** — A discrete, resumable unit of the pipeline that reads inputs from
disk and writes its own outputs. Stages never share in-memory state or call each
other directly. There are 9 stages: `extract`, `style`, `cast`, `adapt`, `plan`,
`storyboard`, `direct`, `draw`, `compose`.

**Checkpoint stage** — A stage that pauses at `awaiting_review` after completing,
requiring explicit approval before the pipeline continues. Checkpoint stages are:
`extract`, `style`, `cast`, `direct`, `draw`.

**Story Bible** — The central artifact produced by Stage 1. Contains characters
(with visual anchors), locations, scenes, narrative arcs, and props. All
downstream stages read from it.

**Visual anchor** — A 60–80 word physical description on a `Character` or
`Location` that is injected verbatim at the start of every image prompt. Never
paraphrase or summarize a visual anchor.

**Layout plan** — The planner-owned artifact produced by Stage 5 (`plan`). A
`LayoutPlan` containing `PlannedPage` and `PlannedPanel` records. It is the
source of truth for page/panel structure; all downstream stages project from it.

**Planned panel** — A `PlannedPanel` record inside the layout plan. Carries
scene, shot type, shape intent, generation mode, crop/framing contract, lighting,
and page-break hints. Downstream stages (storyboard, direct, draw) project from
planned panels rather than owning structure themselves.

**Panel breakdown** — A `PanelBreakdown` record produced by Stage 6
(`storyboard`). A legacy-compatibility projection from a `PlannedPanel`. Used by
tools that haven't migrated to reading the layout plan directly.

**Image prompt** — An `ImagePrompt` record produced by Stage 7 (`direct`).
Contains `full_prompt` (the assembled string), project-relative
`reference_image_paths`, transition hints, and `continuity_note`. The
`full_prompt` field is re-derived from other fields — never edit it directly;
use `prompt_assembly.rerender_prompt_body()` after editing the source fields.

**ComicPage** — The canonical Stage 9 editing surface. Stored at
`compose/pages/page_NNN.json`. Contains per-panel `PagePanel` objects, each
with a `Bubble` list and optional `Sfx`. All page edits must go through this
JSON — never bypass it with renderer-only state.

**Style template** — The active visual style for a project, persisted as
`style_template` in `config.yaml`. Chosen by the user during Stage 2 review.
Post-style stages are blocked until a style is selected.

**Style gate** — The backend check (`is_style_selected()` in `server/routers/styles.py`)
that blocks `POST /run` for any post-style stage when no style is selected. The
status API surfaces `style_selected: bool` for the frontend to read; the
frontend must read this field from status rather than from stale React Query cache.

---

## Artifacts and storage

**Artifact** — Any file produced or consumed by a stage. Canonical paths for all
artifacts are defined in `artifacts.py`. Always use functions from `artifacts.py`
to construct paths — never hardcode them in stage or route code.

**Project directory** — The root directory for a single comic project. Contains
`config.yaml`, `state.json`, and all stage output subdirectories (`scenes/`,
`refs/`, `plates/`, `plan/`, `storyboard/`, `direct/`, `draw/`, `compose/`,
`exports/`).

**Panel acceptance** — Explicit per-panel approval state stored in
`draw/panel_acceptance.json`. A panel is accepted when the user has reviewed and
approved its generated image. Acceptance is keyed by image fingerprint so that
regeneration clears the acceptance flag automatically.

---

## Generation and models

**Quality preset** — One of `"fast" | "balanced" | "quality"` (or null). When
set, overrides all five intent model fields (`extract`, `adapt`, `plan`,
`prompt`, `image`) at once. `dev_mode` forces `"fast"`. Always read model
choices via `config.effective_*_model()` methods, not raw config fields.

**LiteLLM alias** — A named model alias configured in `litellm/config.yaml` that
routes to a concrete provider and model. Aliases follow the `<intent>-<preset>`
convention (e.g. `extract-fast`, `image-quality`). All inference goes through
the LiteLLM proxy — there is no direct provider call from application code.

**GPT Image 2** — The `image-quality` alias, the only image alias treated as
GPT Image 2 by `is_gpt_image_2()`. Has a different reference image strategy
than Gemini-style routes: uploads a minimal character crop set and keeps style/
location/continuity context text-only.

**Generation job** — An async background task managed by `server/generation_jobs.py`.
Used for single-asset regeneration (panel, character ref, prop, location plate).
Each job is deduped by kind + payload so retrying an active request returns the
existing job. New generation jobs should go through `server/credited_job.py` so
the credit check and debit are coupled to the job lifecycle in one call.

---

## Server concepts

**StageRuntime** — The object passed as `ctx` to every stage `run()`. Owns the
stage lifecycle: state transitions (`begin` → `complete` | `fail`), event
emission, and cost recording. Stages do not call state functions or thread
`on_event` directly; they call `ctx.log()`, `ctx.progress()`,
`ctx.record_item_done()`, etc.

**CreditedJob** — A generation job with a credit guarantee, created via
`server/credited_job.py`. Asserts sufficient credits before enqueuing, debits
on success, and releases (does nothing extra) on failure. All regen handlers
should use this instead of duplicating the assert/enqueue/debit dance.

**Labs run** — An experimentation run in the Labs subsystem. Not a pipeline run.
A `LabsRunSpec` describes a set of panels and models; `start_run()` generates
each panel against each model/variant combination, storing results under
`{user_id}/_labs/`. Labs runs are independent of pipeline state.

---

## Compose room

**Bubble** — A speech, thought, or narration element in a `ComicPage`. Has
optional `x/y` (null = CSS auto-layout, float = pinned pixel position) and
optional `tail_x/tail_y` (panel-relative SVG tail target point).

**Sfx** — A sound-effect element in a `ComicPage`. Has optional `x/y` and
`rotation`. Uppercased at render time.

**Compose room modes** — The four web-editor views for Stage 9: Script (text
review, translation), Layout (page canvas, drag/drop, undo/redo), Style
(lettering, theme, presets), Preview (spread view, export).

**Theme** — A named CSS variable override set applied to the page renderer.
Available themes: `default`, `noir`, `manga`, `vintage`, `painted`. Detected
automatically from `style_template` keywords; can be overridden per-page or
per-project.

---

## Integration concepts

**Library of Short Stories** — A public-domain literature archive (`libraryofshortstories.com`) integrated as a text source option for project generation. Stories can be imported using their URL or unique story code.

---

## Localization and translation

**Target language (`target_language`)** — The configured project-level language (e.g., English, Spanish, French) that controls generated creative text (dialogue, narration, panel descriptions) down the pipeline. AI models are instructed to translate creative fields while preserving structural keys, IDs, and character/location names verbatim.

**UI localization (i18n)** — The frontend translation system (`web/src/i18n.tsx`) that translates UI labels, buttons, and settings in the browser based on the user's selected preference, separate from the project's target generation language.

---

## Layout and aspect ratios

**GenerationShape** — The target bounding bucket for image generation: `"square"` (1024x1024), `"portrait"` (768x1024), or `"landscape"` (1344x768). All numeric layout aspect ratios are mapped to one of these three shapes for optimal generation quality.

**Aspect tolerance** — The allowable floating-point discrepancy (default 12% or `ASPECT_TOLERANCE = 0.12` in `panel_aspect.py`) between a generated image's aspect ratio and its requested aspect ratio. Crucially, any two ratios that map to the same `GenerationShape` are automatically considered within tolerance.


