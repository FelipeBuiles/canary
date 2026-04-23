# Layout Plan and Compose Implementation Plan

**Date:** 2026-04-23
**Status:** Draft
**Spec:** [2026-04-23-layout-plan-compose-design.md](../specs/2026-04-23-layout-plan-compose-design.md)

## Overview

This plan implements the new `layout plan` layer introduced by the design spec without freezing the current product. The strategy is to add a planner-owned structural artifact first, keep Stage 7 rendering functional during the transition, then progressively shift prompts, generation, and Compose structural editing onto the new source of truth.

The intended end state is:

`story bible -> screenplay beats -> layout plan -> prompts -> generate -> compose/export`

with these ownership rules:

- `layout plan` is canonical for comic structure.
- `assembly/pages/page_NNN.json` remains canonical for Stage 7 presentation editing.
- Compose structural edits write planner overrides into the layout plan.
- Compose presentation edits continue to write projected page JSON.

## Assumptions

- Breaking model and JSON changes are acceptable.
- The repo can tolerate a temporary migration window where `PanelBreakdown` still exists but is no longer the long-term structural source of truth.
- We should minimize cross-stage coupling while still changing stage inputs and outputs deliberately.
- Phase 1 should not require immediate UI parity for structural Compose editing.

## Success Criteria

- A new on-disk `layout plan` artifact exists and is generated from screenplay beats.
- The plan owns planned panel IDs, planned page IDs, panel importance, shape intent, and page assignment.
- Stage 7 can project page JSON from the layout plan without depending on naive panel grouping.
- Stage 5 and Stage 6 can migrate from `PanelBreakdown` to planned panels without breaking generation.
- Compose can eventually separate structural edits from presentation edits using distinct API paths and artifact ownership.

## Workstreams

### 1. Data Model and Artifact Workstream

Add planner-owned models and on-disk artifact format.

Target files:

- `novel_to_comic/src/novel_to_comic/models/`
- `docs/reference/models.md`
- `docs/reference/stage-contracts.md`

Deliverables:

- new models for:
  - `ScreenplayBeat` extensions or companion metadata
  - `PlannedPanel`
  - `PlannedPage`
  - `PanelGeometry`
  - `LayoutPlan`
- deterministic ID strategy for:
  - `beat_id`
  - `planned_panel_id`
  - `planned_page_id`
- on-disk location and naming convention, recommended:
  - `layout_plan/layout_plan.json`
  - optional scene-local planner caches if needed later

Key decisions:

- keep semantic shape intent separate from renderer geometry
- store planner-derived decisions separately from user overrides
- include provenance metadata so downstream stages can detect stale projections

### 2. Pipeline and Stage Wiring Workstream

Introduce a planner stage and rewire downstream stages incrementally.

Target files:

- `novel_to_comic/src/novel_to_comic/cli.py`
- `novel_to_comic/src/novel_to_comic/state.py`
- `novel_to_comic/src/novel_to_comic/events.py`
- `novel_to_comic/src/novel_to_comic/stages/s3_screenplay.py`
- new planner stage file, recommended:
  - `novel_to_comic/src/novel_to_comic/stages/s4_layout_plan.py`
- existing:
  - `s4_panels.py`
  - `s5_prompts.py`
  - `s6_generate.py`
  - `s7_assemble.py`

Deliverables:

- new stage registration and stage ordering
- planner stage `run()` with `on_event`
- transition strategy for current stage names and CLI ergonomics
- state-machine support for the planner artifact lifecycle

Key decisions:

- whether to keep CLI name `panels` temporarily while changing its output, or add a new `layout-plan` stage and deprecate `panels`
- how stage invalidation flows when screenplay or planner overrides change

Recommendation:

- add a new explicit `layout-plan` stage first rather than mutating `panels` in place immediately
- keep `panels` as a compatibility stage only during migration, then remove it once prompts and generation no longer depend on it

### 3. Compose and API Workstream

Prepare the backend and frontend for split ownership between structure and presentation.

Target files:

- `novel_to_comic/src/novel_to_comic/server/routers/stages.py`
- `novel_to_comic/src/novel_to_comic/server/routers/pages.py`
- `novel_to_comic/src/novel_to_comic/server/routers/pipeline.py`
- `web/src/api/`
- `web/src/pages/rooms/ComposeRoom.tsx`
- `web/src/components/compose/`

Deliverables:

- read API for `layout plan`
- projection API status or metadata that tells Compose whether a page view is stale relative to the plan
- initial structural operation API shape, even if only read-only in early phases
- Compose state model separating:
  - structural plan data
  - projected page data

Key decisions:

- structural mutations should hit dedicated layout-plan endpoints, not reuse page JSON patch routes
- page patch routes remain presentation-only

### 4. Generation Compatibility Workstream

Make image reuse deterministic under planner-driven structure.

