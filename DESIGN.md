# Design System Document: The Narrative Frame

## 1. Overview & Creative North Star
**Creative North Star: "The Living Ink"**

This design system rejects the sterile, flat "SaaS-standard" aesthetic in favor of a visceral, editorial experience. It is a digital manifestation of the Golden Age of comics—not as a parody, but as a high-end skeuomorphic tribute to ink-on-paper. 

We break the digital "template" look through **Impactful Asymmetry** and **Medium-Awareness**. Instead of a standard grid, elements should feel like panels on a page. We use "Breaking the Gutter" techniques where imagery or primary accents overflow their containers to create kinetic energy. The goal is a UI that feels like it was printed, pressed, and hand-inked, using high-contrast scales to command attention and drive the user through a narrative journey.

---

## 2. Colors: High-Contrast Ink & Pulp
Our palette is rooted in the "Pulp & Pigment" philosophy. We use a sophisticated cream base to simulate aged paper, contrasted with a high-intensity "Hero Red."

### Surface Hierarchy & Nesting
Traditional 1px gray borders are strictly forbidden. In this system, boundaries are defined by **Physical Stacking**.
*   **The "No-Line" Rule:** Do not use `outline` for sectioning. Use `surface-container-low` (#f6f4e7) against the `surface` (#fcfaed) to define large content areas.
*   **Nesting:** Treat the UI as stacked sheets of Bristol board. A `surface-container-lowest` card (pure white #ffffff) should sit atop a `surface-container` (#f0eee1) background to create a crisp, "popping" effect that mimics a freshly printed panel.

### The "Glass & Ben-Day" Rule
To add signature depth, we use **Ben-Day dot patterns** (using `surface-variant` #e4e3d6) as a subtle background texture in containers. 
*   **Glassmorphism:** For floating navigation or "Action Bubbles," use `surface` at 80% opacity with a `20px` backdrop blur. This allows the high-energy Ben-Day dots to bleed through the glass, softening the aesthetic without losing the comic-book grit.
*   **Signature Textures:** Apply a subtle linear gradient from `primary` (#b51822) to `primary_container` (#d93537) on all main CTAs. This simulates the slight color variation found in vintage four-color printing.

---

## 3. Typography: The Editorial Voice
Typography is the "voice" of this system. We use a dramatic scale shift to differentiate between the "Narrator" (Display) and the "Dialogue" (Body).

*   **Display & Headline (Anybody):** These are your "Sound Effects." Use `display-lg` for hero sections with assertive all-caps styling. It should feel heavy, poster-like, and slightly off-kilter without becoming novelty lettering.
*   **Title & Body (Be Vietnam Pro):** This is your narrative text. It provides a clean, modern contrast to the aggressive headlines, ensuring long-form legibility while maintaining a sophisticated, geometric feel.
*   **Labels (Lexend):** Used for "Metadata" and technical callouts. Lexend’s hyper-legibility mimics the clarity of classic comic book lettering at small scales.

---

## 4. Elevation & Depth: Tonal Stacking
We avoid "Material" style drop shadows. Instead, we use **Mechanical Shadows** and **Tonal Layering**.

*   **The Layering Principle:** Depth is achieved by "Offset Stacking." Instead of a centered shadow, offset a container by 4px or 8px and place a `surface-dim` (#dcdace) or `secondary_fixed` (#d3e4ff) block behind it to create a "drop-shadow" that feels like a physical layer of paper.
*   **Ambient Shadows:** If a floating effect is required (e.g., a Modal), use a tinted shadow: `color: on-surface` at 8% opacity with a 32px blur. This mimics natural light falling on a physical page.
*   **The "Ghost Border" Fallback:** In high-density data views where containment is vital, use `outline-variant` (#e4beba) at **15% opacity**. Never use 100% opaque lines; they break the "printed" illusion.

---

## 5. Components: Ink-Ready Primitives

### Buttons (The "Action Panels")
*   **Primary:** Background: `primary` gradient; Text: `on_primary` (All-Caps). Use a `2px` offset shadow of `primary_fixed_dim` to give it a "pressed" look.
*   **Secondary:** Background: `secondary_container`; Text: `on_secondary_container`.
*   **Tertiary:** No background. Use `headline-sm` typography with a `primary` underline that animates on hover.

### Cards & Lists (The "Gutters")
*   **Forbid Dividers:** Do not use horizontal rules. Separate list items using `8px` of vertical whitespace and a subtle background shift to `surface-container-low` on hover.
*   **The "Panel" Card:** Use `surface-container-lowest` with a "Ghost Border." If the card is featured, add a `primary` corner-accent (a small 16px triangle) to the top right to mimic a page fold.

### Input Fields (The "Dialogue Box")
*   **State:** Use a heavy `2px` bottom-border of `primary` when focused.
*   **Labels:** Always use `label-md` in `tertiary` (#6b5f00) to provide a "hand-written note" contrast against the input.

### Signature Component: "The Narrator Tag"
A bespoke component for this system: Use a `tertiary_container` rectangular tag with sharp 0px corners, containing `label-sm` text. Place this overlapping the top-left edge of any container to act as a section header, mimicking a comic's narration box.

---

## 6. Do’s and Don’ts

### Do:
*   **Do** embrace asymmetry. Align a headline to the left but a sub-headline to the right to create a "panel" flow.
*   **Do** use "Hero Red" (`primary`) sparingly for maximum impact—save it for the most critical user actions.
*   **Do** use extreme type scales. If a headline is `headline-lg`, make sure the body text is significantly smaller (`body-md`) to create drama.

### Don't:
*   **Don't** use border-radius. Every corner in this system must be `0px`. Roundness kills the aggressive, "cut-paper" energy.
*   **Don't** use pure black for text. Use `on_surface` (#1b1c15) to keep the "ink-on-paper" look feeling premium and readable.
*   **Don't** use standard "toast" notifications. Use high-contrast "Burst" boxes that utilize the `tertiary_fixed` (#fae361) color to grab attention like a "POW!" graphic.

### Accessibility Note:
Ensure all `primary` red text sits on `surface-container-lowest` or `background` to maintain a 4.5:1 contrast ratio. When using Ben-Day patterns, keep the opacity low enough that it does not interfere with the legibility of `body-md` text.

---

## 7. Composites (Organism Layer)

Between the atoms in `web/src/components/ui/` (Button, Field, Tag, StatusPill, Icon, …) and the room pages, there is a canonical **composite** layer in `web/src/components/composites/`. Rooms compose composites. Composites compose atoms. Rooms do **not** reinvent card surfaces, section headers, toolbars, etc. as one-offs.

### The two-folder rule

| Folder | Purpose | Examples |
|--------|---------|----------|
| `components/ui/` | **Atoms.** Leaf components. No knowledge of layout above themselves. | `Button`, `Field`, `Tag`, `StatusPill`, `Icon`, `Skeleton`, `StateBlock` |
| `components/composites/` | **Organisms.** Compose atoms into recurring layout patterns. | `SectionHeader`, `EntityCard`, `RoomHeader`, `RoomShell`, `Toolbar`, `RoomTabs`, `RegenAction`, `EmptyState`, `SceneSidebar` |

### Canonical composites

| Composite | Use for |
|-----------|---------|
| `SectionHeader` | Any in-room section header. Subsumes the old `SectionDivider` and `SectionLabel`. Variants: `rule` (uppercase meta + horizontal line), `underline` (h2 with 2px border-bottom). |
| `EntityCard` | Any Bristol-paper "panel" card surface — character/location/style/prop/panel cards. Optional `media` slot, optional `footer` slot, `active` + `interactive` boolean states. `padding` variant `"cozy"` (`p-3`, dense grids like panel cards), `"tight"` (`p-5`, ref cards with media), or `"comfortable"` (`px-7 py-6`, text-heavy cards). |
| `RoomHeader` | Top of every room page. Kicker + title + lead + actions. |
| `RoomShell` | Outer room wrapper with loading/empty fallbacks. |
| `Toolbar` | Horizontal toolbar row with optional 2px bottom-rule divider. `children` slot for tabs, search, selects, view-mode toggles. |
| `RoomTabs` | Joined-button tab strip with `bg-ink-black` active and `bg-pulp-paper` inactive states, optional count badges. Used for filter tabs. Underline tabs (hero-red border-b) and scrolling panel tab strips are *different* visual patterns — they stay as room-local components until a 2nd consumer appears. |
| `RegenAction` *(to be added)* | The regen-with-cost-estimate-and-confirm pattern. |
| `EmptyState` *(to be added)* | The stage-blocked / list-empty placeholder. `StagePlaceholder` is the current stage-aware variant; split into a thin primitive when a non-stage consumer appears. |

### API rules

1. **Layout-known composites use strict-prop slots.** Header-shaped components (`SectionHeader`, `RoomHeader`, `SurfaceHeader`, `StateBlock`) accept named slot props (`kicker`, `title`, `actions`, `description`) and forbid `children` for the header content. This keeps the visual layout canonical and prevents drift via slot-stuffing.
2. **Content containers use `children` + modifier props.** Surface-shaped components (`Surface`, `Card`, `EntityCard` body) accept `children` and modifier props (`tone`, `shadow`, `padding`, `active`, `interactive`).
3. **Don't pre-invent variants.** Add a variant only when a real consumer needs it. Three is better than seven.

### Card surface rule (the "Bristol Panel")

Every panel-style card surface uses the same physical treatment:

- Border: **`2px solid border-ink-black/8`** (the "ghost border" at 8% opacity). Not 3px. Not 1px.
- Background: **`bg-bristol`** (pure white).
- Hover (when `interactive`): border darkens to `border-ink-black/24`. Not full opacity — full opacity reads as a *click* state, not a hover state.
- Active/selected: border at full opacity + `shadow-ink`.

Outside of `EntityCard`, this combination should not appear in room code. If you find yourself writing `border-[2px] border-ink-black/8 bg-bristol` in a room, you should be reaching for `EntityCard` instead.

### Surface border variant — "hard" vs "soft"

`Surface` accepts a `border` prop: `"hard"` (default, `border-ink-black`, used with `shadow-paper` for the "popping front sheet" effect) or `"soft"` (`border-ink-black/10`, used with `shadow="none"` for recessed info panels — sidebar progress cards, live cockpit). Don't reinvent `border-[2px] border-ink-black/10 bg-bristol` inline; use `<Surface border="soft" shadow="none" padding="md">` instead.

### Components are canonical; CSS-component classes are implementation detail

The `@layer components` block in `web/src/index.css` historically defines classes like `ui-surface`, `ui-field`, `ui-title`, `ui-kicker`, `section-rule`. These now exist **only as the internal implementation of React components**. Application code calls `<Surface>` / `<Field>` / `<SectionHeader>`, never the CSS class directly. CSS-component classes with zero remaining call sites in `.tsx` files should be deleted as part of each room migration.

Design tokens (`@theme` variables: `--color-*`, `--font-*`, `--shadow-*`, `--spacing-*`) are not affected by this rule — those remain in CSS as the canonical token store.

### When the existing composite doesn't fit

Don't fork. Change the composite. If you find yourself reinventing a card or section header in a room, that is a signal that either (a) the composite's API needs a new slot or variant, or (b) you should add a new composite. Discuss before forking.


## Error presentation

Use `ErrorNotice` from `components/composites/` for failed requests in rooms,
editors, settings, dialogs and account forms. Pass the original error object,
an operation (`load`, `save`, `generate`, `estimate`, `delete`, `approve`,
`export`, `preview`, `upload` or `auth`), and contextual copy when needed.
It explains the failure and recovery beside the affected control. Storage,
session, rate-limit and indeterminate-action errors have shared recovery copy.
Readable application validation remains visible; JSON bodies, exceptions and
diagnostic identifiers belong in the collapsed `ErrorDetails` disclosure.
Authors can copy those details when reporting a problem.

Supply `onRetry` only for provider-free reads, with the existing pending guard.
Generation retains its estimate and explicit consent controls. An uncertain
paid action directs the author to inspect progress before another submission.
Preserve drafts and confirmation inputs. Local field validation stays next to
its field; developer diagnostics and the specialized stage and page failure
summaries keep their existing context and recovery controls.

## Page change requests

Change requests start with words, not drawing. A user may review and submit a
text-only request directly; adding a request to the list first is not required.
Pins, areas and highlights are optional context attached to one request. Their
extra detail is optional, and never duplicates a required request-writing step.

Keep only **Pin, Area and Highlight** in the primary location toolbar. History,
zoom, freehand outlines, arrows and keyboard pin placement live under **More**.
Finish each new mark in selection mode so the next click cannot accidentally
create another location. Drawing supports cancellation and never creates a
zero-area mark. Preserve existing geometry, request ownership and page lineage.

Location labels are square, numbered ink-and-paper tags with a mechanical shadow
and a paper keyline for contrast over artwork. Use CSS-pixel badges rather than
stretching text in a square SVG viewBox. Geometry scales with the image's actual
aspect ratio. User-facing location lists show names and optional detail, never
coordinate dumps. Raw geometry remains in the provider request.

Text-only correction remains available if an image fails to load. Any invalid
stored location or request limit must be explained before cost review; never
silently discard context. Cost review and an explicit generate confirmation
remain separate, and editing anything submitted invalidates the reviewed draft.
