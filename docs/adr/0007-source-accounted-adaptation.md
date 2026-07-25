# ADR 0007: Source-accounted adaptation

**Status:** Accepted  
**Date:** 2026-07-25

## Decision

Canary's `adapt` stage owns book-wide adaptation reasoning and one ordered,
source-accounted book adaptation.

Before the book adaptation is written, Canary infers an adaptation brief from
the source and presents it for user approval or editing. The brief records the
story promises, themes, point of view, tone, motifs, essential facts, protected
language, transformation level, desired emphasis, and a target page range. It
is not authoritative until approved, and the book-wide narrative treatment
must not be created before that approval.

Under the approved brief, `adapt` creates a narrative treatment for the whole
book. The treatment records the causal spine, character and emotional arcs,
reveals, reactions, aftermath, and relative narrative emphasis. It provides
the global contract under which the ordered adaptation is written. It does not
assign page geometry or final page counts; translating the treatment into
pages, spreads, page turns, and concrete page allocation belongs to `plan`.

Canary's adaptation must also account explicitly for every sentence-aligned
source unit. Extraction produces stable, ordered source units and validates
that scene ranges are complete, non-overlapping, and cover the intended source
text. Adaptation assigns every unit a disposition such as depicted, dialogue,
thought, caption, visual motif, compressed into another beat, or intentionally
omitted with a reason. Adapted beats retain links to the source units
they adapt, identify the narrative function being preserved, and own complete
dialogue and caption wording.

Unaccounted source material, incomplete scene boundaries, and truncated
display copy are validation failures rather than warnings. Lettering budgets
may trigger editorial rewriting, redistribution, or additional panels, but
must never silently shorten text or replace a complete thought with a trailing
ellipsis.

`plan` may allocate an adapted lettering item across pages or panels without
changing its words. It may also create more space or report that the item
cannot fit at acceptable density. It may not paraphrase, shorten, omit, or
truncate lettering to satisfy layout constraints. A wording change is an
`adapt` correction and preserves the item's source-ledger provenance.

This ledger makes fidelity inspectable without requiring literal inclusion of
every sentence. It preserves the adapter's freedom to transform prose into
visual storytelling while making every omission and compression deliberate.
The narrative treatment prevents locally plausible scene adaptations from
collectively damaging book-level causality, proportion, pacing, or emotional
release. User approval of the brief protects authorial intent that automated
coverage and coherence checks cannot establish.

The target page range is a soft editorial constraint, not permission to drop
essential material or overload pages. `adapt` uses it to guide proportional
selection and compression, while `plan` determines the actual page count. If
the approved story requirements cannot fit the range at acceptable density,
Canary reports the conflict and recommends a larger range rather than silently
cutting, truncating, or crowding the adaptation.
