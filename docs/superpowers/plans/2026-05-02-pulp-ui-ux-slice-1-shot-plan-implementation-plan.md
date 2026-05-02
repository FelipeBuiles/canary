# PULP UI/UX Slice 1 Implementation Plan: Stage Vocabulary + Shot Plan Route

Date: 2026-05-02

Parent plan:
`docs/superpowers/plans/2026-05-02-pulp-ui-ux-implementation-plan.md`

## Status

Ready for implementation.

## Goal

Replace the user-facing `Plan` and `Storyboard` split with one `Shot Plan`
workflow entry while keeping backend pipeline stages unchanged. This slice
should make the navigation and room model match the product language without
introducing backend stage migration, legacy route compatibility, or layout
editing.

## Non-Negotiable Decisions

- Frontend first.
- Backend stage keys stay as `plan` and `storyboard`.
- Remove `/project/:id/plan` and `/project/:id/storyboard` from app routes.
- Do not add redirects for old route paths.
- Add `/project/:id/shot-plan`.
- Add a new `ShotPlanRoom` instead of mutating `PlanRoom` and
  `StoryboardRoom` in place.
- Delete old room files only after imports are removed.
- `Shot Plan` shows as one rail row with a compact sub-status line.
- `Board` is editable in v1.
- `Outline` and `Layout` are review-only in v1.
- `Layout` is a simple page rhythm list, not a visual grid.
- Slice 1 includes only the `Shot Plan` CTA estimate, not the broader cost
  trust system.

## Success Criteria

- The left rail has no visible `Plan` or `Storyboard` rows.
- The left rail has one visible `Shot Plan` row.
- `/project/:id/shot-plan` renders the new combined room.
- `/project/:id/plan` and `/project/:id/storyboard` are unsupported routes.
- `ShotPlanRoom` shows existing layout plan and storyboard data.
- `Board` edits continue to use the existing panel update API.
- `Outline` and `Layout` do not allow edits.
- Rail primary CTA and room header CTA use the same composite action helper.
- `Shot Plan` CTA estimates the backend sub-stage it will actually run.
- Existing backend API contracts are unchanged.
- Frontend tests and type checks pass.

## Implementation Steps

### 1. Add User-Facing Stage Metadata

Create a frontend UI stage model that is separate from backend `STAGE_ORDER`.

Recommended file:

- `web/src/lib/uiStages.ts`

Suggested types:

```ts
import type { StageName, ProjectStatus } from "../types/api";

export type UiStageKey =
  | "extract"
  | "style"
  | "cast"
  | "adapt"
  | "shot-plan"
  | "direct"
  | "draw"
  | "compose";

export type UiStage =
  | { key: "style"; route: "styles"; label: string; backendStages: [] }
  | { key: "shot-plan"; route: "shot-plan"; label: string; backendStages: ["plan", "storyboard"] }
  | { key: Exclude<UiStageKey, "style" | "shot-plan">; route: string; label: string; backendStages: [StageName] };
```

Initial labels:

- `Extract`
- `Look & Feel`
- `Cast & Places`
- `Script`
- `Shot Plan`
- `Prompt Review`
- `Generate Panels`
- `Letter & Compose`

Important distinction:

- `STAGE_ORDER` remains backend pipeline order.
- The new UI stage list drives navigation, labels, and default room routing.

### 2. Add Composite Shot Plan Helper

Create a shared helper for status, CTA, and estimate decisions.

Recommended file:

- `web/src/lib/shotPlan.ts`

Suggested API:

```ts
import type { ProjectStatus, StageInfo } from "../types/api";

export type ShotPlanSubStatus = {
  layoutLabel: string;
  boardLabel: string;
  detail: string;
  status: "pending" | "running" | "awaiting_review" | "complete" | "failed";
  failedCount: number;
  itemsDone: number;
  itemsTotal: number;
};

export type ShotPlanAction =
  | {
      kind: "run" | "rerun";
      backendStage: "plan" | "storyboard";
      estimateStage: "plan" | "storyboard";
      label: string;
    }
  | {
      kind: "approve";
      backendStage: "plan" | "storyboard";
      estimateStage?: "plan" | "storyboard";
      label: string;
      runAfterApprove?: boolean;
    }
  | { kind: "none"; label: string };

export function getShotPlanSubStatus(status: ProjectStatus | undefined): ShotPlanSubStatus;
export function getShotPlanAction(status: ProjectStatus | undefined): ShotPlanAction;
```

Action rules:

- If `plan.status === "failed"`, return rerun `plan` with `Fix Shot Plan`.
- If `plan.status` is missing or `pending`, return run `plan` with
  `Run Shot Plan`.