Target files:

- `novel_to_comic/src/novel_to_comic/models/prompt.py`
- `novel_to_comic/src/novel_to_comic/prompting.py`
- `novel_to_comic/src/novel_to_comic/stages/s5_prompts.py`
- `novel_to_comic/src/novel_to_comic/stages/s6_generate.py`
- image metadata storage location if separate from `ImagePrompt`

Deliverables:

- prompt and asset metadata keyed by `planned_panel_id`
- `generation_mode` support: `master` vs `exact`
- compatibility evaluation for reused assets
- explicit stale states exposed to Compose and Draw

## Phased Plan

## Phase 1: Introduce the Layout Plan Artifact

### Goal

Create the canonical planning artifact and IDs without breaking the current end-to-end loop.

### Scope

- add planner models
- add planner stage
- generate `layout_plan/layout_plan.json` from screenplay beats
- keep current `panels`, `prompts`, `generate`, and `assemble` working
- optionally derive `PanelBreakdown` compatibility data from planned panels if needed

### Backend Tasks

1. Add new planning models under `models/`.
2. Add deterministic ID helpers shared by planner and downstream stages.
3. Implement a new planner stage file that:
   - reads `screenplays/*.json`
   - emits `layout_plan/layout_plan.json`
   - runs a scene-local panelization pass first
   - runs a global pagination pass second
4. Update CLI and state registration to include the planner stage.
5. Add docs updates for stage contracts and model contracts.

### Compatibility Strategy

- Keep `s4_panels.py` functioning temporarily.
- Add a projection helper from `PlannedPanel` to legacy `PanelBreakdown` where needed.
- Avoid duplicating planning logic in both places; the legacy projection should be thin and mechanical.

### Verification

- `pipeline run screenplay`
- `pipeline run layout-plan`
- inspect `layout_plan/layout_plan.json`
- confirm deterministic IDs and page assignments are stable across repeated runs with unchanged inputs
- verify no downstream stage regressions when planner output exists but is not yet the sole input

### Exit Criteria

- planner artifact exists and is documented
- IDs are stable
- no current stage is blocked by planner introduction

## Phase 2: Move Prompts to Planned Panels

### Goal

Make Stage 5 read planned panels instead of legacy panel breakdowns.

### Scope

- update prompt models and prompt-building logic
- key prompts by `planned_panel_id`
- derive composition/framing from planner fields
- preserve `visual_anchor` rules and current prompt semantics where still valid

### Backend Tasks

1. Extend `ImagePrompt` with planner-linked identifiers and generation contract fields.
2. Refactor `build_image_prompt_spec()` to accept planned panels instead of `PanelBreakdown`.
3. Add prompt logic for:
   - `generation_mode`
   - shape/aspect preference
   - crop/framing flexibility
4. Decide on prompt file storage:
   - either keep scene-local directories with planned-panel names
   - or move to planner-keyed layout directories

### Verification

- prompt generation succeeds for a representative project
- prompt JSON records planner identifiers
- visual anchor text remains verbatim
- prompt output is stable when only presentation edits change

### Exit Criteria

- Stage 5 no longer depends on `panels/scene_NNN/panel_NNN.json`

## Phase 3: Move Generation to Planned Panels

### Goal

Make Stage 6 generate images against planner-owned panel contracts.

### Scope

- update Stage 6 input discovery and output bookkeeping
- store image asset metadata by `planned_panel_id`
- classify assets as compatible or stale when planner requirements change

### Backend Tasks

1. Refactor Stage 6 to read planner-keyed prompts.
2. Add asset contract metadata:
   - `planned_panel_id`
   - `generation_mode`
   - target shape/aspect class
   - framing constraints
3. Add compatibility evaluation utilities.
4. Update regen entry points to target planned panels rather than legacy scene/panel pairs.

### Verification

- single-panel regeneration works with planner IDs
- old assets can be marked compatible or stale after a simulated planner edit
- generation review UX still works for the migrated path

### Exit Criteria

- Stage 6 no longer fundamentally depends on legacy panel numbering as the canonical key

## Phase 4: Make Stage 7 a Pure Projection Layer

### Goal

Stop Stage 7 from inventing page structure. Make it project `PlannedPage` into `ComicPage`.

### Scope

- refactor assemble/build logic to read the layout plan
- keep `assembly/pages/page_NNN.json` as the canonical presentation editing surface
- maintain current export path

### Backend Tasks

1. Refactor `s7_assemble.py`:
   - remove naive `_group_into_pages()` ownership from the canonical path
   - read `PlannedPage`s and project them into `ComicPage`
2. Add projection helpers from planner fields to page JSON:
   - panel ordering
   - panel geometry
   - bubble/SFX defaults
3. Keep rendering and export behavior unchanged where possible.

### Verification

