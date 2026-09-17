# PR #5 — merge-readiness review, 2026-09-16

Status: Historical review evidence. Executable tests, current PR checks and ADR 0021 remain authoritative.

## Verdict and scope

Reviewed starting head `9eace5403755a2a07013d17522e0249e5ae19a35`, including the style-suggestion and v2 typography follow-up. That head had green CI and no submitted reviews. This pass inspected generation/reservation contracts, canonical-source and raw-art boundaries, saved presentation and review identity, font/layout/composition, revision conflicts, and Finish/Book delivery.

Two correctness gaps were reproduced and fixed in `b8313d74ef954cb397d00e98f75395a437b104df`. No remaining technical merge blocker was identified in this pass. Normal CI must be green on the actual final PR head before merge. Live hybrid-page visual acceptance remains separate: technical export success is not proof that an image model honored its quiet-space reservations or that every edited page matches the reference artwork.

No paid provider calls, production deployment, or merge were performed.

## Corrections

### Missing glyphs could silently use system fonts

The previous script checks accepted, for example, emoji with EB Garamond, Cyrillic with Comic Neue, and some Chinese characters missing from M PLUS 1p. A successfully loaded font does not guarantee that it contains a character; fallback output can vary by machine or produce missing-glyph boxes.

The shared v3 engine validates exact codepoint coverage generated from the eight bundled fonts' Unicode cmap tables. Both browser and isolated server compositor use the same table. Coverage generation uses Python's standard library, stores source-font hashes and has a drift regression test. No fonts, providers, or dependencies were added.

`missing_glyphs` is visible in Lettering and blocks Finish as a recoverable `lettering_layout` error. It does not request an artwork redraw. Existing v2 resolved layouts require explicit reflow/save, so validation cannot be bypassed through a stale composite.

### Changed presentations could retain old visual acceptance

An unreviewed copy/layout/locale save or a book-style reflow could inherit the previous artwork-review markers. Those markers now survive only an unchanged presentation or an explicit reviewed save. Style and engine reflows clear acceptance; new artwork is checked against both its image hash and render revision. Client-supplied review markers and resolved geometry remain untrusted.

Finish validator v6 exposes `lettering_placement_review_needed` independently of technical failures. Book shows a user-visible placement-review section and direct Lettering link even when developer diagnostics are disabled. Unreviewed placement remains exportable for inspection. It is not silently described as accepted, nor turned into an unnecessary paid Draw correction.

## Recent fixes retained and checked

The style-suggestion contract still requires `lettering_preset` on each candidate, not at the batch root. Invalid structured replies can be repaired within the existing bounded two-call budget; validation was not loosened.

The v2 geometry/typography improvements are retained: measured glyph extents, contour-aware line partitioning, compact fitted dimensions, persisted line positions, readable font floors, and continuous body/tail paths. Serif narration and speech remain the Literary classic preset; existing custom styles require deliberate preset changes rather than silent restyling.

Regression coverage still protects source copy, raw artwork, retained baked editions without duplicate lettering, revision/style/art conflicts, first multi-page export, saved lines across browser/server, and editor recovery/undo.

## Verification

Local full backend suite: **1,769 passed, 18 skipped** with Python 3.13 and locally available Chromium. Local full frontend suite: **79 files, 490 tests passed**. Ruff, ESLint, TypeScript/Vite production build, generated documentation, documentation reliability, font coverage drift and whitespace checks passed.

The four new lifecycle/font regressions first failed on the starting head and passed after correction. Actual bundled-font Chromium tests verify browser/server geometry parity, glyph containment and 288 tail direction/rotation/scale combinations.

The complete published correction patch is checksum-verified against the local tested patch: `56d4ce9d7bf37cecdfed34d563a04ac4d9a16a348d5d8543303675232d01701e`. The isolated verification workflow (run `35130189217`) passed with Python 3.12, the pinned Playwright Chromium and Node 20 before publishing. Its transport and workflow changes are not part of PR #5's production diff. The ordinary PR CI result on the final head remains the merge gate.

## Visual evidence and remaining acceptance

The review produced a side-by-side reference/actual-compositor proof: identical short and long speech copy, plus comparable-density serif and sans narration. It also rendered editable speech onto an untouched, previously silent crop from the supplied reference page. These are actual compositor outputs, not mocked text metrics; the second fixture is not a newly generated hybrid page. The images were provided with the review response rather than adding the user's reference images to the repository.

The inspected output has compact captions, balanced short/two-line and longer/four-line speech, clear padding and integrated tails. Font/style identity is not pixel-identical to the generative references, and fixed-caption bounds still need sensible page-specific placement.

Before calling the feature publication-quality, inspect representative live hybrid outputs: a dense multi-panel narration page, a dialogue-heavy page with long and short speech, and a longer supported-locale copy variant. Confirm quiet regions actually exist, no unwanted model-drawn comic text/boxes appear, faces and focal artwork stay visible, reading order and speaker tails are clear, and reader/export match the saved composition. Adjusting lettering is provider-free; regenerate artwork only for an actual artwork/reservation failure. Review and save against the current artwork to clear the new Book reminder.
