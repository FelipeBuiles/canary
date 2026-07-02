# Appearance Timeline — modeling visual change over story time

**Status:** Implemented (2026-06-14) — see "As-built notes" at the end.
**Date:** 2026-06-14
**Author:** Pipeline design pass (canary)

## Problem

In the project `the-girl-without-hands`, the protagonist's **silver hands**
appear in the opening scenes — before her hands are cut off (scene_004) and
six scenes before the silver prostheses are forged (scene_009). The silver
also wrongly persists through the handless stretch (005–008) and the
restoration climax (scene_016), where her real hands grow back.

Root cause, mechanical → fundamental:

1. **False-positive prop matching.** `prompting.py::_prop_matches_context`
   tokenizes the prop name `"Silver Hands"` → `{silver, hands}` and matches on
   *either* token plus a context-cue regex that itself lists `hand|hands|wear`.
   So a panel that says "washing her **hands**" pulls in the Silver Hands prop
   and its reference image, with no occurrence of "silver" anywhere.
2. **Temporal gate unused.** `Prop.first_appearance_scene` (= `scene_009` for
   the silver hands) exists in the model but is referenced nowhere in stage
   logic — only in tests.
3. **Wrong abstraction.** Silver hands are not a carried object; they are a
   **body state** of the character from scene_009 to mid-scene_016. The `Prop`
   concept cannot express "replaces part of a character from scene X to Y."
4. **Right mechanism under-powered.** `Scene.character_appearances` already
   captured the arc correctly (stumps → silver → restored) but is text-only:
   it carries no reference image (so the silver hands have no visual
   consistency) and it does not suppress the canonical character refs (normal
   hands), so the prompt ships "normal-hands image + silver-hands text" — a
   contradiction the model resolves arbitrarily.
5. **Locations share the gap.** `Location.states[]` + `Scene.location_state_id`
   exist and are wired into `prompting.py` per-panel, but there is **one plate
   per location** on disk — no per-state plate — so a "post-collapse" or
   "interior" state has no visual reference, exactly like the silver hands.

The through-line: **appearance is modeled as a single fixed thing per entity,
with temporal variation bolted on as text-only side-channels that the prompt
builder does not authoritatively consume.**

## Goals

- Model an entity's appearance as a **base look + a timeline of transitions**,
  resolved to **panel granularity** (transformations occur mid-scene:
  scene_004 cuts the hands, scene_016 restores them).
- A **visually-significant** state gets its **own generated reference**
  (image), and the prompt uses ONLY the active state's anchor + ref. Minor
  states (e.g. "dusty travel clothes") stay text-only.
- One uniform mechanism across **characters, locations, props, and the world**.
- Make the silver-hands class of bug **structurally impossible**: state
  selection is explicit (position-resolved), never fuzzy text matching.

## Non-goals (deferred)

- **Cause → narration wiring.** `Transition.cause` is stored but unread for
  now; no compose/narration consumer this pass.
- **Multi-facet appearance via event folding.** States are authored as
  self-contained snapshots. If independently-varying facets (hands vs. load
  vs. wear) ever need to compose, transitions are already objects and can be
  promoted to a fold then. Not now.
- **UI timeline editor.** Inspecting/editing the timeline in the four-station
  UI is a likely follow-up, tracked separately.

## Core model — `models/appearance.py` (new)

```python
class StoryPosition(BaseModel):
    """A point in story time."""
    scene_id: str
    beat: int | None = None          # 1-indexed beat within the scene; None = scene start

class Transition(BaseModel):
    """Descriptive annotation of the moment a new state begins.
    NEVER consumed by the resolver — it only labels the boundary for
    narration/inspection (forward-compatible with an event-fold model)."""
    label: str                        # "hands severed"
    depicted_at: StoryPosition | None = None   # where the change is SHOWN (may differ from where it takes effect)
    cause: str | None = None          # stored-but-unread for now

class AppearanceState(BaseModel):
    """One distinct look of an entity. visual_anchor is SELF-CONTAINED and
    fully replaces the entity's base look when this state is active —
    never a delta, never mixed with another state's tags."""
    id: str                           # entity-scoped, e.g. "silver"
    label: str                        # "Silver hands"
    visual_anchor: str                # clean tags describing THIS state in full
    visually_significant: bool = False  # flagged → cast stage generates its own ref

class StateActivation(BaseModel):
    """Binds a state to a point in story time. The active state at a panel is
    the activation with the greatest position <= the panel's position."""
    state_id: str
    at: StoryPosition
    transition: Transition | None = None
```

