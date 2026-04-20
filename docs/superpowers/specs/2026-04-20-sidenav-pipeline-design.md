# SideNav Pipeline Control — Design Spec

**Date:** 2026-04-20
**Status:** Draft

## Overview

Remove the top header navigation entirely. Redesign the SideNav as the single source of truth for all navigation and pipeline control. The SideNav shows the full pipeline status, stage details, and provides the primary action button to continue the pipeline.

---

## Header Removal

- Remove `TopNav.tsx` entirely — no more top navigation bar
- Keep project selector (it stays where it is or moves into SideNav)
- App title / logo moves into SideNav header when expanded

---

## SideNav Redesign

### Dimensions

- **Expanded width:** 280px (readable, spacious)
- **Collapsed width:** 56px (icon rail)
- **Expanded by default** on page load
- **Collapsible** via click on a collapse toggle or the SideNav header

### Collapsed State (Icon Rail)

Each stage shows as an icon button:
- Checkmark icon for complete stages
- Play/running icon for running stages
- Alert icon for failed / awaiting_review stages
- Circle icon for pending stages
- Tooltip on hover showing stage name

### Expanded State

```
┌──────────────────────────────┐
│ [Logo]  Canary         [≡]   │  ← Header with collapse toggle
├──────────────────────────────┤
│ ▸ EXTRACT    ✓               │
│ ▸ CAST       ✓               │
│ ▸ ADAPT      ✓               │
│ ▸ STORYBOARD ✓               │
│ ▸ DIRECT     ● RUNNING       │  ← Current stage highlighted
│ ▸ DRAW       ○ PENDING       │
│ ▸ COMPOSE    ○ PENDING       │
├──────────────────────────────┤
│                              │
│   ●████████████████░░░░░░░   │  ← Progress bar (3/7 complete)
│                              │
│      [ CONTINUE → ]         │  ← Primary action button
│                              │
├──────────────────────────────┤
│ [Settings]        [Help]     │  ← Footer
└──────────────────────────────┘
```

### Stage Rows

Each stage row shows:
- **Stage name** (larger text, ~14px)
- **Status badge** with clear label:
  - "COMPLETE" / "DONE" (green)
  - "RUNNING" (amber, pulsing)
  - "REVIEW" (red, for awaiting_review)
  - "FAILED" (red)
  - "PENDING" (gray)
- **Progress fraction** if running (e.g., "5/12 panels")
- **Blocked reason** if pending due to dependency (e.g., "waiting for DRAW")

### Stage Status Strip (Timeline)

Horizontal visual strip above the stage list:
```
[✓] → [✓] → [✓] → [✓] → [●] → [○] → [○]
```

Icons: ✓ complete, ● running, ✗ failed/review, ○ pending

---

## CONTINUE Button

Primary action button at the bottom of SideNav.

### States

| Condition | Label | Action |
|-----------|-------|--------|
| `awaiting_review` exists | "APPROVE & CONTINUE" | Approve then run next |
| Pipeline idle, next stage pending | "CONTINUE" | Run next stage |
| Pipeline running | "RUNNING..." + spinner | Disabled |
| All stages complete | Hidden or "VIEW COMIC" | Navigate to compose |

### Behavior

- Auto-determines correct next action based on pipeline state
- If multiple stages need approval, approves all in order then runs
- Single button, no ambiguity

---

## Floating Indicator (During Pipeline Run)

Shows when `is_running = true`. Fixed bottom-right corner.

### Layout

```
┌─────────────────────────────────┐
│  ● DIRECT — RUNNING            │
│  ████████░░░░░░░░  8/12       │
│                                 │
│  Jump to [DIRECT →]   [Cancel] │
└─────────────────────────────────┘
```

### Behavior

- Shows current stage name + running indicator
- Progress bar with items done/total
- "Jump to [Stage →]" navigates to that stage's room
- "Cancel" stops the pipeline (if cancellation is implemented)
- Collapses automatically when pipeline completes

---

## Project Selector

Project selector is kept and integrated into SideNav:
- Shows current project name prominently at top of SideNav
- Click to expand list of all projects
- "NEW PROJECT" button creates a new project

---

## Removed Elements

- **TopNav** — completely removed (project selector is preserved, moves into SideNav)
- **"NEW CHAPTER" / "RENDER" button in header** — removed
- **Footer component** — replaced by SideNav footer
- **LiveSpecPill** — replaced by floating indicator

---

## Implementation Notes

### Files to Modify

```
web/src/
├── layout/
│   ├── SideNav.tsx         # Complete redesign
│   ├── Shell.tsx           # Remove TopNav, add SideNav
│   └── TopNav.tsx          # DELETE
├── components/
│   ├── ui/LiveSpecPill.tsx # Replace with floating indicator
│   └── ProjectSelector.tsx # NEW or integrate into SideNav
└── pages/
    └── NavigateToRoom.tsx  # May need updates

novel_to_comic/src/novel_to_comic/
└── (no backend changes needed — this is pure UX)
```

### State Dependencies

- `useProjectStatus()` — already provides `is_running`, `stages` dict
- `useApproveStage()` — existing mutation
- `useRunAction()` — existing hook for running pipeline
- `useCancelPipeline()` — check if exists, may need to add

### Accessibility

- Keyboard navigation through stage list
- ARIA labels for status badges
- Focus management when SideNav expands/collapses
- Screen reader announcements for pipeline state changes

---

## Implementation Order

1. Create `FloatingIndicator` component (replaces LiveSpecPill)
2. Redesign `SideNav` structure with expanded/collapsed states
3. Remove `TopNav` from `Shell.tsx`
4. Implement project selector in SideNav
5. Add CONTINUE button with auto-action logic
6. Style: larger text, wider sidebar, better status readability
7. Add icons for collapsed state
8. Test full pipeline flow: wizard → exit → continue from SideNav
