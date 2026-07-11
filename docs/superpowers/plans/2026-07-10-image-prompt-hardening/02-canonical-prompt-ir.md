# Slice 02 — Canonical Prompt IR and Protected Verbatim Anchors

## Fresh-session assignment

Implement only this slice. Read `AGENTS.md`, the sibling `README.md`, this file,
and verify Slice 01's edit-invalidation tests. Do not begin Slice 03.

## Goal

Create a canonical prompt intermediate representation in which immutable visual
anchors, editable scene direction, and generated system constraints have
separate owners. This slice produces provider-independent canonical sections;
Slice 05 will combine them with a finalized reference plan into the exact
provider-bound request.

## Current problem

- active character-state anchors, location anchors, and prop anchors are
  shortened or filtered;
- the preferred LLM visual brief rewrites identity and setting facts;
- validation checks formatting, not anchor retention;
- system invariants live in a single editable semicolon string;
- continuity and caption constraints can be duplicated during rendering.

## Required reading

- `novel_to_comic/src/novel_to_comic/models/prompt.py`
- `novel_to_comic/src/novel_to_comic/models/story_bible.py`
- `novel_to_comic/src/novel_to_comic/prompting.py`
- `novel_to_comic/src/novel_to_comic/prompt_assembly.py`
- `novel_to_comic/src/novel_to_comic/prompt_instructions.py`
- `novel_to_comic/tests/test_prompting.py`
- `novel_to_comic/tests/test_visual_brief.py`
- `novel_to_comic/tests/test_prompt_assembly.py`

## Deliverables

1. Add a protected anchor model, for example:

   ```python
   class PromptAnchor(BaseModel):
       kind: Literal["character", "location", "prop"]
       entity_id: str
       name: str
       appearance_state_id: str | None = None
       text: str
   ```

2. Resolve exactly one self-contained appearance anchor per active entity: the
   base `visual_anchor` when no state is active, otherwise the active state's
   `visual_anchor`. Never concatenate base and state anchors, and never inject
   base `default_outfit` beside an active state. Do not pass the resolved anchor
   through `shorten`, token filters, underscore replacement, translation, or an
   LLM.
3. Store the active character state id on each `PromptSubject` and the active
   location id/state id on `ImagePrompt`.
4. Split constraints into:
   - generated system constraints: count, one-body, single instant,
     no-lettering, crop policy, appearance locks, unified canvas;
   - editable user constraint addenda.
   System constraints cannot be replaced by manual or instructed edits.
5. Narrow the LLM visual-brief input to scene direction: framing, action,
   expression, position, panel-specific setting delta, lighting, mood, spatial
   relationships, and caption-space composition. Exclude protected anchors,
   reference instructions, and generated constraints.
6. Render a deterministic canonical prompt-body projection from the owned
   sections. A small new `generation_prompt.py` module is preferred over further
   growth in `prompting.py`. Do not call this projection the final
   provider-bound prompt: it does not yet contain the finalized reference
   selection or role instructions.
7. Bump `IMAGE_PROMPT_VERSION`; breaking stored prompt JSON is acceptable.

## Tests first

- Use sentinel anchors longer than the old 120/180/220-character limits.
- Assert each sentinel is an exact substring of the canonical rendered
  projection.
- Cover base character, minor state, significant state, restored state,
  location state, and prop.
- Mock an LLM brief that omits or contradicts an anchor; the canonical rendered
  projection must still contain the protected anchor unchanged.
- Assert system constraints cannot be removed through either edit path.
- Assert the LLM brief source contains no anchor text or system constraints.

## Exit criteria

- Anchors are byte-for-byte preserved in canonical serialization and rendering.
- The LLM owns only scene direction.
- System constraints are typed, generated, and non-editable.
- Existing style injection remains generation-time behavior.
- Focused tests, full backend tests, and Ruff pass.

## Handoff to Slice 03

Write `handoffs/02.md` using the durable handoff template before replying.

Report the new IR fields, canonical renderer entry point, prompt version, and
exact list of source fields. Slice 03 will fingerprint those sources and
preserve user overlays across canonical rebuilds. The final request compiler is
deliberately deferred to Slice 05.
