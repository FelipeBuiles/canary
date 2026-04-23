# Layout Plan and Compose Redesign

**Date:** 2026-04-23
**Status:** Draft

## Overview

The current pipeline treats layout mostly as a Stage 7 concern. That works for simple pagination, but it breaks down when Compose changes panel count, page balance, or panel emphasis. A page-level layout change can imply upstream changes to panel structure, prompt framing, and generation requirements, yet there is no canonical artifact that owns those decisions.

This design introduces a new canonical planning layer between screenplay beats and prompt generation:

`story bible -> screenplay beats -> layout plan -> prompts -> generate -> compose/export`

The `layout plan` becomes the source of truth for comic structure. It owns beat-to-panel grouping, panel importance, panel shape intent, page assignment, and downstream regeneration impact. Compose edits this plan for structural changes, while `assembly/pages/page_NNN.json` remains the canonical Stage 7 editing surface for presentation concerns such as bubbles, SFX, styling, and final render adjustments.

## Problem Statement

| Issue | Current Behavior |
|-------|------------------|
| **Layout is too late** | Page layout is mostly chosen during assemble, after panel count and framing are already fixed |
| **Panel count has no safe owner** | A Compose layout change can imply split/merge/add/remove behavior, but no upstream artifact owns that structure |
| **Prompt framing is disconnected from page intent** | Stage 5 and Stage 6 know `shot_type` but not whether a panel is supposed to be wide, tall, splash, inset, or irregular |
| **Stage 7 is overloaded** | `assembly/pages/page_NNN.json` is both the editing surface and the only place where page structure is concretely visible |
| **Structural edits are not traceable** | There is no clean distinction between narrative/panel edits and presentation edits |
| **Image reuse is ad hoc** | The system lacks a policy for when an existing generated image is still compatible after layout changes |

## Goals

- Make panel count and page assignment explicit, canonical, and editable before rendering.
- Preserve a beat-first storytelling model while allowing balanced beat grouping for stronger comics pacing.
- Let screenplay express cinematic intent without forcing it to own final panelization.
- Support first-class dynamic panel shapes without locking the planner to one renderer's geometry model.
- Keep Compose exploratory and fast by preserving existing images by default and making regeneration explicit.
- Preserve Stage 7 page JSON as the canonical presentation editing surface without making it the structural source of truth.

## Non-Goals

- Freeform visual drag-and-drop geometry authoring as the canonical structural model.
- Automatic regeneration on every structural layout change.
- Legacy compatibility shims for old `PanelBreakdown`-driven behavior unless explicitly needed during migration.
- Solving final irregular panel rendering math in this design; this spec defines the semantic and pipeline contracts first.

## Proposed Architecture

Reshape the pipeline into:

`story bible -> screenplay beats -> layout plan -> prompts -> generate -> compose/export`

Responsibilities by stage:

- **Screenplay:** produce scene-contained narrative beats plus lightweight cinematic hints.
- **Layout planning:** convert beats into planned panels and planned pages.
- **Prompts:** build generation prompts from planned panels rather than legacy panel breakdowns.
- **Generate:** produce image assets against a planned framing contract.
- **Compose:** edit the layout plan for structural decisions and projected page JSON for presentation decisions.
- **Render/export:** project the current plan into page JSON/HTML/PNG/PDF/CBZ.

The critical boundary is:

- `layout plan` is canonical for comic structure.
- `assembly/pages/page_NNN.json` is canonical for Stage 7 presentation editing.

## Core Design Decisions

The design assumes the following product choices:

- **Fundamental unit:** beat-first. Screenplay emits beats; planning groups beats into panels.
- **Beat grouping policy:** balanced. Narrative clarity is primary, but beat grouping can split/fuse when visual rhythm gains are strong enough.
- **Scene boundaries:** scene-contained by default, with explicit cross-scene exceptions for transitions and special cases.
- **Importance ownership:** hybrid. Screenplay may emit intent hints; the planner may upgrade or downgrade them.
- **Shape model:** full shape-first. Dynamic and irregular panel shapes are a first-class planning concept.
- **Canonical planning artifact:** `layout plan`, not raw beats and not projected page patches.
- **Planning scope:** hybrid. Scene-local panelization followed by a lighter global pagination pass.
- **Generation strategy:** hybrid. Standard panels often use master compositions; hero/splash/irregular panels may require exact geometry generation.

## Data Model

### ScreenplayBeat

`ScreenplayBeat` remains the narrative-first input. It stays scene-scoped and should not become a page layout object.

Expected fields:

- `beat_id`
- `scene_id`
- `type`
- `content`
- `character_id` or participating characters where relevant
- optional `emphasis_hint`
- optional `shot_hint`
- optional `transition_significance`

Screenplay should express dramatic and cinematic intent, not exact panel count or final page layout.

### PlannedPanel

`PlannedPanel` becomes the canonical visual storytelling unit. It replaces the current role of `PanelBreakdown` as the thing downstream stages reason about.

