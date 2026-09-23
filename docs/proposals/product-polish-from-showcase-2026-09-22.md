# Product polish and fixes suggested by the "Any style" showcase

Proposed · September 22, 2026 · written after building the 65-second promo
(`showcase/video/src/v2`, record in [EDIT.md](../../showcase/video/EDIT.md)).

Building the video meant driving the real product hard: 22 custom style directions
typed into the composer, one uploaded reference, a page revision, lettering edits
and three project translations. This document records what that exposed. It is
meant to be picked up in fresh sessions, so each item says why (evidence), what to
build, where the code lives, and how to know it is done.

## Implementation status (September 22, 2026, same day)

Done in the working tree, with provider-free tests. There was no visual pass in a signed-in browser.

- **§0:** verified. `_supported_saved_selections` (commit `fbca23c`) lets every project
  open. Retired project choices show as "Retired model" in project settings, and the
  account default is used instead. Inventory: Call of Cthulhu, The Egg and The Most Dangerous Game
  still store retired API models.
- **A1:** after a custom proof lands, one vision call on the visual-review model fills
  `display_label` and the descriptive fields. It is best effort, priced in the direction estimate
  and never overwrites an author's label. `PATCH /styles/{id}` renames or hides a proof. `label`
  stays as it was because it is part of the stable suggestion id.
- **A2:** Grid / Flip / Wall in the Look room.
- **A3:** single directions queue beside other proof jobs; admission and index assignment
  happen under `production_lock`. `is_suggesting` gates batches, and `is_generating` still drives polling.
  Remaining limit: the very first direction (while the Style stage is `running`) still blocks new directions.
- **A4:** All / Yours / Suggested filters, reversible Hide with a "Hidden (n)" row, and Yours sorted newest first.
- **A5:** `components/ui/motion.tsx` (`Stamp`, `usePress`, `useArrival`): the style-selected stamp,
  proof press, the one-time whole-book pull-back (`WholeBookReveal`) and the PRINTED export stamp.
- **A6:** `components/ui/Loupe.tsx` on proof cards and the page view. The lettering editor keeps its own zoom.
- **A8:** a WIPE comparison mode with a one-time auto-sweep per revision pair.
- **A9:** `POST /lettering/locale` switches, with no charge, to languages that are already
  stored. The chips appear inside Project language. Still open: a preview-only language toggle in the page editor.
- **A11:** the resize hit area sits outside the box, "Confirm placement" replaces
  "Save lettering" while review is pending, and the gallery shows a "Needs placement" badge.
- **A7 (September 23):** Pages → page detail has a read-only **Source** tab backed by
  `GET /pages/{n}/source` (`page_source.py`). Passages are the page's beat source units plus
  lettering citations. Lettering is panel-level: the verbatim words are highlighted, or the whole
  cited unit when the copy paraphrases it. Ledger `depicted`/`visual_motif` units are beat-level and
  point at every panel on the page that carries the beat. Hovering or focusing a highlight outlines its
  panel(s) only when the current render's text check has OCR panel boxes tied to planned panels, either
  through matched lettering or through a proven reading order whose panel count equals the plan's.
  Plan and Draw store no canonical panel geometry (`pinned_geometry` is unused). Pages without a
  text check show no outlines. Stale lineage (source→Adapt→Plan) is rejected with a rerun instruction.
  **Later:** panel-level depiction would need Plan to cite source units per content item.
- **B1:** audit is clean. Durable jobs already run on the admitted `Config` snapshot, and only the
  translation recheck re-read disk (already patched).
- **B2:** `lettering_translation` has its own per-account lane and dispatch lock. Payloads carry
  `waiting_for_other_project`.
- **B3:** root cause was visual review requiring the *current* draw adapter. It now validates against
  the edition's own profile (`validate_review_request`). Drawing still refuses retired profiles.
- **B5:** fresh editions already composite without editor saves (existing test). The real failure
  was engine drift (v9→v10 in `a918055`). Composites now reflow in memory without saving, and placement review is requested.
- **B7:** the reader slider announces "Page N of M".
- **Not started:** A10, A12, B4 (each needs planning), and B6 (read-only check: failed proofs
  already show "Try sample again" behind an estimate).

