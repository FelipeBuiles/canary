# ADR 0024: Part sequences and the book map

**Status:** Accepted, implemented 2026-10-02. Amends ADR 0023 (series of parts).

## Context

A long upload becomes a series of parts of about 100,000 characters, and only
the part the author starts is analyzed. Each part was still treated as a whole
book:

- Extract forced every part into exactly three acts. Chapters 1–6 of a
  47-chapter novel got their own Act 3 climax.
- Neither Brief nor Adapt was told it was working on one part of a longer
  book. Adapt was asked for "one book-wide narrative treatment for the complete
  adaptation" and received the part's three acts, so a part would be paced as a
  finished story with its own resolution.
- Context only looked backwards, and only one part back. Nothing knew which
  people and setups mattered later, and part 1's Brief fixed the series-wide
  themes and motifs from one eighth of the book.

## Decision

### Parts have sequences, not acts

Extract groups a part's narrative scenes into `sequences`: consecutive runs
that pursue one goal and end on a turn, as many as the text supports. They
partition the part's narrative scenes in order; code assigns their numbers.
`narrative_arcs` is removed from the Story Bible. A Bible that still holds it is
rejected with an instruction to analyze the manuscript again; there is no
reader for the old shape.

### The book map holds the book's structure

A multi-part series has one book map at the series root. Extract builds it
before analyzing a part whenever the saved parts changed:

1. Each saved part is digested on its own: a synopsis, chapter notes, the
   people who matter, the threads it opens, advances or resolves, and its
   motifs. A digest is cached by the part's exact text.
2. One combining call turns the digests into the book's acts (spanning parts,
   any number), each part's role, through-lines with the parts that open and
   resolve them, recurring people, themes and motifs.

The map is part of Extract's cost estimate, checkpoints and model choice;
there is no new stage. A map that no longer matches the saved parts is never
used. Appending or replacing text costs only the new digests and one combining
call.

### Every part knows its place

Brief and Adapt receive a part's book context: its position (part *k* of *N*),
the rule that a part before the last has no ending of its own, and, with a
fresh map, a bounded slice of the map: the acts that touch the part, its role,
recent earlier parts, the through-lines active in it, the people present who
matter beyond it, and the book's themes and motifs. The slice stays bounded
however long the book is. It is reference, never source: a part's promises,
events and turns describe its own stretch. Part 1's Brief bases the
series-wide themes and motifs on the book's. Adapt keeps its existing
continuity from earlier adapted parts (recent causal spines and the previous
part's closing beats); long-range threads come from the map rather than a
second ledger.

Extract requires Cast references for a part's rostered characters that the
map names as principal or recurring, so someone who matters to the book is
designed even when their first part shows them briefly. Nothing is demoted.

### Showing a multi-part book

The Story screen shows the book as a strip, one segment per part sized by its
text, inside the manuscript hero. One sentence says how many parts are
analyzed and that the rest wait until the author starts them. The part list,
with each part's map synopsis, is one disclosure away. The next part is
offered only after the open part's Brief is approved, in reading order, and
never while another part is analyzing or failed. Subscription-funded work says
it is included rather than quoting zero credits.

## Consequences

- Existing Story Bibles must be extracted again (new project). Recorded mock
  fixtures are converted by the replay service only.
- Extract of a multi-part series' first part reads the whole manuscript once.
  On a ~720,000-character book that is eight digest calls plus one combining
  call on the extraction model, run in parallel before the part's sections.
- Single-part projects are unchanged: no map, no position, a whole-book
  treatment.