### Entity wiring

- `Character` gains:
  - `appearance_states: list[AppearanceState] = []` — catalog of alternate looks.
  - `appearance_timeline: list[StateActivation] = []` — ordered transitions.
  - Existing `visual_anchor` remains the **base/default look** (the look before
    the first activation at-or-before a panel).
- `Location` gains the same two fields; its existing `visual_anchor` is the
  base look. **Removes** `Location.states: list[LocationState]` (replaced by
  `appearance_states`).
- `Prop` — silver hands are no longer a prop. Props stay single-look but gain
  real debut gating: replace the unused `first_appearance_scene: str` with
  `appears_from: StoryPosition | None`, **enforced** in resolution.
- `StoryBible` gains optional `world_states: list[AppearanceState] = []` and
  `world_timeline: list[StateActivation] = []` for global drift (season,
  global style shift, time-skip). Empty for stories without world change.

Generated state references (filled by the cast stage, resolved by convention,
not stored on the model):
- Character state refs: `refs/<char_id>/states/<state_id>/{front,three_quarter,gesture}.png`
- Location state plate: `plates/<loc_id>/states/<state_id>.png`

## Resolver — `appearance.py`

```python
@dataclass
class ResolvedAppearance:
    state_id: str | None          # None = base look
    anchor: str                   # self-contained identity/appearance text to use
    ref_dir: Path | None          # state ref dir if flagged+generated, else None (use canonical)

def active_state(
    base_anchor: str,
    states: list[AppearanceState],
    timeline: list[StateActivation],
    position: StoryPosition,
    scene_order: list[str],        # canonical scene ordering, from story_bible.scenes
) -> ResolvedAppearance: ...
```

Rules:
- Position comparison key: `(scene_order.index(scene_id), beat or 0)`.
- Choose the activation with the greatest key `<=` the panel's position. If
  none, return the base look (`state_id=None`, `anchor=base_anchor`).
- A **panel's position** = `(panel.scene_id, max(beat index in panel.beat_ids))`
  — the panel reflects the end-state of the action it covers. `beat_ids` encode
  the scene-relative beat index via `_beat_id(scene_id, i)` (s5_layout_plan.py).
- **Straddle lint:** if a panel's covered beats span an activation position,
  emit a warning (the change should be split across panels). Resolution still
  returns the end-state deterministically.

**Transition timing convention (`at` vs `depicted_at`).** `at` is the first
beat at which the **new** look holds. The *act* of transformation (the axe
falling, the hands regrowing) is depicted in the beat(s) **before** `at`, which
resolve to the **prior** state — so the cutting panel correctly shows hands
being severed, not stumps. `depicted_at` records where the act is shown (for
narration/inspection) and is typically `at`'s immediately preceding beat. Extract
must place `at` at the first post-change beat; the straddle lint catches
mis-authoring where a single panel covers both.

Helper `panel_position(panel, scene_order) -> StoryPosition` lives here so no
stage re-implements the beat-id → ordinal mapping.

## Prompt assembly changes — `prompting.py`

- **Characters** (around `prompting.py:543-567`): replace the
  `scene.character_appearances.get(character_id)` lookup with
  `active_state(...)` per subject.
  - Identity text becomes the resolved `anchor` (self-contained), NOT
    `canonical_anchor + " wardrobe_override: …"`. `_character_identity` is
    simplified accordingly.
  - References: if `ref_dir` is set (flagged state), use the state's pose crops
    and **suppress** the canonical `refs/<char>/…` crops. Otherwise use the
    canonical crops (current behavior) with the resolved anchor as text.
- **Props** (delete `prompting.py:339-432`): remove `_PROP_CONTEXT_CUE_RE`,
  `_story_prop_tokens`, `_prop_matches_context`, and the token-fallback branch
  of `_props_present_in_panel`. A prop is present iff:
  1. its **exact** id or full name appears in the panel's `key_objects` or
     `visual_requirements`, AND
  2. its `appears_from` position (if set) is `<=` the panel position.
  `_filtered_key_objects` stays (still drops unmatched prop labels).
