# ADR 0010: Book-level adaptation, not scene-parallel scripts

**Status:** Accepted  
**Date:** 2026-07-25

Amended by [ADR 0023](0023-series-parts-and-author-owned-story-bible.md): the ordered adaptation is per part, with continuity from earlier parts.

## Decision

`adapt` produces one logically ordered adaptation for the whole book. Source
scenes remain useful for navigation, provenance, and context selection, but
they are not independent creative units and do not own separate canonical
screenplays.

The book adaptation contains the ordered adapted beats, transitions, complete
dialogue and caption wording, narrative functions, and source-ledger links
consumed by `plan`.
It is governed by the approved adaptation brief and narrative treatment.

The artifact may be physically sharded by chapter or scene to fit storage,
streaming, or model-context constraints. Such shards are implementation
details: they preserve one global order and do not become independently
approved or independently authoritative outputs. Internal model calls may also
be chunked or parallelized, but the public stage contract exposes only the
single ordered adaptation.

`plan` allocates that global sequence to canonical ComicPages. It may place a
scene transition within a page or across a page turn according to narrative
rhythm; pages are not required to be scene-contained.

## Consequences

The target architecture removes per-scene screenplay artifacts, parallel scene
adaptation as a domain concept, scene-local panel planning, and a mandatory
post-hoc reconciliation pass. Those mechanisms compensate for an artificial
scene boundary rather than expressing the book's actual adaptation.

Full-page generation begins from globally planned pages, not from concatenated
scene-local panel plans. This makes book-level proportion, pacing, reveals, and
aftermath decisions available before Draw receives a page.
