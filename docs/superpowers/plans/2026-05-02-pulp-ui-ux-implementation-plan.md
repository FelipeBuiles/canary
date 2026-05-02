# PULP UI/UX Implementation Plan

Date: 2026-05-02

Source review: `docs/pulp-ui-ux-to-do.md`

## Goal

Upgrade PULP's production workflow UI without changing backend pipeline
contracts prematurely. The site should keep its editorial production-desk
identity while making each step clearer about what the user is reviewing, what
can be changed, what happens downstream, and what credits will be spent.

## Key Decisions

- Implement frontend changes first.
- Keep backend stage keys and pipeline order unchanged for now.
- Remove the user-facing `Plan` and `Storyboard` routes.
- Add one user-facing `Shot Plan` route at `/project/:id/shot-plan`.
- Do not add redirects or compatibility handling for old `/plan` or
  `/storyboard` URLs.
- Represent `Shot Plan` as one navigation row backed by the existing `plan`
  and `storyboard` backend stages.
- Show a compact sub-status line for `Shot Plan`, such as
  `Layout complete · Board needs review`.
- Build `ShotPlanRoom` as a new room, then remove old route imports/usages.
- Default `Shot Plan` to `Board` when storyboard data exists; otherwise default
  to `Outline`.
- Make only `Board` editable in v1. Keep `Outline` and `Layout` review-only.
- Use a simple page rhythm list for the `Layout` tab in v1, not a visual page
  grid or drag/drop editor.
- Use planned comic flow, not story recap, as the organizing principle for the
  `Outline` tab.
- In Slice 1, include only the `Shot Plan` CTA estimate. Broader cost UI comes
  later.
- Approve the first `awaiting_review` `Shot Plan` sub-stage only. If both are
  awaiting review, handle `plan` first.
- Put composite `Shot Plan` action logic in a shared helper used by the rail and
  the room header.
- Generated panels start as `Needs review`; successful generation does not mean
  accepted.
- Regenerating or restoring a panel clears acceptance. The backend already has
  this behavior for regeneration and restore paths.
- Compose and Export warn about unaccepted panels but do not hard-block export.

## Slice 1: Stage Vocabulary + Shot Plan Route

### Intent

Replace the exposed `Plan`/`Storyboard` mental model with one user-facing
`Shot Plan` production step while leaving backend stages intact.

### Scope

- Add a frontend-only user-facing stage model separate from backend
  `STAGE_ORDER`.
- Remove `/project/:id/plan` and `/project/:id/storyboard` from app routes.
- Add `/project/:id/shot-plan`.
- Add `web/src/pages/rooms/ShotPlanRoom.tsx`.
- Remove `Plan` and `Storyboard` from the left rail.
- Show one `Shot Plan` rail row with sub-status derived from `plan` and
  `storyboard`.
- Rename visible stage labels:
  - `Styles` -> `Look & Feel`
  - `Direct` -> `Prompt Review`
  - `Draw` -> `Generate Panels`
  - `Compose` -> `Letter & Compose`
- Add a shared composite-stage helper for `Shot Plan` CTA decisions.
- Update tests that currently assume every route equals its backend stage key.

### Out Of Scope

- Backend stage consolidation.
- Legacy route redirects.
- Layout drag/drop editing.
- Global cost ledger.
- New backend cost APIs.
- Compose issue engine.
- Prompt warning engine.
- Panel modal redesign.

### Shot Plan Tabs

#### Outline

Purpose: Review planned comic flow before board-level panel review.

Data:

- Story bible scene titles for readability.
- Story bible location and character IDs/names.
- Layout plan scene/panel counts.
- Narration decisions from layout plan.
- Board availability from storyboard summaries.

Behavior:

- Review-only in v1.
- Organize by production flow: scenes, beats, planned panels, narration, cast,
  location.
- Do not expose story-bible editing here.

#### Board

Purpose: Review and edit each panel's intent before Prompt Review.

Data:

- Existing storyboard panel summaries and per-scene panel breakdowns.
- Existing `usePanelSummaries`, `usePanelsForScene`, and `useUpdatePanel`
  hooks.

Behavior:

- Editable in v1.
- Use existing storyboard update API.
- Keep edits field-level and conservative.
- Do not introduce natural-language patching in Slice 1.

#### Layout

Purpose: Review page rhythm and panel distribution.

Data:

- Layout plan pages and planned panels.

Behavior:

- Review-only in v1.
- Render a simple list by page:
  - Page number
  - Rhythm role
  - Panel count
  - Panel order
  - Importance labels
  - Shape intent
  - Scene IDs and panel numbers
- No page grid, visual geometry editor, or drag/drop ordering in Slice 1.

### Composite Shot Plan CTA

Create a small helper with a shape like:

