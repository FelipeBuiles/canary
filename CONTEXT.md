# Canary — Domain Glossary

This file defines the project's canonical vocabulary. It is intentionally
implementation-free: runtime contracts, file paths, API routes, model choices,
and UI behavior belong in `docs/reference/`.

When a term conflicts with this glossary, stop and resolve the vocabulary
before changing code or documentation.

## Pipeline concepts

**Stage** — A discrete, resumable unit of the comic-making pipeline. A stage
has a named input/output contract, validates the artifact it owns, and may
pause for user review.

**Stage validation** — The blocking invariants and non-blocking issues evaluated
by the stage that owns an artifact. Finish independently preflights the book
but does not duplicate every upstream validator. A stage that blocks persists
its own verdict, including any recommendation, so the evidence outlives the
failed run.

**Invariant failure** — A provable violation of an artifact contract that
blocks advancement, such as broken source coverage, mutated lettering, or
incorrect OCR.

**Editorial issue** — An evidence-backed creative concern that cites affected
source and artifact IDs but is not presented as an objective quality score.

**Checkpoint stage** — A stage whose completed output requires explicit user
approval before the pipeline advances.

**Station** — A user-facing grouping of pipeline work. Stations are a product
concept; they do not rename or merge backend stages.

**Pages station** — Station 03, where the book adaptation is planned into
pages, complete pages are generated, and page revisions are reviewed.
_Avoid_: Panels station

**Auto step** — Pipeline work that runs without an approval decision and is
presented for inspection when useful.

**Draw stage** — The pipeline stage that exclusively generates complete comic
page revisions. It does not generate independently assembled production
panels.

**Brief stage** — The pipeline stage that proposes the adaptation brief and
turns it into an authoritative contract through user approval or editing. Its
Story-station review includes the Story Bible; Extract has no separate user
approval.

**Adapt stage** — The pipeline stage that creates the book-wide narrative
treatment, adaptation ledger, and one ordered book-level adaptation under the
approved adaptation brief.

**Plan stage** — The pipeline stage that translates the narrative treatment
and book adaptation into canonical ComicPages, including page allocation,
spread rhythm, page-turn intent, reading order, and semantic layout intent.
It allocates Adapt's complete lettering by citing lettering IDs; the wording
itself is copied from the adaptation and is never restated, so it cannot be
rewritten or shortened.

**Finish stage** — The final pipeline stage, which verifies and corrects page
renders, coordinates correction requests with Draw, performs production-safe
normalization, and exports the book. It does not repair artwork or lettering
pixels itself.
_Avoid_: Compose stage

**Story Bible** — The shared story understanding used by later pipeline work:
characters, locations, scenes, arcs, and props.

**Source unit** — A stable, sentence-aligned passage of the source novel used
to account for adaptation coverage. It retains exact offsets into the immutable
source and is never recreated by slicing scene text.

**Source scene** — An ordered editorial grouping that references a contiguous
range of source-unit IDs. It does not own a copied or independently sliced
version of the novel's prose.

**Adaptation brief** — The project-level statement of what the adaptation must
preserve or may transform, including story promises, themes, point of view,
tone, motifs, essential facts, protected language, and a target page range.
Canary may infer a draft, but it becomes authoritative only after the user
approves or edits it.

**Narrative treatment** — The book-wide adaptation contract owned by the Adapt
stage. It describes the causal spine, character and emotional arcs, reveals,
reactions, aftermath, and relative narrative emphasis before the ordered book
adaptation is written. It does not assign page geometry or final page counts.

**Adaptation ledger** — The record assigning every source unit an explicit
adaptation disposition and connecting retained material to adapted beats.

**Book adaptation** — Adapt's single ordered sequence of visual beats,
complete dialogue and caption wording, transitions, and source provenance
under the narrative treatment. It describes story content before that content
is allocated to canonical pages. Chapter or scene shards are storage only, not
independent creative artifacts.

