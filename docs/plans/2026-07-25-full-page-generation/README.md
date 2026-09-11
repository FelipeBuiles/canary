# Full-page generation — implementation plan

**Date:** 2026-07-25
**Status:** Historical migration plan. Branch, sequencing, and implementation
instructions below describe the July migration, not current agent workflow.
The original Ticket 09 acceptance checklist is retained for reference; its
outstanding items require revalidation against current evidence.
**Design:** ADRs 0003-0015 in [`docs/adr/`](../../adr/) — the dated design
document was removed once its decisions were recorded there.

## Purpose

Implement the accepted full-page pipeline directly, without migrations,
feature flags, panel fallbacks, dual artifact reads, or backward-compatible
stage aliases.

Implementation work belongs on `render-full-pages`, created from the agreed
clean base. The prototype branch is evidence, not merge material. Reuse
production concepts deliberately; do not merge prototype runners, provider
experiments, paid outputs, or aliases wholesale.

The plan is retained as the implementation record. The remaining work is
hardening and launch evidence, not a second architecture or a compatibility
migration.

## Sequencing

```text
00 contracts
  → 01 source + brief
    → 02 book adaptation
      → 03 global page plan
        → 04 complete-page draw
          → 05 page issues + corrections
            → 06 finish + export
              → 07 backend cutover + deletion
                → 08 Pages UI cutover
                  → 09 end-to-end hardening + docs
```

| Ticket | Outcome |
|---|---|
| 00 | Target schemas, artifact ownership, and validation vocabulary exist without changing the active pipeline. |
| 01 | Extract writes immutable source units; Brief is the single Story checkpoint. |
| 02 | Adapt writes one source-accounted book adaptation with complete lettering. |
| 03 | Plan writes global canonical ComicPages without templates or scene-local pagination. |
| 04 | Draw compiles and submits one frozen complete-page request per page revision. |
| 05 | OCR, render analysis, page issues, and complete-page correction revisions work. |
| 06 | Finish preflights, normalizes, and exports without changing creative pixels. |
| 07 | The backend atomically switches to eight stages and deletes the legacy panel pipeline. |
| 08 | The frontend switches from Panels/Compose to Pages/Book and deletes legacy rooms and editors. |
| 09 | Cthulhu regressions, end-to-end tests, documentation, and authorized visual acceptance complete the migration. |

## Global implementation rules

1. Add the focused failing test before each behavioral change.
2. Preserve unrelated user work in the dirty worktree.
3. Do not write compatibility shims or project migrations.
4. Do not add a runtime feature flag or operate both rendering paths after
   Ticket 07.
5. Never paraphrase a `visual_anchor`.
6. Never silently truncate or rewrite canonical lettering.
7. No final-art provider call may exist outside Draw.
8. Every Draw result is a complete page revision.
9. No generated page becomes a reference authority for the next page.
10. Do not make paid model calls without explicit user authorization after
    presenting the estimate.
11. Keep model names and capability selection in configuration/profile code,
    not prompt templates.
12. Update current-contract documentation only when the implementation
    actually changes.

## Ticket 00 — Target contracts

### Scope

Create the target domain models and typed artifact access without registering
the new pipeline yet.

### Production work

- Add models for:
  - `SourceDocument`, `SourceUnit`, and source-scene ranges;
  - `AdaptationBrief`;
  - `BookAdaptation`, treatment, adapted beats, lettering items, and ledger
    entries;
  - semantic `ComicPage` revisions;
  - invariant failures and editorial issues;
  - page capability profile;
  - frozen page-generation request;
  - page-render revision, render analysis, and page issue.
- Replace canonical ComicPage fields that encode mandatory panel boxes,
  compose-only bubbles, and panel-render lifecycle.
- Add target artifact path/read/write functions.
- Define content hashes and revision/staleness rules.
- Keep the new modules unregistered until their producer stages exist.

### Tests

- Model round trips and invalid schemas.
- Verbatim source and lettering preservation.
- Revision invalidation.
- Semantic layout with optional pinned geometry.
- Validation result categories with no numeric score.
- Artifact paths contain no fallback reads.

### Exit criteria

- Every target artifact has one owner and one typed read/write path.
- No new model imports legacy `Screenplay`, `PanelBreakdown`, or `LayoutPlan`.

## Ticket 01 — Immutable source and Brief

### Scope

Replace copied scene text with source-unit references and add the Brief stage.

### Production work

- Refactor Extract to:
  - normalize and store the immutable source once;
  - segment sentence-aligned units with exact offsets;
  - create primary source-scene ranges;
  - validate full ordered coverage.
- Remove quote-based scene slicing and independent `scenes/*.txt` ownership.
- Implement Brief inference, editing, page-range selection, approval, and
  invalidation.
- Present Story Bible and Brief through one backend approval contract.
- Make Extract automatic and Brief a checkpoint.

### Tests

- Mid-word and mid-sentence boundaries fail.
- Offset/text mismatches, gaps, overlaps, and reordered ranges fail.
- Context references do not change primary ownership.
- Brief cannot become authoritative without approval.
- Changing the approved brief invalidates Adapt and downstream artifacts.