- If `plan.status === "running"`, return none/running label.
- If `plan.status === "awaiting_review"`, return approve `plan` with
  `Approve Layout & Build Board` and `runAfterApprove: true`.
- If `storyboard.status === "failed"`, return rerun `storyboard` with
  `Fix Board`.
- If `storyboard.status` is missing or `pending`, return run `storyboard` with
  `Build Board`.
- If `storyboard.status === "running"`, return none/running label.
- If `storyboard.status === "awaiting_review"`, return approve `storyboard`
  with `Approve Shot Plan & Continue`.
- If both are complete, return none with `Shot Plan Complete`.

Composite status rules:

- Failed if either sub-stage failed or has failed items.
- Running if either sub-stage is running.
- Awaiting review if either sub-stage is awaiting review.
- Complete only if both sub-stages are complete.
- Pending otherwise.

Sub-status detail examples:

- `Layout pending · Board locked`
- `Layout needs review · Board locked`
- `Layout complete · Board pending`
- `Layout complete · Board needs review`
- `Layout complete · Board complete`

### 3. Update Routes

Modify:

- `web/src/App.tsx`

Changes:

- Remove imports for `PlanRoom` and `StoryboardRoom`.
- Add import for `ShotPlanRoom`.
- Remove route entries:
  - `path="plan"`
  - `path="storyboard"`
- Add:
  - `path="shot-plan" element={<ShotPlanRoom />}`

Do not add fallback routes or redirects for `plan` or `storyboard`.

### 4. Update Default Project Room Navigation

Modify:

- `web/src/pages/NavigateToRoom.tsx`

Current behavior maps backend stage to `STAGE_ROUTES[stage]`. Replace that with
a backend-stage-to-user-route mapping.

Rules:

- If style selection is needed, route to `styles`.
- If active backend stage is `plan` or `storyboard`, route to `shot-plan`.
- If active backend stage is any other stage, route to its corresponding user
  route:
  - `extract` -> `extract`
  - `cast` -> `cast`
  - `adapt` -> `adapt`
  - `direct` -> `direct`
  - `draw` -> `draw`
  - `compose` -> `compose`

The backend stage priority remains:

1. Running
2. Awaiting review
3. Failed
4. Pending
5. Last stage

### 5. Update Left Rail

Modify:

- `web/src/layout/SideNav.tsx`

Main changes:

- Build rail rows from the new UI stage list instead of rendering every backend
  `STAGE_ORDER` entry.
- Insert `Look & Feel` after `Extract`.
- Replace separate `plan` and `storyboard` rows with one `Shot Plan` row.
- Use `getShotPlanSubStatus()` for the `Shot Plan` row.
- Use `getShotPlanAction()` for primary CTA behavior when `Shot Plan` is the
  next active production target.
- Continue using backend status data for all non-composite stages.

CTA behavior:

- If `Shot Plan` action is `run`, call `runPipeline` with that backend stage.
- If `Shot Plan` action is `rerun`, call `runPipeline` with that backend stage
  and `rerun: true`.
- If `Shot Plan` action is `approve`, call `approveStage` for that backend
  stage. If `runAfterApprove` is true, run pipeline after approval.
- Use `useStageEstimate(projectId, action.estimateStage)` when the current CTA
  target is a costed Shot Plan sub-stage.

Implementation note:

- Avoid duplicating Shot Plan action branching directly in the component. The
  component should ask the helper what action to perform.

### 6. Add ShotPlanRoom

Add:

- `web/src/pages/rooms/ShotPlanRoom.tsx`

Use existing hooks:

- `useLayoutPlan`
- `useProjectStatus`
- `useStoryBible`
- `usePanelSummaries`
- `usePanelsForScene`
- `useUpdatePanel`
- `useStageEstimate`
- `useRunPipeline`
- `useApproveStage`

Use existing UI primitives where practical:

- `RoomShell`
- `RoomHeader`
- `SceneSidebar`
- `StagePlaceholder`
- `StateBlock`
- `EditableText`

Tab behavior:

- URL param: `view=outline|board|layout`.
- If no `view` param:
  - Default to `board` when storyboard summaries exist.
  - Default to `outline` when only layout plan data exists.
- Invalid `view` values should fall back internally to the default; no route
  redirects are needed.

#### Outline Tab

Render by planned comic flow:

- Scene title from story bible.
- Location from story bible.
- Characters from story bible via existing character-name helpers.
- Planned panel count from layout plan.
- Narration decisions from layout plan.
- Board status from storyboard summaries.

Review-only.

#### Board Tab

Render storyboard panel cards:

