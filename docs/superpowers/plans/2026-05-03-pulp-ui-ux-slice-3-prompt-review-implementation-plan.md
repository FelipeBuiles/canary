# PULP UI/UX Slice 3 Implementation Plan: Prompt Review

Date: 2026-05-03

Parent plan:
`docs/superpowers/plans/2026-05-02-pulp-ui-ux-implementation-plan.md`

## Status

Ready for implementation. Slice 2 cost primitives are stable.

## Goal

Replace raw-prompt-first review with structured prompt review and a
clear, cost-aware generation approval. Users should be able to
understand what will be generated, spot problems, and commit to running
Generate Panels — all without reading the raw assembled prompt.

## Current State

- The `direct` stage room is called `DirectRoom.tsx`. The UI label
  "Prompt Review" was already applied in Slice 1 via `UI_STAGES`.
- The room shows structured fields (composition, setting, lighting,
  subjects, style) alongside the raw `full_prompt` — both always
  visible, with `full_prompt` prominently displayed.
- No approval action exists in the room. Approval is only reachable
  from the SideNav CONTINUE button.
- No warning detection exists anywhere in the codebase.
- `direct` is a zero-cost stage. Running `draw` (Generate Panels)
  after approval has a variable cost with a credit reservation.

## Decisions

- Warning detection lives entirely on the frontend in
  `web/src/lib/promptWarnings.ts`. No backend changes for warnings.
- Warn at the panel level. Surface an aggregate count in the room
  header and per-panel badges in the scene/panel tabs.
- Gate the primary approval CTA on warnings: if any warnings exist,
  the CTA changes to a warning-first label and clicks open a
  `WarningOverrideDrawer` before proceeding.
- Collapse `full_prompt` by default. It is still accessible; just not
  the first thing a user sees.
- The approval action in `DirectRoom` mirrors the `ShotPlanRoom`
  pattern: approve `direct` then run `draw` in sequence.
- The `ConfirmDrawer` for approval shows the `draw` stage cost using
  Slice 2 `CostBreakdown`. The `direct` step itself is zero-cost and
  does not need a separate confirmation.
- `WarningOverrideDrawer` is a new drawer component, not a reuse of
  `ConfirmDrawer`. It lists all warnings with per-panel context and
  has a single override confirmation button.
- Do not redesign the panel detail modal in this slice (that is Slice 4).
- Do not add natural-language prompt editing in this slice.
- Keep all existing inline field editing (composition, setting,
  lighting) working as before.

## Out Of Scope

- Panel detail modal redesign.
- Natural-language prompt patching.
- Per-panel regen from Prompt Review.
- Prompt warning server-side validation.
- Changes to how `draw` stage runs or estimates.

## Warning Detection

### File

`web/src/lib/promptWarnings.ts`

### Types

```ts
export type PromptWarningCode =
  | "missing_character_ref"
  | "thin_composition"
  | "thin_setting"
  | "text_in_prompt"
  | "missing_style"
  | "inconsistent_dimensions";

export interface PromptWarning {
  code: PromptWarningCode;
  label: string;
  detail: string;
  scene_id: string;
  panel_number: number;
}
```

Add these to `web/src/types/api.ts` so they can be imported across the
app.

### Detection Rules

Implement `detectPromptWarnings(prompt: ImagePrompt): PromptWarning[]`:

| Code | Condition | Label | Detail |
|------|-----------|-------|--------|
| `missing_character_ref` | `subjects` has ≥1 entry with a non-null `character_id` AND `reference_image_paths` is empty | Missing character reference | No reference image is attached. The model will invent the character's appearance. |
| `thin_composition` | `composition` is null, empty, or under 20 characters | Thin composition | The composition description is very short. Consider expanding it. |
| `thin_setting` | `setting` is null, empty, or under 15 characters | Thin setting | The setting description is very short. The background may be vague. |
| `text_in_prompt` | `full_prompt` contains `"`, `"`, `"` quote characters, or `composition`/`setting` contains sequences that look like spoken dialogue (e.g., `said`, `asked`, `replied` followed by a quote) | Dialogue text in prompt | Dialogue or speech text was found in the image prompt. This often causes unwanted text to appear in the generated image. |
| `missing_style` | `style` is null or empty AND `reference_image_paths` is empty | No style or reference | Neither a style template nor a reference image is attached. Generated art direction will vary. |
| `inconsistent_dimensions` | `width` or `height` is 0, null, or undefined, OR `steps` is 0 | Missing generation parameters | Width, height, or step count is unset. Generation may fail or use defaults. |

The mismatch check between structured fields and `full_prompt`
(mentioned in the parent plan) is deferred: it requires reliable
heuristics that are not ready in v1.

### Aggregate Helper

```ts
export function detectAllWarnings(
  prompts: ImagePrompt[],
): PromptWarning[]
```

Returns the flattened warnings across all prompts. Used by the room
header and the override drawer.

### Warning Severity

