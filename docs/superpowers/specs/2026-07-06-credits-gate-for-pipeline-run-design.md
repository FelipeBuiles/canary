# Credits Gate for Pipeline Run — Design

**Date:** 2026-07-06
**Scope:** `novel_to_comic/src/novel_to_comic/state.py`,
`novel_to_comic/src/novel_to_comic/server/routers/pipeline.py`,
`novel_to_comic/src/novel_to_comic/server/routers/projects.py`,
`web/src/types/api.ts`,
`web/src/api/queries.ts`,
`web/src/hooks/useNeedsCredits.ts` (new),
`web/src/components/composites/CreditsGate.tsx` (new),
`web/src/lib/creditsPurchase.ts` (new),
`web/src/components/composites/StagePlaceholder.tsx`,
`web/src/components/InsufficientCreditsDialog.tsx`.

**Status:** Design approved; implementation pending.

---

## 1. Summary

A brand-new user starts with **0 credits** (no free-credit provisioning on
signup; credits only enter the ledger via Stripe purchase). When such a user
creates a project, the UI misleads them:

1. `Library.handleCreate` navigates to the `extract` room and immediately calls
   `handleRun(id, "extract")`.
2. `useRunPipeline` **optimistically** marks `extract` as `"running"` in the
   query cache *before* the network responds.
3. `StoryBibleRoom` paints `StageRunning` — animated badge, progress bar —
   **looking like work is happening**.
4. The `POST /run` returns **HTTP 402** (pre-flight credit check,
   `pipeline.py:521-525`).
5. The optimistic state rolls back to `"pending"`, so the room now shows
   **"WAITING FOR PIPELINE"** (`StagePlaceholder.tsx:148`), and the
   `InsufficientCreditsDialog` pops.

If the user dismisses the dialog — or reloads the page — they are left looking
at "WAITING FOR PIPELINE" with no hint that credits are the blocker. Worse, on
reload the frontend **cannot tell** a credit failure from any other failure:
the structured `error_code: "insufficient_credits"` lives only on the
in-memory SSE `stage_fail` event and is never persisted or returned by
`GET /status`.

This design makes the credit requirement obvious at every moment and pushes
the user toward purchase.

---

## 2. Approach — hybrid

Three mechanisms cover three distinct moments:

| Moment | Trigger | Mechanism |
|---|---|---|
| **1. New user, 0 credits, before any run** | Creates project, lands in room | Client-side heuristic (balance vs. stage estimate) renders the gate panel; optimistic "running" flash is suppressed |
| **2. Just failed on credits (this session)** | `POST /run` → 402, or SSE `stage_fail` | Existing `InsufficientCreditsDialog` opens (unchanged); the gate panel renders behind it so dismissal no longer dumps the user into confusion |
| **3. Reloaded after a credit failure** | `GET /status` returns `failed` stage | Persisted `error_code: "insufficient_credits"` on `StageState` drives the panel |

The persisted reason is authoritative and survives reloads; the heuristic
catches the pre-run new-user case the persisted reason cannot (no failure has
happened yet). Suppressing the optimistic cache write removes the misleading
"running" flash.

---

## 3. Backend — persist the credit-failure reason

Purely additive. No migration; no new endpoint.

### 3.1 `StageState` — `state.py:47-63`

Add four optional fields:

```python
class StageState(BaseModel):
    # ...existing fields...
    error: Optional[str] = None
    # NEW
    error_code: Optional[str] = None
    balance_credits: Optional[int] = None
    required_credits: Optional[int] = None
    shortfall_credits: Optional[int] = None
```

All `Optional[...] = None`, so existing `state.json` files deserialize
unchanged. Per AGENTS.md, breaking JSON/model changes are acceptable and no
legacy shim is added.

### 3.2 `fail_stage` — `state.py:177-183`

Extend to accept an optional detail payload, mirroring the SSE event shape
already built in `pipeline.py:247-252`:

