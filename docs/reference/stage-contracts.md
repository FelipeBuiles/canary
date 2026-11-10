# Stage contracts

**Status: Current, October 2, 2026.** Implementation and tests are authoritative.
Each stage owns its file boundary. Server orchestration runs the explicit chain;
stages do not call one another. The CLI has only `init` and `serve`.

| # | Stage | Checkpoint? | Responsibility |
|---|-------|-------------|----------------|
| 1 | `extract` | No | Source document and Story Bible |
| 2 | `brief` | Yes | Approve adaptation intent and constraints |
| 3 | `style` | Yes | Select visual style |
| 4 | `cast` | Yes | Approve character, location, and prop references |
| 5 | `adapt` | No | Book adaptation, source coverage, exact lettering |
| 6 | `plan` | No | Canonical complete pages, copy allocation and space reservations |
| 7 | `draw` | Yes | Complete base-art images and issue review; optional base-art OCR |
| 8 | `finish` | No | Provider-free lettering composition, preflight and PDF/CBZ packaging |

`state.py` and `stages/__init__.py` define ordering and gates. Series routes
(Style, Cast, the Story Bible and parts) serve under `/api/projects/{project_id}`;
part routes serve under `/api/projects/{project_id}/parts/{part_id}`. Pipeline
operations live in `server/routers/pipeline.py` and serve both: a series stage
reached from a part route still runs on the series root. Page generation,
saved-pixel text-check recovery, correction, visual review, and render history
live in `server/routers/pages.py`; editorial decisions and story changes live in
`server/routers/editorial.py`; Finish export lives in `server/routers/export.py`.
All of these are part routes.

## Series and parts

A project is a series of parts ([ADR 0023](../adr/0023-series-parts-and-author-owned-story-bible.md)).
Each part is its own issue with its own source text, source document, Brief,
adaptation, plan, pages, cover, Finish and export. The Story Bible, Style and
Cast belong to the series.

- **Layout.** `workspace.series_root` holds the Look work (Story Bible, Style
  proofs, Cast references, `config.yaml`, book lettering style) and the part
  manifest `source/parts.json` with each part's text. A part workspace is
  `parts/<part_id>/`, marked by `part.json`. Look paths resolve against the
  series root and page paths against the part workspace, so stored relative
  paths keep their meaning. A directory without the marker is its own series.
- **State.** The series `state.json` owns `style` and `cast`; each part's
  `state.json` owns `extract` through `finish`. `load_state(part)` overlays the
  series stages read-only; `load_series_state` reads the series record.
- **Migration.** Opening a project created before parts moves it once into a
  one-part series (`series_migration.migrate_to_series`); the manifest write is
  the commit point. Artifact schemas and contents are unchanged.
- **Text.** Initial uploads and appended manuscripts (`POST /parts`) group
  consecutive detected chapters into parts with a target of 100,000 characters.
  Every source character is preserved, including front matter; oversized
  chapters and sources without recognizable headings stay intact. Short inputs
  remain one part. Appending accepts `auto_split=false` to keep the upload
  together, and returns the first `part`, its `chapters`, and every `created`
  part ID. New projects open the returned `part_id` (part 1). Manual splits
  remain available (`POST /parts/{part_id}/split`). Replacing a part's text
  replaces only that part and never automatically splits it.
  Detection recognizes named, bare-number and decorated-number headings such
  as `[ 1 ]` and `(XII)`. Manual splitting requires Extract to be pending;
  completed extraction is not silently repartitioned or invalidated.
  Chapter responses expose `opening_characters`: source before the first
  detected heading remains in the first span. Grouped parts are titled by
  chapter range (`Chapters 1–6`, `Chapter 44 – Epilogue`); decorated or bare
  numerals read as `Chapter N`. Titles stay author-editable.
  EPUB ingestion follows the spine's reading order and preserves heading and
  paragraph breaks for chapter detection.
  Initial uploads, appends and replacements share the source upload budget
  (defaults: 50 MB, 2,000 PDF pages, 5,000,000 extracted characters, 60 seconds
  to read the source); the pre-parser multipart cap adds 1 MB of form overhead.
  Other request bodies keep their independent limit.
  PDF text is cleaned before parts, hashes and immutable source units are
  created: standalone OceanofPDF watermarks and stray controls are removed,
  split small capitals and line-wrapped words are joined, and the final
  standalone `ABOUT THE AUTHOR` section and following back matter are trimmed.
  Hard hyphens are retained unless an unbroken occurrence establishes the word;
  normal uppercase phrases such as `I SAID` and `A HOUSE` stay separate.
  The uploaded original remains on disk. Existing saved source text and citation
  units are never silently cleaned or repartitioned.
  Only the newest part's text can be replaced, split or deleted, and only until
  its Adapt starts; once a later part's extraction has started, earlier text is
  final (`series.edit_blocker`). Renaming is always allowed.
- **Order.** Extract and Adapt run in reading order: a part's Extract waits
  for the previous part's Extract to complete, and its Adapt for the previous
  part's Adapt (`part_order_blocker`). Brief, Plan, Draw and Finish are
  independent of other parts.
- **Discovery.** Multi-part Story screens carry a book strip in the manuscript
  hero (or on its own sheet while the part waits for or runs analysis): one
  segment per part sized by its text, analyzed parts filled, the open part
  raised, and one sentence saying how many parts are analyzed and that the
  rest wait until the author starts them. The full part list, with each
  part's book-map synopsis (or its size) and state, is one disclosure away.
  Viewing a part never starts generation. The next part is offered only after
  the open part's Brief is approved, when it is the next in reading order and
  no part is analyzing or failed; the offer uses the existing stage estimate,
  credit review and run admission, then opens that part's Story progress.
  Subscription-funded estimates read "Included in your … subscription"
  rather than zero credits. Initial ingestion analyzes only part 1.
- **Book map.** A multi-part series has a book map (`book_map.py`, stored
  under the series root's `book_map/`). Extract builds it before a part's
  extraction when the saved parts changed: each part is digested once on its
  own (cached by its exact text), then one call combines the digests into the
  book's acts (spanning parts, any number), the parts' roles, through-lines
  with the parts that open and resolve them, recurring people, themes and
  motifs. The map is part of Extract's estimate, checkpoints and model choice.
  A map that no longer matches the saved parts is never used; unchanged parts
  keep their digests, so a rebuild costs only new text plus one combining
  call. Part summaries carry a part's `synopsis` and `book_role` while its
  map entry still matches its text. Single-part projects have no map.
- **Book context.** Every part of a multi-part series is told its position
  (`book_context.py`): part *k* of *N*, that a part before the last has no
  ending of its own and must not be given a climax or resolution the text does
  not contain, and that a later part opens mid-story. With a fresh map it also
  receives a bounded slice: the book synopsis, its role, the acts that touch
  it, up to five earlier parts' synopses, the through-lines active in it
  (opening, continuing or resolving here), the principal and recurring people
  present, and the book's themes and motifs. Brief and Adapt receive it as
  reference, never as source; part 1's Brief bases the series-wide themes and
  motifs on the book's. A part's Extract requires Cast references for rostered
  characters the map names as principal or recurring (exact name or alias),
  never demoting one.
- **Extract.** A part extracts only its own text against the shared registry.
  Source-unit ordinals continue across parts; offsets are relative to the
  part's text. The extraction delta records what the part added, so replacing
  or deleting an unadapted part withdraws exactly that.
  The first part also writes `source/opening.json` (`OpeningSnapshot`) after
  its first section, or after a short book's single call, and publishes an
  `opening` stage snapshot. It is not an authority: only the Cold Open reads
  it, and every stage reads the published Story Bible.
- **Cold Open.** Not a stage. Server orchestration admits it on the `opening`
  snapshot, once per account in production (`CANARY_COLD_OPEN_PER_ACCOUNT`: unset
  means 1 in production and no limit elsewhere; 0 turns it off) and once per project. It draws the opening's Style proof scene
  in three house looks under `cold_open/` at the series root, with every model
  call sponsored (`AIRequestContext.sponsor`): recorded at provider cost,
  never authorized against or debited from the author. It is ambient work
  (`AMBIENT_JOB_KINDS`): admission, busy checks and stage status ignore it,
  so it never holds back a checkpoint or a stage; only project deletion waits
  for it. Style adopts a Cold
  Open proof into its picker only when the proof's request fingerprint equals
  the one Style would build; the author's favorite is a highlight, never a
  selection. An empty Look adopts those proofs when the room opens
  (`POST /cold-open/adopt`): no model call, no spend, and a never-run Style
  stage becomes reviewable. Paid curation adopts them the same way.
- **Brief.** A later part's draft takes `themes`, `point_of_view`,
  `narrator_treatment`, `tone`, `motifs` and `transformation_level` from the
  nearest earlier approved Brief; the author can still edit them. Its
  `story_so_far` is the previous part's scenes; earlier parts reach it through
  the book context.
- **Cast.** Cast is a series checkpoint. It reopens only when the reference
  inventory grows (a part's extraction or an author's addition) and designs
  only characters without a current per-character fingerprint. Automatic
  character work includes participants in at least three narrative scenes
  across the series, author-added characters, retained main Cast sheets, and
  characters explicitly marked `cast_required` (principal antagonists,
  companions and plot-critical creatures even with few appearances). The Story
  Bible editor exposes this override; promoting an identity reopens Cast.
  Sources with fewer than three narrative scenes keep their participants.
  Explicit character requests can include an incidental participant. All source
  identities, relationships, scene rosters and citation IDs remain canonical;
  recurrence changes only the derived Cast worklist. Later appearances promote
  the same ID into image reference work. API Story Bible views expose the
  derived `cast_character_ids`; the editor can show all source participants.
- **Adapt.** Every part of a multi-part series writes a treatment for its
  own stretch of the book, with its book context. A later part also receives
  continuity from earlier parts' adapted scripts (the last three causal spines
  and the previous part's closing beats) and records which scripts it read.
  When an earlier part's adaptation changes afterwards, the later part reports
  an advisory `earlier_part_changed` flag. Nothing re-runs.
- **Draw.** A part's first edition inherits the previous part's profile while
  the project can spend on it, and otherwise binds the current profile.
- **Concurrency.** Admission, busy checks and event streams are per part. A
  part's work waits only for its own jobs and series work; series work waits
  only for series work. Extract and Brief use the light lane, so the next
  part's Story and Look work can run while another part draws. A part's
  `/events` stream also carries series events.
- **Export.** `POST /parts/export` combines consecutive finished parts from
  their verified normalized pages into one PDF or CBZ; each part starts on a
  right-hand page. Publications still use the project's single record.

## Story Bible editing

The author owns the series Story Bible (`story_bible_edits.py`,
`server/routers/story_bible.py`). Every write carries `expected_revision` and
is refused (409 `stale_story_bible`) when the Bible changed since.

- Edit, add, remove and merge characters, places and props; add, edit and
  remove their looks. Removing or merging away an entity or look that an
  adapted part's script or pages name is refused (409 `entity_cited`, with the
  parts). Editing is always allowed. Removal and merge also wait for running
  Adapt and Plan work.
- Removed names become `excluded_entities`; registry-based extraction skips
  them until the author restores them. A removal keeps the removed record
  (details, scenes, incoming relationships), so restoring brings the entry back
  whole, under its id, and its Cast images apply again. Author-added ids are
  never reused. Merged names become `aliases` of the kept entry, and
  extraction recognizes aliases.
- `GET /story-bible/{kind}/{id}/impact?action=remove|merge&into=` previews a
  removal or merge without writing: the scenes, looks and relationships that
  move or leave, Cast images that stop being used, new references Cast would
  need, and why the edit is blocked.
- Each author edit keeps the Bible from before it in
  `story_bible_history/` (newest 20). `POST /story-bible/undo` reverses the
  newest edit as a new revision while nothing else (another edit or an
  extraction) has changed the Bible since; it never takes away what an adapted
  part cites, and waits for running Adapt and Plan work. The editor response
  carries `undo` and `possible_duplicates` (complete primary-name matches, including a primary
  name matching an explicit alias; shared aliases and partial word overlap are
  insufficient). These are suggestions only and never merge entries automatically.
- An added entry (`origin: author`) joins only scenes in parts whose Adapt
  hasn't started. `POST /story-bible/{kind}/draft` proposes its details from
  the passages that mention the name, under a credit hold
  (`GET /story-bible/{kind}/draft-estimate` gives the estimate); nothing is
  saved.
- New entities or looks reopen an approved Cast for those items only.
- A changed description makes only that entity's references out of date
  (`GET /cast/freshness`, compared through the same frozen requests generation
  uses). `POST /cast/references/keep` keeps an image as it is (recorded beside
  its provenance, never replacing it); `POST /cast/reopen` returns an approved
  Cast to pending so a resumed Cast regenerates every out-of-date or missing
  reference. Edits that change no appearance carry current references over.
  Each out-of-date reference carries a `reason`: `parent_redrawn` for a look
  whose main image was redrawn after it (its request binds the main image's
  bytes), else `edited`. The Cast room groups references by entry and never
  sends `parent_redrawn` looks to the Story Bible: an edit there would redesign
  the main image and outdate the looks again.
- The Pages list reports each drawn page whose frozen references or written
  identities differ from the current Story Bible or Cast (image, description,
  continuity note, or removed entry), alongside re-planned pages, in its
  `redraws` field (`page_redraws.py`). Pages are never redrawn automatically.
- Every entry keeps a written look: no edit may blank a visual anchor (422).
  A blank anchor left by an extraction from before anchors were required is
  filled in place with `POST /story-bible/visual-anchor` (the Cast station
  form). It writes only a blank anchor (409 for an existing one), advances the
  revision, resets no stage and waits for running Style or Cast work. Plan,
  Cast approval and a later part's Extract refuse while any anchor is blank
  (409, naming the entries); Extract refuses before any spend, because
  sections must keep known anchors verbatim.

`TargetArtifacts` owns the active source, brief, adaptation, plan, Draw,
lettering, and Finish paths. `artifacts.py` owns Story Bible and Cast reference paths. Never
introduce alternate readers for legacy output shapes. Provider wire v3 is a
breaking cutover; current profiles and the local Codex runtime v7 Fast-mode execution
fingerprint reject incompatible saved requests rather than translating old wire.
Re-extract/regenerate affected output, or use a new project when an existing
edition is incompatible. There is no generated-artifact migration. Known retained baked-lettering
editions remain readable, reviewable, and exportable without rehashing saved
requests, rebinding their profiles, or placing another lettering layer over them.

