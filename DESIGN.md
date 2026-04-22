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
