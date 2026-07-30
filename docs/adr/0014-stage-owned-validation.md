# ADR 0014: Stage-owned validation

**Status:** Accepted  
**Date:** 2026-07-25

## Decision

Each pipeline stage validates the artifact it owns before that artifact can
advance. Finish performs an independent final book preflight, but it does not
become a second implementation of every upstream domain rule.

Validation ownership is:

- `extract`: immutable source-unit boundaries, order, offsets, primary scene
  ownership, gaps, and overlaps;
- `brief`: explicit user approval of adaptation intent and target page range;
- `adapt`: adaptation-ledger coverage, preserved narrative functions,
  causality, emotional continuity, transition completeness, and complete
  lettering;
- `plan`: global page rhythm, page-turn reveals, reading order, acceptable
  density, complete beat allocation, and unchanged lettering;
- `draw`: requested page structure, exact OCR, reference identity, appearance
  state, and generation-request fidelity;
- `finish`: cross-page consistency, unresolved issue status, production
  dimensions, bleed, color, ordering, packaging, and export integrity.

An error remains owned by the stage that created the invalid artifact. A
downstream stage may discover it and issue a structured correction request,
but does not silently repair or redefine the upstream source of truth.

## Consequences

Stage outputs include structured validation results that distinguish blocking
failures from reviewable issues and cite the affected canonical IDs. Validation
evidence is derived data, not a competing creative artifact.

Validation does not produce an aggregate quality score, confidence percentage,
or weighted retry threshold. A result is either:

- an **invariant failure**: a provable contract violation that blocks
  advancement; or
- an **editorial issue**: an evidence-backed creative concern citing the
  affected source and artifact IDs.

Examples of invariant failures include a source range ending mid-sentence,
unaccounted source units, lettering changed by Plan, and OCR that differs from
canonical copy. Examples of editorial issues include rushed aftermath, weak
reveal timing, questionable omission, redundant image and narration, or
confusing composition. Creative judgment is not represented as a synthetic
numeric score.

Unresolved editorial issues from Adapt and Plan are surfaced by exception at
the existing pre-Draw decision. They do not create another checkpoint. The user
may correct an issue or deliberately continue; invariant failures cannot be
overridden through that path.

This prevents late detection of source corruption, missing adaptation beats,
lettering truncation, page-density failures, or generation drift while keeping
Finish focused on the completed book and production export.