## User gates

The four stations are Story, Look, Pages, and Book; they group, not replace,
the eight backend stages. Story includes Extract/Brief; Look includes Style/Cast.
`POST /api/projects/` and `/api/projects/import-story` validate and save the
source, configuration, and initial state only. They return `status: created`;
they do not start generation or reserve credits. Story analysis starts only
after an explicit estimated action through `/run?stage=extract`. A failed
estimate can be retried without starting work.

Story approval saves the visible Brief draft before approving; a failed save,
invalid page range, or revision conflict must not approve an older saved value.
Local unsaved drafts are keyed by Brief revision and content SHA. Matching
drafts can restore locally; older drafts remain separately inspectable in a
labelled read-only text field, with copy/manual-copy recovery and confirmed
discard. They are never silently applied to a newer Brief.

Entering Cast does not spend. Starting or resuming missing references is an
explicit estimated action; Style's explicit Continue action may start Cast
before navigating there. The initial cover is deferred until Draw starts, after
page jobs are queued, so it cannot delay Adapt. The Draw batch estimate includes
the cover when no previous attempt exists; Cast's estimate excludes it. Existing
cover attempts (including interrupted jobs recovered after restart) require an
explicit retry; entering a room never retries them. Approving Cast accepts the
estimated Adapt → Plan chain. Pages retains one Continue to Book decision,
not per-page acceptance.

### Cast reference corrections

Every significant character or location appearance opens its own revision controls.
Review and instructed corrections stay available while Cast or other project
work runs. Corrections queue without rewriting instructions or changing images
at admission; conflicting generation finishes before they execute. This applies
to main references, alternate appearances, locations and props. A second active
correction for the same asset still shares or rejects according to its existing
route contract, preserving one paid action per request.
State corrections use the entity-scoped instructed regeneration routes; their
instructions and images do not replace the main reference. Missing appearances
can be generated individually. Each paid action remains explicitly estimated
and confirmed. A character sheet or location plate redraw, plain or instructed,
accepts `with_looks`: the same job then redraws that entity's looks one at a
time from the new main image, reserving for every look up front
(`asset-regen-estimate` reports `looks`). A look that fails stays out of date
and is never retried. A main character sheet correction may also return
lasting `design` facets (face, hair, silhouette, posture, wardrobe); they
revise that character's Cast design in place, keeping its fingerprint, and the
Story Bible is never written. The addendum still carries the change, because
Draw reads it as approved art direction. Each sheet records the design it was
drawn from (`cast_design` in its metadata), and restoring a version restores it.

Cast instruction bodies optionally accept `reference_assets` (project-local
`asset_type`, `asset_id`, optional `state_id`; up to three). **Add a reference**
reveals the optional picker. Attached thumbnails can be reviewed and removed;
the author describes how each should guide the change in the same instruction.
There is no mandatory reference operation: borrowing a detail, matching an
appearance, preserving continuity, or avoiding similarity all use this flow.

The rewriter receives each attachment's name, state label and visual anchor;
the renderer receives the actual image as instruction context. Attachment alone
never implies copying or differentiation. The owner's explicit art direction takes
precedence over generated appearance details, continuity guards and style defaults
for the targeted asset/state. Unrequested details and the reference format remain
stable. Source anchors and guards remain verbatim for provenance; they cannot veto
a requested redesign. Attachments never become edit parents.

Successful image metadata stores the applied art direction. Draw carries that
direction with the selected reference, so source descriptions do not undo Cast
edits. Failed drafts are not treated as approved art direction. Main and alternate
location references expose version history and reversible restoration, including
the corresponding image metadata. Version numbers identify distinct saved images;
restoring an image selects its existing version without adding another history
entry. Restoring a main reference marks dependent states stale without
automatically regenerating them.

Missing/unreadable images, unknown identifiers, self-attachments and reference
overflow fail before the rewrite spends credits. Accepted attachments are saved
with the instruction and reused by plain rerolls. An explicit empty list removes
them from the next correction. `reference_count` on the asset estimate includes
the selected additional image inputs. `reference_assets_supported` advertises
attachment support to the UI; unknown correction fields are rejected rather
than silently ignored.

Location corrections may distinguish layout, furniture arrangement, decor, and
architectural details/materials consistent with canonical facts. They are no
longer restricted to lighting/weather changes. Visual anchors and active-state
continuity guards remain verbatim and authoritative. These controls do not
establish that the resulting designs are visually distinct; that requires review.

## Authority through generation

### Extraction participation

Sources longer than `Config.extraction_chunk_chars` (16,000 characters by
default) use sequential, sentence-aligned extraction sections. Each section's
first scene starts at its first unit, so a cut is a scene boundary: within a
quarter-share of each equal share, the cut moves to a chapter heading or
scene-break ornament, then a paragraph end, before falling back to a sentence.
When a later section still opens mid-scene, the model sets
`continues_previous_scene` and code folds that opening scene into the previous
one, shifting its beats after the previous scene's last referenced beat so every
appearance activation keeps its order. Code assigns each scene's chapter from the
detected heading that precedes it (or opens its first sentence); a heading's stated
number is kept and an unnumbered heading continues the book-wide count. Text with
no headings keeps the extraction's own chapter numbers.
No source characters are removed or duplicated. A single unit exceeding the limit fails
before generation with a source-formatting/configuration instruction. Shorter
sources retain the single-call path.
Extract sends a typed response schema on the initial call and every correction,
for whole-source extraction, section deltas and the final source review and sequence organization.
Review evidence is checked and then discarded, so code grounds it without a
correction. It begins in the scene it names and may run past that scene's last
sentence; typographic quotes, a line break typed as a space or a dropped ending
still name that sentence. Words that begin in a neighbouring scene are accepted
as cited; words from further away are re-cited to the scene that owns them, so
an added actor joins that scene's roster. A `scene_details` correction keeps
its exact scene and is rejected instead, as are words that are not source text;
that correction names the scene that holds the words and the named scene's
first and last sentences. Shared
instructions describe source fidelity and visual continuity; whole-source and
section scope rules are separate. Scene counts, panel counts and description
tag counts are not extraction quotas. Code derives scene counts and owns source
provenance and editor metadata rather than asking the model to reproduce them.

Section extraction also saves deterministic `source_start_offset` provenance
on each scene, so repeated opening sentences cannot relocate a section's
boundary to an earlier occurrence. Supplied offsets are validated against the
exact complete source unit; invalid offsets never fall back to fuzzy matching.
Requests supply the exact first source unit as
`required_first_scene_source_start_quote`; validation feedback repeats it if
the model skips the opening. Front matter belongs to the first story scene's
source span without requiring an invented comic scene for a title or copyright page.

Scene ranges also retain explicitly classified non-narrative source matter,
such as credits and promotional recommendations. A span with no staged
characters or objects is normalized to `scene_type: non_narrative` and
`location_id: null`; it requires no invented physical setting. Only an empty,
unreferenced placeholder location supplied for that span is removed. Existing
anchors, appearance states and settings used by narrative scenes remain intact.
The exact text and source-unit coverage remain complete. Brief and Adapt keep
these spans out of essential story action; Adapt accounts for them through
explicit intentional-omission ledger decisions and reasons. Narrative scenes
with unknown non-null entity references still fail with the offending IDs.
Story Explorer omits these ranges from scene action and numbering and explains
that non-story material is excluded; the source audit retains their coverage.

Each section receives the established entity registry and carried appearance
states. New IDs use a section prefix; recurring entities reuse their original
IDs. Existing first-part IDs such as `part0006_...` identify extraction section
six, not series part six; later-part prefixes include both part and section.
Saved IDs remain stable. Merging preserves existing base anchors, state
definitions and first appearances; it validates references and ordered timelines.
Disappearance and absence are not appearance states: states describe visible
physical looks, and activations reference the same entity's declared catalog.
The model does not retype established entities: recurring entries may
contain only their ID and new states, activations, or relationships. The response
can also add stable physical facts to `distinguishing_features` when a later
section first states them, record newly revealed names in `aliases`, and promote
an important identity with `cast_required`. A known identity's new facts do not
require local visual participation: a letter, description or background mention
can refine the registry without inventing an on-page actor. Its anchor and first
appearance stay unchanged. New identities still require staged participation.
These additions never rewrite established anchors, invent a physical transition
or demote required Cast work. Acting creatures, bosses, mounts and pets are
Characters; collective creatures use a group identity rather than a transient
object or one reference per interchangeable member. Persistent equipped
accessories remain in subsequent self-contained appearance states until removed.
`identity_kind` distinguishes independently tracked `individual` identities,
temporary `interchangeable` creature members and a shared `group` design. Matching
descriptions alone never authorize merging named people or companions.
The response schema constrains known-ID branches to those fields; complete new identities
and all new scene references use the current section prefix. Known IDs are
defined once in the schema and reused by citations. Large registries use exact
ID regex alternatives when needed to stay within provider enum budgets;
no identity is dropped. Section responses omit sequences, and later sections omit
inherited title/author/style metadata. Extract hydrates omitted identity fields
and known states from the registry verbatim;
it also resolves known character IDs cited by participation or scene rosters,
and known location IDs cited by scenes, when their local definitions are
omitted entirely. A repeated entity declared with a new ID is resolved locally
when its name exactly matches one registry name or alias (ignoring case and
surrounding whitespace) and its anchor is omitted or contains only literal tags
already in that registry anchor. The complete established anchor is preserved
verbatim, and scene, participation, and relationship references use the established
ID. Matching is scoped to entity kind; ambiguous names, conflicting physical
tags, blank anchors, conflicting duplicate deltas, and changed state definitions still fail.
Exact repeated entity entries and empty known-ID echoes accompanying a real
delta are coalesced before hydration, preserving all distinct facts and the raw
response. Empty unused known-entity deltas do not become new visual candidates.
Duplicate-name feedback identifies the incoming ID and matching registry IDs and
anchors so a correction can reuse the right authority without inventing identity.
On a rejected final attempt within one section's schema-repair chain, a dangling
character reference is reconciled when the preceding and current responses each declare exactly one
character with the same name and verbatim base anchor, but different IDs. Scene
rosters, private participation evidence, and relationship targets then use the
current definition's ID. No character is created from an orphan reference;
ambiguous identities, changed anchors, and unknown scene IDs still fail ordinary
validation. Ordinary validation runs first, preserving already valid responses
and existing intermediate feedback and cache keys. The raw responses remain unchanged.
An exhausted base-anchor conflict names the registry entity and the returned
entity with both anchors, so a misassigned known ID is visible without changing
earlier correction prompts or overwriting established physical identity.
Only referenced entities are loaded; previous scene definitions
and timeline activations are never imported into the section. Unknown IDs and
explicit conflicting values still fail validation, with the offending character,
scene, or appearance-state IDs identified in correction feedback. Per-section elapsed time and
AI source scope make subsequent live runs measurable. Section boundaries
may split a narrative scene into consecutive source scenes; Adapt still owns
book-level pacing. The existing final organization call also reads the complete
part source once, with scene boundaries and the registry. Its typed
`source_review` can add omitted staged creatures, important companions, stated
physical facts, newly revealed names, plot-critical props and missing locations,
and can move a scene to the place its action is staged. A group member with its
own role and gear stays a separate Character. The final review must also report,
in `part_end_looks`, the body look of every character whose look changes in the
part or who carries a changed body look into it (`end_look_required` lists them;
composed worn-item looks are outfit and excluded). A reported return adds an
activation of the character's canonical-equivalent look, created once as
`audit_base_return` when missing. Source quotes are
validated against their exact scene passages. Only explicitly interchangeable
creatures introduced in this part, with identical physical identity and no
individual states, may consolidate into a group; prior parts and individual
identities remain protected. Non-story matter stays in source coverage and is
excluded from sequences. Sequences (`StorySequence`) belong to their part:
as many as the source supports, each a consecutive run of scenes pursuing one
goal and ending on a turn, together partitioning the part's narrative scenes
in order. Code assigns their numbers. A part is never shaped into acts or
given its own climax; the book's acts live in the book map. A Story Bible that
still holds per-part `narrative_arcs` is rejected with an instruction to
analyze the manuscript again.

Missed persistent worn items have explicit acquisition/removal positions. Extract
composes their tags with subsequent body/wardrobe states, including minor looks
and returns to the base, without overwriting existing anchors or guards. A lost
or removed garment is an interval whose `removes_tags` name exact tags of the
look it is taken from; composed looks drop them and guard against redrawing
them. Composed labels name the items; continuity guards require only items
marked visually significant (prominent at full-figure size) to stay visible.
The look a Cast-required character ends the part in is marked visually
significant, because it carries into the next part. Declared
absence intervals cover earlier-lived-time frames or concealment. Existing complete
looks need no duplicate reference. New composed looks replace local activations;
unused intermediate states from this unpublished part are text-only, while prior
state authorities remain unchanged. Short sources emit the same selective review
inside their single extraction response. This adds source tokens to the final
sectioned call, without another model round trip or rewriting a saved Bible.

Section and organization JSON responses, including schema-repair responses,
are retained under `.checkpoints/extract/responses`, keyed by model and request
inputs. Resume revalidates matching responses without another provider call or
usage charge. Completed section usage is recorded before later work; a timeout
fails without automatically resubmitting that request. The stage log names the
section a rerun resumes at, and the local diagnostics journal keeps the runtime's
timing evidence (last model activity, token counts, event types; never request
content), so a stalled connection can be told from a slow model. Stage cleanup preserves
these checkpoints. A section or sequence-organization call that exhausts validation
attempts archives only its rejected response chain under
`.checkpoints/extract/rejected`, so an explicit retry can generate new output.
Successful sections retain their entire correction chain for exact cache reuse;
transport interruptions do not trigger this archival.
Schema and prompt changes are new request inputs and invalidate those response
cache keys; they do not authorize reusing a different request's output.
Cost estimates include all sections, estimated registry
growth, and the final source/organization call; they are not a spend ceiling or a
measured latency/quality guarantee.

