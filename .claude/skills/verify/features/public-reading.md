# Public reading

Anyone, signed in or not, can open a published comic at `/read/:id`. The page opens a `Book reader` dialog that pages through the book, and the page itself offers sharing, downloads and the source credits. The home page shelf links to these readers. `/samples` is a different feature: the shelf of source stories a user picks from before starting a project.

## Sub-features

- `public-reader-open` opens the `Book reader` dialog at `/read/:id` on page 1, with a counter that reads "Page 1 · N pages".
- `public-paging` moves through pages with `Next page` / `Previous page` (in the dialog's footer, `contentinfo`) and the `Jump to page` slider.
- `public-view-modes` switches between the `SPREADS`, `FIT HEIGHT` and `ZOOM` toggles.
- `public-close` closes the reader with `Close reader`, revealing the book page (title, `Share book`, `Download this book` PDF/CBZ, source credits, back-page preview).
- `public-language` switches language with `Book language` when the book has stored translations.
- `public-samples-shelf` lists source stories at `/samples` (search box "Title, author, tag, or theme", tabs "All stories" / "Selected stories" / "Classic archive").

## How to get to it (user POV)

- Choose a cover on the signed-out home page `/` (links `/read/<id>`).
- Open a shared `/read/<id>` link, for example one copied with `Share book` or from the Book room's publication panel.
- Go to `/samples`, or choose the samples link on the home page, for the source-story shelf.

## Driving it with playwright-cli

Preconditions:

- `doctor.sh` exits 0. No sign-in is needed, so use the signed-out session `S=-s=canary-verify-public`.

- **Pick a book.** Run `curl -sS http://127.0.0.1:5173/api/public/books > "$EV/books.json"`. It is a JSON list of `{id, title, …}`, and seven books were listed on 2026-11-13. Note one `id` and its page count from `/api/public/books/<id>` (`pages`, `version`).
- **Open the reader.** Run `$PW $S open http://127.0.0.1:5173/read/<id>`, then `$PW $S snapshot --filename="$EV/read.aria.yml"`. The snapshot shows `heading "<title>"` and `dialog "Book reader"`, with `img "Page 1 — Page 1"` and a footer paragraph reading "Page 1 · N pages", where N matches the API. Save `$EV/read-p1.png`.
- **Page forward and back.** Run `$PW $S run-code 'async page => { await page.getByRole("contentinfo").getByRole("button", { name: "Next page" }).click(); }'`. The counter reads "Page 2 · N pages", the image alt reads "Page 2 — Page 2", and its `naturalWidth` is greater than 0. Save `$EV/read-p2.png`. `Previous page` returns to page 1.
- **Close the reader.** Choose `Close reader`. The book page shows `Share book`, `Download this book` with PDF and CBZ links (`/api/public/books/<id>/download/{pdf,cbz}`), and the `Back page preview` image.
- **Samples shelf.** Run `$PW $S goto http://127.0.0.1:5173/samples` and wait for the "Search stories" field before you take the snapshot. The page renders "Choose the world you want to draw" and a "N selected · M classics" count.

## Gotchas

- `/samples` is not the comic list. Its stories are inputs to a new project. Use `/api/public/books` and `/read/:id` for published comics.
- The reader dialog opens at once, and `Open the first page` exists only after it is closed. Do not wait for that button on load.
- `Next page` / `Previous page` appear twice: in the image overlay and in the footer. Scope to `contentinfo` (the footer) or the click is ambiguous.
- A snapshot taken right after `open` can be nearly empty while the lazy route loads. Wait for a known element first, using `run-code` with `locator.waitFor()`.
- Public books come from production Supabase. Only read them. Never publish or unpublish to set up this journey.
- `bin/cleanup.sh` closes `canary-verify-public` too.
