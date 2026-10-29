# Canary → Scenewright marketing knowledge map

Audited 2026-10-27 against `/Users/jbuiles/Code/canary` (GitHub `FelipeBuiles/canary`),
HEAD `83b9d06a` ("director, runware provider", 2026-10-27). Read-only; nothing in canary
was changed. Paths below are relative to the canary root unless stated.

Legend: **CT** = current truth, **PLAN** = plan/aspirational, **INT** = internal-only.

---

## 0. Corrections to the brief, and conflicts found

- "Living Ink" is the **UI design system's** creative north star (`DESIGN.md:4`, `PRODUCT.md:68`).
  The logo/identity package is named **"Panel Frame S"** (`web/brand-system/README.md:1`).
- `web/brand-system/` holds **no CSS design tokens**. The tokens live in Tailwind v4
  `@theme` in `web/src/index.css:125-160`. brand-system holds the logo geometry and palette
  (`web/brand-system/src/geometry.ts:1-9`). See §3.
- `docs/reference/models.md` covers Pydantic data models, not AI models (`docs/reference/models.md:3`).
  AI model defaults are in `docs/reference/account-model-settings.md:25-47`.
- **Station count conflict.** `PRODUCT.md:21-22` and `web/src/lib/stations.ts:40,50,61,73`
  define **four** stations (Story, Look, Pages, Book). The live landing page says
  **"Five stations"** and lists Story / Look / Cast / Pages / Book
  (`web/src/locales/en.json:3213-3229`; commit `9fc1165b`, "…the five stations").
  Marketing should copy the landing (five steps). Treat the four-station `PRODUCT.md` as the
  internal model.
- **"Nothing moves on until you approve it"** (`en.json:3213`) is looser than the product contract:
  Adapt and Plan run automatically and never block (`PRODUCT.md:23-25,41-43`). Do not strengthen this claim.
- **Input formats are understated.** Copy says "EPUB, PDF or TXT in" (`en.json:3177`,
  `web/src/lib/publicPages.ts:15`). The code also accepts `.docx`, `.md`, `.markdown`
  (`novel_to_comic/src/novel_to_comic/server/routers/projects.py:283`). `PRODUCT.md:12` lists only .txt/.epub/.pdf.
- **Price rule conflict.** The social copy-kit rule says "No prices, credits, free generations or model
  names in any public copy" (`showcase/marketing/copy-kit.md:8`). The live landing shows "Packs start at US$12"
  (`en.json:3258`), and `/pricing` meta mentions US$12 (`publicPages.ts:19`). Working rule: prices may appear on
  owned web pages but not in social/ad creative.

---

## 1. Source-of-truth docs

### Policy (the governing rule)
- `docs/README.md:3-13` defines the status labels: Current / Historical / Proposed / Superseded. Unlabelled docs
  "must not make claims that conflict with executable code or tests".
- `docs/README.md:15-24` sets the source hierarchy: (1) code and tests > (2) checked-in config and fixtures >
  (3) `docs/reference/` > (4) `CONTEXT.md` (vocabulary only) > (5) proposals, plans, handoffs.
- `docs/README.md:30-33` sets the defaults: `docs/proposals/` = Proposed; dated `docs/plans/`, `docs/reviews/`,
  and `docs/handoffs/` = Historical.
- ADR 0002 records the same decision (`docs/adr/0002-documentation-source-of-truth.md`).
- There is **no CHANGELOG or release-notes file** anywhere in the repo. There are 0 git tags (see §7).