Brief inference also sends its typed response schema on every attempt, excluding
approval/revision/hash fields and any locally inherited series direction. The
prompt requests only those inferred fields. Later-part outputs do not have to
reproduce approved tone, point of view, themes or other series choices; code
preserves them. Estimates for both stages include their response schemas.
Brief inference receives the complete verbatim source once, partitioned into
primary scene passages derived from immutable source-unit offsets. A compact
Story Bible supplies entity IDs, names, aliases, stated physical identity,
character relationships and narrative direction. Compact `visual_continuity`
includes activated looks and the state carried in from earlier parts; future-part
looks never become carried context. Unactivated catalogs, sentence JSON wrappers
and duplicate source passages are omitted. Non-narrative matter is marked in
the source view and excluded from the recommended page envelope, which follows
narrative word count (about 250–400 source words per page); each narrative scene
raises the minimum to at least one page and widens the maximum by half a page,
so Extract's scene granularity cannot set the book's length. Source artifacts
and citations do not change.
Recurring characters are prioritized for ongoing arcs without removing
infrequent participants from essential events. Its first-call instructions specify string/list types and the
transformation enum. Recoverable Brief validation failures are recorded in the
existing opt-in local diagnostic journal, so truncated provider traces do not
hide the reason for a correction.
Structured JSON parsing can locally append missing closing brackets/braces when
the result parses without changing authored content. It never completes strings,
numbers, missing values, or responses reported as output-limit truncations;
ordinary schema and reference validation still run afterward.

Extract requires private `character_participation` evidence for candidate
characters and scene rosters: `direct_action` means physically staged action,
speech, or experience; `staged_recollection` means an embodied sequence in a
memory, diary, dream, testimony, or flashback; `background_only` means mentions,
biographical exposition, unseen speakers, or background photos/social images.
Retrospective narration alone does not exclude a staged participant, and a
mention alone does not authorize inventing one.

Participation observations have a nonempty `source_quote`
found in the source with whitespace normalized only: words, punctuation, and
case remain significant. A malformed nonempty model quote is replaced at this
private boundary with that scene's resolved exact opening sentence; if no
scene-scoped source sentence can be resolved, validation fails. Repeated
observations of a character/scene pair are consolidated after every quote is
validated: any explicitly staged participation survives additional background
mentions; background-only observations never create a visual participant.
When the model's redundant roster
and participation fields disagree, a resolved scene sentence grounds the
rostered participant or adds an explicitly staged participant to the roster.
Scene rosters contain visual participants, not everyone mentioned;
background-only candidates and references are removed while relevant summary
facts remain. This includes relationship links to an undefined character
explicitly classified as background-only. Links to established registry
characters remain valid even when those characters do not participate in the
current section; other undefined relationship targets fail with their exact IDs
and correction guidance. This evidence is discarded at the extraction boundary, not added
to the canonical Story Bible. `visual_anchor` remains the shared physical
identity authority, including species/anatomy; there is no separate species DTO.

Quote resolution reads only scene openings, not the entire Story Bible schema.
Unrelated metadata errors cannot suppress valid evidence recovery. Extract
derives `total_scenes` from the actual scene array. Explicit null character
`age_range`, `gender`, and `default_outfit` become empty unknown descriptions;
missing required fields and invalid visual anchors remain validation errors.
Later sections inherit omitted book metadata from the established book. Unused,
known, ID-only character echoes are ignored in the section while remaining in
the book registry; new candidates or authored updates still require evidence.
Unrecoverable missing participation pairs are reported together with their
unresolved opening-quote cause for a single targeted correction.
An opening quote the model did not copy exactly never fails Extract and never
spends a correction: a correction regenerates the whole Story Bible, so code
settles openings on every response before validating it. A quote that differs
from the source only in whitespace (a line break typed as a space) is an exact
copy. Otherwise the scene takes the closest source sentence between the scenes
resolved around it (or, when its quote starts inside the previous scene's
opening sentence, the next sentence); the first scene owns the start of the
text. A scene with no boundary of its own is merged into the scene before it,
which already owns those sentences: summary, roster, objects, evidence and
appearance positions move with it, beats following the earlier scene's last
referenced beat. A first scene with no sentence ahead of the second scene's
opening shares that opening, and the second is merged into it. The stage log
names each settled scene. Recorded `source_start_offset` provenance is never
re-guessed, and every other validation still runs on the settled response;
corrections are spent only on those.
Candidates absent from every roster and participation entry are identified by
ID and name in correction feedback. They require source-supported classification
or removal; definitions alone never establish visual participation.

### Adaptation and state authority

Adapt pipelines each shard's validated blueprint into its locked-lettering
request immediately, without waiting for unrelated blueprints. Both operations
share one admission pool sized by `max_concurrent_requests` (default 5), which
also bounds narrative review windows and Plan detail batches. They retain their original prompts,
checkpoint identities, and source scopes; final drafts merge in source order.
Failure or cancellation closes admission, including ready lettering, while
already admitted operations finish accounting and persistence.

Adapt's bounded source requests keep complete scenes together when they fit the
unit and projected output limits. Oversized scenes may split; each authoring
prompt identifies the supplied opening/middle/closing fragment, full scene bounds,
and a read-only book scene outline. Whole-scene summaries are context, not a demand
to recreate the scene in each fragment. Prompts distinguish mentions, testimony,
recollections, and enacted events, and require only source-supported reactions;
scene participants do not imply mandatory dialogue.

Blueprint and story-repair request schemas express ledger exceptions as separate
closed alternatives for each disposition. Compression and visual motifs require
nonempty `adapted_beat_ids`; intentional omission requires an empty destination
array. Compression and omission require a nonempty reason. Prompts distinguish
literal destination IDs from prose ranges such as “beat_030 onward”; prose is
never parsed to invent destination links. Python validation additionally checks
whether a blueprint destination exists in the response before accepting its
checkpoint. Corrections retain unaffected beats and accounting decisions.

Locked-lettering generation has a separate authoring contract: the writer returns
copy, kind, speaker identity, source citations, and `presentation`. It does not
invent lettering IDs. The application validates complete locked-beat membership,
orders responses by the blueprint, and assigns unique local lettering IDs before
canonical validation; the book merge supplies final global IDs. It copies text,
provenance, and speaker decisions without rewriting them. The authoring field
`presentation` explicitly means onscreen/offscreen/narration/quoted_text/display,
never performance direction such as “listless” or “quiet, sincere”; it maps to the
canonical `delivery` field. Invalid presentation choices still require an authored
correction. Canonical checkpoints remain distinct from writer responses.

Adapt's lettering and story-repair request schemas constrain kind/delivery
pairs before generation: dialogue/thought use onscreen or offscreen, captions
use narration or quoted text, and SFX uses display. Onscreen speakers require
a known Story Bible character ID. Canonical validation still checks returned
and cached responses; invalid metadata is never silently reinterpreted.
Exhausted locked-lettering attempts retain their last parseable rejection under
`.checkpoints/adapt/lettering/<shard>/rejected.json`. Explicit Resume repairs that
exact payload within the existing request allowance; valid lettering checkpoints
keep their input keys and remain reusable. A successful repair removes the rejection.
Blueprint, locked lettering, and scoped story repair constrain source citations
to the assigned source IDs in their request schemas. Locked lettering retains
its blueprint structure; provenance is checked before its checkpoint is accepted.
Scoped story repair constrains beat, lettering, and ledger-exception citations. Both newly generated
and cached repair drafts pass that scope check inside the bounded correction loop,
before caching or splicing. An invalid cached batch keeps the reviewed candidate
active; Resume corrects invalid responses and reuses valid siblings. Neighbor
citations are never stripped or relabeled. Compression may still target retained
external beats while accounting only for source units owned by the repair.
Repairs must account for their complete source scope and retain requirement IDs
whose only realizing beats they replace. Missing citation/accounting metadata is
corrected without authoring duplicate events. Partial repairs receive the replaced
beats' exclusive requirement ownership, rather than the whole shard's obligations.

Adapt owns exact lettering. Plan assigns it to `ComicPage.content` and records
reading order and optional geometry. The two-pass global page map assigns every
lettering ID exactly once, in Adapt order, to a page carrying its owning beat.
Detail batches must preserve each page's exact lettering allocation, even when
one beat spans a batch boundary. The detail writer returns visual panels and a
page-level `lettering_placements` object: each locked lettering ID is one required
key with an authored object containing a 1-based `panel_number` and a
reservation intent: zone, footprint, line budget, optional normalized bounds,
and valid visible speaker/tail anchor.

Gemini uses a shared detail template with `lettering_placements` as a list of
objects carrying `lettering_item_id`; the request-specific adapter converts
that list to the same ID-keyed local contract before validation. Gemini always
uses the two-pass workflow, including short stories. Its page count and exact
beat/lettering ownership remain enforced by the same local validators.

The whole-book writer carries equivalent
ordered reservation arrays (closed items, no arbitrary-key schema). Every
canonical lettering ID has exactly one reservation in locked reading order.
Canonicalization clears reservation speaker and tail attachments for non-onscreen
lettering, including cached drafts, using Adapt’s authoritative delivery. Named
narrators and quoted voices keep their attribution without becoming visible
speakers. Onscreen attachments still require the item’s visible speaker.
These extend the existing calls, not another planning stage. Panels cannot return
lettering ID lists. Closed page-specific schemas require all assigned IDs and
forbid other pages' IDs; silent pages require an empty object. Compilation copies
canonical items to those exact destinations in locked order, rejecting missing
or foreign keys, nonexistent panels, and backward destinations. Canonical panel
beat citations combine the authored visual beats with the known Adapt owners of
its assigned lettering. A panel bridging two beats need not redundantly restate
both caption-owner links: they follow its exact authored word placement. This
does not claim that captions must be literally depicted. Foreign or backward
visual citations remain invalid, and the combined provenance still undergoes
the fixed-map ordering checks. Compilation never chooses a destination. Local repairs
may return corrected pages first: explicit page numbers identify their locked
allocations, and compilation orders them by the map without moving panel content
or lettering. Duplicate, missing, foreign, or partially numbered page sets fail
validation. A fully unnumbered response uses the existing fixed-map array order.
Local repairs
receive the previous panels in the same writer format. Canonical page artifacts
retain their existing lettering contract; changed request schemas invalidate
only the corresponding response checkpoints. Map/whole-book author instructions may change global allocation; detail
instructions apply the same intent within the already fixed map and do not
authorize moving words between pages. A failed detail response is corrected with its
previous panels and explicit allocation errors before canonicalization. Plan
normalization derives identifiers and reading order; it never fills missing words,
deduplicates placements, or moves lettering between authored visual moments.
Each content item declares visible
`entity_ids` and an `appearance_states` map from entity ID to state ID. State
IDs are entity-scoped. Characters, locations, and props share state catalogs.
Plan's authoring inventory exposes entity IDs and nullable appearance-state IDs,
omitting Draw's storage identifiers such as `char_001:base`. A null state denotes
the main reference: retain the entity citation and omit its state binding.
Both whole-book and detail request schemas constrain entity citations and explicit
entity/state pairs to the approved inventory. Detail batches validate these
citations locally before merge and use the existing bounded correction attempt
for invalid output. When a compiled batch's failures all cite specific pages,
only those pages are re-detailed, in parallel, each with its own bounded attempts;
the batch's accepted pages and cached response are kept. Rejection reasons are
written to the stage log. Reference failures include canonical page/panel locations,
so final validation can route concerns to their owning batch. No unknown state is
silently dropped or mapped to a different approved appearance.
State conditioning uses explicit `changed_facets` and `replaces_identity`.
Preserve `visual_anchor` and `continuity_guard` verbatim through Cast and Draw.
Plan retains incidental characters in its complete identity/state inventory
with `requires_image: false`. Draw includes their exact appearance anchor and
continuity guard as per-panel written identity authority, alongside acting and
staging, without requiring or uploading a dedicated Cast sheet. These selected
authorities are retained in `FrozenPageGenerationRequest.written_identities`
and participate in its content hash and subsequent Story Bible edit advisories.
Image authorities remain required for recurring and retained characters,
locations and props; reference overflow still fails before spend.
Scene `transient_objects` enter the same inventory as `kind: object` with
`requires_image: false`: Adapt may cite them in beat `entity_ids`, Plan cites
them where visible, and Draw sends their anchor as written identity. Character
references carry an `identity` line (age, gender and any unusual `stature`)
beside the anchor in Plan's inventory and Draw's reference payload.

Cast character sheets carry identity only and follow the character's
`reference_form` (`reference_forms.py`). The default `figure` sheet is a
neutral five-view turnaround (three-quarter and profile heads; front,
three-quarter and back bodies). A `form` sheet shows one hero depiction with a
material study and an alternate shape, for an entity with no fixed front, back
or head; a `formation` sheet shows a `group` in formation with member studies.
Every form keeps the hero in the right two thirds and a close study top-left,
so the `full_body` and `portrait` crops stay valid. An appearance state may
override the form when it changes the body plan.
Only an authored state affect reaches a sheet. Appearance-state sheets show only
the changed look (two heads and one neutral full body), never the situation:
objects touching the body, support and pose stay in the continuity guard and
the panel, and Draw treats a state asset as evidence for surface changes only.
Character states that change only `damage` are text-only; Extract clears their
`visually_significant` on the merged Story Bible. Their Draw reference inherits
the last explicitly activated significant look when chronology supplies one
consistent image ancestor, carrying crowns and clothing through minor changes
without another paid sheet. A canonical-equivalent activation resets that image
ancestor to the base; ambiguous ancestry keeps the canonical image while the
self-contained active anchor remains authoritative. Plan owns performance: every
panel has a `camera` (shot, angle) and every visible entity whose inventory
`kind` is `character` has one `acting` entry (screen-direction `facing`, `gaze`,
`expression`, optional `gesture`). Missing staging, acting for props or
locations, four consecutive identical facing/expression pairs, and six or more
appearances that are all three-quarter views are Plan-repairable failures.
Draw binds acting to subject handles. Plans written before these fields fail
their content hash and must be rerun.

