# Slice 11 — Panel Caller Convergence and Provenance

## Fresh-session assignment

Implement only this slice. Read `AGENTS.md`, the sibling `README.md`, this file,
and verify Slice 10's immutable-submission tests. Do not begin Slice 12.

## Goal

Route every production panel path through the same prepare, resolve, compile,
wire, freeze, and transport lifecycle, and persist a common panel-generation
provenance envelope.

## Current problem

Initial draw, batch draw, manual rerender, instructed rerender, estimates, cache
checks, and Labs can each reconstruct overlapping pieces of a request. This
allows stale derived fields, different reference selections, different counts,
or metadata that cannot explain what the provider received.

## Required reading

- Slices 01–10 handoffs
- `novel_to_comic/src/novel_to_comic/prompt_assembly.py`
- `novel_to_comic/src/novel_to_comic/panel_store.py`
- `novel_to_comic/src/novel_to_comic/stages/s6_storyboard.py`
- `novel_to_comic/src/novel_to_comic/stages/s7_draw.py`
- `novel_to_comic/src/novel_to_comic/server/routers/pipeline.py`
- `novel_to_comic/src/novel_to_comic/server/routers/labs.py`
- panel cache, rerender, estimate, Labs, credits, and failure-metadata tests

## Deliverables

1. Establish explicit lifecycle functions, for example:
   - `prepare_panel_prompt(...)`: content freshness, overlay application, and any
     asynchronous visual-brief/layout hydration;
   - `resolve_panel_references(...)`: final Slice 04 `ReferencePlan`;
   - `compile_panel_request(...)`: pure compiled and wire requests;
   - `submit_panel_request(...)`: Slice 10 immutable staging/job submission.
2. Use that lifecycle for first draw, batch draw, manual edit rerender,
   instruction-based rerender, plain rerender, and retry after a failed job.
3. Prepare derived prompt/layout data once per submitted request. A queued job
   must never repeat an LLM call. Preserve Slice 01's invalidation rules.
4. Make cost estimates use the same route profile, final reference plan, target
   dimensions, and provider pricing inputs. If a prompt is already prepared,
   expose its execution fingerprint. If exact preparation would require a paid
   model call, return a clearly labeled provisional estimate without making that
   call or claiming exact-request parity.
5. Give Labs a production-equivalent panel mode that uses the same lifecycle.
   Experimental changes must be explicit compiler inputs and produce a different
   attributable request, not a hidden alternate assembly path.
6. Make panel cache identity use `execution_fingerprint`. Selected-byte changes,
   prompt-source changes, state changes, target geometry, or controls invalidate;
   diagnostic-only/dropped-candidate changes do not.
7. Persist a panel result provenance envelope containing:
   - prepared prompt source and compiler versions;
   - compiled and wire request hashes;
   - exact submitted request id/execution fingerprint;
   - selected immutable reference digests/order/roles/scopes/facets;
   - dropped candidates and warnings outside execution identity;
   - requested alias, expected route, configured target, and provider-reported
     actual model when available;
   - requested/effective dimensions and actual returned dimensions;
   - provider result id, timing, cost, and failure data where safe;
   - a deterministic provenance-record hash excluding timestamps where required
     by its canonicalization contract.
8. Replace panel-specific partial metadata writers with the common envelope.
   Preserve actionable failure records even when no image is produced.
9. Remove old panel-only final-prompt reconstruction, ref selection/counting, and
   cache-key helpers once all callers are migrated.

## Tests first

- Initial draw and plain rerender compile the same request for unchanged inputs.
- Manual/instructed edits invalidate and reprepare exactly once.
- Batch and single-panel draw use byte-equivalent wire requests per panel.
- Prepared estimate and submitted request agree on route, reference plan,
  dimensions, controls, cost inputs, and fingerprint.
- Unprepared/provisional estimate makes no prompt-model call and is labeled.
- Labs production-equivalent mode matches production; explicit experiment input
  changes are attributable.
- Selected byte/path-same replacement invalidates cache; diagnostic-only change
  does not.
- Queued job uses the frozen request even if panel/project data changes.
- Success and failure provenance contain the required envelope and distinguish
  configured from actual provider model.
- Architecture test finds no panel generation entry point bypassing submission.

## Exit criteria

- Every panel generation path shares one authoritative lifecycle.
- Estimate limitations are explicit and never hide a paid preparation call.
- Cache identity matches exact provider-affecting inputs.
- Panel result/failure provenance reconstructs the submitted request.
- Legacy panel request builders and partial metadata paths are gone.
- Focused tests, full backend tests, Ruff, and affected Labs/credit tests pass.

## Handoff to Slice 12

Write `handoffs/11.md` using the durable handoff template before replying.

Report lifecycle entry points, every migrated panel caller, provisional versus
prepared estimate contract, cache projection, common provenance schema, storage
locations, and removed legacy helpers. Slice 12 will apply the same envelope and
submission contract to non-panel image assets.
