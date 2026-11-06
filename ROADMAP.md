# Roadmap

This is the work I plan to do next. Canary is a solo learning project (see the
[README](README.md)), so priorities shift as I learn from the live instance.
For background, see the design notes in [docs/proposals/](docs/proposals/)
and the decisions in [docs/adr/](docs/adr/).

## Now

- **Validate recently built features against real providers.**
  [Cold Open](docs/proposals/cold-open-2026-10-26.md) (an author's opening
  scene as a comic page in about a minute) and
  [The Director](docs/proposals/director-2026-10-27.md) (notes that carry
  through to later pages) both pass provider-free tests. Neither has been run
  end to end on paid models or checked visually.
- **Make Extract more reliable on messy manuscripts.** That means PDF page
  breaks, unpunctuated headings, and scene openings the model can't resolve
  on its first pass.
- **Polish page review after the studio redesign.** This covers the reading
  rooms, the redraw states and lettering editing at laptop sizes.

## Next

- **Self-service flow.** An author should be able to sign up, try a scene,
  buy credits and finish a book without help
  ([strategy](docs/proposals/self-service-launch.md)).
- **Second-pass OCR checks.** Turn on the opt-in Textract close-up OCR once
  its quality is measured ([reference](docs/reference/textract-ocr.md)).
- **Series workflow.** Make it easier to work across multi-part books that
  share a style, a cast and a Story Bible
  ([ADR 0023](docs/adr/0023-series-parts-and-author-owned-story-bible.md),
  [ADR 0024](docs/adr/0024-part-sequences-and-the-book-map.md)).
- **Clearer credits.** Keep estimates, provider usage and charged credits
  distinct and easy to understand in every room.

## SaaS operations (the learning part)

- Backup and restore drills for project volumes and the database
  ([runbook](docs/ops/backup-restore.md)).
- Alerting and dashboards on generation failures, provider fallbacks and spend.
- Safer deploys: rehearsing configuration changes and rolling them back.
- Keeping the test suite fast while the feature set grows
  ([backend test maintenance](docs/reference/backend-tests.md)).

## Ideas, not scheduled

- More house styles and better style-proof variety.
- Export presets for print-on-demand services.
- More UI and comic-output languages (the UI is currently English, Spanish and
  French).
