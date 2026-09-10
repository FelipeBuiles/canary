# Model routing and external batch pipeline audit

**Status: Proposed. Audited September 9, 2026.** This report describes checked-in
implementation and proposed changes. No runtime configuration was changed and no
paid model calls were made. Prices below are repository estimates, not a fresh
verification of provider rates. See the [selection review](model-selection-review-2026-09-09.md)
for researched recommendations.

## Current model inventory

| Operation | Production gateway | Dev launcher default |
|---|---|---|
| Extract and Brief | Gemini 3.8 Flash, all presets | GPT-5.6 Terra |
| Adapt | Haiku 4.5 fast; Gemini 3.8 Flash balanced; Opus 4.7 quality/escalation | GPT-5.6 Terra |
| Plan | Gemini 3.5 Flash Lite fast; Gemini 3.8 Flash balanced/quality | GPT-5.6 Terra |
| Style suggestions and asset instruction rewrites | Gemini 3.5 Flash Lite | GPT-5.6 Terra |
| OCR | Gemini 3.8 Flash, independent of preset | GPT-5.6 Terra |
| General style/cast images | Gemini Flash Lite Image fast; Gemini 3 Pro Image balanced; GPT Image 2 quality; Reve optional and Seedream test route | GPT Image 2 source selector; GPT-5.5 image reasoning |
| Complete-page Draw | Fixed Gemini 3 Pro Image profile | Codex complete-page route through image-balanced |

Sources: [gateway aliases](../../litellm/config.yaml),
[dev launch defaults](../../scripts/dev.sh),
[configuration](../../novel_to_comic/src/novel_to_comic/config.py),
[Brief call site](../../novel_to_comic/src/novel_to_comic/stages/s2_brief.py),
[Adapt call site](../../novel_to_comic/src/novel_to_comic/stages/s4_adapt.py),
[Plan call site](../../novel_to_comic/src/novel_to_comic/stages/s5_plan.py).

The successful GPT Adapt/Plan baseline comes from the development routing map,
not the committed production gateway. Every text alias in the default dev launcher
maps to exact selector `gpt-5.6-terra`.

## Draw is a separate model selection seam

Changing `image-quality` changes general assets but does **not** switch complete
pages. [page_drawing.py](../../novel_to_comic/src/novel_to_comic/page_drawing.py)
selects the production profile and Vertex adapter separately. Its profile records
`vertex-multimodal/gemini-3-pro-image`, 1696×2528 output, eight references, a
32,000-character prompt budget, and bounded submission semantics.

[Configuration](../../novel_to_comic/src/novel_to_comic/config.py) estimates
$0.134 per page plus $0.00112 per reference, with a separate $0.004 OCR allowance.
One hundred pages with four references and one OCR pass each therefore have a
configured estimate of $14.248, excluding other pipeline work and corrections.

A new image backend requires an evaluated complete-page profile and adapter.
Existing edition/profile hashes are checked and cannot silently change. The
current implementation rejects incompatible editions rather than supporting
arbitrary historic profile dispatch; retain their producing model where supported
and use a new edition/project for comparisons.

The [Codex route](../../novel_to_comic/src/novel_to_comic/codex_dev.py) fixes the
image source selector to `gpt-image-2`. Its reasoning model is a separate value.
The [capability evidence](../reference/codex-dev-capabilities.md) explicitly says
the actual returned image backend is unknown and Sunburst/Flare cannot be selected
through that tool. Subscription funding is distinct from API dollars; a single job
cannot mix subscription-funded and API-funded operations.

## Batch fit and required changes

First-pass pages are a good independent workload after approved references and
Plan are frozen. They do not require a previous generated page as input.
[Draw-all routing](../../novel_to_comic/src/novel_to_comic/server/routers/pages.py)
currently prepares pages together, then enqueues individual immediate jobs; this
is not provider Batch processing.

The adapter currently exposes an awaited `generate` operation that returns image
bytes. [The credited wrapper](../../novel_to_comic/src/novel_to_comic/server/credited_job.py)
holds authorization through work and settlement and cleans up in `finally`.
True external jobs require the following changes:

1. **Persist submission intent and item identity.** Record provider job/file IDs,
   custom item IDs, frozen request/profile hashes, page/render revisions, reference
   digests, ledger job identity, and terminal result/error state. Persist before
   spend; reconcile ambiguous submissions instead of automatically repeating them.
2. **Collect across restarts.** Poll or ingest notifications, download results,
   and import each item idempotently, including partial success, expiration, and
   cancellation. [Current recovery](../../novel_to_comic/src/novel_to_comic/server/generation_jobs.py)
   marks previously queued/running jobs failed after restart. External provider
   work can still be running and needs a different recovery path.
3. **Make authorization durable.** [Credit reservations](../../novel_to_comic/src/novel_to_comic/server/credits.py)
   have 3,600-second leases renewed every 30 seconds by a process-specific owner.
   A day-long provider job must retain authorization through server downtime and
   ownership takeover. Extending the coroutine timeout alone is insufficient.
   Release unused authorization only after reconciling actual provider outcomes.
4. **Split generation from analysis continuation.** Reuse saved provenance and
   render persistence before OCR. Existing analysis recovery already avoids drawing
   again when lettering checks fail. Settle image/OCR usage once and only mark
   completion after required settlement and evidence are durable.
5. **Protect pending pages durably.** Existing page locks are process-local.
   Pending batch records must prevent conflicting corrections or replans, and
   stale results must not become the current render accidentally.
6. **Expose the actual lifecycle.** Distinguish externally queued, generating,
   imported, checking lettering, ready, failed, and cancelling work. Preserve
   partial results. The [Draw stage](../../novel_to_comic/src/novel_to_comic/stages/s7_page_draw.py)
   already defers provider work to per-page routes; keep its review checkpoint and
   Finish's downstream checks intact.
7. **Record price mode and actual usage.** Retain batch versus standard pricing
   provenance, settle per item, and account for completed billable items after
   cancellation. Request hashes identify inputs, not provider deduplication.

Recommended sequence: implement and evaluate a synchronous GPT Image 2.5 profile
first, then add optional economy/overnight first-pass Draw using identical frozen
requests. Keep interactive style proofs and corrections synchronous initially.
The research report separately establishes which providers support image batches;
this audit does not infer support from the existence of a local job queue.

## Pricing inconsistency to fix during implementation

[Pricing overrides](../../novel_to_comic/src/novel_to_comic/litellm_pricing_overrides.yaml)
map `extract-fast` to Gemini 3.5 Flash Lite, but the
[gateway](../../litellm/config.yaml) sends it to Gemini 3.8 Flash. Pre-call fast
Extract/Brief estimates can therefore use the wrong price. Synchronize aliases
and run pricing validation during a subsequent implementation change.