- `pipeline run assemble` builds pages from the layout plan
- `pipeline export` still respects page JSON presentation edits
- page count now matches planner decisions, not `max_panels_per_page` packing heuristics

### Exit Criteria

- Stage 7 page structure is planner-driven

## Phase 5: Expose the Layout Plan Through APIs

### Goal

Let the app read planner structure and understand structural versus presentation state.

### Scope

- add read endpoints for layout plan
- add projection freshness metadata
- keep mutation APIs read-only for structural edits initially if needed

### Backend Tasks

1. Add `GET /layout-plan` and related scene/page selectors.
2. Add planner/projection freshness indicators.
3. Ensure router responses include planner IDs used by prompts, generation, and projected pages.

### Frontend Tasks

1. Add client types for `LayoutPlan`, `PlannedPanel`, and `PlannedPage`.
2. Load planner data in Compose alongside page JSON.
3. Render planner-owned structure separately from page-owned presentation controls.

### Verification

- Compose can inspect planner structure and page projection together
- UI can show whether a panel/page is planner-stale or generation-stale

### Exit Criteria

- Compose is no longer structurally blind

## Phase 6: Add Structural Compose Overrides

### Goal

Let Compose write explicit structural overrides into the layout plan.

### Scope

- split/merge/promote/repaginate operations
- impact classification
- reprojection after structural edits
- no automatic regeneration by default

### Backend Tasks

1. Add structural mutation endpoints against the layout plan.
2. Implement override recording separate from planner-derived values.
3. Add impact classification:
   - `presentation_only`
   - `reproject_only`
   - `regeneration_recommended`
   - `regeneration_required`
4. Reproject Stage 7 page JSON after structural changes.

### Frontend Tasks

1. Add structural editing affordances in Compose.
2. Surface impact explanations before apply.
3. Show stale/compatible/redraw-needed states after apply.

### Verification

- structural edits persist in the layout plan
- page JSON is rebuilt from the plan after structural edits
- existing images are preserved by default and correctly classified

### Exit Criteria

- Compose structural edits no longer rely on page JSON as the structural source of truth

## Phase 7: Add Richer Geometry and Shape Realization

### Goal

Support dynamic and irregular planned shapes without collapsing semantics into renderer-specific hacks.

### Scope

- evolve semantic shape classes
- add concrete geometry realization
- teach the renderer and Compose preview to display richer panel geometry

### Tasks

1. Extend `PanelGeometry` representation.
2. Add geometry realization rules in Stage 7 projection and renderer code.
3. Add Compose preview support for new geometry.
4. Add compatibility rules for shape-sensitive generation cases.

### Verification

- irregular/tall/wide/bleed panels render consistently in projection and export
- generation compatibility logic handles shape-sensitive panels correctly

### Exit Criteria

- dynamic panel shapes are first-class in planning and rendering

## Recommended Sequencing

Recommended execution order:

1. Phase 1
2. Phase 2
3. Phase 4
4. Phase 5
5. Phase 3
6. Phase 6
7. Phase 7

Rationale:

- Phase 1 establishes the canonical artifact first.
- Phase 2 moves prompt semantics earlier without immediately forcing generation rewrites.
- Phase 4 makes Stage 7 planner-driven before structural Compose edits exist.
- Phase 5 gives the UI visibility into planner structure early.
- Phase 3 can then migrate generation with clearer IDs and UI needs in place.
- Phase 6 depends on planner APIs and projection ownership being real.
- Phase 7 should wait until the ownership model is stable.

If generation migration proves technically simpler earlier, swap Phases 3 and 4. The hard rule is that Phase 6 should not start before planner ownership and projection boundaries are implemented.

## Risks

- Carrying both `PanelBreakdown` and `PlannedPanel` too long will create dual-truth drift.
- Planner IDs must be stable enough for downstream caching and UI references, but also predictable under split/merge semantics.
- If Stage 7 remains structurally authoritative during migration, Compose will keep developing against the wrong source of truth.
- Shape-first semantics can outpace renderer capability; semantic shape intent must land before irregular geometry rendering.

## Verification Strategy

For each phase:

- add or update stage-level tests for artifact creation and parsing
- verify stage resumability with partial outputs on disk
- verify event emissions remain aligned with new logs and stage boundaries
- verify a representative project can still go from screenplay through export

Recommended targeted fixtures:

- a dialogue-heavy scene
- a reveal/hero-panel scene
- a scene-transition boundary case
- a case that should trigger `master` versus `exact` generation mode differences

## First Implementation Slice

The first concrete implementation slice should be:

1. add planner models
2. add `layout-plan` stage registration
3. implement `layout_plan/layout_plan.json` generation from screenplay beats
4. document stage and model contracts
5. add a read-only API endpoint for the new artifact

That slice establishes the new source-of-truth layer with minimal blast radius and gives the rest of the migration a stable contract to build against.
