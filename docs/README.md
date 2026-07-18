# Documentation map

## Status labels

- **Current** — verified against implementation, tests, and configuration.
- **Historical** — records a past decision or migration; not normative.
- **Proposed** — future intent; not evidence of current behavior.
- **Superseded** — retained for rationale and points to the replacing source.

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

## Reliability check

Run `python3 scripts/check_docs_reliability.py` after changing stage metadata,
CLI commands, generated references, or documentation links. It checks only
facts that can be compared mechanically; it does not replace a documentation
review.
