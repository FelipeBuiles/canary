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
dialogue and caption wording. Every lettering item records how it is delivered.
On-screen dialogue and thought also identify one canonical speaking character;
quoted prose is captioned quoted text rather than dialogue attributed to an
arbitrary visible character.

Unaccounted source material, incomplete scene boundaries, and truncated
display copy are validation failures rather than warnings. Lettering budgets
may trigger editorial rewriting, redistribution, or additional panels, but
must never silently shorten text or replace a complete thought with a trailing
ellipsis. A faithful adaptation also fails validation when it effectively
erases a substantial source scene or leaves a sustained run of causal beats
without reader-facing dialogue, caption, or thought.

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

The canonical ledger remains one entry per source unit, but the model does not
author repetitive entries that can be derived from beat and lettering
provenance. Adapt's internal wire format contains beats plus compact exceptions
for compression, intentional omission, and visual-motif treatment. Code expands
those decisions into the complete canonical ledger. Model-facing source and
Story Bible views omit offsets, hashes, visual prose, and other fields that do
not affect narrative judgment.

Validation failures are repaired at the smallest source-owned scope that
preserves coherence. A failure with source evidence expands to its complete
source scene and replaces only that scene's beats and ledger decisions inside
the affected shard. Failures without resolvable local evidence may still
require a full-shard repair. Provenance closure also includes intervening beats
in authored order, so replacement is one contiguous interval. Splicing retains
the generated repair's order and the untouched prefix/suffix. Sorting by earliest
source citation is invalid: an event's supporting provenance can include an
earlier summary or foreshadowing without moving its dramatization there.

The earlier minimum-page-floor policy is superseded by
[ADR 0016](0016-narrative-review-and-advisory-length.md). Both ends of the
approved range are now advisory. Adapt preserves the source's narrative
functions; Plan chooses the purposeful length without padding to meet a minimum
or cutting/crowding essential material to meet a maximum. Separate narrative
review evaluates completeness, coherence, and pacing before drawing.
