# PULP UI/UX Slice 4 Implementation Plan: Generate Panels Review Cockpit

Date: 2026-05-03

Parent plan:
`docs/superpowers/plans/2026-05-02-pulp-ui-ux-implementation-plan.md`

## Status

Ready for implementation. Slice 3 prompt approval is stable.

## Goal

Redesign the Draw room into a production cockpit where users can track
generation progress, filter panels by status, launch generation of pending
panels, and review or regenerate individual panels through a tabbed detail
modal — all without leaving the room.

The attached mockup is the primary UX reference. Decisions in this plan resolve
any gaps the mockup leaves open.

## Current State

- `DrawRoom.tsx` renders a flat grid of `PanelCard` components filtered only by
  scene. The primary filter bar is a horizontal scene tab strip.
- The right sidebar shows "SESSION STATS" (count table) and nothing else.
- `PanelCard.tsx` has a 7-state internal machine
  (`active|inking|failed|narrative|queued|regening|stale`). The label for
  `active` (done, not necessarily accepted) is hardcoded to `"ACCEPTED"`,
  which is wrong — a done-but-not-accepted panel shows "ACCEPTED".
- `PanelDetailModal.tsx` is a two-column layout with a fixed left image pane
  and a scrollable right area containing: version history, `PromptLineageCard`
  (editable prompt fields), an instruction textarea for NL-guided regen, an
  accept/unaccept bar in the footer, and a `GenerationDetailsModal` sub-modal.
  There are no tabs. All functionality is visible simultaneously.
- The credit low-balance warning is an inline banner inside the modal footer,
  not a `ConfirmDrawer`.
- `useStageEstimate(project, "draw")` already exists and returns the pending
  draw cost.
- `useProjectConfig` / `updateProjectConfig` PATCH endpoint already exists and
  supports `image_model`, `image_provider`, `quality_preset`.
- `useRegenEstimate` already returns per-panel credit cost.
- `useAcceptPanel`, `useUnacceptPanel`, `useRegenPanel`,
  `useRegenPanelWithInstruction`, `usePanelImageVersions`,
  `useRestorePanelImageVersion`, `useImageGenerationMeta` all exist.

## Decisions

### Panel States

Replace the 7-state internal enum with a 6-state display enum that maps
directly to user-facing labels and filter buckets:

| Display state | Condition | Filter bucket | Badge color |
|---|---|---|---|
| `pending` | Not yet generated (status ≠ done/failed, no regen active) | Pending | Amber |
| `generating` | Draw stage running OR regenMode = queued/running | Pending | Animated amber |
| `generated` | status=done, not accepted, version_count=1 (or absent) | Generated | Green |
| `regenerated` | status=done, not accepted, version_count>1 | Generated | Teal |
| `accepted` | accepted=true | Generated | Archive-sage |
| `failed` | status=failed | Failed | Hero-red |
| `stale` | status=stale | Pending | Gray |

The filter tabs mirror the mockup: **All**, **Generated**, **Pending**,
**Failed**. "Generated" bucket includes `generated`, `regenerated`, and
`accepted` states. "Pending" includes `pending`, `generating`, `stale`.

### New Panel Card Design

Replace the current `PanelCard` visual with the mockup layout:

- Top-left number badge (e.g. `01`).
- Scene/shot label line (e.g. `Shot 01 · Scene 001`) derived from
  `scene_id` and `panel_number`.
