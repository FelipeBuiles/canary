# Slice 08 — Alternate-State Asset Lifecycle and Lineage

## Fresh-session assignment

Implement only this slice. Read `AGENTS.md`, the sibling `README.md`, this file,
and verify Slice 07's provider-wire snapshots. Do not begin Slice 09.

## Goal

Give character and location state assets non-conflicting prompts, independent
correction/version lifecycles, explicit canonical-parent lineage, and reliable
stale-lineage detection. This slice defines and persists the lifecycle; Slice 09
will switch state generation to canonical-conditioned requests.

## Current problem

- copying a character and replacing its `visual_anchor` retains
  `default_outfit`, which can contradict the active state;
- gesture language can demand limbs/anatomy absent in a transformed state;
- base correction addenda are silently reused for all state assets;
- state location plates can be regenerated only through incomplete/internal
  paths despite state-aware lower-level functions;
- state assets do not consistently record which canonical/style bytes they
  descend from;
- rerolling a canonical character/location at the same path does not invalidate
  dependent state assets;
- state version history/restore parity is weaker than canonical asset parity.

## Required reading

- Slices 03–07 handoffs, especially state ids, authority facets, and wire schema
- `novel_to_comic/src/novel_to_comic/stages/s3_cast.py`
- `novel_to_comic/src/novel_to_comic/artifacts.py`
- `novel_to_comic/src/novel_to_comic/prompt_instructions.py`
- `novel_to_comic/src/novel_to_comic/server/routers/pipeline.py`
- `novel_to_comic/src/novel_to_comic/clients/flux.py`
- `docs/superpowers/specs/2026-06-14-appearance-timeline-design.md`
- cast, failure-metadata, version-history, and rerender tests

## Deliverables

1. Introduce an explicit `StateAssetGenerationSpec` or equivalent for character
   and location states. Include entity/state ids, exact active-state anchor,
   canonical parent identity, compatible preserved/overridden facets, selected
   style identity, state-scoped user addendum, requested shape, and lineage
   status.
2. Build state-character prompt data from the active state, not a shallow copy of
   the canonical character. Preserve permanent identity facts only when the
   state does not replace them. Exclude base outfit, changed anatomy/age/hair,
   and incompatible gesture language.
3. Build location-state prompt data so the active state wins over canonical
   weather, light, material condition, atmosphere, damage, water level, or
   architecture. Preserve only non-conflicting stable landmarks/facets.
4. Add state-scoped instruction/addendum storage for each character state and
   location state. Canonical corrections do not automatically apply to every
   state, and state corrections do not mutate canonical artifacts.
5. Expose explicit entity/state-id routes for regenerate, instructed regenerate,
   version list, restore, and current metadata for both character and location
   states. Preserve existing auth/credit/job patterns.
6. Define a common lineage metadata envelope containing:
   - asset kind, entity id, and state id;
   - exact active-state anchor and rendered prompt/spec version;
   - canonical parent path and SHA-256;
   - style path and SHA-256 when present;
   - configured route/model and effective target dimensions;
   - state addendum revision;
   - `lineage_mode` and `lineage_status`;
   - generated request/provenance links when available after later slices.
7. On canonical reroll/restore, compare current bytes to every dependent state
   asset's parent hash and mark mismatches stale. Do not delete history or spend
   credits automatically. Surface a structured regeneration-required warning.
8. Generate/order canonical assets before state specs during a normal cast run so
   the current canonical hash is known. Where this slice touches actual state
   generation, use the shared compiled/wire seam with no canonical reference and
   record `lineage_mode=unconditioned`; do not add an ad hoc multi-reference
   call. Actual conditioned generation belongs to Slice 09.
9. Mark pre-contract or still-unconditioned state outputs explicitly rather than
   claiming canonical-conditioned lineage. The Slice 04 resolver must follow its
   documented unverified-lineage safety policy.

## Tests first

- State prompt/spec contains the full exact state anchor and no canonical
  `default_outfit`.
- A no-hands state contains no hand-dependent gesture instruction.
- Age, hair, anatomy, clothing, damage, day/night, weather, collapse, and
  drained-lake fixtures override only the relevant canonical facets.
- Base and state correction addenda are isolated.
- Character/location state endpoints target the exact entity/state artifact and
  preserve version history.
- Canonical replacement or restore at the same path marks dependent states
  stale; unrelated canonical changes do not.
- Stale state metadata is never reported as current lineage.
- Normal cast orchestration prepares canonical assets before state specs.
- No paid image call is made in these tests.

## Exit criteria

- State prompt/spec construction has no canonical mutable-state contradiction.
- Every state asset is independently correctable, versioned, and addressable.
- Canonical rerolls deterministically mark dependent states stale.
- Metadata distinguishes conditioned, unconditioned/unverified, current, and
  stale lineage.
- No new parallel reference transport exists.
- Focused tests, full backend tests, Ruff, and affected route tests pass.

## Handoff to Slice 09

Write `handoffs/08.md` using the durable handoff template before replying.

Report state spec fields, facet-override rules, addendum paths, endpoint
contracts, metadata schema, stale-lineage invalidation hook, and canonical-first
orchestration seam. Slice 09 will use these specs with the shared
ReferencePlan/compiled/wire contracts.
