# Scenewright SEO and GEO review

Status: Historical audit snapshot, observed 2026-10-06 in America/Toronto. Recommendations below were Proposed at audit time. The [implementation follow-up](2026-10-07-scenewright-seo-geo-implementation.md) records subsequent local changes and verification.

Scenewright has working discovery infrastructure, but its strongest product information and visual evidence are difficult for crawlers to retrieve. The first investment should be complete public HTML and access to public reader resources. Product explanations, annotated examples, and a clearer brand identity should follow. GEO here means visibility and accurate citation in generative search and AI answers.

## Scope and evidence

The review fetched the live homepage, robots.txt, XML sitemap, all 29 sitemap URLs, a legal page, signup, an intentionally unknown route, an unavailable reader, and selected asset headers. It checked a real ranged GET of a public comic image and an OAI-SearchBot user-agent request. Repository code was inspected to identify implementation points; key landing statements were also confirmed in the deployed public language bundle. A rendered public sample was inspected in the browser.

The browser already had an authenticated session, so its root showed the Library. Anonymous homepage findings come from requests without cookies and the deployed HTML, rather than that personalized screen. No account state was changed. The PageSpeed API returned HTTP 429 for exhausted service quota. Search Console, Bing Webmaster Tools, production analytics, backlink inventories, and actual responses from separate AI products were not inspected.

The machine-readable [crawl evidence](2026-10-06-scenewright-seo-crawl.json) contains public URLs and structural observations, with page copy omitted. No application changes, deployments, paid generation, or development-server operations were performed.

### What already works

