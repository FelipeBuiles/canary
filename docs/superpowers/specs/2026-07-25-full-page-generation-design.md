# Full-page generation pipeline

**Date:** 2026-07-25  
**Status:** Accepted; ready for implementation planning  
**Supersedes:** all prior panel-generation, deterministic Compose, layout
template, panel-continuity, and nine-stage future-design documents

## Goal

Replace Canary's scene-local, panel-generated, deterministically assembled
comic pipeline with a book-level adaptation pipeline whose only production
rendering unit is a complete, fully lettered page.

The result must improve adaptation completeness and pacing while deleting the
legacy mechanisms that existed to reconcile independently generated panels.

## Product contract

The backend pipeline is:

```text
extract → brief → style → cast → adapt → plan → draw → finish
```

The user-facing stations are:

```text
01 Story → 02 Look → 03 Pages → 04 Book
```

User decisions are:

1. approve or edit the Story Bible and adaptation brief together;
2. select a style;
3. approve the cast;
4. review any pre-generation editorial issues and generate pages;
5. review generated pages by exception and continue to Book;
6. export after final preflight.

`extract`, `adapt`, and `plan` do not have separate creative approval gates.
Provable invariant failures block automatically. Evidence-backed editorial
issues are presented by exception before Draw spends credits.

## Core simplification

Source scenes, adapted scenes, planned panels, and generated panels are not
independent production pipelines.

- Source scenes are references into immutable source units.
- Adapt produces one logically ordered book adaptation.
- Plan allocates that ordered adaptation to canonical pages.
- Draw generates a complete page revision in one provider call or edit job.
- Finish validates the completed book and exports it without changing creative
  pixels.

Internal files or model calls may be chunked for context or storage, but
chunking is never exposed as competing creative authority.

## Canonical artifact graph

```text
immutable novel
  ↓
SourceDocument
  - ordered SourceUnits with exact offsets and verbatim text
  - SourceScenes referencing contiguous unit ranges
  ↓
StoryBible + approved AdaptationBrief
  ↓
BookAdaptation
  - narrative treatment
  - ordered AdaptedBeats
  - complete dialogue and captions
  - explicit appearance-state changes
  - source-accounting ledger
  ↓
ComicPage revisions
  - ordered content
  - exact unchanged lettering
  - reading order
  - page-turn and spread role
  - narrative emphasis and density intent
  - semantic layout intent
  - relevant entity and appearance-state IDs
  ↓
FrozenPageGenerationRequest
  - selected book-edition capability profile
  - verbatim anchors
  - approved page-scoped references
  - exact lettering
  - immutable input hashes
  ↓
PageRender revision + RenderAnalysis
  ↓
FinishPreflight + export
```

Only the latest valid `ComicPage` revision is canonical publishable intent.
Page renders, OCR, detected geometry, panel crops, prompts, validation evidence,
and provider responses are derived.

## Target artifacts

New projects use only these target paths:

```text
source/
  source.json
brief/
  adaptation_brief.json
adapt/
  book.json
plan/
  book.json
  pages/page_NNN.json
draw/
  book_edition.json
  pages/page_NNN/
    request_NNN.json
    render_NNN.png
    analysis_NNN.json
    issues.json
finish/
  preflight.json
exports/
```

`adapt/book.json` is one logical artifact. A later implementation may add
manifested shards if real context or storage measurements require them; the
initial implementation must not invent scene-level authority in anticipation
of that need.

There are no `screenplays/`, `storyboard/`, `direct/`, panel prompt, panel
render, panel acceptance, panel flag, or `compose/` target paths.

## Stage contracts

### Extract

Inputs:

- immutable original novel.

Outputs:

- `SourceDocument`;
- Story Bible;
- proposed source-scene groupings.

Required behavior:

- segment the source once into stable sentence-aligned units;
- retain exact character offsets and verbatim text;
- express scenes as contiguous source-unit ranges;
- require exactly one primary scene owner for every adapted source unit;
- allow labeled context references that do not affect primary ownership.

Blocking validation:

- offset/text mismatch;
- mid-unit scene boundary;
- unknown, inverted, overlapping, or gapped primary ranges;
- reordered or duplicated source units.

Extract has no approval checkpoint.

### Brief

Inputs:

- SourceDocument;
- Story Bible.

Outputs:

- proposed and then approved `AdaptationBrief`.

The brief contains:

- story promises and themes;
- point of view and narrator treatment;
- tone, ambiguity, motifs, and protected language;
- essential causal events and character turns;
- acceptable transformation level;
- desired emphasis;
- user-approved target page range.

The Story station presents the Story Bible and brief in one approval/editing
decision. Adapt cannot run until the brief is approved.

### Style and Cast

The useful contracts remain:

- one approved visual direction for a book edition;
- approved primary character, location, prop, and appearance-state references;
- verbatim visual anchors;
- explicit reference authority.