```ts
type ShotPlanAction =
  | { kind: "run"; backendStage: "plan" | "storyboard"; estimateStage: "plan" | "storyboard"; label: string }
  | { kind: "approve"; backendStage: "plan" | "storyboard"; estimateStage?: "plan" | "storyboard"; label: string }
  | { kind: "rerun"; backendStage: "plan" | "storyboard"; estimateStage: "plan" | "storyboard"; label: string }
  | { kind: "none"; label: string };
```

Initial rules:

- If `plan` failed, rerun `plan`.
- If `plan` is pending, run `plan`.
- If `plan` is awaiting review, approve `plan` and then build `storyboard`.
- If `storyboard` failed, rerun `storyboard`.
- If `storyboard` is pending, run `storyboard`.
- If `storyboard` is awaiting review, approve `storyboard` and continue.
- If both are complete, no local Shot Plan action is needed.

Example labels:

- `Run Shot Plan · Est. N credits`
- `Approve Layout & Build Board`
- `Build Board · Est. N credits`
- `Approve Shot Plan & Continue`
- `Fix Shot Plan`

The helper should be used by:

- The left rail primary CTA.
- `ShotPlanRoom` header/local action.

### Files Likely To Change

- `web/src/types/api.ts`
- `web/src/App.tsx`
- `web/src/layout/SideNav.tsx`
- `web/src/layout/TopNav.tsx`
- `web/src/pages/NavigateToRoom.tsx`
- `web/src/pages/rooms/ShotPlanRoom.tsx`
- `web/src/pages/rooms/PlanRoom.tsx`
- `web/src/pages/rooms/StoryboardRoom.tsx`
- `web/src/__tests__/api.test.ts`

Delete `PlanRoom.tsx` and `StoryboardRoom.tsx` only after no imports remain.

### Success Criteria

- No visible `Plan` or `Storyboard` navigation remains.
- `/project/:id/shot-plan` is the only user-facing Shot Plan route.
- Old `/plan` and `/storyboard` routes are unsupported; no redirects are added.
- `Shot Plan` can display existing layout plan and storyboard data.
- `Board` remains editable through existing panel update APIs.
- `Outline` and `Layout` are review-only.
- Rail and room header use the same composite action logic.
- `Shot Plan` CTA estimates the backend sub-stage it will actually run.
- Frontend tests pass.

### Verification

- Run the frontend test suite.
- Run TypeScript checks.
- Manually inspect the project rail with projects in these states:
  - No `plan` output.
  - `plan` awaiting review.
  - `plan` complete and `storyboard` pending.
  - `storyboard` awaiting review.
  - Both complete.
  - Either sub-stage failed.
- Manually open `/project/:id/shot-plan` and verify tab default behavior with
  and without storyboard data.

## Slice 2: Cost Trust Foundation

### Intent

Make expensive production actions deliberate and understandable.

### Scope

- Add shared cost UI primitives for:
  - Estimate
  - Reserved
  - Actual
  - Returned
  - Cost confidence
- Standardize copy around credits only inside production flows.
- Replace ambiguous language like `credit hold` and negative hold values.
- Show contextual estimates beside expensive actions.

### Dependencies

- Slice 1 should land first so composite `Shot Plan` cost behavior is stable.

### Success Criteria

- Expensive actions show cost before running.
- Confirmation drawers explain reserved vs final credits.
- The UI does not mix dollars into production actions.

## Slice 3: Prompt Review

### Intent

Replace raw-prompt-first review with structured prompt review and clear
generation approval.

### Scope

- Rename visible `Direct` UI to `Prompt Review`.
- Keep backend `direct` key unchanged.
- Show structured prompt parts before raw prompt.
- Collapse raw prompt by default.
- Add v1 warning detection:
  - Missing visible character reference.
  - Empty or thin composition/setting.
  - Text/dialogue leaking into image prompt.
  - Missing active style or style reference.
  - Missing or inconsistent image dimensions/quality.
  - Cheap structured-vs-raw mismatch checks only if reliable.
- Change approval CTA based on warnings.

### Success Criteria

- User can understand what will be generated without reading raw prompt text.
- `Approve Prompts & Run Generate Panels · Est. N credits` appears when safe.
- Warnings require review but can be overridden in a confirmation drawer.

## Slice 4: Generate Panels Review Cockpit

### Intent

Make generated panel review, acceptance, regeneration, and version history clear.

### Scope

- Rename visible `Draw` UI to `Generate Panels`.
- Make panel states explicit:
  - Needs review
  - Accepted
  - Failed
  - Generating
  - Regenerated
- Add useful filters:
  - All
  - Accepted
  - Needs review
  - Failed
  - Regenerated
- Redesign panel detail modal around tabs:
  - Review
  - Edit
  - Prompt
  - History
  - Metadata