### Classification
| Path | Class | Notes |
|---|---|---|
| `PRODUCT.md` (122 lines) | **CT** (positioning, users, brand) | Users, purpose, positioning, constraints, brand commitments, anti-references. Best single marketing source. |
| `CONTEXT.md` (297 lines) | CT, **vocabulary only** | Domain glossary; "intentionally implementation-free" (`CONTEXT.md:3-5`). Use it for consistent terms, not for claims. Its `## Historical terms` (`:269`) lists terms to avoid. |
| `DESIGN.md` (179 lines) | CT for visuals; **not a source of claims** (`PRODUCT.md:96-97`) | Living Ink system: colors, type, do/don't. |
| `AGENTS.md`, `CLAUDE.md` | INT | Agent workflow. |
| `docs/README.md` | CT (navigation and policy) | Lists which docs are Current vs Active future work. |
| `docs/reference/*.md` (25) | **CT** | Most are labelled Current. Marketing-relevant: `localization.md`, `public-books.md`, `sample-library.md`, `observability.md`, `account-model-settings.md`, `stage-contracts.md`, `public-search.md`. Ops-only: `bedrock.md`, `vertex-ai.md`, `ci-runners.md`, `gateway-refresh.md`, `job-queue.md`, `textract-ocr.md`, `crop-ocr-experiment.md`, `mock-model-replay.md`, `codex-dev-capabilities.md`, `dependencies.md`, `backend-tests.md`, `config-fields.md`, `tester-tracker.md`, `agent-context.md`. |
| `docs/adr/0001-0024` (20 files; 0017-0020 absent) | CT (durable decisions) | Product-shaping ADRs: 0008 eight-stage pipeline, 0013 complete-page generation only, 0015 page review by exception, 0021 hybrid lettering, 0022 project lettering choice, 0023 series parts and Story Bible, 0024 part sequences and Book Map. |
| `docs/proposals/*.md` (23) | **PLAN** | `cold-open-2026-10-26.md` and `director-2026-10-27.md` are "Implemented… not yet run against paid providers" (`docs/README.md:72-80`). They are code-true but **not yet shippable as claims**. `pricing-and-margin.md` mixes code-backed facts with proposed policy (`:3-7`). `branding-and-marketing.md` and `first-scene-campaign.md` are **Superseded** by `showcase-and-growth-2026-09.md` (`:3` in each). |
| `docs/research/*` (21) | PLAN / historical evidence | Market research and style quality. Useful background, not claims. |
| `docs/plans/`, `docs/handoffs/`, `docs/reviews/` (582 files) | Historical / INT | Exclude. |
| `docs/ops/*` | INT, with a few marketing-adjacent files | `landing-showcase-assets.json`, `landing-development-samples.json`, `astronomical-community-posts.md`, `monkeys-paw-community-posts.md`, `tester-recruitment-2026-10.md`, `launch-scorecard-template.json`, `abuse-dmca.md`, `billing-refunds.md`. |
| `docs/migrations/`, `docs/sql/`, `docs/supabase-schema.sql`, `docs/exports/` | INT | `docs/exports` holds only a Cthulhu deep-research zip. |
| `docs/startup-application-package.md` | INT (pitch draft) | Review before reuse. |
| `docs/novel-to-comic-pipeline.md`, `docs/deploy.md` | INT / technical | |
| `posthog-self-driving-report.md` | INT | PostHog setup record (§5). |
| `showcase/marketing/copy-kit.md` | PLAN ("Draft, September 26, 2026", `:3`) | House rules for social copy. Read these. |
| `showcase/audit.md`, `showcase/video/EDIT*.md` | INT / historical | Shot audits and film edits. |
| `.impeccable/surfaces/*.md` | INT design briefs | e.g. `launch-landing.md` (Persuade mode). Useful for voice. |
| `web/src/locales/{en,es,fr}.json` (`landing.*`, 129 keys) | **CT shipped copy** | The approved, live landing copy. |
| `web/src/lib/publicPages.ts` | **CT** | SEO titles and descriptions for every public route. |
| `web/src/pages/ProductPage.tsx`, `legal/*.tsx` | **CT** | English copy for product, guide, and legal pages, inline in TSX. |

### Proposed sync manifest
```yaml
include:
  - PRODUCT.md
  - CONTEXT.md
  - DESIGN.md
  - docs/README.md
  - docs/adr/*.md
  - docs/reference/localization.md
  - docs/reference/public-books.md
  - docs/reference/public-search.md
  - docs/reference/sample-library.md
  - docs/reference/stage-contracts.md
  - docs/reference/observability.md          # event contract (§5)
  - docs/reference/account-model-settings.md # internal-only facts; never quote
  - docs/proposals/pricing-and-margin.md     # code-backed package table + approved copy line
  - docs/proposals/showcase-and-growth-2026-09.md
  - docs/proposals/cold-open-2026-10-26.md   # tag as "implemented, unverified"
  - docs/proposals/director-2026-10-27.md    # tag as "implemented, unverified"
  - docs/ops/landing-showcase-assets.json
  - docs/ops/*-community-posts.md
  - showcase/marketing/copy-kit.md
  - showcase/books/README.md
  - showcase/books/*/book.json
  - web/src/locales/{en,es,fr}.json          # filter to landing.* keys
  - web/src/locales/languages.ts
  - web/src/lib/publicPages.ts
  - web/src/lib/showcaseShelf.ts
  - web/src/lib/stations.ts
  - web/src/pages/ProductPage.tsx
  - web/src/pages/landingCopy.ts
  - web/src/pages/legal/*.tsx
  - web/src/index.css                        # @theme tokens only
  - web/brand-system/src/geometry.ts
  - web/brand-system/README.md
  - novel_to_comic/src/novel_to_comic/server/routers/billing.py   # packages (lines ~20-35)
  - novel_to_comic/src/novel_to_comic/input_limits.py
  - novel_to_comic/src/novel_to_comic/server/product_events.py
exclude:
  - docs/reviews/**
  - docs/handoffs/**
  - docs/plans/**
  - docs/exports/**
  - docs/migrations/**
  - docs/sql/**
  - docs/supabase-schema.sql
  - docs/research/the-call-of-cthulhu-*/**
  - docs/proposals/branding-and-marketing.md   # superseded
  - docs/proposals/first-scene-campaign.md     # superseded
  - docs/proposals/scenewright-prelaunch-acquisition-2026-07-18.html
  - docs/ops/{secret-delivery,backup-restore,host-maintenance,lightsail-ci,security-incident,crash-recovery*}.md
  - AGENTS.md
  - CLAUDE.md
  - .env*
  - projects/**              # gitignored, 6.9 GB, contains copyrighted sources
  - samples/**               # copyrighted texts (§6)
  - showcase/video/**        # node_modules and a copyrighted Carl footage risk
  - "**/node_modules/**"
  - .claude/worktrees/**     # stale duplicate copies of PRODUCT/DESIGN
```
The sync should record each file's git blob SHA. It should also tag files under `docs/proposals/` as PLAN unless
`docs/README.md` lists them under "Current contracts".