```python
def fail_stage(state, stage, error, *, detail=None):
    s = state.stages[stage]
    s.status = FAILED
    s.finished_at = datetime.now(timezone.utc).isoformat()
    s.error = error
    if detail and detail.get("error") == "insufficient_credits":
        s.error_code = "insufficient_credits"
        s.balance_credits = detail.get("balance_credits")
        s.required_credits = detail.get("required_credits")
        s.shortfall_credits = detail.get("shortfall_credits")
    else:
        # Clear any stale credit code from a prior failure on the same stage.
        s.error_code = None
        s.balance_credits = None
        s.required_credits = None
        s.shortfall_credits = None
```

The `else` branch is required: a stage can fail on credits, be topped up,
be re-run, then fail for a *different* reason. Clearing on every non-credit
`fail_stage` guarantees no stale `insufficient_credits` code lingers.

### 3.3 `_run_stage_with_credits` — `pipeline.py:238-253`

One-line change: pass `detail=denied.detail` so persisted state matches the
SSE event:

```python
except CreditReservationDenied as denied:
    fail_stage(state, stage, denied.message, detail=denied.detail)
    save_state(state, project_dir)
    # ...existing SSE event emission unchanged...
```

The SSE event construction below this line is already correct; no change.

### 3.4 `_stage_payload` — `projects.py:161-201`

Surface the four new fields:

```python
payload = {
    # ...existing fields...
    "error": error,
    # NEW
    "error_code": s.error_code,
    "balance_credits": s.balance_credits,
    "required_credits": s.required_credits,
    "shortfall_credits": s.shortfall_credits,
    "started_at": ...,
}
```

### 3.5 What is explicitly *not* changed on the backend

- No new endpoint. `GET /status` and `GET /credits/balance` cover everything.
- No change to the `/run` pre-flight. It already returns the structured 402;
  `maybeShowInsufficientCredits` already handles it.
- No change to `CreditReservationDenied` — it already carries `.detail`.
- No migration. Old failed stages deserialize with `error_code=None` and render
  as generic failures.

---

## 4. Frontend

### 4.1 Shared purchase primitives — `web/src/lib/creditsPurchase.ts` (new)

Extract from `InsufficientCreditsDialog.tsx` so the panel and dialog share one
implementation:

```ts
// Smallest package whose credits cover the shortfall; fallback to cheapest.
export function pickRecommendedPackage(
  packages: CreditPackage[],
  shortfall: number
): CreditPackage | undefined;

// Launch Stripe Checkout for a package; resolves when the tab opens.
export async function buyCredits(packageId: string): Promise<void>;

// Wraps the packages query + picker.
export function useRecommendedPackage(shortfall: number): {
  package: CreditPackage | undefined;
  isLoading: boolean;
};
```

`InsufficientCreditsDialog` is refactored to import from here (no behavior
change); the new `CreditsGate` imports the same module.

### 4.2 The hook — `web/src/hooks/useNeedsCredits.ts` (new)

```ts
export type NeedsCredits =
  | { blocked: false }
  | {
      blocked: true;
      balance: number;
      required: number;
      shortfall: number;
      reason: "persisted" | "heuristic";
    };

export function useNeedsCredits(stage: StageName): NeedsCredits;
```

Reads `useProjectStatus().stages[stage]` and `useCreditBalance()`. Decision
logic, in order:

1. **Persisted (authoritative).** `status === "failed"` and
   `error_code === "insufficient_credits"` → blocked, `reason: "persisted"`,
   with `required` and `shortfall` from the persisted fields. The **balance**
   shown is always the **live** balance from `useCreditBalance()` — it is
   polled and is always at least as fresh as the persisted snapshot (see §5,
   "Topped up, but hasn't re-run yet").
2. **Heuristic.** Stage is `pending` **or** non-credit `failed`, and
   `liveBalance < stage.estimated_cost_credits` (and `estimate > 0`) → blocked,
   `reason: "heuristic"`, with `balance = liveBalance`,
   `required = estimated_cost_credits`, `shortfall = required - balance`.
3. Otherwise `{ blocked: false }`.

The heuristic applies to `pending` *and* non-credit `failed` stages, because
retrying a failed stage also costs credits. The `estimate > 0` guard avoids
false positives on stages that genuinely cost nothing to start.

