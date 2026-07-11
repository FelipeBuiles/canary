# Slice 04 — Model Capabilities and Semantic ReferencePlan

## Fresh-session assignment

Implement only this slice. Read `AGENTS.md`, the sibling `README.md`, this file,
and verify Slice 03's source-lineage and state-aware overlay tests. Do not begin
Slice 05.

## Goal

Replace stored-path and provider-branch reference selection with one immutable,
capability-aware `ReferencePlan`. The plan owns final selection, ordering,
authority facets, selected content hashes, and drop diagnostics before prompt
compilation begins.

## Current problem

- persisted `reference_image_paths` reflect what existed during prompt creation,
  not necessarily the active semantic state at draw time;
- multiple crops of one character can consume scarce slots;
- a significant alternate appearance can be conditioned by a contradictory
  canonical full-body image;
- primary pose selection is not applied consistently across routes or state
  directories;
- Reve's hard reference cap is enforced after some prompt/index construction;
- active location plates, props, style, and continuity compete without one
  documented policy;
- reference bytes are absent from panel cache identity;
- state assets whose canonical parent changed can remain silently usable.

## Required reading

- Slice 00's route-description seam and handoff
- Slice 02's canonical prompt IR
- Slice 03's active-state and overlay contract
- `novel_to_comic/src/novel_to_comic/image_ref_strategy.py`
- `novel_to_comic/src/novel_to_comic/prompting.py`
- `novel_to_comic/src/novel_to_comic/stages/s7_draw.py`
- `novel_to_comic/src/novel_to_comic/artifacts.py`
- `novel_to_comic/src/novel_to_comic/models/prompt.py`
- `novel_to_comic/src/novel_to_comic/ai/providers/base.py`
- `web/src/lib/promptWarnings.ts`
- relevant prompting, cache, estimate, and failure-metadata tests

## Domain contract

Extend the route profile from Slice 00 with verified reference capabilities
needed before selection, including the hard reference count and any role/type
restrictions. Do not add prompt-length, aspect, or generation-control fields yet.

Create an application-level module such as `image_references.py`. A suitable
starting shape is:

```python
class ReferenceAsset:
    path: Path
    role: RefRole
    entity_id: str | None
    appearance_state_id: str | None
    authority_scope: AuthorityScope
    preserve_facets: tuple[str, ...]
    ignore_facets: tuple[str, ...]
    pose: str | None
    content_sha256: str
    lineage_parent_sha256: str | None

class DroppedReference:
    candidate: ReferenceAsset | SemanticCandidate
    reason: DropReason
    detail: str | None

class ReferencePlan:
    expected_route: ImageRoute
    selected: tuple[ReferenceAsset, ...]
    dropped: tuple[DroppedReference, ...]
    selection_fingerprint: str
```

Required drop reasons include `missing`, `unreadable`, `duplicate_entity`,
`provider_cap`, `unsupported_role`, `state_conflict`, `stale_lineage`,
`unverified_lineage`, and `lower_priority`.

Use dataclasses or Pydantic consistently with surrounding code. Prompt-domain
code must not import HTTP-provider types.

## Deliverables

1. Resolve candidates at draw/estimate time from semantic entity/state ids,
   current Story Bible records, selected primary poses, current asset metadata,
   and current files. Stored path availability is not authority.
2. Define a pure, table-driven scarce-slot policy as part of plan construction.
   The plan is final only after the route's hard cap and role restrictions have
   been applied. No later layer may select, cap, or reorder references.
3. Treat all visible subjects as prompt requirements. Choose at most one
   framing-appropriate crop per character. If subjects exceed the route cap,
   follow one explicit route policy: reject with an actionable error, or allow
   named subjects to proceed text-only with a structured warning. Never silently
   erase a subject from the prompt or diagnostics.
4. Make active-state location normally outrank a redundant style sample. Define
   deterministic priorities for canonical location, explicit critical props,
   compatible continuity, and style by shot type. Publish the full 0–4 subject
   matrix in tests and the Slice 05 handoff.
5. Make the user's explicit primary pose win on every route, including assets
   nested in appearance-state directories.
6. Apply state authority:
   - dedicated significant-state ref -> full active appearance authority;
   - minor text-only state -> a compatible canonical crop may preserve only
     explicitly listed identity facets and must ignore mutable state facets;
   - missing significant-state ref -> omit contradictory canonical full-body
     conditioning; use identity-only input only when its preserved facets are
     explicitly compatible;
   - explicitly restored/canonical-equivalent state -> canonical full appearance
     is allowed only when the state declares that equivalence;
   - missing or stale active location-state plate -> no canonical-state plate
     substitution; warn and remain text-only for the location.
7. Compare a state asset's recorded canonical parent hash with the current
   canonical bytes. Mark mismatches `stale_lineage` and exclude them. Until
   Slice 08 makes lineage metadata mandatory, treat absent lineage as
   `unverified_lineage` under an explicit, tested safety policy.
8. Disable previous-panel continuity references when character/location state
   authority changes across the boundary, except an explicitly compatible
   match-cut policy.
9. Materialize the final selection before prompt rendering: verify readability,
   compute SHA-256 per selected file, and compute a stable selection fingerprint
   from selected semantic roles, order, scopes/facets, and content hashes.
10. Use selected count for estimates and selected hashes for panel cache input.
    A changed unselected candidate must not invalidate cache unless it changes
    the selected plan.
11. Remove `reference_image_paths` as an authoritative persisted field. Breaking
    prompt JSON is acceptable; do not maintain two sources of truth.
12. Surface dropped-reference warnings through the backend. UI presentation may
    remain minimal until Slice 13.

## Tests first

- Route-profile hard caps and role support agree with configured production
  routes.
- Matrix: 0–4 subjects plus canonical/active-state location, critical/noncritical
  prop, style, and continuity candidates for close/medium/wide shots.
- Subject overflow follows the documented error or text-only policy and names
  every unreferenced subject.
- One character with many crops selects one correct crop; explicit primary pose
  wins in base and state directories.
- Base, minor wardrobe, significant present/missing, and restored state scopes.
- Active location state present, missing, stale, and unverified.
- Replacing canonical character/location bytes at the same path marks dependent
  state refs stale.
- State change suppresses incompatible prior-panel continuity.
- Selected-byte change alters selection fingerprint/cache; unselected-byte
  change does not.
- Unreadable selected asset fails before prompt indices can be constructed.
- Estimate uses the final selected count.

## Exit criteria

- Every panel resolves one deterministic, capability-aware final plan.
- No later prompt or provider layer needs to choose or drop references.
- No alternate appearance/location is paired with contradictory canonical
  full-state conditioning.
- State lineage mismatches are visible and excluded.
- Focused tests, full backend tests, Ruff, and affected warning tests pass.

## Handoff to Slice 05

Write `handoffs/04.md` using the durable handoff template before replying.

Report the `ImageModelProfile` reference fields, `ReferencePlan` API, full slot
matrix, final ordering rule, authority scopes/facets, warning codes, lineage
policy, and selection-fingerprint projection. Slice 05 must consume the plan
without changing selection.