---

## 2. Hard product facts

### Pipeline and stations
- 8 backend stages: `extract → brief → style → cast → adapt → plan → draw → finish`, each resumable
  (`PRODUCT.md:18-19,37-38`; ADR 0008).
- The UI groups the stages into stations (`web/src/lib/stations.ts`):
  - story (`:40`): brief = extract + brief, gated (`:46`)
  - look (`:50`): style gated (`:56`), cast gated (`:57`)
  - pages (`:61`): adapt auto (`:67`), plan auto (`:68`), plus draw
  - book (`:73`)
- Author decision points: approve the story brief, choose the look and cast, review complete pages,
  and finish the edition (`PRODUCT.md:21-23`). Adapt and Plan "auto-run and stay inspectable but never block"
  (`PRODUCT.md:23-25`).
- Draw produces **complete, lettered pages**. Corrections are complete-page revisions, and pages are
  accepted by default unless the author flags an issue (`PRODUCT.md:44-45`; ADR 0013, ADR 0015).
- Every station ends in one approval bar with a plain-language next step and `~N credits` (`PRODUCT.md:25-26`).
- Marketing wording of the five steps (`en.json:3215-3229`): Story "Approve the brief"; Look "Choose the look"
  (describe it, show a reference, or ask for six directions); Cast "Meet the cast" (character sheets and location
  plates keep faces steady); Pages "Review every page" (drawn and lettered; ask for changes in plain words;
  redraw only what misses); Book "Export and share" (PDF/CBZ, or publish with a link).
- Newer features are **code-true but unverified with paid providers. Do not market them yet:**
  - **Cold Open**: one Canary-paid page of the opening in three looks during Extract. Target time to the first
    page of the author's own story is under 2 minutes (`docs/proposals/cold-open-2026-10-26.md:3-18`).
  - **Director**: page notes carry through to every page they touch (`docs/README.md:76-80`).
- Series parts, the Story Bible, and the Book Map exist as ADRs 0023 and 0024. The landing names the
  "Story Bible" (`en.json:3248`).
- Public books: the owner can publish to a public reader at `/read/:id`, with share attribution and an optional
  export back page (`docs/README.md:51-52`; `docs/reference/public-books.md`).

### Pricing and credits (code)
- Packages, in `novel_to_comic/src/novel_to_comic/server/routers/billing.py:26-29` and mirrored in
  `server/checkout_receipts.py:19-22`:

  | Package | Price | Credits | Credits per $ |
  |---|---:|---:|---:|
  | Starter | $12 | 1,200 | 100 |
  | Standard | $30 | 3,000 | 100 |
  | Creator | $70 | 7,500 | 107 |
  | Studio | $150 | 18,000 | 120 |

  The Standard package is at `billing.py:27`. The same table appears in `docs/proposals/pricing-and-margin.md:42-48`.
- Packages are one-time Stripe purchases with no subscription. Terms say "Credits do not expire" and
  "credits are non-refundable" except where required by law (`web/src/pages/legal/TermsPage.tsx:81-83`).
