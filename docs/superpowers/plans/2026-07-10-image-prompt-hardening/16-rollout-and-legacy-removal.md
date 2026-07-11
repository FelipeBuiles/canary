# Slice 16 — Rollout, Legacy Removal, and Final Documentation

## Fresh-session assignment

Implement only this slice. Read `AGENTS.md`, the sibling `README.md`, this file,
all prior slice handoffs, the Slice 14 gate report, and the Slice 15 visual report
or explicit user-approved waiver. This is the final slice.

## Goal

Complete the clean cutover, remove obsolete prompt/reference authorities and
temporary comparison seams, document operation/extension of the new pipeline,
and independently verify that no bypass or state-consistency regression remains.

## Required reading

- all Slice 00–15 handoffs and test/evaluation reports
- every remaining use of legacy prompt/reference/model/metadata fields found via
  targeted `rg`
- project agent/reference documentation that describes image stages, aliases,
  prompt editing, rerendering, states, estimates, Labs, or Dev Content
- storage/GC, migration, and operational docs affected by frozen requests

## Deliverables

1. Confirm rollout gates before cleanup:
   - all Slice 14 deterministic thresholds pass;
   - Slice 15 shows no material canonical regression and improved alternate-state
     correctness, or the user has explicitly approved a documented waiver;
   - normal backend/frontend suites and builds pass.
2. Exercise no-cost request compilation/preview across every production alias
   and asset kind. Inspect a disposable fixture reconstruction of existing
   project artifacts; never mutate user projects for rollout testing.
3. Remove obsolete authorities and bypasses, including remaining forms of:
   - independently assembled generator-bound `full_prompt` strings;
   - stale `visual_brief`/layout preference logic;
   - authoritative persisted `reference_image_paths`;
   - duplicate route aliases/capability maps;
   - provider-side prompt prefixes, truncation, reference caps, or sorting;
   - raw prompt plus arbitrary mutable-path transport helpers;
   - partial/conflicting generation metadata writers;
   - approximate preview reconstruction presented as exact;
   - temporary Labs dual-compiler comparison code.
4. Retain old fields only when they have an explicit historical/editing purpose.
   Rename ambiguous retained fields so they cannot be mistaken for generation
   authority. Do not add legacy shims by default.
5. Add existing-project guidance:
   - which stored prompt JSON must be regenerated;
   - how unverified/stale state assets are surfaced and regenerated;
   - how cache identity changes affect existing panels;
   - request/blob storage retention and safe cleanup;
   - why internal schema compatibility is intentionally not preserved.
6. Document the final lifecycle:
   - canonical IR and protected anchors;
   - state-aware overlays and freshness;
   - model profiles and ReferencePlan selection;
   - compiled request, provider wire, immutable submission, and hashes;
   - alternate character/location state inheritance and authority facets;
   - exact preview/provenance and Dev Content;
   - provider extension rules, including isolated-handler constraints;
   - golden corpus and safe Labs evaluation workflow.
7. Correct stale model/route labels everywhere. Keep model names, hashes, ids,
   and other machine vocabulary behind Dev Content in the product UI.
8. Define rollback as reverting the clean-cutover change set and preserving
   generated artifacts/provenance. Do not keep a permanent runtime legacy path
   solely for rollback.
9. Run a fresh verifier whose remit is to find provider bypasses, post-compile
   mutations, state contradictions, stale lineage, cache errors, and misleading
   previews. Use a security reviewer for request/blob authorization, redaction,
   retention, and any signed-reference behavior.

## Tests and verification

Run focused legacy-removal/architecture tests and then, from repository root:

```bash
rtk uv run --directory novel_to_comic pytest -q
rtk uv run --directory novel_to_comic ruff check src tests
rtk npm --prefix web test
rtk npm --prefix web run lint
rtk npm --prefix web run build
rtk git diff --check
```

Do not run additional paid evaluation in this slice unless the user separately
authorizes it.

## Exit criteria

- Deterministic and required visual rollout gates are satisfied or explicitly
  waived by the user with the limitation documented.
- One production lifecycle owns image prompt/reference compilation and transport.
- All generated image classes have common, redaction-safe provenance.
- Legacy authorities, provider mutations, temporary comparison seams, and raw
  transport bypasses are removed.
- Existing-project regeneration/storage guidance is complete.
- Route labels and capability descriptions are truthful throughout code/UI/docs.
- Normal tests, lint, build, and diff checks pass.
- Independent verifier reports `CONFIRMED`; security review is complete where
  required.

## Final handoff

Write `handoffs/16.md` using the durable handoff template before replying.

Produce a concise completion record containing:

- final architecture and intentional deviations from the plan;
- files/contracts removed and retained historical fields;
- tests/build commands and results;
- Slice 14 deterministic gate report;
- Slice 15 experiment authorization, cost, results, or approved waiver;
- remaining provider limitations, especially reference-slot constraints;
- migration/regeneration and blob-retention guidance;
- verifier/security-review outcomes;
- follow-up reliability work explicitly deferred from this initiative.
