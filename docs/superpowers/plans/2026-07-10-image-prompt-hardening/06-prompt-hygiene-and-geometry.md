# Slice 06 — Prompt Hygiene, Budgets, and Geometry Truth

## Fresh-session assignment

Implement only this slice. Read `AGENTS.md`, the sibling `README.md`, this file,
and verify Slice 05's compiler and protected-section tests. Do not begin Slice
07.

## Goal

Make compiled requests compact, non-duplicative, text-safe, budget-aware, and
truthful about requested geometry and supported generation controls without
changing reference selection or authority.

## Current problem

- narration/caption-space, continuity, no-lettering, subject locks, and scene
  facts can be repeated across several prompt lanes;
- `visual_requirements` can duplicate actions, expressions, positions, props,
  and key objects;
- text sanitation covers only some fields;
- long prompts are shortened by provider-side prefix slicing, which can discard
  critical tail constraints;
- location prompts can inject unconditional gouache/material wording;
- style proofs and location plates can request dimensions that contradict their
  promised composition;
- UI/config controls can imply provider parameters that are not actually sent.

## Required reading

- Slice 05 compiler and handoff
- Slice 00/04 `ImageModelProfile`
- `novel_to_comic/src/novel_to_comic/prompting.py`
- `novel_to_comic/src/novel_to_comic/prompt_assembly.py`
- `novel_to_comic/src/novel_to_comic/stages/s2_style.py`
- `novel_to_comic/src/novel_to_comic/stages/s3_cast.py`
- `novel_to_comic/src/novel_to_comic/panel_aspect.py`
- provider request code only to characterize verified limits/controls
- prompt, aspect, style, cast, and config tests

## Deliverables

1. Give each fact one owner: anchors, scene direction, narration-space
   composition, continuity, generated constraints, reference instructions, and
   user addenda each render once.
2. Normalize and semantically deduplicate `visual_requirements` against subject
   action/expression/position, key objects, props, and setting delta. Enforce the
   planner's intended 1–4 must-show details rather than retaining a long clause
   list.
3. Apply text-render sanitation to all editable/dynamic scene fields: actions,
   expressions, positions, setting delta, key objects, props, requirements,
   lighting, mood, composition, continuity, and user addenda. Preserve physical
   descriptions of text-bearing objects while removing requested readable
   content intended for Stage 9.
4. Never sanitize protected anchors. If an anchor itself conflicts with the
   no-lettering policy, emit a structured upstream-correction diagnostic while
   preserving the anchor verbatim and retaining the generated no-lettering
   constraint.
5. Remove hardcoded medium conflicts such as unconditional gouache wording.
   Material guidance must derive from the active selected style and appear once.
6. Extend `ImageModelProfile` with verified prompt-character limits, native
   aspect modes/values, and supported controls such as quality, steps, negative
   prompt, and guidance. Reference limits remain owned by Slice 04.
7. Add section-aware budgeting. Protected anchors, active-state locks, reference
   instructions, and system constraints are non-truncatable. Compress or omit
   lower-priority scene prose first. Reject a request that cannot fit protected
   material; no provider may prefix-slice it later.
8. Keep all dimension math in `panel_aspect.py`. Record requested aspect,
   generation shape, and effective target pixel dimensions in the pre-transport
   request. Actual returned image dimensions belong only in result provenance.
9. Make style proof requests use a portrait 4:5 shape when the prompt promises
   4:5, and location plates use a verified landscape shape when they promise a
   wide plate. Retain canonical panel shape logic.
10. Represent native aspect and control intentions structurally. Keep a short
    prose aspect cue during rollout only when it is emitted by the canonical
    compiler and therefore visible in the request—not added later by a handler.
11. Remove/hide phantom controls that the selected route does not support.

## Tests first

- Narration-space, continuity, and each invariant appear exactly once.
- Adversarial readable-text cues in every dynamic field are removed or converted
  to a physical text-free description.
- Protected anchor remains byte-exact even when it triggers a text-conflict
  diagnostic.
- Must-show list is capped and non-redundant.
- Long requests preserve all protected sections within each route budget;
  impossible requests fail explicitly.
- A non-gouache style receives no gouache direction.
- Style proof and location prompt geometry matches effective target dimensions.
- 3:2 versus 16:9 is validated numerically, not merely as “landscape.”
- Unsupported controls are rejected or omitted by the model profile.
- Diagnostic-only changes do not affect provider-impacting compiled fields.

## Exit criteria

- Compiled prompts are compact, internally consistent, and text-safe.
- Protected content can never be lost to a provider character cap.
- Prompt geometry, effective dimensions, and supported controls agree.
- Reference selection/order is unchanged from Slice 04.
- Focused tests, full backend tests, and Ruff pass.

## Handoff to Slice 07

Write `handoffs/06.md` using the durable handoff template before replying.

Report prompt-section priority/budget rules, text diagnostics, model capability
fields, native-aspect mapping, effective-dimension contract, and supported
control matrix. Slice 07 must serialize these exact compiled values without
adding or trimming prose.