- Usage debit is `ceil(provider USD × credits-per-USD × markup)`. The default is 100 credits per USD
  (`.env.example`). The example markup is 2.0, but the runtime fallback is 1.0, so **do not infer the margin**.
  A reservation hold of ×1.25 is temporary, not a charge (`docs/proposals/pricing-and-margin.md:24-33`).
- **Approved customer copy:** "Credit packs start at $12. No subscription. See the estimated credits before each
  paid step. Total use depends on your story, quality choices and revisions." (`pricing-and-margin.md:53-56`).
- **Forbidden claims:** "a full book for $25", any number of pages per pack, "most popular" (`pricing-and-margin.md:12-15,50-51`).
- Landing pricing bullets: No subscription · Credits never expire · Packs start at US$12 · An estimate before
  each step (`en.json:3254-3260`).
- No free signup credit grant was found in code. The only Canary-paid output is the Cold Open, which is unverified.

### Inputs and limits
- Accepted extensions: `.txt .md .markdown .docx .epub .pdf` (`server/routers/projects.py:283`).
  Readers are in `input_limits.py:309-320`.
- Default limits in `novel_to_comic/src/novel_to_comic/input_limits.py:44-58` (all env-overridable):
  - upload 50 MB (`CANARY_MAX_UPLOAD_MB`)
  - PDF ≤ 2,000 pages
  - EPUB ≤ 500 documents
  - ≤ 5,000,000 extracted characters (~800k–900k words)
  - extraction time ≤ 60 s
  - remote story ≤ 5 MB compressed / 2M characters
- Length is advisory, not a hard cap (ADR 0016, "narrative review and advisory length"). Page density is
  capability-bounded (ADR 0011).
- Marketing phrasing: "Bring a chapter or the whole book" (`en.json:3174`).

### Outputs
- Export formats: **PDF and CBZ only** (`server/routers/export.py:96-97,154-161`). The package is verified before
  download (`open_verified_package`, `export.py:106,157`).
- Public web reader link at `/read/:id` (`web/src/App.tsx:157`).
- Lettering is editable. Book lettering can be switched between `source`, `en`, `es`, `fr`. Translation of
  missing languages is a paid, estimated step. Already-stored languages switch for free
  (`docs/reference/localization.md:57-77`). Integrated/baked art is not translated (`:61`).

### Languages
- UI: English, Spanish, French (`web/src/locales/languages.ts:2-6`; `PRODUCT.md:51-52`).
- Public landing pages exist at `/`, `/es`, `/fr` with hreflang. Product, guide, example, and legal pages are
  **English only** (`docs/reference/localization.md:48-55`).
- Comic output language is set per project and is independent of the UI language (`PRODUCT.md:51-52`).

### Models and providers (verdict: INTERNAL, do not market)
- Production defaults (`docs/reference/account-model-settings.md:25-35`):
  - text stages: GPT-6 Luna / GPT-6 Sol
  - Draw: "Sunburst on OpenAI, FAL backup"
  - selectable alternatives: Claude, Gemini (Vertex), Bedrock, DeepSeek, MiMo (`:37-47`)
  - Runware provider added in HEAD `83b9d06a`
- Reasons not to name models:
  - The copy kit forbids model names in public copy (`showcase/marketing/copy-kit.md:8`).
  - `docs/ops/landing-showcase-assets.json` rules say "No … development model routing".
  - Models change weekly (see `docs/proposals/*model*` and provider-fallbacks).
- The marketable form is the landing disclosure: "Scenewright uses third-party generative models to assist with
  adaptation and illustration… we claim no ownership over generated output" (`en.json:3252`).
  Terms explain that purely AI-generated images may not be copyrightable (`TermsPage.tsx:53-64`).

### Positioning facts
- Users: writers, indie authors, and small studios with a manuscript and no art team. They understand
  "credits" and "export PDF", not "diffusion model" or "prompt" (`PRODUCT.md:9-15`).
- Positioning: "a guided production pipeline rather than an image-generation canvas" (`PRODUCT.md:31-37`).
- Hero: label "AI comic studio for authors" / title "Turn your novel into a comic" / CTA "Start your comic" and
  "Read a finished book" (`en.json:3172-3176`).
- Signature line in social media: "Your novel. Any style." (`copy-kit.md:10`).
- Social card tagline: "Your story. Its first comic scene." / "Direct · Review · Export" / scenewright.ink
  (`web/scripts/build-social-card.mjs:9-15`).
- Domain is `https://scenewright.ink`. Contact is `hello@scenewright.ink` (`publicPages.ts:5,45`).

---

## 3. Brand

