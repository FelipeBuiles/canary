# ADR 0004: Draw owns generation and Finish completes the book

**Status:** Accepted  
**Date:** 2026-07-25

## Decision

`draw` is the exclusive owner of model calls that generate final comic art,
and every production generation or correction job outputs a complete page
revision. There is no panel-generation fallback. The final stage is renamed
from `compose` to `finish`: it verifies page renders against their canonical
`ComicPage`, applies permitted
deterministic corrections, prepares print-ready assets, and exports the book.
`finish` does not call image-generation providers; model-based correction is
generation work owned by `draw`.

Permitted deterministic work is limited to production-safe normalization such
as dimensions, color profile, bleed, file metadata, ordering, and export
packaging. `finish` does not redraw artwork, replace lettering, paint over
regions, or assemble replacement panels. A narrative, lettering, or artwork
failure produces a structured correction request; server orchestration sends
that request to `draw`, whose successful output is a new complete page-render
revision that `finish` verifies again.

The user-facing station remains **Book**, with **Review, fix & export** as its
primary action. “Compose” is retired as current pipeline vocabulary because
model-owned page composition makes deterministic panel assembly a historical
technique rather than the final stage's responsibility.

Panel crops may be derived from a page render for inspection or diagnosis, but
they are not independently generated assets and are never assembled into the
production page. A provider that cannot reliably generate complete lettered
pages is rejected by Draw's capability gate rather than activating the
historical panel pipeline.

Canary has not launched, so the implementation should replace the current
contract directly. Backward-compatible stage aliases, dual artifact paths,
migrations for existing project outputs, and other legacy shims are explicitly
out of scope unless they contribute to the target architecture itself.