Panel geometry, panel prompt, and previous-render continuity concepts do not
enter these stages.

### Adapt

Inputs:

- SourceDocument;
- Story Bible;
- approved AdaptationBrief.

Output:

- one `BookAdaptation`.

The book adaptation contains:

- a book-wide narrative treatment;
- one ordered sequence of adapted beats;
- complete dialogue and caption wording;
- carrier choice for each retained source function;
- explicit reveals, reactions, consequences, transitions, and aftermath;
- explicit appearance-state change beats;
- source-unit provenance;
- an adaptation-ledger disposition for every source unit.

Allowed ledger dispositions include:

- `depicted`;
- `dialogue`;
- `thought`;
- `caption`;
- `visual_motif`;
- `compressed_into`;
- `intentionally_omitted`.

Compression and omission require a reason and the narrative function preserved
or intentionally removed.

Adapt is book-level. It does not expose parallel scene screenplays or require a
reconciliation subsystem. It uses the target page range to guide proportional
selection but does not assign pages or geometry.

Blocking validation:

- any source unit without exactly one coverage disposition;
- broken ledger destinations;
- missing essential causal events or protected language;
- incomplete dialogue or caption wording;
- accidental trailing truncation;
- inconsistent appearance-state chronology;
- incomplete transitions that make time, place, knowledge, or emotional state
  impossible to follow.

Editorial issues:

- questionable omission;
- duplicated information;
- weak visual substitution;
- rushed reaction or aftermath;
- lost narrator voice, ambiguity, motif, or thematic promise.

### Plan

Inputs:

- BookAdaptation;
- approved visual reference inventory;
- target page range.

Outputs:

- `plan/book.json`;
- ordered canonical `ComicPage` revisions.

Plan owns:

- actual page count;
- page and spread rhythm;
- page-turn reveals;
- assignment of adapted beats to pages;
- panel order and reading order;
- exact unchanged lettering allocation;
- narrative emphasis;
- semantic layout and density intent;
- page-scoped entities and appearance states.

Plan does not own:

- prose adaptation or copy rewriting;
- exact panel boxes by default;
- deterministic templates;
- universal panel-count or word-count caps;
- scene-contained pages;
- provider prompts.

Pages may cross source-scene boundaries. Exact coordinates exist only as an
explicit author pin or an empirically required capability constraint.

If a page is too dense, Plan redistributes complete beats across pages. If the
book cannot fit the approved range without damaging required content, Plan
reports the conflict and recommends a larger range.

Blocking validation:

- missing, duplicated, or reordered adapted beats;
- changed, clipped, or omitted lettering;
- ambiguous canonical reading order;
- invalid page/spread order;
- unresolvable page density under the selected capability.

Editorial issues:

- weak page turn;
- poor Peak/Release proportion;
- crowded or monotonous rhythm;
- confusing transition;
- emphasis inconsistent with narrative importance.

### Draw

Inputs:

- a specific ComicPage revision;
- one book-edition page-generation capability profile;
- approved page-scoped references.

Outputs:

- frozen request;
- complete page-render revision;
- render analysis;
- generation provenance and cost.

Draw:

- is the only stage that calls providers for final comic art;
- compiles one frozen request from canonical page intent;
- supplies anchors and references once at page scope;
- preserves exact lettering;
- produces a complete revised page for initial generation and every correction;
- never silently changes provider within a book edition.

There is no panel-generation or deterministic-assembly fallback. Unsupported
models fail capability selection. A targeted edit may localize its instruction
to a region, but its output is still a complete page revision.

Render analysis may include:

- OCR with lettering-item matches;
- observed panel boxes or polygons;
- observed reading order;
- identity and appearance-state evidence;
- output geometry;
- detected issue regions and derived panel crops.

Blocking validation:

- OCR mismatch;
- missing, invented, or duplicated lettering;
- requested content or page-order failure;
- wrong required appearance state;
- unusable output dimensions or corruption.

Subjective visual concerns become page issues rather than numeric quality
scores.

### Finish

Inputs:

- latest valid page-render revisions;
- their ComicPage revisions and render analyses;
- page issues.

Outputs:

- final preflight;
- normalized print assets;
- PDF/CBZ and other exports.

Finish:

- independently verifies page order, cross-page state, unresolved issues, OCR
  status, dimensions, bleed, color, and packaging;
- emits structured correction requests to Draw for creative failures;
- performs production-safe dimension, color-profile, metadata, ordering, and
  packaging normalization;
- never redraws artwork, replaces lettering, paints over regions, assembles
  panels, or calls an image provider.

## Validation model

Validation has two categories:

1. **Invariant failure** — a provable contract violation that blocks.
2. **Editorial issue** — an evidence-backed concern that cites source and
   artifact IDs and is reviewable by the user.

There is no aggregate adaptation-quality score, confidence percentage, or
weighted retry threshold.