- **Identity:** "The Living Ink", "a Golden-Age print-shop tribute, not a generic SaaS interface or comic-book
  parody" (`PRODUCT.md:68-73`). Also described as a "high-end skeuomorphic tribute to ink-on-paper"
  (`DESIGN.md:4-8`).
- **Voice:** "crafted, mechanical, and theatrical—warm and specific at real checkpoints, but clear and calm for
  errors and billing". Familiar terms stay familiar, and internal vocabulary stays behind Dev Content
  (`PRODUCT.md:70-73`).
- **Principles** (`PRODUCT.md:99-115`):
  - Print physics, not digital chrome (pressed, stamped, Ben-Day; never glowing or bouncing)
  - Delight at checkpoints, calm in between
  - Honest machinery (real counts, ETAs, credit estimates)
  - The author owns the project
- **Anti-references** (`PRODUCT.md:75-82`):
  - sterile flat-gray SaaS (Linear/Notion clones)
  - rounded, glassy, gradient-text "AI tool" look
  - comic parody (BAM!/POW!, Comic Sans)
  - Material soft shadows and 1px gray hairlines
- **Visual do/don't** (`DESIGN.md:65-80`):
  - 0px radius everywhere
  - text in `#1b1c15`, never pure black
  - Hero Red used sparingly
  - extreme type scale
  - "Burst" boxes in gold instead of toasts
  - red text only on pulp/bristol for 4.5:1 contrast
- **Social copy house rules** (`showcase/marketing/copy-kit.md:5-12`):
  - show real output only
  - say "AI-assisted"
  - never write "in the style of <artist>"
  - always credit sources and licenses
  - ad-safe page restrictions apply (Janitor pages 4+, gore)
- **Type** (`DESIGN.md:27-33`; `web/src/index.css:158-160`): Anybody for display, Be Vietnam Pro for body, Lexend
  for meta. Self-hosted woff2 files are in `web/src/assets/fonts/` (Anybody OFL, `anybody-OFL.txt`). The Panel
  Frame wordmark is "live-text-provisional" until a licensed Anybody font is outlined
  (`web/brand-system/README.md` Typography status).
- **Tokens:** `web/src/index.css:125-160` (`@theme`). Core values: `--color-hero-red #b51822`,
  `--color-pulp-paper #fcfaed`, `--color-ink-black #1b1c15`, `--color-narrator-gold #fae361`,
  `--color-bristol #ffffff`, `--color-archive-sage #4a7c59`, plus surface, chip, ink-fade, and state colors.
  `web/brand-system/src/geometry.ts:1-9` duplicates the core palette for logo generation. The social card uses
  slightly different reds and pulps (`#b8202b`, `#ece8dc`; `build-social-card.mjs:6-8`), so it drifts from the tokens.
- **Logo assets** are built by `npm run brand:build` and written to `web/public/brand/scenewright-panel-frame/`:
  symbol (primary/black/red/white/reversed/micro) SVGs, horizontal, reversed, and stacked lockups, wordmark,
  app icons 64–1024 PNG, and contact sheet. Favicons are in `web/public/` (`favicon.svg`, `.ico`, 16/32/48 PNG,
  `apple-touch-icon.png`). Concept images in `web/brand-system/references/*.png` are **reference only**, not brand assets.

**Can a separate Vite app import them directly?** Partly:
- `../web/src/index.css` begins with `@import "tailwindcss"` and `@import "./fonts.css"` (`index.css:1-2`) and
  contains app-level rules. Importing the whole file drags in app CSS. It also requires Tailwind v4
  (`web/package.json`: `tailwindcss ^4.3.3`, `@tailwindcss/vite`). Recommended: a sync script extracts the `@theme { … }`
  block (`index.css:125-160`) and `fonts.css` into `scenewright-marketing/src/brand/tokens.css`, keyed by blob SHA.
  Alternatively, import `../web/brand-system/src/geometry.ts` for `PALETTE` (plain TS, no deps).
- Vite blocks files outside the project root by default. A direct import needs
  `server.fs.allow: ['..', '../web']` and a relative `@import` path. Fonts are referenced from
  `../web/src/assets/fonts/*.woff2` via `fonts.css`.
- Static logo files can be copied from `../web/public/brand/scenewright-panel-frame/*.svg` or served as-is.

---

## 4. Public marketing surface (already in canary/web)

- **Routes** (`web/src/App.tsx:157-179`):
  - `/` (public home when signed out, Library when signed in), `/es`, `/fr`
  - `/how-it-works`, `/pricing`, `/guides/turn-a-novel-into-a-comic`, `/examples/kaitlin-out-of-space`, `/about`
    (all rendered by `ProductPage`, `App.tsx:161`)
  - `/samples` (sample library), `/read/:id` (public books)
  - `/legal/terms`, `/legal/privacy`, `/legal/acceptable-use`
  - `/login`, `/signup`
