# Slice 14 — Deterministic Golden Corpus and CI Gates

## Fresh-session assignment

Implement only this slice. Read `AGENTS.md`, the sibling `README.md`, this file,
and verify Slice 13's exact-preview parity tests. Do not begin Slice 15.

## Goal

Create a compact deterministic scenario corpus and CI checks that fail whenever
prompt ownership, alternate-state semantics, reference selection, provider wire,
cache identity, freezing, or preview parity regresses—without calling a model.

## Required reading

- Slices 00–13 handoffs, especially schema versions and canonical serializers
- existing prompt/reference/provider/cache/provenance fixtures under
  `novel_to_comic/tests/`
- `novel_to_comic/src/novel_to_comic/labs/`
- visual-consistency evaluation models/reports located through targeted `rg`
- backend/frontend CI configuration and test helpers

Do not use generated user project directories as an undocumented corpus. Add
small explicit fixtures with reviewable expected semantics.

## Deliverables

1. Build golden source fixtures for at least:
   - one canonical character in a canonical location;
   - two characters plus location;
   - three characters plus location/prop/style under a constrained route;
   - four characters plus location where non-subject omission is unavoidable;
   - subject count beyond a route cap, exercising the explicit error/text-only
     policy;
   - minor wardrobe-only state;
   - major age/anatomy/hair/injury/transformation state;
   - explicitly restored canonical-equivalent state;
   - location time/weather/damage/collapse/water-level states;
   - missing, unverified, and stale state assets;
   - recurring critical and noncritical props;
   - narration/dialogue/SFX/sign text that must not leak from dynamic fields;
   - compatible and incompatible previous-panel/match-cut continuity;
   - manual semantic edit, manual layout-only edit, and instructed edit;
   - selected reference replaced at the same path;
   - equivalent aliases resolving to the same configured route.
2. For each scenario, state expected:
   - exact protected anchors;
   - active entity/state ids and overlay compatibility;
   - selected/dropped references, order, roles, scopes, and facets;
   - warnings/errors;
   - prompt section ownership and required/forbidden concepts;
   - effective geometry/controls;
   - which changes must affect source, selection, compiled, execution, and
     provenance hashes.
3. Prefer focused semantic assertions over one giant opaque string snapshot.
   Use small golden JSON snapshots for canonical serialization and provider wire
   only where byte stability is itself the contract.
4. Add deterministic release gates for:
   - exact protected-anchor preservation;
   - zero canonical-versus-active-state mutable-fact contradictions in the
     corpus;
   - state-aware overlay rejection;
   - zero wrong location-state substitution;
   - zero dynamic story-text leakage;
   - correct one-owner/dedup behavior;
   - exact ReferencePlan/provider order agreement;
   - immutable snapshot digest parity;
   - correct cache invalidation/non-invalidation;
   - prepared/submitted/adapter preview parity;
   - truthful route/profile labels and capabilities.
5. Add architectural contract tests that fail if a stage/route can call a
   provider with raw prompt plus arbitrary paths, if a handler adds prompt prose,
   or if a second reference cap/sorter appears. Prefer dependency/interface
   assertions over brittle source-line matching.
6. Add provenance/redaction tests for all asset kinds, including separation of
   configured versus actual model and effective versus actual dimensions.
7. Keep deterministic corpus execution fast enough for normal CI. Separate slow
   integration tests with a clear marker only when unavoidable; no test may
   require provider credentials or credits.

## Release-blocker thresholds

These deterministic thresholds are non-negotiable:

- protected anchor preservation: 100%;
- prepared/submitted/adapter request parity: 100%;
- expected cache invalidation after provider-affecting changes: 100%;
- expected cache stability after diagnostic-only changes: 100%;
- known canonical/state contradictions: zero;
- silent wrong-state location substitutions: zero;
- dynamic story-text leakage: zero;
- reference selection/order disagreement: zero;
- route/profile truth disagreement: zero;
- provider bypasses and post-compilation mutations: zero.

## Tests first

The corpus is the test work for this slice. Start with scenarios reproducing the
original review failures, confirm they fail if their corresponding safeguard is
temporarily removed, then add the complete matrix. Do not weaken production
contracts to make snapshots easier to maintain.

## Exit criteria

- Every original review finding maps to at least one deterministic regression.
- Canonical and alternate character/location states have explicit fixtures.
- All release-blocker thresholds pass without model/network calls.
- Architecture tests guard the one-way IR -> plan -> compiler -> wire -> frozen
  request flow.
- Full backend tests, Ruff, frontend tests/lint/build, and `git diff --check`
  pass.

## Handoff to Slice 15

Write `handoffs/14.md` using the durable handoff template before replying.

Report corpus fixture ids, scenario matrix, assertion vocabulary, snapshot
versioning policy, gate results, CI commands/timing, and any behavior that still
requires visual rather than structural evaluation. Slice 15 will add that
authorized visual evidence without replacing these deterministic gates.