All warnings in v1 are the same severity: they require acknowledgment
but do not hard-block approval.

## Frontend Plan

### 1. Add Warning Types to `api.ts`

Add `PromptWarningCode` and `PromptWarning` to
`web/src/types/api.ts`.

### 2. Add `promptWarnings.ts`

Create `web/src/lib/promptWarnings.ts` with `detectPromptWarnings` and
`detectAllWarnings` as described above.

### 3. Collapse Raw Prompt by Default

Target: `web/src/pages/rooms/DirectRoom.tsx`

The `ASSEMBLED PROMPT` section currently renders unconditionally.
Wrap it in a collapsible `<details>` or a toggle with an explicit
"Show assembled prompt" label. Default state: collapsed.

Keep the section editable when expanded. No behavior change other than
default visibility.

### 4. Add Warning Badges to Panel Tabs

Target: `web/src/pages/rooms/DirectRoom.tsx`

In the `PanelTabStrip`, each tab already has a panel number label.
After computing per-panel warnings using `detectPromptWarnings`, show
a small orange warning badge on tabs that have at least one warning.

The badge should use a visually distinct but compact style consistent
with the existing `items_failed` badge pattern in other rooms.

### 5. Add Warning Summary to Room Header

Target: `web/src/pages/rooms/DirectRoom.tsx`

Below the stage title in the header, show a compact line when
aggregate warnings exist:

```
⚠ N prompts have warnings — review before approving
```

Use `text-warn-orange` styling. Hide this line when no warnings exist.

### 6. Add Approval Action to DirectRoom

Add a `DirectApproveAction` component (or inline the logic in
`DirectRoom`), following the `ShotPlanActionButton` pattern from
`ShotPlanRoom.tsx`.

State needed:
- `useProjectStatus(project)` for stage status
- `useStageEstimate(project, "draw", open)` for draw stage cost
- `useApproveStage()` + `useRunPipeline()` for the action

Logic:

```ts
type DirectAction =
  | { kind: "approve_and_run"; label: string }
  | { kind: "waiting" }
  | { kind: "none" };
```

- If `direct` is `awaiting_review`: `{ kind: "approve_and_run" }`.
- Otherwise: `{ kind: "none" }` or `{ kind: "waiting" }` based on
  running state.

CTA label rules (in priority order):
1. If warnings exist: `Review N Warnings Before Approving`
2. If `draw` estimate > 0: `Approve Prompts & Run Generate Panels · Est. N credits`
3. Otherwise: `Approve Prompts & Run Generate Panels`

On click:

1. If warnings exist → open `WarningOverrideDrawer`.
2. If no warnings → open `ConfirmDrawer` with `draw` stage
   `CostEstimate` prop.

After confirmation (either path):
1. Call `approveStage({ project, stage: "direct" })`.
2. On success, call `runPipeline({ project, stage: "draw" })`.
3. Connect to pipeline event stream.

### 7. Add ConfirmDrawer for Approval (No Warnings Path)

Reuse `ConfirmDrawer` from Slice 2 with:

```ts
cost={drawStageEstimate}  // StageCostEstimate from useStageEstimate
title="Run Generate Panels?"
body="Approving prompts is free. Generating panels will reserve credits
      for the draw stage. Unused reserved credits are released after
      the stage completes."
confirmLabel="Approve & Run Generate Panels"
```

The drawer correctly shows `CostBreakdown` for the draw stage, which
has `reserved_credits > 0` and `confidence: "variable"`.

### 8. Add `WarningOverrideDrawer`

New file: `web/src/components/ui/WarningOverrideDrawer.tsx`

Props:

```ts
interface WarningOverrideDrawerProps {
  open: boolean;
  warnings: PromptWarning[];
  cost?: StageCostEstimate;  // draw stage estimate
  onConfirm: () => void;
  onClose: () => void;
  busy?: boolean;
}
```

Layout:
- Header: `Review Prompt Warnings`
- Orange top border (same as `RerunDrawer`).
- Warning list: grouped by scene/panel. Each item shows the `label`
  and `detail`. Use the warn-orange color for warning icons.
- Cost section: render `CostBreakdown` with `draw` stage estimate
  (reuses Slice 2 component).
- Footer buttons: `Cancel` + `Approve Anyway` (destructive style).

Copy for the override explanation:
```
These warnings may cause generation issues. You can continue, but
consider fixing them first to get the best results.
```

### 9. Add Warning Badges in SideNav `direct` Row

Target: `web/src/layout/SideNav.tsx`

The SideNav `direct` row currently shows prompt count as detail.
When warnings exist, additionally show a count of warned prompts as a
small badge, e.g.:

```
42 prompts · 3 with warnings
```

This requires loading prompt data in the SideNav when `direct` is the
active or nearby stage. The existing `usePromptSummaries` hook is
already gated on `directReady`. However, running warning detection
in SideNav requires loading all prompt data for all scenes, which is
expensive.

