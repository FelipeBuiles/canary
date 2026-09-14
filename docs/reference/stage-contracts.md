# Stage contracts

**Status: Current, September 13, 2026.** Implementation and tests are authoritative.
Each stage owns its file boundary. Server orchestration runs the explicit chain;
stages do not call one another. The CLI has only `init` and `serve`.

| # | Stage | Checkpoint? | Responsibility |
|---|-------|-------------|----------------|
| 1 | `extract` | No | Source document and Story Bible |
| 2 | `brief` | Yes | Approve adaptation intent and constraints |
| 3 | `style` | Yes | Select visual style |
| 4 | `cast` | Yes | Approve character, location, and prop references |
| 5 | `adapt` | No | Book adaptation, source coverage, exact lettering |
| 6 | `plan` | No | Canonical complete pages and lettering allocation |
| 7 | `draw` | Yes | Complete lettered images, OCR, issue review |
| 8 | `finish` | No | Provider-free preflight and PDF/CBZ packaging |

`state.py` and `stages/__init__.py` define ordering and gates. All routes below
serve under `/api/projects/{project_id}`: pipeline operations live in
`server/routers/pipeline.py`; page generation, saved-pixel text-check recovery,
correction, visual review, and render history live in `server/routers/pages.py`;
editorial decisions and story changes live in `server/routers/editorial.py`.

`TargetArtifacts` owns the active source, brief, adaptation, plan, Draw, and
Finish paths. `artifacts.py` owns Story Bible and Cast reference paths. Never
introduce alternate readers for legacy output shapes. Provider wire v3 is a
breaking cutover; current profiles and the local Codex runtime v6 execution
fingerprint reject incompatible saved requests rather than translating old wire.
Re-extract/regenerate affected output, or use a new project when an existing
edition is incompatible. There is no generated-artifact migration.

## User gates

The four stations are Story, Look, Pages, and Book; they group, not replace,
the eight backend stages. Story includes Extract/Brief; Look includes Style/Cast.
`POST /api/projects/` and `/api/projects/import-story` validate and save the
source, configuration, and initial state only. They return `status: created`;
they do not start generation or reserve credits. Story analysis starts only
after an explicit estimated action through `/run?stage=extract`. A failed
estimate can be retried without starting work.

Story approval saves the visible Brief draft before approving; a failed save,
invalid page range, or revision conflict must not approve an older saved value.
Local unsaved drafts are keyed by Brief revision and content SHA. Matching
drafts can restore locally; older drafts remain separately inspectable in a
labelled read-only text field, with copy/manual-copy recovery and confirmed
discard. They are never silently applied to a newer Brief.

Entering Cast does not spend. Starting or resuming missing references is an
explicit estimated action; Style's explicit Continue action may start Cast
before navigating there. Cast's estimate includes an initial cover, queued by
the server only after Cast succeeds and its identity references exist. Existing
cover attempts (including interrupted jobs recovered after restart) require an
explicit retry; entering a room never retries them. Approving Cast accepts the
estimated Adapt → Plan chain. Pages retains one Continue to Book decision,
not per-page acceptance.

### Cast reference corrections

Every significant character or location appearance opens its own revision controls.
State corrections use the entity-scoped instructed regeneration routes; their
instructions and images do not replace the main reference. Missing appearances
can be generated individually. Each paid action remains explicitly estimated
and confirmed.

Cast instruction bodies optionally accept `reference_assets` (project-local
`asset_type`, `asset_id`, optional `state_id`; up to three). **Add a reference**
reveals the optional picker. Attached thumbnails can be reviewed and removed;
the author describes how each should guide the change in the same instruction.
There is no mandatory reference operation: borrowing a detail, matching an
appearance, preserving continuity, or avoiding similarity all use this flow.

The rewriter receives each attachment's name, state label and visual anchor;
the renderer receives the actual image as instruction context. Attachment alone
never implies copying or differentiation. The owner's explicit art direction takes
precedence over generated appearance details, continuity guards and style defaults
for the targeted asset/state. Unrequested details and the reference format remain
stable. Source anchors and guards remain verbatim for provenance; they cannot veto
a requested redesign. Attachments never become edit parents.

Successful image metadata stores the applied art direction. Draw carries that
direction with the selected reference, so source descriptions do not undo Cast
edits. Failed drafts are not treated as approved art direction. Main and alternate
location references expose version history and reversible restoration, including
the corresponding image metadata; restoring a main reference marks dependent
states stale without automatically regenerating them.

Missing/unreadable images, unknown identifiers, self-attachments and reference
overflow fail before the rewrite spends credits. Accepted attachments are saved
with the instruction and reused by plain rerolls. An explicit empty list removes
them from the next correction. `reference_count` on the asset estimate includes
the selected additional image inputs. `reference_assets_supported` advertises
attachment support to the UI; unknown correction fields are rejected rather
than silently ignored.

Location corrections may distinguish layout, furniture arrangement, decor, and
architectural details/materials consistent with canonical facts. They are no
longer restricted to lighting/weather changes. Visual anchors and active-state
continuity guards remain verbatim and authoritative. These controls do not
establish that the resulting designs are visually distinct; that requires review.

## Authority through generation

### Extraction participation

