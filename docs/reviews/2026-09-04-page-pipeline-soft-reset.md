# Page pipeline soft-reset review

**Status:** Original review at `e0fc331`, September 4, 2026; reset implemented in the working tree September 5. The findings below describe the pre-reset code; their line numbers are historical.

## Implementation outcome

- Plan now uses explicit entity-to-state maps. Draw preserves panel assignments, distinct reference labels, reading order, optional geometry, verbatim anchors, and continuity guards through the final provider input. Required reference overflow fails before spend; less-graphic framing retains references.
- Character, location, and prop states declare changed facets and identity replacement. Removed prose/regex inference; props now generate state references through the shared compiler and are included in estimates.
- Editions no longer silently switch profiles. Removed legacy hash acceptance and the Finish exception for missing state citations. Unknown requirements and entity citations fail validation.
- Plan caches paid responses by full input, model, and schema. Small-book and batched execution share canonical validation and publishing. Adapt beats cite a single Brief requirement registry instead of duplicating text, and missing citations are no longer synthesized from word overlap. Explicit beat entity scope allows safe reference-context pruning.
- Image transport does not automatically repeat ambiguous submissions. Gateway retries are disabled so they cannot multiply client attempts. Request hashes remain input identity, not a provider exactly-once guarantee.
- OCR checks geometry even when its text array already matches canonical order. Completed OCR is reusable. Manual OCR and optional visual checks now run with project/user billing context and a releasable credit hold.
- One page correction carries unresolved Draw findings together. Producing a visual revision marks findings `revised`, requiring confirmation. Only supported OCR findings can be automatically resolved by fresh OCR evidence.
- Added a bounded, optional reference-aware visual check with persisted input identity, uncertainty, at most eight editorial findings, and a credit estimate. It is independent from OCR and has no automatic correction loop. Its precision has not been measured on fresh generations.
- Added a project provider-usage report, scoped by authenticated owner and project, with page/operation grouping, failures, source labels, unknown costs, and missing artifact-linked events. Book exposes it under Dev Content. Recorded provider costs remain separate from charged credits and progress totals.
- Editorial suggestions are visible to authors, while raw evidence stays under Dev Content. Updated English/Spanish/French copy, current stage references, generated API/model docs, and agent guardrails.

### Validation

Final working-tree checks: **958 backend tests passed**, four optional tests skipped; **251 frontend tests passed** across 44 files. TypeScript/Vite build, ESLint, Ruff on changed Python files, documentation reliability, and `git diff --check` passed. Vite still reports its existing large-chunk warning; no bundle-size claim is made.

Focused regressions cover entity-scoped state collisions, geometry and continuity guards in the final prompt, reference overflow, less-graphic reference retention, fixed editions, ambiguous submissions, checkpoint invalidation/reuse, reference-aware review caching, credited-check failure cleanup, scoped provider reporting, and explicit requirement coverage.

### Deliberate boundaries and remaining evaluation

The cheap short-book Plan call remains, sharing validation and persistence with the batched path. Forcing all books through a paid page-map call is not a demonstrated cost improvement. Adapt retains its treatment/blueprint/locked-lettering passes and targeted repair; combining these passes and replacing the repair writer require a measured quality/cost comparison, not an assumed benefit.

An approved typography/style specimen and fresh model comparisons remain **evaluation work**, not shipped changes. No paid generation was run, so no numerical quality gain, acceptance-rate improvement, or realized cost saving is claimed. The optional visual critic is not enabled automatically for every page.

The local landing page and sign-in route load. An authenticated studio walkthrough remains blocked by login access. Gateway retry configuration takes effect after restarting the gateway. Existing incompatible artifacts must be rebuilt by their owning stages; the reset intentionally supplies no migration shims.

### Original review


The full-page architecture is worth keeping. The highest-value reset is to simplify how authoritative story and visual data reaches generation, remove compatibility exceptions, and make verification and retry behavior match their contracts. Another pipeline rewrite or additional autonomous critic stages would be premature.

## Scope and evidence

Reviewed the eight-stage registry, Adapt and Plan orchestration, Cast/state references, page prompt compilation, Vertex transport, OCR, issue correction, Finish, and Pages/Book frontend code. Opened `localhost:5173`; the public site and sign-in work, but the authenticated studio walkthrough remains pending login access. No paid generation was run.

