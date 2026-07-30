# Product

## Register

product

## Users

Writers, indie authors, and small studios who want their prose fiction turned
into a finished comic book without hiring an art team. They arrive with a
manuscript (.txt/.epub/.pdf), not design skills. They work in long sessions:
upload, wait for generation stages, review checkpoints, nudge and regenerate,
export. Tech comfort is moderate — they understand "credits" and "export PDF",
not "diffusion model" or "prompt".

## Product Purpose

PULP turns a novel into a comic book through an 8-stage pipeline (extract →
brief → style → cast → adapt → plan → draw → finish), each stage resumable.
The web app is the studio, presented as four user-facing stations (Story →
Look → Pages → Book): the user makes four decisions — approve the story brief,
choose the look and cast, review complete pages, and finish the edition.
Machine artifacts (adaptation and page plan) auto-run and stay inspectable but
never block. Every station ends in one standing approval bar with a
plain-language next step and `~N credits`. Complete pages are reviewed by
exception and corrected as complete-page revisions. Credit metering for AI
spend (Stripe top-ups) and Book preflight/export handle exact lettering and
final PDF/CBZ output. Success = a user ships an issue they're proud to show,
and trusts the cost meter enough to run the next one.

## Brand Personality

"The Living Ink" (see DESIGN.md): a Golden-Age print-shop tribute, not a SaaS
template and not a comic parody. Three words: **crafted, mechanical, theatrical**.
The interface behaves like a working pressroom — things stamp, press, and
register; statuses read like a production floor (CASTING CALL, ALL PAGES
DRAWN, PAGE BENCH). Voice is a confident studio foreman: warm, specific,
lightly dramatic at checkpoints, never wacky during errors or billing. The
flavor lives in type treatment and stagecraft, never in renaming familiar
concepts — characters are Characters, places are Places, and internal
vocabulary (entity IDs, telemetry, prompts) stays behind Dev Content.

## Anti-references

- Sterile flat-gray SaaS dashboards (generic Linear/Notion clone energy).
- Rounded, glassy, gradient-text "AI tool" aesthetic.
- Comic-book parody: novelty lettering everywhere, BAM!/POW! on every surface,
  Comic Sans energy. The system is a tribute to print craft, not a costume.
- Material-style soft shadows and 1px gray hairline borders (forbidden by
  DESIGN.md — depth comes from offset "mechanical" shadows and tonal stacking).

## Design Principles

1. **The tool disappears into the task.** Rooms are dense, consistent work
   surfaces; familiarity over novelty (product register).
2. **Print physics, not digital chrome.** Feedback is pressed, stamped, offset,
   screened (Ben-Day) — never glowing, bouncing, or floating.
3. **Delight at checkpoints, calm in between.** Celebration belongs to real
   milestones (style picked, all pages drawn, issue exported); steady-state
   surfaces stay quiet and informative.
4. **Empty states teach the press.** Pending rooms explain inputs → outputs of
   the stage rather than saying "nothing here".
5. **Honest machinery.** Real progress counts, real ETAs, real credit estimates
   and holds — flavor never obscures what the pipeline is actually doing.

## Accessibility & Inclusion

- Body text contrast ≥ 4.5:1; hero-red text only on bristol/pulp backgrounds
  (DESIGN.md accessibility note).
- `prefers-reduced-motion` honored globally (index.css) and inside canvas
  animations (FlowingDotsPlaceholder renders a static frame).
- Keyboard support: skip-to-content link, `:focus-visible` outlines, visible
  Esc affordances on dialogs.
- UI ships in en/es/fr; generated comic output language is a per-project
  setting independent of UI language.
