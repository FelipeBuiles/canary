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

PULP turns a novel into a comic book through a 9-stage pipeline (extract →
style → cast → adapt → plan → storyboard → direct → draw → compose), each stage
resumable and human-reviewable. The web app is the studio: one room per stage,
a pipeline sidebar that runs/approves stages, credit metering for AI spend
(Stripe top-ups), and a compose editor for lettering and final export
(PDF/CBZ). Success = a user ships an issue they're proud to show, and trusts
the cost meter enough to run the next one.

## Brand Personality

"The Living Ink" (see DESIGN.md): a Golden-Age print-shop tribute, not a SaaS
template and not a comic parody. Three words: **crafted, mechanical, theatrical**.
The interface behaves like a working pressroom — things stamp, press, and
register; statuses read like a production floor (CASTING CALL, STUDIO
TELEMETRY, TOTAL INK USAGE). Voice is a confident studio foreman: warm,
specific, lightly dramatic at checkpoints, never wacky during errors or billing.

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
   milestones (style picked, all panels drawn, issue exported); steady-state
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
