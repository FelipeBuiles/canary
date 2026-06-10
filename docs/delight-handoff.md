# Delight Backlog — Handoff

Output of a June 2026 `/delight` review of the PULP web frontend (`web/`).
Each item below is self-contained: a fresh session should be able to implement
it from this document alone. Suggested prompt for a new session:

> Read `docs/delight-handoff.md` and implement item N. Follow the shared
> guardrails section. Verify per the item's verification notes.

Items are ordered by value. 2 and 5 are quick wins; 1 is the highest-value.

---

## Shared context (read first)

- **Brand system:** `DESIGN.md` at repo root ("The Living Ink" — Golden-Age
  print-shop tribute). **Strategy:** `PRODUCT.md` at repo root (register:
  `product` — delight at checkpoints only, calm steady state).
- **Tokens & keyframes:** `web/src/index.css`. Relevant existing materials:
  `--color-narrator-gold`, `--shadow-ink*`, `.animate-comic-pop`,
  `.skeleton-benday`, `.benday-paper`.
- **House micro-interaction:** the ink-stamp press on
  `web/src/components/ui/Button.tsx` — hover nudges 1px, `:active` presses
  3px while the offset shadow collapses. Reuse this vocabulary; don't invent
  new motion grammar.

### Shared guardrails (apply to every item)

1. **No `border-radius`, ever** (DESIGN.md). No Material-style soft shadows —
   depth is offset "mechanical" shadows (`shadow-ink*`, `shadow-paper*`).
2. **No toasts.** Celebrations are gold "Burst" boxes (`narrator-gold`
   background, 2px `ink-black` border) per DESIGN.md §6.
3. **Reduced motion is non-negotiable.** Global kill switch exists in
   `web/src/index.css` (`@media (prefers-reduced-motion: reduce)`); CSS
   animations inherit it, but any JS-driven animation (canvas, rAF tweens)
   must check `matchMedia("(prefers-reduced-motion: reduce)")` itself, like
   `FlowingDotsPlaceholder.tsx` does.
4. **Delight is < 1s, skippable, never blocks the task.** No orchestrated
   sequences; no motion added to steady-state surfaces.
5. **Voice:** confident studio foreman — warm, print-shop vocabulary,
   lightly theatrical at milestones. Never wacky in error or billing copy.
6. Per `AGENTS.md`: minimum code, touch only files the item requires, match
   existing style. Per `CLAUDE.md`: work directly on `main`, no worktrees.

### Commands

```bash
cd web && npm run dev     # Vite dev server (frontend-only items need nothing else)
cd web && npm test        # vitest
cd web && npm run build   # tsc -b && vite build — must stay green
```

---

## Item 1 — Export ceremony ("hot off the press")

**Problem.** Exporting the finished comic is the product's single biggest
payoff, and today it's two small buttons in
`web/src/components/compose/ComposeHeader.tsx` (`PDF`, `CBZ`) that flip to
`EXPORTING…` and silently back. No completion moment at all.

**Build.** When an export succeeds, show a gold Burst panel (this is the
DESIGN.md-sanctioned celebration surface):

- Container: `bg-narrator-gold`, `border-[2px] border-ink-black`,
  `shadow-ink`, 0 radius, entering with `animate-comic-pop` (instant-appear
  under reduced motion).
- Content: `font-display` headline `HOT OFF THE PRESS`, subline
  `ISSUE READY — {pageCount} PAGES`, the download link/button for the
  exported file, and a dismiss control (click-outside + visible `ESC` button,
  matching the pattern in `InsufficientCreditsDialog.tsx`).
- Do **not** auto-dismiss — it carries the download link. Position centered
  over the compose surface or anchored under the header; implementer's call.

**Wiring.** `ComposeHeader` only receives `isExporting` and `onExport(format)`
as props — the export mutation lives in the parent
(`web/src/pages/rooms/ComposeRoom.tsx`; find where `isExporting` is derived
and where the export request resolves, likely via `web/src/api/` +
TanStack Query). Hook the ceremony to the mutation's success callback, where
the artifact URL/filename is known. Inspect what the export endpoint returns
before designing the download affordance.

**Verify.** Run an export in dev (or mock the mutation in a vitest test):
burst appears once on success with correct page count and working download;
Esc and click-outside dismiss; `npm run build` and `npm test` green;
reduced-motion shows it without the pop.

---

## Item 2 — Port the Spanish voice into the English copy

**Problem.** In `web/src/i18n.tsx` the `en` table is empty, so the literal
keys are the English UI — and they're flat ("LOADING PANELS…",
"GENERATING…"). The Spanish table carries craft metaphors that fit the brand
far better: `ENTINTANDO LAS VIÑETAS…` (inking the panels),
`BOSQUEJANDO EL ARCHIVO NARRATIVO…`, `MEZCLANDO PALETAS DE COLOR…`,
`PREPARANDO LA MESA DE DIBUJO…`. English deserves the same voice.