- **Build** (`web/package.json:11`): `i18n:check → tsc → vite build → build-social-card.mjs → prerender-public.mjs → perf:check`.
  - `web/scripts/prerender-public.mjs` emits static HTML per public path into `public/<slug>.html`
    (`:45-48`) with hreflang for the home pages (`:43`).
  - `build-social-card.mjs` renders the 1200×630 OG card SVG to `dist/marketing/scenewright-social.png`.
  - `build-marketing-images.mjs` builds 480/800 webp previews and `src/assets/marketing-images.json` from
    `web/public/marketing/*.webp`.
- **Copy locations, which is where approved copy would go:**
  - Landing copy: `web/src/locales/{en,es,fr}.json` `landing.*` keys (nav, hero, books, styles, process, rights,
    pricing, faq, final, footer; 129 EN keys). Shape: `web/src/pages/landingCopy.ts`. Render:
    `web/src/pages/HomePage.tsx` + `HomePage.css`.
  - SEO titles and meta for every public route: `web/src/lib/publicPages.ts:14-26`. Schema.org JSON-LD:
    `publicPages.ts:39-66`.
  - Product, guide, example, and about bodies: inline English JSX in `web/src/pages/ProductPage.tsx`
    (83 lines; **not** in catalogs).
  - Legal: `web/src/pages/legal/*.tsx`.
  - Shelf: `web/src/lib/showcaseShelf.ts:15-21` (7 books). Bodies: `showcase/books/` (deploys on push to main,
    `showcase/books/README.md:5-7`).
  - Workflow rule: new strings go through `npm run i18n:extract`, then fill es/fr, then `npm run i18n:check`.
    The build fails on gaps (`docs/reference/localization.md:23-30`).
- GA4 is optional and consent-gated, with a `sign_up` event (`web/src/lib/ga4.ts:156`;
  `docs/reference/observability.md:8`).

---

## 5. Analytics (PostHog)

- **Browser:** `web/src/telemetry.ts` is the only posthog-js user. `posthog.init` is at `:423`:
  - lazy-loaded, text and attributes masked, all images, video, and canvas blocked in replay
  - `capture_pageview:false`, manual canonical `$pageview` (`:469`)
  - `person_profiles: "identified_only"` (`:451`)
- The browser allowlist in `scrubEvent` keeps only `$exception, $identify, $create_alias, $pageview,
  signup_submitted, $autocapture, $rageclick, $snapshot, $web_vitals, api_request_completed` (`telemetry.ts:243-244`).
- First-touch attribution (UTM source/medium/campaign, `book_referral`, referring domain, `direct`) is captured
  in `telemetry.ts:39-99` and stored in Supabase user metadata (`observability.md:313-318`).
- **No feature flags are used.** No `isFeatureEnabled`, `getFeatureFlag`, or `useFeatureFlag` calls were found
  in `web/src` or the backend.
- **Server product events.** The allowlist is in `novel_to_comic/src/novel_to_comic/server/product_events.py:28-70`:
  `page_ready, operation_completed, output_accepted, feedback_submitted, credit_blocked, stage_dispatched,
  export_package_ready, export_download_requested, project_created, stage_started, stage_succeeded, stage_failed,
  stage_approved, style_selected, cold_open_printed, cold_open_favorite, page_outcome, checkout_started,
  credits_purchased, refund_completed, operator_credit_granted, export_succeeded, account_created,
  account_observed, station_viewed, inspect_drawer_opened, checkout_cancelled, page_viewed`.
- Emit sites:
  - `project_created`: `routers/projects.py:560,1054`
  - `checkout_started`: `routers/billing.py:216`
  - `credits_purchased`: Stripe webhook plus an atomic outbox (`observability.md:445-466`)
  - `account_created`: `routers/events.py:85`, dated at Supabase signup, deterministic ID
  - `style_selected`: `routers/styles.py:991`
  - `stage_approved`: `routers/pipeline.py:575`
  - `credit_blocked`: `pipeline_operations.py:351`
  - `export_package_ready` / `export_download_requested`: `routers/export.py:111,136,160`
  - `station_viewed`: browser `web/src/layout/ProjectRooms.tsx:38`
  - `cold_open_printed`: `cold_open_jobs.py:214`