Adapt's appearance changes carry forward until changed; explicit Plan state
citations remain authoritative for intentional earlier-state imagery. A beat
changes each entity's appearance at most once (`compound_appearance_change`),
because page content holds one state per entity; a transformation sequence is
one beat per resulting state. Plan rejects an adaptation that breaks this, or
cites a state Cast never approved, before its first paid call, attributing the
failure to Adapt. Users cannot rerun Adapt from a failed Plan, so recovery is
orchestrated: starting or continuing Plan while the current Adapt contract
rejects the published script runs Adapt first. Adapt resumes that script as
its failed candidate and repairs only the cited shards (never regenerating the
book); its completion auto-chains Plan. Beats that move one entity into different states cannot share
a content item (`appearance_state_conflict`, Plan-repairable). Content never
cites a look before the beat that activates it (`cross_page_appearance_state`,
Plan-repairable); Plan and Finish share one chronology check
(`appearance_chronology.py`), so Finish cannot reject a plan Plan accepted. A
plan accepted before that check is repaired one page at a time with
`POST /pages/{n}/replan`: one paid detail call keeps the page's beats, lettering
and map entry, the whole book is validated again, and a new `ComicPage` and
`BookPlan` revision are written. The page's art is then stale: corrections
only edit art of the same `ComicPage` revision, so the page is drawn fresh from
its current plan (`POST /pages/{n}/generate`) and the old art stays in history. Plan
drafts author non-lettering `continuity_intent` for scene transitions, staging,
and held-object ownership. Canonicalization folds it into `ComicPage.layout_intent`
as ordered panel staging, not a new `PageContent.continuity_intent` field.

### Protected language

Protected language is a verbatim obligation only for wording the source carries
(`protected_language.py`). When Brief proposes a draft, or an author edits the
list, each phrase is anchored to the source. If the Brief quoted a passage with
different casing or punctuation, or left out an attribution tag between two
quotations, the phrase is replaced with the source's own wording. A dialogue
passage keeps its tag, so each quotation is checked verbatim. Only in-order,
word-for-word matches count; similar wording does not anchor. A phrase the
source lacks moves to `unmatched_protected_language`, which the Story room shows
and Adapt ignores.

Adapt checks approved Briefs the same way. A phrase that is still unanchored
becomes an `unanchored_protected_language` editorial issue, never a blocking
failure. An anchored phrase that is missing blocks with source scope, so repair
can target it. When repair is spent and missing protected wording is the only
blocking failure, Adapt letters the source wording once, provider-free, as a
`quoted_text` caption with a reserved `lettering_protected_` ID. The caption goes
on the beat that already carries that source, or else on the scene's nearest
beat, and it never crosses shard ownership. Validation reports each such caption
as `protected_language_lettered_by_canary` for review. The candidate then
passes narrative review as usual.

### Plan and Adapt progress and transport limits

Plan publishes a display-only progress snapshot (`StageState.snapshot`, pushed
as `stage_snapshot` and restored by the status poll): the validated page map,
then each detail batch once its pages compile and match the map. Adapt
publishes the same kind of snapshot (`kind: "adapt"`): treatment counts, each
source shard's beats once its blueprint validates and its lettering once that
validates, and each validation round's blocking and editorial counts with the
beats its failures cite. Neither snapshot is ever an input to generation. Text work is sized to the transport that carries it
(`ai/transport.py`): the local Codex runtime executes one request at a time
under a 15-minute deadline, so Plan and Adapt clamp concurrency to 1 there.
Plan uses 4-page detail batches on every transport: detail latency is
output-bound, so smaller parallel batches shorten the wall clock. A call counts as started only when the
transport begins executing it (`GenerationCall.started_at`); admitted calls
may be queued.

### Narrative review and flexible length

Brief's page range is a preferred scale, not a minimum or maximum allocation.
Plan preserves that target as metadata while allowing the actual book to be
shorter or longer. Exact lettering, source accounting, continuity, reference
capacity, and protected language remain enforced.

Before publishing Adapt, a separate structured editorial call reviews source
windows, including omitted units, alongside global beat summaries and neighboring
beats. Supporting source units accompany the exact beat and lettering provenance
in each detailed window. Identical ledger decisions are grouped losslessly for
transport. Review contract `narrative_v6` also supplies the exact lettering outside
the detailed window as compact `reader_context`, with no duplicate local copy.
Together these contain the full adapted text in global story order. Reviewers
must check earlier publishable words before requesting a repeated date, identity,
or causal explanation; later reveals do not automatically excuse earlier gaps.
Plan must also check when its page allocation presents those words. A potentially
blocking missing-context claim receives one checkpointed verification
against the full supplied copy before it can trigger a story repair. This check
can withdraw an overlooked-context claim but cannot erase other defect categories.
Malformed verification receives one protocol correction, then blocks as invalid;
transport failures retain completed work for an explicit resume. New-run estimates
and Adapt request allowances include verification; existing cumulative limits
remain in force. Changes to distant
lettering invalidate affected review requests because reader knowledge is part
of their evidence; a content-hash change alone does not. Each silence/concentration signal
has one review-window owner with its complete sequence supplied. Lettering IDs
are valid evidence anchors and map to their own source units. Exact essential-event
and character-turn IDs supplied by the treatment are also valid citations. They
map to the source of beats claiming the requirement only when the finding has no
concrete beat, lettering, page, or source citation. Supplemental requirement IDs
do not broaden a concrete finding's repair scope. A wholly unclaimed requirement
without concrete evidence remains a book-wide concern. Invented IDs remain invalid
and diagnostics list them.
It checks
reader-visible context, repeated events, unsupported additions, and essential
development. Plan reviews the global map before detail in its
larger-book workflow and reviews actual canonical page candidates before
publication. Silence/SFX-only runs and disproportionate reuse of a beat are
computed questions that the reviewer must assess, not numerical quality scores
or automatic bans on silent comics. Defects cite known artifacts and carry
repair ownership; Plan cannot repair missing Adapt wording by inventing copy.

The review request schema scopes signal IDs, assessment count, evidence IDs, and
repair-stage ownership to the supplied window. Plan page citations use the absolute page IDs actually
supplied in the detailed window (including pages added for owned signals), not
window-relative numbers; other global pages are context and have their own
review windows. Incorrect citations receive a protocol correction before they
can route a story repair. With no signals, the assessment
array must be empty; the reviewer still checks the story and reports defects in
`findings`. Checklist entries for arbitrary beats, pages, or the ledger are not
substitutes for the detected signals. Duplicate assessments remain checked in
Python, with explicit missing, unexpected, and duplicate ID diagnostics.

Independent review windows run with at most `max_concurrent_requests` admitted operations. They
inspect the same fixed candidate; no window consumes or acts on another's
verdict. Findings merge in window order with the existing evidence-based
deduplication, so completion timing cannot change repair ownership. Exhausted
protocol correction stops new admission and records all completed invalid
windows; admitted siblings finish checkpointing and are reusable on Resume.
This changes scheduling, not review scope, evidence, or repair allowances.

Review contract `narrative_v6` separates advisory preferences from substantiated
blockers. Padding, pacing, emphasis, panel variety, weak page turns, and
`redundant_caption` (a caption that only narrates what its panel shows) never
block or trigger automatic polishing. Negative signal assessments are advisory;
they cannot manufacture a missing-context blocker. Advisory findings are saved
in the review record, stage validation, and accepted Adapt/Plan editorial notes,
and shown as optional notes in their reading views.

### Comics craft guidance

Adapt and Plan carry craft guidance for every text model, not only Gemini's
checklist ([research](../research/2026-10-10-adapt-plan-comics-craft.md)).
Adapt's word-writing passes ask for about 25 words per balloon or caption,
splits at sentence boundaries, the author's own dialogue over paraphrase, and
captions that add voice, time, interiority or causal links rather than narrate
what the panel shows. A protected passage stays whole in one item. Adapt notes
`long_lettering_items` (over 30 words, excluding quoted text, SFX and protected
passages that fill the item) as one grouped editorial note. A short protected
phrase does not exempt surrounding unprotected copy; remedies must preserve
the protected passage whole and verbatim.

Page sides are derived, not authored: page 1 and every odd page is right-hand,
matching the combined export, and canonical pages set `spread_role` from the
page number. A page side a model still returns is dropped before validation.
Plan prompts teach that a turn happens only after an odd page, so setups and
cliffhangers belong at the end of odd pages and turn reveals at the top of even
pages; they also give panel-count and word-load guidance (about five panels a
page as a descriptive reference, 50 words a panel) and ask for an orienting shot
when the story moves to a new place. Plan computes these advisory notes:
`reveal_on_right_page`, `turn_setup_on_left_page`, `uniform_panel_count` (four
or more consecutive pages with one count), `unestablished_location_change`
(the first two panels after a place transition, across beat/page boundaries
but stopping at another place transition, are all close shots), and, for
editable editions, one grouped `crowded_lettering` note (a panel over 35 words
or a page over 150: editable art is lettered after drawing, so it keeps to the
low end of editorial norms). Integrated editions keep `dense_integrated_lettering`. None of these block,
repair or alter lettering. Repeated counts invite review, not mandatory variation.

Page allocation uses the edition's advisory budget before locking lettering IDs:
editable pages aim for at most about 150 words; integrated pages for about 110
words and 10 items, matching their density signal. Protected items remain whole.
The Gemini checklist reinforces the same budgets rather than supplying a
conflicting cap.

Plan's generation and estimate prompts receive the approved Brief's tone.
`rhythm_summary` carries a coherent layout vocabulary; page `rhythm_intent`
carries motivated changes, shared with neighboring pages in parallel detail
batches. `layout_intent` describes ordered panel proportions and row grouping.
Clear rectangles and gutters are the default; steady grids remain valid.
Wide, tall or larger panels are optional story-driven choices, not a rotation
or quota. Unusual shapes require a narrative purpose and clear reading order.
No generated geometry, new layout artifact or automatic variety repair is added.
Draw receives that direction under existing selected-style, reading-order and
author-pin authority; editable art still receives no lettering reservations.
Local replans retain the accepted map's layout direction and the Brief's tone. Tests establish the
handoff, not visual adherence or storytelling quality.

Changed prompts require new matching generation requests. A `narrative_v6`
refresh is one review pass, potentially multiple window calls plus protocol
corrections or missing-context confirmations, not necessarily one paid call.

A substantive finding must state a concrete consequence and reader impact and
quote exact passages from their cited supplied artifacts. Contradictions and
invented events require at least two distinct cited artifacts; an indispensable
context gap requires at least one passage. An explicit requirement violation
must also name an approved requirement. A missing or unverifiable evidence claim
remains advisory. This raises the admission bar for blocking judgments without
claiming automated literary certainty. Structural invariants and malformed or
stale review checks remain blocking. Plan reviews see the adapted script, not the
source, so a Plan-time finding routed to Adapt (copy or events) is advisory:
Adapt's source-backed review governs the script, and Plan cannot repair it.

When a published Adapt script has an outdated or missing review, **Resume
adaptation** revalidates current source/Brief/Cast constraints and refreshes the
review of that exact script. It does not rewrite or renumber the script, change
its content hash, clear Plan checkpoints, or reset the cumulative work budget.
Review notes are saved in the review receipt and stage validation without
changing the published artifact. The Pages failure view offers this resume
action alongside the separate, destructive **Start adaptation over** action.
After refreshing Adapt, an already failed Plan requires an explicit retry;
the normal auto-chain starts only pending stages.

Adapt normally permits one repair of the cited source scope. One final bounded
repair is allowed when blocking codes strictly decrease or the repaired candidate
exposes a changed narrative-review finding. Repeated failures do not extend the
loop. Plan permits at most one narrative repair pass. Plan repairs the compact
map before detail, or after composition only the cited pages (in parallel; contiguous cited pages
stay together), and such a repair may split a cited beat into more panels than the map's rhythm intent
names; a narrative map revision consumes that
allowance. It never escalates an unresolved detail finding into whole-book
regeneration. Map, whole-book, and detail schema corrections retain a separate
bounded allowance and preserve the current repair feedback. Plan evicts completed
responses rejected by its schema or owned contract checks from the response
cache, so explicit Resume can replace them while retaining valid batches.
Upstream blockers and malformed review evidence do not invalidate valid planning
responses. Transport failures do not trigger automatic resubmission.
Unresolved blockers stop with evidence and preserve the draft for explicit
review. Structurally valid Plan pages are retained in `plan/review_draft.json`
before narrative review, readable through `GET /plan/review-draft`; they never
become Draw authority. Successful publication removes that temporary draft.
The cumulative work ceiling still bounds all requests.

`TargetArtifacts` stores `adapt/adapt_review.json`, `plan/plan_map_review.json`,
and `plan/plan_review.json`. Required successful reviews are keyed by version and
input digest. Draw initialization, batch preflight, individual generation, and
correction preflight reject missing, failed, or stale Adapt/Plan reviews before
spend. Reading existing pages and OCR-only recovery do not require new narrative
review. Older projects need rerunning Adapt and Plan; no artifacts or request
hashes are migrated in place. A frozen pending image result is retained, never
authorization to silently redraw or release a reservation.

### Style and reference authority

Style curation generates **six** base proofs: three story fits, an adjacent
option, a contrast, and a wildcard. Twelve typed art-direction sketches are
curated one per role rather than taking the first six. Sketches omit the
production system; only the curated survivors get lettering, preset, page
framing, strengths and risk, designed in parallel (`style.production`, one
schema-repair attempt each). The default portfolio has at least four
`stylized`/`graphic` directions, at least one `realistic_illustration`, and at
most one optional `photographic` direction. Photography is not mandatory.

Each generated candidate declares `proportion_family` (`naturalistic`, `heroic`,
`elongated`, `compact`, `caricatured`, or `geometric`) and a concrete
`character_design`. Selection requires four proportion families including three
non-naturalistic families, with shape differences weighted above surface/medium
wording. Design and rendering category are compiled into selected art authority
and its identity/fingerprint; they are not picker-only metadata.

Each candidate also declares a `color_strategy` (`monochrome`, `spot_color`,
`muted`, `naturalistic`, `saturated`, `high_key`) and a `medium_family`
(`comic_production`, `painted`, `drawn`, `printmaking`, `collage`,
`photographic`, `novelty_process`). Default selection requires four color
strategies, at most two low-chroma and one monochrome option, and at least two
full-color options. At least one story-fit role is `comic_production`, and
`novelty_process` media (cyanotype, stained glass, diorama and similar) appear
only as the wildcard; regenerations rotate away from earlier novelty processes.
An author `color_restriction` or `medium_restriction` lifts the matching rule.
The palette and color strategy compile into the selected style's `COLOR —`
section, with an anti-warm-cast clause and, for monochrome, a positive-rendering
clause. `medium_family` is curation metadata outside the stable id. Extracted
`style_notes` describe the story world and never choose a palette. See
[style quality research](../research/2026-10-08-graphic-novel-style-quality.md).