Extract requires private `character_participation` evidence for candidate
characters and scene rosters: `direct_action` means physically staged action,
speech, or experience; `staged_recollection` means an embodied sequence in a
memory, diary, dream, testimony, or flashback; `background_only` means mentions,
biographical exposition, unseen speakers, or background photos/social images.
Retrospective narration alone does not exclude a staged participant, and a
mention alone does not authorize inventing one.

Each character/scene pair has one classification and a nonempty `source_quote`
found in the source with whitespace normalized only: words, punctuation, and
case remain significant. Missing, duplicate, or invalid evidence fails
validation. Scene rosters contain visual participants, not everyone mentioned;
background-only candidates and references are removed while relevant summary
facts remain. This evidence is discarded at the extraction boundary, not added
to the canonical Story Bible. `visual_anchor` remains the shared physical
identity authority, including species/anatomy; there is no separate species DTO.

### Adaptation and state authority

Adapt's bounded source requests keep complete scenes together when they fit the
unit and projected output limits. Oversized scenes may split; each authoring
prompt identifies the supplied opening/middle/closing fragment, full scene bounds,
and a read-only book scene outline. Whole-scene summaries are context, not a demand
to recreate the scene in each fragment. Prompts distinguish mentions, testimony,
recollections, and enacted events, and require only source-supported reactions;
scene participants do not imply mandatory dialogue.

Blueprint and story-repair request schemas express ledger exceptions as separate
closed alternatives for each disposition. Compression and visual motifs require
nonempty `adapted_beat_ids`; intentional omission requires an empty destination
array. Compression and omission require a nonempty reason. Prompts distinguish
literal destination IDs from prose ranges such as “beat_030 onward”; prose is
never parsed to invent destination links. Python validation additionally checks
whether a blueprint destination exists in the response before accepting its
checkpoint. Corrections retain unaffected beats and accounting decisions.

Locked-lettering generation has a separate authoring contract: the writer returns
copy, kind, speaker identity, source citations, and `presentation`. It does not
invent lettering IDs. The application validates complete locked-beat membership,
orders responses by the blueprint, and assigns unique local lettering IDs before
canonical validation; the book merge supplies final global IDs. It copies text,
provenance, and speaker decisions without rewriting them. The authoring field
`presentation` explicitly means onscreen/offscreen/narration/quoted_text/display,
never performance direction such as “listless” or “quiet, sincere”; it maps to the
canonical `delivery` field. Invalid presentation choices still require an authored
correction. Canonical checkpoints remain distinct from writer responses.

Adapt's lettering and story-repair request schemas constrain kind/delivery
pairs before generation: dialogue/thought use onscreen or offscreen, captions
use narration or quoted text, and SFX uses display. Onscreen speakers require
a known Story Bible character ID. Canonical validation still checks returned
and cached responses; invalid metadata is never silently reinterpreted.
Exhausted locked-lettering attempts retain their last parseable rejection under
`.checkpoints/adapt/lettering/<shard>/rejected.json`. Explicit Resume repairs that
exact payload within the existing request allowance; valid lettering checkpoints
keep their input keys and remain reusable. A successful repair removes the rejection.
Blueprint, locked lettering, and scoped story repair constrain source citations
to the assigned source IDs in their request schemas. Locked lettering retains
its blueprint structure; provenance is checked before its checkpoint is accepted.
Scoped story repair constrains beat, lettering, and ledger-exception citations. Both newly generated
and cached repair drafts pass that scope check inside the bounded correction loop,
before caching or splicing. An invalid cached batch keeps the reviewed candidate
active; Resume corrects invalid responses and reuses valid siblings. Neighbor
citations are never stripped or relabeled. Compression may still target retained
external beats while accounting only for source units owned by the repair.
Repairs must account for their complete source scope and retain requirement IDs
whose only realizing beats they replace. Missing citation/accounting metadata is
corrected without authoring duplicate events. Partial repairs receive the replaced
beats' exclusive requirement ownership, rather than the whole shard's obligations.

Adapt owns exact lettering. Plan assigns it to `ComicPage.content` and records
reading order and optional geometry. The two-pass global page map assigns every
lettering ID exactly once, in Adapt order, to a page carrying its owning beat.
Detail batches must preserve each page's exact lettering allocation, even when
one beat spans a batch boundary. The detail writer returns visual panels and a
page-level `lettering_placements` object: each locked lettering ID is one required
key with an authored 1-based destination panel number. Panels cannot return
lettering ID lists. Closed page-specific schemas require all assigned IDs and
forbid other pages' IDs; silent pages require an empty object. Compilation copies
canonical items to those exact destinations in locked order, rejecting missing
or foreign keys, nonexistent panels, and backward destinations. Canonical panel
beat citations combine the authored visual beats with the known Adapt owners of
its assigned lettering. A panel bridging two beats need not redundantly restate
both caption-owner links: they follow its exact authored word placement. This
does not claim that captions must be literally depicted. Foreign or backward
visual citations remain invalid, and the combined provenance still undergoes
the fixed-map ordering checks. Compilation never chooses a destination. Local repairs
receive the previous panels in the same writer format. Canonical page artifacts
retain their existing lettering contract; changed request schemas invalidate
only the corresponding response checkpoints. Map/whole-book author instructions may change global allocation; detail
instructions apply the same intent within the already fixed map and do not
authorize moving words between pages. A failed detail response is corrected with its
previous panels and explicit allocation errors before canonicalization. Plan
normalization derives identifiers and reading order; it never fills missing words,
deduplicates placements, or moves lettering between authored visual moments.
Each content item declares visible
`entity_ids` and an `appearance_states` map from entity ID to state ID. State
IDs are entity-scoped. Characters, locations, and props share state catalogs.
Plan's authoring inventory exposes entity IDs and nullable appearance-state IDs,
omitting Draw's storage identifiers such as `char_001:base`. A null state denotes
the main reference: retain the entity citation and omit its state binding.
Both whole-book and detail request schemas constrain entity citations and explicit
entity/state pairs to the approved inventory. Detail batches validate these
citations locally before merge and use the existing bounded correction attempt
for invalid output. Reference failures include canonical page/panel locations,
so final validation can route concerns to their owning batch. No unknown state is
silently dropped or mapped to a different approved appearance.
State conditioning uses explicit `changed_facets` and `replaces_identity`.
Preserve `visual_anchor` and `continuity_guard` verbatim through Cast and Draw.

