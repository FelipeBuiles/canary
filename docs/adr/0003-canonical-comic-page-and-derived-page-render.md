# ADR 0003: Canonical ComicPage and derived page render

**Status:** Accepted  
**Date:** 2026-07-25

## Decision

`ComicPage` remains the canonical publishable page specification when layout
and lettering are generated into pixels. It owns ordered panels, geometry,
exact lettering, reading order, and lettering target intent. A model-generated
page bitmap is a derived **page render** tied to a specific `ComicPage`
revision; embedded text, generation prompts, and OCR results do not replace
canonical structured data.

Author-facing edits to page-owned intent create a new `ComicPage` revision and
make page renders derived from an earlier revision stale. A wording change is
an Adapt correction first; Plan then allocates the revised lettering into a new
ComicPage revision. This preserves editable copy, localization, accessibility,
alternate editions, deterministic production metadata, and reliable
invalidation while keeping copy ownership unambiguous.

Here, geometry means semantic layout intent by default. Exact coordinates are
canonical only when explicitly pinned, as refined by ADR 0006.
