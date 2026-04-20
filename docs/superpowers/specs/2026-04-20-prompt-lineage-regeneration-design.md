# Prompt Lineage + Panel Regeneration Modal Design

**Date:** 2026-04-20
**Status:** Approved

## Overview

Two related UX improvements for displaying and editing generated prompts:

1. **PromptLineageCard** — a reusable component that surfaces prompt construction lineage with collapsible sections, inline editing, and an "advanced" toggle for granular detail
2. **PanelDetailModal** — a modal for DrawRoom that allows full prompt inspection, editing, and regeneration

Both features share the same underlying component (`PromptLineageCard`) but differ in mode and available actions.

---

## Component 1: PromptLineageCard

### Purpose

Display an `ImagePrompt` with its constituent parts visible and editable. Used anywhere prompts are shown as text.

### Props

```typescript
interface PromptLineageCardProps {
  prompt: ImagePrompt;
  onSave?: (patch: Partial<ImagePrompt>) => void;
  mode?: "review" | "edit";
  defaultExpanded?: boolean;
}
```

- `mode="review"` — sections collapsed by default, no "advanced" section
- `mode="edit"` — sections expanded, all fields editable, "advanced" shown

### Lineage Sections

Each section is collapsible. Sections (in order):

| Section | Collapsed View | Expanded View | Editable |
|---------|---------------|---------------|----------|
| **Style** | Style name only (e.g., `"noir comic style"`) | Full style template string | Yes, via EditableText |
| **Subjects** | `"SARA, MARCUS"` | Each subject with identity, action, expression, position | Yes, per-subject fields |
| **Composition** | Full composition string | Full composition string | Yes |
| **Setting** | Full setting string | Full setting string | Yes |
| **Lighting** | Full lighting string | Full lighting string | Yes |
| **Mood** | Full mood string | Full mood string | Yes |
| **Assembled Prompt** | Full `full_prompt` (read-only in review mode) | Full `full_prompt` | Yes in edit mode |

### "Advanced" Toggle

When `mode="review"`, an "Advanced" toggle button reveals:
- Individual subject details (identity, action, expression, position per character)
- `props` array
- `constraints` string

When `mode="edit"`, all of the above is always visible.

### Visual Structure

```
┌─ STYLE ──────────────────────────────────┐
│ ▶ noir comic style                       │
└──────────────────────────────────────────┘
┌─ SUBJECTS ───────────────────────────────┐
│ ▶ SARA, MARCUS                          │
└──────────────────────────────────────────┘
┌─ COMPOSITION ────────────────────────────┐
│ wide shot, centered frame               │
└──────────────────────────────────────────┘
...
┌─ ASSEMBLED PROMPT ───────────────────────┐
│ noir comic style, wide shot...          │
└──────────────────────────────────────────┘
```

### Interactions

- Click section header → expand/collapse
- Click text in edit mode → inline edit via EditableText
- Blur or Enter → save
- Escape → revert

---

## Component 2: PanelDetailModal

### Purpose

Full panel inspection, prompt editing, and image regeneration for DrawRoom.

### Layout

```
┌─────────────────────────────────────────────────────┐
│ PANEL 03                                [×]         │
│ scene_id                                            │
│─────────────────────────────────────────────────────│
│                                                     │
│   ┌─────────────────────┐   ┌───────────────────┐  │
│   │                     │   │ [PromptLineageCard]│  │
│   │   IMAGE PREVIEW     │   │                   │  │
│   │                     │   │ [Advanced toggle]  │  │
│   │                     │   │                   │  │
│   └─────────────────────┘   └───────────────────┘  │
│                                                     │
│   [QUICK RE-DO]        [GENERATE]     [CLOSE]      │
└─────────────────────────────────────────────────────┘
```

### Two-Column Layout

- **Left:** Current generated image (max 50% width)
- **Right:** PromptLineageCard in edit mode, fully expanded

### Actions

| Button | Behavior |
|--------|----------|
| **QUICK RE-DO** | Regenerate with current prompt immediately (no modal close needed) |
| **GENERATE** | Save edited prompt, close modal, then regenerate |
| **CLOSE** | Discard edits, close modal |

### State

- Track local draft state for all prompt fields
- "GENERATE" commits draft to backend via `useUpdatePrompt`, then triggers regen
- "QUICK RE-DO" triggers regen without opening edit state

---

## DrawRoom Changes

### Current Behavior

- Panel click → opens `ImageModal` (image only)
- Hover → "REGENERATE" button

### New Behavior

- Panel click → opens `PanelDetailModal` (prompt + image + regen)
- Hover → "QUICK RE-DO" button (same action as modal's QUICK RE-DO)
- "REGENERATE" button is removed from hover overlay

### Backward Compatibility

- `PanelCard` still receives `onRegenerate` prop → maps to "QUICK RE-DO"
- Modal is only opened via panel click, not via `onRegenerate`

---

## DirectRoom Changes

- Replace inline prompt display with `PromptLineageCard` in edit mode
- Keep scene sidebar and overall layout
- Each prompt card becomes a PromptLineageCard with full expand

---

## API Changes

### PUT /projects/{project}/prompts/{scene_id}/{panel_number}

Existing endpoint (`useUpdatePrompt`) already supports full prompt updates. Ensure it handles partial patches correctly.

```typescript
// Partial update example
updatePrompt.mutate({
  project: name,
  sceneId: sceneId,
  data: { scene_id, panel_number, style: "new style" } // only style field
});
```

### GET /projects/{project}/prompts/{scene_id}/{panel_number}

May need a single-panel fetch for loading prompt into modal. Check if `usePromptsForScene` can be used or if a more targeted fetch is needed.

---

## File Structure

```
web/src/
├── components/
│   ├── PromptLineageCard.tsx      # NEW
│   ├── PanelDetailModal.tsx      # NEW
│   ├── PanelCard.tsx             # MODIFIED: remove regen button, add click handler
│   └── ui/
│       ├── EditableText.tsx      # Already exists
│       └── CollapsibleSection.tsx # NEW (shared with other sections if needed)
├── pages/rooms/
│   ├── DrawRoom.tsx               # MODIFIED: integrate PanelDetailModal
│   └── DirectRoom.tsx             # MODIFIED: use PromptLineageCard
└── api/
    └── queries.ts                 # May add single-prompt fetch
```

---

## Implementation Order

1. `CollapsibleSection` component (shared UI primitive)
2. `PromptLineageCard` component
3. Update `EditableText` if needed (multiline in card context)
4. `PanelDetailModal` component
5. `DrawRoom` integration
6. `DirectRoom` integration
7. Remove legacy prompt display code if any

---

## Edge Cases

- **Empty subjects array:** Show "No subjects" in collapsed state
- **Very long style string:** Truncate in collapsed view, full string in expanded
- **Regen while modal open:** Close modal on regen start, reopen on failure
- **Concurrent edits:** Last write wins (no optimistic locking for MVP)
