# PULP UI/UX Slice 2 Implementation Plan: Cost Trust Foundation

Date: 2026-05-03

Parent plan:
`docs/superpowers/plans/2026-05-02-pulp-ui-ux-implementation-plan.md`

## Status

Ready for implementation.

## Goal

Make pre-action production costs explicit and trustworthy. Every expensive
production action should distinguish projected final cost from temporary credit
reservation, and zero-cost deterministic steps should say so without adding
noise to primary CTAs.

## Decisions

- Slice 2 includes backend and frontend changes.
- Do not keep compatibility shims for the old `credits` estimate response key.
- `estimate_credits` means unbuffered projected final cost.
- `reserved_credits` means buffered temporary hold.
- Stage estimate responses always include `reserved_credits: number`.
- Zero-cost reserving stages return `reserved_credits: 0`.
- Non-reserving actions, such as panel regeneration in the current system,
  return `reserved_credits: null`.
- Slice 2 is pre-action cost trust only.
- Do not add final/actual/returned cost displays in Slice 2.
- Do not add project-level active reserved aggregation in Slice 2.
- Do not build the production ledger in Slice 2.
- Keep `ConfirmDrawer` and `RerunDrawer`, but make both render shared cost
  components.
- Put cost UI under `web/src/components/cost/`, not generic `ui/`.
- Do not show `Est. 0 credits` in CTA labels.
- For zero-cost confirmation details, show `No credit hold needed for this step.`
- `storyboard`, `direct`, and `compose` should return explicit zero-cost
  low-variance estimates.

## Out Of Scope

- Prompt Review warning/approval redesign.
- Generate Panels modal redesign beyond clearer regeneration cost language.
- Actual/returned cost calculations after completion.
- Ledger grouping.
- Active reserved credit totals.
- Adding credit reservations for panel regeneration.
- Dollars inside production flows.

## Backend Plan

### 1. Add Explicit Estimate Types

Target file:

- `novel_to_comic/src/novel_to_comic/server/credits.py`

Add a small typed structure or plain dict helper for estimate results. Suggested
shape:

```py
CostConfidence = Literal["low_variance", "usually_within_estimate", "variable"]

class CreditEstimate(TypedDict):
    estimate_credits: int
    reserved_credits: int | None
    reservation_multiplier: float
    confidence: CostConfidence
```

If avoiding `TypedDict`, keep the return shape centralized through helper
functions so endpoint responses remain consistent.

### 2. Split Base Estimate From Reservation

Current behavior:

- `estimate_stage_credit_reservation()` returns one buffered number.
- The `/estimate` endpoint returns that number as `credits`.

New behavior:

- Add `estimate_stage_credit_cost(...) -> int`.
- Keep or rewrite `estimate_stage_credit_reservation(...)` to call the base
  estimate and apply `reservation_buffer()`.
- Add `estimate_stage_credit_breakdown(...)` returning:
  - `estimate_credits`
  - `reserved_credits`
  - `reservation_multiplier`
  - `confidence`

Rules:

- `estimate_credits = provider_usd_to_credits(estimated_provider_cost_usd)`.
- If the provider estimate is zero, `estimate_credits = 0`.
- For reserving stage actions, `reserved_credits = ceil(estimate_credits *
  reservation_buffer())` when estimate is positive, otherwise `0`.
- Reservation code should continue reserving `reserved_credits`.

### 3. Add Missing Explicit Stage Estimates

Current `estimate_stage_provider_cost_usd()` handles only some stages. Update it
so every backend stage has an explicit answer:

- `extract`: existing text estimate.
- `style`: existing text estimate.
- `cast`: existing image estimate.
- `adapt`: existing text estimate.
- `plan`: existing text estimate.
- `storyboard`: `0.0`, deterministic layout-plan projection.
- `direct`: `0.0`, deterministic prompt-spec assembly.
- `draw`: existing image estimate.
- `compose`: `0.0`, deterministic compose/export render in normal flow.

Do not invent paid estimates for deterministic stages.

### 4. Add Confidence Mapping

Initial confidence rules:

- `extract`: `usually_within_estimate`
- `style`: `usually_within_estimate`
- `cast`: `variable`
- `adapt`: `usually_within_estimate`
- `plan`: `usually_within_estimate`
- `storyboard`: `low_variance`
- `direct`: `low_variance`
- `draw`: `variable`
- `compose`: `low_variance`
- panel regeneration: `variable`

Keep this mapping centralized, for example:

```py
def stage_cost_confidence(stage: str) -> CostConfidence:
    ...
```

### 5. Update Estimate Endpoints

Target file:

- `novel_to_comic/src/novel_to_comic/server/routers/pipeline.py`

Update `GET /estimate` response from:

```json
{ "stage": "draw", "credits": 112 }
```

to:

