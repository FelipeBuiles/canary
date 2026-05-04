# PULP UI/UX Slice 6 Implementation Plan: Export Checkpoint

Date: 2026-05-04

Parent plan:
`docs/superpowers/plans/2026-05-02-pulp-ui-ux-implementation-plan.md`

## Status

Ready for implementation. Slice 5 (`issueEngine.ts` and `IssueMode`) are
stable. `detectIssues` is the canonical check entry point; `ComposeRoom`
already owns the `issues` array computed from `allPages` and `useImages`.

## Goal

Make the Export tab feel like a final production checkpoint. Surface unresolved
issues from the Slice 5 engine, let the user navigate back to fix them, and
still allow export with a deliberate confirmation step when issues remain.
Issues are warnings — they never hard-block export.

## Current State

- `ComposeRoom` renders `PreviewMode` when `tab === "export"`.
- `PreviewMode` has a sidebar with four cards: THEME, TRANSLATE, EXPORT (stats
  + PDF/CBZ buttons), and ALL PAGES.
- `ComposeRoom` already calls `useImages(id)` and computes `issues` via
  `useMemo` for the Compose issues sub-mode (Slice 5). The data is available at
  zero additional network cost.
- `ConfirmDrawer` is a stable, reusable component used elsewhere in the app
  (it accepts `open`, `title`, `body`, `confirmLabel`, `onConfirm`, `onClose`).
- The export actions (`onExport("pdf")` / `onExport("cbz")`) live in
  `ComposeRoom` and are already passed into `PreviewMode` as callbacks.

## Key Decisions

### Issue data flows from ComposeRoom, not re-fetched in PreviewMode

`ComposeRoom` already has `issues: ComposeIssue[]`. Pass it as a prop to
`PreviewMode`. React Query's cache means `useImages` is already resolved; no
new network request fires when the user switches to the export tab.

Do **not** call `useImages` again inside `PreviewMode`. Keeping the data source
in one place avoids any stale-data divergence between the Compose issues view
and the Export checkpoint.

### "Review Issues" callback, not router navigation

`PreviewMode` receives `onReviewIssues: () => void`. `ComposeRoom` implements
it by setting `tab` to `"edit"` and `editSubMode` to `"issues"`. This mirrors
the existing `handleSwitchToCanvas` pattern: a callback at the room level,
simple setState calls, no router involvement.

### ConfirmDrawer for export when issues exist

When `issues.length > 0` and the user clicks an export button, intercept the
action and open a `ConfirmDrawer` instead of calling `onExport` immediately.
The drawer body describes the outstanding issue count and clarifies that export
is still possible. The confirm button calls `onExport(format)` and closes the
drawer.

When `issues.length === 0`, clicking an export button calls `onExport` directly
— no drawer, no friction.

This keeps the ConfirmDrawer pattern consistent with the rest of the app and
avoids adding a new confirmation primitive.

### Production Check card position in the sidebar

Insert the PRODUCTION CHECK card between TRANSLATE and EXPORT in the existing
sidebar stack. It is directly related to export readiness, so placing it
immediately before the export actions is the natural reading order.

### No issue list in the Export sidebar

The sidebar is 220 px wide. Showing a scrollable issue list there would crowd
the existing cards. The PRODUCTION CHECK card shows only the count and severity
summary. The full list remains in the Compose `IssueMode` (reached via
"REVIEW ISSUES").

### No new files

All changes fit in `PreviewMode.tsx` (new card, drawer state, conditional
export behaviour) and `ComposeRoom.tsx` (two new props on `PreviewMode`,
`handleGoToIssues`). No new component file is needed.

## UI Spec

### Production Check card (sidebar)

**All-clear state** (`issues.length === 0`):

```
┌─────────────────────────────────────┐
│ PRODUCTION CHECK                    │
│                                     │
│  ✓  READY TO EXPORT                 │
└─────────────────────────────────────┘
```

Checkmark in `archive-sage`. Label in `ink-black/50`.

**Issues present** (`issues.length > 0`):

```
┌─────────────────────────────────────┐
│ PRODUCTION CHECK                    │
│                                     │
│  ● 2 ERRORS  ● 3 WARNINGS           │
│                                     │
│  [  REVIEW ISSUES  ]                │
└─────────────────────────────────────┘
```

