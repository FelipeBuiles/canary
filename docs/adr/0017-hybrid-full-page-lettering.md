# ADR 0017: Hybrid full-page artwork and editable lettering

**Status:** Accepted
**Date:** 2026-09-15

## Context

A single complete-page generation yields coherent artwork, but baking the final
words into the image couples spelling, translation and typography to paid art
regeneration. The historical Compose editor mixed panel assembly and presentation
and duplicated client/export layout. Neither architecture meets the new editing
requirement.

## Decision

Keep the eight-stage, full-page-only pipeline. Adapt owns canonical copy; Plan
owns page assignment and coarse lettering reservations; Draw owns immutable base
art; Pages owns editable presentation; Finish composites and packages it.
No panel raster assets, ninth Compose stage, raster text removal, extra planning
call or silent model/profile migration is introduced.

Use the existing `exact_visible_lettering` capability seam. Explicitly versioned
new hybrid profiles set it false, omit literal publishable copy from the image
request and forbid generated balloons/boxes/SFX. Existing stored true profiles
keep their serialized identity and remain readable/reviewable/exportable without
duplicate overlays. Historical artifacts do not acquire current-generation rights.

Plan reservations live in hash-bound sidecars rather than adding fields that
change retained ComicPage content hashes. Independent PageLettering records own
copy overrides, locale variants, suggested/actual normalized geometry, role
styles, tails, resolved typography and reviewed-against-art identity. Styles use
the curated font allowlist and existing Style call's optional executable tokens;
legacy prose directions seed an editable curated preset, not a claimed exact
translation of arbitrary prose into CSS.

Use measured, bounded font fitting and balanced line breaks, one server SVG and
local Playwright. The browser displays that SVG, with the same glyph/geometry
contract used in composition and export. Font fingerprints and compositor version
participate in identities. Missing glyphs/translations and overflow are explicit;
the software never keeps shrinking below the minimum or silently wraps a word.

Provider-free preview is read-only. Explicit saves use expected hashes and
immutable history with crash-safe revision allocation. Project publication locks
serialize source/art changes, lettering saves and Finish. Lettering changes
invalidate only derived Finish output; Draw changes preserve lettering and make
placement review outdated. Plan/upstream changes invalidate affected presentation.
Local UI drafts support explicit recovery, not silent conflict resolution.

Blind OCR sees base art. Unexpected comic lettering is an advisory visual finding
with its detected region, not missing-canonical-copy noise. Incidental writing
remains distinct. The deterministic software layer is not OCRed to prove itself.

## Consequences and validation

This supersedes only the baked-lettering portions of ADRs 0004 and 0013. Model-owned
art layout, capability-bound editions and exception-based art review remain intact.
New typography failures block Finish without creating paid redraw requests.
The editor is deliberately a focused lettering workspace, not a general canvas
application: explicit saves, direct manipulation, accessible property fields,
undo/redo, role presets, local recovery and a raw-art comparison.

Provider-free tests cover lineage/CAS, orphan revision recovery, legacy profiles,
Plan schemas, reservation validation, copy omission, locale/overflow behavior,
SVG escaping/parity, real Chromium composition and PDF/CBZ, HTTP mutations and UI
recovery. Browser fixture interaction checks cover drag, undo, save and responsive
layout. Those checks cannot establish how a live image model respects reserved
space; visual acceptance on newly generated hybrid pages remains required before
claiming reference-level artistic quality.
