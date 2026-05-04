# PULP UI/UX Slice 7 Implementation Plan: Production Cost Ledger

Date: 2026-05-04

Parent plan:
`docs/superpowers/plans/2026-05-02-pulp-ui-ux-implementation-plan.md`

## Status

Ready to plan. Slices 1–6 are complete. Slice 2 (Cost Trust Foundation) shipped
with `CostBreakdown` and `CostInline` primitives. The billing history endpoint
and `credit_ledger` table are stable.

## Goal

Turn the flat credit transaction log into a readable production ledger grouped
by action. Each group should show estimate, actual charge, and returned credits
at a glance so the user can understand what each production step cost and where
their budget went.

## Current State

### What exists

- `/credits/history` returns `{ transactions: CreditTransaction[] }` — a flat
  chronological list for the authenticated user.
- `CreditTransaction` has: `id`, `amount_credits`, `status` (`reserved` |
  `settled` | `released`), `stage`, `description`, `project_id`, `created_at`,
  plus optional provider/model/token metadata.
- `CreditsPage` renders a 3-column table: Description | When | Credits. It uses
  `tx.description` or `Model call: {tx.stage}` as the label.
- No grouping, no reservation-vs-actual breakdown, no project name shown,
  no per-project filter.

### What a complete stage run produces in the ledger

```
Row A  status=reserved   amount=-200  stage="draw"   (hold placed at run start)
Row B  status=settled    amount=-12   stage="draw"   (model call 1)
Row C  status=settled    amount=-8    stage="draw"   (model call 2)
...
Row A' status=released   amount=-200  stage="draw"   (same row A, status updated when stage finishes — unused hold returned)
```

The `released` status is set in-place on Row A; it does not produce a new row.
So the ledger already expresses estimate (reserved), actual (sum of settled),
and returned (reserved amount − actual, released back to balance) — but none of
these rows are linked by any field.

## The Grouping Problem and Resolution

Without a linking field, frontend grouping must rely on temporal proximity
combined with `(stage, project_id)`. This is unreliable when the same stage
runs twice in quick succession for the same project, or when two projects run
the same stage concurrently.

**Decision: add `job_id UUID` to `credit_ledger`.**

This is the minimal backend change required to make grouping reliable. Every
stage run gets one fresh UUID at reservation time; all debit rows for that run
receive the same `job_id`. The frontend groups by `job_id` and can calculate
estimate / actual / returned without heuristics.

The column is nullable so existing rows (which have no `job_id`) continue to
appear ungrouped as individual "legacy" rows.

## Key Decisions

### job_id is the grouping key; all else is display logic

The backend adds `job_id` as a UUID column. The frontend groups transactions
by it. Rows without a `job_id` (legacy / purchase rows) remain flat.

### Per-project filtering via existing project_id on transactions

`CreditTransaction.project_id` already exists. The frontend fetches the project
list from the existing `useProjects` query and resolves names for display. No
new backend endpoint is needed for per-project filtering — the filtering is
done client-side.

### No second API endpoint for grouped data

The backend returns flat rows. The frontend groups them. This avoids a new
aggregation endpoint and keeps the plan minimal.

### Ledger lives on CreditsPage, not per-project pages

History appears in one place — the existing CreditsPage — with a project filter
dropdown. Per-project ledger sections inside individual project rooms are
deferred.

### Expand/collapse per group for model-call detail

Each action group shows a summary row. Clicking it expands to show the
individual settled rows with model, token counts, and per-call credits. This
keeps the default view scannable without losing the raw data.

### User-facing stage label map lives in a shared constant

Backend stage keys (`draw`, `plan`, `direct`, etc.) map to user-facing labels
(`Generate Panels`, `Shot Plan`, `Prompt Review`, etc.). This map already
exists implicitly in the app; we extract it into one shared constant file so
the ledger, rail, and room headers all use the same strings.

## Data Model

### Backend: new `job_id` column

```sql
ALTER TABLE credit_ledger ADD COLUMN job_id UUID;
```

No index is strictly needed for the current history volume, but one on
`(user_id, job_id)` would help if the history grows large.

### Frontend: extended CreditTransaction type

```ts
export interface CreditTransaction {
  // existing fields unchanged
  id: string;
  amount_credits: number;
  status: "reserved" | "settled" | "released";
  stage: string | null;
  description: string | null;
  project_id: string | null;
  created_at: string;
  provider?: string | null;
  model?: string | null;
  operation?: string | null;
  input_tokens?: number;
  output_tokens?: number;
  image_count?: number;
  // new
  job_id?: string | null;
}
```