- Primary regeneration path is natural-language instruction.
- Use cost confirmation before regeneration.
- Generate immediately in v1; do not add pre-generation prompt patch preview.
- Show rewritten prompt after regeneration starts/completes.

### Dependencies

- Slice 2 cost primitives.
- Existing regeneration and acceptance APIs.

### Success Criteria

- Successful generated panels require explicit acceptance.
- Regeneration clears acceptance.
- Version history allows restore, and restored versions still require acceptance.
- Users can regenerate with natural-language instructions and a clear cost
  estimate.

## Slice 5: Compose Issues

### Intent

Give users a production QA mode before export.

### Scope

- Add `issues` as a Compose edit sub-mode beside `canvas` and `script`.
- Build a reusable issue engine from page JSON and image acceptance state.
- Initial issue checks:
  - Unaccepted panel.
  - Missing narration/dialogue where expected.
  - Bubble outside safe area.
  - Obvious text overflow.
  - Low contrast where detectable.
  - Missing image.
- Link each issue to the relevant page/panel/object.

### Dependencies

- Slice 4 panel acceptance semantics.

### Success Criteria

- Compose surfaces fixable issues before export.
- Issues are warnings, not hard blockers.
- The issue engine can be reused by Export.

## Slice 6: Export Checkpoint

### Intent

Make Export feel like a final production checkpoint.

### Scope

- Reuse the Compose issue engine in Export.
- Show page/spread preview.
- Show export settings and checks.
- Provide actions:
  - Review issues
  - Export anyway
  - Export PDF
  - Export CBZ

### Dependencies

- Slice 5 issue engine.

### Success Criteria

- Export warns about unresolved production issues.
- Export remains possible with explicit override.

## Slice 7: Production Cost Ledger

### Intent

Turn raw credit transactions into a readable production ledger.

### Scope

- Group credit rows by user-facing action where possible.
- Show:
  - Action
  - Stage
  - Estimate
  - Reserved
  - Actual
  - Returned
  - Status
- Add per-project and account-level views if backend data supports it.

### Dependencies

- Slice 2 cost semantics.
- Stable action/job identifiers from generation and stage execution.

### Risk

Current billing UI receives transaction rows, not action summaries. This slice
may require a backend aggregation endpoint or richer ledger metadata.

## Open Questions Deferred

- Whether backend `plan` and `storyboard` should ever be collapsed.
- Whether layout editing should eventually support drag/drop.
- Whether natural-language edits should preview structured prompt patches before
  spending credits.
- Whether cost ledger grouping can be reliable from existing metadata or needs
  schema changes.

## Planning Gates For Later Slices

Write detailed implementation plans for later slices only when their dependency
conditions are met. This keeps the roadmap clear without locking in assumptions
before the frontend navigation model changes.

### Slice 2: Cost Trust Foundation

Plan after Slice 1 lands and the shared UI stage model, route model, and
composite CTA helper location are stable.

Detailed plan should decide:

- Shared component/API shape for estimate, reserved, actual, and returned
  credits.
- Which existing confirmation drawers should be generalized.
- Whether any backend estimate response needs additional metadata.
- How to phrase cost confidence without exposing provider accounting internals.

### Slice 3: Prompt Review

Plan after Slice 2 establishes cost display and confirmation patterns.

Detailed plan should decide:

- Prompt warning data model and where warning detection lives.
- Structured prompt review layout.
- Override flow for warning-gated generation.
- How Prompt Review's approval CTA uses shared cost primitives.

### Slice 4: Generate Panels Review Cockpit

Plan after Slice 2 cost primitives are available and Slice 3 establishes prompt
warning/approval patterns.

Detailed plan should decide:

- Panel state naming and filter behavior.
- Panel modal tab structure.
- Natural-language regeneration UX using existing `regen-instructed` behavior.
- How rewritten prompts are displayed after regeneration.
- How accepted/regenerated/versioned state is represented in the UI.

### Slices 5 and 6: Compose Issues + Export Checkpoint

Plan together after Slice 4 makes panel acceptance and regeneration state clear
in the UI.

Detailed plan should decide:

- Reusable issue engine shape.
- Initial checks and their severity levels.
- How issues deep-link to Compose pages, panels, bubbles, and SFX.
- Export checkpoint layout and override behavior.
- Which checks can be client-only and which require backend support.

### Slice 7: Production Cost Ledger

Plan after Slice 2 lands and after inspecting whether current ledger metadata can
be grouped into user-facing production actions.

Detailed plan should decide:

- Whether the current transaction rows are sufficient.
- Whether a backend aggregation endpoint is needed.
- How to group reservations, debits, releases, and generation jobs into one
  action row.
- Whether the ledger appears per project, globally on the credits page, or both.
