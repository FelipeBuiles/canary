# Stage contracts

**Status: Current, September 9, 2026.** Implementation and tests are authoritative.
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
and a needed cover before navigating there. Approving Cast accepts the
estimated Adapt → Plan chain. Pages retains one Continue to Book decision,
not per-page acceptance.

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

Adapt owns exact lettering. Plan assigns it to `ComicPage.content` and records
reading order and optional geometry. Each content item declares visible
`entity_ids` and an `appearance_states` map from entity ID to state ID. State
IDs are entity-scoped. Characters, locations, and props share state catalogs.
State conditioning uses explicit `changed_facets` and `replaces_identity`.
Preserve `visual_anchor` and `continuity_guard` verbatim through Cast and Draw.

Adapt's appearance changes carry forward until changed; explicit Plan state
citations remain authoritative for intentional earlier-state imagery. Plan
drafts author non-lettering `continuity_intent` for scene transitions, staging,
and held-object ownership. Canonicalization folds it into `ComicPage.layout_intent`
as ordered panel staging, not a new `PageContent.continuity_intent` field.

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
experimental complete-page profile when `image-balanced` and OCR are both
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
punctuation. A valid recovered candidate is persisted without a model call.
Changed source/brief identities or a new story instruction prevent this reuse.
If validation still fails, an explicit resume reuses initial generation
checkpoints but gives the existing bounded repair pass a fresh checkpoint
namespace, so a cached failed repair cannot trap every subsequent retry.
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

Rejected reruns (including missing style or reservation denial) preserve state
and artifacts. Admitted non-Draw replacements still use stage-owned cleanup:
there is no general rollback on later failure. Draw replacements retain render
revisions and recover the original unfinished action before accepting new input.

Adapt and Plan retain input-keyed paid responses outside stage cleanup. Keys
include model and generation input; reused responses still undergo validation.
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

Stage estimates include page references and OCR; Cast estimates include state
references. Provider usage and credit settlement remain distinct from estimates
and stage-progress totals. Missing usage is not evidence of zero provider cost.

Read-only immediate quotes are distinct from the full-stage rerun estimate:

| GET route | Quoted work |
|---|---|
| `/pages/{page_number}/generate/estimate?depiction=canonical` | One undrawn page, compiled references and OCR; `less_graphic` is also supported |
| `/pages/{page_number}/analyze/estimate` | Text-check recovery of an existing render: zero for cached evidence, otherwise OCR only; never redraws |
| `/pages/generate/estimate` | Only pages without saved render provenance, including references and OCR |
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

Missing, stale, or invalid OCR evidence is a text-check readiness blocker, not
proof that saved artwork needs replacement. Preflight may revalidate cached
evidence but never buys OCR; explicit Pages check recovery handles that boundary.

Book's persisted package list supports “ready to download” across refreshes;
the edition-ready cue reports package creation, never browser download
completion. Neither successful preflight nor packaging guarantees model
output quality.