**Visual anchor** — A stable physical description attached to a character or
location and used to preserve visual identity across generated images.

**Appearance state** — An authoritative visual condition for a character or
location, activated by an explicit adapted beat. Draw supplies the relevant
approved state references at page scope; it is not inferred from generated
panels.

**Layout plan** — Planner rationale and visual execution detail supporting the
canonical ComicPages. It is not a competing source for publishable page
structure or copy.

**Planned panel** — A panel-level record in a layout plan. It describes the
intended scene, semantic role, framing, shape, and other visual constraints.
Adjacent planned panels may cite the same adapted beat when they decompose it
into distinct source-supported visual moments; beat citations remain monotonic
and never return to an earlier beat after the story advances.

**Generation request** — A frozen, derived request compiled by Draw from a
specific ComicPage revision and its approved references. It is retained for
provenance, retries, and inspection but is not an independent creative source
of truth. References are supplied at page scope rather than through a
panel-to-panel image chain.

## Comic editing concepts

**ComicPage** — The canonical publishable specification of one comic page,
including ordered panels, exact lettering, reading order, narrative emphasis,
semantic layout intent, and page-level density intent. Exact panel coordinates
are optional author constraints, not mandatory planned structure. Universal
panel-count and word-count caps are not part of the canonical page model.

**Page render** — A derived visual realization of a specific ComicPage
revision. Text embedded in a page render is not canonical copy.

**Render analysis** — Derived observations about a page render, such as
detected panel boundaries, reading order, and recognized lettering. It is
validation evidence, not author intent.

**Lettering comparison policy** — The single named rule for comparing canonical
lettering with recognized lettering. It folds representation differences that
carry no meaning — quote and dash forms, ellipses, line breaks introduced by
the letterer, repeated whitespace — and nothing else. Case and wording
differences remain defects.

**Reading-order evidence** — Detected page geometry, not an OCR engine's own
observation sequence. Only geometry that places canonical lettering in a
contradicting order is a provable reading-order defect; an unexplained
sequence difference is an editorial issue.

**Panel crop** — A derived view cut from a page render for inspection,
accessibility, or diagnosis. It is not an independently generated asset or a
canonical input to page assembly.

**Bubble** — A speech, thought, or narration element placed on a comic page.

**Sfx** — A sound-effect element placed on a comic page.

**Page issue** — An evidence-backed user or validator concern attached to a
page-render revision. It may target a detected panel region or lettering item,
but correction always produces a complete new page revision.

**Primary ref** — The user's chosen canonical character reference used to
support consistent depiction.

## Project and generation concepts

**Project** — One comic production workspace, from source novel through export.

**Style template** — The project's active visual direction.

**Target language** — The language used for generated creative text in a
project.

**UI localization** — The language used for browser interface text. It is
separate from target language.

**Quality preset** — A named generation-quality choice that selects a coherent
set of model intents.

**Generation job** — An asynchronous unit of asset generation, such as a panel
or character reference regeneration.

**Labs run** — An independent model-experiment run. It is not a pipeline run
and does not advance project pipeline state.

## Historical terms

**Panels station** — Obsolete name for Station 03 from the panel-generation
workflow. The current station is Pages.

**Storyboard stage** — Obsolete compatibility projection from layout plans to
panel breakdowns. It is not part of the target pipeline.

**Direct stage** — Obsolete stage for compiling panel image prompts. Draw owns
compilation of derived page-generation requests in the target pipeline.

**Panel breakdown** — Obsolete panel-specific projection formerly produced by
Storyboard.

**Panel flag** — Obsolete review record from the panel-generation workflow.
Current review uses page issues.

**Panel acceptance** — Obsolete per-panel approval state. Pages are accepted by
default and reviewed by exception before one Continue to Book decision.

**Image prompt** — Historical name for an independently editable panel
generation instruction. Target generation requests are derived from canonical
ComicPages.

**Direct checkpoint** — Obsolete terminology for a former approval boundary.
Direct is not part of the target pipeline.
