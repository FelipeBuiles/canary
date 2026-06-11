# Four-Station Redesign — Implementation Plan

> **Status (2026-06-11): implemented** in a single pass — Phases 1–4 are live.
> Known deliberate gaps: "Apply all N safe fixes" (no auto-fix engine exists
> yet), login-page polish (P2), and `es`/`fr` i18n maps for the new EN copy
> (falls back to EN). Dev Content now defaults OFF; the old adapt/shot-plan/
> direct rooms are reachable only with it enabled.

Source: the `design_handoff_pulp_redesign` bundle (UX review + HTML prototype,
June 2026). The prototype is a **wireframe-level reference** — recreate the
flow and visual language inside the existing codebase using established
components, stores, and APIs. Where this plan diverges from the prototype, the
plan wins (we have product context the review didn't).

## Decisions already made

- **No backend stage reorder.** Stage order stays
  `extract → style → cast → adapt → plan → storyboard → direct → draw → compose`.
  The Story station's Script drawer shows a placeholder until `adapt` has run
  (which happens automatically after cast approval).
- **Stations are UI grouping only.** Backend stages remain discrete (AGENTS.md
  rule). The mapping lives in the frontend.
- **Flag-by-exception is confirmed.** Generation quality is usually good.
  Panels are accepted by default; flagging is the user action.
- **Free navigation.** Users can open any station; stations whose content
  isn't generated yet show a placeholder instead of being locked out.
- The "Spanish Look & Feel" P0 from the review was hardcoded Spanish literals
  in `StyleRoom.tsx` — **already fixed (2026-06-11)**. There is no locale-leak
  mechanism; UI language and project `target_language` are separate.

## Station ↔ stage mapping

| Station | Route(s) today | Backend stages | Gate / primary action |
|---|---|---|---|
| 01 Story | `extract` | `extract` | "Looks right — Continue" → approve extract, run style |
| 02 Look | `styles`, `cast` | `style`, `cast` | select style; "Continue" → approve cast → auto-chain `adapt→plan→storyboard→direct` |
| 03 Panels | `draw` (+ `adapt`/`shot-plan`/`direct` as drawers) | auto: `adapt`,`plan`,`storyboard`,`direct`; gated: `draw` | "Draw all panels" → run draw; "Accept all — Continue" → approve draw, run compose |
| 04 Book | `compose` | `compose` | Export (PDF/CBZ) inside Export tab |

Backend enablers that already exist: `STAGE_AUTO_CHAIN` (adapt→plan→storyboard→direct),
combined chain estimates from `GET /estimate`, per-panel acceptance storage
(`server/panel_acceptance.py`), the style gate (`style_selected`), and the
draw checkpoint before compose.

---

## Phase 1 — Backend enablement (small, do first)

1. **Make `direct` non-blocking.** Remove `"direct"` from `CHECKPOINT_STAGES`
   in `state.py:67`. The cast-approval chain then runs through `direct` and
   stops before `draw` (not in any chain). Update any state-machine tests.
   Keep the prompt artifacts and their endpoints — they feed the Prompts
   drawer and the panel modal's Prompt tab.
2. **Panel flags.** Add a per-panel flag store, mirroring
   `server/panel_acceptance.py` (same shape: project-scoped JSON, toggle
   endpoint, included in the images/status payload). Do **not** overload
   acceptance — acceptance semantics stay for "approve draw"; flags are review
   marks that must survive reload. Flags never block compose; they drive the
   "Review N flagged" secondary action and the flagged filter.
3. **Primary cast ref.** Persist a "primary reference" choice per character
   (config or cast artifact + small endpoint). Used by the Look station's
   reference sheet ("set as primary"). If `RefStrategy` already consumes a
   canonical ref, wire it there; otherwise store and surface it, and feed it to
   prompt assembly where applicable.
4. **Verify chain estimates.** `GET /estimate?stage=adapt` must return the
   combined adapt+plan+storyboard+direct figure for the Look approval bar.
   Already implemented — add/confirm a test.

## Phase 2 — Frontend chassis (the structural work)

5. **Station registry.** New `web/src/lib/stations.ts`: 4 stations with
   substeps, mapped to backend stages and routes; per-station "state tag"
   derivation (`✓ Done` / `● Review` / `Wait`) computed from existing status
   data. Extend, don't delete, `lib/uiStages` until the migration completes.
6. **SideNav rewrite** (`layout/SideNav.tsx` — the choke point). 4 station
   rows (number + Anton name + right state tag); current station expands its
   substeps (dot + label; auto substeps get an `auto · view` badge that opens
   the inspect drawer instead of navigating). Remove the sidebar "NEXT STAGE"
   CTA entirely — the approval bar replaces it. Footer keeps Settings/Dev mode.
   Reuse the existing `useApproveStage` / `runPipeline` / `findPendingStageAfter`
   wiring; move it into the approval bar hook below.
7. **ApprovalBar component** (new, one per station, fixed to the bottom of the
   content area): plain-language "Next: …" sentence, `~N credits · you have M`
   cost line, one primary button, optional quiet secondary (re-run verb).
   Build on the `useRunAction` seam + `useStageEstimate`. This absorbs: the
   sidebar CTA, per-room "Approve & Continue" buttons, and floating header
   RERUN verbs (RerunStageAction becomes the bar's secondary).
   Credits phrasing everywhere: `~26 credits` — kill `Est. N` and any
   "reserves up to N" copy (if overage must be stated: "won't exceed N").
8. **InspectDrawer component** (right-side, ~420px, scrim, read-only) with
   three variants reusing existing room content:
   - *Script* — scene cards with one-line summaries, beats on expand (from
     AdaptRoom's data).
   - *Shot plan* — per-scene panel thumbnail grid with plain-word labels
     ("Medium · eye level", never "P01 medium ·H") (from ShotPlanRoom's
     page-grid; the flat all-panels table is cut, see Phase 4).
   - *Prompts* — one row per panel: thumb + scene/panel + Shot/Cast/Setting/
     Light summary (from DirectRoom's breakdown).
   **Placeholder state** when the artifact doesn't exist yet: short copy like
   "PULP writes the script automatically after you approve the cast." Use the
   existing `StagePlaceholder`/`StateBlock` patterns.
9. **Demote old rooms, keep routes.** `adapt`, `shot-plan`, `direct` routes
   stay (deep links, Dev Mode), but SideNav stops linking them; gate the full
   pages behind `useShowDevContent`. `NavigateToRoom` maps pipeline position →
   station route.

## Phase 3 — Stations

10. **Station 01 — Story** (remodel StoryBibleRoom): two-column grid — Source
    card (kicker, Anton title, byline, italic opening excerpt with gold left
    border) + "What PULP found" card (N scenes / kept in story order, N
    characters · N places, ~N panels planned from config estimate; `Read the
    script ▸` chip → Script drawer). Keep the correcting-the-AI affordances:
    visible rename/edit on characters and places (pencil affordance), trait
    chips labeled "used in image prompts". No `char_001`/`loc_*` IDs outside
    Dev Content. Approval bar: "Next: PULP proposes five art styles drawn from
    your story · ~N credits" / secondary "⟳ Re-extract".
11. **Station 02 — Look** (StyleRoom + CastRoom under one station, switchable
    substep chips in the header):
    - *Style*: the card itself is the selection — remove SELECT buttons, click
      selects; selected card pinned first with red border + `✓ YOUR STYLE`
      ribbon. Keep `+ Suggest more · ~N cr`. Add the line "✓ Every sample above
      was previewed on your scene 001" (samples are rendered from the user's
      story — claim the wow). One-line descriptions + tag chips.
    - *Cast*: per-item `⟳ Re-roll · ~N cr` (regen-intake seam; charges only
      that item), inline `✎ rename`, description editable on focus, reference
      sheet with click-to-set-primary. Locations get the same per-item re-roll
      (symmetry). Plain names only.
    - Approval bar (cast substep): "Next: PULP plans shots and writes prompts —
      automatically · ~N credits (combined chain estimate)" / secondary
      "⟳ Re-extract cast". Style gate unchanged: can't continue without a
      selected style.
12. **Station 03 — Panels** (DrawRoom + PanelDetailModal):
    - Pre-generation: short explainer; approval bar primary `▶ Draw all panels
      · ~N credits`.
    - Generating: one status line ("Drawing panel N/M…") + one thin progress
      bar (stageProgress seam), panels fade in. **Delete**: donut, per-scene
      progress list (or collapse it when done), ALL/GENERATED/PENDING/FAILED
      tabs when single-state, and all zero-count buttons ("Generate all
      pending (0)", "Retry failed (0)") — hide actions whose object count is 0.
    - Generated: status sentence `M/M generated · N flagged by you`; filter
      chips `All · M` and `⚑ Flagged · N` (flagged chip only when N > 0).
      Panel card: ⚑ toggle on the caption row (instant, no confirm); flagged =
      red border + `⚑ RE-WORK` ribbon. Failed panels keep a visible failed
      state + retry (review was out of scope on errors; don't regress).
    - Panel detail modal: `Panel | Prompt` tab chips. Panel tab: shot summary,
      `⚑ Flag for re-work` toggle, `⟳ Re-roll (same prompt) · ~N cr`,
      "Describe a fix" textarea + `Regenerate with fix · ~N cr` (existing
      regen intake). Prompt tab: the structured Shot/Characters/Setting/
      Lighting breakdown from DirectRoom — this replaces Prompt Review as a
      stage surface. Nav: `← Prev / Next → / Next flagged ⚑`. Per-panel model
      picker moves behind Dev Content.
    - Approval bar: `Accept all — Continue →` primary (approve draw → run
      compose); `Review N flagged` secondary when N > 0 (opens modal at first
      flagged).
13. **Station 04 — Book** (ComposeRoom):
    - **One tab row**: `Pages | Script | Export` (50px header). Kill the
      `edit/export` top level + `canvas/script/issues` sublevel split.
    - Move PDF/CBZ buttons out of `ComposeHeader` into the Export tab. Header
      keeps: issues chip, undo/redo, `⟳ Regenerate ▾` (absorbs Rerun Compose /
      Match Lettering as menu items).
    - **Issues** become a drawer + triaged chip: `⚑ N need you · M suggestions`
      (severity already exists in `lib/issueEngine`: error → "need you",
      warning → "suggestions"). "Fix →" navigates to and selects the item on
      canvas (existing reveal path). Add `Apply all M safe fixes` for warnings
      that have safe auto-fixes; show the green confirmation state after.
    - *Pages tab*: page rail + bench + docked inspector (all existing). The
      inspector's position kicker is computed plain language (`middle · left`)
      — never `UNKNOWN (narration · left)`; unknown speaker resolves to
      narrator or prompts a fix. Source passage clamps to 2 lines +
      "Show full passage ▾". Footer: `Re-letter · ~N cr` + `Delete`.
    - *Script tab*: rows = kind+position chip (`CAPTION · TOP LEFT`) + text +
      `Reveal in canvas →`. Kill the "Bulk ops" panel: find & replace moves to
      the toolbar; translate moves to Export.
    - *Export tab*: "Your book" card (counts, include-lettering, `↓ Download
      PDF` primary + `↓ CBZ`) + "Translate the book" card (language select +
      `Translate · ~N cr`) — the **only** home for translation (remove it from
      Script bulk-ops; the project-creation `target_language` setting stays).
    - **Theme moves out of Export.** `comic_theme` selection joins the Look
      station (it re-renders the book; it must not sit at export time). Keep
      the settings-page control as the Dev/advanced path.

## Phase 4 — Cleanup & polish

14. Library: one status system per card (quiet chip, not green/red buttons);
    whole card resumes at current station; cut the Studio Telemetry widget.
15. New-project modal: Dev Mode toggle out of the happy path (Settings only);
    "Back" → "Cancel"; sample-story library gets per-story page+credit
    estimates; URL import gets a supported-sources placeholder example.
16. Vocabulary pass: Characters/Places headers, no entity/node/telemetry
    words, no IDs outside Dev Content, plain-word shot labels everywhere,
    standardized re-run verbs with scope + cost.
17. Cut the ShotPlan "ALL PANELS" flat table (Dev Mode at most) — it
    duplicates the page grid 1:1.
18. Confirmation moments for credit-spending actions: follow **DESIGN.md, not
    the prototype** — DESIGN.md's no-toast rule wins; use the existing
    Burst-box pattern, always naming the cost ("Re-rolling The Dreamer ·
    ~13 credits").
19. Login page (P2, optional): pair the product description with the
    headline; show one generated page on the dark half.

## Cross-cutting cautions

- **i18n churn:** EN strings are the translation keys; renaming copy orphans
  `es`/`fr` map entries in `web/src/i18n.tsx`. Update the maps in the same PR
  as each copy change, or accept fallback-to-EN and batch-update at the end.
- **Don't regress working machinery:** compose canvas fundamentals (bench,
  pointer-capture drag, % coords, `tail_x`/`tail_y` contract, keyboard
  shortcuts, undo/redo) are explicitly "keep". Same for cost-labeled actions
  and the style gate.
- **Square corners, hard offset shadows, red = action/selection only** —
  already the design system; treat prototype spacing as intentional but map
  colors/type onto the existing Tailwind tokens (`bristol`, `ink-black`,
  `hero-red`, `narrator-gold`), not new CSS variables.
- **Prototype is sample-data** — never copy `prototype/` code or `img/` assets.

## Suggested order of execution

1. Phase 1 (backend: checkpoint change, flags, primary ref) — unblocks all UI.
2. Items 12 (flag-by-exception + Panels cleanup) and 13 (Book flattening) —
   the review's P0s, each shippable standalone inside the current 8-room nav.
3. Items 5–9 (chassis: stations, SideNav, ApprovalBar, drawers) — the visible
   station merge.
4. Items 10–11 (Story and Look remodels).
5. Phase 4 polish.

Each step lands green: `cd web && npm test` + `npx tsc --noEmit`, and
`cd novel_to_comic && uv run pytest tests/` for backend changes; verify
station flows in the browser preview against a real project.
