# ADR 0008: Eight-stage page-generation pipeline

**Status:** Accepted  
**Date:** 2026-07-25

## Decision

Canary's target backend pipeline has eight discrete stages:

1. `extract`
2. `brief`
3. `style`
4. `cast`
5. `adapt`
6. `plan`
7. `draw`
8. `finish`

The pipeline does not preserve the historical `storyboard`, `direct`, or
`compose` stage names for compatibility.

`extract` creates the Story Bible and stable source units. `brief` proposes the
adaptation brief and makes it authoritative through user approval or editing.
`style` and `cast` establish the visual direction and approved references.
`adapt` creates the book-wide narrative treatment, adaptation ledger, and one
ordered book adaptation. `plan` creates canonical ComicPages and owns page
allocation, spread rhythm, page turns, reading order, exact lettering, and
semantic layout intent. `draw` compiles frozen generation requests from
canonical page revisions and exclusively owns complete-page generation
provider calls. Plan must stage the canonical speaker for on-screen lettering
in the same semantic panel. Draw uses that ownership to give each balloon one
unambiguous speaker target; off-screen speech and captioned narration or quoted
text do not receive tails pointing at visible characters.
`finish` verifies, corrects, normalizes, and exports page renders without
calling generation providers directly.

`storyboard` is removed because its panel-breakdown artifact is a compatibility
projection rather than an independent source of creative intent. `direct` is
removed because request compilation is a derived implementation concern within
`draw`, not a separately editable creative stage. Frozen generation requests
remain inspectable and resumable artifacts for provenance, retries, cost
accounting, and diagnosis.

The historical panel-generation and deterministic assembly route is not a
production fallback. Draw capability-gates providers to complete-page
generation, and every correction produces another complete page revision.

The four user-facing stations remain a presentation layer over these backend
stages. They do not merge stage artifacts or responsibilities.

The stations are:

1. **Story** — source understanding and adaptation brief;
2. **Look** — style and cast;
3. **Pages** — book adaptation, page planning, complete-page generation, and
   page revision;
4. **Book** — final preflight and export.

Station 03 is renamed from **Panels** to **Pages** because independently
generated production panels no longer exist in the target architecture.

The Story station has one user approval boundary at `brief`. `extract` runs
strict source-integrity validation automatically and cannot advance while that
validation fails. The `brief` review then presents the Story Bible and proposed
adaptation brief together for one approval or editing decision. There is no
separate `extract` approval.

`adapt` and `plan` remain automatic, inspectable work. Their unresolved
editorial issues are summarized at the existing pre-Draw decision in the
Pages station, with source evidence and proposed remedies. Invariant failures
block automatically. Editorial issues do not create another approval stage:
the user may correct them or deliberately continue before spending credits on
page generation. When no issues exist, no additional review surface is shown.

For long books, Plan's implementation uses two internal passes behind the same
stage interface. A compact global page map owns page count, ordered beat
allocation, page turns, spreads, emphasis, density, and rhythm. Bounded page
batches then expand that fixed authority into semantic panels. Plan consumes a
ledger-free planning projection rather than the complete Adapt artifact.
Mechanical page numbers, content IDs/order, ordinary lettering allocation, and
reading order are canonicalized by code. Validation repairs regenerate only
the affected page batch whenever the global map remains valid.

## Consequences

The target architecture may break existing projects, stage state, artifact
paths, API contracts, and UI assumptions. Canary has not launched, so the
implementation should migrate directly to the accepted model without legacy
shims, dual reads, compatibility projections, or fallback stage aliases.

Existing documentation that describes the implemented nine-stage pipeline
remains accurate until the migration lands. Once implementation changes, the
current-contract documentation must be updated atomically.
