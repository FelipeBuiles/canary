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
- `draw`: requested page structure, optional text-check evidence, reference identity, appearance
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
unaccounted source units and lettering changed by Plan. Examples of editorial issues include rushed aftermath, weak
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


## Optional text review (2026-09-14)

Automated OCR is advisory. On the reviewed 44-page edition, 36 checks did not
complete and the five pages flagged by completed checks contained OCR word
substitutions rather than the reported artwork mistakes. Exact transcription
agreement is therefore not a proven artwork invariant.

Draw and correction jobs produce artwork without automatic OCR or its credit
hold. Readers can explicitly check saved pages, inspect the disputed image
regions and script, and dismiss suggestions. An unavailable check remains
unchecked. Existing OCR findings remain recorded but cannot block Draw approval
or Finish; they are not automatically selected for redraw. Finish reads retained
analysis without running or repairing it. File integrity, active artifact lineage,
production requirements and non-OCR review decisions remain enforced. Packaging
never certifies text accuracy or visual quality.

A replacement OCR engine requires a small, manually reviewed comic benchmark;
changing the model alone does not restore a mandatory verification gate.