Expected fields:

- stable `panel_id`
- `scene_id`
- `beat_ids[]`
- `importance` such as `standard`, `accent`, `hero`, `splash`, `inset`
- `shape_intent` such as `rect`, `tall`, `wide`, `panorama`, `bleed`, `irregular`
- `aspect_preference`
- `aspect_range`
- `crop_policy` or `framing_flex`
- `dialogue_load`
- `caption_load`
- `transition_in`
- `transition_out`
- `generation_mode` such as `master` or `exact`
- `image_fit_status`
- `regeneration_status`
- visual direction fields migrated from panel breakdown logic:
  - `shot_type`
  - `camera_angle`
  - `characters_present`
  - `character_actions`
  - `character_expressions`
  - `character_positions`
  - `background_description`
  - `lighting`
  - `mood`
  - `sfx`

### PlannedPage

`PlannedPage` is the canonical pagination unit in the plan.

Expected fields:

- stable `page_id`
- ordered `panel_ids[]`
- page-local panel geometry specs
- `scene_boundary_mode`
- `page_rhythm_role` such as `regular`, `intro`, `climax`, `transition`
- optional spread metadata
- exception markers for any cross-scene page

### PanelGeometry

Because the system needs shape-first planning, semantic shape intent should be kept separate from concrete renderer geometry.

Expected layers:

- **Semantic intent:** `wide hero`, `vertical inset`, `irregular accent`, `full bleed splash`
- **Concrete geometry:** polygon/path or normalized region, aspect box, bleed flags, z-order

The planner should decide the kind of panel the story wants. The renderer should realize that intent in a given theme/layout system.

### LayoutPlan

`LayoutPlan` is the top-level canonical structural artifact.

Expected contents:

- source screenplay version/hash
- ordered `planned_panels`
- ordered `planned_pages`
- planner metadata and provenance
- planner warnings or unresolved tensions
- user override sections
- regeneration impact metadata

## Stage Flow

### Stage 3: Screenplay

Screenplay remains narrative-first.

Outputs:

- scene-contained beat sequences
- optional cinematic hints
- optional emphasis signals
- transition significance

Screenplay does not choose final panel count or page layout.

### Stage 4: Layout Planning

This becomes the core planning stage and runs in two passes.

#### Pass 1: Scene-Local Panelization

Consumes beats scene by scene and creates `PlannedPanel`s.

Rules:

- default toward narrative clarity
- allow split/fuse when visual rhythm clearly improves readability or impact
- preserve scene boundaries by default
- assign importance, shape intent, framing flexibility, and generation mode

#### Pass 2: Global Pagination

Consumes planned panels and creates `PlannedPage`s.

Rules:

- keep pages scene-contained by default
- allow explicit cross-scene exceptions for transition pages
- place hero/splash/irregular panels intentionally
- balance dense versus sparse pages
- choose page rhythm patterns and spread opportunities

This keeps the pipeline resumable: narrow scene-local replans are possible, and global pagination can rerun as a lighter downstream pass.

### Stage 5: Prompts

Prompts read `PlannedPanel`, not `PanelBreakdown`.

Prompt behavior:

- if `generation_mode = master`, prompt for broader composition with safe margins and environment
- if `generation_mode = exact`, prompt for the exact framing/shape/aspect contract
- include planner framing intent without asking the model to render page text
- preserve `visual_anchor` text verbatim
- compute whether an existing asset is still compatible with the current panel contract

### Stage 6: Generate

Generation is keyed by `planned_panel_id`, not only `scene_id` plus panel number.

Generation behavior:

- first generation for a planned panel
- targeted regeneration for invalidated planned panels
- optional asset versioning when a layout change creates a new generation requirement

Each generated asset should retain compatibility metadata describing the contract it was generated for.

### Stage 7: Compose Projection and Render

Stage 7 should be treated as two concerns:

- **Projection:** materialize the current layout plan and chosen image assets into renderable `ComicPage` JSON.
- **Render/export:** build HTML and screenshots from projected pages, then export PDF/CBZ.

`assembly/pages/page_NNN.json` remains the canonical Stage 7 editing surface, but now for presentation and render concerns rather than structural truth.

## Compose Editing Model

Compose should expose two explicit editing surfaces in one room:

- **Structural surface:** edits the `layout plan`
- **Presentation surface:** edits projected `ComicPage` JSON

The system should not hide which layer the user is editing.

### Structural Operations

Structural operations are first-class and named:

- split panel
- merge adjacent panels
- promote to hero/splash/inset
- change shape intent
- move panel before or after another panel
- move panel to next or previous page
- repaginate selection or scene
- allow or disallow a cross-scene page break
- mark panel as exact-framing required
- revert planner override back to automatic

These operations should write user overrides into the `layout plan`, not mutate screenplay beats directly.

The plan should distinguish:

- planner-derived decisions
- user-authored overrides

