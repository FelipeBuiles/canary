# ADR 0006: Model-owned layout and observed geometry

**Status:** Accepted  
**Date:** 2026-07-25

## Decision

Canonical `ComicPage` artifacts express semantic layout intent rather than
mandatory normalized panel coordinates. They own panel order, content, exact
lettering, reading order, narrative importance, and roles such as hero,
standard, inset, or splash. The page-generation model normally chooses exact
panel boxes, gutters, borders, and composition.

After generation, derived render analysis records observed panel boxes or
polygons for crops, review, OCR, accessibility, and validation. Observed
geometry describes a particular page render and is not canonical author
intent. Exact geometry becomes authoritative only when an author explicitly
pins it or a chosen generation capability requires a structural constraint.

This removes deterministic slot templates, per-panel aspect compatibility,
crop-risk classification, and exact-versus-master panel generation from the
default architecture. Those mechanisms existed to reconcile independently
generated panels with application-owned page assembly and should not constrain
model-owned page composition.

Canonical planning also does not use universal panel-count caps, per-panel word
caps, template-capacity pagination, or mechanical overflow splitting. A page
expresses narrative purpose, relative emphasis, ordered complete lettering,
and a density intent such as sparse, standard, or dense. `plan` redistributes
complete beats across pages when a page is infeasible rather than splitting
panels mechanically or truncating copy.

Hard limits may exist in a selected generation capability profile when
supported by model evidence. Such limits validate a derived generation request;
they do not become universal story-planning rules or canonical page fields.