**Decision:** Show the warned-prompt count in SideNav only when the
user is already in the `direct` route (i.e., `DirectRoom` has loaded
the prompts and can share the aggregate via a lightweight store or
context). Do not add a new global prompt load in SideNav.

Implementation approach: add a small `usePromptWarningStore` (Zustand
slice or simple atom) that `DirectRoom` writes to when it computes
warnings, and SideNav reads from. Alternatively, skip the SideNav
badge in Slice 3 and revisit in Slice 4 when panel state is more
prominent. **Defer SideNav warning badge to after initial review — it
is a nice-to-have.**

### Files Likely To Change

- `web/src/types/api.ts`
- `web/src/lib/promptWarnings.ts` (new)
- `web/src/pages/rooms/DirectRoom.tsx`
- `web/src/components/ui/WarningOverrideDrawer.tsx` (new)
- `web/src/__tests__/promptWarnings.test.ts` (new)

### Files Unlikely To Change

- Backend: no changes for v1 warnings.
- `web/src/components/ui/ConfirmDrawer.tsx`: already updated in Slice 2.
- `web/src/layout/SideNav.tsx`: SideNav already handles `direct`
  approval via the CONTINUE button. Local approval in `DirectRoom`
  does not conflict with it.

## Tests

### `web/src/__tests__/promptWarnings.test.ts`

Cover all six warning codes with:

- Positive cases: prompt that triggers the warning.
- Negative cases: prompt that should not trigger.
- Edge cases: empty `subjects`, null fields, zero-length strings.

Cover `detectAllWarnings`:

- Returns correct flattened list for a mixed set of prompts.
- Returns empty array for a clean set.
- Deduplicated per panel (one `thin_composition` per panel, not per
  invocation).

## Verification Steps

1. Run frontend tests: `cd web && npm test`.
2. Run TypeScript check: `cd web && npm run build`.
3. Manually open a project at `direct` awaiting review:
   - Confirm raw prompt is collapsed by default.
   - Expand raw prompt and verify it remains editable.
   - Confirm structured fields (composition, setting, subjects) are
     still shown and editable.
4. Manually verify warnings:
   - Use a prompt with no `reference_image_paths` and confirm
     `missing_character_ref` badge appears on the panel tab.
   - Edit `composition` to be empty and confirm `thin_composition`
     warning appears.
   - Confirm no warnings for a clean prompt.
5. With no warnings: click approval CTA → confirm drawer opens with
   `draw` stage cost breakdown → confirm → verify `direct` is approved
   and `draw` starts running.
6. With warnings: click CTA → `WarningOverrideDrawer` opens listing
   warnings → click Approve Anyway → verify same sequence as step 5.
7. Verify SideNav CONTINUE button still works as before (no
   regression).

## Suggested Implementation Order

1. Add `PromptWarning`/`PromptWarningCode` types to `api.ts`.
2. Write `promptWarnings.ts` with all six detection rules.
3. Write `promptWarnings.test.ts` and verify all tests pass.
4. Collapse `full_prompt` by default in `DirectRoom`.
5. Add per-panel warning computation and panel tab badges.
6. Add room header warning summary line.
7. Add `DirectApproveAction` with `ConfirmDrawer` (no-warning path).
8. Write `WarningOverrideDrawer`.
9. Wire `WarningOverrideDrawer` into `DirectApproveAction` (warning
   path).
10. Run tests and build.

## Risks and Mitigations

### Risk: Warning Detection Produces Too Many False Positives

Mitigation:

- Thresholds for "thin" copy (`thin_composition` < 20 chars,
  `thin_setting` < 15 chars) are conservative. Adjust after manual
  review of real project data.
- The `text_in_prompt` check uses explicit quote-character matching
  rather than heuristics; err on the side of caution.
- Warnings never block approval; they only change the CTA label and
  add a confirmation step.

### Risk: Approval + Run Sequence Is Not Atomic

Mitigation:

- `approveStage` succeeds → `runPipeline` starts draw.
- If `runPipeline` fails after approval, the stage is approved and
  `draw` is pending. The user can use the SideNav CONTINUE button to
  re-trigger draw. This is the same behavior as ShotPlanRoom.
- No special error recovery needed in Slice 3.

### Risk: Drawer Shows Wrong Cost (Direct vs Draw)

Mitigation:

- `ConfirmDrawer` and `WarningOverrideDrawer` both receive the `draw`
  estimate explicitly — not the `direct` estimate (which is always
  zero).
- `useStageEstimate(project, "draw", open)` is called with the gate
  condition `open` so it only fetches when the drawer is about to
  show.
- `direct` zero-cost is not shown in the approval CTA (per Slice 2
  rule: do not show `Est. 0 credits`).

### Risk: Slice 3 Drifts Into Panel Modal Redesign

Mitigation:

- Warning display is limited to the panel tab badge and room header
  summary.
- No per-panel warning detail panel in Slice 3; per-panel detail modal
  redesign is Slice 4.
