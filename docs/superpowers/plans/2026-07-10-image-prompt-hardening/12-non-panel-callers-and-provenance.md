# Slice 12 — Non-Panel Image Callers and Common Provenance

## Fresh-session assignment

Implement only this slice. Read `AGENTS.md`, the sibling `README.md`, this file,
and verify Slice 11's panel lifecycle and provenance tests. Do not begin Slice
13.

## Goal

Route style, cast, location, appearance-state, and prop image generation through
the same compiler, wire, immutable-submission, and provenance contracts without
forcing panel-only fields onto those asset kinds.

## Current problem

Non-panel image stages use several direct generator helpers and record different
subsets of prompt/model/reference metadata. Geometry, controls, reference
instructions, configured route identity, and actual provider result can therefore
drift from panel behavior or become impossible to audit.

## Required reading

- Slices 05–11 handoffs
- `novel_to_comic/src/novel_to_comic/stages/s2_style.py`
- `novel_to_comic/src/novel_to_comic/stages/s3_cast.py`
- prop-reference generation paths located through targeted `rg`
- `novel_to_comic/src/novel_to_comic/clients/flux.py`
- `novel_to_comic/src/novel_to_comic/ai/finalisation.py`
- `novel_to_comic/src/novel_to_comic/artifacts.py`
- style/cast/state/prop estimate, retry, failure, and metadata tests

## Deliverables

1. Define explicit compiled-request input schemas for:
   - abstract style proofs;
   - entity-specific style proofs, if supported;
   - canonical character references;
   - canonical location plates;
   - character appearance-state references;
   - location-state plates;
   - prop references.
2. Reuse common protected-section, route-profile, geometry, control, wire,
   immutable snapshot, and provider result contracts. Do not model non-panel
   assets as fake panels or add empty panel-only fields.
3. Route each asset generator, instructed regeneration, retry, and estimate
   through the shared generation lifecycle at the appropriate level. Treat
   version restore as a result/provenance operation only: activate archived image
   bytes, reconnect their original frozen-request/provenance link, and
   re-evaluate current lineage. Restore must not compile, freeze, enqueue,
   reserve credits, or call a provider.
4. Preserve the style-proof anchor rule:
   - abstract style proofs with no entity/location anchor do not invent one;
   - any supplied character/location/prop anchor is protected verbatim;
   - style prose cannot rewrite a supplied entity anchor.
5. Enforce the Slice 06 geometry contract for style proofs and location plates.
   Estimates and submitted requests use the same effective dimensions and final
   reference count.
6. Apply the common provenance envelope to every image result/failure, with
   asset-specific identity and lineage extensions. Include exact request ids,
   compiled/wire hashes, immutable reference digests, configured/actual model
   fields, effective/actual dimensions, controls, timings, cost, and warnings.
7. Make state asset provenance from Slices 08–09 conform to the common envelope
   without losing canonical-parent/style hashes or stale-lineage history.
8. After the last panel/non-panel caller is migrated, remove the temporary
   legacy transport schema branch and its provider-side prefixes, truncation,
   caps, sorting, mutable-path uploads, partial request rebuilds, and partial
   metadata writers.
9. Remove remaining direct non-panel geometry math and model-control branches
   once their model-profile equivalents are in use.
10. Retain one low-level provider transport seam that accepts only a frozen wire
   request. Do not retain a generic helper that accepts raw prompt plus arbitrary
   paths and can bypass compilation.

## Tests first

- One golden compiled/wire/provenance snapshot for each asset kind and route used
  in production.
- Abstract style proof has no invented anchor; entity-specific proof preserves
  supplied sentinel anchor exactly.
- Character/location/prop prompts and references retain correct roles/scopes.
- Conditioned state metadata retains parent/style hashes inside common
  provenance.
- Style proof is actual 4:5 target; location plate uses verified landscape
  target; actual output dimensions are result-only fields.
- Estimate and submission share route/ref-count/dimensions/pricing inputs.
- Retry/regenerate use newly prepared frozen requests and correct asset identity.
- Restore activates archived bytes and original request provenance with zero
  prompt/image calls and zero credit reservation, then rechecks lineage.
- Failure metadata retains request provenance without secrets.
- Architecture test finds no non-panel raw-prompt/raw-path provider call.

## Exit criteria

- Every production image class uses the shared request/wire/submission contract.
- Common provenance is reconstructable and asset-specific lineage is preserved.
- Style proof anchor semantics and geometry are explicit and tested.
- Raw prompt plus arbitrary mutable-path transport is no longer callable from a
  stage/route.
- The temporary legacy discriminator and all inventoried callers are gone.
- Focused tests, full backend tests, Ruff, and affected estimate/route tests pass.

## Handoff to Slice 13

Write `handoffs/12.md` using the durable handoff template before replying.

Report every migrated asset path, asset-kind input schemas, common provenance
envelope and extensions, style-proof anchor policy, storage/API locations, and
all remaining request readers. Slice 13 will expose authoritative prepared,
submitted, and completed records behind Dev Content.