- **Locations** (`prompting.py:569-645`): the per-panel resolution already
  exists; point it at `active_state(location, …)` over the location timeline
  and select the per-state **plate image** (`plates/<loc>/states/<id>.png`)
  when present, falling back to `plates/<loc>.png`.
- **World** (optional): resolve `active_state(world, …)` over the world
  timeline and append its anchor to the panel's global style/setting context
  (where `style`/global tags are assembled). Empty timeline → no-op.
- Bump `IMAGE_PROMPT_VERSION` (currently 18) and note the new contract.

## Cast stage — `s3_cast.py`

After generating the canonical character sheet and location plates, for each
`visually_significant` state:
- **Character state ref:** call `_character_ref_prompt` with the **state's**
  `visual_anchor` in place of the character's, passing the canonical sheet as
  an **image reference** so identity is preserved (same face/hair, changed
  facet). Crop with `_crop_sheet_to_poses` into
  `refs/<char>/states/<state_id>/`. Write a `*.meta.json` recording
  `state_id`, lineage to the canonical sheet sha, and the state anchor.
- **Location state plate:** same pattern with the location plate prompt,
  conditioned on the canonical plate, into `plates/<loc>/states/<state_id>.png`.
- Text-only (unflagged) states generate nothing.

Generation count grows by the number of flagged states only — bounded and
visible in the cast-stage cost estimate.

## Extract — extraction prompt / `s1`

- Author `appearance_states` + `appearance_timeline` for any entity whose
  appearance changes, thinking in **transitions**: for each change, emit
  (new state's self-contained `visual_anchor`, the `at` position where it takes
  effect, and a `Transition` with `label`, optional `depicted_at`, optional
  `cause`). Normalize events → states once, at write time.
- Set `visually_significant: true` for body transformations and structural
  location changes; leave it false for minor wardrobe/dirt notes.
- **Props are detachable carried objects only.** Body modifications, worn-in
  prostheses, and anything that replaces part of a character are character
  states — never props. (This is the rule that prevents "Silver Hands" from
  being re-created as a prop.)

## Forward-only removals (no back-compat shims)

Per the project's forward-only stance:
- `Scene.character_appearances` (replaced by character timeline)
- `Scene.location_state_id` and `PlannedPanel.location_state_id` (replaced by
  location timeline; panel-granular activations cover the override case)
- `LocationState` model (replaced by `AppearanceState`)
- `Prop.first_appearance_scene` (replaced by `Prop.appears_from`)
- `_PROP_CONTEXT_CUE_RE`, `_story_prop_tokens`, `_prop_matches_context`, and the
  fuzzy branch of `_props_present_in_panel`

## Testing

- **Resolver unit tests:** before-first-activation → base; exact-boundary
  inclusivity; monotonic character arc; non-monotonic location (state reused at
  a later position); panel-straddle lint fires.
- **Prompt-assembly tests (regression from this story):**
  - silver hands appear in NO panel before `scene_009`'s activation;
  - stumps/bound-arms appear across 004–008;
  - silver across 009–015;
  - natural hands at the scene_016 restoration beat onward;
  - "washing her hands" (scene_003) does NOT attach the silver-hands ref or any
    prop (fuzzy matcher gone).
- **Cast tests:** a flagged state produces `refs/<char>/states/<id>/front.png`
  and a meta with canonical lineage; an unflagged state produces nothing.

## Worked example — the-girl-without-hands

`char_001` base `visual_anchor` = "long blonde hair, blue eyes, pale skin,
simple peasant dress…" (unchanged).

`appearance_states` (each `visual_anchor` is **self-contained** — the table
abbreviates it as "base + delta," but the stored anchor spells out the full
look so it can replace the base wholesale with no contradiction):
| id | label | visually_significant | anchor (abridged) |
|----|-------|----------------------|-------------------|
| `stumps`   | Maimed | true | base look + "bloodied bandaged stumps where her hands were" |
| `silver`   | Silver hands | true | base look + "polished sterling-silver prosthetic hands strapped to her forearms" |
| `restored` | Restored | true | base look + "natural hands, fully regrown" |

