# PULP UI/UX Slice 5 Implementation Plan: Compose Issues

Date: 2026-05-04

Parent plan:
`docs/superpowers/plans/2026-05-02-pulp-ui-ux-implementation-plan.md`

## Status

Ready for implementation. Slice 4 panel acceptance is stable and
`ImageStatus.accepted` is available as the primary input to the unaccepted-panel
check.

## Goal

Add a production QA mode to the Compose room so users can surface and navigate
to fixable issues before export. Issues are warnings, not hard blockers. The
detection logic must be a pure, reusable module that Export (Slice 6) can also
call.

## Current State

- `ComposeRoom` has two edit sub-modes: `canvas` and `script`, toggled by
  `EditSubTabs` in `ModeSwitcher.tsx`.
- `EditSubMode` is `"canvas" | "script"` in `compose-types.ts`.
- `ComposeRoom` already holds `allPages: ComicPage[]` (via `useAllPages`).
- `ComicPage.panels` has `scene_id`, `panel_number`, `bubbles: Bubble[]`, and
  `sfx: Sfx | null` — enough to run all planned v1 checks.
- `ImageStatus` from `useImages` carries `accepted`, `image_available`,
  `scene_id`, and `panel_number`. `ComposeRoom` does **not** currently call
  `useImages`.
- Page canvas is `PAGE_W = 2480` × `PAGE_H = 3508` px. Bubble `x`, `y` are
  absolute pixel coordinates in that space; they are `null` when auto-placed.
- The `ConfirmDrawer` from Slice 2 and the panel acceptance flow from Slice 4
  are both stable.

## Key Decisions

### Issue engine location

New file `web/src/lib/issueEngine.ts` — pure TypeScript, no React. Accepts
`ComicPage[]` and `ImageStatus[]`, returns `ComposeIssue[]`. No hooks, no side
effects. Export can import it directly.

### Issue data model

```ts
export type IssueSeverity = "error" | "warning";

export type IssueType =
  | "unaccepted_panel"
  | "missing_image"
  | "empty_bubble_text"
  | "bubble_outside_safe_area"
  | "text_too_long"
  | "low_contrast";

export interface ComposeIssue {
  id: string;               // stable: `${type}:${pageNumber}:${panelId}:${bubbleId}`
  type: IssueType;
  severity: IssueSeverity;
  message: string;
  pageNumber: number;
  panelId?: string;         // for panel and bubble issues
  bubbleId?: string;        // for bubble issues only
}
```

`id` is deterministic from the location so that the issue list is stable across
re-renders without needing array indices.

### Which checks run client-only

All v1 checks are client-only. No new backend endpoints needed.

| Check | Severity | Condition |
|---|---|---|
| `unaccepted_panel` | warning | `ImageStatus.accepted === false` and `status === "done"` for a panel present in the page |
| `missing_image` | error | No `ImageStatus` found for a `PagePanel`, or `image_available === false` |
| `empty_bubble_text` | warning | `bubble.text.trim() === ""` |
| `bubble_outside_safe_area` | warning | Bubble is pinned (`x != null && y != null`) and its position falls outside the safe margin |
| `text_too_long` | warning | `bubble.text.length > 200` (heuristic for overflow risk) |
| `low_contrast` | warning | Both `bubble.font_color` and `bubble.fill_color` are set and their WCAG contrast ratio < 3.0 |

### Safe area margin

Use `PAGE_W * 0.05 = 124 px` and `PAGE_H * 0.05 = 175 px` as the safe inset
on each edge. A pinned bubble is flagged if `x < 124`, `y < 175`,
`x > PAGE_W - 124`, or `y > PAGE_H - 175`. The check only fires for pinned
bubbles (`x` and `y` not null) — auto-placed bubbles are the engine's
responsibility.

### Panel ↔ ImageStatus linking

`PagePanel` has `scene_id` and `panel_number`. Build a lookup `Map<string,
ImageStatus>` keyed by `${scene_id}-${panel_number}` before running checks.
If a `PagePanel` has no matching `ImageStatus` at all, treat it as
`missing_image`.

### Low contrast check