- Error dot: `hero-red`. Warning dot: `narrator-gold`.
- Only the relevant line renders (omit ERRORS line if `errorCount === 0`, etc.).
- "REVIEW ISSUES" button calls `onReviewIssues()`. Secondary style, full width.

### Export buttons — conditional behaviour

| Condition | Clicking "EXPORT PDF" |
|---|---|
| `issues.length === 0` | Calls `onExport("pdf")` immediately |
| `issues.length > 0` | Opens the `ConfirmDrawer` (format stored in local state) |

Same logic for CBZ.

### ConfirmDrawer content (issues present)

```
Title:  Export with issues?
Body:   N issue(s) need attention — including X error(s) and Y warning(s).
        Panels with unaccepted images or missing text may not be print-ready.
        You can still export; review and fix issues first for best results.
Confirm label:  EXPORT PDF ANYWAY   (or EXPORT CBZ ANYWAY)
Cancel:  Cancel
```

- Errors and warnings are counted from the `issues` prop.
- Omit the errors or warnings clause when that count is zero.
- `busy` is wired to `isExporting` so the button disables during export.
- On confirm: call `onExport(pendingFormat)`, close drawer.

## Data Model

No new types. `ComposeIssue` from `issueEngine.ts` is already the correct
shape. `PreviewMode` receives `issues: ComposeIssue[]` and
`onReviewIssues: () => void` as new props.

## Frontend Plan

### 1. Update `PreviewMode.tsx`

**New props:**

```ts
interface PreviewModeProps {
  // ... existing props unchanged ...
  issues: ComposeIssue[];
  onReviewIssues: () => void;
}
```

**New local state** (inside `PreviewMode`):

```ts
const [exportDrawerFormat, setExportDrawerFormat] = useState<"pdf" | "cbz" | null>(null);
```

**New helper** — replaces direct `onExport` calls:

```ts
function handleExportClick(format: "pdf" | "cbz") {
  if (issues.length > 0) {
    setExportDrawerFormat(format);
  } else {
    onExport(format);
  }
}
```

Wire `handleExportClick` to both export buttons in place of the current
`onExport` calls.

**New ProductionCheck card** — insert in the sidebar between TRANSLATE and
EXPORT:

```tsx
<div className="border-[2px] border-ink-black bg-surface-container p-3 shadow-ink-sm">
  <div className="mb-2 font-meta text-[0.52rem] tracking-[0.18em] text-ink-black/50">
    PRODUCTION CHECK
  </div>
  {issues.length === 0 ? (
    <div className="flex items-center gap-1.5">
      <svg ...checkmark... className="h-3.5 w-3.5 text-archive-sage" />
      <span className="font-meta text-[0.52rem] tracking-[0.12em] text-ink-black/50">
        READY TO EXPORT
      </span>
    </div>
  ) : (
    <>
      <div className="mb-2 flex flex-wrap gap-2">
        {errorCount > 0 && (
          <span className="flex items-center gap-1 font-meta text-[0.5rem] tracking-[0.1em] text-hero-red">
            <span className="h-1.5 w-1.5 rounded-full bg-hero-red" />
            {errorCount} ERROR{errorCount !== 1 ? "S" : ""}
          </span>
        )}
        {warnCount > 0 && (
          <span className="flex items-center gap-1 font-meta text-[0.5rem] tracking-[0.1em] text-narrator-gold">
            <span className="h-1.5 w-1.5 rounded-full bg-narrator-gold" />
            {warnCount} WARNING{warnCount !== 1 ? "S" : ""}
          </span>
        )}
      </div>
      <Button size="sm" variant="secondary" fullWidth onClick={onReviewIssues}>
        REVIEW ISSUES
      </Button>
    </>
  )}
</div>
```

**Export ConfirmDrawer** — mount at the bottom of `PreviewMode`'s JSX:

```tsx
<ConfirmDrawer
  open={exportDrawerFormat !== null}
  title="Export with issues?"
  body={buildExportDrawerBody(issues)}
  confirmLabel={`EXPORT ${exportDrawerFormat?.toUpperCase()} ANYWAY`}
  busy={isExporting}
  onConfirm={() => {
    if (exportDrawerFormat) onExport(exportDrawerFormat);
    setExportDrawerFormat(null);
  }}
  onClose={() => setExportDrawerFormat(null)}
/>
```

Helper (pure function, defined outside the component):