- **Funnels a marketer would query** (dashboards in `observability.md:277-310`; PostHog project 630262):
  - Visit → signup: `$pageview` (path `/`, `/es`, `/fr`, `/pricing`…) → `signup_submitted` (anonymous, carries
    attribution) → `account_created` (server, has `acquisition_*`, `referring_domain`, `referred_by_book`).
  - Activation (14-day): `account_created → project_created → style_selected → page_ready`
    (first page) `→ export_download_requested`.
  - Revenue: `credit_blocked → checkout_started → credits_purchased` (`gross_amount_cents`, gross; refunds are
    not netted; the ledger is authoritative). `checkout_cancelled` and `refund_completed` are also available.
  - "Author active" action: `project_created, stage_started, stage_approved, style_selected, station_viewed,
    page_outcome, export_download_requested, checkout_started, feedback_submitted` (`observability.md:296-301`).
  - Book referral loop: public reader `/read/:id` → `book_referral` source.
- Filters: `environment=production`, exclude cohort `$internal_or_test_user = true`. Launch annotation is
  2026-09-28 (`observability.md:279-301`).
- `posthog-self-driving-report.md` (INT):
  - Session Replay, Error Tracking, and Support are on
  - GitHub Issues is synced into the warehouse
  - 7 scouts, including custom `signals-scout-credit-purchase-recovery` (credit-block → checkout → purchase)
    and `generation-pipeline-health`
  - 2 Replay Vision monitors: `/project/:id/book` breakage and rage-click frustration
  - open follow-ups: no support channel connected; recordings unverified (`:84-88`)

---

## 6. Showcase assets

### Cleared for public use (licensed, already published)
- **Homepage shelf**: `showcase/books/NN-slug/{book.json, <version>/*.jpg}`, 191 JPGs total.
  - Shelf metadata: `web/src/lib/showcaseShelf.ts:15-21`
  - Rights and per-page ad clearance: `docs/proposals/showcase-and-growth-2026-09.md:49-58`

  | Book | Source license | Pages | Ad-cleared pages |
  |---|---|---:|---|
  | The Call of Cthulhu (Lovecraft) | PD | 44 | all |
  | The Masque of the Red Death (Poe) | PD | 24 | 3–12 only |
  | Kaitlin Out of Space (Coupland) | CC0 | 52 | all except 10, 15 |
  | Elm and Keep (@strnglft) | CC0 | 21 | all after review |
  | Site-30's Janitor (JanitorCakeworth) | **CC BY-SA 3.0** (attribution and share-alike) | 9 | not pages 4+ |
  | Astronomical (Sophia Light, SCP) | **CC BY-SA 3.0** | 21 | not assessed |
  | The Monkey's Paw (W. W. Jacobs) | PD (1902) | 20 | not assessed |

- **Web-ready marketing images** in `web/public/marketing/`:
  - `cthulhu-page-40.webp`, `elm-and-keep-page-12.webp`, `janitor-{riso,gouache,oil}-page-01.webp`
    (same story in 3 looks = before/after material), `kaitlin-page-{01,12,34}.webp`
  - `anya/rurik/tavern-reference.webp` (cast sheets), `masque-flipbook.mp4` + poster (style flipbook hero),
    `scenewright-film-poster.webp`
  - `home/` holds 7 covers `cover-*.webp`, `cast-sheet.webp`, `look-proof-{a,b}.webp`, `review-page.webp`
  - 480/800 previews are in `previews/`
- **Launch kit** in `showcase/marketing/launch-kit/`: `gallery-1..6-*.jpg` (any style, describe the look, same
  faces, lettering, plain-words revision, whole books), `preview-{1x1,4x3,16x9,16x10}.jpg`,
  `social-card-1200x630.jpg`, `carousel-poe-ten-styles/`, `comparison.html`, `asset-checks.json`.
- **YouTube kit** in `showcase/marketing/youtube-kit/`: avatar, banner, thumbnails (4k), description, title,
  watermark. See the Carl risk below.
- **UI screenshots**: `showcase/audit-captures/` (2560×1440 PNG, `showcase/audit.md:44-46`). Freshness caveat:
  some date from September 14 and some states are stale (`audit.md:48`). The UI was redesigned 2026-10-26, so
  recapture before use.
