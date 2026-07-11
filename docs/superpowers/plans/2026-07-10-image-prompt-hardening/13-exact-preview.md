# Slice 13 — Exact Request Preview and Dev Content Inspection

## Fresh-session assignment

Implement only this slice. Read `AGENTS.md`, the sibling `README.md`, this file,
and verify Slice 12's all-asset provenance coverage. Do not begin Slice 14.

## Goal

Let developers inspect the exact prepared/submitted generation request and its
provenance, while clearly distinguishing a free draft projection from a request
that has actually been prepared and frozen.

## Current problem

The UI can display `full_prompt`, distilled text, visual brief, stored reference
paths, or model labels that are adjacent to—but not necessarily identical to—the
request consumed by generation. An “exact preview” can also hide a prompt-model
call if preparation is not already complete.

## Required reading

- Slices 10–12 frozen request and provenance APIs/handoffs
- `novel_to_comic/src/novel_to_comic/server/routers/pipeline.py`
- `novel_to_comic/src/novel_to_comic/server/deps.py`
- panel detail modal, prompt lineage card, Dev Content gating, API hooks, and
  prompt-warning components under `web/src/`
- auth/project-resolution, route-response, and panel modal tests

## State labels

Every API/UI representation must use one of these labels:

- **Draft projection:** free deterministic projection from current persisted
  inputs; not exact if prompt/layout preparation remains outstanding.
- **Prepared request:** all derivation complete and exact wire request known, but
  image work not yet submitted.
- **Submitted request:** immutable manifest accepted for queued/provider work.
- **Completed request:** submitted request paired with result/failure provenance.

Never label a draft projection “exact.”

## Deliverables

1. Add a no-cost read/preview endpoint that performs no prompt-model or image
   call. It returns the current deterministic projection, final ReferencePlan
   where available without paid derivation, warnings, and a clear exactness/state
   label.
2. If exact pre-submission review requires asynchronous prompt preparation, add
   an explicit prepare action with disclosed estimated cost/credits and existing
   auth/accounting. It prepares once, freezes or persists the exact request, and
   returns its request id/fingerprint without silently starting image generation.
3. Let the normal generation submission either consume a still-current prepared
   request or prepare/freeze exactly once as part of the explicit generate
   action. Any authoritative edit or source-lineage change invalidates a prepared
   request and requires a new fingerprint.
4. Add authorized read endpoints for submitted and completed request records.
   Return redaction-safe structured data, never server paths, credentials, signed
   URLs, or cross-project blob locators.
5. Behind Dev Content, show:
   - state label and exactness;
   - exact semantic and provider-wire prompt fields;
   - protected anchors and source ids;
   - requested alias, expected route, configured target, and actual model only
     after a provider reports it;
   - requested aspect, effective dimensions, and actual result dimensions;
   - ordered refs with roles, entity/state ids, scopes/facets, digests, and exact
     instructions;
   - dropped refs/reasons and warnings;
   - supported/filtered controls;
   - compiler/wire versions, request ids, hashes, and execution fingerprint.
6. Keep the default product UI free of model names, hashes, internal entity ids,
   and machine-only vocabulary. Preserve the existing panel editing experience.
7. Make the displayed submitted wire representation byte-equivalent to the
   frozen manifest and adapter input. Do not reconstruct it from separate fields
   in the frontend.
8. Remove or relabel old approximate prompt/reference/model previews so none can
   be mistaken for the authoritative submitted request.

## Tests first

- Draft projection performs no prompt/image model call and is labeled
  non-exact when preparation is outstanding.
- Prepared, submitted, and completed transitions retain one execution
  fingerprint when inputs do not change.
- Authoritative edit/source change invalidates the prepared request.
- Explicit prepare discloses/uses the expected accounting contract and never
  starts image generation by itself.
- Dev Content submitted prompt/ref order/digests/dimensions/controls are
  byte-equivalent to frozen manifest and adapter fixture.
- Actual model/dimensions appear only after result provenance exists.
- Default API/UI omits machine-only details; Dev Content exposes them.
- Unauthorized/cross-project request access is rejected and no sensitive path or
  credential leaks.
- Old approximate fields are absent or clearly labeled historical/derived.

## Exit criteria

- Users can distinguish free projection from exact prepared/submitted data.
- No preview endpoint silently incurs a paid call.
- Dev Content reads the authoritative record rather than rebuilding it.
- Exact submitted preview, immutable manifest, and adapter input agree.
- Machine details remain gated and authorized.
- Focused backend/frontend tests, full backend tests, Ruff, frontend test/lint/
  build, and security review where needed all pass.

## Handoff to Slice 14

Write `handoffs/13.md` using the durable handoff template before replying.

Report preview/prepare/read endpoint contracts, state-transition rules,
redaction/auth behavior, UI locations, removed approximate views, and parity
tests. Slice 14 will turn all core contracts into a compact deterministic golden
corpus and CI gates.