```ts
function buildExportDrawerBody(issues: ComposeIssue[]): string {
  const errors = issues.filter((i) => i.severity === "error").length;
  const warnings = issues.filter((i) => i.severity === "warning").length;
  const parts: string[] = [];
  if (errors > 0) parts.push(`${errors} error${errors !== 1 ? "s" : ""}`);
  if (warnings > 0) parts.push(`${warnings} warning${warnings !== 1 ? "s" : ""}`);
  const summary = parts.join(" and ");
  return (
    `${issues.length} issue${issues.length !== 1 ? "s" : ""} need attention — including ${summary}. ` +
    `Panels with unaccepted images or missing text may not be print-ready. ` +
    `You can still export; review and fix issues first for best results.`
  );
}
```

### 2. Update `ComposeRoom.tsx`

Add `handleGoToIssues`:

```ts
function handleGoToIssues() {
  setTab("edit");
  setEditSubMode("issues");
}
```

Pass new props to `PreviewMode`:

```tsx
<PreviewMode
  {/* ...existing props... */}
  issues={issues}
  onReviewIssues={handleGoToIssues}
/>
```

## Files That Change

- `web/src/components/compose/PreviewMode.tsx` (add card, drawer, conditional
  export logic, two new props)
- `web/src/pages/rooms/ComposeRoom.tsx` (`handleGoToIssues`, two new props on
  `PreviewMode`)

## Files That Do Not Change

- `web/src/lib/issueEngine.ts` — no changes needed.
- `web/src/components/compose/IssueMode.tsx` — no changes needed.
- `web/src/components/compose/compose-types.ts` — no changes needed.
- `web/src/components/compose/ModeSwitcher.tsx` — no changes needed.
- Backend: no changes.

## Suggested Implementation Order

1. Add `issues` and `onReviewIssues` props to `PreviewModeProps` — TypeScript
   will flag every call site; fix `ComposeRoom.tsx` immediately.
2. Add `handleGoToIssues` to `ComposeRoom` and pass props.
3. Add the `exportDrawerFormat` state, `handleExportClick` helper, and swap
   the export button `onClick` handlers.
4. Add the PRODUCTION CHECK card to the sidebar.
5. Mount the `ConfirmDrawer` and wire `buildExportDrawerBody`.
6. Verify in the dev server: all-clear project, issues project, export with
   issues, export without issues.
7. Run `npm test` and `npm run build`.

## Verification Steps

1. `cd web && npm test` — all tests pass (no new tests needed; engine is
   already tested).
2. `cd web && npm run build` — TypeScript clean.
3. Open a project with no issues in the export tab:
   - Production Check card shows green checkmark + "READY TO EXPORT".
   - Clicking "EXPORT PDF" calls export immediately — no drawer appears.
4. Open a project with unaccepted panels / empty bubbles in the export tab:
   - Production Check card shows error/warning counts and "REVIEW ISSUES".
   - Clicking "REVIEW ISSUES" switches to Edit → Issues mode.
   - Clicking "EXPORT PDF" opens the ConfirmDrawer with correct count summary.
   - Clicking Cancel dismisses the drawer; no export fires.
   - Clicking "EXPORT PDF ANYWAY" fires the export and closes the drawer.
   - Button disables (`busy`) while export is in flight.
5. Verify keyboard shortcut `3` still opens the export tab (no regression).
6. Verify the Compose issues tab is unaffected (no regression).

## Risks and Mitigations

### Risk: issues prop is stale if user accepts panels while on the export tab

The `issues` array is derived from `images` (React Query) and `allPages`. React
Query will refetch `images` on window focus or when the accept mutation
invalidates the cache. Because `ComposeRoom` holds the `issues` memo at the
top level, switching from the export tab back to compose and accepting a panel
will update `issues` automatically on return. No special handling needed.

### Risk: drawer body text is awkward for single-issue case

`buildExportDrawerBody` uses singular/plural helpers consistently (`issue`/
`issues`, `error`/`errors`, `warning`/`warnings`). Covered in implementation
step 5 — manually check with 1 issue, 1 error, 1 warning.

### Risk: "Review Issues" from export tab leaves user on wrong page

`handleGoToIssues` just switches tabs and sub-mode — it does not change the
current page number. When the user arrives at the Issues list, they click
"GO →" on a specific issue to navigate. This is correct behavior: no page
change should happen until the user explicitly picks an issue.
