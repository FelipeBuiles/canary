# ADR 0021: Full-page base art and independent lettering

Status: Accepted, implemented 2026-09-15. Supersedes the baked-lettering part
of the full-page Draw contract, not full-page generation or stage ownership.

## Prior contract

Adapt owns exact copy; Plan allocates it to semantic panels; Draw previously asked
one image request to typeset it. Immutable render revisions and Finish's derived
outputs are already separate. The historical Compose editor coupled page/panel
coordinates, drag optimism, and panel reframing, which made text editing fragile.

## Reused ideas, not the old architecture

Retain the bundled fonts, semantic style roles, SVG tails, explicit measured
lines, and Chromium rendering technique from the historical lettering work.
Discard the panel grid, raw-pixel authority, separate Compose stage, and panel
reframing. A single shared JavaScript layout/SVG engine serves browser editing
and server composition; there is no Python approximation of the overlay.

## Decision

New versioned Draw profiles request an entire text-free page, composed around
Plan's reservations. Retained baked profiles remain baked. Mutable, revisioned
`lettering/` artifacts link to canonical copy and live outside `draw/`. Changes
to wording, locale, placement or styling invalidate Finish, never paid art.
Finish combines unchanged render bytes and resolved lettering with the same
engine used by the editor, then uses its existing normalization/PDF/CBZ pipeline.

The editor is a Pages mode: a large page, a reading-order list, visible save
state, direct manipulation, deliberate undo boundaries, and draft recovery.
Canonical copy and suggested placement remain independently recoverable.
Stale source plans are explicitly reset, never silently overwritten; historical
lettering revisions remain available. Missing glyphs/overflow are visible errors,
not an excuse to shrink text indefinitely or spend on another image.


## Consequences and verification

New profiles explicitly opt into hybrid artwork; stored baked profiles are never
changed. Known retained baked editions have read/review/export support without
provider-wire migration or raster text removal. A new Plan/Draw lifecycle is
required to obtain reservations and a hybrid edition.

One JavaScript renderer avoids Python/React typography approximations. A
1000-unit vector page defines typography; persisted geometry is page-normalized.
Backend Chromium uses the same bundled fonts and returns resolved lines; browser
and export share those tokens and paths. The cost is a local Chromium dependency
and CPU work on uncached composition. Layout failure never falls back to a model.

Optimistic revision/image/style checks, archived states, account-scoped recovery,
and a project-level filesystem lock protect saves and export invalidation. These
locks assume the existing single-machine persistent filesystem architecture;
this does not add distributed multi-machine coordination.

Provider-free regression coverage includes prompt non-leakage, strict authoring
schemas, retained baked pages, immutable base art, revision conflicts, copy/locale
edits, style inheritance, first multi-page Finish, browser rendering, explicit
editor recovery, and saved-state undo. Synthetic browser inspection checks real
pointer handling, preview/export lines, and desktop/mobile layout. These checks
do not establish that an image provider consistently honors reservations or that
finished pages match the supplied artistic references; that requires explicit
live generation and human visual review. No paid provider calls are part of this
implementation verification.


## Typography acceptance correction (2026-09-15)

The first interaction/export checks did not establish an acceptable lettering
appearance. The supplied reference pages call for compact typography, smoothly
shaped speech balloons, and integrated tails, rather than generic rounded UI
rectangles. The v2 engine replaces the body/tail geometry and typesetting together.
It partitions words against per-line contour widths, uses measured glyph extents
for vertical centering, fits both dimensions, and persists the exact line positions.
The Literary classic preset now pairs serif narration with serif speech. Existing
saved styles require explicit preset selection; previous resolved layouts require
explicit reflow/save, not silent export changes.

`tests/test_lettering_typography.py` checks the real bundled fonts in Chromium:
short/two-line and longer/four-line speech, glyph containment in the actual SVG
contour, shared browser/server resolved metrics, 288 direction/rotation/scale tail
cases, and versioned export. Frontend tests cover fitted-edge resize/undo, continuous
transparent/colored silhouettes, readable floors, and layout-cache invalidation.
A local visual proof uses only unlettered crops from the supplied reference pages,
with the actual compositor. It does not remove raster lettering or pretend to be
a newly generated full page. Artistic parity and future generated-art reservation
adherence remain visual acceptance decisions, not consequences of passing tests.

Style suggestions also receive a regression correction: `lettering_preset` is a
required property of each candidate, and prompt wording explicitly forbids placing
it at the batch root. Invalid parsed responses can be corrected within the same
two-call budget used for portfolio completion; validation is not loosened.

## Merge-readiness corrections (2026-09-16)

Visual acceptance is scoped to both the saved lettering presentation and its
artwork. A copy/layout/locale change saved without explicit review, a book-style
reflow, or an engine reflow cannot inherit an earlier approval. Finish records
`lettering_placement_review_needed` separately from technical export invariants;
Book exposes the outstanding review and a direct Lettering link outside developer
mode. Unreviewed placement remains exportable for inspection, not certified as
publication-quality. New artwork still needs review even when the words remain.

The v3 engine retains v2's measured contours, tight line fitting and integrated
tails, but rejects characters absent from the selected bundled font. Loaded fonts
alone are insufficient: browsers silently substitute OS fonts for missing glyphs.
The shared generated coverage table is derived from the actual TTF cmap tables
with `python3 scripts/update_lettering_fonts.py` (check with `--check`), without
runtime downloads or dependencies. Missing glyphs are recoverable lettering
errors and prevent export, never trigger a Draw correction. Existing resolved
layouts must be explicitly reflowed/saved; font coverage is not inferred from a
script name or promised for all Japanese/Chinese characters.
