# Slice 01 — Rerender Safety and Derived-State Ownership

## Fresh-session assignment

Implement only this slice. Read `AGENTS.md`, the sibling `README.md`, this file,
and verify Slice 00's route tests pass. Do not begin Slice 02.

## Goal

Make it impossible for a manual or instructed edit to retain a stale visual
brief or layout. All rerender paths must persist authoritative structured fields
plus derived fields that are either fresh or absent.

## Current problem

- `panel_store.save_prompt()` rebuilds `full_prompt` and `distilled_prompt` but
  preserves client-supplied `visual_brief` and `layout`.
- final generation prefers `visual_brief`, so a corrected draft can regenerate
  the old scene;
- instructed edits clear the visual brief but not layout;
- the current PUT API sends a full `ImagePrompt`, obscuring which fields the
  user actually changed;
- a direct edit to `full_prompt` is overwritten by server rerendering and is not
  an authoritative generation input.

## Required reading

- `novel_to_comic/src/novel_to_comic/panel_store.py`
- `novel_to_comic/src/novel_to_comic/prompt_assembly.py`
- `novel_to_comic/src/novel_to_comic/prompt_instructions.py`
- `novel_to_comic/src/novel_to_comic/server/routers/stages.py`
- `novel_to_comic/src/novel_to_comic/stages/s7_draw.py`
- `web/src/components/PanelDetailModal.tsx`
- `web/src/components/PromptLineageCard.tsx`
- `web/src/api/queries.ts`
- `novel_to_comic/tests/test_panel_store.py`
- `novel_to_comic/tests/test_prompt_instructions.py`

## Deliverables

1. Define the authoritative editable field set. It includes scene direction,
   subject action/expression/position, user constraint addenda, and intentional
   manual layout edits. It excludes anchors, reference paths, system
   constraints, visual briefs, distilled prompts, and rendered prompt strings.
2. Change prompt editing to an explicit patch contract so the server knows which
   fields changed. Do not trust an entire client-supplied `ImagePrompt` as
   authoritative state.
3. Centralize derived-field invalidation:
   - semantic prompt change -> clear `visual_brief` and `layout`;
   - manual layout-only change -> preserve the supplied layout and mark it as
     manual if provenance is added;
   - any accepted instructed semantic change -> clear layout as well as both
     prompt bodies.
4. Rebuild `full_prompt` and deterministic distilled prompt server-side.
5. Remove or make read-only any UI control that claims raw `full_prompt` editing
   is authoritative.
6. Ensure initial draw and Quick Re-Do hydrate missing visual brief/layout using
   the same existing path. Do not redesign the visual-brief content yet.

## Tests first

- Manual composition edit clears old visual brief and layout.
- Subject-position edit clears old layout.
- Manual layout-only edit survives.
- Instructed edit clears old layout.
- Client attempts to set `visual_brief`, anchors, reference data, or system
  constraints are ignored or rejected.
- Saved structured edit appears in the provider-bound body after hydration.
- Plain rerender without an edit keeps fresh derived fields.

Add a focused cross-path test, such as `test_prompt_rerender_parity.py`, rather
than relying only on unit tests of rendering helpers.

## Exit criteria

- Persisted prompts never contain stale derived state after an edit.
- The UI no longer presents ineffective raw-prompt editing as authoritative.
- Manual and instructed edits reach the same hydration path.
- Focused tests, full backend tests, Ruff, affected frontend tests, lint, and
  build pass.

## Handoff to Slice 02

Write `handoffs/01.md` using the durable handoff template before replying.

Document the patch schema, authoritative field set, and invalidation helper.
Slice 02 will build protected anchors and constraints around this ownership
model.