Adapt's appearance changes carry forward until changed; explicit Plan state
citations remain authoritative for intentional earlier-state imagery. Plan
drafts author non-lettering `continuity_intent` for scene transitions, staging,
and held-object ownership. Canonicalization folds it into `ComicPage.layout_intent`
as ordered panel staging, not a new `PageContent.continuity_intent` field.

### Narrative review and flexible length

Brief's page range is a preferred scale, not a minimum or maximum allocation.
Plan preserves that target as metadata while allowing the actual book to be
shorter or longer. Exact lettering, source accounting, continuity, reference
capacity, and protected language remain enforced.

Before publishing Adapt, a separate structured editorial call reviews source
windows, including omitted units, alongside global beat summaries and neighboring
beats. Supporting source units accompany the exact beat and lettering provenance
in each detailed window. Identical ledger decisions are grouped losslessly for
transport. Review contract `narrative_v4` also supplies the exact lettering outside
the detailed window as compact `reader_context`, with no duplicate local copy.
Together these contain the full adapted text in global story order. Reviewers
must check earlier publishable words before requesting a repeated date, identity,
or causal explanation; later reveals do not automatically excuse earlier gaps.
Plan must also check when its page allocation presents those words. This adds
text to existing review calls, not another review/repair loop. Changes to distant
lettering invalidate affected review requests because reader knowledge is part
of their evidence; a content-hash change alone does not. Each silence/concentration signal
has one review-window owner with its complete sequence supplied. Lettering IDs
are valid evidence anchors and map to their own source units. Exact essential-event
and character-turn IDs supplied by the treatment are also valid citations. They
map to the source of beats claiming the requirement only when the finding has no
concrete beat, lettering, page, or source citation. Supplemental requirement IDs
do not broaden a concrete finding's repair scope. A wholly unclaimed requirement
without concrete evidence remains a book-wide concern. Invented IDs remain invalid
and diagnostics list them.
It checks
reader-visible context, repeated events, unsupported additions, and essential
development. Plan reviews the global map before detail in its
larger-book workflow and reviews actual canonical page candidates before
publication. Silence/SFX-only runs and disproportionate reuse of a beat are
computed questions that the reviewer must assess, not numerical quality scores
or automatic bans on silent comics. Defects cite known artifacts and carry
repair ownership; Plan cannot repair missing Adapt wording by inventing copy.

The review request schema scopes signal IDs, assessment count, evidence IDs, and
repair-stage ownership to the supplied window. Plan page citations use the absolute page IDs actually
supplied in the detailed window (including pages added for owned signals), not
window-relative numbers; other global pages are context and have their own
review windows. Incorrect citations receive a protocol correction before they
can route a story repair. With no signals, the assessment
array must be empty; the reviewer still checks the story and reports defects in
`findings`. Checklist entries for arbitrary beats, pages, or the ledger are not
substitutes for the detected signals. Duplicate assessments remain checked in
Python, with explicit missing, unexpected, and duplicate ID diagnostics.

Review contract `narrative_v4` separates advisory preferences from substantiated
blockers. Padding, pacing, emphasis, panel variety, and weak page turns never
block or trigger automatic polishing. Negative signal assessments are advisory;
they cannot manufacture a missing-context blocker. Advisory findings are saved
in the review record, stage validation, and accepted Adapt/Plan editorial notes,
and shown as optional notes in their reading views.

A substantive finding must state a concrete consequence and reader impact and
quote exact passages from their cited supplied artifacts. Contradictions and
invented events require at least two distinct cited artifacts; an indispensable
context gap requires at least one passage. An explicit requirement violation
must also name an approved requirement. A missing or unverifiable evidence claim
remains advisory. This raises the admission bar for blocking judgments without
claiming automated literary certainty. Structural invariants and malformed or
stale review checks remain blocking.

When a published Adapt script has an outdated or missing review, **Resume
adaptation** revalidates current source/Brief/Cast constraints and refreshes the
review of that exact script. It does not rewrite or renumber the script, change
its content hash, clear Plan checkpoints, or reset the cumulative work budget.
Review notes are saved in the review receipt and stage validation without
changing the published artifact. The Pages failure view offers this resume
action alongside the separate, destructive **Start adaptation over** action.
After refreshing Adapt, an already failed Plan requires an explicit retry;
the normal auto-chain starts only pending stages.

