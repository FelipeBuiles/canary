# Claims policy

Use this policy when writing or reviewing public drafts. Canary paths below are relative to `..` from this directory, or `CANARY_ROOT` when set. Evidence was reviewed against lock `83b9d06af5e9698ab65db29461c3d57f6570fdf9` on 2026-10-27. The lock records source state, not approval to publish.

## Decide whether a claim is usable

1. Read the source and its status before copying a claim. Follow `docs/README.md:3-33`. Implementation and tests outrank configuration, current references, vocabulary, and proposals. Public copy does not override implementation.
2. Cite a ledger fact for every product claim. Use only `marketable: true` facts whose quotes, meaning, and `verifiedSources` hashes still match. A matching quote proves text exists, not that the statement is true or complete.
3. Treat `marketable: true` as permission to draft within this policy, not a quality guarantee, asset clearance, or human approval. Never cite internal-only facts in public draft frontmatter.
4. If sources disagree, omit the uncertain claim. Keep the contradiction and its evidence internal until the product owner reconciles it. Do not turn a plan, a benchmark target, or a provider-free test into a shipped capability.
5. Write every public artifact as `status: draft`. Only the human approves and posts it. Never use a sync or a passing check as approval.

## Do not make these claims

| Do not claim | Evidence and safe treatment |
|---|---|
| A full book for $25, a fixed page count per credit pack, or a first purchase that necessarily finishes an excerpt | `docs/proposals/pricing-and-margin.md:11-15,44-49` and `web/src/pages/ProductPage.tsx:28` reject fixed output quantities. Describe prepaid generation capacity and variable costs. |
| Standard is the most popular pack | `docs/proposals/pricing-and-margin.md:44-45` says there is no evidence. Use the pack's name only. |
| Free signup credits, free generations, an unbounded free chapter, or a guaranteed free first page | `showcase/marketing/copy-kit.md:8` bans free-generation copy. Cold Open remains unverified in `docs/proposals/cold-open-2026-10-26.md:3-18`. Do not infer a free offer from a test run or operator grant. |
| A guaranteed final price, production margin, free failed requests, or that a temporary hold is a final charge | `docs/proposals/pricing-and-margin.md:25-32` distinguishes usage, uncertain runtime configuration, holds, and failure billing. `PRODUCT.md:59-60` distinguishes estimates, usage, and charges. Use approximate action estimates, not cost guarantees. |
| A refund guarantee or unconditional non-refundability | `web/src/pages/legal/TermsPage.tsx:78-83` makes credits non-refundable except where law requires. Preserve that exception. |
| Copyright-safe, guaranteed copyright ownership, exclusive rights to generated images, or permission to adapt any purchased book | `web/src/pages/legal/TermsPage.tsx:35-64` limits the service license and disclaims ownership of generated output. Purely generated imagery may not be copyrightable. `web/src/pages/ProductPage.tsx:35` says owning a copy does not grant adaptation rights. |
| Identical faces on every page, perfect lettering, or guaranteed showcase quality | `web/src/pages/ProductPage.tsx:20,54` and `web/src/locales/en.json:3268` require human review and qualify continuity. Say references help reduce drift. |
| Every step waits for approval, or nothing moves until the author approves | `PRODUCT.md:22-28` and `web/src/lib/stations.ts:66-69` make adaptation and planning automatic. Describe the actual author checkpoints. |
| All lettering is editable or all illustrated text translates | `web/src/pages/ProductPage.tsx:21` distinguishes integrated and editable projects. `docs/reference/localization.md:59-77` excludes integrated or baked art and charges for missing translations. |
| Cold Open is publicly available, produces a page in under two minutes, or the Director has proven paid-provider behavior | Both proposals say implemented but not yet run against paid providers at `docs/proposals/cold-open-2026-10-26.md:3-18` and `docs/proposals/director-2026-10-27.md:3-21`. Keep targets and capabilities internal. Do not promise a launch date or say coming soon without a separately approved announcement. |
| A conversational book-wide Director, Reel export, an embeddable reader, affiliate rewards, or creator-loop launch dates | `docs/proposals/director-2026-10-27.md:9-24` rejects book-wide chat. The creator loop in `docs/proposals/showcase-and-growth-2026-09.md:85-95` is proposed, not evidence of shipped capabilities. |
| Sales lift, superiority over a named competitor without a like-for-like test, or an artist's name as a style label | `docs/proposals/showcase-and-growth-2026-09.md:35` bans these. Describe a medium, era, and mood instead, per `showcase/marketing/copy-kit.md:9`. |
| Specific generative model names, provider routing, or development funding arrangements | `showcase/marketing/copy-kit.md:8` and `docs/ops/landing-showcase-assets.json:5` exclude them. Say AI-assisted and explain the author's choices. |

