# Sample story library

**Status: Current, September 22, 2026.** The library combines a curated shelf
of complete, licensed source texts with a searchable snapshot of the former
Library of Short Stories catalog. It is separate from the finished comic-book
showcase in `showcase/books/`.

`novel_to_comic/src/novel_to_comic/sample_stories/catalog.json` owns the shelf's
editorial order, descriptions, tags, source links, license links, and SHA-256
hashes. The adjacent `.txt` files contain the real story text. `sample_library.py`
checks the hashes before listing or importing them. The package-data rule in
`novel_to_comic/pyproject.toml` ships the catalog and text files with the server.

The curated shelf currently has **21** stories: seven CC0 works by Krishan
Coupland, three CC0 Wanderverse works by Angie, @strnglft, and Sonya Mann, and
eleven SCP Wiki works under CC BY-SA 3.0. Each entry has a synopsis, tags, a
visual adaptation angle, source link, license link, and a content note where
appropriate. Some illustrated source pages are transcribed as text only; no
source artwork is bundled. See the [source audit](../research/2026-09-22-sample-story-expansion.md)
for first-party license evidence and excluded candidates.

`archive_catalog.json` holds **1,082** factual metadata records from the former
Library of Short Stories catalog, fetched on September 22, 2026. The snapshot
keeps titles, authors, codes, word counts, tags, and publication details
browseable even if that service is temporarily offline. It omits the site's
artwork and editorial blurbs. All classic stories appear in the same search,
tag filters, and sort results as curated stories; the collection filter is
optional. Their full text is fetched from the service only when opened or
imported. The archive does not provide a uniform adaptation license: the UI
does not label these works as licensed and tells readers to verify rights for
their location and intended publication.

`GET /api/projects/short-stories` returns the combined catalog;
`GET /api/projects/short-stories/{code}` returns bundled text or fetches an
archive story with the existing remote size/decompression limits.
`POST /api/projects/import-story` copies a bundled source locally or downloads
an archive story and saves available provenance in `sample_source.json`,
including the normalized source-text hash. No generation starts at import.
Library of Short Stories codes and reader URLs still work directly; unrelated
URLs are rejected. Users can also upload their own manuscripts.

For SCP imports, `sample_source.json` records the original article, author,
source URL, and CC BY-SA 3.0 license. Finish appends a visible source/license
page to PDF and CBZ exports. Public publication appends that page to its reader
and downloads, and exposes the citation as accessible text on the public book
page. The SCP Wiki [licensing guide](https://scp-wiki.wikidot.com/licensing-guide)
requires attribution to the specific author and wiki and a share-alike license
for adaptations. The [image policy](https://scp-wiki.wikidot.com/image-use-policy)
applies separately; source images were not imported.

To add a curated story, confirm the license on the rightsholder's source page
and that commercial adaptation is allowed. Add its complete plain text,
record the source and license URLs, and hash the bytes after any newline
normalization. Choose tags and a description, then run the short-story import
test. For share-alike sources, preserve mandatory credit in export and public
publication. Do not bundle images merely because the text is licensed.