A stage attempt permits at most one narrative repair pass. Adapt repairs the
cited source scope. Plan repairs the compact map before detail, or the affected
detail batches after composition; a narrative map revision consumes that
allowance. It never escalates an unresolved detail finding into whole-book
regeneration. Schema corrections retain their separate bounded allowance.
Unresolved blockers stop with evidence and preserve the draft for explicit
review. Structurally valid Plan pages are retained in `plan/review_draft.json`
before narrative review, readable through `GET /plan/review-draft`; they never
become Draw authority. Successful publication removes that temporary draft.
The cumulative work ceiling still bounds all requests.

`TargetArtifacts` stores `adapt/adapt_review.json`, `plan/plan_map_review.json`,
and `plan/plan_review.json`. Required successful reviews are keyed by version and
input digest. Draw initialization, batch preflight, individual generation, and
correction preflight reject missing, failed, or stale Adapt/Plan reviews before
spend. Reading existing pages and OCR-only recovery do not require new narrative
review. Older projects need rerunning Adapt and Plan; no artifacts or request
hashes are migrated in place. A frozen pending image result is retained, never
authorization to silently redraw or release a reservation.

### Style and reference authority

Style curation uses typed `visual_logic`: `photographic`,
`realistic_illustration`, `stylized`, or `graphic`. Selection covers declared
portfolio roles rather than taking the first candidates. Without an explicit
author medium restriction, the selected portfolio must include photographic
and realistic-illustration options in distinct roles; an invalid portfolio
fails rather than silently dropping coverage. A restriction must quote the
author direction verbatim; story mood is not a medium restriction. Contrast
and wildcard directions must also honor that restriction.

Style proofs share one bounded scene roster and location across the generated
brief, deterministic fallback, and request compiler. Contextual mentions cannot
add subjects or crowds. Brief prose owns staging, not redesigned identities;
the compiler supplies each selected canonical `visual_anchor` exactly.
The v5 brief cache fingerprints the selected evidence, model, and prompt;
stale cache entries are not reused. Candidate styles render the same selection.

Full-page style samples and Draw retain the selected lettering and page-framing
standards. Cast reference prompts use only the art-rendering projection, not
page lettering, borders, or gutters. Style and reference authority are not
disposable scene prose: approved style imagery owns rendering, not depicted
people, objects, text, or layout. Canonical subject references own compatible
identity/state facets, not their original rendering style. Active-state anchors
override explicitly changed anatomy, age, proportions, wardrobe, location, or
object facets; a provider-safe rewrite must not reverse a state or restore
missing anatomy. Textual style notes remain secondary to an approved style
reference; a generated-neighbor variation instead owns its declared changed
rendering facets.

Character style calibration is a distinct `style_calibration` asset: a
text-free lineup of canonical Cast subjects in anatomy-appropriate natural
postures, not an invented human/adult roster or a lettered page sample.
It supplies rendering evidence only, never another character's identity, and
is not a required Cast approval output. Reuse requires its current producing
request; otherwise the approved style proof is the fallback conditioning image.
Sunburst uses the same approved proof directly for every Cast character and state
reference, instead of generating or reusing a shared character lineup. Saved
Sunburst project evidence showed the lineup leaking its identities into other
characters. Other models retain shared calibration to prevent per-character or
per-species style drift; the exception does not apply to the whole GPT Image route.
Sunburst character generation fails before submission if the proof is absent,
rather than silently falling back to text. Cast prompts explicitly keep one
medium and degree of realism across human, animal, and creature subjects.
An image-edit transport never licenses discarding the selected style image.
Canonical character sheets also receive the Story Bible's age, wardrobe, and
distinguishing details alongside the exact protected visual anchor.

Extraction requires explicit `changed_facets` and `replaces_identity` for every
returned appearance state and rejects two activations for one entity at the
same scene/beat. Its prompt includes plot-critical silent/nonhuman actors even
when they occur in only one scene, and explicit returns to the canonical look
when a later source passage depicts an earlier lived-time flashback. These
prompt requirements do not prove semantic completeness of a generated roster.

Style references are rendering-only, not implicit edit parents. Only explicitly
selected edit-parent references authorize preserving an existing composition
or applying an edit. Canonical text outranks mistaken parent pixels: restoring
canonical species, identity, age, or anatomy is a valid correction, not permission
to redefine those facts. State anchors still own explicitly changed facets.

Location state plates use `plates/{location}/states/{state}.png`, with
instructions beside them as `{state}.instructions.jsonl`. Reads, writes, and
lineage scans stay scoped to that location; there is no migration or alternate
reader for the old location-state artifact layout.

### Frozen pages and corrections

Draw compiles selected references, distinct subject labels, panel assignments,
geometry, reading order, and exact lettering into one frozen request. Excess
references fail before submission. Less-graphic framing retains identity
references. An edition keeps its selected model/profile; a different current
profile rejects without rewriting the existing edition. No reset or migration
action is provided. Request hashes identify input but do not guarantee
provider deduplication. Ambiguous image submissions are not automatically retried.