Ran the existing complete-page Draw, page review, page finishing, and page planning suites: **113 passed**. Two additional in-memory reproductions confirmed state-name collision and reading-order validation defects. These reproductions did not modify production files.

Examined saved Cthulhu projects and visually inspected v3 pages 2 and 3. Saved outputs span earlier prompt/model revisions: they are useful evaluation fixtures, not a measured failure rate for today's code.

The supplied project guide still describes nine stages and text-free panel generation. The actual registry is `extract → brief → style → cast → adapt → plan → draw → finish`. Current full-page generation includes lettering. Update agent guidance early so future work does not resurrect the removed architecture.

The documentation reliability checker confirms existing stale stage/checkpoint tables in `docs/reference/stage-contracts.md` and `docs/reference/agent-context.md`, plus a broken ADR link in `docs/plans/2026-07-25-full-page-generation/README.md`. It therefore fails independently of the new review document.

## Highest-priority findings

### 1. Preserve identity and state relationships through the final provider request

**Evidence:** `page_drawing.py:245` constructs a provider projection that omits each content item's `entity_ids`, `appearance_state_ids`, and `pinned_geometry`, and omits canonical `reading_order`. It replaces identifiers such as `char_001` with “the referenced character.” Reference entries in that JSON contain only order and anchor. Meanwhile `litellm_handlers/vertex_multimodal.py:425` adds raw entity/state identifiers back beside image parts.

This means the provider sees reference identity labels, but loses the explicit connection between a particular panel, character, and appearance state. Multiple states on one page are especially ambiguous. It also means prompt-only tests asserting that internal IDs are absent do not cover the actual multimodal request.

**Recommendation:** One compiler should own the complete ordered text/image request. Resolve internal IDs into distinct human-readable labels, and include per-panel visible subjects, their selected state/reference labels, location, and props. Keep exact lettering in an explicitly separated section. Honor supported geometry pins; otherwise remove the unsupported editing contract. Preserve anchors verbatim, but instruct the model to *depict their described features*, not “preserve anchors verbatim” in a way that can sound like typesetting instructions.

Test the final provider contents, not only the intermediate prompt string. Do not solve ambiguity by reintroducing fixed character coordinates or previous-page image chains; that would conflict with ADR 0012.

### 2. State identity is entity-scoped in one contract and global in another

**Evidence:** `models/appearance.py` defines state IDs as entity-scoped. `ApprovedVisualReferenceInventory` permits `(alice, wet)` and `(bob, wet)`. However, `_selected_authorities` at `page_drawing.py:187` indexes references by state ID alone. A valid page containing only Alice in state `wet` fails when Bob's `wet` reference overwrites Alice's dictionary entry. Reproduced locally.

**Recommendation:** Carry a single entity/state reference key, or an explicit `(entity_id, state_id)` pair, throughout Adapt, Plan, and Draw. Remove parallel unpaired entity/state lists where possible. Audit Plan's state lookup tables for the same assumption. This is both a correctness fix and a contract simplification.

### 3. “Verified” currently means much less than visual consistency

**Evidence:** `page_review.py:271` invokes OCR and compares lettering; it performs no reference-image identity, prop, panel-structure, or scene-fidelity comparison. `page_finishing.py:130` checks planned state citations rather than rendered appearance, and deliberately treats legacy state gaps as diagnostics. ADR 0014 describes broader Draw and Finish validation than is implemented.

There is also a concrete reading-order bug at `page_review.py:228`: geometric order is checked only when the OCR observation array differs from canonical text order. With canonical array order but reversed geometric order, `_region_order_contradicts` returns true while `_compare_lettering` returns no failures or issues. Reproduced locally.

**Recommendation:** Fix that conditional first. Then label checks accurately in the product: text checked, visual review pending, production preflight passed. Introduce a bounded visual comparison on selected high-risk pages—first appearances, transformations, recurring props, and scene returns—against approved references. Keep uncertain visual judgments as reviewable issues. OCR should remain blind to expected wording; that is a good existing design.

The fixed 0.06 row-band OCR ordering heuristic also deserves multi-column and inset-page fixtures before its output is treated as proof. An uncertain detector reading should trigger a reread or author review before an expensive full-page correction.

