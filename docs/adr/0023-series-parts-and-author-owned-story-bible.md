# ADR 0023: Series of parts and an author-owned Story Bible

**Status:** Accepted, implemented 2026-10-02. Amends ADR 0007 (one Brief per
part), ADR 0009 (source units per part) and ADR 0010 (one adaptation per part).

## Context

A project's source could not change once extraction started. A long novel had
to be uploaded whole, or split into separate projects that lost the cast and
continuity between them. Authors adapting several books or serialized releases
paid the full time and cost of Extract and Brief again for every installment.
Extracted characters, places and props could not be corrected, added, removed
or merged afterwards; the only edit path replaced the whole Story Bible and
reset every downstream stage.

## Decision

### A project is a series of parts

Each part is its own issue: its own source text, source document, Brief,
adaptation, plan, pages, cover, Finish and export. The Story Bible, Style and
Cast belong to the series and are shared by every part.

- The series root holds the Look work (Story Bible, Style proofs, Cast
  references, configuration, book lettering style) and the part manifest
  (`source/parts.json`) with each part's text. Each part's page work lives in
  its workspace, `parts/<part_id>/`, marked by `part.json`. Stored relative
  paths keep their meaning: Look paths are relative to the series root, page
  paths to the part workspace.
- Style and Cast state lives in the series state; Extract through Finish state
  lives in each part's state, which reads the series stages as an overlay.
- Source-unit ordinals continue across parts so every unit identifier stays
  unique in the series; offsets are relative to the part's own text.
- Each part has its own Brief. A later part's draft takes the series-wide
  fields (themes, point of view, narrator treatment, tone, motifs and
  transformation level) from the nearest earlier approved Brief instead of
  inferring them again; the author can still edit them before approving.
- Adapt reads a compact continuity context from earlier parts' adapted
  scripts and records what it read. Re-adapting an earlier part later flags
  the parts after it; nothing re-runs automatically.
- Consecutive finished parts combine into one PDF or CBZ from their verified
  normalized pages, each part starting on a right-hand page. Nothing is redrawn.
- A part's first Draw edition inherits the previous part's profile while the
  project can still spend on it, and otherwise binds the current profile.
  Existing editions never change profile.

### Text freezes as the series grows

Initial uploads and appended manuscripts automatically group consecutive
detected chapters into parts near 100,000 characters, preserving exact text
and keeping oversized chapters intact. Authors can disable grouping when
appending, or choose additional chapter splits manually. Short manuscripts
remain one part, and replacing text never splits an existing part. A new
project opens part 1 so extraction starts in reading order.
Grouped parts are titled by chapter range. How a multi-part book is shown,
and how each part learns where it sits in the whole book, is decided in
[ADR 0024](0024-part-sequences-and-the-book-map.md).
Detection includes decorated numeric headings such as `[ 1 ]`. A completed
extraction is never repartitioned automatically; manual splits happen before
Extract and keep the exact source text.
Only the newest part's text can be replaced, split or deleted,
and only until its Adapt starts; once a later part's extraction has started,
earlier text is final. Extraction and adaptation run in reading order because each reads
what the earlier parts established.

### Extraction is incremental

A part's Extract reads only its own text against the shared registry and
records what it added, so replacing or deleting an unadapted part withdraws
exactly its contribution. Cast is a series checkpoint that reopens only for
new entities and looks. Character designs are fingerprinted per character
(appearance facts and style, not name or relationships), so a new character
is designed beside the established cast without redesigning it.

The source registry retains every established participant and citation. The
automatic Cast worklist selects characters appearing in at least three narrative
scenes across the series, explicit author additions, retained Cast sheets and
`cast_required` identities (principal antagonists, companions and plot-critical
creatures even with few appearances). Authors can set this override in the
Story Bible editor.
Tiny stories with fewer than three narrative scenes retain their participants;
explicit character requests can include an incidental participant. Incidental
characters carry verbatim written appearance authority through Plan and Draw
without a dedicated image. When later parts establish recurrence, the same ID
enters Cast and reopens its checkpoint. This reduces reference generation and
upload cost without deleting story facts or weakening required image authorities.

### Parts progress independently

Admission, busy checks and event streams are scoped per part. A part's work
waits only for its own jobs and series work, so the next part's Extract, Brief
and Cast can run while another part draws. A part's event stream also carries
series events.

### The author owns the Story Bible

Authors edit, add, remove and merge characters, places and props, and add,
edit or remove their looks. Every write carries the revision the editor loaded
and is refused when the Bible changed since.

- Removing or merging away an entity or look that an adapted part names is
  refused with the parts that name it; restarting those parts' adaptation is
  the way to change them. Editing is always allowed.
- Removed names are recorded and later extraction does not recreate them until
  the author restores them. A merged entry's names become aliases of the kept
  one, and extraction recognizes aliases.
- An added entry joins only scenes in parts whose adaptation hasn't started.
  "Draft from source" proposes its details from the passages that mention it,
  under a credit hold, and saves nothing.
- A changed description makes only that entity's Cast references out of date,
  compared through the same frozen requests generation uses. The author keeps
  the current image or reopens Cast to regenerate; edits that change no
  appearance (names, aliases, relationships, look labels) carry current
  references over. Drawn pages whose frozen references differ from the current
  Bible or Cast are flagged and never redrawn automatically.
- The whole-Bible replacement route is removed.
- Every entry keeps a written look. No edit blanks a visual anchor; a blank
  one left by an older extraction is filled in place without resetting any
  stage, and a later part's extraction waits until none is blank.

## Consequences

Part routes serve under `/api/projects/{project_id}/parts/{part_id}`; series
routes (Style, Cast, Story Bible, parts) under `/api/projects/{project_id}`.
The web app addresses a part with the project key `<project_id>~<part_id>`, so
each part keeps its own query cache while series data refreshes across parts.

Existing projects move once, on open, into a one-part series. This is a layout
move, not a compatibility reader: artifact schemas and contents are unchanged,
nothing is regenerated, and incompatible artifacts are still rejected with a
rerun instruction (ADR 0009's no-shim rule stands).

Publishing still uses the project's single publication record and publishes
the routed part; per-part publications are not yet implemented.