## Handle documentation contradictions

### Station count and approval wording

The landing says five stations and lists Story, Look, Cast, Pages, and Book at `web/src/locales/en.json:3213-3229`. The product contract says four, and the app nests Cast under Look at `PRODUCT.md:22-28` and `web/src/lib/stations.ts:38-82`. The same landing sentence says nothing moves without approval, contrary to automatic Adapt and Plan.

Do not use a numerical station count in new public drafts. Keep both observed counts internal. You may describe confirmed user actions without counting stations, such as approving the brief, choosing a look and cast, reviewing pages, and exporting. Do not repeat the research report's advice to prefer five merely because the landing is public.

### Prices in copy

The draft copy kit bans prices and credits in all public copy at `showcase/marketing/copy-kit.md:3-8`. Current owned-web copy publishes pack prices, no subscription, and credit estimates at `web/src/pages/ProductPage.tsx:26-28` and `web/src/locales/en.json:3254-3260,3274`.

Use this conservative workspace rule until the owner reconciles the wording. No prices, credit quantities, free-generation offers, or model names in social, community, outreach, or ad creative. Owned-web drafts may cite current pack facts and explain approximate estimates, no subscription, and that purchased credits do not expire. Confirm prices against `novel_to_comic/src/novel_to_comic/server/routers/billing.py:25-30` and the checkout wording before approval. Pricing facts are marketable only within that owned-web scope. `approved-pricing-line` is an internal historical id, not an approval record.

### Inputs and limits

The source reader accepts TXT, Markdown, Word .docx, PDF, and EPUB at `novel_to_comic/src/novel_to_comic/input_limits.py:309-323`. Landing formats list only EPUB, PDF, and TXT at `web/src/locales/en.json:3177`. Keep new public format claims to those three until the upload path and public wording are confirmed. The extra reader formats remain internal evidence, not a planned feature claim.

Input defaults are environment-overridable at `novel_to_comic/src/novel_to_comic/input_limits.py:42-58`. Do not advertise unlimited uploads or infer deployed limits from defaults. The 50 MB setting computes 50 MiB of bytes, not 50 million bytes.

### Showcase records and films

The September strategy still lists The Terror on the shelf and future seasonal books at `docs/proposals/showcase-and-growth-2026-09.md:50-58`. Current shelf metadata and `showcase/books/README.md:9-28` show Astronomical replaced The Terror and The Monkey's Paw was added. Use current manifests and shelf metadata, not the proposed calendar.

The asset manifest lists a Poe hero loop, but its final `known_limits` entry still calls the hero loop Dungeon Crawler Carl art. Its `known_limits` also excludes Kaitlin pages 4 and 8, which the strategy's ad column does not exclude. See `docs/ops/landing-showcase-assets.json` under `assets` and `known_limits`, and `docs/proposals/showcase-and-growth-2026-09.md:39-41,51-55`.

Do not resolve this conflict by assuming the newer-looking label proves the pixels. Do not reuse a film, loop, or poster with uncertain provenance until its exact frames and source record have been checked. A landing link to a 66-second film is not rights clearance for that film. Never reuse files from `showcase/video/` in this workspace.

## Choose cleared creative assets