Local Codex development routing can bind a first Draw edition to a separate
experimental complete-page profile when its image route and OCR are both
subscription-selected. It permits five total ordered image inputs, including a
correction parent; all required authorities and authored lettering remain intact.
Queue all prepares every page before any hold or enqueue. Subscription quotes,
holds and debits are zero; observed cost and actual image backend remain unknown.
This does not relax the production Vertex profile; both use current wire contracts.
Codex native PNG dimensions are authoritative: 1696×2528 is composition intent,
not an output guarantee. Finish preserves native bytes and per-page PDF/CBZ
geometry, rejecting incompatible fixed/custom trims rather than cropping.
See [Codex development capabilities](codex-dev-capabilities.md) for setup and limits.

Adapt beats cite Brief requirement IDs without repeated requirement prose.
Missing citations remain validation failures rather than being inferred from
keyword overlap. Explicit beat entity scopes allow bounded Plan context.

OCR is blind to canonical copy. It checks visible lettering and observed order;
it does not establish visual identity, object fidelity, or scene correctness.
Page-render and preview HTTP responses use `private, no-cache`: an Adapt/Plan
restart can reuse page and render revision numbers in a new edition. The client
uses `delivery=2` URLs to bypass responses previously cached as immutable for a
year. Derived previews remain cached on disk within the active edition.
An optional reference-aware visual check records up to eight editorial findings
and uncertainty independently of OCR; it does not certify a page as correct.
A saved visual report is reusable only while the canonical page, exact render
bytes, approved reference bytes, review model, prompt, and schema still digest
identically; otherwise the report is null until a matching paid review lands.
Canonical lettering is immutable for Draw: wording changes return to
Adapt/Plan, never image correction. Missing or stale OCR evidence blocks Finish
but is not an artwork defect or an instruction to redraw. Recover checks on
saved pixels; paid artwork correction is a separate action for an identified
change. A correction is one explicit
author-selected batch — linked tracked issues and/or new manual
instructions — where each change carries an editable instruction plus
normalized page-fraction marks (origin top-left), an optional author note, and
explicitly selected source passages. Bookwide beat summaries, treatment spine,
appearance chronology, and continuity travel with every correction;
author-selected passages always arrive in full and only auto-gathered page
units are budget-truncated. Preview compiles, validates lineage (canonical
revision/SHA, parent render revision/bytes), and estimates cost without
spending or mutating issues; manual issues are created deterministically
inside the reserved job. Submit enqueues exactly one full-page job; stale
lineage is rejected, unselected open issues remain, and the exact submitted
correction (edited instructions, annotation notes, manual note) is served back
per render revision — null for initial draws. A generated visual fix stays
`revised` (visually unverified) until a person confirms; only OCR-proven text
fixes may resolve by OCR. Finish checks artifact and render lineage, OCR,
state citations, unresolved issues, dimensions, and packaging. It does not
invoke a creative model.

Correction lineage retains the exact original producing prompt in
`PageRenderCorrection.retained_instructions`, then carries prior correction
instructions and notes forward. These are subordinate, non-lettering historical
constraints: current canonical copy, approved identity/state/style, and author
pins remain authoritative, and current changes supersede conflicting earlier
changes. Historical subject/image bindings are not current attachments, extra
panels, or copy to render. This preserves deliberate depiction, including
less-graphic intent, without adding a top-level `depiction` field to
`FrozenPageGenerationRequest` or rehashing stored requests to invent one.

## Editorial workflow
This workflow is a backend API contract; the Pages room exposes no storyboard
or story-change UI.

Adapt/Plan findings are revision-scoped: keep/reopen dispositions apply only
while both the editorial revision and the individual issue fingerprint still
match; drifted evidence resurfaces as open. A story-change preview persists
only a resumable proposal with truthful whole-book impact and a projected
(never billed) chain estimate — no generation, no canonical mutation. Apply
requires an explicit accept of that cost and impact: Adapt reruns Adapt+Plan,
Plan reruns Plan only, always whole-book; selected pages focus the
instruction, never bound regeneration; Draw is never auto-queued and stays
separately estimated. Stale previews (client echo or canonical drift) are
rejected; applied proposals go read-only.

### Pages review context

`/project/{project_id}/pages` carries `page=N`, `review=page|visual|checks`,
`filter=all|needs-review|drawing|failed`, and optional
`reading=adaptation|page-plan`. The URL is authoritative; project-scoped
session storage restores review context only on an entry without query
parameters, and does not persist the reading drawer. Book findings link to
the affected page and review view.

The exception queue contains pages with `open` or `revised` issues; a new
render alone does not clear it. Filters are pressed-state buttons, not tabs.
Drawing and failed filters reflect current page artifacts and failure phase,
not historical job failure alone; a current completed check supersedes an old
failed job. Saved artwork with incomplete checks is presented as an analysis
recovery, not an image-generation failure. Drawn and checked counts are separate.
Next-unresolved navigation wraps through remaining flagged pages. Reading
Adaptation/Plan stays read-only.

## Recovery and costs