### 4. Silent model migration contradicts the fixed-edition contract

**Evidence:** `ensure_current_page_edition` at `page_drawing.py:165` replaces the active edition profile when configuration changes. Page generation and correction routes call it automatically. Existing renders remain. Tests explicitly require migration, while ADR 0013 says model changes create explicitly regenerated editions. The saved v2 project contains renders from two different models; this demonstrates mixed-model history, not by itself its cause. Finish does not enforce a render-model comparison against the active edition.

**Recommendation:** Delete automatic edition upgrading. Freeze the selected profile; require an explicit new-edition operation when it changes. Since compatibility is dispensable, old projects can require regeneration. Keep the immutable request/render lineage—it is useful evidence, not unnecessary complexity.

### 5. An idempotency key is checked, but does not establish provider deduplication

**Evidence:** `page_drawing.py:623` sends a request hash as `canary_idempotency_key`; the Vertex handler checks equality with the manifest and then calls generation. That branch has no request-result lookup or deduplication. `ai/client.py:217` automatically retries transient failures, including transport failures. Active-job deduplication in `credited_job.py` covers a different layer.

**Recommendation:** Treat ambiguous provider timeouts separately from safe connection/rate-limit retries. Persist request execution state and reconcile/reuse completed results when possible. Do not advertise `retry_semantics='idempotent_request'` as an external guarantee merely because a hash is verified. A local request lock alone cannot guarantee exactly-once billing after an ambiguous provider timeout. Actual duplicate provider charges were not established by this review.

## Consistency and prompt improvements

**Reference limits need an explicit policy.** `compile_page_generation_request` takes the first eight authorities and converts overflow to text-only anchors. The `less_graphic` mode removes every reference image and applies a blanket clothing override. These are deliberate, tested behaviors, but weaken continuity. Rank references by the page's visible narrative subjects and surface omissions before spending. Make any alternate depiction narrowly scoped and retain unaffected identity references. The sampled v3 pages have at most five distinct entities, so reference overflow does not explain their observed drift.

**Objects need the same state vocabulary as characters and locations.** `models/story_bible.py:127` gives props an anchor but no appearance states. Broken, opened, emptied, disguised, or transferred objects are left to prose. Generalize a small visual-entity/state record across all three kinds; avoid a separate object continuity subsystem. Track story-relevant changes explicitly, rather than building a physical simulation.

**Replace prose-derived reference-conditioning rules with authored changes.** `state_assets.py` infers changing facets and total transformations using large English regex tables. Broad words such as “wolf” or “creature” can determine whether the canonical identity image is omitted. Prefer explicit changed facets and a replacement/continuation decision authored during extraction and reviewed with the state. Remove the inference machinery once equivalent test cases exist. Preserve immutable anchor text separately from those fields.

**Carry state constraints all the way to Draw.** Appearance states have `continuity_guard`, used in Cast state generation, but the approved inventory sent toward page generation retains only the anchor and identifiers. A rule such as “cannot grip with missing hands” should remain explicit at the page where it matters.

**Use a stable style specimen, not increasingly long style prose.** The compiler already supplies book-wide lettering and framing instructions. Saved v3 pages 2 and 3 nevertheless show different caption typefaces and noticeably different detailing on the recurring tablet. Evaluate an approved typography/framing specimen and a clear prop reference against those cases. Account for its reference-slot cost; do not append references indiscriminately.

## Simplification and cost priorities

### Keep the valuable structure

Keep discrete resumable stages, the approved brief, canonical lettering authored by Adapt and allocated by Plan, canonical ComicPages, approved visual references, frozen generation requests, render lineage, and provider-free export. These protect real editing and recovery behavior. Do not merge Adapt and Plan simply to reduce the stage count.

### Unify Plan's execution workflow and checkpoint paid intermediate work

`page_planning.py` is 2,473 lines and maintains separate one-shot and map/detail execution loops, with separate repair logic. The two-pass path keeps its page map and successful detail batches in memory, writing canonical outputs at the end. A later batch failure can discard useful paid work on restart. Adapt already has prompt/model-keyed checkpoints.

Use one map/detail orchestration path with checkpointed successful batches and localized repair. A short-book optimization can stay only if measurements justify it; avoid two independent validation/repair implementations. Keep deterministic IDs, numbering, and lettering allocation in code.

