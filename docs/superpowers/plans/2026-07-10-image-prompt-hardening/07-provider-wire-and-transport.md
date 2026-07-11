# Slice 07 — ProviderWireRequest and Transport Parity

## Fresh-session assignment

Implement only this slice. Read `AGENTS.md`, the sibling `README.md`, this file,
and verify Slice 06's compiler budgets and capability matrix. Do not begin Slice
08.

## Goal

Create a versioned provider-wire representation and make adapters/isolated
handlers serialize wire requests exactly. For the new wire schema, provider code
must not reinterpret semantic roles, add prompt prose, choose references,
reorder bytes, or enforce a second cap. Existing callers migrate in Slices
11–12, so this slice must keep their legacy path isolated until then.

## Current problem

- prompt indices can be constructed before a provider reorders or drops refs;
- Reve inline indices, multipart order, and v2 bindings have separate logic;
- generic Gemini labels discard entity/state/scope meaning;
- custom LiteLLM handlers run in an isolated environment and cannot safely
  import application modules;
- provider helpers can prefix/append prose or silently ignore unsupported
  controls;
- configured model identity is not clearly separated from the model actually
  reported by a provider response.

## Required reading

- Slices 04–06 handoffs and request snapshots
- `novel_to_comic/src/novel_to_comic/ai/providers/base.py`
- `novel_to_comic/src/novel_to_comic/ai/providers/litellm_http.py`
- `novel_to_comic/src/novel_to_comic/ai/providers/reve_layout.py`
- `novel_to_comic/src/novel_to_comic/clients/flux.py`
- `novel_to_comic/src/novel_to_comic/ai/finalisation.py`
- `litellm_handlers/vertex_multimodal.py`
- `litellm_handlers/reve_provider.py`
- `litellm_handlers/fal_provider.py`
- `litellm/config.yaml`
- provider, handler, and request-snapshot tests

## Domain contract

Define a portable, versioned `ProviderWireRequest` that contains the exact
provider-bound representation before credentials/transient upload data:

- configured target and expected route;
- exact prompt field(s) or text parts in provider order;
- exact ordered reference entries with digest, role label, semantic instruction,
  and provider binding/index;
- effective target dimensions and structured aspect;
- only capability-approved controls;
- a deterministic `execution_fingerprint` over all provider-affecting fields and
  selected reference digests;
- a link to the provider-independent compiled request hash.

The wire schema must be portable into isolated handlers. Prefer a JSON/manifest
contract. If multipart filename encoding is unavoidable, version it and test
round-trip exhaustively.

## Deliverables

1. Compile `ProviderWireRequest` deterministically from
   `CompiledGenerationRequest`. Provider-specific syntax such as Reve image tags
   is created here, not in the isolated handler, and is included in the hashed,
   inspectable wire representation.
2. Make handlers parse and serialize only. They may not map authority enums to
   new sentences, add aspect prose, trim prompts, sort/cap refs, or choose
   fallback controls for a `ProviderWireRequest`.
3. Do not import application packages from custom handlers unless packaging is
   deliberately redesigned. Duplicate only the minimal versioned wire parser in
   the isolated environment and verify it against shared golden payloads.
4. Derive Reve `<img>N</img>` references, multipart order, and v2 `image_index`
   bindings from the same final selected sequence.
5. Preserve entity/state/scope labels and exact per-reference instructions for
   Gemini/Vertex and other edit routes.
6. Treat a missing, unreadable, or digest-mismatched selected ref as a hard
   contract error. Never skip it and shift later indices. Immutable staging is
   added in Slice 10; until then, verify source bytes immediately before upload.
7. Send native structured aspect and only the approved controls from Slice 06.
   Provider payload fields must agree with the wire request snapshot.
8. Preserve semantic manifests when Labs stages references. Anonymous numeric
   copies without a manifest are not acceptable.
9. Record post-response `actual_provider_model` separately when the provider
   supplies it. Never overwrite `requested_alias`, `expected_route`, or
   `configured_provider_model`.
10. Keep existing raw-prompt/raw-path callers working through a temporary,
    schema-discriminated legacy branch. Freeze its existing behavior with
    characterization tests, mark it deprecated, and prevent any new caller from
    adopting it. Legacy transforms must never run for a wire request. Record a
    complete caller inventory for Slices 11–12; removal occurs only after the
    final caller migrates.

## Tests first

- Golden wire snapshots for every production route with no refs and with
  representative preselected 1–4 ref plans.
- Identity-only, full-appearance, active-location, prop, style, and continuity
  instructions reach the handler byte-for-byte.
- Every Reve inline index maps to the expected digest and uploaded bytes.
- Gemini labels round-trip entity, state, scope, and facets.
- Handler cannot silently remove, reorder, relabel, or prose-wrap a reference.
- Wire requests cannot enter the legacy transform branch; legacy requests remain
  characterized until caller migration.
- Prompt over budget is rejected before handler invocation; no prefix slicing.
- Provider payload includes only supported aspect/control fields.
- Digest mismatch fails before network I/O.
- Labs staging round-trips the wire manifest.
- Configured and provider-reported actual model identities remain distinct.
- Diagnostic/dropped-candidate changes do not alter `execution_fingerprint`;
  any provider-affecting field does.

## Exit criteria

- Every migrated provider adapter can consume one exact, hashed wire request.
- For wire requests, prompt text, reference instructions, indices, order,
  dimensions, and controls are inspectable before transport and unchanged during
  serialization.
- Isolated handlers have no application-domain dependency or semantic freedom.
- The temporary legacy branch is schema-isolated, frozen, inventoried, and has no
  new callers.
- Focused backend/handler tests, full backend tests, and Ruff pass.

## Handoff to Slice 08

Write `handoffs/07.md` using the durable handoff template before replying.

Report the wire schema/version, execution-fingerprint projection, provider
snapshot fixtures, isolated-handler packaging contract, actual-model result
field, temporary legacy discriminator, and complete unmigrated-caller inventory.
Slice 08 will build alternate-asset lifecycle semantics on the stable wire path;
Slices 11–12 must retire the inventory before deleting the legacy branch.