- Full-width image with a lazy-load placeholder.
- Panel title below image — use `background_description` from the storyboard
  panel (or the prompt's `setting` field as fallback). Keep it to one line,
  truncated.
- One-line description — use the first subject name + action from the prompt's
  `subjects` array, or `composition` if no subjects.
- Status badge: `GENERATED` / `PENDING` / `FAILED` / `ACCEPTED`.
- Three action icons below the description: **Preview** (opens detail modal),
  **Download** (direct image link), **More** (ellipsis → quick actions).

Cross-referencing storyboard data in the card requires `usePanelsForScene` per
scene, which is too expensive to load per card. Instead, pass the panel
title/description as a derived field from the parent `DrawRoom`, which already
has `promptSummaries`. Use prompt `setting` (first line) as the panel title and
`composition` as the description — these are available from `ImageStatus`-keyed
prompt data that `DrawRoom` already loads via `usePromptSummaries` and can
augment with `usePromptsForScene` per active scene.

**Simpler approach:** Use scene-level lazy loading. When the user is viewing a
scene filter, load prompts for that scene to populate title/description. When
`All` is selected, show scene+panel ID as the title and omit the description
line. This avoids N scene loads.

### Right Sidebar

Replace "SESSION STATS" with three sections matching the mockup:

1. **Panel Progress** — donut chart (Generated / Pending / Failed counts with
   colors). Use a simple SVG arc, not a chart library.
2. **Credits Estimate** — derived from `useStageEstimate(project, "draw")`:
   - `Generation cost (est.): N credits`
   - `Available credits: N credits` from `useCreditBalance`
   - `After generation: N credits` (balance minus estimate)
   - Green/amber/red inline status message (enough / tight / insufficient).
3. **Generation Options** — model selector using `useProjectConfig` +
   `updateProjectConfig`. Show only the models available from the project
   config. No `image_style_lock` toggle in v1 (no backend concept exists).
4. **Action buttons:**
   - `GENERATE ALL PENDING (N)` — calls `runPipeline({ project, stage: "draw",
     rerun: false })`. Disabled if no pending panels or stage is running. Gated
     with `ConfirmDrawer` from Slice 2 showing the draw estimate.
   - `RETRY FAILED` — calls `runPipeline({ project, stage: "draw", rerun: true
     })`. Disabled if no failed panels. Also gated with `ConfirmDrawer`.

### Filter + Search + Sort

**Status filter tabs** (mockup top bar): `ALL PANELS N`, `GENERATED N`,
`PENDING N`, `FAILED N`. Derived from `displayImages` counts. Replaces the
current scene tab strip as the primary filter.

**Scene filter**: Demote to a secondary dropdown or a `Filter` popover (mockup
shows a `FILTER` button). In v1, implement as a simple `<select>` adjacent to
the search bar.

**Search**: Filter `displayImages` client-side by `scene_id` or `panel_number`
string match. No backend search needed. The mockup shows a search input; wire
it to a local `searchQuery` state and filter `displayImages` before rendering.

**Sort**: `Scene order` (default, current behavior) only in v1. Defer other
sort modes. Render the dropdown as a UI element but keep it non-functional
beyond default, or implement `panel_number ASC` only.

**View toggle** (list/grid): Grid is the default and primary view. In v1,
implement both — grid is the 4-column layout from the mockup; list is a
compact row per panel (image thumb + title + status badge + actions). Store
preference in `localStorage`.

**Pagination**: The mockup shows "Show 8 per page" with page controls. Defer
pagination to after initial review — the current grid handles dozens of panels
without performance issues. Add a note that it is a nice-to-have if the panel
count exceeds ~50.

### Panel Detail Modal Redesign (Tabbed)

Restructure `PanelDetailModal` into 4 tabs. Remove `GenerationDetailsModal`
as a separate sub-modal — absorb it into the **Metadata** tab.

#### Tab: Review

Contents:
- Full image (left/primary area, same as current).
- Accept button (primary CTA, green archive-sage). Disabled if status ≠ done.
- "Undo Accept" appears only when already accepted.
- "Next Unaccepted →" button when available.
- Quick Re-Do button (bottom of this tab) — triggers `regenPanel`. Gates with
  `ConfirmDrawer` showing `regenEstimate` cost.
- Version strip (thumbnail row) if `version_count > 1`. "RESTORE vN" button
  when a non-current version is selected.

#### Tab: Edit

Contents:
- Natural-language instruction textarea (primary regeneration path). "Apply &
  Regen · Est. N credits" button — gates with `ConfirmDrawer`.
- `PromptLineageCard` in `edit` mode below the instruction box. Shows
  composition, setting, lighting, subjects. Editing here updates the local
  draft.
- If `hasChanges` (draft differs from saved prompt): "Generate · Est. N
  credits" button that saves draft then regens. Also gates with `ConfirmDrawer`.
- After a successful instructed regen, show the rewritten prompt in a
  collapsible "Rewritten Prompt" section at the top of this tab (sourced from
  `data.prompt` in the `useRegenPanelWithInstruction` success callback).

#### Tab: Prompt

Contents:
- Read-only structured view of the current saved prompt fields:
  style, composition, setting, lighting/mood, subjects, reference images.
- Full assembled `full_prompt` in a monospaced block (collapsed by default, same
  as Slice 3 `DirectRoom` pattern).
- If a rewritten prompt is available (post-regen), show a diff badge "Updated
  by last regen" with the new values highlighted.

#### Tab: History

Contents:
- Version thumbnail strip (moved from Review tab when `version_count > 1`).
- Per-version metadata: generated at timestamp (from `archived_at`), reason for
  archival.
- Restore button.
- If no history: "No previous versions" empty state.

#### Tab: Metadata

Contents:
- Absorb `GenerationDetailsModal` contents:
  - Model, steps, width × height, style template.
  - Full prompt sent to the model (`generationMeta.prompt`).
  - Error details if failed.
  - Recovery instructions if `recoverable`.
- Remove `GenerationDetailsModal` and the "DETAILS" button.

### Credit Confirmation

Replace the inline `pendingCreditAction` banner with `ConfirmDrawer`:
- Quick Re-Do → `ConfirmDrawer` with `regenEstimate` cost.
- Apply & Regen (instruction) → `ConfirmDrawer` with `regenEstimate` cost.
- Generate (from edited draft) → `ConfirmDrawer` with `regenEstimate` cost.
- Generate All Pending → `ConfirmDrawer` with `useStageEstimate("draw")` cost.
- Retry Failed → `ConfirmDrawer` with `useStageEstimate("draw")` cost.

All confirmations use the existing `ConfirmDrawer` from Slice 2.

### Rewritten Prompt Display

When `useRegenPanelWithInstruction` succeeds, `data.prompt` is the updated
`ImagePrompt`. Store it in a `lastRewrittenPrompt` state inside the modal.
Clear it when the panel selection changes. Display it in the Edit tab header
as a collapsible "Rewritten Prompt" block. The Prompt tab reflects the saved
data via the existing query invalidation (`queryClient.invalidateQueries`).

### Remove GenerationDetailsModal

The `GenerationDetailsModal` component is absorbed into the Metadata tab of
the redesigned modal. After the modal redesign is complete, delete
`web/src/components/ui/GenerationDetailsModal.tsx`.

### Naming

- Room `kicker`: `"DRAW"` → `"GENERATE PANELS"` (matches SideNav label from
  Slice 1).
- Room `title`: `"PANEL GALLERY"` → `"GENERATE PANELS"`.
- Room `lead`: update to match mockup: "Review and generate final illustrated
  panels for your story."

## Out Of Scope

- Pagination (defer; grid handles current counts fine).
- Sort modes beyond Scene order.
- Image style lock toggle (no backend concept).
- Bulk accept / bulk regenerate.
- Per-panel regen cost breakdown inside the grid card.
- Compose/Export stage changes.
- Any backend schema changes.

## Frontend Plan

### 1. Extract `getPanelDisplayState` helper

New file: `web/src/lib/panelState.ts`

```ts
export type PanelDisplayState =
  | "pending"
  | "generating"
  | "generated"
  | "regenerated"
  | "accepted"
  | "failed"
  | "stale";

export function getPanelDisplayState(
  img: ImageStatus,
  regenMode: "queued" | "running" | null,
  isDrawRunning: boolean,
): PanelDisplayState
```

Used by both `DrawRoom` (for filter counts) and `PanelCard` (for badge label
and color).

### 2. Update `PanelCard`

Target: `web/src/components/PanelCard.tsx`

Rewrite to match mockup card design:
- Number badge + scene/shot label.
- Full-width image via `LazyImage`.
- Panel title (from `title` prop, falls back to `Scene · Panel N`).
- Description line (from `description` prop, optional).
- Status badge using `getPanelDisplayState`.
- Action row: Preview icon, Download icon, More (`…`) icon.
- Pass `title` and `description` as optional props from parent.

Keep existing props stable where possible: `sceneId`, `panelNumber`, `status`,
`imageUrl`, `imageAvailable`, `accepted`, `regenMode`, `onPanelClick`.
Remove `onRegenerate` from the card — regeneration moves into the modal.

### 3. Redesign `DrawRoom`

Target: `web/src/pages/rooms/DrawRoom.tsx`

Changes:
- Update `kicker`, `title`, `lead`.
- Replace scene tab strip with status filter tabs.
- Add scene `<select>` dropdown (secondary filter).
- Add search `<input>` (client-side filter on scene_id + panel_number string).
- Compute `panelCounts` (generated, pending, failed) from `displayImages` using
  `getPanelDisplayState`.
- Add view toggle state (`"grid" | "list"`) persisted to `localStorage`.
- Replace "SESSION STATS" sidebar with the three new sections:
  - `PanelProgressDonut` (inline SVG component, ~40 lines).
  - `DrawCreditsEstimate` (uses `useStageEstimate` + `useCreditBalance`).
  - `GenerationOptionsPanel` (model selector from `useProjectConfig` +
    `updateProjectConfig`).
  - `GenerateAllPendingButton` + `RetryFailedButton` with `ConfirmDrawer`.
- Load prompts for active scene filter to supply `title`/`description` to
  `PanelCard`. When `All` is selected, omit `title`/`description` (show ID
  only).

### 4. Redesign `PanelDetailModal` with tabs

Target: `web/src/components/PanelDetailModal.tsx`

- Add `activeTab: "review" | "edit" | "prompt" | "history" | "metadata"` state.
  Default: `"review"`.
- Keep the existing two-column layout (image left, content right). The tab bar
  replaces the current un-separated scrollable right panel.
- Implement tab content components:
  `ReviewTabContent`, `EditTabContent`, `PromptTabContent`,
  `HistoryTabContent`, `MetadataTabContent` — local to the file.
- Move `footerMode` logic into `ReviewTabContent`. The modal footer becomes a
  thin nav strip only (prev/next panel arrows + close).
- Wire `ConfirmDrawer` for all regen actions (replacing `pendingCreditAction`
  banner).
- Add `lastRewrittenPrompt: ImagePrompt | null` state. Set on instructed regen
  success. Clear on panel change. Pass to `EditTabContent` and `PromptTabContent`.
- Remove `isDetailsOpen` / `GenerationDetailsModal` usage. Metadata is now a
  tab.

### 5. Delete `GenerationDetailsModal`

After step 4 is complete and `GenerationDetailsModal` has no remaining
imports, delete `web/src/components/ui/GenerationDetailsModal.tsx`.

### 6. Write `panelState.test.ts`

New file: `web/src/__tests__/panelState.test.ts`

Cover:
- `accepted=true` → `"accepted"` regardless of version count.
- `status=done`, not accepted, `version_count=1` → `"generated"`.
- `status=done`, not accepted, `version_count=3` → `"regenerated"`.
- `status=failed` → `"failed"`.
- `regenMode="running"` → `"generating"`.
- `status=pending`, draw stage running → `"generating"`.
- `status=stale` → `"stale"`.

## Files Likely To Change

- `web/src/lib/panelState.ts` (new)
- `web/src/__tests__/panelState.test.ts` (new)
- `web/src/components/PanelCard.tsx`
- `web/src/components/PanelDetailModal.tsx`
- `web/src/pages/rooms/DrawRoom.tsx`

## Files To Delete After Implementation

- `web/src/components/ui/GenerationDetailsModal.tsx`

## Files Unlikely To Change

- Backend: no changes.
- `web/src/api/queries.ts`: all needed hooks exist.
- `web/src/store/regen.ts`: no changes needed.
- `web/src/components/ui/ConfirmDrawer.tsx`: reused as-is from Slice 2.
- `web/src/components/PromptLineageCard.tsx`: reused inside `EditTabContent`.

## Suggested Implementation Order

1. Write `panelState.ts` and `panelState.test.ts`. Verify tests pass.
2. Redesign `PanelCard` to match mockup layout. Verify visually in dev server.
3. Update `DrawRoom` header, filter tabs, and search. Wire `getPanelDisplayState`
   for counts and card props.
4. Implement right sidebar sections (`PanelProgressDonut`,
   `DrawCreditsEstimate`, `GenerationOptionsPanel`, Generate/Retry CTAs with
   `ConfirmDrawer`).
5. Redesign `PanelDetailModal` with tabs:
   - Review tab first (accept, quick redo, version strip).
   - Edit tab (NL instruction → ConfirmDrawer → regen, PromptLineageCard).
   - Prompt tab (read-only structured view, collapsed assembled prompt).
   - History tab (version thumbnails, restore).
   - Metadata tab (absorb GenerationDetailsModal content).
6. Remove `GenerationDetailsModal` and its import from `DrawRoom`.
7. Run `npm test` and `npm run build`.
8. Manual verification against the mockup.

## Tests

### `panelState.test.ts`

All 7 display states covered with positive and negative cases as described
above.

No new UI component tests are needed in v1; the existing test suite covers
the query hooks and utility functions that the components depend on.

## Verification Steps

1. Run `cd web && npm test` — all tests pass.
2. Run `cd web && npm run build` — TypeScript clean.
3. Open a project at the `draw` stage:
   - Verify room title, kicker, and lead text are updated.
   - Verify filter tabs show correct counts (Generated/Pending/Failed).
   - Verify scene dropdown filters the grid correctly.
   - Verify search input filters by scene_id and panel_number.
   - Verify grid view matches mockup card design.
   - Verify list view shows compact rows.
4. Right sidebar:
   - Donut chart reflects live counts as panels generate.
   - Credits estimate section shows estimate, balance, and after-generation.
   - Model selector updates project config on change.
   - "Generate All Pending" opens ConfirmDrawer with draw estimate.
   - "Retry Failed" opens ConfirmDrawer. Both buttons disabled when no
     panels in the relevant state.
5. Panel detail modal:
   - Review tab: image, accept/undo, quick redo with ConfirmDrawer, next
     unaccepted navigation.
   - Edit tab: instruction regen with ConfirmDrawer; rewritten prompt appears
     after success; PromptLineageCard editable.
   - Prompt tab: structured fields read-only; assembled prompt collapsed.
   - History tab: version thumbnails visible when version_count > 1; restore
     works.
   - Metadata tab: model, steps, dimensions, full prompt, error details visible.
6. Verify SideNav CONTINUE button still works (no regression on draw stage
   approval path).

## Risks and Mitigations

### Risk: PanelCard title/description data is unavailable in "All" view

Mitigation: Show only `Scene_id · Panel NN` as the title when no scene filter
is active. Description line omitted. This avoids loading all scene prompt data
eagerly. Acceptable UX tradeoff documented in "Simpler approach" above.

### Risk: Donut chart adds a charting dependency

Mitigation: Use a minimal inline SVG arc calculation (~30 lines, no external
library). The three-segment donut is a fixed structure with computed stroke
offsets.

### Risk: Tabbed modal increases file size and complexity

Mitigation: Tab content components are defined locally in
`PanelDetailModal.tsx` as named functions (not separate files). The file will
grow but stays a single responsibility. If it exceeds ~600 lines, extract tab
files in a follow-up.

### Risk: ConfirmDrawer for every regen action feels repetitive

Mitigation: The Quick Re-Do cost is typically low (1–5 credits). If `regenCredits
<= 5`, consider skipping the drawer and going direct. Decide during
implementation based on real credit values from test projects.

### Risk: Absorbing GenerationDetailsModal into Metadata tab misses edge cases

Mitigation: The existing `GenerationDetailsModal` content is fully known (model
params, full prompt string, error chain). Copy the render logic into
`MetadataTabContent` verbatim first, then simplify. Do not delete the original
until the tab is visually verified.