Compute relative luminance from hex color strings using the WCAG formula.
Skip the check if either color is `null`, empty, or not a valid hex string
(don't crash on CSS named colors or rgba values). This keeps the check
conservative.

### `issues` as an EditSubMode

Add `"issues"` to `EditSubMode`. It renders as a third tab between `script` and
the export button. Issue count badge appears on the tab when `issues.length > 0`.

Keyboard shortcut: do not add one in v1. The existing `1`/`2` shortcuts for
canvas/script are enough; `issues` is a review mode, not a primary editing
mode.

### Deep-link navigation from the Issues panel

`IssueMode` receives an `onGoToIssue(issue: ComposeIssue): void` callback.
`ComposeRoom` implements it:

1. Navigate to `issue.pageNumber`.
2. Switch `editSubMode` to `"canvas"`.
3. If `issue.bubbleId` is set, call `select(issue.panelId, "bubble", issue.bubbleId)`.
4. If `issue.panelId` is set but no `bubbleId`, call `select(issue.panelId, ...)` — or just navigate to the page without selecting (v1, acceptable).

### Issue grouping in the UI

Flat list, sorted: errors first, then warnings. Within each severity, sort by
page number ascending. No per-page grouping in v1 — the page badge on each row
provides enough context.

### Issue count propagation

`ComposeRoom` computes `issues` via `useMemo` and passes `issues.length` to
`EditSubTabs` (for the badge) and `issues` to `IssueMode`. No global state
needed.

## Out Of Scope

- Export checkpoint UI (Slice 6 — uses this engine, adds its own layout).
- Bubble safe-area visualisation overlay on the canvas.
- Server-side issue detection.
- "Fix" actions from the issues panel (navigate only, no inline editing).
- Bulk "Accept all" shortcut from the issues panel.
- Ordering issues by fix priority.
- Issue suppression / ignore list.

## Frontend Plan

### 1. Write `issueEngine.ts`

New file: `web/src/lib/issueEngine.ts`

Exports:

```ts
export type IssueSeverity = "error" | "warning";
export type IssueType = ...;
export interface ComposeIssue { ... }
export function detectIssues(pages: ComicPage[], images: ImageStatus[]): ComposeIssue[]
```

Internal structure — one function per check, all called by `detectIssues`:

```ts
function checkUnacceptedPanels(pages, imageMap): ComposeIssue[]
function checkMissingImages(pages, imageMap): ComposeIssue[]
function checkEmptyBubbleText(pages): ComposeIssue[]
function checkBubbleOutsideSafeArea(pages): ComposeIssue[]
function checkTextTooLong(pages): ComposeIssue[]
function checkLowContrast(pages): ComposeIssue[]
```

Helper: `contrastRatio(hex1: string, hex2: string): number` — parses two hex
colors and returns the WCAG contrast ratio. Returns `Infinity` if either color
fails to parse (so the check never fires on unparseable input).

### 2. Write `issueEngine.test.ts`

New file: `web/src/__tests__/issueEngine.test.ts`

Cover:

- `unaccepted_panel`: panel present in page with `accepted === false` and
  `status === "done"` → 1 issue. `accepted === true` → 0 issues.
- `missing_image`: no matching ImageStatus for a panel → error. Panel with
  `image_available === false` → error.
- `empty_bubble_text`: bubble with `text: ""` → 1 warning. Non-empty → 0.
- `bubble_outside_safe_area`: pinned bubble at `x=50` (below margin) → 1 warning.
  Auto-placed bubble (`x=null`) → 0. Pinned bubble safely inside → 0.
- `text_too_long`: bubble with 201-char text → 1 warning. 200-char → 0.
- `low_contrast`: black text on black fill → 1 warning. Black on white → 0.
  Null color → 0.
- `detectIssues`: empty pages → empty array.
- Issue `id` is stable (same for same page/panel/bubble).

### 3. Update `compose-types.ts`

```ts
export type EditSubMode = "canvas" | "script" | "issues";
```

### 4. Update `ModeSwitcher.tsx`

`EditSubTabsProps` gains `issueCount: number`. The `"issues"` tab renders a
small badge when `issueCount > 0`:

```tsx
{m === "issues" && issueCount > 0 && (
  <span className="ml-1.5 inline-flex h-4 min-w-4 items-center justify-center
    rounded-full bg-hero-red px-1 font-meta text-[0.48rem] text-bristol">
    {issueCount}
  </span>
)}
```

Tab label for `"issues"`: `"ISSUES"`.

### 5. Write `IssueMode.tsx`

New file: `web/src/components/compose/IssueMode.tsx`

Props:

```ts
interface IssueModeProps {
  issues: ComposeIssue[];
  onGoToIssue: (issue: ComposeIssue) => void;
}
```

Layout: full-width scrollable list inside the existing compose shell.

Header strip: `"N ISSUES FOUND"` (or `"ALL CLEAR"` when empty). Errors in
hero-red, warnings in narrator-gold.

Each issue row:
- Left: severity dot (red = error, amber = warning).
- Center: issue type label (small meta caps) + message.
- Right: page badge (`P.3`) + `GO →` button that calls `onGoToIssue(issue)`.

Empty state: archive-sage checkmark icon + `"No issues detected. Ready to
export."`.

### 6. Update `ComposeRoom.tsx`

Changes:

- Add `useImages(id)` call. Poll interval: none (static check, not live).
- Compute `issues` via `useMemo`:
  ```ts
  const issues = useMemo(
    () => detectIssues(allPages, images ?? []),
    [allPages, images],
  );
  ```
- Pass `issueCount={issues.length}` to `EditSubTabs`.
- Add `"issues"` branch alongside `canvas` and `script` branches:
  ```tsx
  {editSubMode === "issues" && (
    <IssueMode issues={issues} onGoToIssue={handleGoToIssue} />
  )}
  ```
- Add `handleGoToIssue`:
  ```ts
  function handleGoToIssue(issue: ComposeIssue) {
    setPageNum(issue.pageNumber);
    setEditSubMode("canvas");
    if (issue.panelId && issue.bubbleId) {
      select(issue.panelId, "bubble", issue.bubbleId);
    } else {
      deselect();
    }
  }
  ```
- The `"3"` keyboard shortcut currently sets `tab === "export"`. Leave it
  unchanged — `issues` is a sub-mode of the edit tab, not a top-level tab.

## Files Likely To Change

- `web/src/lib/issueEngine.ts` (new)
- `web/src/__tests__/issueEngine.test.ts` (new)
- `web/src/components/compose/compose-types.ts`
- `web/src/components/compose/ModeSwitcher.tsx`
- `web/src/components/compose/IssueMode.tsx` (new)
- `web/src/pages/rooms/ComposeRoom.tsx`

## Files Unlikely To Change

- `web/src/types/api.ts`: all needed types exist.
- `web/src/api/queries.ts`: `useImages` already exists.
- All other compose components (canvas, script, preview modes untouched).
- Backend: no changes.

## Suggested Implementation Order

1. Write `issueEngine.ts` and `issueEngine.test.ts`. Run tests until green.
2. Update `compose-types.ts` (one-line change).
3. Update `ModeSwitcher.tsx` to accept `issueCount` and render the badge.
4. Write `IssueMode.tsx`. Verify empty state and issue list render correctly
   with mock data in the dev server.
5. Update `ComposeRoom.tsx`: add `useImages`, `useMemo` for issues, wire
   `IssueMode` and `handleGoToIssue`.
6. Manually verify deep-link navigation (go to issue → canvas mode, element
   selected) against a project with known issues.
7. Run `npm test` and `npm run build`.

## Tests

### `issueEngine.test.ts`

All checks covered with positive and negative cases as described above
(~12–15 test cases). Each check gets its own `describe` block.

The `contrastRatio` helper gets its own tests:
- White on black → 21:1.
- Same color → 1:1.
- Invalid input → `Infinity` (no warning fired).

No UI component tests needed for v1.

## Verification Steps

1. Run `cd web && npm test` — all tests pass.
2. Run `cd web && npm run build` — TypeScript clean.
3. Open a project at the compose stage.
4. Issues tab:
   - With a project that has un-accepted panels: verify `unaccepted_panel`
     issues appear with correct page numbers.
   - With a project where all panels are accepted and bubbles are valid: verify
     "All clear" empty state.
   - Verify issue count badge appears on the ISSUES tab when issues exist.
5. Deep-link:
   - Click "GO →" on a bubble issue: verify page changes, canvas mode activates,
     the bubble is selected in the property panel.
   - Click "GO →" on a panel-level issue (missing image): verify page changes
     and canvas mode activates.
6. Verify canvas and script modes are unaffected (no regression).
7. Verify keyboard shortcuts `1` (canvas) and `2` (script) still work.

## Risks and Mitigations

### Risk: `useImages` adds a network request on every Compose visit

Mitigation: `useImages` uses React Query's default caching. If the draw stage
is complete, the response is stable and will be served from cache after the
first fetch. No polling is added (no `refetchInterval`).

### Risk: low contrast check crashes on CSS named colors or rgba values

Mitigation: `contrastRatio` returns `Infinity` (no issue) for any color string
that fails hex parsing. Only `#rrggbb` and `#rgb` formats trigger the check.

### Risk: safe area check produces false positives for edge panels

Mitigation: The 5% safe margin is conservative. If real projects show excessive
noise, the constant can be tuned. The check only fires for explicitly pinned
bubbles, which are a small fraction of all bubbles.

### Risk: `text_too_long` threshold is arbitrary

Mitigation: 200 characters is a loose upper bound — a speech bubble rarely
reads well above 150 characters anyway. The threshold can be adjusted based on
feedback without changing the check's structure.
