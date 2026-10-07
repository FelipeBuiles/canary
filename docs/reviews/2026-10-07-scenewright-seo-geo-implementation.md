# Scenewright SEO and GEO implementation

Status: Historical implementation and local verification snapshot, 2026-10-07.
Production release and subsequent search/field measurements are not included.

This follows the [live audit](2026-10-06-scenewright-seo-geo-review.md). Work was
rebased onto local `main`, including Web Vitals commit `5ba1130e`, without
conflicts. The implementation is on `codex/scenewright-seo-geo-2026-10-06` in
the shared checkout.

## Applied changes

- Complete HTML for eleven React marketing/legal pages, with hydration from
  the same application tree. The public page stays visible while auth restores;
  signed-in `/` still becomes Library using the stored application language.
- Stable English `/`, Spanish `/es`, and French `/fr` landing URLs, localized
  initial copy and metadata, reciprocal hreflang and self-canonicals. Public
  language selection does not overwrite application preferences.
- Workflow, pricing, novel-to-comic guide, About, and annotated Kaitlin example
  pages, linked from public navigation. The example identifies the real source,
  CC0 license and finished comic, with clear development-example limitations.
- Complete verified curated source text and attribution in initial story HTML;
  reader synopsis, author, page count, three preview images and workflow/source
  links. Public bootstrap data avoids empty loading states for these resources.
- Truthful Organization, WebSite, WebApplication, Article, CreativeWork and Book
  structured data. Canonical/social/robots/schema updates are coordinated across
  client navigation. No invented reviews, ratings or app-price offers.
- Narrow crawler exceptions for the public-book collection and reader resources;
  private API/app exclusions, opt-in publication and manual curation remain.
- Unique legal metadata and complete legal HTML; noindex for auth/private URLs;
  real 404s for unknown URLs and preserved valid app deep links.
- A 1200×630 PNG social card, correct WebP MIME, and export referral defaults
  pointing to `https://scenewright.ink` instead of the unresolved app subdomain.

The rebased font preloads, poster-first/deferred video, responsive previews,
locale splitting, idle telemetry, lazy editor and immutable caching remain.
See [public search rendering](../reference/public-search.md) for the current
implementation contract.

## Local verification

The frontend builds eleven complete public documents. Startup JavaScript is
236.7 KB gzip across ten initial scripts, below the existing 300 KB budget and
the rebased report’s 237.8 KB baseline. These are build measurements, not
post-deployment LCP/INP/CLS results.

The final full frontend run passed 1,015 tests across 133 files. The
publication/static/public-site run passed 70 backend checks; the thirteen built
HTML checks were also rechecked after the final page changes. Build, lint,
generated-reference update and documentation reliability checks passed.
Production English/Spanish/French landing, pricing and terms HTML is hydrated
in tests: the original heading node is
retained while auth is pending, with no hydration warnings or recoverable
errors. Built-page checks verify metadata, language, stylesheet/asset delivery,
social-card dimensions, billing pack agreement, escaping, cache policy,
404/noindex behavior, publication consent and revocation.

Build verification used public test auth configuration; release builds must use
the normal production build arguments. No development server was started,
production deployed, paid generation submitted, or external outreach sent.

## Release follow-ups

After the normal release, crawl cookie-free production URLs and submit or
recheck the sitemap in Search Console and Bing Webmaster Tools. Verify indexing,
search/AI visibility and mobile lab/field Web Vitals with those accounts.
Confirm the deployed `SCENEWRIGHT_APP_URL` and public origin match the working
site; changing defaults does not override an explicitly configured environment.

Verified operator/profile links, authentic customer case studies and independent
mentions require additional real evidence. The About page uses the established
product identity and contact addresses without inventing a company biography.
Broader Spanish/French editorial localization remains separate from the three
translated landing pages. Search/training policies are preserved; no speculative
GEO control files or FAQ rich-result markup were introduced.
