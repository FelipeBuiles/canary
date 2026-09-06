## Delegation and model-cost policy

The main agent is the orchestrator. Preserve its context and model usage for planning,
architectural decisions, ambiguity resolution, integration, and final verification.

For any non-trivial task, actively look for work that can be delegated to subagents.

Prefer the `worker` agent for:
- repository exploration and codebase searches
- reading many files
- tracing implementations or call chains
- implementing well-scoped changes
- repetitive or mechanical edits
- test execution and investigation of failures
- large refactors after the approach has been decided
- documentation generation
- summarizing large outputs
- independent research
- first-pass code review

The main agent should normally:
1. understand the user's goal;
2. decide the approach and decompose the work;
3. delegate substantial execution work to `worker`;
4. inspect the worker results;
5. resolve difficult decisions or inconsistencies itself;
6. perform a final review and answer the user.

Do not delegate tiny operations where delegation overhead exceeds the work.

Prefer parallel workers for independent tasks.

Workers are execution resources, not decision makers. Do not blindly accept their
conclusions; verify important changes before presenting the final result.

Use `worker` for normal delegated implementation, exploration, tests,
and mechanical work.

Use `deep-worker` for difficult debugging, architecture analysis,
large refactors, or tasks where substantial reasoning is valuable.

Prefer worker unless deep reasoning is actually needed.

# Canary — Agent Guidelines

Canary turns novels into complete, lettered comic pages. Read `CONTEXT.md` for
vocabulary, relevant `docs/adr/` decisions, and `docs/README.md` for source
hierarchy. Implementation and tests outrank historical plans and proposals.
Current runtime navigation: `docs/reference/agent-context.md`. Artifact
contracts: `docs/reference/stage-contracts.md`.

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
- Full-page Draw includes exact lettering authored by Adapt. Do not revive
  text-free panel generation, legacy panel stages, or compose-editor contracts.
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
`page_review.py`, and `page_finishing.py`. Cast state conditioning is in
`state_assets.py`; gateway serialization is in root
`litellm_handlers/vertex_multimodal.py`. Frontend rooms live in
`web/src/pages/rooms/`.

Use targeted `rg` searches; exclude generated outputs, dependencies, lockfiles,
and logs unless directly relevant. Backend tests use
`novel_to_comic/.venv/bin/python -m pytest novel_to_comic/tests -q`.
Frontend checks: `npm test`, `npm run build`, `npm run lint` in `web/`.
Documentation checks: `python3 scripts/check_docs_reliability.py`.

Issues and PRDs: GitHub `FelipeBuiles/canary`, via `gh`; see
`docs/agents/issue-tracker.md` and `docs/agents/triage-labels.md`. Domain guidance:
`docs/agents/domain.md`. Launch branding research is proposed material in
`docs/proposals/branding-and-marketing.md`, not a runtime contract.

### Task Execution & Autonomy
- For implementation or fix requests, carry the authorized work through implementation and relevant verification. Do not stop at a proposed plan when you can proceed.
- Make reasonable assumptions for routine, reversible decisions. Ask a focused question when missing information materially affects correctness, scope, or authorization.
- Continue with authorized read-only actions, local worktrees, branch edits, and appropriate tests without repeatedly asking.
- Before requesting approval, finish the preparation that is already authorized and present a concrete, reviewable result.
- Respect required approval gates. Ask before destructive, irreversible, or otherwise unauthorized actions.
- Avoid boilerplate warnings about hypothetical risks. Explain concrete blockers or material risks when relevant.
### Instruction Conflicts
- Explicit user instructions take precedence over conflicting skill guidelines, subject to higher-priority instructions and actual permission boundaries.
- If a skill causes a pause or deviation, identify the file and relevant rule, and explain whether it is an explicit requirement or your interpretation. Continue any unaffected authorized work.
### Style & Output
- Lead with the result. Use plain language, active voice, and concise paragraphs. Include technical details that help assess the work.
- Use lists when they improve readability; avoid repetitive transitions and stock phrases such as "it's worth noting", "delve", "leverage", and "Bottom line".
- Report what changed, what was verified, and any remaining uncertainty.
### Verification
- Match verification to the scope and impact of the change. Complete required checks; expand testing when a concrete unresolvedconcern justifies it.