Each detail prompt currently includes the entire approved reference inventory. Filter it using known page/beat scope after ensuring extraction/adaptation preserve that scope. Avoid pruning solely by name keyword matching.

### Reduce repeated creative contracts in Adapt before removing passes

Adapt currently produces a treatment, a blueprint per shard, and locked lettering per shard, with another draft-shaped path for repairs. It has useful targeted repair and checkpointing, but also requirement text/ID duplication and substantial normalization/materialization logic.

First give requirements stable IDs with one text registry, and make repairs use the same draft shape as initial generation. Keep source coverage and exact lettering invariants. Then benchmark a combined blueprint-plus-lettering pass for short inputs against the current two-pass result. Do not assume fewer calls are cheaper if repair rates rise. Semantic completeness should not be inferred merely from a mechanically added requirement citation.

### Prioritize avoided image revisions over tiny OCR savings

The saved v3 project contains 36 planned pages, 38 render records, and 40 frozen requests. Render provenance totals **$5.22192**; eight analysis records contain lettering invariant failures (seven spelling-class findings and one invented-lettering finding). These are historical record counts, not current-model rates or final unresolved counts. Not every request produced a paid render, and failed-call costs may be absent from this sum.

The project state records **$3.1683425** total and **$0** for Draw despite those render costs. Provider-event settlement is separate, so this does not prove missing billing. It does show that project state alone cannot answer “what did this book cost?” OCR cost fields in these saved analyses are absent/zero; that is not evidence OCR was free.

Build one reconciled view from provider usage events, linked to project/page/request, separating initial generation, correction, OCR, and failed calls. Use cost per accepted page to evaluate changes. At checked-in estimates, image generation ($0.134 base plus references) dominates the $0.004 OCR allowance; these are configuration values, not verified current vendor prices.

There are also smaller estimate inconsistencies: Draw's stage estimate omits reference costs (`stages/s7_page_draw.py:30`), and two-pass Plan adds actual detail estimates to an initial estimate that already includes projected detail calls (`page_planning.py:1180`). Calculate estimates from the same planned operations used for execution.

### Batch corrections by page and verify outcomes

Corrections are requested per issue, but every correction regenerates a whole page. `correct_complete_page` marks the initiating issue resolved after producing a revision; it does not establish that a visual concern was fixed. New OCR findings can still block, which is useful, but arbitrary visual corrections have no equivalent check.

Submit one correction containing the selected open issues for that page. Recheck the new page, preserve its lineage, and distinguish “new revision produced” from “correction verified.” This reduces repeated page renders and misleading resolution state without adding another stage.

## Product and deletion decisions

`PagesRoom.tsx:158` hides Adapt/Plan editorial diagnostics behind Dev Content, whereas ADRs 0008/0014 call for useful exceptions before paid Draw. Choose intentionally: show a few actionable, source-linked concerns before spending, or remove low-value heuristic diagnostics and their automatic repair work. Do not maintain a large review contract that authors cannot act on.

Delete the old ComicPage hash acceptance hook (`models/page.py:148` and its base hook), automatic edition upgrades, legacy-only Finish state accommodations, stale stage/appearance-resolver documentation, and obsolete model metadata after checking remaining callers. Keep legitimate recovery and provider-response normalization: a “fallback” label alone is not evidence of a legacy shim. Do not retain or revive the panel generation architecture.

## Suggested reset order

1. Fix state-key collisions, final prompt identity/state mapping, and reading-order validation. Add focused regressions around the complete provider payload.
2. Freeze edition behavior; separate retry identity from provider deduplication claims. Reconcile page usage reporting.
3. Replace prose-derived state rules with explicit entity/state data; extend it to recurring props. Remove compatibility exceptions and stale guidance.
4. Unify and checkpoint Plan; simplify Adapt requirement/draft shapes and measure pass consolidation.
5. Evaluate reference/style changes on a small fixed set: recurring prop, similar-looking cast, appearance change, scene return, crowded page, dense lettering, and correction. Compare visual consistency, false OCR alarms, final acceptance, latency, and total provider cost.

The authenticated studio walkthrough and fresh model comparisons remain separate outstanding validation. This review does not claim a complete live end-to-end product test.