### Exit criteria

- The historical Cthulhu broken source boundary is impossible to serialize as a
  valid Extract output.
- No target stage reads a copied scene text file.

## Ticket 02 — Book-level Adapt

### Scope

Replace per-scene screenplays with one ordered book adaptation.

### Production work

- Implement the narrative-treatment and book-adaptation prompt contracts.
- Generate ordered adapted beats with complete dialogue/caption wording.
- Populate one ledger disposition for every source unit.
- Carry narrative function, source provenance, protected language,
  transitions, reactions, aftermath, and appearance-state changes.
- Use the approved page range for proportional adaptation without assigning
  pages.
- Implement Adapt-owned invariant validation and evidence-backed editorial
  issues.
- Estimate and record text-model cost through StageRuntime.

### Tests

- Every source unit has exactly one disposition.
- Compression and omission require reasons and valid destinations.
- Protected language survives verbatim.
- Trailing clipping and incomplete display text fail.
- Appearance-state chronology and transition continuity validate.
- A Cthulhu fixture flags the missing reaction/aftermath pattern as an
  editorial issue.

### Exit criteria

- Adapt writes one `adapt/book.json`.
- There are no per-scene screenplay outputs in the target code.

## Ticket 03 — Global page Plan

### Scope

Create canonical pages from the ordered book adaptation.

### Production work

- Implement global page allocation and page/spread rhythm.
- Carry adapted beat IDs and exact lettering unchanged into ComicPages.
- Record page-turn roles, reading order, emphasis, density, and semantic layout
  intent.
- Allow scene transitions within pages and across page turns.
- Validate the target range and report an evidence-backed recommendation when
  more pages are required.
- Remove templates, universal caps, deterministic panel splitting, exact
  geometry defaults, fixed character positions, and scene-local pagination
  from the target planner.
- Write `plan/book.json` plus revisioned `plan/pages/page_NNN.json`.

### Tests

- Every adapted beat is allocated once and in order.
- Lettering is byte-identical to Adapt output.
- A page may bridge source scenes.
- Exact coordinates are absent unless pinned.
- Sparse/standard/dense intent does not impose universal panel counts.
- Peak, Release, reveal, and aftermath fixtures produce inspectable page rhythm
  and issue evidence.

### Exit criteria

- Plan can produce the complete Cthulhu page sequence without reading
  `LayoutPlan`, layout presets, or per-scene screenplays.

## Ticket 04 — Complete-page Draw

### Scope

Build the only production final-art path.

### Production work

- Add the complete-page capability profile and book-edition selection.
- Implement page-scoped reference resolution from approved anchors,
  references, and appearance states.
- Compile a frozen request from one ComicPage revision.
- Adapt the proven Vertex multimodal/Nano Banana Pro transport for production.
- Persist immutable request, reference hashes, output, usage, latency, and
  lineage.
- Route estimates, credit reservation, execution, retry, and cancellation
  through the existing credited-job lifecycle.
- Require one fixed model/profile for the edition.
- Do not implement panel generation or provider fallback.

### Tests

- Prepared request equals submitted request.
- All required visual anchors are verbatim.
- References and uploaded bytes have one order.
- Changing page revision or selected reference bytes changes request identity.
- Unselected diagnostic data does not.
- The provider adapter returns one complete page and cannot return a panel
  production artifact.
- A provider/model without complete-page capability is rejected before cost.

### Exit criteria

- A mocked Draw run produces one page revision and full provenance with no
  dependency on panel prompt, panel aspect, panel store, or Compose assembly.

## Ticket 05 — Render analysis and page correction

### Scope

Validate generated pages and replace panel review with page revisions.

### Production work

- Implement OCR extraction and exact canonical lettering comparison.
- Store observed panel regions and reading order as derived render analysis.
- Implement page issues with optional region, lettering, beat, source, entity,
  and appearance-state targets.
- Add instructed/targeted correction requests where the selected profile
  supports them.
- Ensure every correction returns a complete page revision with parent lineage.
- Route requested copy changes to Adapt and replan affected pages; Draw handles
  only render fidelity to the current canonical copy.
- Keep pages accepted by default; summarize unresolved issues before Continue
  to Book.

### Tests

- Missing, invented, duplicated, misspelled, or reordered lettering blocks.
- Punctuation normalization follows an explicit canonical policy.
- Detected regions never become canonical geometry.
- A correction supersedes but does not overwrite its parent render.
- An issue target may be a region, but no replacement panel artifact is
  created.
- Invariant failures cannot be deliberately accepted.

### Exit criteria

- Cthulhu page 34's exact lettering can be verified against its ComicPage.
- Page revision history and issue resolution are fully reconstructable.

## Ticket 06 — Finish and export

### Scope

Replace Compose with provider-free final preflight and export.

### Production work

- Implement Finish stage and artifact paths.
- Reuse export packaging and production normalization only where they do not
  assemble or alter creative content.
- Validate active page order, revision validity, OCR status, cross-page
  appearance state, dimensions, bleed, color profile, unresolved issues, and
  export packaging.
