# ADR 0011: Capability-bounded page density

**Status:** Accepted  
**Date:** 2026-07-25

## Decision

Canary removes universal panel-count caps, per-panel lettering caps,
template-capacity pagination, and mechanical overflow panel splitting from the
target planning architecture.

`plan` chooses page boundaries, panel count, and relative space from narrative
function. Each canonical ComicPage records ordered content, emphasis, complete
lettering, and semantic density intent. When content is too dense for a good
page, `plan` redistributes complete beats across additional pages.

Generation providers may have empirically validated capability limits. Those
limits belong to a capability profile used to validate Draw's derived
generation request. They must not become universal constraints on the book
adaptation or canonical page model.

## Consequences

The migration deletes planning behavior whose purpose was to fit independently
generated panels into deterministic assembly templates, including:

- maximum panels per scene;
- universal maximum panels per page;
- visual-beat and dialogue counts per panel;
- word-count-triggered panel splitting;
- preset geometry selection by panel count;
- page construction constrained by template slot capacity.

Lettering economy remains an adaptation craft concern, and page density remains
a planning concern. Neither is implemented through silent truncation or
generic numeric caps.
