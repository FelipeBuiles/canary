# Slice 03 — Prompt Source Lineage and Freshness

## Fresh-session assignment

Implement only this slice. Read `AGENTS.md`, the sibling `README.md`, this file,
and verify Slice 02's verbatim-anchor contract. Do not begin Slice 04.

## Goal

Replace ID/version-only prompt freshness with deterministic source lineage.
Upstream visual changes must rebuild the canonical prompt while preserving
valid user-authored scene-direction overlays.

## Current problem

`prompt_is_current()` currently checks only `planned_panel_id` and prompt
version. Changes to panel action, Story Bible anchors, appearance timelines,
location, props, continuity inputs, or language can leave a stale prompt
indefinitely. Reference availability has a parallel freshness problem owned by
Slice 04's `ReferencePlan`. Returning current prompts unchanged was also used to
preserve user edits, so naive rebuilding would destroy corrections.

## Required reading

- `novel_to_comic/src/novel_to_comic/prompt_assembly.py`
- `novel_to_comic/src/novel_to_comic/panel_store.py`
- `novel_to_comic/src/novel_to_comic/models/prompt.py`
- `novel_to_comic/src/novel_to_comic/layout_planning.py`
- `novel_to_comic/src/novel_to_comic/stages/s6_storyboard.py`
- `novel_to_comic/src/novel_to_comic/stages/s7_draw.py`
- `novel_to_comic/tests/test_pipeline_fixes.py`

## Deliverables

1. Define a canonical, sorted source projection and `source_sha256` for each
   panel prompt. Include:
   - the complete relevant `PlannedPanel` visual fields;
   - prior-panel continuity inputs when applicable;
   - referenced character records and appearance timelines;
   - active location record and timeline;
   - matched prop records;
   - canonical prompt schema/version and target language;
   - prompt-affecting configuration such as continuity mode.
2. Exclude data injected exclusively at generation time, notably active style
   text, if changing it should not rebuild stored panel structure.
3. Store user corrections as an explicit overlay separate from canonical IR.
   Rebuilding means: compile canonical source -> reapply valid overlay ->
   invalidate derived brief/layout -> persist new lineage.
4. Key subject/location-sensitive overlay operations to entity id and the
   appearance/location state in which they were authored. Revalidate them on
   rebuild. Drop with a structured warning when the entity disappears or the
   active state makes the correction incompatible; never apply an operation to
   a different subject index or state.
5. Make direct, draw preflight, and single-panel rerender use the same freshness
   function.
6. Do not include reference file hashes yet; Slice 04 owns selected-reference
   materialization and cache fingerprints.

## Tests first

- Unchanged sources return the stored prompt without new LLM/layout calls.
- Panel action, character anchor, timeline activation, location anchor,
  matched prop, language, continuity mode, and prior transition changes each
  change `source_sha256` and rebuild.
- Style-only change does or does not rebuild according to the explicit contract.
- User composition/action overlay survives a compatible rebuild.
- Overlay targeting a removed character is reported and not misapplied.
- A “uses both hands” overlay is dropped when the character enters a no-hands
  state; a state-neutral framing overlay survives.
- A location-material correction is revalidated when a damage/weather state
  activates.
- Newly available state references do not affect prompt lineage here; that is a
  `ReferencePlan` concern in Slice 04.

## Exit criteria

- Prompt currency is content-based rather than ID-based.
- User corrections are preserved as overlays, not by suppressing canonical
  rebuilds.
- All build/rerender entry points share the same decision.
- Focused freshness tests, full backend tests, and Ruff pass.

## Handoff to Slice 04

Write `handoffs/03.md` using the durable handoff template before replying.

Report the exact source projection, state-aware overlay storage shape, warning
codes, and rebuild API. Slice 04 will use the active state identities while
selecting compatible references.