Every stage owns validation of its artifact. A downstream stage may discover
an upstream problem, but it creates a correction request for the owner rather
than silently mutating the upstream artifact.

## Page review and correction

Pages are accepted by default.

A `PageIssue` contains:

- stable issue ID and type;
- page-render revision;
- evidence;
- requested correction;
- optional source-unit, adapted-beat, lettering-item, detected-region, or
  entity/state targets;
- status and resolution revision.

Resolving an artwork or lettering-rendering issue always produces a complete
new page-render revision. A request to change the words is an Adapt correction;
Plan then creates a new ComicPage revision before Draw renders it. The Pages
station offers one **Continue to Book** action. Unresolved editorial issues are
summarized and may be deliberately accepted. Invariant failures cannot be
overridden.

## Capability profile

The selected page model must have an explicit capability profile covering:

- complete-page generation;
- exact visible lettering;
- multiple image references and their ordering;
- instructed or region-targeted editing, if supported;
- output aspect and dimensions;
- pricing and cost estimation;
- reference and prompt limits;
- retry-safe request semantics.

One model/profile is fixed for an entire book edition. Changing the model
creates an explicitly regenerated edition; automatic provider mixing is
forbidden.

The initial production profile should use the proven Nano Banana Pro route.
Flash Lite remains unavailable for complete-page Draw until a new evaluation
meets the same acceptance criteria.

## UI

### Story

- Show Story Bible and inferred adaptation brief together.
- Allow brief editing and page-range selection.
- One approval action.
- Show source-integrity failures inline; they cannot be approved away.

### Look

- Preserve style selection and cast approval.
- Explain that approved references guide every complete page.

### Pages

- Replace the Panels station.
- Show Adapt and Plan as inspectable automatic work.
- Before generation, show only unresolved editorial exceptions.
- Generate and review complete page thumbnails.
- Open a page revision, its canonical intent, OCR, and issue history.
- Allow issue creation with optional region or lettering target.
- Remove panel acceptance and independently replaceable-panel language.
- One Continue to Book action.

### Book

- Replace Compose terminology with Finish.
- Show final preflight and correction requests.
- Retain export and production-format controls.
- Remove deterministic panel layout, bubble overlay, panel replacement, and
  panel reframing tools.

## Explicit deletions

Delete or replace, rather than adapt around:

- `s4_screenplay.py` and per-scene `Screenplay` artifacts;
- `s5_layout_plan.py` scene-local planning, templates, caps, and paginator;
- `s5_panels.py`;
- `s6_storyboard.py`;
- the `storyboard` and `direct` registry stages;
- `layout_planning.py`;
- panel breakdown models;
- panel prompt paths and editable prompt overlays;
- panel aspect, exact/master generation, crop-fit, and regeneration-status
  machinery;
- fixed character-side and per-panel position assignment;
- previous-panel continuity chains;
- post-hoc appearance-transition keyword pinning;
- panel store, panel acceptance, and panel flags;
- panel-generation lifecycle and fallback routing;
- deterministic HTML panel assembly and creative lettering overlay;
- Compose page-editing UI that moves panel images or rendered bubbles;
- Adapt, Shot Plan, Direct, and Compose legacy routes and rooms;
- API compatibility aliases and artifact dual reads.

Retain and reshape:

- Story Bible and verbatim visual anchors;
- approved references and appearance states;
- stage runtime, events, credited jobs, reservations, and usage provenance;
- provider transport and immutable request concepts that generalize cleanly to
  a page request;
- ComicPage revision and invalidation concepts;
- export packaging and production normalization;
- page navigation and issue UI patterns that do not assume panel assets.

## Non-goals

- Migrating existing project artifacts.
- Keeping old API or stage names alive.
- Supporting panel-by-panel generation.
- Mixing providers within an edition.
- Building a generic workflow engine.
- Assigning objective numeric scores to creative quality.
- Solving arbitrary digital-scroll or motion-comic formats in this migration.

## Acceptance criteria

1. A new project exposes only the eight target stages and four target stations.
2. The original source is completely and exactly represented by immutable
   source units and valid scene references.
3. Every source unit has one inspectable adaptation-ledger disposition.
4. Adapt produces one ordered book artifact with complete lettering and no
   scene screenplay authority.
5. Plan produces canonical pages globally without templates, universal caps,
   or scene-contained pagination.
6. Draw makes one complete-page provider request per initial page revision and
   never invokes panel generation.
7. OCR must exactly match canonical lettering before a page is valid.
8. A page correction creates a complete new page revision with lineage.
9. Finish cannot change creative pixels and cannot export invariant failures.
10. The Cthulhu regression corpus fails on its historical broken boundaries,
    truncated captions, and compressed aftermath, then passes with corrected
    artifacts.
11. Panel stages, artifacts, routes, editor concepts, and fallback code are
    absent rather than deprecated.
12. No paid visual evaluation runs without explicit user authorization and a
    cost estimate.