1. Source public creative only from `../showcase/books/` or `../web/public/marketing/`, as required by this workspace's `AGENTS.md`. A path allowlist is necessary but does not clear every file in it.
2. For a book page, read its current `book.json`. Use only its named `version` and listed pages. Check title, author, source credit, license URL, and the intended use. Preserve author and source credits even for public-domain or CC0 work. Some manifests lack license metadata. Corroborate those rights in the locked sources below rather than inventing a license field.
3. For a marketing derivative, trace the exact asset through `docs/ops/landing-showcase-assets.json` when recorded. Keep the declared provenance and check source and asset hashes when present. A record that points into `projects/` does not permit copying the working project. Use only the reviewed public derivative. Hold unrecorded or contradictory assets for rights review.
4. For Site-30's Janitor and Astronomical, include the work title, author, SCP Wiki source URL, CC BY-SA 3.0 license and URL, and the adaptation's share-alike notice. Preserve mandatory credit pages. Follow `docs/reference/sample-library.md:43-49` and each book's `source_credit`.
5. Inspect the chosen page or crop for gore, nudity, profanity, and third-party material. Apply the stricter restriction when records disagree. A strategy's ad-clearance column is an internal selection record, not a guarantee of platform acceptance or legal clearance.
6. Label team-made editions as showcase work, not customer work. Do not imply a testimonial or promise matching quality. See `web/src/locales/en.json:3185-3189` and `docs/ops/landing-showcase-assets.json:4`.

Use these selection limits before human review:

| Book | Rights evidence | Creative restriction |
|---|---|---|
| The Call of Cthulhu, H. P. Lovecraft | `docs/proposals/showcase-and-growth-2026-09.md:55` records public domain. Current page count is `web/src/lib/showcaseShelf.ts:15`. | The strategy lists all pages as ad candidates. Inspect the selected page and do not promise ad acceptance. |
| The Masque of the Red Death, Edgar Allan Poe | `docs/proposals/showcase-and-growth-2026-09.md:51` records public domain and woodblock edition. | Ad candidates are pages 3 through 12 only. Exclude pages 1, 2, and 13 through 24 for blood or bodies. |
| Kaitlin Out of Space, Krishan Coupland | `web/src/pages/ProductPage.tsx:54` identifies CC0 and links the source. | Exclude pages 10 and 15 from ads for undressing. Also exclude pages 4 and 8 from new creative under the asset manifest's known limits. |
| Elm and Keep, @strnglft | `docs/proposals/showcase-and-growth-2026-09.md:53` and `docs/ops/landing-showcase-assets.json` record CC0. | All pages still require review. The strategy explicitly says after review. |
| Site-30's Janitor, JanitorCakeworth | `showcase/books/04-site-30s-janitor-risograph/book.json:65-71` records CC BY-SA 3.0 and source URLs. | Use only risograph page 1 as an ad candidate. The strategy excludes page 2 for profanity and pages 3 onward for blood. The copy kit's pages 4 onward rule is less restrictive. Never use the gouache page 1 profanity panel in ads. |
| Astronomical, Sophia Light | `showcase/books/05-astronomical/book.json:138-144` records CC BY-SA 3.0. `showcase/books/README.md:9-13` distinguishes 20 story pages and a credit page. | No ad clearance was established in the reviewed sources. Hold ad use for review. |
| The Monkey's Paw, W. W. Jacobs | `showcase/books/README.md:22-28` records public domain, 1902, and 20 story pages. | No ad clearance was established in the reviewed sources. Hold ad use for review. |

Janitor restrictions come from `docs/proposals/showcase-and-growth-2026-09.md:54` and `showcase/marketing/copy-kit.md:12`. Rights to a source text do not automatically clear illustrations or unrelated assets. Check each derivative.

## Respect the copyright and generation boundaries

Never use manuscripts, generated pages, footage, or screenshots from `../samples/`, `../projects/`, or `../showcase/video/` in public material. Do not copy from retired books, launch kits, YouTube kits, or audit captures outside the two permitted creative roots. These exclusions apply even when a file is tracked or a source story is public domain.

Dungeon Crawler Carl and The Egg are explicitly out of public use at `docs/proposals/showcase-and-growth-2026-09.md:39-41`. The historical research report also flags third-party texts such as The Last Question, Nightmare at 20,000 Feet, The Flowers, and works or translations by García Márquez, Cortázar, and Kafka. That report is a warning, not rights clearance. Do not reuse those test inputs or their generated derivatives.

Do not claim that sample-library search results all carry adaptation rights. The curated 21-story shelf and the classic archive differ. `docs/reference/sample-library.md:14-20,22-31` requires readers to verify archive rights for their location and intended publication.

Canary is read-only. Do not run generation, redraws, translation, style proofs, provider checks, or other paid work to substantiate marketing. Record missing paid-provider evidence and request the owner's verification. Do not access credentials or change deployed configuration. Write a draft rather than publishing, purchasing ads, or contacting customers.
