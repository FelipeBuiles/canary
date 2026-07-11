# Slice 09 — Canonical-Conditioned Character and Location State Assets

## Fresh-session assignment

Implement only this slice. Read `AGENTS.md`, the sibling `README.md`, this file,
and verify Slice 08's lifecycle, metadata, and stale-lineage tests. Do not begin
Slice 10.

## Goal

Generate alternate character sheets and location plates through the shared
reference, compiler, and provider-wire contracts so each state inherits
compatible canonical identity while its active state overrides mutable facts.

## Current problem

State assets are generated independently from style plus text, allowing faces,
body identity, architecture, and landmark geometry to drift. Simply adding the
canonical image as a generic reference would create the opposite failure: the
canonical outfit, anatomy, weather, materials, or undamaged structure could
overrule the intended alternate state.

## Required reading

- Slice 08 state specs and lifecycle handoff
- Slices 04–07 `ReferencePlan`, compiled request, model profile, and wire schema
- `novel_to_comic/src/novel_to_comic/stages/s3_cast.py`
- `novel_to_comic/src/novel_to_comic/artifacts.py`
- `novel_to_comic/src/novel_to_comic/clients/flux.py`
- `novel_to_comic/src/novel_to_comic/ai/finalisation.py`
- cast generation, request-snapshot, estimate, and failure-metadata tests

## Deliverables

1. Add state-asset-specific semantic reference candidates that reuse the Slice
   04 types and route caps:
   - character state: current canonical character as compatible identity facets,
     plus selected style where space permits;
   - location state: current canonical plate as compatible location facets, plus
     selected style where space permits.
2. Give canonical identity/location input priority over redundant style when a
   provider cap cannot accept both. Record every dropped candidate and reason.
3. For a character state, preserve only identity facets not replaced by the
   state spec. The exact active-state anchor and state addendum control clothing,
   anatomy, age, hair, injury/transformation, and gesture where applicable.
4. For a location state, preserve only landmarks/geometry/materials not replaced
   by the state. The exact active anchor wins for collapse, damage, weather,
   time/light, water level, vegetation, atmosphere, and altered architecture.
5. Include a canonical parent reference only when the state spec names at least
   one visually meaningful compatible facet. If a total transformation or total
   destruction replaces every useful facet, omit the contradictory parent,
   record `state_conflict` and `lineage_mode=state_only`, retain the canonical
   parent hash as semantic lineage, and generate from the exact self-contained
   state anchor plus compatible style rather than pretending the request is
   safely conditioned.
6. Generate canonical character/location assets first, then compile and send
   state requests after the canonical SHA is known. A missing/unreadable
   canonical parent blocks conditioned state generation with a structured error;
   never fall back silently to an independent unconditioned image.
7. Use `CompiledGenerationRequest` and `ProviderWireRequest` for state assets.
   Do not introduce a cast-specific prompt prefix, ref sorter, or provider call.
8. Keep the number of state image jobs unchanged. Update estimates only for
   reference-input pricing differences and use the final selected count.
9. Persist exact compiled/wire request hashes, ordered reference roles/hashes,
   current parent/style hashes, result metadata, and `lineage_mode=conditioned`
   or the explicit `state_only` exception.
10. When a user regenerates a canonical asset, keep dependent states stale until
   the user explicitly regenerates or restores them. Offer a state-regeneration
   action but do not create an automatic paid cascade.
11. Ensure restored state versions retain the lineage metadata from their own
    generation and are immediately re-evaluated against current parent bytes.

## Tests first

- Character state request receives canonical identity and style in final plan
  order with compatible facet instructions.
- No-hands, older-age, severe-injury, transformed-body, changed-hair, and
  alternate-outfit states contain no contradictory canonical matching rule.
- Location state request starts only after canonical availability and receives
  a location-identity reference.
- Total transformation/destruction with no compatible facets omits the canonical
  parent and records the conflict rather than sending a contradictory image.
- Collapsed-building, drained-lake, flooded, day/night, and weather-state tests
  prove the active anchor wins over canonical reference facets.
- Tight provider cap drops style before canonical identity and reports it.
- Missing/digest-mismatched canonical parent fails before provider I/O.
- State metadata contains exact parent/style hashes and request identities.
- Canonical reroll does not silently auto-spend or reuse stale state output.
- Restored version is current only when its parent hash still matches.
- Provider boundaries are mocked; no paid image call occurs.

## Exit criteria

- Every newly generated state asset has compatible canonical lineage.
- Active state semantics cannot be overruled by canonical mutable facts.
- State generation uses the same reference/compiler/wire contracts as panels.
- Stale or unverifiable state outputs cannot become authoritative references.
- Focused tests, full backend tests, Ruff, and estimate tests pass.

## Handoff to Slice 10

Write `handoffs/09.md` using the durable handoff template before replying.

Report state-asset request builders, asset-specific reference priority,
canonical-first scheduling, metadata/provenance fields, stale-output behavior,
and request snapshots. Slice 10 will freeze all queued request inputs, including
these canonical/style bytes.
