# ADR 0009: Immutable source units and referenced scenes

**Status:** Accepted  
**Date:** 2026-07-25

## Decision

`extract` segments the original novel once into stable, globally ordered,
sentence-aligned source units. Each unit retains its exact character offsets
into the immutable source text, its verbatim content, and a stable identifier.

Scenes do not store independently copied or sliced prose. A scene references an
ordered, contiguous range of source-unit identifiers. Changing a scene boundary
therefore changes references rather than rewriting source text. Downstream
artifacts cite source-unit IDs for provenance and adaptation accounting instead
of relying on duplicated scene text.

Extraction validates source-unit boundaries and scene ranges before `brief`
can run. A range beginning or ending inside a source unit, an unknown unit ID,
an inverted range, overlap in primary scene ownership, or an unintended gap in
the adapted source is a blocking integrity failure.

Additional contextual references may point to units outside a scene's primary
range, but they must be labeled as context and do not alter primary ownership
or adaptation-ledger coverage.

## Consequences

The source-unit index is the canonical bridge between the original novel and
all adaptation artifacts. Scene text may be materialized as a derived view for
model context or UI display, but that view is never stored as an independent
source of truth.

Existing scene-text files and quote-based boundary recovery are not preserved
as compatibility paths. The migration should replace them directly with source
references and strict integrity validation.