**Build.** Rename these keys (the key *is* the EN string, so every rename
must update all `t("…")` call sites — `rg` for each — plus the `es` and `fr`
map entries):

| Current key | New EN string | Existing ES (keep) |
|---|---|---|
| `LOADING STORY BIBLE…` | `SKETCHING THE STORY BIBLE…` | `BOSQUEJANDO EL ARCHIVO NARRATIVO…` |
| `LOADING PANELS…` | `INKING PANELS…` | `ENTINTANDO LAS VIÑETAS…` |
| `LOADING STYLES…` | `MIXING PALETTES…` | `MEZCLANDO PALETAS DE COLOR…` |
| `LOADING PROMPT SAMPLE...` | `DEVELOPING PROOF SHEETS…` | `REVELANDO BOCETOS DE PRUEBA...` |
| `GENERATING NEW PANEL` | `LAYING DOWN LINES…` | `TIRANDO LÍNEAS EN EL LIENZO…` |
| `BUILDING STUDIO INDEX…` | `WARMING UP THE DRAWING TABLE…` | `PREPARANDO LA MESA DE DIBUJO…` |
| `GENERATING…` | `DRAWING…` | `DIBUJANDO…` |

Update the `fr` entries to match the new voice (current FR is literal),
e.g. `INKING PANELS…` → `ENCRAGE DES CASES…`,
`SKETCHING THE STORY BIBLE…` → `CRAYONNÉ DE LA BIBLE DE L'HISTOIRE…`,
`MIXING PALETTES…` → `MÉLANGE DES PALETTES…`,
`WARMING UP THE DRAWING TABLE…` → `PRÉPARATION DE LA TABLE À DESSIN…`.

**Scope guard.** Only loading/progress strings get the craft voice. Error,
billing, and destructive-action copy stays literal. Don't invent strings
that misdescribe what a stage does — each line must map to the stage's real
work (extract sketches structure, draw inks panels, style mixes palettes).

**Verify.** `rg` shows no orphaned old keys; switch UI language to es/fr in
the running app (language picker persists via `canary.uiLanguage`
localStorage) and confirm all three languages render; `npm test` green.

---

## Item 3 — 404 page ("cutting room floor")

**Problem.** `web/src/App.tsx` has no `path="*"` route. Unmatched URLs render
a blank outlet inside the Shell.

**Build.** Catch-all route rendering a NotFound page: an empty comic panel
(2px ink-black border, `bg-bristol`, maybe `.benday-paper` backdrop) with
`font-display` headline `THIS PAGE WAS LEFT ON THE CUTTING ROOM FLOOR` and a
`Button` back to the Library (`/`). Reuse the `StateBlock` composition
pattern (`web/src/components/ui/StateBlock.tsx`). Add a nested catch-all
under `project/:id` too if straightforward (redirect to `NavigateToRoom` is
acceptable there).

**Note:** a background task chip for this item may already exist from the
review session — check open sessions before starting to avoid duplicating.

**Verify.** Visit `/nonsense` and `/project/x/nonsense` in dev; both render
something intentional; `npm run build` green.

---

## Item 4 — "All panels inked" milestone in the Draw room

**Problem.** `web/src/components/draw/LiveCockpit.tsx` renders ETA,
throughput, in-flight and recent-finish lists during the longest wait in the
product — but when the final panel lands (`generated === total`), nothing
happens.

**Build.** One-shot celebration on the transition into completion:

- Detect the transition (previous `generated < total` → `generated === total`
  with `total > 0`), e.g. a `useRef` of the previous value in the component
  that owns the donut/summary (check `web/src/pages/rooms/DrawRoom.tsx` for
  where `PanelProgressDonut` gets its props, and `web/src/store/drawProgress.ts`
  for existing state). Must fire once per completion, not on remount of an
  already-complete stage.
- Effect: `animate-comic-pop` on the donut + a small gold stamp
  (`ALL PANELS INKED`, `bg-narrator-gold`, 2px ink-black border) near the
  summary. If panels failed, do **not** celebrate — the existing failure
  surfacing keeps priority.
- Optional, cheap: apply `animate-comic-pop` to new rows arriving in
  `RecentFinishesCard` (class on mount is enough).

**Verify.** Simulate a draw run finishing (dev-mode project, or unit-test the
transition detection); stamp appears once, not on page reload of a complete
stage, never when `failed > 0`; reduced-motion shows the stamp without pop.

---

## Item 5 — Give NEXT STAGE the house press physics

**Problem.** The most-clicked button in the app — the red `NEXT STAGE` /
`APPROVE & CONTINUE` CTA at the bottom of the sidebar
(`web/src/layout/SideNav.tsx`, the `handleContinueClick` button, around line
649) — is a raw `<button>` with only a background hover. It's the one major
CTA missing the ink-stamp press every `Button` has.

