# Panel Continuity System Design

**Date:** 2026-04-20
**Status:** Approved

## Overview

Each panel is currently generated independently without explicit knowledge of what characters were doing in the previous panel. This causes continuity breaks — a character can be "lying in a hospital bed" in panel 1, a close-up face in panel 2 (model reinvents them standing), and back in bed in panel 3.

The solution is a two-stage continuity chain: Stage 5 builds a narrative continuity note from the previous panel's breakdown, and Stage 6 fixes the scene anchor mechanism to chain to the immediately previous panel instead of the first successful one.

---

## Problem Statement

| Issue | Current Behavior |
|-------|-----------------|
| **No temporal context** | Each panel's prompt has no reference to what happened in the previous panel |
| **Scene anchor is wrong** | `scene_anchors[scene_id]` = first successful panel, never updated — so later panels lose connection to the immediately prior panel |
| **transition_note unused** | Defined in `PanelBreakdown` but never reaches the prompt |
| **Action chaining broken** | Panel 1: "Sara draws sword", Panel 2: model invents new action instead of continuing from draw |

---

## Solution: Two-Stage Continuity

### Stage 5 — Build Continuity Note

**File:** `novel_to_comic/src/novel_to_comic/prompting.py`

Add `continuity_note` field to `ImagePrompt` and build it in `build_image_prompt_spec()`.

**New field on ImagePrompt** (`models/prompt.py`):
```python
continuity_note: str | None = None  # Narrative chain from previous panel
```

**New utility function** (`prompting.py`):
```python
def build_continuity_note(
    current_panel: PanelBreakdown,
    prev_panel: PanelBreakdown | None,
) -> str | None:
    """Build narrative chain from previous panel's state.

    Returns a string like:
    "CONTINUING FROM: Sara stands at the hospital door, hand on the frame,
    expression worried. Marcus lies in the hospital bed, eyes closed, IV drip nearby.
    TRANSITION: fade. Now: Close-up on Sara's face, tears in her eyes."
    """
    if not prev_panel:
        return None

    # Build previous state description for each character
    prev_state_parts = []
    for char_id in prev_panel.characters_present:
        action = prev_panel.character_actions.get(char_id, "")
        expression = prev_panel.character_expressions.get(char_id, "")
        position = prev_panel.character_positions.get(char_id, "")
        parts = [p for p in [action, expression, position] if p]
        if parts:
            char_name = char_id  # fallback to ID if name lookup fails
            prev_state_parts.append(f"{char_name}: {', '.join(parts)}")

    prev_state_str = "; ".join(prev_state_parts) if prev_state_parts else "scene continues"

    # Build current action description
    curr_action_parts = []
    for char_id in current_panel.characters_present:
        action = current_panel.character_actions.get(char_id, "")
        expression = current_panel.character_expressions.get(char_id, "")
        parts = [p for p in [action, expression] if p]
        if parts:
            curr_action_parts.append(f"{char_id}: {', '.join(parts)}")

    curr_str = "; ".join(curr_action_parts) if curr_action_parts else "scene continues"

    # Assemble
    parts = [f"CONTINUING FROM: {prev_state_str}."]
    if prev_panel.transition_note:
        parts.append(f"TRANSITION: {prev_panel.transition_note}.")
    parts.append(f"Now: {curr_str}.")
    return " ".join(parts)
```

**Integration in `build_image_prompt_spec()`:**

```python
def build_image_prompt_spec(
    config: Config,
    project_dir: Path,
    panel: PanelBreakdown,
    story_bible: StoryBible,
    prev_panel: PanelBreakdown | None = None,  # NEW param
) -> ImagePrompt:
    # ... existing code ...

    continuity_note = build_continuity_note(panel, prev_panel)

    prompt = ImagePrompt(
        # ... existing fields ...
        continuity_note=continuity_note,
    )
    return prompt
```

**Integration in `s5_prompts.py`:** When processing panels, load the previous panel's breakdown and pass it to `build_image_prompt_spec()`.

**Prompt rendering** (`render_generation_prompt()`):
```python
def render_generation_prompt(prompt: ImagePrompt, style_template: str) -> str:
    style = _clean(style_template or getattr(prompt, "style", None))

    body = _clean(getattr(prompt, "full_prompt", "")) or render_panel_prompt_body(prompt)

    if style:
        output = f"{style}\n\n{body}"
    else:
        output = body

    # Append continuity note if present
    if getattr(prompt, "continuity_note", None):
        output = f"{output}\n\n{prompt.continuity_note}"

    return output
```

---

### Stage 6 — Conditional Scene Anchor + Continuity

**File:** `novel_to_comic/src/novel_to_comic/stages/s6_generate.py`

**Scene anchor chaining (fix as described above):**
```python
# Scene anchor is updated after EACH success to point to immediately previous panel
if result:
    scene_anchors[prompt.scene_id] = output_path
```

**Conditional image reference based on transition:**

The previous panel image should only be used as a style reference when the transition is **smooth/semantic**. Hard cuts (smash cut, fade to black/white, scene change) can make the previous panel image actively harmful — the model might blend the previous scene into the new one.

```python
def _should_use_prev_panel_image(prev_panel: PanelBreakdown | None) -> bool:
    """Return True if the previous panel's image should be used as a style reference."""
    if not prev_panel:
        return False
    transition = prev_panel.transition_note.lower() if prev_panel.transition_note else ""
    hard_cuts = ["smash cut", "fade to", "cut to", "scene change", "time jump"]
    return not any(hard in transition for hard in hard_cuts)
```

When generating a panel, check `transition_note` from the **previous** panel:
- **Smooth transitions** (no note, temporal continuity like "seconds later", "then") → use previous panel image as style_ref
- **Hard cuts** (smash cut, fade, cut to, time jump) → skip previous panel image, only use style sample

This decision is made at generation time using the previous panel's breakdown (already on disk). The continuity note text is always included regardless of transition type — it describes what happened, not visual reference.

---

## Retroactive Benefit

Any regeneration of an existing panel will:
1. Rebuild its prompt from the current `PanelBreakdown`
2. Pick up the previous panel's breakdown (from disk)
3. Generate a fresh `continuity_note`
4. Include it in the regenerated prompt

No data migration needed.

---

## Scope Boundaries

- **In scope:** Intra-scene continuity only (panel N → panel N+1 within the same `scene_id`). Cross-scene continuity not desired — scenes can have location/time breaks. Conditional image reference based on transition type.
- **Out of scope:** Cross-scene continuity, camera movement descriptions between panels, dialogue continuity (dialogue is already in the prompt). User-configurable transition behavior (transition list is hardcoded for now).

---

## Implementation Order

1. Add `continuity_note` to `ImagePrompt` model (`models/prompt.py`)
2. Implement `build_continuity_note()` in `prompting.py`
3. Update `build_image_prompt_spec()` to accept `prev_panel` and build continuity note
4. Update `s5_prompts.py` to pass previous panel when building prompts
5. Update `render_generation_prompt()` to append continuity note
6. Implement `_should_use_prev_panel_image()` in `s6_generate.py`
7. Update scene anchor logic to chain and use conditional previous panel image
8. Test with a multi-panel scene, verify continuity note appears and hard cuts skip image reference
