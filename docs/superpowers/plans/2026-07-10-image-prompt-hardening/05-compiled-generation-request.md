# Slice 05 — CompiledGenerationRequest and Role-Aware Prompt Compilation

## Fresh-session assignment

Implement only this slice. Read `AGENTS.md`, the sibling `README.md`, this file,
and verify Slice 04's complete reference-policy matrix. Do not begin Slice 06.

## Goal

Introduce one provider-independent compiled request that combines the canonical
prompt IR with the already-final `ReferencePlan`. It must contain exact prompt
sections and exact per-reference semantic instructions without performing
provider serialization or I/O.

## Current problem

- final prompt bodies can be assembled independently in direct, draw, rerender,
  Labs, and provider helpers;
- the global reference guard treats characters, locations, props, style, and
  continuity as though they have the same authority;
- location guidance can say to ignore backgrounds, while the location plate is
  specifically intended to preserve a setting;
- identity-only references can accidentally demand canonical wardrobe or body
  state;
- configured route identity is often presented as though it were observed
  provider execution identity.

## Required reading

- Slice 00 route profile and Slice 04 reference-plan handoffs
- Slice 02 canonical prompt IR and renderer
- Slice 03 prompt preparation/freshness entry point
- `novel_to_comic/src/novel_to_comic/prompt_assembly.py`
- `novel_to_comic/src/novel_to_comic/prompting.py`
- `novel_to_comic/src/novel_to_comic/prompt_instructions.py`
- `novel_to_comic/src/novel_to_comic/panel_aspect.py`
- direct, draw, rerender, and visual-brief tests

## Domain contract

Add a typed `CompiledGenerationRequest` in the narrowest shared application
module. It should include at least:

- compiler/schema version;
- `requested_alias`, `expected_route`, and `configured_provider_model` as
  distinct fields;
- asset kind and semantic asset identity;
- selected style text/spec identity and its source hash when style is an input;
- exact ordered prompt sections and exact final semantic prompt string;
- protected anchors and source identifiers;
- the final ordered `ReferencePlan` selection;
- one exact semantic instruction per selected reference;
- requested generation shape and effective target dimensions;
- typed provider-control intentions, initially empty/default where Slice 06 has
  not yet verified support;
- prompt source SHA, reference selection fingerprint, warnings, and deterministic
  fallback decisions;
- a deterministic `compiled_request_sha256` over provider-independent execution
  fields, excluding diagnostics and timestamps.

Do not include credentials, signed URLs, transient upload ids, provider response
objects, or an `actual_provider_model` field. Actual execution identity belongs
to result provenance after transport.

## Deliverables

1. Make compilation a pure function of prepared canonical IR, selected active
   style spec/text, final `ReferencePlan`, route profile, generation shape, and
   explicit control intentions. No file discovery, LLM call, persistence, or
   provider call occurs inside it. A generation-time style change may leave the
   stored prompt source hash unchanged, but it must change the compiled request
   whenever provider-bound style content changes.
2. Compile prompt sections in one stable order. Protected anchors must appear
   byte-for-byte and may not be transformed by formatting helpers.
3. Delete the generic all-reference guard. Compile instruction text by scope and
   explicit facets:
   - full appearance: match active face/hair/build/anatomy/wardrobe facets;
   - identity only: preserve only named compatible identity facets and ignore
     named active-state conflicts;
   - location identity: preserve only architecture/landmarks/materials that the
     active state does not replace; the active damage/weather/time anchor wins;
   - prop identity: preserve the object and ignore its reference backdrop;
   - style only: preserve medium/mark-making/palette and ignore depicted content;
   - continuity: preserve only facets explicitly compatible with current states.
4. Keep active state anchors authoritative even if a reference instruction or
   canonical image suggests otherwise. Add compiler validation for contradictory
   scopes/facets and fail before transport.
5. Do not render provider-specific tags such as Reve `<img>N</img>` here. Store
   exact ordered semantic sections/instructions so Slice 07 can serialize them
   without inventing prose.
6. Make the compiler usable by panel and non-panel asset kinds, while allowing
   explicit schemas per kind instead of a bag of optional strings.
7. Replace only parallel final-prompt assembly that can be migrated without I/O
   changes. Do not migrate provider adapters or all callers yet.

## Tests first

- Long sentinel character, location, state, and prop anchors survive exact.
- A visual brief that omits or contradicts identity cannot alter protected
  sections.
- Full-appearance, identity-only, location-state, prop, style, and continuity
  instructions name the correct preserved/ignored facets.
- Collapsed-building, drained-lake, and day/night state anchors overrule
  incompatible canonical location facets.
- No generic “ignore all backgrounds” or “match all wardrobe” instruction
  remains.
- Same inputs serialize identically and produce the same compiled hash.
- Style-only change updates compiled identity while leaving Slice 03's stored
  panel prompt-source identity unchanged under that contract.
- Changing warnings/dropped-candidate diagnostics alone does not change the
  provider-independent compiled request hash.
- Configured model fields never appear as provider-reported actual identity.
- Compiler performs no LLM, filesystem-discovery, persistence, or provider I/O.

## Exit criteria

- One pure provider-independent compiler owns final semantic prompt content and
  per-reference meaning.
- Every active anchor is exact and every reference instruction is role/state
  compatible.
- Reference selection/order remains exactly the Slice 04 plan.
- Focused tests, full backend tests, and Ruff pass.

## Handoff to Slice 06

Write `handoffs/05.md` using the durable handoff template before replying.

Report the compiled-request schema, canonical serialization, prompt-section
order, reference-instruction rules, configured route/model fields, and compiled
hash projection. Slice 06 may shorten only explicitly lower-priority sections;
it may never change protected anchors or reference selection.
