# Public search rendering

Status: Current. Implemented anonymous HTML and client navigation contract.

Public marketing and legal pages ship as complete HTML generated from the same
React components used in the browser. They do not require a Node process at
request time. The signed-in application keeps the SPA and its authentication
and account-scoped caches.

## Build and delivery

The web build emits Vite assets and the SPA shell, a 1200×630 PNG brand card,
and eleven public documents in `dist/public/`. `public-pages.json` maps public
URLs to built files. The renderer uses `App` with an anonymous server auth
snapshot, the existing i18n provider, and the same route/Suspense boundaries as
hydration. Build rendering never subscribes to account auth.

Documents include their route stylesheet, critical font preloads, localized
content, canonical/social metadata, and truthful JSON-LD. The homepage starts
with the high-priority poster; video remains deferred. Its bootstrap includes
only verified curated story metadata. Reader and story bootstraps contain only
already-public fields or shipped, hash-verified licensed text. JSON escapes
HTML delimiters.

The client loads the current route and requested catalog before hydrating or
rendering, keeping the original content visible; if either fails it renders
client-side instead of leaving a static page. Public URL language does not
write the application preference, and the i18n provider is never remounted:
a language change keeps the current screen until its catalog is ready.

Restoring a session never remounts the page. Public queries (`short-stories`,
`public-book`) are hashed without an account; the first restored session binds
the startup query client in place, dropping only account-scoped entries. Later
account switches still replace the client and remount, with request-epoch
isolation. Browsers with a session carry a presentation-only `sw_signed_in`
cookie; for it, `/` serves the SPA shell (`Vary: Cookie`) so Library opens
without the homepage appearing first. It authorizes nothing. Server documents
for `/read`, `/samples` and 404s keep a crawler-readable `.server-intro`, hidden
under `@media (scripting: enabled)` so the app's own view is the first one seen.

`SPAStaticFiles` serves known public documents with HTML revalidation, immutable
fingerprinted assets, and short marketing caches. File aliases redirect to
public URLs. Recognized auth/private SPA deep links still work and return
`X-Robots-Tag: noindex, follow`. Unknown page URLs return HTTP 404 HTML and an
anonymous client 404 page. Missing assets and APIs keep their real errors.
WebP is served as `image/webp`.

## Inventory and metadata

The public inventory is `/`, `/es`, `/fr`, `/how-it-works`, `/pricing`,
`/guides/turn-a-novel-into-a-comic`, `/examples/kaitlin-out-of-space`, `/about`,
and the three existing legal pages. Product/editorial pages publish in English.
Only translated landing pages advertise reciprocal English/Spanish/French and
x-default hreflang.

The pricing table must agree with billing pack configuration; the built-page
test checks those independent contracts. Credits buy generation capacity,
not a fixed number of pages. The annotated example is a development
demonstration with its actual source, license and finished-reader link.

Stable Organization/WebSite/WebApplication IDs describe the product. Guide,
example, source-story and book markup uses visible public content. There are
no invented ratings, reviews, app-license offers or FAQ rich-result markup.
Client navigation replaces canonical, social, robots, alternates and JSON-LD
together; private/utility pages clear public schema.

Reader HTML includes synopsis, author, page count, previews, source/license
context when available, and workflow/library links. Curated source-story URLs
include complete verified text and attribution. See [public books](public-books.md)
for access checks, revocation, source rights and manual discovery boundaries.

The sitemap includes these pages, curated bundled stories, and validated
showcase books. It never enumerates private projects, uncurated owner
publications, unpublished versions, or the classic archive. Robots allows the
read-only public-book collection/resources while retaining the private API
exclusion. Robots is not an access-control mechanism.

Build/client canonicals target `https://scenewright.ink`. Reader HTML uses
`SCENEWRIGHT_PUBLIC_URL`, defaulting to that origin. Alternate-origin deployments
need a matching public build. `SCENEWRIGHT_APP_URL` separately controls exported
signup referrals and defaults to the working public origin.

## Verification and release

Build the frontend before artifact checks. `publicHydration.test.tsx` uses
production HTML to check hydration, DOM retention during auth restoration,
and language navigation. Routing/i18n tests cover signed-in Library language
and public 404 behavior. `test_public_site.py` checks initial content, metadata,
languages, styles/assets, card dimensions, billing-pack agreement and redirects.
`test_publications.py` checks escaping, source text, schema, consent and revocation;
`test_spa_static.py` checks status and cache policies.

Build/bundle checks do not establish deployed field Web Vitals or search
visibility. After the normal production release, recheck cookie-free HTML,
sitemap URLs, crawler resources, Search Console/Bing indexing and mobile
performance. Search/AI reporting and independent author evidence require
access or activity outside this repository.
