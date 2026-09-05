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

`state.py` and `stages/__init__.py` define ordering and gates. HTTP pipeline
operations live in `server/routers/pipeline.py`; page generation, correction,
and analysis live in `server/routers/pages.py`.

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
One correction addresses a page's unresolved Draw findings. A generated visual
fix remains `revised` until confirmed; proven OCR fixes may be resolved by OCR.
Finish checks artifact and render lineage, OCR, state citations, unresolved
issues, dimensions, and packaging. It does not invoke a creative model.

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