Adapt resumes by revalidating its saved failed candidate against the unchanged
source and approved brief. Source-backed protected quotations receive explicit
quoted-caption delivery; exact protected book titles do not require terminal
punctuation. Missing terminal punctuation alone produces a nonblocking
`possible_clipped_display_text` editorial issue: headings, date cards, chants,
and quoted phrases may intentionally omit it. Unclosed quotation marks and
delimiters remain blocking. Warnings preserve the exact lettering and cited IDs.
A valid recovered candidate with current successful narrative-review evidence
is persisted without a model call; structural validity alone does not waive review.
Changed source/brief identities or a new story instruction prevent this reuse.
A structurally valid candidate with a completed failed editorial review can also
resume as repair input, without publication. Its exact review digest, instruction,
and completed review-request receipts under the original review model must match
the current source/Brief/Story Bible work lineage. Selecting a different model
preserves this story progress; subsequent review requests remain keyed to the
selected model and cannot reuse another model's verdicts. Resume retains that improved candidate
instead of reconstructing the original draft. Its unchanged review windows remain
cacheable. Missing/stale receipts fall back to the existing generation checkpoints;
no old review is promoted to successful evidence. A typed candidate checkpoint
also binds the unpublished candidate, its source partition, and any pending repair
batch to these exact authorities. It is saved before review so transport failures
or an exhausted work limit do not force a return to initial generation. Completed
unchecked repairs can be reconstructed from exact original-model prompt hashes
before the next model reviews them. Resume estimates omit initial story generation
when this saved work is eligible; repair and re-review remain uncertain scenarios.
Repair inputs use the same
global beat and lettering IDs cited by the reviewer, and repartitioning rejects
cross-shard literal provenance or reordered shard intervals. Explicit compression
may cite another shard's globally identified beat.
An interrupted repair batch reuses its completed siblings only when
every existing sibling matches the exact model and prompt hash. Only the missing
sections generate again. A complete response batch interrupted before candidate
validation also remains reusable. A separate receipt records the exact batch's
completed validation outcome, including narrative review when structural checks
pass. Only checked complete batches require a fresh repair namespace, so saved
responses survive a splice crash without trapping retries in a rejected answer.
Repair scope starts from affected source scenes, then includes all source units
and literal ledger claims carried by any beat being replaced, including its
lettering. Overlapping beats and intervening beats in authored order expand that
scope until stable, producing one contiguous replacement interval. Repair
prompts include up to three retained beats on either side with their exact
lettering, including neighbors across shard boundaries. This read-only context
establishes which events already occur outside the replacement; it grants no
additional source ownership or permission to rewrite those neighbors. The splice
preserves the repair's authored sequence and the untouched prefix/suffix; earliest
source citation is not used to sort narrative order. StageRuntime logs cited and
closed source counts per shard before repair generation. The splice rejects
a partial scope before replacing anything; it must not keep a caption claim
while deleting the caption that realized it. All sibling repairs are applied to
the book together before any identifiers are rebased. Compression-only links
resolve to retained or replacement beats across shards; replacement identity
must be supported by source provenance or the repair's explicit ledger decisions.
Unknown destinations, cycles, and deletion of a referenced beat without a
supported replacement are rejected. A nearby beat is never an invented fallback.
Resolved compression remains subject to narrative review.
The Pages error screen offers Resume adaptation with the existing estimate and
confirmation, plain-language checks, and collapsed technical evidence.

Paid project actions require `Idempotency-Key` (nonblank, at most 200 characters).
The persistent request journal keys replay by verified account, HTTP method/path,
and action key; the fingerprint covers query and canonical body (multipart file
bytes, not its random boundary). A saved response replays without dispatch, even
while drained, with `Idempotency-Replayed: true`. Different input returns 409
`idempotency_conflict`; an admitted request without a recorded response returns
409 `idempotency_indeterminate`. Missing keys return 400
`idempotency_key_required`. Inspect status, jobs, and saved output before explicit
recovery; never automatically retry a paid submission or replace its uncertain
receipt with a fresh key. Request hashes are not provider-side deduplication.

Browser unresolved-action receipts survive reload and are account/input-scoped.
Account changes abort tracked requests, reject late responses, replace the query
cache, disconnect pipeline events, and clear style-job and credit-resume state.
Do not reuse another account's cached project, balance, job, or action state.

`GET /jobs` (also `/generation-jobs`) returns `{"jobs": [...]}` for the verified
account/project, optionally filtered by repeated `ids` query parameters. It
combines live jobs with persisted observations. After restart, previously
queued/running observations become failed/recoverable, not automatically queued.
Complete-page Draw jobs include `is_current_page`: true only when their request
hash matches a retained frozen request for the current page revision and content
hash. Pages ignores jobs marked false for failure badges and drawing status;
the job history remains available after Adapt/Plan restarts.
Pipeline status and saved artifacts remain recovery authority. Pipeline and
style SSE broadcast to independent bounded subscribers: 128 events of in-process
reconnect history and a 256-event queue per subscriber, dropping oldest overflow.
This is not a durable event log or a substitute for fetching status/jobs.

Cast, instructed Cast rewrites, style direction/suggestions/samples/validation,
and covers use credit reservations before paid work. Instructed Cast enqueues
a durable job before rewriting instructions; its reserved job owns the text
rewrite and subsequent image work. Submission reports queued, not an immediately
applied correction. Rejected rewrites still settle recorded text usage.
Cast UI retains the instruction draft and exposes pending/running and durable
failure/rejection observations across navigation; a queued receipt or old visible
image is not new-image success. Failed work requires explicit recovery, not an
automatic paid retry.

