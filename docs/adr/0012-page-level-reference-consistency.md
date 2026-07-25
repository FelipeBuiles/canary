# ADR 0012: Page-level reference consistency

**Status:** Accepted  
**Date:** 2026-07-25

## Decision

Visual consistency in the target pipeline comes from authoritative visual
anchors, approved references, named appearance states, and explicit state-change
beats. It does not come from application-planned character coordinates or from
chaining generated images together.

Each canonical ComicPage identifies the characters, locations, props, and
appearance states required by its adapted beats. Draw resolves and supplies the
approved references once at page scope. The page-generation model owns exact
staging, screen direction, character placement, and visual continuity among
panels on that page.

Appearance changes are authored explicitly in the ordered book adaptation and
carried into the relevant ComicPage. The pipeline does not guess their
activation point afterward from keyword matches in generated intermediate
text.

A prior page render is not an authoritative reference for the next page.
Generated pages may be compared during verification, but using each generated
render as required input to the next would propagate mistakes and make
regeneration order-dependent.

## Consequences

The migration removes:

- fixed left/right/center character assignments across scenes;
- per-panel character-position maps used as generation constraints;
- previous-panel or previous-page image chains as the default continuity
  mechanism;
- keyword heuristics that pin appearance transitions after adaptation;
- continuity rules derived from observed render geometry.

Primary references, visual anchors, appearance states, protected verbatim
anchors, and explicit story-position changes remain core inputs. Render
analysis may flag cross-page identity or state drift, but corrections return to
Draw using the authoritative references rather than blessing the drift as new
reference material.