- Scene sidebar from storyboard summaries.
- Per-scene panel breakdowns from existing API.
- Field-level editing through `useUpdatePanel`.

Reuse the useful parts of `StoryboardRoom` but keep the component local first.
Extract shared child components only if duplication becomes meaningful.

Editable fields should match existing `StoryboardRoom` behavior. Do not add
new natural-language edit flows in this slice.

#### Layout Tab

Render layout plan pages as a simple list:

- Page number.
- Rhythm role.
- Panel count.
- Ordered panel list.
- For each panel:
  - Scene ID.
  - Panel number.
  - Importance.
  - Shape intent.
  - Shot type when available.

Review-only.

### 7. Update Top Navigation If Needed

Modify if it currently renders backend stages directly:

- `web/src/layout/TopNav.tsx`

Expected change:

- Use the new user-facing stage list.
- Show `Shot Plan`, not `Plan` and `Storyboard`.
- Keep route highlighting based on user route.

### 8. Remove Old Room Wiring

After `ShotPlanRoom` is compiled and routed:

- Remove unused imports.
- Delete `web/src/pages/rooms/PlanRoom.tsx` if no imports remain.
- Delete `web/src/pages/rooms/StoryboardRoom.tsx` if no imports remain.

Before deleting, use:

```sh
rg "PlanRoom|StoryboardRoom" web/src
```

### 9. Update Tests

Modify:

- `web/src/__tests__/api.test.ts`

Current tests assume:

- `STAGE_ORDER` has exactly 8 backend stages.
- Every route equals the stage name.
- `ROUTE_TO_STAGE` has exactly 8 entries.

New test direction:

- Keep tests proving backend `STAGE_ORDER` is unchanged.
- Add tests for UI stage route mapping.
- Assert `plan` and `storyboard` both map to user route `shot-plan`.
- Assert UI stage list contains one `shot-plan` item and no `plan` or
  `storyboard` UI items.
- Assert display names use new product vocabulary.

Possible additional test file:

- `web/src/__tests__/shotPlan.test.ts`

Test cases:

- `plan` pending -> run `plan`, label `Run Shot Plan`.
- `plan` awaiting review -> approve `plan`, run after approve.
- `plan` complete and `storyboard` pending -> run `storyboard`, label
  `Build Board`.
- `storyboard` awaiting review -> approve `storyboard`.
- either sub-stage failed -> rerun failed sub-stage.
- both complete -> no action.

### 10. Verification Commands

Run from `web/`:

```sh
npm test
npm run build
```

If the repo has a dedicated typecheck script, run it as well. If not, the Vite
build should catch TypeScript compilation failures.

Manual verification:

- Start the web app.
- Open a project with no plan output and confirm `Shot Plan` is visible.
- Confirm the primary CTA targets `plan`.
- Open a project where `plan` is complete and `storyboard` is pending; confirm
  the CTA targets `storyboard`.
- Open a project with storyboard data; confirm `Shot Plan` defaults to `Board`.
- Open a project with layout plan data but no storyboard data; confirm it
  defaults to `Outline`.
- Confirm no visible `Plan` or `Storyboard` nav items remain.
- Manually entering `/project/:id/plan` or `/project/:id/storyboard` should not
  render old rooms.

## Suggested Implementation Order

1. Add `uiStages` model and tests.
2. Add `shotPlan` helper and tests.
3. Add `ShotPlanRoom` with tabs and read-only `Outline`/`Layout`.
4. Add editable `Board` using existing storyboard APIs.
5. Update `App.tsx` routes.
6. Update `NavigateToRoom`.
7. Update `SideNav`.
8. Update `TopNav` if needed.
9. Remove old room imports and files.
10. Run tests/build and manually inspect.

## Risks And Mitigations

### Risk: Backend Stage Order Leaks Into UI Again

Mitigation:

- Keep `STAGE_ORDER` as backend-only.
- Use `uiStages` for visible navigation.
- Add tests that fail if `plan` or `storyboard` reappear as UI stage keys.

### Risk: Composite CTA Logic Diverges Between Rail And Room

Mitigation:

- Put all branching in `getShotPlanAction()`.
- Rail and room only execute the returned action.

### Risk: Shot Plan Hides Too Much Backend Truth

Mitigation:

- Show sub-status detail on the rail and in the room header.
- Use user-facing sub-labels `Layout` and `Board`, not backend names.

### Risk: Slice 1 Becomes A Redesign Of Plan/Storyboard Internals

Mitigation:

- Board editing should reuse existing `StoryboardRoom` behavior.
- Outline and Layout are review-only.
- No drag/drop, prompt warnings, issue engine, or global cost work in this
  slice.