```json
{
  "stage": "draw",
  "estimate_credits": 112,
  "reserved_credits": 140,
  "reservation_multiplier": 1.25,
  "confidence": "variable"
}
```

Update `GET /regen-estimate` response from:

```json
{ "scene_id": "scene_001", "panel_number": 4, "credits": 8 }
```

to:

```json
{
  "scene_id": "scene_001",
  "panel_number": 4,
  "estimate_credits": 8,
  "reserved_credits": null,
  "reservation_multiplier": 1.25,
  "confidence": "variable"
}
```

No `credits` key should remain.

### 6. Update Impact Estimates

Target file:

- `novel_to_comic/src/novel_to_comic/server/routers/stages.py`

Narration impact currently builds `stage_credits` from
`estimate_stage_credit_reservation()`. Update this to use explicit estimate
fields.

Preferred shape:

```json
{
  "estimated_credits": 112,
  "reserved_credits": 140,
  "stage_credits": {
    "direct": {
      "estimate_credits": 0,
      "reserved_credits": 0,
      "confidence": "low_variance"
    },
    "draw": {
      "estimate_credits": 112,
      "reserved_credits": 140,
      "confidence": "variable"
    }
  }
}
```

Use explicit estimate and reservation fields for impact responses as part of
this slice. Do not preserve the old ambiguous `stage_credits` semantics.

## Frontend Plan

### 1. Update API Types

Target files:

- `web/src/types/api.ts`
- `web/src/api/pipeline.ts`
- `web/src/api/queries.ts`

Add:

```ts
export type CostConfidence =
  | "low_variance"
  | "usually_within_estimate"
  | "variable";

export interface CostEstimate {
  estimate_credits: number;
  reserved_credits: number | null;
  reservation_multiplier: number;
  confidence: CostConfidence;
}

export interface StageCostEstimate extends CostEstimate {
  stage: string;
  reserved_credits: number;
}

export interface RegenCostEstimate extends CostEstimate {
  scene_id: string;
  panel_number: number;
  reserved_credits: null;
}
```

Update hooks and call sites to use explicit fields. Remove `.credits` usage.

### 2. Add Cost Components

Add directory:

- `web/src/components/cost/`

Recommended files:

- `CostBreakdown.tsx`
- `CostInline.tsx`
- `cost-copy.ts`
- `index.ts`

`CostBreakdown` responsibilities:

- Show `Estimated` when `estimate_credits > 0`.
- Show `Reserved` when `reserved_credits` is a positive number.
- Show `No credit hold needed for this step.` when both estimate and reserved
  are zero.
- Show estimate-only copy when `reserved_credits === null`.
- Show confidence helper copy.

Confidence copy:

- `low_variance`: `Low variance`
- `usually_within_estimate`: `Usually within estimate`
- `variable`: `Variable`

Suggested helper text:

- Stage with reservation:
  `Reserved credits are held before the action starts. Unused reserved credits are released after the action finishes, resets, or fails.`
- Estimate-only action:
  `This action is charged from reported model usage after it finishes. No separate credit hold is made before it starts.`
- Zero-cost action:
  `No credit hold needed for this step.`

`CostInline` responsibilities:

- Produce compact CTA fragments like `Est. 112 credits`.
- Return `null` for zero-cost estimates.
- Never output `Est. 0 credits`.

### 3. Update ConfirmDrawer

Target file:

- `web/src/components/ui/ConfirmDrawer.tsx`

Replace `estimatedCredits?: number` with an explicit estimate prop:

```ts
cost?: CostEstimate;
```

Render `CostBreakdown` when provided.

Update body copy:

- Remove `credit hold` phrasing.
- Use `Estimated` and `Reserved`.
- For zero-cost stages, allow the drawer to explain that no credit hold is
  needed.

### 4. Update RerunDrawer And RerunStageAction

Target files:

- `web/src/components/ui/RerunDrawer.tsx`
- `web/src/components/ui/RerunStageAction.tsx`
- `web/src/lib/rerunImpact.ts`
- `web/src/__tests__/rerunImpact.test.ts`

Changes:

- Replace `estimatedCredits: string` and `creditsAreEstimated` with
  `cost?: StageCostEstimate`.
- Keep fallback copy for loading state, but do not keep ambiguous static
  `credits` strings in `RERUN_IMPACT`.
- `RERUN_IMPACT` should own downstream impact only.
- Rerun drawer renders `CostBreakdown`.
- Downstream stage labels should use user-facing UI labels where possible, not
  backend raw names.

### 5. Update SideNav CTA Confirmation

Target file:

- `web/src/layout/SideNav.tsx`

Changes:

- Use `nextStageEstimate.estimate_credits` for CTA inline copy.
- Use `nextStageEstimate.reserved_credits` for confirmation drawer reserved
  display.
