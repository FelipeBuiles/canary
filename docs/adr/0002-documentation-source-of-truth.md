# ADR 0002: Documentation source-of-truth hierarchy

**Status:** Accepted  
**Date:** 2026-07-18

## Context

The repository contains runtime code, tests, generated references, agent
instructions, proposals, plans, and handoffs. Several of these repeated the
same pipeline and workflow claims. As implementation changed, duplicated prose
became contradictory and agents could not tell which document was normative.

## Decision

Documentation claims are governed by this order:

1. Executable implementation and tests.
2. Checked-in configuration and fixtures.
3. Focused reference documentation in `docs/reference/`.
4. `AGENTS.md` and `CLAUDE.md` for guardrails and pointers.
5. `CONTEXT.md` for domain vocabulary only.
6. Proposals, plans, handoffs, and other historical material.

Documents use `Current`, `Historical`, `Proposed`, or `Superseded` status labels
when they describe more than navigation. Generated references must identify
their generator and be regenerated instead of edited manually.

## Consequences

Reference docs can explain current behavior without making the glossary or
agent entrypoints duplicate implementation contracts. Historical rationale is
preserved, but it cannot override code, tests, or current references. Mechanical
checks may verify high-risk facts such as stage metadata, command names, and
documentation links; prose semantics remain a human review responsibility.