Holds have a process owner and a one-hour lease, renewed every 30 seconds;
work checks ownership/expiry before starting. Startup requires the reviewed
lease/settlement SQL migration before
admission. Only expired, never-started holds are automatically reclaimable.
Started-expired holds, legacy unowned holds, and ambiguous settlement require
operator reconciliation, not global startup/reset release. Ledger settlement
may replay its identical idempotent database operation; this is not a retry of
the paid provider request.

Project-lookup connection failures may retry the read once on the shared live
database pool. Request recovery must not close or replace that client: admitted
credit jobs and the reservation-renewal thread retain it across browser requests.

Rejected reruns (including missing style or reservation denial) preserve state
and artifacts. Admitted non-Draw replacements still use stage-owned cleanup:
there is no general rollback on later failure. Draw replacements retain render
revisions and recover the original unfinished action before accepting new input.

Adapt and Plan retain input-keyed paid responses outside stage cleanup. Keys
include model and generation input; reused responses still undergo validation.
Adapt/Plan also keep a typed cumulative work journal under `.checkpoints/<stage>/work`.
Every admitted structured request consumes a slot, including interrupted or
unresolved work; matching checkpoint hits consume none. Source/approved-intent
and stage-authority identities scope the journal across resumes. A model change
or a fresh repair namespace cannot reset it. Adapt defaults to twice its projected
clean call graph (treatment, blueprint, lettering and reviews). Plan defaults to
at least 64 structured requests, or four times its projected map/detail and review
call graph if larger. Plan projects the greater of one page per adapted beat and
the upper advisory page target, leaving room for bounded corrections and explicit
resumes. These are cumulative work allowances, not retry counts or cost
estimates; the existing per-request and global repair-attempt bounds still apply.
An explicit positive
`Config.narrative_max_calls` overrides the ceiling. Changing that configured
limit retains the prior call count. Exhaustion reports `generation_work_limit`
and preserves completed checkpoints; ordinary Resume cannot grant more slots.
The explicit **Start adaptation over** action (`POST /run?stage=adapt&rerun=true`)
archives Adapt and downstream outputs, exports, and Adapt/Plan checkpoints and
work journals under `.checkpoints/restarts/<attempt-id>/`, with the prior state.
It preserves source, approved Brief, selected Style, Cast, and retained editorial
directives. Credits must be reserved before archiving; archive failures restore
moved files. The new attempt receives the configured/default work allowance;
past usage and charges remain recorded. `GET /estimate?stage=adapt&rerun=true`
quotes fresh Adapt work without cached-output discounts. This quote covers Adapt
only: Plan is estimated and reserved after the new script passes validation,
then runs automatically. Draw still requires a separate user action.
This counts structured requests, not exact provider submissions or dollars:
JSON repair and transport recovery retain their own existing bounds. Journaling
starts with newly admitted work; historical calls are not retroactively imported.
Reported/estimated costs, unknown outcomes, and subscription funding remain
separate in this journal; it does not debit user credits.