### Frontend: computed LedgerGroup type (not persisted)

```ts
interface LedgerGroup {
  job_id: string;
  stage: string | null;
  project_id: string | null;
  startedAt: string;           // created_at of the reservation row
  estimate_credits: number;    // abs(reserved row amount_credits)
  actual_credits: number;      // sum of abs(settled rows' amount_credits)
  returned_credits: number;    // estimate - actual, when status = "released"
  status: "in_flight" | "complete" | "failed";
  rows: CreditTransaction[];   // all rows in this group (for expand view)
}
```

For legacy rows without `job_id`, each row becomes its own single-row group.

## UI Spec

### History section — grouped ledger

Replace the 3-column flat table with a grouped list. Each group renders as a
single summary row with an expand chevron.

**Collapsed group row:**

```
┌──────────────────────────────────────────────────────────────────────┐
│ ▶  Generate Panels · My Project          Est 200  Act 87  Ret 113   │
│    2026-05-04 14:30                      ● COMPLETE                  │
└──────────────────────────────────────────────────────────────────────┘
```

Column layout (left to right):
- Expand chevron (`▶` / `▼`)
- Stage label + project name
- Start timestamp
- EST / ACT / RET credit columns (right-aligned, tabular-nums)
- Status badge

**Expanded group (shows after clicking the row):**

```
▼  Generate Panels · My Project           Est 200  Act 87  Ret 113
   2026-05-04 14:30                        ● COMPLETE
   ├ claude-3-5-sonnet · prompt      12 ◆
   ├ fal/flux1-schnell · 4 images    35 ◆
   ├ fal/flux1-schnell · 3 images    28 ◆
   └ claude-3-5-sonnet · compose     12 ◆
```

Each child row: model label | operation hint | credits (right-aligned).

**Status badges:**
- `IN FLIGHT` — `narrator-gold` background; reserved row present, not released
- `COMPLETE` — `archive-sage` background; reservation released
- `FAILED` — `hero-red` background; reservation released, zero actual debits
- (no badge for credit purchases or legacy rows)

**In-flight group:** If a `reserved` row has `status="reserved"` (not yet
released), show only the estimate column; actual and returned are dashes.

**Columns for ungrouped / legacy rows:** show description, date, credits —
same as the current table, no EST/ACT/RET.

### Project filter

A small dropdown above the ledger:

```
ALL PROJECTS  ▾
```

Options: "All Projects" + one entry per distinct `project_id` found in
transactions. Project names resolved from the project list query. Unknown IDs
fall back to the truncated UUID.

When a project is selected, only groups (and ungrouped rows) whose `project_id`
matches are shown. Credit purchases (no `project_id`) are always shown under
"All Projects" and hidden when a specific project is filtered.

### Credit summary bar

Keep the existing "This month" bar and balance section unchanged.

## Backend Plan

### 1. DB migration

```sql
ALTER TABLE credit_ledger ADD COLUMN job_id UUID;
CREATE INDEX IF NOT EXISTS idx_credit_ledger_job_id
  ON credit_ledger (user_id, job_id)
  WHERE job_id IS NOT NULL;
```

### 2. `credits.py` — thread `job_id` through reserve and debit

Update `reserve_credits` to accept and write a `job_id`:

```python
import uuid as uuid_lib

def reserve_credits(
    db: Client,
    user_id: str,
    project_id: str | None,
    stage: str,
    amount_credits: int,
    *,
    job_id: str | None = None,
) -> tuple[str | None, str]:
    """Returns (reservation_id, job_id). Generates a fresh job_id if none given."""
    if job_id is None:
        job_id = str(uuid_lib.uuid4())
    if amount_credits <= 0:
        return None, job_id
    result = db.rpc("reserve_stage_credits", {
        "p_user_id": user_id,
        "p_project_id": project_id,
        "p_stage": stage,
        "p_amount_credits": amount_credits,
        "p_job_id": job_id,
    }).execute()
    reservation_id = result.data
    if not reservation_id:
        balance = get_balance_credits(db, user_id)
        raise HTTPException(
            402,
            f"Insufficient credits — {balance} available, {amount_credits} required for '{stage}'",
        )
    return str(reservation_id), job_id
```

Update `debit_model_usage` to accept `job_id`:

```python
def debit_model_usage(
    db: Client,
    user_id: str,
    project_id: str | None,
    usage: UsageRecord,
    *,
    stage: str | None = None,
    description: str,
    job_id: str | None = None,
) -> None:
    ...
    db.table("credit_ledger").upsert({
        ...existing fields...,
        "job_id": job_id,
    }, on_conflict="usage_call_id").execute()
```

Update the `reserve_stage_credits` Supabase RPC (or inline SQL in
`reserve_credits` if no RPC is used) to accept and store `p_job_id`.

### 3. Stage runner — pass job_id

In the pipeline stage execution code, capture the `job_id` returned by
`reserve_credits` and pass it to every `debit_model_usage` call within that
stage run. The exact call site depends on how stages thread the db/credits
context; this is a localized change to the stage runner, not to each stage
individually.

### 4. History endpoint — include job_id

The `/credits/history` endpoint already returns all ledger columns via a
`SELECT *`-equivalent. No query change is needed; `job_id` will appear in
the response once the column exists. Confirm the Supabase query in
`credits.py` does not explicitly exclude it.

## Frontend Plan

### 1. Shared stage label map — new file

```ts
// web/src/lib/stageLabels.ts
export const STAGE_LABELS: Record<string, string> = {
  extract:    "Extract Story",
  style:      "Look & Feel",
  cast:       "Cast & Locations",
  adapt:      "Adapt Screenplay",
  plan:       "Shot Plan",
  storyboard: "Shot Plan",
  direct:     "Prompt Review",
  draw:       "Generate Panels",
  compose:    "Letter & Compose",
};

export function stageLabel(stage: string | null): string {
  if (!stage) return "System";
  return STAGE_LABELS[stage] ?? stage.charAt(0).toUpperCase() + stage.slice(1);
}
```

### 2. types/api.ts — add job_id to CreditTransaction

One line addition: `job_id?: string | null;`

### 3. CreditsPage.tsx — replace flat table with grouped ledger

**New grouping pure function** (defined outside the component):

```ts
function groupTransactions(txs: CreditTransaction[]): LedgerGroup[] {
  // Separate transactions with and without job_id
  const byJob = new Map<string, CreditTransaction[]>();
  const ungrouped: CreditTransaction[] = [];

  for (const tx of txs) {
    if (tx.job_id) {
      const existing = byJob.get(tx.job_id) ?? [];
      existing.push(tx);
      byJob.set(tx.job_id, existing);
    } else {
      ungrouped.push(tx);
    }
  }

  const groups: LedgerGroup[] = [];

  for (const [job_id, rows] of byJob.entries()) {
    const reservation = rows.find((r) => r.status === "reserved" || r.status === "released");
    const settled = rows.filter((r) => r.status === "settled");
    const estimate = reservation ? Math.abs(reservation.amount_credits) : 0;
    const actual = settled.reduce((s, r) => s + Math.abs(r.amount_credits), 0);
    const isReleased = reservation?.status === "released";
    const returned = isReleased ? Math.max(0, estimate - actual) : 0;
    const status: LedgerGroup["status"] =
      !isReleased ? "in_flight"
      : actual > 0 ? "complete"
      : "failed";
    const startedAt = rows.reduce((earliest, r) =>
      r.created_at < earliest ? r.created_at : earliest, rows[0].created_at);
    groups.push({
      job_id,
      stage: reservation?.stage ?? settled[0]?.stage ?? null,
      project_id: reservation?.project_id ?? null,
      startedAt,
      estimate_credits: estimate,
      actual_credits: actual,
      returned_credits: returned,
      status,
      rows,
    });
  }

  for (const tx of ungrouped) {
    groups.push({
      job_id: tx.id,
      stage: tx.stage,
      project_id: tx.project_id,
      startedAt: tx.created_at,
      estimate_credits: 0,
      actual_credits: Math.max(0, -tx.amount_credits),
      returned_credits: 0,
      status: "complete",
      rows: [tx],
    });
  }

  // Sort by startedAt descending (newest first)
  return groups.sort((a, b) => b.startedAt.localeCompare(a.startedAt));
}
```

**New `LedgerGroupRow` component** inside `CreditsPage.tsx`:

- Renders a summary row (estimate / actual / returned columns + badge)
- Tracks `expanded: boolean` in local `useState`
- When expanded, renders child rows for each settled tx

**Project filter:** `useState<string | null>(null)` for `projectFilter`.
Dropdown built from `useMemo` over the grouped list's distinct `project_id`s,
resolved with a `useProjects` hook (already exists in the app).

