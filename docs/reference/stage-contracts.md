# Stage contracts

**Status: Current, September 5, 2026.** Implementation and tests are authoritative.
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
`server/routers/pipeline.py`; page generation, correction, visual review, and
render history live in `server/routers/pages.py`; editorial decisions and
story changes live in `server/routers/editorial.py`.

`TargetArtifacts` owns the active source, brief, adaptation, plan, Draw, and
Finish paths. `artifacts.py` owns Story Bible and Cast reference paths. Never
introduce alternate readers for legacy output shapes: incompatible hashes or
schemas require rerunning the owning stage.

## Authority through generation

Adapt owns exact lettering. Plan assigns it to `ComicPage.content` and records
reading order and optional geometry. Each content item declares visible
`entity_ids` and an `appearance_states` map from entity ID to state ID. State
IDs are entity-scoped. Characters, locations, and props share state catalogs.
State conditioning uses explicit `changed_facets` and `replaces_identity`.
Preserve `visual_anchor` and `continuity_guard` verbatim through Cast and Draw.

Draw compiles selected references, distinct subject labels, panel assignments,
geometry, reading order, and exact lettering into one frozen request. Excess
references fail before submission. Less-graphic framing retains identity
references. An edition keeps its selected model/profile; model changes require
a fresh Draw edition. Request hashes identify input but do not guarantee
provider deduplication. Ambiguous image submissions are not automatically retried.

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
Adapt/Plan, never image correction. A correction is one explicit
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

## Recovery and costs

Adapt and Plan retain input-keyed paid responses outside stage cleanup. Keys
include model and generation input; reused responses still undergo validation.
Draw stores render provenance before OCR so text-check retries do not redraw.
Stage estimates include page references and OCR; Cast estimates include state
references. Provider usage and credit settlement remain distinct from estimates
and stage-progress totals. Missing usage is not evidence of zero provider cost.

`GET /api/projects/{project_id}/provider-usage` reconciles provider events and
artifact call IDs, including failures and unknown costs. Book's Dev Content
view shows recorded cost sources separately from user credit charges. Optional
visual review uses `/pages/{page_number}/visual-review` and its `/estimate`
endpoint. Restart the gateway after changing its retry configuration.