The heuristic uses the already-available `StageInfo.estimated_cost_credits`
(backend computes this for the stage **including** its auto-chain). For the
new-user-on-`extract` case there is no auto-chain ahead of it, so the estimate
is exactly `extract` — correct.

### 4.3 The panel — `web/src/components/composites/CreditsGate.tsx` (new)

Presentational. Props:

```ts
interface CreditsGateProps {
  project: string;          // for handleRun auto-run
  stage: StageName;
  stageLabel: string;       // "Story Bible", "Cast", etc.
  balance: number;
  required: number;
  shortfall: number;
  reason: "persisted" | "heuristic";
}
```

Layout (consistent with `InsufficientCreditsDialog`'s visual language):

- **Headline:** `"{stageLabel} needs credits"`
- **Subhead** differs by `reason`:
  - `persisted` — `"You ran out of credits mid-stage. Buy more to resume."`
  - `heuristic` — `"You don't have enough credits to start this stage yet."`
- **3-column grid:** Balance / Needed / Shortfall (same treatment as
  `InsufficientCreditsDialog:167-195`).
- **Recommended package card** (from `useRecommendedPackage(shortfall)`)
  showing credits + price.
- **Primary CTA:** `Buy credits` → `buyCredits(pkg.id)` (opens Stripe Checkout
  in a new tab).
- **Auto-run note** (accurate per reason, since the polling mechanism below
  guarantees it):
  - `persisted` — `"After buying, this stage resumes automatically."`
  - `heuristic` — `"After buying, this stage starts automatically."`

**Auto-run mechanism.** `CreditsGate` subscribes to `useCreditBalance()`
(which already polls every 15s and refetches on window focus). When
`liveBalance >= required`, it calls `useRunAction().handleRun(project, stage)`
to (re-)run the stage — the same path the `InsufficientCreditsDialog` uses for
its `onRetry`. This requires passing `project` and `stage` into the panel;
`StagePlaceholder` already has both. A local `ranOnce` guard prevents duplicate
runs if the balance ticks past the threshold multiple times before
invalidation swaps the panel out for the real running state. The optimistic
cache write is skipped (§4.5), so the user sees the genuine "running" state
only once `GET /status` confirms it.

Credit cost phrasing follows the repo convention of `~N credits`
(AGENTS.md: "Credits phrasing is `~N credits` everywhere").

### 4.4 Render site — `web/src/components/composites/StagePlaceholder.tsx`

Single early branch, before the existing `pending`/`running`/failed logic:

```tsx
const needsCredits = useNeedsCredits(stage);
if (needsCredits.blocked) {
  return (
    <CreditsGate
      project={project}
      stage={stage}
      stageLabel={...}
      {...needsCredits}
    />
  );
}
// ...existing branches...
```

`StagePlaceholder` is already the central surface `RoomShell` routes to for
pending/running/failed stages, so this one insertion covers every room without
per-room wiring. The `ApprovalBar` continue-buttons (which fire `handleRun`)
are unchanged: when blocked, clicking them simply triggers the 402 → dialog,
and the panel behind it is already the right state.

### 4.5 Kill the optimistic flash — `web/src/api/queries.ts:153-183`

`markStageRunningInCache` is called unconditionally in `onMutate`. Wrap it:

```ts
onMutate: async ({ stage }) => {
  const balance = queryClient.getQueryData<number>(creditBalanceKey);
  const status = queryClient.getQueryData<ProjectStatus>(statusKey);
  const stageInfo = status?.stages[stage];
  if (
    typeof balance === "number" &&
    stageInfo &&
    stageInfo.estimated_cost_credits > 0 &&
    balance < stageInfo.estimated_cost_credits
  ) {
    return { previous: status, skipped: true }; // don't fake "running"
  }
  // ...existing optimistic write...
  return { previous: status };
},
```

The `skipped` flag prevents `onError` rollback logic from thrashing — on error
we just don't touch the cache (it's already correct). The mutation still
fires; if the server somehow accepts it, `onSettled` invalidates status and
the real state appears.

---

## 5. Edge cases