**Modified `CreditsPage`:** replace the `<table>` in the History section with
`{groups.map((g) => <LedgerGroupRow key={g.job_id} group={g} ... />)}`. Keep
the balance, "How credits work", and "Add Credits" sections unchanged.

## Files That Change

### Backend
- `novel_to_comic/src/novel_to_comic/server/credits.py` — `job_id` param on
  `reserve_credits` and `debit_model_usage`
- Stage runner / pipeline orchestration code that calls `reserve_credits` and
  passes the context to `debit_model_usage` (exact file TBD during
  implementation — likely `pipeline.py` or a shared stage context object)
- Supabase migration (SQL): `ALTER TABLE credit_ledger ADD COLUMN job_id UUID`
- Supabase `reserve_stage_credits` RPC: add `p_job_id` parameter and write it

### Frontend
- `web/src/lib/stageLabels.ts` (new)
- `web/src/types/api.ts` (add `job_id` to `CreditTransaction`)
- `web/src/pages/CreditsPage.tsx` (grouped ledger, project filter, expand row)

## Files That Do Not Change

- `web/src/api/credits.ts` — no new endpoint needed
- `web/src/components/cost/CostBreakdown.tsx` — unchanged
- `web/src/components/cost/CostInline.tsx` — unchanged
- `web/src/components/ui/ConfirmDrawer.tsx` — unchanged
- All compose and export components — unchanged

## Suggested Implementation Order

1. DB migration: add `job_id UUID` column and index to `credit_ledger`.
2. Update Supabase `reserve_stage_credits` RPC to accept and store `p_job_id`.
3. Update `reserve_credits` in `credits.py` to generate and return `job_id`.
4. Update `debit_model_usage` to accept and store `job_id`.
5. Thread `job_id` through the stage runner so every model call in a stage run
   shares the same `job_id`.
6. Verify in the DB that a test stage run produces rows with matching `job_id`.
7. Add `job_id` to `CreditTransaction` in `types/api.ts`.
8. Write `stageLabels.ts`.
9. Write `groupTransactions` pure function and `LedgerGroup` type.
10. Build `LedgerGroupRow` component with expand/collapse.
11. Wire project filter dropdown using `useProjects`.
12. Replace the flat table in `CreditsPage` with the grouped ledger.
13. Run `npm test` and `npm run build`.
14. Manually verify in the dev server with a project that has a completed
    stage run.

## Verification Steps

1. `cd web && npm test` — all existing tests pass.
2. `cd web && npm run build` — TypeScript clean.
3. Run a stage that charges credits (e.g. Shot Plan or Generate Panels).
4. Open `/credits` and confirm:
   - The stage run appears as one group (not many flat rows).
   - Estimate shows the reservation amount.
   - Actual shows the sum of settled rows.
   - Returned shows estimate − actual (when reservation is released).
   - Status badge shows `IN FLIGHT` while running, `COMPLETE` after.
5. Filter by project — confirm only that project's groups appear.
6. Expand a group — confirm individual model calls appear with model label
   and per-call credits.
7. Credit purchases (Stripe) still appear as flat ungrouped rows with the
   original description.
8. Projects with no transactions do not appear in the filter dropdown.
9. Legacy rows (no `job_id`) each appear as individual rows, not grouped.

## Risks and Mitigations

### Risk: reserve_stage_credits RPC may not exist or may be inlined

Inspect the actual Supabase function. If it is inlined SQL in `credits.py`,
add `job_id` directly to the `INSERT` statement. If it is a stored procedure,
update it. The implementation step 2 must verify which path is taken before
editing.

### Risk: stage runner threading is unclear without reading all callers

Step 5 ("thread job_id through the stage runner") is the most likely to
uncover surprises. Run `grep -r "reserve_credits\|debit_model_usage"`
across the Python source before writing any code to map all call sites.

### Risk: Supabase SELECT in history endpoint may omit job_id

If the history query explicitly lists columns (rather than `SELECT *`), the
new column will be silently absent from API responses. Check
`server/routers/credits.py` history endpoint before assuming the field appears
automatically.

### Risk: groupTransactions is wrong for zero-reservation stages

Some stages (`storyboard`, `direct`, `compose`) have zero estimated cost and
may produce no reservation row, only settled rows (if any model calls happen).
These rows will all have the same `job_id` if the stage runner always generates
one, so they group correctly. Verify by testing with `compose` stage.

### Risk: returned_credits calculation is wrong if stage only partially ran

If a stage is cancelled mid-run, the reservation is released but some settled
rows exist. `returned = estimate - actual` is still correct — the unreserved
portion is returned. No special handling needed.