An author-directed set is one unchanged faithful proof plus **five** neighbors.
Neighbor curation uses five roles, at least three stylized/graphic options, and
the same shape-diversity requirement. Explicit author restrictions override
only the constrained axis: `medium_restriction` covers medium/rendering,
and `proportion_restriction` covers proportions. Each is the model's reading of
the author direction and may paraphrase or interpret vague wording; without an
author direction, restrictions are ignored. Explicit photographic-only directions may constrain both; a dark mood,
identity anchor or an ink-only medium does not mandate naturalistic proportions.
Contrast and wildcard directions honor the same restrictions.

Sketch schema correction, missing roles and inadequate diversity share at most
two sketch attempts. A complete but unbalanced pool receives the remaining attempt;
no invalid portfolio is silently accepted or padded with invented directions.
This validates declared directions, not generated pixels. Paid-image retries,
visual verification and author selection remain explicit. Existing saved proofs
remain visible and selectable; increasing the default does not auto-generate a
sixth image or replace the selected style. The picker uses three columns on
desktop, two on tablets, and one on narrow screens.

Style proofs share one bounded scene roster and location across the generated
brief, deterministic fallback, and request compiler. The scene is chosen
deterministically from the first part's opening (at least eight narrative
scenes or a third of them): avoid climax-like beats, then prefer the lead
character, action or emotional scenes, and turning beats, then earlier scenes.
The brief stages a charged moment just before a turn, ending on one large,
readable reaction face with a named key light; proof constraints in both
lettering modes add a legibility clause. Contextual mentions cannot
add subjects or crowds. Brief prose owns staging, not redesigned identities;
the compiler supplies each selected canonical `visual_anchor` exactly.
The v7 brief cache fingerprints the selected evidence, model, and prompt;
stale cache entries are not reused. Candidate styles render the same selection.
Concurrent sample jobs serialize shared-brief authoring and recheck the cache;
a durable suggestion batch resolves its brief once, including a deterministic
fallback when authoring fails. The brief depends only on the Story Bible, so a
batch authors it while sketches are curated and cancels it if curation fails.
Proofs run under `image_concurrency` (the shared Style/Cast image limit). A
durable batch persists `style_phase` (`directions` → `production` → `proofs`),
`style_phase_at`, and the curated `style_shortlist` in its job payload so the
Look room can explain the current step after a reload.

Editable full-page style samples generate art and framing only, reserving four
natural quiet areas without words, balloons, boxes or effects. The compiler and
cost estimator share that same contract. Each generated candidate supplies a
closed `lettering_design` with validated caption, speech, thought and SFX role
tokens. Selection seeds `lettering/style.json`; existing/custom directions
without generated tokens use an explicit preset baseline. Neither structured
tokens nor post-production prose enter image-model style projections.

Editable style cards show a separate cached software-lettered proof, composed by the same
bundled-font SVG engine as finished pages. Raw sample bytes and their generation
metadata remain the reference authority. `GET /styles/{suggestion_id}/proof/{kind}`
serves the derivative, keyed by raw art, style, engine and specimen copy.
Specimen words are the project's story proof copy (`samples/style_proof_copy.json`,
feature `style.proof_copy`): caption, speech, shout, thought and SFX lines from
the proof scene's source passage, spoken only by its listed subjects and
bounded by `SPECIMEN_MAX_CHARS` so every bundled design fits. The copy names its
`speaker` (speech and shout) and `thinker` (thought), each a listed subject;
copy without listed owners is invalid. It is authored
with the shared proof brief and cached by the same scene selection; every proof
of a project letters the same lines. Without valid copy (failure, overrun, or
the brief pass disabled), proofs letter neutral role labels, never invented
dialogue, and a line one design cannot fit shows that role's label.
The speech reservation contains separate normal and shouted-speech specimens;
the shout uses a burst variant of the speech style, distinct from free-standing
SFX. Specimen tails attach after text fitting and stay short, ending near
`SPEAKER_POINTS`. Editable proof art with story copy stages the speaker and
thinker at those points, so new copy is new art request identity. The overlay
letters story copy only on art whose stored prompt carries that copy's staging;
other art letters role labels, so a pointer never assigns a line to whoever
the art happened to place there. Generated thought
styles use compact padding. The shared renderer balances thought text across lines
and fits it inside unequal cloud lobes distributed around the full perimeter.
Each element/style has a deterministic silhouette shared by fitting and rendering;
moving a bubble does not change its shape. SVG font families are
quoted so measurement and rendered text use the same bundled font.
Integrated style proofs draw the same caption, speech, shout, thought and SFX specimen
strings directly into the image using the candidate’s prose lettering standard,
with tails pointing at the named speaker and thinker; new story copy is new request identity, so older integrated proofs become refreshable.
Software design tokens remain excluded from the image prompt; the endpoint serves
the original lettered raster without an overlay. Compilation, estimates, freshness
and delivery follow the project mode, including a retained frozen edition.
Legacy/stale proofs remain visible as raw images and require an explicit
mode-appropriate refresh; no overlay is added to an old baked proof. Hybrid Draw uses only art and
framing directions. Cast reference prompts use only the art-rendering projection,
not page lettering, borders, or gutters. Style and reference authority are not
disposable scene prose: approved style imagery owns rendering, not depicted
people, objects, text, or layout. Canonical subject references own compatible
identity/state facets, not their original rendering style. Active-state anchors
override explicitly changed anatomy, age, proportions, wardrobe, location, or
object facets; a provider-safe rewrite must not reverse a state or restore
missing anatomy. Textual style notes remain secondary to an approved style
reference's intended rendering language, subject to surface-fidelity constraints
for incidental texture; a generated-neighbor variation instead owns its declared changed
rendering facets.

Cast first writes `refs/cast_design.json`: a versioned, story/style-bound design
plan covering the entire ensemble. Face, hair, silhouette, posture, wardrobe and
contrasts are explicit adaptation choices for unspecified details, never edits
to source visual anchors. The prompt receives the full roster and co-occurrence
sets. Missing, repeated or duplicate-id designs are rejected before image work.
The response schema limits the roster to the exact requested IDs and count.
A completed JSON response with invalid designs gets at most one correction with
the validation details; transport failures and unparseable responses are not
resubmitted. Both completed attempts retain their usage, and the estimate includes
the correction allowance. Established designs stay fixed through the correction.
Canonical sheets receive these choices alongside verbatim source anchors, age,
wardrobe and distinguishing details. Authorized correction addenda take priority.

Canonical character requests use the selected raw Style proof directly
on every image route. A character look drawn from its main sheet does not: the
sheet, which the proof styled, is its rendering authority and also keeps its
wardrobe unless the look changes clothing. A proof depicts the book's own
characters, so beside the sheet it was a second identity that looks copied
(hair, crown, gown). A look that replaces identity has no sheet and keeps the proof. Generated material boards are not substitutes: they lose
facial abstraction and character proportion evidence. The proof owns artistic
treatment, not depicted identities, hair, costumes, poses, gaze, expressions,
camera angles, text or composition. Cast design and canonical/state anchors own
identity; scene instructions own acting. Missing selected proofs reject generation
before spend. Existing artwork is versioned only on an explicit regeneration.

Draw never uploads the proof. A proof drawn from the book's own scene depicts
the cast, so beside the approved sheets it acts as a conflicting second version
of the same people (2026-10-14: a proof costume replaced a Cast costume across
pages). Style reaches pages through the proof-conditioned Cast sheets and the
board-conditioned plates, which Cast Check reviews for style. Reserve any
correction-parent slot before packing subject reference sheets; never drop
identities to fit a provider limit. Integrated and editable
pages both receive surface-fidelity guidance. Corrections retain their requested
scope and untouched artwork. Saved requests and rendered pages are not rewritten.

After character generation, Cast visually compares all canonical sheets using
labelled contact sheets and the configured visual review model. The typed
`refs/cast_review.json` stores suspected lookalikes, anatomy, wardrobe and identity
concerns, keyed to source, designs, correction direction and exact image hashes.
`GET /cast/review` reports missing, stale or current evidence without spending,
plus `reviewing` while the model call is in flight. Redrawing a character's main
sheet (plain or instructed) re-runs the review in the same job when every sheet
and design is current; its usage settles with the redraw and is included in the
redraw estimate, and a failed review leaves the check stale without failing the
redraw. `POST /cast/review/dismiss` records that the author judged one note fine
(`refs/cast_review_dismissals.json`), bound to the exact sheet hashes of its
characters, so the note returns when any of those sheets is redrawn. Notes are
advisory: approval needs a current review, not an empty one.
A Cast run with failed assets or checks fails the stage instead of entering the
author checkpoint. Project status exposes `stages.cast.approval_blocker`, using
the same read-only gate as approval: no failed/incomplete items, all required
canonical and appearance images present, and a current identity review. The UI
offers Resume Cast for blocked historical checkpoints rather than Continue.
`stages.cast.failures` lists each failed reference; a provider decline adds
`likely_triggers`, phrases in the sent request that commonly trip safety filters
(`content_triggers.py`, a deterministic heuristic, never a verdict). The UI offers
a less graphic version, which opens the reference's direction review prefilled,
and a link to reword the entry's description. Neither spends until confirmed.
Resume rechecks and counts reusable references; its progress total is the full
inventory, not the number of new image calls.
The Cast screen links each concern to its characters. Empty findings do not mean
verified visual quality; the author remains responsible for approval. Approval
requires a current comparison, and findings never trigger automatic regeneration.
Resume Cast reuses current artifacts and refreshes stale ones, including review.
An individual correction requires current designs and a current rendering board;
state corrections also require a current canonical parent, before paid work.

Design and visual-review text calls use StageRuntime usage accounting and are
included in Cast admission/funding and estimates. No automatic text transport or
invalid-JSON retries are added. Neither software tests nor a completed visual
comparison establish that new generated art is distinct; that needs live visual
assessment of the resulting references.

Extraction requires explicit `changed_facets` and `replaces_identity` for every
returned appearance state and rejects two activations for one entity at the
same scene/beat. Its prompt includes plot-critical silent/nonhuman actors even
when they occur in only one scene, and explicit returns to the canonical look
when a later source passage depicts an earlier lived-time flashback. These
prompt requirements do not prove semantic completeness of a generated roster.

Style references are rendering-only, not implicit edit parents. Only explicitly
selected edit-parent references authorize preserving an existing composition
or applying an edit. Canonical text outranks mistaken parent pixels: restoring
canonical species, identity, age, or anatomy is a valid correction, not permission
to redefine those facts. State anchors still own explicitly changed facets.

Location state plates use `plates/{location}/states/{state}.png`, with
instructions beside them as `{state}.instructions.jsonl`. Reads, writes, and
lineage scans stay scoped to that location; there is no migration or alternate
reader for the old location-state artifact layout.

### Frozen pages and corrections

The model catalog offers Sunburst and Nano Banana 2.1 for Style/Cast images and
complete-page Draw. Sunburst remains the default. Nano Banana 2.1 uses the direct
Vertex route with a 1K portrait Draw profile (848×1264) and 14 total ordered image
inputs, including a correction parent; overflow is rejected before submission.
Nano Banana Style/Cast requests freeze `quality=low`, selecting native 1K;
Sunburst Style/Cast quality remains configurable. Both Draw choices preserve the
project's integrated or editable lettering mode.

Draw compiles selected references, distinct subject labels, panel assignments,
geometry and mode-specific lettering instructions into one frozen request.
Projects explicitly choose integrated or editable lettering at creation (see
[ADR 0022](../adr/0022-project-lettering-choice.md)). New integrated profiles set
`exact_visible_lettering=true`, send canonical copy to Draw, and export the
original raster. Software lettering controls are unavailable for these projects.
Lettering mode changes require a new project.
Editable profiles set `exact_visible_lettering=false`: their wire lettering
array is empty and their prompt forbids balloons, caption boxes, SFX glyphs,
placeholder words, pseudo-writing, and reserved blank areas. They request continuous
scene artwork; Plan placement reservations seed the editor only and are omitted
from image requests. Editable Plan detail and Draw prompts share `lettering/room.py`
framing: a panel with more than 25 words framed tighter than a medium shot is drawn
as a medium shot or wider, and lettered panels keep faces out of their top quarter
with the scene continuing there. Integrated prompts keep Plan's framing. Canonical copy remains in Adapt/Plan; it
is not a typesetting payload for the image provider. Excess
references fail before submission. Less-graphic framing retains identity
references. An edition retains its profile while it remains spendable. Otherwise, new
work advances the edition revision to the configured profile, preserving existing
pages and frozen request provenance. Cost estimates select this revision without
saving it. Profile changes must retain the lettering mode. Read/review keeps the
saved edition profile. Use the explicit upstream
Plan restart/new-edition lifecycle for hybrid generation from an old allocation;
there is no raster-text removal or silent conversion. Request hashes identify input but do not guarantee
provider deduplication. Ambiguous image submissions are not automatically retried.

Local Codex development routing can bind a first Draw edition to a separate
experimental complete-page profile when its image route and OCR are both
subscription-selected. It permits five total ordered image inputs, including a
correction parent; all required visual authorities remain intact. Hybrid copy
stays outside the image request.
When separate authority images exceed those slots, Draw creates labeled PNG
reference sheets with at most two authorities per sheet, preserving every source
pixel without cropping or resizing. Exact source hashes, anchors, guards, and
sheet regions remain in the frozen request, and prompt bindings identify each
subject's region. Requests that fit retain their original reference bytes. The
model/profile and canonical Plan do not change. This permits up to ten authorities
for initial Draw and eight with a correction parent; pixel-budget or larger
overflows still fail before submission. Reference previews show the original
subjects and thumbnails. Packaging checks do not establish generated identity
fidelity; that requires visual review.
Queue all prepares every page before any hold or enqueue. Subscription quotes,
holds and debits are zero; observed cost and actual image backend remain unknown.
This does not relax the production Vertex profile; both use current wire contracts.
Every frozen Draw prompt explicitly requires the edition’s portrait page canvas,
including corrections. Codex native resolution may vary, but Draw rejects a
width-to-height ratio more than 1% from the frozen profile before publishing the
page, without automatically retrying. Finish preserves accepted native bytes and
per-page PDF/CBZ geometry, rejecting incompatible fixed/custom trims rather than cropping.
See [Codex development capabilities](codex-dev-capabilities.md) for setup and limits.