- HTTP redirects to HTTPS with 308.
- [robots.txt](https://scenewright.ink/robots.txt) returns plain text and identifies the sitemap.
- [sitemap.xml](https://scenewright.ink/sitemap.xml) returns real XML with 29 URLs: the homepage, sample shelf, six curated comics, and 21 curated source stories. All 29 returned 200 and a matching canonical URL.
- Samples and public books have unique server-generated titles, descriptions, and brief introductions. An unavailable reader returned 404 and `X-Robots-Tag: noindex`.
- The landing copy explains author control, inputs and exports, credits, and continuity limitations. It already has six FAQ answers; pricing information is present in the deployed copy.
- The rendered sample preserves author/source and license links. Marketing components use descriptive image text, dimensions, WebP assets, and lazy loading for lower-page illustrations.
- Acquisition-source, domain-referrer, and signup tracking are already implemented in [telemetry.ts](../../web/src/telemetry.ts). Reporting should build on these contracts.

These results establish successful retrieval and consistent metadata. They do not establish indexing, rankings, conversions, or AI citations.

## Prioritized gaps and proposed fixes

P0 means resolve first because it obstructs retrieval of core product information or evidence. P1 means the next acquisition work. P2 means subsequent improvements or work contingent on measurement. Effort is relative: S is a focused change, M crosses rendering/content boundaries, and L requires substantial editorial or localization work.

| Priority | Gap and verified evidence | Proposed fix | Effort |
| --- | --- | --- | --- |
| P0 | The anonymous homepage returns an empty `<div id="root"></div>`: no body text, headings, or links before JavaScript. The web search fetch also extracted zero lines. | Render the complete public landing content in the initial HTML: product definition, workflow, examples, pricing explanation, FAQs, and navigation. Keep the content consistent when JavaScript starts. | M |
| P0 | The blanket `Disallow: /api/` also excludes public book JSON and comic images. All six comic social-image URLs are under this prefix. A representative image works with GET, but robots rules disallow it. | Add narrowly scoped exceptions for the read-only public reader metadata and image resources needed for rendering, or serve approved public assets through a crawlable public namespace. Keep private APIs excluded and existing access checks authoritative. | S–M |
| P1 | `/legal/terms` returns the homepage title, description, canonical, and empty body. `/signup` also inherits homepage metadata. An invented URL returns 200 and the homepage canonical. | Give legal pages full initial HTML and unique self-canonicals. Give auth utility pages explicit noindex. Restrict successful SPA fallback to recognized routes, and return a genuine 404 for unknown URLs while preserving valid app deep links. | M |
| P1 | The discovery inventory is dominated by source stories and comics. The current router defines no dedicated pricing, product workflow, guide, or About page. | Publish a small set of useful product pages linked from the homepage and relevant examples. Add them to the curated sitemap after publication. Focus first on authors adapting existing prose. | M–L |
| P1 | The homepage title describes the first-scene promise but omits the product category. | Introduce the category in the title and a clear descriptive heading/supporting line. Keep the first-scene positioning and existing author control. Suggested copy appears below. | S |
| P1 | Initial comic HTML contains only 30–43 words; source-story detail HTML contains 14–29. The comic HTML has no inline image elements or links. | Make each curated example useful as evidence about adaptation: source context, preview images, adaptation decisions, author controls, limitations, and a link to the complete reader. Make this information visible in initial HTML and retain it after client navigation. | M–L |
| P1 | Sampled exact-domain searches returned no results. A broader brand search surfaced the unrelated Unreal Engine product at scenewright.dev. The current public navigation lacks an About page. | Establish a consistent definition of Scenewright at scenewright.ink, an About page with verified operator/contact details, and links to verified official profiles. Seek authentic author case studies and independent reviews. Confirm actual indexing in Search Console before attributing the search result gap to a specific cause. | M |
| P2 | No JSON-LD appeared in any of the 29 initial HTML responses or the rendered sample inspected. | Add truthful Organization and WebSite data on the homepage, WebApplication data for the product, and appropriate CreativeWork/Book data for curated examples. Reuse stable entity IDs and public fields. Validate the result. | S–M |
| P2 | Language selection changes client state on the same URLs. Initial HTML is English, with no language alternates. | If Spanish and French organic acquisition are priorities, give their public landing pages stable URLs, localized initial content and metadata, reciprocal hreflang, and matching canonicals. Preserve the existing application language preference separately. | L |
| P2 | The initial document preloads a language chunk whose uncompressed response length is 821,634 bytes. The hero video is 2,503,000 bytes and uses autoplay plus `preload="auto"`. | Measure mobile performance, load public-page translations separately from the complete application catalogs, and defer the video until the poster and essential content are ready. Preserve reduced-motion behavior and image dimensions. | M |
| P2 | The hero WebP poster is served as `application/octet-stream`. Homepage social sharing uses a 512×512 brand mark; sample initial HTML has no social image. | Serve WebP with `image/webp`. Create a dedicated comic-based landscape social card and explicit sample cards, with appropriate image descriptions and dimensions. | S |

### Rendering and crawl access

Google can execute JavaScript, so the empty initial response is not proof that the homepage is unindexable. It does impose a rendering dependency and gives fetchers that do not render JavaScript almost no content. Google's [JavaScript SEO guidance](https://developers.google.com/search/docs/crawling-indexing/javascript/javascript-seo-basics) explains this distinction.

An incremental implementation can reuse the public-document delivery work in [publications.py](../../novel_to_comic/src/novel_to_comic/server/routers/publications.py) and the route ownership in [app.py](../../novel_to_comic/src/novel_to_comic/server/app.py). Generate or render public markup from the same content that the visible page uses. Ensure bootstrapping preserves that content until the application can render the appropriate destination; authenticated users must retain the current Library behavior. No framework migration is necessary to begin this work.

For reader resources, the live [Cthulhu reader](https://scenewright.ink/read/d1cb0ec790244ce6849974daa586146b) sets an image under `/api/public/books/…/pages/1`, which the current robots rule excludes. The reader also fetches its book JSON from `/api/public/books/{id}`. The exception must cover the resources required by the reader, not only its social image. Verify the exact path rules with a robots parser and Google's rendered-page inspection. See Google's [robots specification](https://developers.google.com/crawling/docs/robots-txt/robots-txt-spec).

Keep existing discovery curation: private projects and uncurated owner publications must not be automatically enumerated. Existing sample query URLs already have matching canonicals; their query-string shape does not require migration. Legal pages need their own canonicals because their content differs from the homepage; Google's [canonical guidance](https://developers.google.com/search/docs/crawling-indexing/consolidate-duplicate-urls) supports consolidation of duplicate versions, rather than unrelated pages.

### Proposed homepage copy

Title:

```text
AI Comic Studio for Authors | Scenewright
```

Descriptive H1, or a prominent sentence beside the existing brand line:

```text
Turn a scene from your novel into a comic.
```

Meta description:

```text
Turn an EPUB, PDF, or TXT excerpt into comic pages with Scenewright. Direct the style and cast, review each page, and export PDF or CBZ.
```

A useful visible product definition:

> Scenewright is an AI-assisted comic studio for authors adapting existing stories. Upload an EPUB, PDF, or TXT excerpt, approve the story brief, style, and cast, then review complete comic pages and export a PDF or CBZ edition.

This is proposed editorial copy grounded in current product behavior. Input support, credit prices, and export support must stay synchronized with the application. Claims about full manuscripts should continue recommending a small first project.

### Proposed public content

| Page | Reader question / search intent | Required substance |
| --- | --- | --- |
| `/how-it-works` | How does AI turn a manuscript into comic pages? | Inputs, creative checkpoints, complete-page production, review/correction options, and exports, illustrated with an actual example. |
| `/pricing` | What does an AI comic adaptation cost? | Current credit packs, the starting price stated in deployed copy, no-subscription policy, factors affecting consumption, and real estimates expressed as `~N credits`. Explain what revisions can cost. |
| An annotated example, linked to its existing `/read/…` URL | Can I see a complete result and understand its limitations? | Source and license, a small preview, adaptation decisions, approved references where public, actual revisions, and the complete reader. Clearly label development examples. |
| `/guides/turn-a-novel-into-a-comic` | How should an author prepare a scene for visual adaptation? | A practical preparation checklist and a first-hand demonstration of what was compressed, retained, or corrected. |
| `/about` | Who built Scenewright, and which product is this? | Verified operator identity, product purpose, support contact, official domain and profiles, and editorial accountability. |

These are proposed intents, not keyword-volume estimates. A generic “AI comic generator” search has many established product pages; the existing-manuscript workflow provides a more focused starting point. Additional pages about character continuity or lettering should follow demonstrated reader/search demand and distinct content, rather than duplicating the same product explanation.

The existing FAQ already addresses starting inputs, control, continuity, ownership, AI use, and credits. Render those answers in HTML first. Extend answers where the actual policy supports them: manuscript handling, third-party providers, retention/deletion, and how dialogue correction differs between editable and integrated lettering. Preserve the current continuity caveat. Do not promise uniform free text edits across all editions.

## GEO recommendations

The most useful GEO work is to make verified product facts and first-hand examples easy to find, understand, and cite. Useful questions include which authors the product serves, how it handles existing prose, what continuity controls exist, what can be corrected, what export formats are available, and how credits work. Present answers for readers and link them to visible evidence.

1. **Provide evidence behind product claims.** Pair the brief description of continuity with an approved-reference example and pages that show both successes and revisions. Pair pricing explanations with dated, reproducible production estimates, if available. Public stories alone do not explain the tool's adaptation choices.
2. **Disambiguate the brand.** Consistent domain, category, operator details, official-profile links, and Organization data can reduce confusion with the unrelated `.dev` product. Google's [Organization guidance](https://developers.google.com/search/docs/appearance/structured-data/organization) explicitly covers entity disambiguation.
3. **Keep search-crawler access and training choices separate.** The current wildcard robots group allows OAI-SearchBot on public page URLs. The user-agent probe returned 200, although this does not establish access from the crawler's actual IPs. OpenAI documents separate roles for [OAI-SearchBot and GPTBot](https://developers.openai.com/api/docs/bots). A training-policy choice does not require opting out of search visibility. Inspect verified crawler requests in edge logs if access problems remain after fixing public resource rules.
4. **Check Google's inclusion setting.** Search Console now exposes Settings → Search generative AI, with inclusion as the default and inheritance possible. The site's actual setting was not inspected. Verify it rather than assume it is disabled. See the [Search generative AI control](https://support.google.com/webmasters/answer/16908024).
5. **Earn independent evidence.** Author interviews, published adaptations, and independent reviews can make the product easier to evaluate. Publish real work with permission and clear attribution. The sampled search gap does not establish that Scenewright has no backlinks or independent mentions; a separate inventory is needed.

Schema should describe facts rather than manufacture eligibility. For example, a credit-pack starting price is not automatically the purchase price of an application license. Google’s [software-app rich result documentation](https://developers.google.com/search/docs/appearance/structured-data/software-app) also requires qualifying review/rating information; do not invent it to complete the schema.

`/llms.txt` returned 404. Its absence is a low-priority observation. Google's current [AI optimization guide](https://developers.google.com/search/docs/fundamentals/ai-optimization-guide) says it does not use llms.txt for visibility or rankings, and no special AI schema is required. An optional file can summarize verified facts and link to authoritative pages for other consumers, provided it stays current. It should follow the retrieval and content fixes.

Keep the useful FAQ content without building a Google FAQ-rich-result project: Google’s [documentation changelog](https://developers.google.com/search/updates) states that the FAQ rich result was deprecated in May 2026. Visible answers still help readers.

## Measurement and verification

### Establish the baseline

- In Search Console, inspect the homepage, one sample, and one public reader. Record indexing status, Google-selected canonical, rendered content, and blocked resources; submit the existing sitemap if it is not already submitted. These account states are unknown from this review.
- Record branded and relevant non-branded impressions/clicks in the standard performance report. Check the [Generative AI performance report](https://support.google.com/webmasters/answer/16984139) for AI Overviews/AI Mode impressions; Google notes that it may be absent until enough impressions exist.
- In Bing Webmaster Tools, use the [AI Performance dashboard](https://blogs.bing.com/webmaster/2026/2/Introducing-AI-Performance-in-Bing-Webmaster-Tools-Public-Preview/) for supported Microsoft AI citation activity and cited URLs. A citation count is not a traffic or ranking measure.
- Use the existing acquisition source/referring domain to break out search and identifiable AI referrals, then follow account creation and completed export outcomes. Add only bounded public landing-page identifiers if page-level acquisition reporting requires them; preserve the telemetry privacy contract. A missing referrer does not prove direct discovery, and referral visits do not count all AI mentions.
- Run a mobile performance assessment once PageSpeed is available. Record measured results before selecting a performance sprint. The asset sizes in this audit are uncompressed response lengths, not measured transfer totals or Core Web Vitals failures.

### Acceptance criteria for implementation

| Change | Verification |
| --- | --- |
| Public rendering | A cookie-free GET includes the product definition, meaningful heading, current pricing explanation, FAQ answers, and real navigation links. Visible content remains consistent after JavaScript boot. |
| Reader crawl access | Rules permit required public metadata/images and continue to exclude private APIs. Public image GET works; unpublished/private content stays unavailable. Search Console renders the example successfully. |
| Metadata and errors | Public legal pages have unique titles and self-canonicals. Auth pages return explicit noindex. Unknown routes return 404. Valid client routes and unavailable-reader behavior remain intact. |
| Example content and schema | The initial response includes the public explanation and preview. Source/license attribution survives. JSON-LD validates and accurately reflects visible fields. No new private content enters discovery. |
| Localization | Each chosen language URL serves that language before JavaScript, with localized metadata, reciprocal hreflang, and a matching canonical. |
| Outcome reporting | Indexing, organic visits, AI impressions/citations, referred signups, and export outcomes remain distinct measures. |

For a later AI visibility check, use a fixed set of prompts across ChatGPT search, Google AI search, Bing/Copilot, and Perplexity. Examples: tools for adapting an existing novel excerpt; options with author approval and PDF/CBZ export; Scenewright's credit model; and how it handles continuity. Record the date, exact prompt, system, citations, and factual errors. The baseline has not been run in this review. Repeat after recrawling and content publication; individual answers are variable.

## Suggested implementation order

1. Complete initial public HTML and correct reader resource crawl rules.
2. Fix legal metadata, utility-page noindex, and unknown-route status handling; update homepage category copy.
3. Publish the workflow and pricing pages plus one annotated adaptation example; link them from the rendered homepage.
4. Add verified About/entity data, then establish search and AI visibility baselines using existing conversion tracking.
5. Choose localization, performance, and additional editorial work based on observed demand and measurements.

A secondary origin check found that `app.scenewright.ink` did not resolve during the audit. The repository still uses it as the default `SCENEWRIGHT_APP_URL` for exported book referrals, while inspected browser CTAs use relative signup links. Verify the actual deployment value and an exported referral/QR destination before concluding that exports contain broken links.