Text streaming preserves provider error events even when HTTP status is 200 or
an error follows syntactically complete JSON. Such responses fail before parsing
or checkpoint publication, with request ID, source scope, finish reason, bounded
provider diagnostics, and stream counters retained. Failed text calls preserve
reported usage; missing usage remains unknown under the default billing policy.
Before the first answer, substantive reasoning deltas count as generation
progress for the 900-second inactivity guard. Role metadata, empty reasoning
fields, and SSE comments do not. The 1,800-second total stream ceiling still
applies, including continuous reasoning. Reasoning never becomes answer text or
completed-answer character counts; a response with reasoning but no answer still
fails. Timing logs identify the event, model, and source scope and count reasoning
events without logging their text. This follows the provider's separate
[reasoning stream fields](https://openrouter.ai/docs/guides/best-practices/reasoning-tokens).
Structured generation can retry a genuinely empty answer once, sharing its
existing JSON-recovery attempt allowance and retaining known prior usage.
Explicit provider errors, refusals, and empty output at the token cap do not
enter that retry path. `retry_invalid_json=False` also disables empty-answer
recovery for callers that own durable raw-response recovery. Image submission
retry policy is unchanged.

Adapt estimates use the lettering prompt and known blueprint content, exclude
matching clean-generation checkpoints, and price a full scoped repair scenario
plus re-review instead of a flat percentage. Unknown outputs and future review
cache hits remain estimates. Adapt/Plan credit confidence is `variable`; quotes
and reservations are not a hard provider-spend ceiling.

Draw durably saves paid image bytes/provenance in `.pending`, then publishes
the render with an `.unfinished` identity marker. Recovery retains the original
frozen request, parent revision, and usage call IDs through publication/OCR
failures; the unfinished marker clears only after successful operation completion
and, for queued jobs, post-settlement acknowledgement. A visible render alone
does not prove settlement or completion. Resume that original action rather than
redrawing or submitting a different correction.

OCR requests an explicit root schema with `lettering` and `panels` arrays.
Every text observation includes its exact text, comic-lettering/incidental-text
role, and normalized `box`; panel coordinates are directly on each panel
object. This is a blind observation request, never a canonical-copy prompt.

The complete provider response text and finalized usage are durably saved
before JSON parsing or schema validation, separately from versioned raw OCR
observations and derived analysis. A malformed response or persistence failure
does not trigger a hidden paid JSON-repair retry. Saved evidence is replayed
through current parsers/validators provider-free; invalid cached evidence may
still fail and does not authorize replacing it with another paid call.
Missing downstream artifacts alone do not justify new OCR. Proven panel-order
contradictions block; uncertain order remains nonblocking editorial evidence
for visual review, not proof of a defect or of correctness.

### Saved-pixel check recovery

`GET /pages/checks/estimate` returns per-page recovery status, active
`render_image_sha256`, `paid_pages`, and the sum of independently rounded
OCR-only credit quotes/holds. Status is `undrawn`, `stale_render`, `checked`,
`cached_evidence`, or `requires_ocr`; `cached_evidence` indicates available
evidence to validate, not guaranteed successful recovery.

`POST /pages/checks/recover` defaults to `{"allow_paid": false, "renders": {}}`:
revalidate saved evidence, skip pages needing a paid call, and never generate
images. Paid OCR requires explicit `allow_paid: true` plus `renders`, a map
from page number to the approved active image SHA-256. Missing or changed
selections return `selection_changed`; undrawn/stale renders are not repaired
by this endpoint. Each page reports its outcome, so one failure does not
discard successful checks on other pages.

Both bulk recovery and `/pages/{page_number}/analyze` use the shared page
operation lock. Cache replay and active-image lineage checks occur inside it,
before credit reservation: successful cached recovery reserves and spends
nothing, even at zero balance. Only absent reusable OCR evidence, with paid
permission, reaches an OCR-only provider call on the existing image. Saved
bytes must match render lineage. None of these actions redraws, verifies visual
identity, or guarantees provider success; an OCR failure leaves the saved image
available for inspection and recovery.

Stage estimates include page references but exclude optional OCR; Cast estimates include state
references. Provider usage and credit settlement remain distinct from estimates
and stage-progress totals. Missing usage is not evidence of zero provider cost.

Read-only immediate quotes are distinct from the full-stage rerun estimate:

| GET route | Quoted work |
|---|---|
| `/pages/{page_number}/generate/estimate?depiction=canonical` | One undrawn page and compiled references, without OCR; `less_graphic` is also supported |
| `/pages/{page_number}/analyze/estimate` | Text-check recovery of an existing render: zero for cached evidence, otherwise OCR only; never redraws |
| `/pages/generate/estimate` | Only pages without saved render provenance, including references but not OCR |
| `/pages/checks/estimate` | Per-page readiness and total OCR-only quote for missing checks on saved pages |

These routes validate prerequisites but neither submit jobs, reserve credits,
nor mutate generation artifacts. `estimate_credits` is the projected charge;
`reserved_credits` is the temporary hold, not an extra charge. The remaining-page
quote sums independently rounded per-job estimates and buffered holds; rounding
one aggregate can understate the required credits. `/estimate?stage=draw`
still estimates every planned page for a full-stage rerun, even when some
already have renders. Show estimates as `~N credits`, not guaranteed prices
or completion times.

After a top-up, the insufficient-credits dialog refreshes the balance but
does not replay the action automatically. A retained action requires explicit
Resume once the balance covers its hold; without a retained action, return
to the original control. Do not turn an ambiguous paid submission into an
automatic retry.

`GET /api/projects/{project_id}/provider-usage` reconciles provider events and
artifact call IDs, including failures and unknown costs. Book's Dev Content
view shows recorded cost sources separately from user credit charges. Optional
visual review uses `/pages/{page_number}/visual-review` and its `/estimate`
endpoint. Restart the gateway after changing its retry configuration.

## Book readiness and package recovery

`GET /export/preflight` reads persisted Finish evidence. Its package readiness
requires a current validator version and saved package files whose resolved
paths remain inside the project, byte sizes match, and SHA-256 digests match.
Missing, unsafe, or damaged packages require a preflight refresh; an old
download URL is not readiness evidence. Package reuse also requires matching
edition, production settings, canonical page, and render identities.

`POST /export/preflight` retries provider-free checks without creating packages,
retaining valid packages when their inputs still match. Explicit export/rebuild
uses `/export/?format=pdf|cbz` (`force=true` for rebuild), reruns Finish, and
packages saved pages without generating artwork or spending credits. Book
distinguishes technical blockers, unresolved review issues, and accepted
editorial decisions, with links back to Pages.

Text review is optional and advisory. Missing, stale, invalid or mismatched OCR
evidence does not block Draw approval or export and never proves that saved
artwork needs replacement. Draw and correction jobs do not run OCR. Preflight
only reads retained analysis and never repairs or buys OCR; explicit Pages text
review handles that boundary. Automatic text findings remain reviewable, are not
preselected for redraw, and do not require acceptance before export. A missing
check stays unchecked; successful packaging does not verify wording.

Book's persisted package list supports “ready to download” across refreshes;
the edition-ready cue reports package creation, never browser download
completion. Neither successful preflight nor packaging guarantees model
output quality.
