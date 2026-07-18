# ADR 0001: UI Composites Layer

**Status:** Accepted
**Date:** 2026-05-15

> **Current status (2026-07-18):** Current. The atoms/composites split and
> component-led adoption remain the active frontend architecture. The room
> counts and migration inventory below are historical context, not a current
> implementation census.

## Context

At the time of this decision, the web frontend had eight room pages and about
4,900 lines of room-specific UI. An audit found significant visual
inconsistency despite a canonical design system and primitive components.

The drift manifests in three forms:

1. **Primitive drift** — same conceptual surface implemented three different ways. Card surfaces alone appear as `border-[2px] border-ink-black/8 bg-bristol` (StoryBibleRoom), `border-[3px] border-ink-black/8 bg-bristol` (CastRoom, StyleRoom), and `border-[2px] bg-pulp-paper` (PanelCard).
2. **Layout drift** — each room invents its own page chrome: section headers, sidebars, toolbars, tab bars.
3. **Pattern drift** — composite patterns like "regen with cost estimate", "scene sidebar + reading pane", "stage-blocked placeholder" are rebuilt fresh in each room.

The existing `components/ui/` folder mixes 30-line atoms (`Tag`, `IconButton`) with 5K-line organisms (`StagePlaceholder`, `RerunDrawer`). When an engineer (or coding agent) opens the folder, there is no signal which file to reach for, and the answer to "do I use `<Surface>` or `className='ui-surface'`?" is unclear because both exist.

The primitives that *do* exist often have rigid APIs that don't match real consumer needs — `SectionDivider` requires a `number` prop, forcing the "SECTION 01 //" shape, which is why every room invented its own unnumbered section header instead.

## Decision

Introduce a **composites layer** between atoms and rooms.

### 1. Two-folder split

- `web/src/components/ui/` — **atoms.** Leaf components with no knowledge of layout above themselves. Examples: `Button`, `Field`, `Tag`, `StatusPill`, `Icon`, `Skeleton`, `StateBlock`.
- `web/src/components/composites/` — **organisms.** Compose atoms into recurring layout patterns. Examples: `SectionHeader`, `EntityCard`, `RoomHeader`, `RoomShell`, plus the deferred `Toolbar`, `RoomTabs`, `RegenAction`, `EmptyState`, and `SceneSidebar`.

### 2. Components are canonical; CSS-component classes are implementation detail

The `@layer components` classes in `index.css` (`ui-surface`, `ui-field`, `ui-title`, `ui-kicker`, `section-rule`) survive only as the internal implementation of React components. Application code calls `<Surface>` / `<SectionHeader>`, never the CSS class directly. Classes with zero remaining `.tsx` call sites are deleted lazily during per-room migrations.

Design tokens (`@theme` variables) are unaffected — those remain canonical in CSS.

### 3. API rules

- **Layout-known composites** (header-shaped) use strict-prop slots (`kicker`, `title`, `actions`, `description`) and forbid `children` for the header content. This prevents drift via slot-stuffing.
- **Content containers** (surface-shaped) use `children` + modifier props (`tone`, `shadow`, `padding`, `active`, `interactive`).
- **No pre-invented variants.** Add a variant only when a real consumer needs it.

### 4. Deprecated primitives are deleted, not soft-deprecated

After the breadth migration completes for a given old primitive, it is removed from the codebase. `SectionDivider` and `SectionLabel` are subsumed by `SectionHeader` and will be deleted once all call sites migrate. Removing the wrong path is the strongest available adoption lever.

### 5. Exemplar-first migration

The first migration is `StoryBibleRoom` (the smallest room at 274 lines), refactored end-to-end to use the new composites. The composites' APIs are designed against this real consumer, not in the abstract. Once the exemplar ships, the remaining rooms are migrated composite-by-composite (breadth), so each PR is visually narrow.

## Alternatives considered

**Flat `components/ui/` folder.** Current state. Rejected because it conflates atoms and organisms, gives no signal which file to reach for, and the 32-file folder demonstrably failed to drive adoption.

**Four-layer atomic-design hierarchy** (atoms / molecules / organisms / templates). Rejected as overkill at this codebase size. Two layers carry the needed information; more layers add ceremony without additional discrimination.

**Unify the outer room scaffold.** Define a canonical `<Room>` with slots and force every room into one shape. Rejected because room shapes are genuinely different (DrawRoom has a persistent progress sidebar, ComposeRoom has Script/Layout/Style/Preview modes, AdaptRoom is screenplay-shaped). A single scaffold would either force escape hatches or omit legitimate variation. Selective scaffold extraction (e.g., a future `SceneRoom` for AdaptRoom + DirectRoom) happens only after the shared shape is empirically obvious.

**CSS-first design system** (canonicalize the `@layer components` classes, treat React components as optional sugar). Rejected because CSS classes can't enforce slot structure — you can put any markup inside a `.ui-surface` div, including a forked section header. Components let us encode the layout contract.

**Composite-first, breadth-first migration** (build `SectionHeader` in the
abstract, then migrate all rooms at once). Rejected because designing
primitives without a real consumer is what produced the unused primitives in
the first place. The exemplar-first approach uses a real room to anchor each
API decision.

**Heavy enforcement via Stylelint / visual-regression tests.** Rejected for now as cost-to-value is wrong at this stage. If drift recurs after the deletion + docs + narrow ESLint rule prove insufficient, revisit.

## Consequences

**Positive:**
- Two-folder structure gives engineers and coding agents a clear signal which file to reach for.
- Designing APIs against a real consumer (exemplar-first) prevents the over-generalization that caused current primitives to go unused.
- Deletion of deprecated primitives makes the wrong path harder than the right one — the strongest adoption lever available without runtime checks.

**Negative / costs:**
- Migration is incremental and will span multiple PRs. During the transition, both the new composites and the old primitives exist side-by-side, which is the very duplication this ADR is trying to eliminate. Mitigated by deleting old primitives as soon as their call sites hit zero, not at the end of the full migration.
- A future "I need something slightly different" case will require either extending an existing composite's API or adding a new composite — never forking inside a room. This is a discipline cost on PR review.
- The `components/ui/` → `components/composites/` move for existing organism-shaped files (`RoomHeader`, `RoomShell`, `StagePlaceholder`, `ConfirmDrawer`, `RerunDrawer`, `SceneSidebar`) creates import churn. Mitigated by moving files only when they are touched, not in a big-bang move.

**Out of scope for this ADR:**
- The individual composite APIs (`SectionHeader`, `EntityCard`, etc.) are documented in `DESIGN.md` §7 and in the component files themselves.
- The five deferred composites (`Toolbar`, `RoomTabs`, `RegenAction`, `EmptyState`, `SceneRoom` scaffold) are designed when their first real consumer is migrated, not now.