| Case | Resolution |
|---|---|
| **Reload after credit failure** | Persisted `error_code` (§3) → panel renders. |
| **Topped up, but hasn't re-run yet** | Panel shows the **live** balance (always fresher than the persisted snapshot). Once `liveBalance >= required`, the panel's auto-run mechanism (§4.3) calls `handleRun` and the panel is replaced by the real running state when status invalidates. |
| **Failed on credits, re-ran, now fails for a different reason** | The `else` branch in `fail_stage` (§3.2) clears `error_code` → panel does not render; stage shows the generic failed state. |
| **Stage with `estimate === 0`** (no `estimate_cost` hook) | Heuristic's `estimate > 0` guard → not flagged pre-run. If the stage nonetheless reserves a positive amount and fails mid-chain, the persisted code catches it. Pre-run the user sees a normal run; acceptable since the estimate is genuinely ~0. |
| **Concurrent runs drain balance mid-chain** | Pre-flight passed (balance was fine at submit), but the in-task `reserve_credits` RPC returns NULL → `CreditReservationDenied` → persisted code → panel. |
| **0-credit user, never clicks run** | Heuristic fires on landing in the room → panel shows immediately. They never see the flash. |
| **Returning user with credits** | Heuristic: `balance >= estimate` → `blocked: false`. Normal flow. |
| **Mobile** (top-bar credit chip is hidden < `sm`) | Panel is in-room, so the credit state is visible regardless of viewport — improves the mobile story. |

---

## 6. Testing

### Backend (pytest)

- `fail_stage` sets `error_code`/`balance`/`required`/`shortfall` when
  `detail` is a credit-failure; clears them when `detail` is absent or
  non-credit. *(state.py)*
- `_stage_payload` includes the four new fields. *(projects.py)*
- Regression: a `state.json` written *before* this change loads with the new
  fields as `None`. *(no migration)*
- `_run_stage_with_credits` persists `denied.detail` on a credit denial.
  *(pipeline.py)*

### Frontend (vitest)

- `useNeedsCredits`:
  - persisted `error_code === "insufficient_credits"` → blocked,
    `reason: "persisted"`.
  - `pending` stage with `balance < estimated_cost_credits` → blocked,
    `reason: "heuristic"`.
  - `failed` (non-credit) stage with `balance < estimated_cost_credits` →
    blocked, `reason: "heuristic"` (retrying costs credits).
  - `pending` with `estimate === 0` → not blocked.
  - `complete` / `awaiting_review` stage → not blocked.
- `markStageRunningInCache` skip path: low balance + positive estimate → cache
  untouched. Sufficient balance → existing behavior. *(queries.ts)*
- `pickRecommendedPackage`: smallest package covering shortfall; falls back to
  cheapest. *(creditsPurchase.ts)*
- `CreditsGate` renders: correct headline/subhead per `reason`; recommended
  package card; Buy button calls `buyCredits`. *(CreditsGate.tsx)*
- `CreditsGate` auto-run: when `liveBalance >= required`, calls
  `handleRun(project, stage)` exactly once (`ranOnce` guard); does not fire
  while `balance < required`. *(CreditsGate.tsx)*

### Manual / E2E (Playwright, if present)

- New account → create project → `extract` room shows `CreditsGate`, not
  "WAITING FOR PIPELINE", not a "running" flash. Buy flow → balance clears →
  stage resumes.
- Reload after a credit failure → panel still shows.
- Re-run a credit-failed stage after topping up → succeeds → panel gone.

---

## 7. Success criteria

1. A brand-new (0-credit) user who creates a project **never** sees the
   optimistic "running" animation or the "WAITING FOR PIPELINE" placeholder.
   They see the `CreditsGate` panel with a Buy CTA.
2. After a credit failure — including across a page reload — the blocked stage
   shows `CreditsGate`, not a generic failed/waiting state.
3. Purchasing from the panel (or the existing dialog) leads to automatic stage
   resumption; once resumed, the panel clears.
4. Non-credit failures and stages with sufficient credits render exactly as
   they do today (no regression).

---

## 8. Out of scope

- No free/starter credits on signup.
- No hard block on project creation.
- No new backend endpoints.
- No changes to the `/run` pre-flight or the existing
  `InsufficientCreditsDialog` retry logic (the panel is *additive* surface).
- No mobile top-bar changes (the panel already covers mobile).