Adapt beats cite Brief requirement IDs without repeated requirement prose.
Missing citations remain validation failures rather than being inferred from
keyword overlap. Explicit beat entity scopes allow bounded Plan context.
Character scope pruning keeps approved location and prop descriptions available
when Adapt lists only actors. Each new Plan panel must author a setting decision
(location, environment visibility, and direction) and a physical-relationship
list (participants, contact, orientation, and support; empty when none are visible).
Visible settings must cite an approved location in the panel's entity IDs;
relationship participants must also be cited. These checks use the existing
bounded Plan repair path before Draw. Close-ups may keep the setting offscreen.
Plan compiles this direction into canonical `layout_intent`, preserving the
existing saved-page contract and reference selection. A mention of another room
in dialogue does not move the scene; available references are not automatically
added to panels. Narrative review can cite canonical layout/staging as evidence
for a setting or attachment contradiction. These are planning checks, not proof
of generated-image fidelity.

Draw takes settings from panel staging, not backgrounds in style or identity
references. Current author corrections override disputed parent staging and
carry corrected contact, orientation, support, and setting through the affected
panels. Existing pages can receive an explicit full-page correction without
replanning other pages; new planning requirements do not rewrite saved artwork.

OCR is blind to expected copy and runs only on raw saved art. Integrated profiles, including retained baked editions,
compare canonical lettering and observed order. Hybrid profiles instead
record `unexpected_generated_lettering`, including its detected region, for
comic text that should not have been drawn; incidental signs/documents remain
distinct. It never checks a software-composited image and does not establish
visual identity, object fidelity, or scene correctness.
The opt-in [Textract close-up reader](textract-ocr.md) submits bounded disputed
integrated/baked crops during admitted checks. It retains raw provider evidence
and attempts, never submits during cached revalidation, and requires explicit
retry after unknown outcomes. Canary absorbs its fee; primary OCR funding is
unchanged. An unfinished close-up read never makes a page unchecked; the author
retries it from the finding (`analyze?second_look_only=true`), which refuses
any work needing a primary read and reserves no author credits.

The disabled-by-default [crop OCR experiment](crop-ocr-experiment.md) can add
a local, blind PaddleOCR read of mismatching integrated/baked lettering regions.
It preserves primary observations and author decisions. Conflicting or weak
reads remain uncertain advisory evidence; the second pass never certifies copy
or a visual concern. Saved crop reports are keyed by exact render/canonical
lineage, observations, worker/runtime/model fingerprint and policy.
Page-render and preview HTTP responses use `private, no-cache`: an Adapt/Plan
restart can reuse page and render revision numbers in a new edition. The client
uses `delivery=2` URLs to bypass responses previously cached as immutable for a
year. Derived previews remain cached on disk within the active edition.
An optional reference-aware visual check records up to eight editorial findings
and uncertainty independently of OCR; it does not certify a page as correct.
A saved visual report is reusable only while the canonical page, exact render
bytes, approved reference bytes, review model, prompt, and schema still digest
identically; otherwise the report is null until a matching paid review lands.
Reviews receive prior visual concerns from ancestor renders under the same
canonical page and approved reference set. A repeated concern links to its
existing issue ID when the subject, panel, feature and expected outcome match;
new concerns get new IDs. Closed author decisions remain closed, and a repeated
finding does not create another dismissal task or certify a correction. The
immutable prior evidence enters the review digest; mutable decisions do not,
so clearing an issue does not invalidate or repay the review. Unknown IDs and
panel/category mismatches are rejected. Updated prompt/schema versions require
a new check; saved requests, images and older reports are never rewritten.
Canonical lettering is immutable for Draw: story-source wording changes return
to Adapt/Plan, never image correction. Display wording/translation changes use
Pages Lettering, leaving Adapt and base art unchanged. Missing or stale OCR is
unchecked advisory evidence, not an export blocker or instruction to redraw. Recover checks on
saved pixels; paid artwork correction is a separate action for an identified
change. A correction is one explicit
author-selected batch — linked tracked issues and/or new manual
instructions — where each change carries an editable instruction plus
normalized page-fraction marks (origin top-left), an optional author note, and
explicitly selected source passages. Bookwide beat summaries, treatment spine,
appearance chronology, and continuity are compiled into every correction's
provenance; author-selected passages retain their source context and only
auto-gathered page units are budget-truncated. Hybrid image prompts redact long exact
publishable phrases from read-only context rather than reintroducing them
as typesetting instructions. Preview compiles, validates lineage (canonical
revision/SHA, parent render revision/bytes), and estimates cost without
spending or mutating issues; manual issues are created deterministically
inside the reserved job. Submit enqueues exactly one full-page job; stale
lineage is rejected, unselected open issues remain, and the exact submitted
correction (edited instructions, annotation notes, manual note) is served back
per render revision — null for initial draws. A generated visual fix stays
`revised` (visually unverified) until a person confirms; only OCR-proven text
fixes may resolve by OCR. Finish checks artifact and render lineage,
state citations, unresolved issues, dimensions, and packaging. It does not
invoke a creative model.

Corrections use a short plain-text edit prompt, not the page-generation
specification: the requested changes (with marks and regions as page
percentages) come first, then "keep everything else as in Image 1" with the
rendering-fidelity block, then constraints, and the changes are restated last.
Image 1 is the parent page; constraints bind each approved identity/state/style
reference to its actual upload position (`Image N (asset-X)`), keep visual
anchors and continuity guards verbatim, list panel cast, pinned geometry,
earlier author requests and exact lettering (or the hybrid no-lettering rule).
Original panel acting and staging, the style essay, treatment spine,
chronology and continuity are omitted because Image 1 already carries them;
only page/neighboring beat summaries and author-selected passages remain as
reference. Full book context remains in provenance. Prompt priority is not
proof that the model applied the edit. An older tracked visual
concern can target the current render only when the normal issue lineage matches
or a saved visual report explicitly links that concern to those exact current
pixels. Confirming such a revised concern records the render the author inspected.

Correction lineage retains the exact original producing prompt in
`PageRenderCorrection.retained_instructions`, then carries prior correction
instructions and notes forward. These are subordinate, non-lettering historical
constraints: current canonical copy, approved identity/state/style, and author
pins remain authoritative, and current changes supersede conflicting earlier
changes. Historical subject/image bindings are not current attachments, extra
panels, or copy to render. This preserves deliberate depiction, including
less-graphic intent, without adding a top-level `depiction` field to
`FrozenPageGenerationRequest` or rehashing stored requests to invent one.

## Editorial workflow

Adapt/Plan findings are revision-scoped: keep/reopen dispositions apply only
while both the editorial revision and the individual issue fingerprint still
match; drifted evidence resurfaces as open.

### Carried notes

The page change check (`corrections/interpret`) may name what a change reaches
beyond the page's art, as a typed claim: a script line (`line`), a missing or
unclear story moment (`beat`), or a look or place fact over a run of pages
(`look`). The model names the fact; `note_scope` finds the pages from the plan
and adaptation. Routes live under `/parts/{part_id}/notes`.

- Preview resolves the pages and writes only `notes/<id>.json`. Free.
- Checks (look only) ask, per other drawn page in the run, whether its current
  art breaks the fact. Each is a paid page check; nothing changes.
