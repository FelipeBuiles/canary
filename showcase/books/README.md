# Homepage showcase

Each immediate subfolder contains one complete public edition. Folder names set
homepage order: use names such as `01-call-of-cthulhu`, `02-another-book`.
The app reads these folders directly. No backoffice action or production account
mapping is required. The catalogue is committed to Git and copied into the
Docker image, so pushing to `main` deploys it.

The sixth shelf entry is **Astronomical by Sophia Light**, replacing The Terror
on October 8, 2026. Its reader ID is `0110627cd88244f5933fb11bdd85bf2d`;
the edition contains 20 story pages and an SCP Wiki source-credit page, shared
under CC BY-SA 3.0. The Terror is preserved locally under
`showcase/retired-books/05-the-terror/`, outside the public catalogue.

This entry copies the existing immutable public snapshot, retaining its reader
ID, version, page bytes and spread roles. Its story-page pixels were compared
with all 20 hash-verified Finish pages. Repackaging the working project was
blocked by the local account storage limit; no quota settings were changed.
Community recommendations and ready-to-post copy are in
[the Astronomical sharing kit](../../docs/ops/astronomical-community-posts.md).

The seventh shelf entry is **The Monkey's Paw by W. W. Jacobs** (public domain,
1902), added October 15, 2026. Its reader ID is
`b32d070d85f942278577140e7f55778b`; the edition contains 20 story pages. Like
Astronomical, it copies the existing public snapshot because packaging was
blocked by the local account storage limit; all 20 pages are byte-identical to
the Finish pages. Ready-to-post copy is in
[the Monkey's Paw sharing kit](../../docs/ops/monkeys-paw-community-posts.md).

## Add or update a book

From the repository root, run the provider-free packaging command:

```sh
novel_to_comic/.venv/bin/python scripts/prepare_showcase.py \
  projects/ACCOUNT/PROJECT \
  --folder 03-my-book \
  --title "My book" \
  --author "Author credit" \
  --description "A short introduction to the story."
```

The project must pass the same Finish checks as a published book. This runs no
paid generation. It copies finished pages (including saved lettering) and public
metadata only. It does not copy manuscripts, prompts, accounts, or working files.
The generated `book.json` and version folder belong together; do not copy a whole
working project into this folder.

Run the same command with the same destination folder to update a book and retain
its reader URL. The previous edition stays readable if preparation fails.
Older version directories can be deleted after a successful update; only the
version named in `book.json` is served. Edit title, author, or description in
`book.json` directly if desired; do not change IDs or page metadata.

## Order, remove, deploy

- Rename folders to change their alphabetical order without changing reader URLs.
- Move a book folder outside `showcase/books/` to remove it from the homepage **and**
  disable its bundled public reader on the next deployment.
- Check all entries:
  `novel_to_comic/.venv/bin/python scripts/prepare_showcase.py --check`.
- Commit each `book.json` with its versioned image folder, and delete older version
  folders after an update so the image stays small. The image build and the backend
  tests validate the catalogue; no database import is needed.
- If an invalid `book.json` still reaches a server, the homepage skips only that
  book and reports the error to error tracking.
- A separately mounted catalogue can still replace the bundled one through
  `CANARY_SHOWCASE_DIR`; validate it with `scripts/prepare_showcase.py --check`
  using the same variable.

Keep only work deliberately selected for public display here. This is a curated
demo catalogue independent of account-owned publications and consent controls.
A separately published copy of the same work retains its own public URL.

`CANARY_SHOWCASE_DIR` can override this directory for tests or a separately mounted
catalogue; the default is this repository's `showcase/books/` directory.
