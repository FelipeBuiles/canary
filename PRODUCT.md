# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

Writers, indie authors, and small studios who want their prose fiction turned
into a finished comic book without hiring an art team. They arrive with a
manuscript (.txt/.epub/.pdf), not design skills. They work in long sessions:
upload, wait for generation stages, review checkpoints, nudge and regenerate,
export. Tech comfort is moderate — they understand "credits" and "export PDF",
not "diffusion model" or "prompt".

## Product Purpose

Scenewright turns a novel into a comic book through an 8-stage pipeline (extract →
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

## Positioning

Scenewright is a guided production pipeline rather than an image-generation
canvas: it carries a manuscript from structured story understanding through
style and cast continuity, complete-page drawing with authored lettering, and
print-ready export. The author retains creative control at meaningful
checkpoints while intermediate machine artifacts run automatically and remain
inspectable.

## Operating Context

Work happens in long studio sessions: authors upload a manuscript, wait for
generation stages, review checkpoints, request bounded corrections, and export
the finished issue. The web app communicates with a FastAPI backend over REST
and server-sent events; project work may involve manuscript files, visual
references, generated page images, and PDF/CBZ exports.

## Capabilities and Constraints

- The active pipeline stages are `extract → brief → style → cast → adapt →
  plan → draw → finish`. It presents them as Story, Look, Pages, and Book.
- Story brief, selected style, cast, page review, and book preflight are the
  author-facing decision points. Adaptation and planning artifacts auto-run,
  remain inspectable, and do not independently block progress.
- Draw produces complete, lettered comic pages. Corrections are complete-page
  revisions, with pages accepted by default unless an author flags an issue.
- AI spending is estimated in credits; Stripe supports top-ups. Credit
  estimates, usage, and charges must remain distinct and intelligible.
- The UI is available in English, Spanish, and French. Comic-output language is
  configured per project independently of the UI language.
- The product is a React, TypeScript, and Vite web app backed by a Python
  FastAPI pipeline engine.

## Brand Commitments

The visual identity is "The Living Ink": a Golden-Age print-shop tribute, not
a generic SaaS interface or comic-book parody. Its voice is crafted,
mechanical, and theatrical—warm and specific at real checkpoints, but clear
and calm for errors and billing. Familiar terms remain familiar to authors;
internal vocabulary stays behind Dev Content.

## Anti-references

- Sterile flat-gray SaaS dashboards (generic Linear/Notion clone energy).
- Rounded, glassy, gradient-text "AI tool" aesthetic.
- Comic-book parody: novelty lettering everywhere, BAM!/POW! on every surface,
  Comic Sans energy. The system is a tribute to print craft, not a costume.
- Material-style soft shadows and 1px gray hairline borders.

## Evidence on Hand

- The implemented web client is under `web/`; its primary rooms are
  `web/src/pages/rooms/StoryRoom.tsx`, `StyleRoom.tsx`, `CastRoom.tsx`,
  `PagesRoom.tsx`, and `BookRoom.tsx`.
- The engine is the `novel_to_comic/` Python package. API and stage contracts
  are documented in `docs/reference/api-routes.md` and
  `docs/reference/stage-contracts.md`.
- `DESIGN.md` records the existing interface design system. It is visual-system
  documentation, not a source of product claims.

## Product Principles

1. **The tool disappears into the task.** Rooms are dense, consistent work
   surfaces; familiarity over novelty.
2. **Print physics, not digital chrome.** Feedback is pressed, stamped, offset,
   screened (Ben-Day) — never glowing, bouncing, or floating.
3. **Delight at checkpoints, calm in between.** Celebration belongs to real
   milestones (style picked, all pages drawn, issue exported); steady-state
   surfaces stay quiet and informative.
4. **Empty states teach the press.** Pending rooms explain inputs → outputs of
   the stage rather than saying "nothing here".
5. **Honest machinery.** Real progress counts, real ETAs, real credit estimates
   and holds — flavor never obscures what the pipeline is actually doing.

6. **The author owns the project.** Generated descriptions are starting points,
   not creative permission boundaries. Explicit visual changes take precedence;
   preserve what the author did not ask to change. Keep optional reference
   attachments neutral and let the author describe their purpose. Make creative
   experiments reversible through visible version history.

## Accessibility & Inclusion

- Body text contrast ≥ 4.5:1; hero-red text only on bristol/pulp backgrounds
  (DESIGN.md accessibility note).
- `prefers-reduced-motion` honored globally (index.css) and inside canvas
  animations (FlowingDotsPlaceholder renders a static frame).
- Keyboard support: skip-to-content link, `:focus-visible` outlines, visible
  Esc affordances on dialogs.
- UI ships in en/es/fr; generated comic output language is a per-project
  setting independent of UI language.
