# Documentation map

## Status labels

- **Current** — verified against implementation, tests, and configuration.
- **Historical** — records a past decision or migration; not normative.
- **Proposed** — future intent; not evidence of current behavior.
- **Superseded** — retained only when uncaptured rationale remains, and points
  to the replacing source.

Documents without an explicit status are navigation or reference material and
must not make claims that conflict with executable code or tests.

## Source-of-truth hierarchy

When sources disagree, use this order:

1. Executable implementation and tests.
2. Checked-in configuration and fixtures.
3. Focused reference documentation in `docs/reference/`.
4. `AGENTS.md` and `CLAUDE.md` for guardrails and pointers.
5. `CONTEXT.md` for domain vocabulary only.
6. Proposals, plans, handoffs, and other historical material.

Generated references identify their generator and must be regenerated rather
than edited by hand.

By default, files under `docs/proposals/` and `docs/superpowers/` are
**Proposed**, and files under `docs/handoffs/` are **Historical**. Add a more
specific status when a document is intentionally promoted, superseded, or
retained as current reference.

## Current contracts and capability evidence

- [Stage contracts](reference/stage-contracts.md): source-owned stage authority,
  user gates, correction jobs, recovery, and generated-output compatibility.
- [Agent context](reference/agent-context.md): concise workflow and code navigation.
- [Codex development capability report](reference/codex-dev-capabilities.md):
  implemented local adapter configuration, restricted execution/funding contracts,
  and scoped live evidence, including experimental complete-page Draw. This is
  not a production deployment or model-quality guarantee.

## Active future work

- [Self-service launch strategy](proposals/self-service-launch.md): September 9
  commercial direction, independent-use gates and automation priorities.
- [First-scene campaign kit](proposals/first-scene-campaign.md): prepared copy,
  measurement and bounded spend proposal; not an activated campaign.
- [Launch readiness](proposals/launch-readiness.md) and
  [pricing](proposals/pricing-and-margin.md): current implementation evidence
  and unresolved production/commercial checks.

Only active, accepted, or genuinely pending design work should remain under
`docs/superpowers/`:

- full-page implementation plan:
  `docs/superpowers/plans/2026-07-25-full-page-generation/README.md`

The full-page pipeline design itself is no longer kept as a document: its
durable decisions are recorded as ADRs 0003–0015 in `docs/adr/`, and its
contracts are enforced by implementation and tests.

Completed implementation plans and superseded designs should be deleted once
their durable contracts are represented by implementation, tests, reference
documentation, or ADRs. Do not retain them merely as narrative history: stale
plans are especially likely to mislead coding agents.

## Reliability check

Run `python3 scripts/check_docs_reliability.py` after changing stage metadata,
CLI commands, generated references, or documentation links. It checks only
facts that can be compared mechanically; it does not replace a documentation
review.
