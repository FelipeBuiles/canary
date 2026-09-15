# Canary — Agent Guidelines

Canary turns novels into complete, lettered comic pages. Start from the reported
symptom and relevant code/tests. Use [agent context](docs/reference/agent-context.md#code-navigation)
for navigation, [stage contracts](docs/reference/stage-contracts.md) for a touched
artifact boundary, and [CONTEXT.md](CONTEXT.md) for unfamiliar domain terms.
Read relevant ADRs when an architectural decision is involved. These are lookup
resources, not a mandatory onboarding sequence; reuse context already loaded.
[Documentation policy](docs/README.md) distinguishes current evidence from plans.

## Guardrails

- The active stages are `extract → brief → style → cast → adapt → plan → draw → finish`.
  `state.py` and `stages/__init__.py` are authoritative. Checkpoints are
  `brief`, `style`, `cast`, and `draw`.
- The CLI supports only `init` and `serve`. Run, approve, status, correction,
  and export operations use HTTP APIs. Never suggest `pipeline run` or
  `pipeline approve` CLI commands.
- Keep stage artifact boundaries; stages do not call one another. Server
  orchestration owns the explicit auto-chain.
- Preserve visual anchors and continuity guards verbatim. State IDs are
  entity-scoped; Plan maps each visible entity to its state explicitly.
- New full-page Draw profiles generate base art with Plan-owned lettering
  reservations, never Canary's publishable copy or balloon/box shapes. Pages
  lettering owns editable presentation; Finish uses the same canonical SVG.
  Retained baked-text profiles remain readable/reviewable/exportable without
  overlays or hash migration. Do not revive panel generation or a Compose stage.
- `TargetArtifacts` owns current full-page paths and typed reads/writes.
  Breaking schema changes are acceptable. Reject incompatible artifacts with
  a rerun instruction; do not add compatibility hash exceptions or shims.
- Keep model aliases and pricing in configuration. A Draw edition has one
  fixed profile; do not silently upgrade existing pages to a different model.
- Request hashes identify input, not guaranteed provider deduplication.
  Avoid automatic retries after ambiguous paid image submissions.
- OCR proves only its lettering checks. Visual concerns require visual review;
  creating a revision alone must not mark them verified.
- Stage `run()` receives `StageRuntime` as `ctx`; use its logging, progress,
  item accounting, and events rather than parallel lifecycle implementations.
- Post-style generation requires a selected style. UI gating uses the status
  API's `style_selected` field.
- Keep identity references on less-graphic redraws. Reject reference overflow
  before spend; never silently discard required authorities.
- User-facing credit estimates use `~N credits`. Keep provider costs, unknown
  usage, estimates, and charged credits distinct.
- Work in this shared checkout; preserve other edits. Do not create a separate
  worktree for routine changes.

## Navigation and checks

Python source root: `novel_to_comic/src/novel_to_comic/`. The page pipeline is
implemented by `book_adaptation.py`, `page_planning.py`, `page_drawing.py`,
`page_review.py`, and `page_finishing.py`. Provider-free lettering lives in
`page_lettering.py`, `lettering_service.py`, and the Pages lettering workspace. Cast state conditioning is in
`state_assets.py`; gateway serialization is in root
`litellm_handlers/vertex_multimodal.py`. Frontend rooms live in
`web/src/pages/rooms/`.

Use targeted `rg` searches; exclude generated outputs, dependencies, lockfiles,
and logs unless directly relevant. Issues and PRDs live in GitHub
`FelipeBuiles/canary`; consult [issue conventions](docs/agents/issue-tracker.md)
and [labels](docs/agents/triage-labels.md) when working with tickets.

## Debugging and verification

Reuse the reported failure, existing tests, and captured evidence. Inspect code
and logs to choose the smallest useful check. Build a harness, minimize a repro,
or expand hypotheses only when it resolves uncertainty. Keep reproduction loops
provider-free; paid generation and ambiguous submissions retain the guardrails above.

- Backend: start with `novel_to_comic/.venv/bin/python -m pytest novel_to_comic/tests/test_<area>.py -q`
  (substitute the relevant test file; use `-k` to narrow further).
- Frontend: in `web/`, use `npm test -- src/__tests__/<area>.test.tsx` for the
  affected behavior. Run `npm run build` for TypeScript/bundling changes and
  `npm run lint` for frontend source changes.
- Docs: run `python3 scripts/check_docs_reliability.py`. Regenerate affected
  generated references with `python3 scripts/update_docs.py` after source changes.
- Broaden to the backend suite (`novel_to_comic/.venv/bin/python -m pytest novel_to_comic/tests -q`)
  or frontend suite (`npm test` in `web/`) for shared contracts, integration impact,
  or release requirements. Do not repeat passing checks without a relevant change
  or unresolved concern. Mocked tests do not establish image quality.

## Working agreements

Carry authorized work through implementation and relevant verification. Make
routine reversible decisions locally; ask when missing information affects
correctness, scope, or authorization. Preserve unrelated edits in this shared
checkout. Report the result, checks performed, and remaining uncertainty.

Explicit user instructions take precedence over skill guidelines, subject to
higher-priority instructions and permission boundaries. If a skill causes a
pause or deviation, identify the file and exact rule and continue unaffected work.
