# Story station — implemented surface

This scoped brief records the Story station as implemented on 2026-09-09.
The existing **Living Ink** world in `DESIGN.md` and product commitments in
`PRODUCT.md` remain the authority; this surface does not introduce a new
global visual system.

## Task and hierarchy

The task combines **operate** and **read**: review the extracted manuscript,
shape the adaptation brief, save changes, and approve the brief to continue
to visual direction. The page leads with a dark manuscript hero: title,
author, and scene/character/place counts. The count line is a jump link to
the extracted-source explorer below the brief.

Editorial cards show readable paragraphs or lists first. Story promises are
featured alongside tone and target length. Themes, desired emphasis,
essential events, and character turns stay visible. “More editorial details”
starts collapsed and contains point of view, narrator treatment, motifs,
protected language, and ambiguities.

## Interaction and recovery

- Each editorial card has an explicit **Edit** / **Done editing** toggle.
  Edit focuses its textarea. Done editing returns to the reading view and
  retains the draft; it does not save. Escape also retains the draft, closes
  editing, and returns focus to the toggle. Array fields use one item per line.
- Target length uses always-visible minimum and maximum page fields. The
  minimum must be at least one; the maximum cannot be below the minimum.
- **Save brief** and save status sit above the fields. The standing approval
  action saves a dirty visible draft before approval and states that behavior
  in its label and note.
- Existing save, conflict detection, and local draft recovery remain in
  place. Conflicts preserve the draft and require reviewing the latest
  revision before saving. Earlier drafts can be inspected or copied;
  discarding one requires confirmation. Storage and save errors remain visible.
- The source explorer is read-only, with **Scenes**, **Characters**, and
  **Places** views and counts. Scenes show summaries, chapters, and available
  cast/place names. Character and place entries show their visual anchors.

## Layout and implementation

The surface uses the existing display/body/meta typography, paper cards,
ink background, red accents, gold manuscript metadata, and mechanical
shadows. Brief sections use the shared `EntityCard`; source navigation uses
`RoomTabs`.

The main brief becomes an asymmetric two-column arrangement at extra-large
widths. Supporting editorial cards become two columns at large widths;
character/place entries become two columns at medium widths. Narrow layouts
stack these sections; page-range fields remain paired. Hero text and action
rows wrap, and scene number gutters become narrower on small screens.

Implementation references:

- `web/src/pages/rooms/StoryRoom.tsx`
- `web/src/components/composites/BriefSection.tsx`
- `web/src/components/composites/StoryExplorer.tsx`

## Validation scope

The implementation run reported **333 frontend tests passing**, a passing
production build, and passing lint. Visual inspection used an isolated
component capture without the authenticated application shell. This records
the scope of verification, not a claim that the authenticated end-to-end
flow or every viewport was visually verified.

After concurrent edits to the shared `StagePlaceholder` failure presentation,
the final focused rerun had 13 passing tests and four failures asserting its
previous error labels/text. Story editing and save assertions still passed;
those unrelated production edits and assertions were left untouched.