- Replace rail footer `~N credit hold` with clearer copy:
  - Positive estimate: `Est. N credits`
  - Positive reservation: `Reserves up to N`
  - Zero estimate: no inline cost row.
- Pass full estimate object into `ConfirmDrawer`.

### 6. Update ShotPlanRoom Action Label

Target file:

- `web/src/pages/rooms/ShotPlanRoom.tsx`

Change:

- Use `CostInline` with `estimate_credits`.
- Do not append cost text for zero-cost actions like `Build Board`.
- Keep the action label readable:
  - `Run Shot Plan · Est. N credits`
  - `Build Board`
  - `Approve Layout & Build Board`

### 7. Update Panel Detail Regeneration Footer

Target file:

- `web/src/components/PanelDetailModal.tsx`

Changes:

- Use `regenEstimate.estimate_credits`.
- Since `reserved_credits === null`, show estimate-only language.
- Replace bare `8 ◆` style labels with clearer text where space allows:
  - `Est. 8 credits`
  - `Apply & Regenerate · Est. 8 credits`
- Low-credit check should compare balance to `estimate_credits`.
- Do not imply a reserved hold for panel regeneration.

Keep the full panel modal redesign for Slice 4.

### 8. Update Credits Page Copy

Target file:

- `web/src/pages/CreditsPage.tsx`

Changes:

- Keep dollars in billing/account purchase context.
- Update explanatory production copy:
  - Estimated credits are projected before action start.
  - Reserved credits are temporary holds for stage runs.
  - Final charges are settled from reported model usage.
  - Ledger grouping is coming later; raw history remains for now.

Do not build the production ledger in Slice 2.

## Tests

### Backend Tests

Add focused tests, likely in:

- `novel_to_comic/tests/test_credit_estimates.py`

Cases:

- Stage estimate helper returns `estimate_credits`, `reserved_credits`,
  `reservation_multiplier`, and `confidence`.
- `reserved_credits >= estimate_credits` when `estimate_credits > 0`.
- `storyboard`, `direct`, and `compose` return explicit zero estimates and
  `low_variance`.
- Regen estimate response has `reserved_credits is None`.
- Old `credits` key is absent from endpoint responses.
- Reservation helper still reserves the buffered amount, not the base estimate.

### Frontend Tests

Add or update tests for:

- `CostInline` returns no text for zero-cost estimates.
- `CostBreakdown` renders estimated/reserved labels for reserving actions.
- `CostBreakdown` renders estimate-only copy for `reserved_credits === null`.
- `RERUN_IMPACT` no longer requires `credits` strings.
- Existing Shot Plan action tests still pass with the new estimate shape.

Likely files:

- `web/src/__tests__/cost.test.tsx`
- `web/src/__tests__/rerunImpact.test.ts`
- `web/src/__tests__/shotPlan.test.ts`

## Verification Commands

Backend:

```sh
uv run pytest novel_to_comic/tests/test_credit_estimates.py novel_to_comic/tests/test_usage.py
```

Frontend:

```sh
cd web
npm test
npm run build
```

Manual verification:

- A paid stage confirmation shows both `Estimated` and `Reserved`.
- A deterministic stage such as `Build Board` does not show `Est. 0 credits`
  on the CTA.
- A deterministic stage drawer says no credit hold is needed.
- A panel regeneration action shows estimate-only copy and does not mention a
  reservation.
- Credits page copy matches the estimate/reserved/final vocabulary.

## Suggested Implementation Order

1. Add backend estimate breakdown helpers and confidence mapping.
2. Update estimate endpoints and backend tests.
3. Update frontend API types and hooks.
4. Add `components/cost` primitives and tests.
5. Update `ConfirmDrawer`.
6. Update `RerunDrawer` and `RerunStageAction`.
7. Update `SideNav` and `ShotPlanRoom`.
8. Update `PanelDetailModal` estimate-only regeneration labels.
9. Update Credits page copy.
10. Run backend/frontend tests and build.

## Risks And Mitigations

### Risk: Estimate Fields Get Semantically Mixed Again

Mitigation:

- Use explicit field names everywhere.
- Remove `credits` from the API contract.
- Add tests that assert `credits` is absent.

### Risk: Deterministic Stages Add UI Noise

Mitigation:

- `CostInline` returns no label for zero-cost estimates.
- Confirmation drawers show a short no-hold explanation only when useful.

### Risk: Panel Regeneration Looks Reserved When It Is Not

Mitigation:

- Return `reserved_credits: null`.
- Cost copy treats `null` as estimate-only.
- Do not use `Reserved` copy for regen until backend reservations exist.

### Risk: Slice 2 Drifts Into Ledger Work

Mitigation:

- No actual/returned display.
- No active reserved totals.
- No action grouping.
- Credits history remains raw transaction history with clearer explanatory copy.