**Build.** Add the press vocabulary from `Button.tsx` to its className:
`shadow-ink-sm hover:translate-x-[1px] hover:translate-y-[1px]
hover:shadow-paper-sm active:translate-x-[3px] active:translate-y-[3px]
active:shadow-none` plus the disabled resets
(`disabled:shadow-none disabled:hover:translate-x-0 disabled:hover:translate-y-0`)
and `transform` in the transition list. It already has `shadow-ink-sm` and
`disabled:shadow-none` — extend, don't duplicate. Swapping the element to the
shared `Button` component is also acceptable if the custom layout (loader
icon, responsive min-heights, tracking) survives intact; the class-add is the
lower-risk path.

**Verify.** Visual check in dev across enabled/hover/active/disabled and the
`RUNNING…` state; the drop shadow on the dark sidebar background still reads
(ink-black shadow on ink-black bg — if invisible, use `shadow-paper-sm` as
the resting shadow instead). `npm run build` green.

---

## Item 6 — Reveal moments for async arrivals

Two silent state-swaps that deserve a beat:

**6a. Library cover lands.** `web/src/pages/Library.tsx` polls every 3s while
covers generate; when ready, `ProjectCard` swaps skeleton → image with no
transition. Track the `coverPending → has_cover` transition and fade/pop the
arriving cover in (CSS opacity transition + optional `animate-comic-pop` on
the card border; `LazyImage` in `web/src/components/ui/LazyImage.tsx` may
already expose an onLoad hook — check before adding one).

**6b. Credits top-up lands.** The credits chip in
`web/src/layout/AppTopBar.tsx` re-renders with the new balance when the
Stripe webhook lands (the insufficient-credits dialog already auto-retries on
this). Animate the number counting up over ~600ms (rAF tween, `tabular-nums`
already set so no layout shift; instant under reduced motion). Only animate
increases — decreases (spend) stay instant and quiet.

**Verify.** 6a: create a project and watch covers arrive in dev. 6b: unit
test the tween hook, or simulate a balance bump via query-cache update.
Reduced-motion path = instant swap for both.

---

## Item 7 — First-run Library as "Issue #0"

**Problem.** A brand-new account sees the full Library page with zeroed
STUDIO TELEMETRY (`0 archive files, 0 live boards, 0 ink`) and a dashed
new-project card — accurate, but it teaches nothing and celebrates nothing.
This is the only empty state every new user is guaranteed to see.

**Build.** When `projects?.length === 0` in `web/src/pages/Library.tsx`:

- Replace the telemetry zeros with `AWAITING FIRST PRODUCTION` (keep the
  panel; swap the rows for a single line in the existing meta style).
- In the grid area, render a first-issue invitation instead of the bare
  dashed card: `ISSUE #0` framing, one line of foreman voice ("Every
  production starts with a manuscript."), a mini pipeline strip teaching the
  journey — render the 9 stage labels from `UI_STAGES`
  (`web/src/lib/uiStages.ts`) as a compact strip (numbered chips with
  ink-black borders), and the existing upload CTA opening `NewProjectModal`.
- Keep it static — no entrance animation; the teaching is the delight.
  All new strings go through `t()` with es/fr entries (see item 2's voice).

**Verify.** Empty-account state in dev (or mock `useProjects` to return `[]`);
non-empty libraries are completely unaffected; i18n renders in all three
languages.

---

## Item 8 — Real pipeline log lines during stage waits

**Problem.** `StageRunning` in
`web/src/components/composites/StagePlaceholder.tsx` shows a static stage
description + progress bar for waits that can run minutes. The pipeline emits
real per-item events over SSE, and the frontend already stores them
(`web/src/store/pipeline.ts`, populated via `connect(projectId)` /
`useSSE`) — showing the live feed is more delightful than any canned message
rotation because it's true ("honest machinery", PRODUCT.md principle 5).

**Build.** In `StageRunning`, render the last ~3 event lines for the running
stage as a small ticker under the progress bar: `font-meta`, `text-[0.6rem]`,
`text-ink-black/45`, newest line full opacity and older lines fading. New
lines may slide up 4px on arrival (CSS transition; instant under reduced
motion). **Inspect the store's actual event shape first** (what
`usePipelineStore` exposes, how events are scoped per stage/project) and
filter to human-readable progress events — raw JSON or error dumps don't
belong here. If the store doesn't retain events suitable for this, scope the
item down to a count-based line ("panel 7 of 32 — scene_03") derived from
`items_done` changes rather than threading new plumbing.

**Verify.** Run a dev-mode pipeline stage and watch the ticker; lines are
readable English, never raw payloads; component still renders fine with zero
events; `npm test` green (there are existing pipeline store tests —
`web/src/__tests__/pipelineStatusEvents.test.ts` — to keep passing).

---

## Explicitly out of scope (decided against)

- **Sound** — it's a work tool people run for an hour at a time.
- **Confetti / external animation libraries** — gold Burst stamps and
  `comic-pop` are the brand's celebration vocabulary; no new dependencies.
- **Motion on steady-state surfaces** (tables, sidebars, editors) and any
  entrance choreography on page load.
- **Personality in error/billing copy** beyond the warmth already present
  (e.g. `InsufficientCreditsDialog`) — the foreman stays calm around money
  and failures.
