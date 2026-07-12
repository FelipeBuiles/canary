# Image Generation Lifecycle

This is the operational and extension contract for image generation after the
July 2026 clean cutover. Internal prompt schemas are intentionally not backward
compatible during this development phase.

## Single production lifecycle

Every image follows one path: structured source data becomes canonical prompt
IR; state-compatible overlays are applied; `image_models.py` resolves one model
profile; `ReferencePlan` selects and orders references once;
`CompiledGenerationRequest` owns final prompt sections, instructions, geometry,
and controls; `ProviderWireRequest` serializes that request; submission freezes
the manifest and content-addressed reference bytes; and the result or failure
receives common redaction-safe provenance.

Protected character, location, and prop anchors remain byte-for-byte source
material. Active appearance/location state overrides contradictory canonical
mutable facets. Stale or incompatible overlays are dropped with diagnostics.
Visible subjects remain provider-bound text requirements even when a route
cannot fit all image references.

The compiled-request hash identifies provider-independent semantics. The
execution fingerprint covers provider-affecting inputs and immutable selected
reference bytes. The provenance hash also covers diagnostics. Configured model
identity remains distinct from provider-reported actual model identity.

`ImagePrompt.full_prompt` and `visual_brief` are retained only as derived
editing/historical fields. Labs `reference_image_paths` is an experiment input
whose paths are confined to the user root and staged. None is generation
authority.

## Existing projects and regeneration

- Regenerate stored Stage 7/direct prompt JSON before rerendering old panels.
  Old derived prompt, layout, or reference-path fields cannot reconstruct an
  exact request and receive no compatibility shim.
- Regenerate unverified or stale character/location state assets from their
  current canonical parent. A canonical reroll invalidates dependent lineage.
- Existing panel pixels remain valid, but their old cache identity will not
  match the new execution fingerprint; the next rerender may miss cache.
- Dev Content distinguishes draft projections from exact prepared/submitted
  requests. Model names, hashes, ids, bindings, and provider data stay behind
  Dev Content.

## Frozen request and blob retention

Retain frozen manifests and content-addressed reference blobs together while a
request is prepared, queued, running, needed for exact preview, or retained for
audit. Cleanup may delete only blobs unreferenced by every retained manifest.
Never delete a blob merely because its original mutable path changed.

Invalidate abandoned prepared requests before garbage collection. Completed
art and redaction-safe provenance may outlive replay blobs when policy permits,
but exact replay then becomes unavailable. Manifests and provenance must not
contain credentials, signed URLs, absolute user paths, or raw payloads.

## Provider extension rules

A provider/alias must add a truthful profile in `image_models.py`, golden
reference-policy coverage, compiled/wire snapshots, geometry tests, and common
provenance coverage. Its isolated handler must require the versioned wire and
preserve exact prompt bytes, reference instructions/order, geometry, and
supported controls. Provider-side prose, truncation, hidden caps, sorting,
filename role inference, mutable-path reads, and model-family fallback are
forbidden.

Reve production uses v1 create/remix within declared reference-slot limits.
The feature-gated v2 layout endpoint is not a production bypass; it may return
only after its capability is represented in the shared compiled/wire contract.

## Golden and visual evaluation

Run the golden corpus, legacy-cutover, and provider-wire tests without
credentials. Labs production-equivalent runs consume server-compiled wire.
Generic A/B experiments may remain, but project import never seeds an old
compiler prompt as its comparison.

Paid visual evaluation requires an estimate and explicit authorization. Retain
per-scenario provenance and count missing/failed pairs. An approximate or
absolute-only benchmark is not paired evidence without an explicit rollout
decision.

## Rollback

Rollback means reverting the clean-cutover change set while preserving images,
frozen manifests, blobs, and provenance. No permanent runtime legacy path is
kept. If a restored version cannot consume a newer schema, retain artifacts and
regenerate through that version instead of adding an implicit shim.