That distinction supports behaviors like “replan this scene but preserve my manual hero panel overrides.”

### Presentation Operations

Presentation operations remain Stage 7 concerns:

- bubble placement
- bubble ordering
- SFX placement
- lettering style
- page theme/style vars
- final crop offsets and similar render-time adjustments

These update projected `ComicPage` JSON only.

## Regeneration and Compatibility Model

Regeneration should be explicit and panel-scoped, not automatic by default.

Each structural edit should receive an impact classification before it is applied:

- `presentation_only`
- `reproject_only`
- `regeneration_recommended`
- `regeneration_required`

### Safe to Keep Existing Image

Examples:

- move panel to another page
- reorder panels
- modest resize within crop tolerance
- theme or lettering changes
- small geometry adjustments that the current asset can satisfy

### Warn but Preserve Image

Examples:

- standard to wide conversion
- standard to tall conversion
- stronger emphasis on the same beat
- irregular shape that may clip important subjects
- increased dialogue/caption load that now competes for space

### Require Regeneration

Examples:

- split one planned panel into multiple panels
- merge multiple planned panels into one
- major shot/framing change
- changed beat grouping
- materially changed exact-framing geometry
- old image no longer satisfies subject-fit or composition-fit rules

After a structural change, Compose should:

- apply the structural override
- reproject pages
- mark affected panels as `compatible`, `stretched`, `cropped_risk`, or `needs_redraw`
- offer a targeted “regenerate affected panels” action

This keeps Compose fast while staying honest about stale assets.

## Image Asset Contract

The system should track more than “PNG exists.”

Each generated asset should record:

- source `planned_panel_id`
- generation mode `master` or `exact`
- target aspect/shape class
- framing constraints
- compatibility metadata used for fit evaluation

This enables deterministic answers to “does the current image still satisfy the panel contract after the layout change?”

## Migration Plan

### Phase 1: Introduce Layout Plan Alongside Current Panels

Add a planner-owned `layout plan` stage output generated from screenplay beats. Initially, some visual fields may still be derived from current panel logic.

At the end of this phase:

- `layout plan` exists on disk
- it has stable panel/page IDs
- Compose can inspect it
- Stage 7 still projects into `assembly/pages/page_NNN.json`

### Phase 2: Move Prompts and Generation to Planned Panels

Change Stage 5 and Stage 6 to read `PlannedPanel` instead of `PanelBreakdown`.

At the end of this phase:

- planned panels are canonical for structure
- generation keys off planned-panel IDs
- asset compatibility metadata starts being stored

### Phase 3: Make Stage 7 a Projection Layer

Refactor assemble so it reads `PlannedPage`s from the layout plan rather than grouping panels naively.

At the end of this phase:

- page structure comes from the planner
- `ComicPage` JSON is a projection
- Stage 7 no longer owns structural truth

### Phase 4: Add Structural Compose Edits

Allow Compose to write structural overrides into the layout plan.

Initial supported operations should be explicit and limited:

- split
- merge
- promote
- repaginate
- shape override
- page boundary override

### Phase 5: Add Richer Shape Realization

Once the planning layer is stable:

- deepen semantic shape classes
- add renderer-specific geometry realization
- evolve theme/layout systems to support irregular panels

Do not start with renderer geometry as the source of truth.

## Risks and Tradeoffs

- This is a meaningful pipeline rewrite, not a local Compose feature.
- A shape-first planner raises the cost of Stage 5 and Stage 6 contracts, but that cost is necessary to avoid rectangular-only assumptions calcifying upstream.
- There will be a temporary migration window where `PanelBreakdown` still exists for compatibility, but it should not remain an equal source of truth for long.
- The product must clearly communicate structural versus presentation edits or Compose will feel unpredictable.

## Success Criteria

The redesign is successful when:

- panel count and page assignment are owned by the `layout plan`
- prompts and generation read planned panels directly
- Compose distinguishes structural edits from presentation edits
- structural changes produce explicit downstream impact states
- existing images can be preserved, warned, or invalidated deterministically
- `assembly/pages/page_NNN.json` remains the canonical Stage 7 editing surface for presentation, not story structure

## Open Questions Resolved by This Design

- **Should Compose own panel count directly?** No. Compose edits the canonical `layout plan`, not late-stage page JSON.
- **Should images auto-regenerate on structural change?** No. Preserve by default, classify impact, and make regeneration explicit.
- **Should the pipeline stay panel-first?** No. The new design is beat-first with planned panels as the canonical comic unit.
- **Should dynamic shapes be first-class now?** Yes, but as semantic planning intent decoupled from renderer geometry.

## Recommended Next Step

Write an implementation plan for Phase 1 that introduces the `layout plan` artifact and IDs without breaking the current pipeline loop. That should include:

- the new planning models
- on-disk artifact format and location
- minimal stage wiring changes
- projection rules from `layout plan` to `ComicPage`
- a first Compose read-only integration path