- Emit correction requests to Draw for creative failures.
- Delete deterministic creative correction, bubble overlay, replacement-panel
  assembly, and HTML comic-page rendering from the target path.

### Tests

- Finish cannot call an image provider.
- Finish cannot change lettering or artwork pixels except approved
  production-safe normalization.
- A stale or invalid page blocks export.
- Deliberately accepted editorial issues are recorded in preflight.
- PDF/CBZ order and page dimensions are correct.

### Exit criteria

- A valid set of page renders exports without reading panel images or Compose
  page assembly data.

## Ticket 07 — Atomic backend cutover and deletion

### Scope

Switch the active backend to the target contract and remove the old backend.

### Production work

- Set stage order to:
  `extract, brief, style, cast, adapt, plan, draw, finish`.
- Set checkpoints to:
  `brief, style, cast, draw`.
- Update registry, clean cascade, state, auto-chain, rerun invalidation,
  credits, events, status, routes, exports, and project summaries.
- Replace screenplays/layout/storyboard/direct/panel/compose APIs with the
  target Brief, Book Adaptation, ComicPage, Draw, Page Issue, and Finish APIs.
- Delete backend panel pipeline modules, artifacts, models, routes, and tests
  identified in the design.
- Do not recognize old stage names or old project state.

### Tests

- State contains exactly eight stages.
- Invalid old stage names return unknown-stage errors.
- Rerunning each stage invalidates exactly its target downstream artifacts.
- Auto-chain stops at Brief approval and pre-Draw.
- Credits reserve per complete page, including correction attempts.
- No production import reaches deleted panel-generation or assembly modules.

### Exit criteria

- Repository search shows no production route or registry entry for
  `storyboard`, `direct`, `compose`, panel acceptance, or panel flags.
- The backend test suite passes without compatibility fixtures.

## Ticket 08 — Pages UI cutover

### Scope

Make the four stations accurately represent the target backend.

### Production work

- Story:
  - combine Story Bible and Brief review;
  - add page-range editing;
  - remove Extract approval.
- Look:
  - preserve style selection and cast approval.
- Pages:
  - rename Panels;
  - show Adapt/Plan exceptions before generation;
  - display complete page thumbnails and revisions;
  - add page-issue creation and resolution history;
  - provide one Continue to Book action.
- Book:
  - rename Compose;
  - show Finish preflight and export.
- Remove AdaptRoom, ShotPlanRoom, DirectRoom, Compose routes, panel detail
  regeneration, panel acceptance, panel flag, bubble-overlay, panel-layout,
  and panel-reframing interfaces.
- Update English, Spanish, and French copy in the same change.

### Tests

- Station mapping and status-event tests.
- Story approval and Brief editing.
- Pre-Draw issue exception behavior.
- Page generation, revision, issue, and Continue to Book flows.
- Finish preflight and export.
- No machine vocabulary outside Dev Content where still applicable.
- Responsive and accessibility checks for page gallery and issue flow.

### Exit criteria

- Users see Story, Look, Pages, and Book only.
- The UI never implies that a production panel can be independently accepted,
  generated, replaced, or assembled.

## Ticket 09 — End-to-end hardening and documentation

### Scope

Prove the migration, remove remaining dead concepts, and update current docs.

### Production work

- Add a deterministic Cthulhu regression corpus covering:
  - immutable source boundaries;
  - adaptation-ledger coverage;
  - complete narration;
  - approach/Peak/escape/Release/aftermath rhythm;
  - exact page lettering.
- Add a small second fixture with a scene transition inside a page.
- Run backend and frontend test suites, lint, type checks, and builds.
- Search for and remove dead panel/Compose terminology and code.
- Update AGENTS.md, reference docs, API docs, station docs, and current
  screenshots only after implementation matches.
- Remove any remaining superseded panel-era design documents rather than
  preserving stale future guidance.
- With explicit authorization and a presented cost estimate, run the final
  Nano Banana Pro visual acceptance corpus.

### Visual acceptance

- correct page and panel order;
- exact lettering;
- approved identity and appearance states;
- intended style;
- readable navigation;
- appropriate page density and page-turn behavior;
- output dimensions and print normalization;
- correction produces a coherent complete revised page.

### Exit criteria

- All deterministic checks pass.
- Authorized visual evidence meets the complete-page capability gate.
- Current documentation describes only the eight-stage target.
- The old panel pipeline is deleted, not deprecated.

## Standard verification

Backend:

```bash
rtk uv run --directory novel_to_comic pytest -q tests/<focused-test>.py
rtk uv run --directory novel_to_comic pytest -q
rtk uv run --directory novel_to_comic ruff check src tests
```

Frontend:

```bash
rtk npm --prefix web test
rtk npm --prefix web run lint
rtk npm --prefix web run build
```

Repository checks:

```bash
rtk rg -n 'storyboard|direct|compose|panel_acceptance|panel_flags' \
  novel_to_comic/src web/src
```

Remaining matches must be intentional historical text or unrelated ordinary
English usage, not active pipeline concepts.