- **Selection record**: `docs/ops/landing-showcase-assets.json` ("Real showcase output from the test account…
  Not customer work; no quality guarantee").
- The sample stories offered to users (21 curated, CC0 and CC BY-SA) are listed in
  `docs/reference/sample-library.md:14-17`.

### Do not use publicly (copyright red flags)
- **`samples/` is git-tracked** (`git ls-files samples`) and contains in-copyright third-party texts:
  - `dcc1.txt`: Dungeon Crawler Carl, Matt Dinniman
  - `theegg.txt`: The Egg, Andy Weir
  - `na2f.txt`: Nightmare at 20,000 Feet, Richard Matheson
  - `theflowers.txt`: Alice Walker, 1973
  - `C00-Last Question.pdf`: Asimov
  - `fpublic0007-one-of-these-days-gabriel-garcia-marquez.pdf` and `undiadeestos.txt`: García Márquez
  - `lanochebocaarriba.txt`: Cortázar
  - Only `themonkeyspaw.txt` is PD.
  - **Never use these texts, or comics generated from them, in marketing.**
- **`projects/`** (gitignored `.gitignore:90`, 6.9 GB, `projects/<account-uuid>/<slug>/`) mixes cleared and
  uncleared work. Uncleared or unverified: `dcc`, `the-egg`, `the-last-question`, `na2f`,
  `undiadeestos-codex`, `la-metamorfosis` (Kafka is PD, but the Spanish translation may not be),
  `merrily-merrily-merrily`, `this-happened-before-v3`. Projects hold `input/` manuscripts and working files.
  Use only the `showcase/books/` snapshots.
- **Dungeon Crawler Carl footage**: the main showcase film uses Carl pages 25/26 ("Fix it in plain words" beat)
  (`showcase/video/EDIT.md:32,37`; `showcase/video/src/**`; `showcase/audit.md:7-17`). A homepage image
  `dungeon-crawler-carl-page-25.webp` was planned (`audit.md:17`) and is **not** in `web/public/marketing/` now.
  **Audit any video render or YouTube upload for Carl frames before reuse.**
- `showcase/retired-books/` holds The Terror (Maupassant, PD; removed from the shelf 2026-10-08) and Janitor
  gouache/oil. The gouache edition has profanity on the last panel of page 1 (`copy-kit.md:12`).
- CC BY-SA works (Janitor, Astronomical, SCP): marketing must carry author, wiki, and license attribution.
  Derivative creative may need share-alike (`docs/reference/sample-library.md:43-49`).

---

## 7. Detecting "what changed" for release-note marketing

- **No tags** (`git tag` → 0), no CHANGELOG, and no release notes. Releases deploy from `main` via Depot CI to
  Lightsail (`docs/ops/lightsail-ci.md:1-45`). Pushing `main` also deploys the showcase shelf
  (`showcase/books/README.md:5-7`). There is a `docs/ops/release-evidence-template.md`, but it is ops-facing.
- **Commit style is inconsistent.** There is no Conventional Commits prefix. There is a mix of:
  - imperative sentences ("Rebuild the front page around the book, the styles and the five stations", `9fc1165b`)
  - terse tags ("cold open" `2d87ffed`, "director, runware provider" `83b9d06a`, "fix test on ci")
  - occasional merges from `codex/*` branches (`467a0832`)

  All by one author. 43 commits since 2026-10-13. A changelog generator cannot rely on prefixes.
- **Better signals for a sync script:**
  1. `git log --since=<last-sync> -- docs/README.md docs/adr docs/reference docs/proposals PRODUCT.md`. New ADRs
     and README "Active future work" entries carry dated status lines such as "Implemented October 27…"
     (`docs/README.md:72-80`).
  2. A diff of `web/src/locales/en.json` `landing.*` and `web/src/lib/publicPages.ts`, for shipped-copy changes.
  3. Diffs of `showcase/books/*/book.json` and `web/src/lib/showcaseShelf.ts`, for new showcase books.
  4. Diffs of `routers/billing.py` and `TermsPage.tsx`, for pricing and terms changes.
  5. `git log --merges` for feature branches.
- **Issue tracker** (`docs/agents/issue-tracker.md`):
  - GitHub Issues via `gh` (`:1-18`); PRs are **not** a request surface (`:26-28`).
  - Wayfinder maps are labelled `wayfinder:map`, and children carry `wayfinder:{research,prototype,grilling,task}`
    labels (`:38-46`).
  - Triage labels: `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`
    (`docs/agents/triage-labels.md:5-11`).
  - Closed issues with resolution comments are the best source for user-facing feature names:
    `gh issue list --state closed --search "closed:>DATE"`.
  - PostHog also syncs these issues into its warehouse (`posthog-self-driving-report.md:13`).
- **Gate for release-note claims:** only promote items that `docs/README.md` lists under "Current contracts"
  or that have paid-provider verification. Items marked "Implemented… not yet run against paid providers"
  (Cold Open, Director) stay "coming soon" at most.
