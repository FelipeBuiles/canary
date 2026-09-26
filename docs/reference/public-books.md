# Public books

**Status: Current.** Implemented publication and reader contract.

The Book room publishes every page of a finished edition, after a fresh,
provider-free Finish check. Publishing is opt-in. The author supplies a public
title, author credit, description, and optional permission for homepage featuring.
The preview opens the existing full-book reader. Publishing exposes reading and
downloading; manuscripts, prompts, working files, and account identifiers are
not included in the public manifest.

Published copies live on the existing persistent projects volume under
`.publications/`. An account/project-scoped private index identifies a stable,
random public book ID. Each publication prepares a new immutable version from
Finish's normalized pages (including saved editable lettering), verifies their
hashes, and atomically switches the current manifest only after every copy is
ready. Production artifact locks serialize source capture with lettering writes.
Failed updates leave the prior version public. Ordinary project edits do not
change the published version.

Finish preflight is provider-free and recomputes current inputs on an explicit
retry. It does not replay action receipts, including pending receipts left by
older clients after an interruption. Paid generation and publication retain
their existing receipt handling. Check failures display the server error in Book.

The owner can update or unpublish from Book. Deleting a project also unpublishes
it. Public metadata, images, and downloads require a current manifest and use
`Cache-Control: no-store`; superseded version URLs return 404. Unpublishing cannot
revoke copies readers have already downloaded. Old version files are retained
on disk; storage reclamation is not yet automated. This uses the same single
persistent-volume deployment model as working project artifacts, not R2.

## Reader languages

Editable-lettering (hybrid) editions publish every stored language a reader can
switch to. The project's current lettering language is the primary `pages` set,
recorded as `locale` (`source` means the original copy). Each other `en`/`es`/`fr`
language is frozen into the same version under `{version}/{locale}/` and listed in
`translations`, with the same page numbers. A language qualifies only when every
lettering element on every page stores it (translation's `translate_count == 0`
rule, hidden elements included). Its saved placement is laid out again in memory
and must pass publication validation: no overflow, `missing_glyphs`, `empty_copy`
or other warnings. A language that fails is left out; the book still publishes,
and the owner's publish response alone lists `unpublished_locales` with reasons.
Publishing never switches or rewrites the project's lettering.

Retained baked editions have no `locale` or `translations` and no reader toggle.
Publications made before this change still read as single-language books; republish
to add languages. The reader shows the toggle only for two or more languages, keeps
the current page on a switch, names the language in each page's image label, and
remembers the viewer's choice in `localStorage` (`canary.readerLanguage`).
Downloads take `?locale=` for a published language.

## Manual homepage catalogue

The homepage now reads the repository's `showcase/books/` folder, in alphabetical
subfolder order. Each prepared folder holds public metadata and complete,
normalized pages. Generated editions stay outside Git and the Docker build
context. Production supplies the catalogue through a volume at
`/app/showcase/books` or `CANARY_SHOWCASE_DIR`; the image defaults to an empty
catalogue. Account-owned publications on the persistent volume remain independent. Backoffice featuring is disabled.
Author consent alone does not add a book to this manually curated catalogue.

Use `scripts/prepare_showcase.py` to package a finished project without paid
generation. It preserves the public ID on updates, validates the Finish checks,
and switches the manifest only after every page is copied. See
[the showcase instructions](../../showcase/books/README.md) for adding, ordering,
removing, and deploying books. Removing a folder disables its bundled reader;
it does not unpublish any separate account-owned publication.

## Surfaces and routes

- `GET/POST/DELETE /api/projects/{project_id}/publication`: authenticated owner
  status, explicit publish/update, and unpublish.
- `/read/{book_id}`: anonymous page-turning reader shared with the Book station, with
  left/right navigation, arrow keys, swipe gestures, single-page/spread layouts,
  fit-height/fit-width controls, native sharing or clipboard fallback, and a
  closing Scenewright invitation after the final story page. The closing page
  is not counted as a story page. New publications retain authored spread roles;
  publications without that optional presentation metadata show individual pages.
- `GET /api/public/books`: ordered books from the manual showcase folder.
- `GET /api/public/books/{book_id}`: allowlisted public manifest.
- `GET /api/public/books/{book_id}/{version}/pages/{number}`: current-version JPEG.
- `GET /api/public/books/{book_id}/{version}/locales/{locale}/pages/{number}`: the same page
  in another published language; 404 for any language not in `translations`.
- `GET /api/public/books/{book_id}/download/{pdf|cbz}[?locale=]`: published
  edition download with a branded closing page included in every download. It is appended outside
  story numbering and does not alter project exports or production artifacts.
  The closing page includes the existing logo, a QR code, and a clickable PDF
  link. The download section previews the exact back-page image via
  `GET /api/public/books/{book_id}/bookend`. Downloads and publication are rate-limited using the export limit.
- `GET /api/ops/publications`: existing operator-token protected publication inventory.
  Homepage selection is managed through the showcase folder.

The anonymous homepage displays showcase books directly below the scene sample when any exist. The production
FastAPI SPA handler adds escaped, book-specific Open Graph metadata for direct
reader requests. Frontend deployments that serve HTML independently must proxy
`/read/*` to this handler to get crawler previews. The Vite dev server uses its
ordinary SPA document.

`SCENEWRIGHT_APP_URL` supplies the absolute application origin for social metadata,
QR codes, and export links (default `https://app.scenewright.ink`). Reader CTAs carry
`ref=book-{id}` into signup; valid IDs are retained as `referred_by_book` signup
metadata. This is attribution only, not a referral rewards or analytics dashboard.
The public UI supports the existing English, Spanish, and French interface
languages; the printed promotional back page currently uses English.

## Verification

`test_publications.py` covers snapshot isolation, stable public IDs, failed
updates, unfinished editions, unpublishing, account-scoped management, manual showcase packaging and removal, escaped crawler metadata, mandatory PDF/CBZ back-page order,
and reader languages (completeness and fit, frozen versions, baked editions).
`publicBook.test.tsx` covers anonymous reading, unavailable books, export options,
the language toggle, and explicit owner publishing/unpublishing.