`appearance_timeline`:
| at | state_id | transition.label | transition.cause (stored, unread) |
|----|----------|------------------|-----------------------------------|
| scene_004 · beat K | `stumps`   | "hands severed"   | "her father's axe, at the Devil's command" |
| scene_009 · beat 2 | `silver`   | "silver hands forged" | "the King's gift" |
| scene_016 · beat M | `restored` | "hands miraculously restored" | "divine grace" |

The "Silver Hands" **prop is deleted**. Locations gain timelines where they
change (e.g. the moat drying within scene_006; the wealth filling the mill in
scene_002), each with a flagged state + generated plate where the change is
visually significant.

Existing projects re-extract → re-cast → re-direct → re-draw to adopt the
model; the success criterion is that the girl shows real hands through
scene_003, stumps through 005–008, silver from 009, and real hands again at the
scene_016 restoration.

## Touched files (summary)

- `models/appearance.py` — new model + resolver home (or split resolver into
  `appearance.py` and keep models in `models/appearance.py`).
- `models/story_bible.py` — entity wiring; remove `LocationState`,
  `Scene.character_appearances`, `Scene.location_state_id`,
  `Prop.first_appearance_scene`.
- `models/layout_plan.py` — remove `PlannedPanel.location_state_id`.
- `prompting.py` — resolver integration; delete fuzzy prop matcher.
- `stages/s3_cast.py` — per-state ref/plate generation.
- `stages/s1_*` (extraction prompt) — author timelines; props rule.
- `stages/s5_layout_plan.py` — `_key_objects_for_panel` prop substring match
  reviewed against the new exact-match contract.
- `artifacts.py` — path helpers for state refs/plates.
- Tests across resolver, prompting, cast.

## As-built notes (deltas from the design)

Implemented across `models/appearance.py` (new), `appearance.py` (new resolver),
`models/story_bible.py`, `models/panel.py`, `models/layout_plan.py`,
`prompting.py`, `stages/s3_cast.py`, `stages/s4_screenplay.py`,
`stages/s5_layout_plan.py`, and the `extraction.txt` / `screenplay.txt` prompts.
460 tests pass (`uv run pytest`); `src/` is ruff-clean.

Where the build diverged from the design above:

- **Locations: full unification (per request).** Both characters and locations
  now use `appearance_states` + `appearance_timeline` resolved by the one
  `active_state` resolver. The input-side `location_state_id` tagging was
  removed (`Scene`, `PlannedPanel`/`LLMPanelSpec`, `ScreenplayBeat`, and the
  s4/s5 propagation + screenplay-prompt beat tagging). The **computed**
  `ImagePrompt.location_state_id` is kept — the draw stage (`_plate_ref_path`)
  still selects `plates/<state_id>.png` from it. `LocationState` was deleted.
- **Prop debut field unchanged.** Kept `Prop.first_appearance_scene: str`
  (scene-level) rather than introducing `Prop.appears_from: StoryPosition`; it
  is now *enforced* as a debut gate in `_props_present_in_panel`.
- **Prop matcher cleaned, not deleted.** Rather than pure exact-match (which
  lost legitimate recall — "armful of wildflowers" → Bundle of Flowers), the
  token+context-cue matcher was retained but the body-part words
  (`hand|hands|feet`) were removed from the cue regex. That single change is
  what makes "washing her hands" stop matching a hands-named prop; combined
  with "body changes are character states, not props," the leak is closed.
- **Authoring granularity is scene-level for now; resolver is beat-capable.**
  Beat ordinals are created in the screenplay stage (s4), after extraction, so
  extraction authors activations at scene granularity (`at.beat` usually null).
  The resolver and `StoryPosition` fully support beat-level positions (and the
  tests exercise mid-scene resolution). **Deferred:** an s4 pass that pins the
  exact beat of a within-scene transformation (e.g. the hand-cutting in
  scene_004) so the depicting panel can show the act in the prior state.
- **`Transition.cause` is stored but unread** (as designed); no narration wiring.
- **World timeline deferred.** `StoryBible.world_states`/`world_timeline` were
  not added — no world-level change exists in the target story (YAGNI). The
  same model + resolver extend to it when needed.

### Verifying on the target project

The live `the-girl-without-hands` artifacts still carry the old shape (silver
hands as a prop, `character_appearances`). Adopting the fix requires re-running
extract → cast → direct (→ draw) so the timeline is authored and per-state refs
generated. That hits external image models and costs credits, so it is left as
a deliberate, separately-triggered step.
