# ADR 0005: Plan owns canonical ComicPages

**Status:** Accepted  
**Date:** 2026-07-25

## Decision

The `plan` stage creates and owns canonical `ComicPage` artifacts under
`plan/pages/page_NNN.json`. These artifacts define publishable page intent
before generation begins: page and panel order, semantic layout intent, exact
lettering, reading order, and lettering target intent. Exact panel geometry is
optional and becomes canonical only when explicitly pinned, as decided in ADR
0006.

Exact lettering in a `ComicPage` is the unchanged publishable allocation of
complete wording authored by `adapt`. `plan` owns its page and panel placement
but does not become a second copywriting authority.

The supporting layout plan may retain planning rationale, beat mappings, and
visual execution detail needed by downstream stages, but it must not compete
with `ComicPage` for authority over publishable structure or copy.
`draw` derives frozen generation requests from that intent and writes page
renders tied to identified `ComicPage` revisions. `finish` consumes those
renders for verification, correction coordination, normalization, and export.

Canonical panel records carry semantic roles such as establishing, action,
reaction, detail, transition, splash, and inset. Adjacent panels may cite the
same adapted beat when they depict distinct source-supported submoments. This
decompression does not duplicate lettering or permit story order to rewind.

Author edits write back to the canonical `ComicPage` and invalidate affected
downstream artifacts. An explicit replan may replace those edits; it must be
presented as a destructive regeneration of page intent rather than a routine
render action.