**Evidence labels:** *Verified* = reproduced or read in code during this session.
*Observed* = seen once in the running app, not reproduced. *To verify* = plausible;
check before building.

**Ground rules for any follow-up session**

- Read `AGENTS.md` first. The user manages dev servers: never start or restart them.
- Test account: see the `reference_test_credentials` memory. Paid generations need explicit
  permission in that session.
- Marketing captures must never show credits, costs, free generations or the Codex adapter.
- `prefers-reduced-motion` must disable every animation proposed below (see `web/src/index.css`).
- DESIGN.md's "print physics" rule applies: motion is pressed, stamped, offset or
  screened. It never glows, bounces or floats.

---

## 0. Urgent: removing models from the catalog locks projects

**Status: Verified, uncommitted change in progress.** `novel_to_comic/src/novel_to_comic/model_catalog.py`
and `litellm/config.yaml` have local edits (likely another agent's) that remove
`gemini-3.8-flash`, `glm-5.3-flash`, `gpt-5.6-terra/luna`, `union-alpha`,
`deepseek-v4.1-flash` and three draw models. Projects whose `config.yaml`
`dev_model_selections` still name those models now fail **every** authenticated
request with 409:

| Project | Response |
| --- | --- |
| The Call of Cthulhu (the published flagship) | `409 Unsupported model for extract: gemini-3.8-flash` |
| The Egg | `409 Unsupported model for adapt: glm-5.3-flash` |
| dcc1-2 | 200 |

The path: `server/deps.py:get_project` → `account_config` → `validate_selections`
raises `ValueError`, and it's mapped to 409. Reading pages, opening the editor,
viewing proofs and exporting all require a project that still loads.

**Fix direction** (not a back-compat shim, since it's user recovery):
1. Loading a project must never depend on its model choices still being valid. Validate model
   selections only when admitting paid work (estimate/submit), not in `get_project`.
2. When a stored selection is no longer offered, the project should report it as
   `model_selection_unavailable: {stage: model}` in status. The UI then asks the
   user to pick a replacement for that stage. Never swap it silently. For `draw`,
   AGENTS.md's fixed-profile rule applies: an existing edition's draw model must not change,
   so a removed draw model means "this edition can't draw new pages"; reading it
   stays fine.
3. Add a test: a project with a removed text model still returns status, pages and
   composites.
4. Before landing the catalog edit, run a one-off inventory of `dev_model_selections`
   across the projects directory so the user knows which projects need a new choice.

Files: `server/deps.py`, `server/account_models.py`, `model_catalog.py`,
status payload in `server/routers/projects.py`, settings UI in `web/src/pages/ProjectSettingsPage.tsx`.

---

## A. Bringing the video's energy into the product

The video works because it shows **one scene, many looks**, then **one look, a whole
book**. The product has all the data for both moments but hides them behind a grid of
equal cards. The items below are ordered by impact per effort.

### A1. Name custom style directions (small, high impact)

**Verified.** Every author direction is stored with `label: "Your direction"`. Its
palette, line, lighting and story-fit fields say "As specified by the author
direction/reference." (`samples/style_suggestions.json` in `dcc1-2`: 18 cards named
"Your direction"). With more than one custom proof, the Look room and the Compare
panel can't tell them apart, and Compare shows three rows of placeholder text.

**Build:** after the proof image lands, run one cheap text call (image + the
author's words) that fills `label` (2–4 words, like "Claymation snowfall") and the
descriptive fields, marked `origin: user_text_image` so the UI can prefix "Yours ·".
Keep the author's original text verbatim, shown under the card as a quote. The user can rename inline.
Files: `server/routers/styles.py` (`create_style_direction` runner, after
`generate_sample_image`), `style_suggestions` model, `StyleRoom.tsx` card.
**Done when:** five custom proofs show five distinct names and Compare shows real
palette/line/story-fit text.

### A2. "Same scene" flip viewer and wall in the Look room (medium, signature moment)

**Why:** every proof is the same scene (`samples/style_sample_brief.json`), which is
exactly what makes comparison meaningful. It's also the video's most striking beat. Today
Compare is capped at three (`toggleCompare` in `StyleRoom.tsx`).

**Build:**
- **Flip mode:** full-height single proof with ← → keys, the proof name in a narrator
  tag, and a 3-card offset stack behind it (see `Flipbook` in
  `showcase/video/src/v2/scenes/Opening.tsx` for the exact look). Holding → flips
  quickly. "Select this style" stays reachable in the same spot.
- **Wall mode:** all proofs as a dense grid of same-size cards. Hover lifts a card with
  an offset shadow; click opens flip mode on that card.
- Keep the current grid as the default; add a segmented control Grid / Flip / Wall.
**Done when:** 30 proofs can be flipped through by keyboard in under 10 seconds,
and selection works from flip mode.

### A3. Let authors queue several directions (medium; aligns with "as many as you want")

**Verified.** `_assert_no_style_task` (`server/routers/styles.py:309`) returns 409
while any style operation runs, so each custom proof blocks the next for about 3 minutes.
The video needed a script that waited out each job. Real authors will just see a 409.

**Build:** accept direction submissions into the durable generation queue as
independent jobs (each with its own reservation), and show them as "Queued ·
Drawing · Ready" placeholder cards in the grid. Keep the existing guard only for
operations that really conflict (the full suggestion batch rewriting
`style_suggestions.json`). Watch `save_suggestions` merge races: append-by-id under
`production_lock`. Alternative with less risk: allow a small multi-line batch in the
composer ("one direction per line") that runs sequentially server-side.
**Done when:** submitting three directions back to back gives three queued cards and
no error.

### A4. Style room at scale: filter, hide, sort (small)

**Observed:** `dcc1-2` now has 32 proofs, and the grid becomes a long scroll with no
way to separate yours from suggested or to hide dead ends (the four off-target
proofs this session).

**Build:** filter chips "All · Yours · Suggested", a Hide action on a card (a
reversible flag, not deletion; hidden cards go to a collapsed "Hidden (n)" row), and
newest-first sorting for "Yours". Files: `StyleRoom.tsx`, a `hidden` field on the suggestion record.

### A5. Stamped checkpoints (small each; the "delight at checkpoints" principle)

Bring the video's motion vocabulary to the three real milestones. Reference
implementations are in `showcase/video/src/v2/fx.tsx` (`Stamp`, `Headline`,
`DotWipe`) and `theme.ts` (`press` easing: fast in, hard stop, no bounce).

1. **Style selected:** a red "✓ YOUR STYLE" rubber stamp slams onto the chosen proof
   at a slight angle, then stays as a badge (the video's `Pick` beat in `Commit.tsx`).
2. **A proof arrives:** the card seats with a 5-frame press (1.08 → 1) instead of
   fading in. Before it arrives, the placeholder uses the existing
   `FlowingDotsPlaceholder` Ben-Day screen.
3. **All pages drawn:** a one-time "It becomes the whole book" pull-back in the Pages
   room. The gallery briefly tilts into a perspective wall of every page, then
   settles (the `WholeBook` beat in `Commit.tsx`, done in CSS 3D transforms). Show
   it once per edition and store that it has been shown.
4. **Export ready:** a stamped "PRINTED" mark on the PDF/CBZ tiles. This overlaps the June
   delight review's "export ceremony"; do it together.

Build a tiny shared motion module in `web/src/components/ui/` (`<Stamp>`,
`usePress`) with a reduced-motion fallback that renders the final state immediately.

### A6. Loupe on proofs and pages (small)

**Verified:** the Cthulhu reference-driven proof is fine-grained pixel art that reads as a
painting at card size. The video needed a 2.5× nearest-neighbor inset to show it. The
page viewer and proof cards have no close inspection.
**Build:** hold Alt (or press Z) over an image to show a square loupe at 2.5×, with
`image-rendering: pixelated` when zoomed past 1:1. Reuse it in the Look room, the page
detail and the lettering editor.

### A7. "Where this page came from": source-to-panel pins (medium–large, unique)

**Why:** the video's opening, where manuscript phrases light up and pin to the drawing, is
the clearest expression of "your novel, your comic", and nothing in the product
shows it.
**Build (first version):** in Pages → page detail, a "Source" tab showing the
passage(s) that page adapts, with the words that became visible details
highlighted. Hovering a highlight outlines its panel. The data exists in Adapt/Plan
artifacts (beats, source passages, panel descriptions). *To verify:* whether panel-level
source spans are stored or only page-level. If only page-level, ship page-level
highlights first and add panel mapping later. No new generation is needed for version one.
Files: `page_planning.py` artifacts, `PagesRoom.tsx`, `ReadingDetails.tsx`.

### A8. Before/after wipe for page revisions (small)

**Verified:** `PagesRoom.tsx` already knows `compareRevision` (the parent render).
The video's strongest proof of control was a wipe from render 1 to render 2 on Carl
page 25, followed by a split detail.
**Build:** in the revision comparison, add a draggable vertical split (and a quick
auto-wipe when a revision first lands). Show the author's request text above it.
*To verify:* what the current compare UI already renders; extend it rather than
duplicating it.

### A9. Languages as instant chips, not a paid job (medium)

**Verified:** after a project has been translated, switching back to a language that
is already stored still goes through **Translate project → confirm drawer → a queued
job**. On this account that switch sat at `queue_position: 1` for about 2 minutes behind
another project's image job, although it translates 0 elements (`translate_count: 0`).
**Build:**
- When `translate_count === 0`, show the control as language chips (EN · ES · FR)
  that switch synchronously through a small `POST /lettering/locale` (no credits, no
  job, same snapshot and optimistic checks). Keep "Translate to…" for languages that
  still need generation.
- In the page editor, add a preview-only toggle to look at another stored language on
  this page without switching the project.
Files: `components/lettering/ProjectLetteringLanguage.tsx`, `lettering/translation.py`,
`server/routers/lettering.py`.

### A10. Language switch in the public reader (medium)

**Why:** editable editions now store several languages. The video's "Speak their
language" beat shows the same art relettered, and a reader should be able to do that too.
**Build:** for hybrid publications, publish every complete locale and add an EN/ES/FR
toggle in the reader header (`PublicBookPage.tsx`, `BookReader.tsx`,
`publicationTranslations.ts`). Only locales with no missing translations are offered.
*To verify:* the publication snapshot format and whether composites are prebuilt per locale.

### A11. Lettering editor ergonomics (small each)

- **Verified:** on a small balloon ("An egg."), grabbing the body often catches the resize
  handle, because the 38 px handle overlaps most of the box. Shrink the handle's hit area
  when the box is small, or place the handle outside the box's corner.
  `lettering.css` `.lettering-handle`.
- **Verified:** pages that need placement review show "Saved" next to an enabled,
  primary "Save lettering" button, which is contradictory. Label it "Confirm placement" in
  that state (`LetteringEditor.tsx`, `base.placement_review_needed`).
- **Observed:** The Egg's first-draft placements are often far from the speaker (pages 7–22
  are still untouched). The editor already says positions are "starting points, not
  detected empty spaces". See B4 for the quality fix. For polish, add a per-page
  "Needs placement" badge in the gallery so authors know where to look.

### A12. Landing page undersells custom styles (small copy + medium visual)

**Verified:** `web/src/pages/landingCopy.ts` step 02 says "Pick a visual direction,
then approve reference art". This is the same "two presets" impression the first video
gave. The hero is a static development sample.
**Build:** retitle step 02 around "Describe it, show it, or ask for six". Add a hero
loop: a muted, short, silent export of the flipbook section (4–11 s of the promo,
compressed WebM plus poster, with reduced motion falling back to the poster). Add a
"Same story, two books" strip using the two Carl editions. Update en/es/fr together.

---

## B. Critical areas and refactors

### B1. Jobs re-deriving config from disk (audit; medium)

**Verified bug, patched this session:** project translation failed every time with
"inputs changed" when an account model selection differed from `config.yaml`. The
job re-ran `prepare_translation` with `load_config(project_dir)`, while admission
used `account_config(...)`. The patch (`lettering/translation.py`, test
`test_account_selected_model_survives_the_job_snapshot_check`) overlays the admitted
`STAGE_FIELDS`. The same pattern (admit with account config, execute or recheck with a
raw disk load) may exist elsewhere.
**Do:** `rg "load_config\(" novel_to_comic/src` inside job `work()` closures and in
`server/job_execution.py`. For each hit, decide whether it should carry the admitted
config in the durable command snapshot instead. The deeper fix: make the
durable job command carry the admitted `Config` (it already serializes `command(...)`)
and have execution use it, so a recheck compares like with like.

### B2. One queue per user blocks cheap work behind image jobs (medium)

**Observed:** a zero-element translation in The Egg waited about 2 minutes as
`queue_position 1` while a style image job ran in another project (same user).
*To verify:* `app.state.user_generation_semaphores` and the durable queue ordering.
**Do:** give text-only and zero-cost jobs a separate lane (or a priority), so
lettering and translation stay interactive while images render. Surface the reason in
the UI ("Waiting for your image job to finish").

### B3. Visual review blocked on the flagship book (from the audit)

**Observed (showcase audit, September 22):** Cthulhu pages 31 and 40 show
`API 409: Frozen complete-page request does not match the selected profile`, and there are no
saved visual reviews. Re-check once §0 is resolved. It may share a root cause with
the model catalog churn (profile ↔ selection drift).

### B4. Speaker-aware first placement for editable lettering (large, quality)

**Why:** editable lettering's promise is "words where they belong". The first draft
currently places balloons from Plan's lettering reservations, which are "starting points, not
detected". On The Egg, most pages needed manual moves.
**Build (staged):** (1) use Plan's speaker and panel assignment to keep each balloon inside
its panel and near that panel's speaker side; (2) optionally, an inexpensive vision
pass on the base art to find faces or heads per panel for tail targets and empty regions.
Treat the result as seeds only. Never mark placement as reviewed automatically (AGENTS.md: a
revision alone must not verify).
Files: `lettering/service.py` (`seed_lettering`), `lettering/engine.mjs`, Plan artifact.

### B5. Composites require an editor save first (to verify, possibly critical)

**Observed before translation:** The Egg pages 7–22 returned
`Lettering needs layout. Open Lettering and save the page.` from
`GET …/composite/*` (`lettering/renderer.py:158`). Project translation later
laid out every page server-side (`resolve_lettering` in `translation.py`), so
server-side layout is possible. If a page never opened in the editor can't be
composited, the private reader, publication and export of a fresh editable edition
may fail or show gaps. **Do:** reproduce on a fresh editable edition (provider-free),
then resolve layout when seeding instead of deferring it to the browser.

### B6. Failed style proofs and failed pages need visible recovery (small)

- **Observed:** one custom direction failed with `image_tool_failed`. *To verify:*
  what the Look room shows for a failed custom direction. It should be a card with the
  author's text, the plain-language failure and "Try again" (a new estimate, never an
  automatic retry, per AGENTS.md).
- The Carl pixel edition has 36/39 pages drawn and 3 failed. Check that the Pages room makes
  "3 pages need another try" the obvious next step.

### B7. Small correctness and accessibility items

- **Verified:** the public reader's "Jump to page" slider is zero-based (value 38 shows
  page 39). Set `aria-valuetext="Page 39 of 44"` and consider 1-based values.
- **Observed:** the dev backend process was replaced mid-session (at 16:06) while style jobs
  ran. Queued jobs survived thanks to the durable queue. If the user didn't restart
  it, check the logs for a crash.

---

## Suggested order for the next sessions

1. **§0** (urgent, small): unlock projects; model selections validated at spend time only.
2. **A1 + A4 + A11 + B7** (one session, all small): names, filters, editor ergonomics, a11y.
3. **A5 + A6 + A8** (one session): shared motion module, stamps, loupe, revision wipe.
4. **A2 + A3** (one session): flip/wall viewer and queued directions.
5. **A9 + B2** (one session): instant language chips and the cheap-job lane.
6. **B1 + B5** (one session, provider-free): config-drift audit, server-side layout.
7. **A7, A10, A12, B4**: larger features; each deserves its own planning pass.