- Apply is one funded call that writes everything or nothing, stamped against
  the adaptation, plan and Story Bible revision it previewed:
  - `line`: a typed edit of one `LetteringItem` in the adaptation and on its
    page. No model writes the line.
  - `beat`: one call rewrites only the named beats (same ids, order and source
    units), then only the pages citing them are re-planned.
  - `look`: a new look is added to the series Story Bible (timeline at the
    start page's scene) or an existing one reused; only the chosen pages'
    panels are bound to it. The adaptation is unchanged.
  Script changes are recorded as `AdaptationAmendment`s. A ComicPage stays
  valid while none of the beats it cites changed since its pinned revision, so
  untouched pages keep their art. Both narrative reviews run as in a stage
  run; any new invariant failure or review failure restores the snapshot.
- Undo restores the snapshot (and removes an added look) while the adaptation
  and plan are still the ones apply wrote. Drawn art stays in page history.
- Nothing redraws. Changed drawn pages go out of date for the author to redraw.

### Pages review context

`/project/{project_id}/pages` carries `page=N`, `review=page|visual|checks`,
`filter=all|needs-review|drawing|failed`, and optional
`reading=adaptation|page-plan`. The URL is authoritative; project-scoped
session storage restores review context only on an entry without query
parameters, and does not persist the reading drawer. Book findings link to
the affected page and review view.

The exception queue contains pages with `open` or `revised` issues; a new
render alone does not clear it. Filters are pressed-state buttons, not tabs.
Drawing and failed filters reflect current page artifacts and failure phase,
not historical job failure alone; a current completed check supersedes an old
failed job. Saved artwork with incomplete checks is presented as an analysis
recovery, not an image-generation failure. Drawn and checked counts are separate.
Next-unresolved navigation wraps through remaining flagged pages. Reading
Adaptation/Plan stays read-only.

## Recovery and costs

Adapt resumes by revalidating its saved failed candidate against the unchanged
source and approved brief. Source-backed protected quotations receive explicit
quoted-caption delivery; exact protected book titles do not require terminal
punctuation. Source matching ignores paired Markdown emphasis without rewriting
source text or approved wording. Protected excerpt comparisons also tolerate
initial-letter capitalization (a clause beginning mid-sentence in the source);
interior case, words, and punctuation remain significant. Blueprint, lettering,
and scoped repair prompts locate protected phrases with source-unit citations.
A complete sentence copied verbatim into a
quoted caption from a longer source quotation can receive its single missing
closing quote locally; paraphrases, incomplete sentences, missing opening quotes,
and other unbalanced delimiters still need repair. Missing protected phrases and
incomplete display text cite their owning source units and beats for shard repair;
source-scoped findings are not sent to unrelated shards.
Missing terminal punctuation alone produces a nonblocking
`possible_clipped_display_text` editorial issue: headings, date cards, chants,
and quoted phrases may intentionally omit it. Unclosed quotation marks and
delimiters remain blocking. Warnings preserve the exact lettering and cited IDs.
A valid recovered candidate with current successful narrative-review evidence
is persisted without a model call; structural validity alone does not waive review.
Changed source/brief identities or a new story instruction prevent this reuse.
A structurally valid candidate with a completed failed editorial review can also
resume as repair input, without publication. Its exact review digest, instruction,
and completed review-request receipts under the original review model must match
the current source/Brief/Story Bible work lineage. Selecting a different model
preserves this story progress; subsequent review requests remain keyed to the
selected model and cannot reuse another model's verdicts. Resume retains that improved candidate
instead of reconstructing the original draft. Its unchanged review windows remain
cacheable. Missing/stale receipts fall back to the existing generation checkpoints;
no old review is promoted to successful evidence. A typed candidate checkpoint
also binds the unpublished candidate, its source partition, and any pending repair
batch to these exact authorities. It is saved before review so transport failures
or an exhausted work limit do not force a return to initial generation. Completed
unchecked repairs can be reconstructed from exact original-model prompt hashes
before the next model reviews them. Resume estimates omit initial story generation
when this saved work is eligible; repair and re-review remain uncertain scenarios.
Repair inputs use the same
global beat and lettering IDs cited by the reviewer, and repartitioning rejects
cross-shard literal provenance or reordered shard intervals. Explicit compression
may cite another shard's globally identified beat.
An interrupted repair batch reuses its completed siblings only when
every existing sibling matches the exact model and prompt hash. Only the missing
sections generate again. A complete response batch interrupted before candidate
validation also remains reusable. A separate receipt records the exact batch's
completed validation outcome, including narrative review when structural checks
pass. Only checked complete batches require a fresh repair namespace, so saved
responses survive a splice crash without trapping retries in a rejected answer.
Repair scope starts from affected source scenes, then includes all source units
and literal ledger claims carried by any beat being replaced, including its
lettering. Overlapping beats and intervening beats in authored order expand that
scope until stable, producing one contiguous replacement interval. Repair
prompts include up to three retained beats on either side with their exact
lettering, including neighbors across shard boundaries. This read-only context
establishes which events already occur outside the replacement; it grants no
additional source ownership or permission to rewrite those neighbors. The splice
preserves the repair's authored sequence and the untouched prefix/suffix; earliest
source citation is not used to sort narrative order. StageRuntime logs cited and
closed source counts per shard before repair generation. The splice rejects
a partial scope before replacing anything; it must not keep a caption claim
while deleting the caption that realized it. All sibling repairs are applied to
the book together before any identifiers are rebased. Compression-only links
resolve to retained or replacement beats across shards; replacement identity
must be supported by source provenance or the repair's explicit ledger decisions.
Unknown destinations, cycles, and deletion of a referenced beat without a
supported replacement are rejected. A nearby beat is never an invented fallback.
Resolved compression remains subject to narrative review.
The Pages error screen offers Resume adaptation with the existing estimate and
confirmation, plain-language checks, and collapsed technical evidence.

Paid project actions require `Idempotency-Key` (nonblank, at most 200 characters).
The persistent request journal keys replay by verified account, HTTP method/path,
and action key; the fingerprint covers query and canonical body (multipart file
bytes, not its random boundary). A saved response replays without dispatch, even
while drained, with `Idempotency-Replayed: true`. Different input returns 409
`idempotency_conflict`; an admitted request without a recorded response returns
409 `idempotency_indeterminate`. Missing keys return 400
`idempotency_key_required`. Inspect status, jobs, and saved output before explicit
recovery; never automatically retry a paid submission or replace its uncertain
receipt with a fresh key. Request hashes are not provider-side deduplication.

Browser unresolved-action receipts survive reload and are account/input-scoped.
Account changes abort tracked requests, reject late responses, replace the query
cache, disconnect pipeline events, and clear style-job and credit-resume state.
Do not reuse another account's cached project, balance, job, or action state.

`GET /jobs` (also `/generation-jobs`) returns `{"jobs": [...]}` for the verified
account/project, optionally filtered by repeated `ids` query parameters. It
combines live jobs with persisted observations. After restart, previously
queued/running observations become failed/recoverable, not automatically queued.
Complete-page Draw jobs include `is_current_page`: true only when their request
hash matches a retained frozen request for the current page revision and content
hash. Pages ignores jobs marked false for failure badges and drawing status;
the job history remains available after Adapt/Plan restarts.
Pipeline status and saved artifacts remain recovery authority. Pipeline and
style SSE broadcast to independent bounded subscribers: 128 events of in-process
reconnect history and a 256-event queue per subscriber, dropping oldest overflow.
This is not a durable event log or a substitute for fetching status/jobs.

Cast, instructed Cast rewrites, style direction/suggestions/samples/validation,
and covers use credit reservations before paid work. Instructed Cast enqueues
a durable job before rewriting instructions; its reserved job owns the text
rewrite and subsequent image work. Submission reports queued, not an immediately
applied correction. Rejected rewrites still settle recorded text usage.
Cast UI retains the instruction draft and exposes pending/running and durable
failure/rejection observations across navigation; a queued receipt or old visible
image is not new-image success. Failed work requires explicit recovery, not an
automatic paid retry.

Holds have a process owner and a one-hour lease, renewed every 30 seconds;
work checks ownership/expiry before starting. Startup requires the reviewed
lease/settlement SQL migration before
admission. Only expired, never-started holds are automatically reclaimable.
Started-expired holds, legacy unowned holds, and ambiguous settlement require
operator reconciliation, not global startup/reset release. Ledger settlement
may replay its identical idempotent database operation; this is not a retry of
the paid provider request.
Explicit OpenAI image safety refusals remain terminal refusals when the gateway
wraps them in a generic 5xx response, including refusals inside an accepted
stream. They do not retain an ambiguous-outcome hold or trigger route fallback.

Project-lookup connection failures may retry the read once on the shared live
database pool. Request recovery must not close or replace that client: admitted
credit jobs and the reservation-renewal thread retain it across browser requests.

Rejected reruns (including missing style or reservation denial) preserve state
and artifacts. Admitted non-Draw replacements still use stage-owned cleanup:
there is no general rollback on later failure. Draw replacements retain render
revisions and recover the original unfinished action before accepting new input.

Adapt and Plan retain input-keyed paid responses outside stage cleanup. Keys
include model and generation input; reused responses still undergo validation.
Adapt/Plan also keep a typed cumulative work journal under `.checkpoints/<stage>/work`.
Every admitted structured request consumes a slot, including interrupted or
unresolved work; matching checkpoint hits consume none. Source/approved-intent
and stage-authority identities scope the journal across resumes. A model change
or a fresh repair namespace cannot reset it. Adapt defaults to twice its projected
clean call graph (treatment, blueprint, lettering and reviews). Plan defaults to
at least 64 structured requests, or four times its projected map/detail and review
call graph if larger. Plan projects the greater of one page per adapted beat and
the upper advisory page target, leaving room for bounded corrections and explicit
resumes. These are cumulative work allowances, not retry counts or cost
estimates; the existing per-request and global repair-attempt bounds still apply.
An explicit positive
`Config.narrative_max_calls` overrides the ceiling. Changing that configured
limit retains the prior call count. Exhaustion reports `generation_work_limit`
and preserves completed checkpoints; ordinary Resume cannot grant more slots.
The explicit **Start adaptation over** action (`POST /run?stage=adapt&rerun=true`)
archives Adapt and downstream outputs, exports, and Adapt/Plan checkpoints and
work journals under `.checkpoints/restarts/<attempt-id>/`, with the prior state.
It preserves source, approved Brief, selected Style, Cast, and retained editorial
directives. Credits must be reserved before archiving; archive failures restore
moved files. Plan restarts use the same archive boundary for Plan and downstream
work, leaving Adapt active. The Plan rerun estimate includes `archived_page_count`;
submission must supply the matching `confirmed_archive_pages` count. Archived
artwork and exports remain accessible in Pages through authenticated
`GET /restart-archives` and `GET /restart-archives/{archive_id}/file` routes, even
if the old plan is incompatible. Archives never become active pipeline inputs.
The new attempt receives the configured/default work allowance;
past usage and charges remain recorded. `GET /estimate?stage=adapt&rerun=true`
quotes fresh Adapt work without cached-output discounts. This quote covers Adapt
only: Plan is estimated and reserved after the new script passes validation,
then runs automatically. Draw still requires a separate user action.
This counts structured requests, not exact provider submissions or dollars:
JSON repair and transport recovery retain their own existing bounds. Journaling
starts with newly admitted work; historical calls are not retroactively imported.
Reported/estimated costs, unknown outcomes, and subscription funding remain
separate in this journal; it does not debit user credits.

Text streaming preserves provider error events even when HTTP status is 200 or
an error follows syntactically complete JSON. Such responses fail before parsing
or checkpoint publication, with request ID, source scope, finish reason, bounded
provider diagnostics, and stream counters retained. Failed text calls preserve
reported usage; missing usage remains unknown under the default billing policy.
Before the first answer, substantive reasoning deltas count as generation
progress for the 900-second inactivity guard. Role metadata, empty reasoning
fields, and SSE comments do not. The 1,800-second total stream ceiling still
applies, including continuous reasoning. Reasoning never becomes answer text or
completed-answer character counts; a response with reasoning but no answer still
fails. Timing logs identify the event, model, and source scope and count reasoning
events without logging their text. This follows the provider's separate
[reasoning stream fields](https://openrouter.ai/docs/guides/best-practices/reasoning-tokens).
Structured generation can retry a genuinely empty answer once, sharing its
existing JSON-recovery attempt allowance and retaining known prior usage.
Explicit provider errors, refusals, and empty output at the token cap do not
enter that retry path. `retry_invalid_json=False` also disables empty-answer
recovery for callers that own durable raw-response recovery. Image submission
retry policy is unchanged.

Adapt estimates use the lettering prompt and known blueprint content, exclude
matching clean-generation checkpoints, and price a full scoped repair scenario
plus re-review instead of a flat percentage. Unknown outputs and future review
cache hits remain estimates. Adapt/Plan credit confidence is `variable`; quotes
are not guaranteed provider prices. Every API-funded model call now needs an
atomic, job-scoped credit authorization before submission. That authorization
can extend the hold from unreserved balance; concurrent calls keep separate
guarantees. Settlement transfers credits from the hold into immutable debit
rows. A provider charge beyond the held capacity is recorded as unfunded
usage, and the job cannot authorize another call. Ambiguous paid text
submissions retain their hold and are not automatically repeated.

Draw durably saves paid image bytes/provenance in `.pending`, then publishes
the render with an `.unfinished` identity marker. Recovery retains the original
frozen request, parent revision, and usage call IDs through publication/OCR
failures; the unfinished marker clears only after successful operation completion
and, for queued jobs, post-settlement acknowledgement. A visible render alone
does not prove settlement or completion. Resume that original action rather than
redrawing or submitting a different correction.

OCR requests an explicit root schema with `lettering` and `panels` arrays.
Every text observation includes its exact text, comic-lettering/incidental-text
role, and normalized `box`; panel coordinates are directly on each panel
object. This is a blind observation request, never a canonical-copy prompt.

The complete provider response text and finalized usage are durably saved
before JSON parsing or schema validation, separately from versioned raw OCR
observations and derived analysis. A malformed response or persistence failure
does not trigger a hidden paid JSON-repair retry. Saved evidence is replayed
through current parsers/validators provider-free; invalid cached evidence may
still fail and does not authorize replacing it with another paid call.
Missing downstream artifacts alone do not justify new OCR. Proven panel-order
contradictions block; uncertain order remains nonblocking editorial evidence
for visual review, not proof of a defect or of correctness.

### Saved artwork selection

`POST /pages/{page_number}/renders/{revision}/select` chooses retained artwork,
with `expected_revision` guarding concurrent selection changes. The Pages
Versions tab previews all retained renders before an explicit selection.
`TargetArtifacts.active_render_revision()` owns the choice, persisted as typed
`draw/pages/page_NNN/selection.json`; without a choice the newest render is active.
Reading, correction parents, source text locations, editable lettering and Finish
use that same selection. Allocation and recovery still use chronological history.
Newly published artwork becomes active without deleting any earlier version.
Selection rejects stale plans, corrupt/missing artwork and in-flight or unfinished
generation. It invalidates Finish and reopens findings whose resolution is outside
the selected lineage; choosing artwork never establishes visual verification.
Selection makes no provider call and costs no credits.

Current visual correction instructions take priority over disputed parent-image
staging. Motion corrections name leading/trailing ends, screen direction and
contact/release relationships while retaining exact copy, approved identities,
visual anchors, continuity guards and unaffected panels.

### Saved-pixel check recovery

`GET /pages/checks/estimate` returns per-page recovery status, active
`render_image_sha256`, `paid_pages`, and the sum of independently rounded
OCR-only credit quotes/holds. Status is `undrawn`, `stale_render`, `checked`,
`cached_evidence`, or `requires_ocr`; `cached_evidence` indicates available
evidence to validate, not guaranteed successful recovery.

`POST /pages/checks/recover` defaults to `{"allow_paid": false, "renders": {}}`:
revalidate saved evidence, skip pages needing a paid call, and never generate
images. Paid OCR requires explicit `allow_paid: true` plus `renders`, a map
from page number to the approved active image SHA-256. Missing or changed
selections return `selection_changed`; undrawn/stale renders are not repaired
by this endpoint. Each page reports its outcome, so one failure does not
discard successful checks on other pages.

Both bulk recovery and `/pages/{page_number}/analyze` use the shared page
operation lock. Cache replay and active-image lineage checks occur inside it,
before credit reservation: successful cached recovery reserves and spends
nothing, even at zero balance. Only absent reusable OCR evidence, with paid
permission, reaches an OCR-only provider call on the existing image. Saved
bytes must match render lineage. None of these actions redraws, verifies visual
identity, or guarantees provider success; an OCR failure leaves the saved image
available for inspection and recovery.

Stage estimates include page references and each page's automatic read-back and visual review; Cast estimates include state
references. Provider usage and credit settlement remain distinct from estimates
and stage-progress totals. Missing usage is not evidence of zero provider cost.

Sunburst Draw editions submit medium quality at 1024×1536; the quality is fixed
by the edition's profile ID, and retained high-quality editions keep theirs. Page
prices are never read from the frozen edition or request: the retained
`price_per_*` and `estimated_cost_usd` fields are inert identity data. Quotes and
holds come from `litellm_pricing_overrides.yaml` (`estimated_*` consumption
allowances for the request's quality, size, references, and prompt). FAL returns
no token usage, so the gateway reads the request's FAL billing event with an
Admin-scoped `FAL_ADMIN_KEY` and reports it as `fal_billing_event`, along with
the FAL request ID. If that charge is unavailable, a completed Sunburst image
(page, style, cast, or cover) settles at a central estimate of that exact request
(`expected_*` consumption), labelled `request_estimate`. All-zero token usage
is treated as unknown, never as a free image.

The gateway also serves GPT Image 2.5 through Runware (`image-sunburst-runware`,
`image-flare-runware`; `RUNWARE_API_KEY`). The handler uploads references once to Runware media storage and
sends them by UUID, requests PNG output with `moderation: low`, and reports
Runware's per-task charge as `runware_cost` with the task UUID as the request
ID. It submits each task once; a lost answer is recovered with
`getTaskDetails`, and only an unresolved recovery is reported as an unknown
outcome. Runware returns no partial images. Uploaded references and generated
images are served at public, unauthenticated URLs.

Every new Sunburst image uses the `openai-fal` route pair: new Draw editions
through their `openai-fal` profile, and Style/Cast images (samples, references,
covers) through their frozen `openai-fal` wire. Each image goes to
OpenAI first (streamed through the gateway's `image-sunburst-openai` route) and,
if OpenAI fails for availability, to FAL once. A rejection before OpenAI
accepted the request falls back with nothing to absorb. An OpenAI attempt with
an unknown outcome also falls back once; its image can never arrive later, so no
duplicate page is published, and Canary absorbs its possible charge (the job
hold is not retained for it; the render provenance records the absorbed usage
event and its estimated cost). Refusals, invalid requests, cancellation, and
completed output that fails validation stop without trying FAL. A
`moderation_blocked` refusal is a refusal wherever it arrives, including
inside an accepted event stream: it neither falls back nor counts toward the
circuit, and it surfaces as a provider decline. The gateway's OpenAI image
handler sends `moderation: "low"` on every request, the least restrictive tier
OpenAI offers; FAL's Sunburst endpoint has no moderation control. After three
consecutive OpenAI failures a worker sends Sunburst images (pages and
Style/Cast images share one circuit) straight to FAL for 15 minutes. Style/Cast
provenance records the route and any absorbed attempt in `response_metadata`,
and Style/Cast requests frozen for FAL before this change finish on FAL.
Editions bound to the earlier FAL-only profile keep drawing on FAL; the adapter
always follows the edition's or frozen request's profile, never mutable
settings. Render provenance keeps the profile's provider and records the route
that drew the page (`response_metadata.route`, `usage.provider`).

While the Runware grant lasts, the operator switch `CANARY_RUNWARE_FIRST_ENABLED`
makes new Sunburst work use the `runware-openai-fal` identity instead: new Draw
editions bind its profile (`gpt-image-2.5-sunburst-runware-openai-fal-complete-page-medium-hybrid-v1`)
and new Style/Cast wires carry it. Each image goes to Runware first and, only
when Runware definitely did not run it, through the unchanged `openai-fal`
chain above. Definite outcomes are a gateway or Runware connection that was never
made, a failed reference upload, and an explicit Runware task error (402 spent
credits, 401/403, 429/503, 5xx; Runware does not bill failed tasks). The
Runware attempt's call guarantee is released before OpenAI authorizes its own.
An unknown Runware outcome, an invalid request, a 4xx refusal, or a completed
result without a usable image stops and keeps today's hold; the OpenAI
absorbed-attempt exception does not apply to Runware. After three consecutive definite
Runware failures (a spent grant) a worker skips Runware for 15 minutes.
Provenance records `{"from_route": "runware", "reason": ...}` with any OpenAI
fallback under `then`. Pages drawn on Runware have no partial previews.
Turning the switch off changes only new editions and wires: both Sunburst
identities stay spendable, so every existing edition keeps its route.

Text calls have one route switch. With `CANARY_RUNWARE_TEXT_FALLBACK_ENABLED`
set, a Vertex `gemini-4-argon` call that the gateway answers with 429 moves once
to `runware-gemini-4-argon`, the same model with Argon's prompt tuning, on its
first rate limit (`text_route_fallback.py`). A 429 is a definite, unbilled
non-submission. The failed Vertex attempt and the Runware attempt are separate
AI events, each with its own call guarantee, and usage records `runware` as the
provider. The first 429 opens a per-worker circuit, so for five minutes Argon
calls go straight to Runware. Timeouts, 5xx and unknown outcomes never switch,
a call never returns to Vertex, and Runware's own 429s use the normal retry
budget. Checkpoints stay keyed on the stage's configured model, so a stage
whose calls are split across the two routes resumes normally. Labs arms are
pinned to the model they name.

While the switch is on, approving Cast (directly, or when a "Continue" run
passes review) sends each distinct approved reference file Draw may use to the
gateway's Runware route, flagged upload-only (`runware_prefetch.py`). The
gateway stores them in Runware media storage and keeps their UUIDs in its
process-local cache; no image task runs and nothing is billed. It is best
effort: a failure is logged and Draw uploads on demand. The gateway also reads
the Runware account balance at most every five minutes while Runware is in use
(immediately after a 402), reports it as the `runware.balance_usd` gauge, and
logs an error once each time it falls below `RUNWARE_BALANCE_ALERT_USD`
(default 25).

Read-only immediate quotes are distinct from the full-stage rerun estimate:

| GET route | Quoted work |
|---|---|
| `/pages/{page_number}/generate/estimate?depiction=canonical` | One undrawn page and compiled references, without OCR; `less_graphic` is also supported |
| `/pages/{page_number}/analyze/estimate` | Text-check recovery of an existing render: zero for cached evidence, otherwise OCR only; never redraws |
| `/pages/generate/estimate` | Only pages without saved render provenance, including references but not OCR |
| `/pages/checks/estimate` | Per-page readiness and total OCR-only quote for missing checks on saved pages |

These routes validate prerequisites but neither submit jobs, reserve credits,
nor mutate generation artifacts. `estimate_credits` is the projected charge;
`reserved_credits` is the temporary hold, not an extra charge. The remaining-page
quote sums independently rounded per-job estimates and buffered holds; rounding
one aggregate can understate the required credits. `/estimate?stage=draw`
still estimates every planned page for a full-stage rerun, even when some
already have renders. Show estimates as `~N credits`, not guaranteed prices
or completion times.

After a top-up, the insufficient-credits dialog refreshes the balance but
does not replay the action automatically. A retained action requires explicit
Resume once the balance covers its hold; without a retained action, return
to the original control. Do not turn an ambiguous paid submission into an
automatic retry.

Book reads `GET /api/credits/history?project_id={project_id}` so its credit
history uses the same holds, final charges, releases, and unsuccessful-attempt
semantics as the account ledger. Customer credit-history responses omit provider
prices, model identities, token counts, funding routes, and cost-source details.
Provider usage remains internal accounting evidence. Each row carries a
customer-facing `label` derived server-side from its ledger description, Draw
rows and runs carry `page_number`, targeted runs (a regenerated reference, a
style sample) carry `action`, and `spend_by_stage` totals final charges over
the whole scoped history, independent of pagination. A visual review that did
not finish during the draw is re-run with `/pages/{page_number}/visual-review`
and its `/estimate` endpoint. Restart the
gateway after changing its retry configuration.

OpenAI image calls observed by a running stage/job request up to three partial
images. The gateway relays them around the existing authenticated Images route;
its final response, usage and failure phases retain their normal contract.
Transient `image_preview` events carry a bounded WebP preview keyed by the asset
path or part-scoped page number and the usage event ID. Event replay keeps only
the latest preview per target; previews never enter persisted artifacts, stage
progress, generation success, or review evidence. They clear on failure, fallback
and job termination. Style, Cast and Pages crossfade decoded previews with
decreasing blur, show completed provider pixels sharp while validation finishes,
and reveal saved artwork when it loads, respecting reduced motion. Quotes include
the configured allowance of 300 extra image output tokens
for three OpenAI previews. Actual provider usage remains authoritative; FAL's
expected-charge estimate excludes OpenAI previews. Calls without an observer
keep final-only streaming. Loading this gateway middleware requires a gateway
restart; no paid live-preview quality claim follows from provider-free tests.

Observed `image-nano-banana-2.1` calls use Vertex's native GenerateContent stream
with thought images included, retaining the model's default thinking level.
Only image parts marked `thought` become transient drafts; reasoning text is
discarded, and only a non-thought final image may become an artifact. The gateway
consumes the whole stream for terminal usage and refusals, prices the latest
cumulative usage through the configured modality tariff, and never resubmits
after a lost stream. Vertex drafts use the same Style, Cast and Pages preview
effect; they may change composition and are not guaranteed to arrive before the
final image. If none arrive, the normal final result still completes. Vertex
does not use the OpenAI preview-token allowance. Calls without an observer
retain the existing buffered Vertex request.

## Book readiness and package recovery

`GET /export/preflight` reads persisted Finish evidence. Its package readiness
requires a current validator version and saved package files whose resolved
paths remain inside the project, byte sizes match, and SHA-256 digests match.
Missing, unsafe, or damaged packages require a preflight refresh; an old
download URL is not readiness evidence. Package reuse also requires matching
edition, production settings, canonical page, render, lettering, locale, style,
and compositor identities.

Cached export triggers and authenticated PDF/CBZ downloads use the same
verification boundary. The download streams its verified open file descriptor
and closes it on completion/cancellation, with `private, no-store` caching.
Combined exports verify a sidecar binding the selected parts' current Finish
inputs to the output checksum. A stale, orphaned or damaged file requires a
refresh/rebuild. Artifact transactions lock the owning series, including when
the caller addresses a part workspace.

`POST /export/preflight` retries provider-free checks without creating packages,
retaining valid packages when their inputs still match. Explicit export/rebuild
uses `/export/?format=pdf|cbz` (`force=true` for rebuild), reruns Finish, and
packages saved pages without generating artwork or spending credits. Book
distinguishes technical blockers, unresolved review issues, and accepted
editorial decisions, with links back to Pages.

Page checks are automatic and advisory. Missing, stale, invalid or mismatched OCR
evidence does not block Draw approval or export and never proves that saved
artwork needs replacement. Every draw and correction job, in both lettering
modes, reads its page back (retried once; heads for balloon seeds and drawn-in
lettering on editable editions) and runs the visual review against approved
references, both best effort. An unreadable saved OCR answer is kept beside the
next read and is not free cached evidence. Preflight
only reads retained analysis and never repairs or buys OCR; Pages offers a
re-check only after drawing settles. An unproven reading order stays analysis
evidence and is not a page finding. Automatic text findings remain reviewable, are not
preselected for redraw. Existing advisory text findings do not require acceptance
before export; a detected hybrid `unexpected_generated_lettering` issue is an
explicit review concern, handled through normal issue resolution. A missing
check stays unchecked; successful packaging does not verify wording.

Book's persisted package list supports “ready to download” across refreshes;
the edition-ready cue reports package creation, never browser download
completion. Neither successful preflight nor packaging guarantees model
output quality.


## Hybrid page lettering

There are still eight stages. **Lettering** is a Pages-room editing mode, not
Compose. Adapt is semantic/canonical copy authority; Plan supplies placement
reservations; Draw stores immutable full-page base art. Pages owns mutable
presentation and Finish uses deterministic software composition.

`lettering/style.json` stores book-wide role defaults, preset, creative direction,
revision, and hash. `lettering/pages/page_001.json` stores canonical-page hash,
locale variants, source-linked/custom elements, suggested and edited normalized
geometry, tails, transforms, per-element overrides, resolved lines/font sizes,
and the last reviewed base-render identity. Immutable saved revisions live under
`lettering/revisions/`. Presentation never lives beneath `draw/`.

Source-backed elements retain their original identity, kind, allocation, and
reading order. Hiding or editing display copy does not change Adapt. Reset copy
and reset placement are separate. Custom post-production captions, speech,
thought, and SFX elements have no source ID. A changed canonical allocation is
shown as stale, not silently reseeded; an explicit rebuild archives the previous
saved state. Draw regeneration preserves lettering and asks for placement review
against the new pixels. Cast/Adapt/Plan reruns invalidate page presentation but
preserve an existing book style. Upstream Story/Style resets may clear it, and
selecting a different visual direction explicitly seeds that direction's design.
Missing onscreen speech/thought pointers receive provisional page-bounded targets
on insertion; explicit Plan targets, offscreen delivery and saved null targets
remain authoritative. Default pointers are not detected speaker locations.
The v5 engine adds rounded cloud lobes, dashed whispers and burst shouting shapes;
these are presentation variants, not new canonical copy roles.

Authenticated provider-free routes (under `/api/projects/{project_id}`):

- `GET/PUT /pages/{page_number}/lettering`: read/edit with expected lettering
  revision, current artwork SHA, and style SHA. Conflicts return 409 without
  overwriting either version. The server validates source links and recomputes
  typography instead of trusting browser-supplied resolved layout.
- `POST /pages/{page_number}/lettering/reset`: explicitly rebuild from current
  Plan while keeping saved historical revisions.
- `GET/PUT /lettering/style`: inspect/change book defaults, including before Plan
  or Draw exist through Look's book-lettering panel. Inheriting pages reflow;
  full per-element style overrides remain independent. Retained baked editions
  remain non-editable. Editing lettering does not regenerate artwork.
- `GET /lettering/languages` and `POST /lettering/locale`: read stored language
  choices once and select them, including `source`, without model admission,
  pricing or credits. Selection snapshots guard against concurrent edits.
  Same-locale no-ops preserve visual-review evidence.
- `GET /lettering/translation-estimate` and `POST /lettering/translate`:
  explicit, estimated project-wide translation of saved lettering into the
  chosen target language (en/es/fr). The estimate prices the exact prepared
  prompts; the submit enqueues one reserved `lettering_translation` job that
  translates from source display copy and fills only missing target-locale variants across all current pages, preserves
  existing target wording including manual edits, and keeps artwork, geometry,
  reading order, and Adapt canonical copy untouched. Stale snapshots return
  412 before any spend; a job failure never silently republishes partial
  results, and retained raw/validated/prepared evidence permits informed retry.
  Baked editions, stale pages, or undrawn pages reject before spending. The
  project locale persists through seeds/resets/saves; a language change still
  requires visual review on every page before export.
  Per-element `translation_sources` records the exact source copy used for each
  variant. Source edits retain target text but mark it stale until target editing
  or explicit translation confirmation. Stale translations block export/publication;
  translation confirmation never establishes visual placement review. See
  [localization](localization.md) for schema incompatibility and catalog workflow.
- `GET /pages/{page_number}/composite/{full|reader|thumbnail}`: cached finished
  PNG/WebP views. The ordinary render endpoint always serves raw artwork for QA.

Opening a saved page whose locale differs from the project locale is not a paid
operation. The editor presents an unsaved reflow in the project locale, retaining
all saved wording variants, geometry, and the original revision. It does not
publish on read. Save explicitly or translate the project before exporting;
composition rejects a saved locale mismatch. Project translation remains
accessible beside a page-loading error so recovery cannot depend on opening
the failed editor first.

The composite key hashes base-image SHA, lettering state, locale, style, and
the lettering engine version. Relevant mutations and composition snapshots serialize
under a reentrant project filesystem lock, outside directories that invalidation
removes. Preview routes release it during rendering and capture response bytes
under the lock; concurrent derivative invalidation permits one rebuild before
returning a refresh conflict. First
book export seeds all missing lettering before building any normalized pages,
so initializing page two cannot remove page one's newly prepared output.

`lettering/engine.mjs` is imported unchanged by the editor and executed by
backend Playwright. It measures bundled fonts, balances explicit lines, respects
hard breaks, fits only within readable limits, and draws SVG boxes, balloons,
thought puffs, tails and SFX. Finish renders the saved resolved lines; it does not
silently reflow approved copy. No fonts download at runtime and the compositor
makes no network or provider requests. Unsupported scripts, missing language
copy, out-of-page transforms and overflow are visible; unresolved layouts block
composition with a `lettering_layout` repair link, not a paid Draw suggestion.
The bundled fonts do not provide universal language coverage.

The v2 compositor uses one continuous cubic contour for each speech body and
its tail, rather than a separate triangle and painted-over seam. Typesetting
uses the same contour's available width per line and measured glyph baselines;
fitted width, height, explicit lines and per-line ink metrics are persisted.
Tight fitting preserves the editable reservation. Resizing begins at the visible
fitted edge, not at the larger reservation. Layout work is cached per measurer
through movement/tail gestures and invalidated for text, locale, size and style.

New **Literary classic** defaults use serif captions and speech, compact cream
narration boxes and rounded-oval balloons. Other presets remain distinct. Saved
book styles and local overrides are not silently replaced. Reapply a preset to
adopt its new defaults. Older v1 layouts remain readable but require reopening
Lettering and saving their explicit v2 reflow before export; artwork is retained.

Style suggestion schema v6 requires `lettering_preset` inside each `styles` item,
not at the batch root. Parsed schema failures receive a complete-response
correction using the existing two-call curation budget. This budget is shared
with portfolio completion and diversity repair; it is not an additional nested retry loop. Extra
fields remain forbidden, and a root-level preset is never propagated silently
across candidates. Provider-call failures are not caught by this correction path.

The desk offers fit/zoom/pan, direct move/resize/tail handles, keyboard nudging,
reading-order selection, display copy, locale switching and role controls.
A drag is one undo action; save retains undo history. Account/project/page-scoped
local recovery never overwrites the server or applies a stale source/style draft
silently. A failed save retains the draft. Fonts must load before editing;
missing artwork permits saving copy but cannot stamp a placement review.

Gallery/reader/Book use composites for hybrid profiles and original previews for
baked profiles. Book packaging uses the same composite, normalization and archive
path rather than a second renderer. Suggested positions are coarse starting
points, not inferred image geometry or proof of artistic quality; review them.


Correction recovery retains the submitted draft and its change IDs until a job
completes. A failed or cancelled job offers an explicit preview-and-resubmit
flow that reuses those identities; it never retries an ambiguous paid submission
automatically. Authors can withdraw open manual correction requests as dismissed,
with no resolution revision or claim of visual verification.
