# Canary — Product Naming & Marketing Strategy

> **Architecture warning (2026-07-25):** retain this document for audience,
> naming, trust, and positioning research only. References to a nine-stage
> pipeline, per-panel generation/revision, or deterministic lettering are
> superseded by
> `docs/superpowers/specs/2026-07-25-full-page-generation-design.md`.

> Deep research (competitive landscape + market demand + naming/domain/trademark
> clearance) and a full go-to-market plan for the lean / pre-revenue tier. Dated
> 2026-07-02.
>
> **Scope decisions locked up front (from clarifying questions):**
> - **Name direction:** fresh new product name — "Canary" is treated as a
>   codename, not the launch brand.
> - **Primary customer:** indie / self-published authors (KDP, Wattpad, Royal
>   Road, Webnovel). Other segments are secondary.
> - **Budget tier:** lean / pre-revenue (under ~$2k/mo). Channel mix is
>   community-led growth, not paid acquisition.

## Validation update — 2026-07-10

This document remains useful for its **audience, human-direction, source-
fidelity, pay-as-you-go, and trust strategy**, but it is no longer reliable as
a current competitive or naming-clearance snapshot. Treat it as roughly
**6/10 current**: the strategic direction is strong; several market facts and
launch hypotheses below have already moved.

### Still valid and supported by the product

- Lead with the outcome: a graphic-novel edition of an author's existing book.
- Position Scenewright as an instrument the author directs, not a black-box
  replacement for the author.
- Whole-manuscript ingestion, four creative checkpoints, reference-guided
  continuity, correction, final lettering, and PDF/CBZ export are implemented
  product truths. The correction and rendering unit is changing from panels to
  complete pages.
- The rights posture is real but must stay precise: the author retains the
  manuscript; Scenewright makes no ownership claim over generated output;
  copyrightability of purely generated material remains case-specific.
- One-off credit packs, pre-run estimates, and non-expiring credits are
  implemented. There is no subscription.

### Material corrections to the original research

1. **Name clearance is unresolved and now higher risk.** Exact federal knockout
   searches remain encouraging, but an active, phonetically identical product,
   [SceneWrite](https://www.scenewrite.app/features/), launched in the adjacent
   AI storytelling/storyboarding category. Pause major brand spend until a
   practitioner reviews federal, state, common-law, domain, and international
   confusion risk. Domain availability in §1.4 was point-in-time; the primary
   `.ink` domain was registered on 2026-07-02.
2. **The competitive wedge narrowed.** [ComicInk](https://www.comicink.ai/) now
   offers whole-book PDF ingestion, recurring cast/world references, printable
   export, ownership language, no-expiry credits, and a creator storefront.
   Whole-book ingestion, consistency, export, rights, and pay-as-you-go are now
   category expectations, not unique claims. Scenewright's strongest current
   difference is the depth and visibility of author control: inspectable
   checkpoints, source-faithful adaptation, focused panel revision, lettering,
   and explicit per-step cost.
3. **Pricing references are stale.** ComicInk currently advertises roughly 30
   pages for $9.99 and 240 for $54.99; LlamaGen's current plans start at $18/mo.
   The `$10 / 8-page` and `$80–200 / book` suggestions below should not guide
   launch copy. `pricing-and-margin.md` supersedes the internal model, but a
   fixed per-book marketing promise still requires real production usage data.
4. **Author sentiment is bifurcated, not uniformly hostile.** A 2025
   [BookBub survey](https://insights.bookbub.com/how-authors-are-thinking-about-ai-survey/)
   found substantial use and substantial rejection of generative AI.
   The attainable audience is AI-open but protective of authorship, consent,
   privacy, and disclosure. Keep AI out of the headline if useful, but disclose
   the AI-assisted workflow clearly on the page rather than hiding it in a tiny
   footer.
5. **Several GTM claims remain experiments.** The “top 20%” buyer profile,
   “80% from community,” free-Chapter-1 flywheel, influencer conversion, and
   mandatory watermark are hypotheses without product or cohort evidence.
   Test them. Facebook, Instagram, author newsletters/podcasts, design partners,
   and high-intent search deserve weight alongside Reddit.

### Application audit at this review

The product applies the internal strategy well: Scenewright naming and visual
identity, four author gates, reference-guided generation, review-by-exception,
page finishing, cautious rights terms, credit estimates, and no-expiry packages
are live. The major gap was acquisition: there was no public homepage, public
workflow explanation, proof reel, pricing story, case study, or responsible-use
explanation. This review adds the public homepage and corrects the unsupported
“500 free credits” signup claim. Still missing are a verified trial/grant,
authorized author case studies, a measured 30–50-panel continuity proof, and
the proposed authorship log.

Homepage claims should stay within what the product can prove:

- “Turn your novel into a graphic novel you direct.”
- “Choose the look. Approve the cast. Review and revise individual panels.”
- “AI-assisted visual adaptation, directed by you.”
- “Export PDF and CBZ.”
- “Your manuscript stays yours. We claim no ownership over generated output.”

Avoid “perfect consistency,” “copyright-safe,” “publish-ready,” “full novel in
minutes,” fixed savings, fixed per-book cost, or compatibility with a
human-authored seal until each is independently substantiated.

## TL;DR

**Recommended name: `Scenewright`** — a real dictionary word
(*"a designer and maker of theatrical scenery"*, Merriam-Webster) that reads as
human craft, not AI toy, in the most AI-hostile creator market that exists.

- **Primary domain:** `scenewright.ink` — ✅ **FREE** (~$3 first year, ~$25/yr
  renewal). `.ink` is thematically perfect (publishing/comics/print heritage).
- **Backup domains:** `scenewright.co` (FREE), `getscenewright.com` (FREE).
- **Cost to secure the brand on day one:** ~$35–45.
- **Tagline:** *"Your novel, scene by scene."*

The research surfaced one non-obvious constraint that reshapes the whole brief:
**indie authors are among the most AI-hostile creator audiences that exist**
(Authors Guild class-actions vs. OpenAI/Anthropic, a "human-written seal"
movement, KDP mandatory AI disclosure, a Copyright Office that denies protection
to purely AI-generated images). Every competitor that names itself like an AI
tool (`ComicAI`, `LlamaGen`, `AI Comic Factory`) hands this audience a reason to
bounce. So the name and positioning must read as **author tool + craft**, sitting
on the shelf next to Scrivener / Atticus / Vellum — not next to a generator.

The marketing strategy is **community-led growth built on the pipeline itself as
content**, a **free Chapter-1-artifact flywheel** for virality, and positioning
as **author-owned IP / human-directed craft** — the one thing every funded
competitor gets wrong.

> ⚠️ **One thing to verify before spending on brand assets:** USPTO trademark
> clearance. Web search returned no software product, company, or live
> registration for "Scenewright" — only dictionary definitions and unrelated
> noise. Encouraging but **not a legal clearance.** See §1.6.

---

## 1. Naming

### 1.1 The strategic constraint

Indie authors are one of the most AI-hostile creator communities that exists:

- **Authors Guild v. OpenAI** (filed Sept 2023, ongoing) — class action by
  George R.R. Martin, John Grisham, Jodi Picoult, David Baldacci + 13 others.
- **Anthropic class action** — Authors Guild urging members to register titles;
  potential statutory damages $750–$150,000 per title.
- **Grassroots "human-written" seal movement** on covers as a marketing
  differentiator.
- **KDP mandatory AI disclosure** (Sept 2023) for AI-generated text, images,
  and translations.
- **U.S. Copyright Office** denies protection to purely AI-generated images
  (*Zarya of the Dawn*, *Thaler v. Perlmutter*, Part 2 Copyrightability Report
  2024).

A name that screams "AI" (`ComicAI`, `NovelGPT`, `LlamaGen`) is self-defeating
for this exact audience. The name must read as **author tool + craft**, not AI
toy.

### 1.2 The naming axis that won: "-wright" (maker/craftsman)

Like **playwright, shipwright, wheelwright** — the `-wright` suffix means
craftsman/maker. It signals human craft, not machine output, and natively evokes
the script/theater world that a novel-to-comic pipeline lives in.

`Scenewright` lands on three levels:

| Axis | Why it works |
|---|---|
| **Etymology** | Real dictionary word (Merriam-Webster): *"a designer and maker of theatrical scenery."* The `-wright` suffix means craftsman/maker — human craft, not machine output. |
| **Semantics** | The product literally builds scenes: novel → scenes → panels. "Scene" is the exact unit of both prose and comics. Describes what the tool *does* without leaning on "comic" (AI-art backlash) or "AI" (author backlash). |
| **IP/copyright posture** | "Wright" implies authored work. Subtly supports the positioning that the *author* is the creator and the tool is the instrument — the framing needed for the copyright/human-authorship story (§4). |

### 1.3 Rejected strong alternatives

| Candidate | Verdict | Why rejected |
|---|---|---|
| **Storywright** | Killed on clearance | **Live collision:** `storywright.io` is an active TTRPG software product; `.com/.co/.studio/.press` all taken. Better semantics, fatal clearance. |
| **Panelwright** | Kept as #2 | `panelwright.ink` FREE. Clean and on-theme, but "panel" tilts comic-industry; "scene" is broader and more literary. |
| **Illuminovel** | Strong #3 | `illuminovel.ink` + `.co` both FREE. Gorgeous (illuminated manuscripts = the original text-with-pictures) but harder to say/spell, less obviously "maker" coded. |
| **Anything "Comic"/"AI"/"GPT"/"Gen"** | Disqualified | Triggers AI-art backlash (comic audience) and author backlash simultaneously. |

### 1.4 Domain availability (verified live 2026-07-02)

| Domain | Status | Notes |
|---|---|---|
| **`scenewright.ink`** | ✅ **FREE** | **Primary.** `.ink` thematically perfect (publishing/comics/print heritage). |
| **`scenewright.co`** | ✅ FREE | Strong backup; `.co` reads as company/startup. |
| `getscenewright.com` | ✅ FREE | Defensive fallback if a `.com` is wanted cheaply. |
| `scenewright.com` | ❌ Taken | IONOS-registered, non-resolving (likely parked/buyable at a premium — not worth it at launch). |
| `scenewright.app` / `.ai` | ❌ Taken | Defensive but not essential. |

### 1.5 Cost to secure the brand

| Item | Cost |
|---|---|
| `scenewright.ink` (Namecheap, yr 1 promo) | ~$2.98 + $0.18 ICANN = **~$3.16** |
| `scenewright.ink` renewal (Porkbun, yr 2+) | ~$25/yr |
| `scenewright.co` (defensive) | ~$20–30/yr |
| `getscenewright.com` (defensive) | ~$10/yr |
| **Total year 1** | **~$35–45** |

`.ink` pricing reference: Namecheap ~$2.98 first-year promo, ~$25+ renewal;
Porkbun transparent renewal (no teaser-spike). Compare at
[tld-list.com/tld/ink](https://tld-list.com/tld/ink).

### 1.6 ⚠️ Trademark caveat (could not fully clear)

USPTO TESS/TSDR is session/POST-based and was rate-limited from the research
environment. Web search returned **no software product, company, or live
registration** for "Scenewright" — only dictionary definitions and unrelated
malware-analysis noise. Encouraging but **not a legal clearance.**

Before committing to logo/design spend:

1. Run the exact string at [tmsearch.uspto.gov](https://tmsearch.uspto.gov/)
   filtered to **Live** / **Class 9** (software) + **Class 42** (SaaS).
2. Check [WIPO Global Brand Database](https://www3.wipo.int/branddb/en/) for
   international coverage.
3. Budget ~$500–800 for a formal trademark clearance opinion from a practitioner
   if certainty is wanted before brand-asset spend.

---

## 2. Competitive landscape

### 2.1 The real competitive set

**Direct competitor (closest):** **ComicInk.ai** — does PDF-book → multi-issue
comic series, credit pricing, claims <$10 per 8-page issue, credits never
expire. Clearest feature analog to this 9-stage pipeline (book → bible → cast →
panels → pages → export). HN "Show HN" reception: "not perfect, but
substantially better than raw text-to-image." *Watch them first.*

**Mature / funded:** **Dashtoon** — $18M raised ($5M seed Matrix/Stellaris 2023
+ $13M Series A Peak XV, Aug 2025). Strongest assembly + consistency + reader-app
distribution. *But* adapts novels via humans (DashAuthors), not pure AI, and
carries contract/ethics baggage:
- [Writer Beware "Contract Critique: Dashtoon"](https://writerbeware.blog/2024/05/10/contract-critique-dashtoon/)
- r/Wattpad low-payout complaints ("$48 for 2025")
- Reader-app reviews call the AI art "creepy and off-putting"

**Owns the keyword:** **LlamaGen** — markets "novel to comic" but is page-level,
not whole-book. Pro $9.99 / Max $19.99.

**Long-script (not prose):** **Drawstory.ai** — strongest on long *script* input
(≤100 pages); requires the author to script first. A friction point this product
removes by taking raw prose.

**Chapter-by-chapter:** **Jenova.ai** — consistency positioning, claims 200+ page
consistency, ~$20/mo.

**The real competitor nobody names:** **DIY** — ChatGPT + Midjourney for
~$30–50/mo. The bar is *materially better consistency/convenience*, not "exists
vs. doesn't exist."

**Tier-2 single-panel / short-prompt tools** (not long-form competitors, but
price anchors): AI Comic Factory (free HF demo), Perchance (truly free,
unlimited), Anifusion, ComicsMaker ($10–$120), Comistitch ($9.99–$39.99,
credits roll over), ArcStory, Adobe Firefly, Canva Magic Media.

### 2.2 Where the entire category is weak (the wedge)

1. **Character & location consistency** — the #1 universal complaint across
   r/aicomicmakers, r/StableDiffusion, r/ComicWriting. Characters "change
   appearance panel-to-panel."
2. **Long-form prose ingestion** — almost no tool ingests a whole book; users
   paste excerpts page-by-page.
3. **Export & finishing** — most generate panels but don't compose a publishable
   PDF/CBZ. (This product's Stage 9 does.)
4. **Contract/IP terms** — publishing platforms take aggressive licensing;
   authors distrust them.

### 2.3 Pricing band that has emerged

| Tier | Price | Examples |
|---|---|---|
| Entry paid | ~$10–11/mo | LlamaGen Pro, Comistitch Starter, Dashtoon Standard, ComicAI |
| Mid | ~$19–30/mo | Jenova, Drawstory, Comistitch Pro, Dashtoon Pro |
| Top | ~$40–120/mo | Comistitch Elite, ComicsMaker Pro/Mega |
| **Breakaway model** | **pay-per-credit, no subscription, credits never expire** | **ComicInk** (~$10 / 8-page issue) — resonates with authors who hate recurring fees |
| Free floor | $0 | Perchance (unlimited), AI Comic Factory (HF demo) |

---

## 3. Market & demand (the honest picture)

### 3.1 Market size & growth

- **~3.5M self-published titles in 2025** (+38.7% YoY); total U.S. book output
  topped 4M (+32.5%). Trad-pub rose only 6.6%.
  ([Publishers Weekly](https://www.publishersweekly.com/pw/by-topic/industry-news/publisher-news/article/99943-book-output-topped-4-million-in-2025.html))
- **Graphic novel sales +9.2% in 2025**, up >100% since 2019.
  ([Comics Beat](https://www.comicsbeat.com/graphic-novel-sales-rose-9-2-in-2025/))
- North American comics/GN market ~$1.94B (2024).
  ([Publishers Weekly](https://www.publishersweekly.com/pw/newsbrief/index.html?record=5455))
- **Webtoon IPO'd June 2024**, ~170M MAUs / 150 countries; FY2024 revenue +5.1%.
  ([Webtoon IR](https://ir.webtoon.com/news-releases/news-release-details/webtoon-entertainment-inc-reports-fourth-quarter-and-full-year/))
- ⚠️ Webtoon "market size" CAGRs (27–28%) floating around are self-interested
  vendor estimates — treat skeptically. The measured signal (Webtoon's own
  revenue + MAUs) is the trustworthy part.

**Caveat:** the 3.5M figure includes low-effort/AI-assisted/non-book titles. The
count of *serious* indie novelists is materially smaller — low hundreds of
thousands. Treat 3.5M as a ceiling, not the buyer base.

### 3.2 The wedge is an order of magnitude

Traditional artist cost vs. indie production budget:

| Cost benchmark | Range | Source |
|---|---|---|
| Comic artist per page | $50–$400+ (full art) | [Creator Resource](https://www.creatorresource.com/page-rate-finder-comic-book-publishers/), [Drawphics 2026](https://drawphics.com/how-to-hire-a-comic-book-artist-2026/) |
| **120-page graphic novel at pro rates** | **$6,000–$12,000+** | math |
| Indie author's *entire* production budget | ~$3,000–$6,000 | [Reedsy](https://reedsy.com/blog/guide/how-to-self-publish-a-book/cost-to-self-publish/) |
| Custom illustrated **cover** (single) | $450–$3,000 | [Book Cover Hub 2026](https://bookcoverhub.com/blog/book-cover-design-cost/) |

Authors already pay $450–$3,000 for a *single illustrated cover*. A full-graphic-
novel tool enters a spend category authors understand and budget for.

### 3.3 Demand signals (real but diffuse)

- Active Reddit threads asking for exactly this workflow: r/writing
  ("Novel to graphic novel"), r/ComicBookCollabs ("Planning to start a comic"),
  r/ComicWriting ("How to adapt prose to comic"), r/WritingWithAI ("Which AI
  tools for comic book/graphic novel writing?").
- Sentiment in those threads is consistent: it's expensive (must pay an artist),
  adapting prose loses internal monologue, people are actively hunting for
  cheaper/AI-assisted paths. This is **bottom-of-funnel demand** — people
  already searching for the workflow — but diffuse and price-sensitive.

### 3.4 Willingness to pay & author income reality

- **Median active self-pub author: ~$12,000–$15,000/yr.** ~50% earn under
  $1,000/yr. Income is extremely skewed; top 10% earn $50K+.
- **Author-tool pricing norms:**
  - *One-time purchase* for infrastructure: Scrivener ~$49–60, Atticus $147,
    Vellum $249.99.
  - *Subscription* for AI content tools: Sudowrite $10–59/mo, NovelCrafter
    $4–20/mo + BYOK, NovelAI $15/mo.
- **Implication:** a graphic-novel generator is closer to an AI content tool
  (subscription + usage credits is expected, because generation has real compute
  cost) than to Scrivener/Atticus. Authors are conditioned to $15–60/mo for AI
  writing tools; a premium above that is defensible only if output quality is
  dramatically higher than DIY (ChatGPT + Midjourney).

### 3.5 The realistic buyer is narrow

The real buyer is the **~top 20% of serious, prolific, multi-book indie authors
earning $12K+/yr** — not the millions of one-book hobbyists earning ~$0. A
mass-market subscription priced for the bottom 50% will under-monetize; a
premium one-time/credit product aimed at serious authors is more aligned with
where the money actually is.

---

## 4. Positioning (the make-or-break decision)

Given the audience's AI hostility, positioning is *the* strategy, not a side
task. Build everything around a single framing:

> **"The author owns the work. Scenewright is the instrument."**

Four non-negotiable product/marketing commitments:

1. **Human-in-the-loop, always.** Every stage is inspectable and editable (the
   9-stage design already does this — *lead with it*). Pitch is "AI accelerates;
   you direct," never "AI does it for you."
2. **Author retains all IP.** No claim on input or output. Make IP terms the most
   prominent thing on the pricing page. (Dashtoon's biggest weakness — the
   clearest contrast.)
3. **Document human authorship.** The Copyright Office denies protection to
   *purely* AI-generated images but protects human-arranged/edited works
   ([USCO Part 2 report](https://www.copyright.gov/ai/Copyright-and-Artificial-Intelligence-Part-2-Copyrightability-Report.pdf)).
   Lean into the edit/approve/arrange workflow. Position the export as
   *human-authored, AI-illustrated* — and say so. Future feature: an exported
   "authorship log" (which panels the author edited/approved) as a
   copyright-supporting artifact.
4. **No "AI comic" language anywhere.** The category term is poison with this
   audience. Sell **"a graphic-novel edition of your book"** or **"visual
   adaptation."** The word "AI" appears in a small "how it works / responsible
   use" footer, not in headlines.

---

## 5. Marketing strategy (lean / pre-revenue tier)

Budget: **under ~$2k/mo.** Community-led growth, not paid acquisition — both
because the budget can't afford paid and because this audience is reached through
trust, not impressions.

### Phase 0 — Foundation (weeks 1–4, ~$0–200)

- [ ] Secure `scenewright.ink` + `.co` + `getscenewright.com` (~$35).
- [ ] Trademark clearance (§1.6).
- [ ] One-page site with email waitlist. Copy lead: *"Turn your novel into a
      graphic novel. You keep the rights."*
- [ ] Set up r/SelfPublish, r/writing, r/KDP, r/ComicBookCollabs, r/WritingWithAI
      accounts (genuine participation, not link-dropping).

### Phase 1 — Community seeding (months 1–3, ~$0–500/mo)

80% of early users come from here.

- [ ] **Show-don't-tell on Reddit/X.** Take a *public-domain* novel (Pride &
      Prejudice, Dracula — IP-clean) and post the adaptation process
      stage-by-stage. The 9-stage pipeline is *innately* shareable content:
      "here's how the AI storyboarded Chapter 1" threads. **The pipeline is the
      marketing.**
- [ ] **Author YouTuber / BookTok seeding.** Identify 10–15 mid-tier
      creator-authors (5–50K subs) covering self-pub craft. Offer free full
      adaptation of one of *their* novels in exchange for an honest process
      video. Booktube audiences convert well and trust creator endorsement far
      more than ads. Cost: compute + time, ~$0 cash.
- [ ] **Target the pain queries with content/SEO.** People are already searching
      these exact phrases: *"turn my novel into a comic,"* *"novel to graphic
      novel,"* *"how to make a comic from my book."* Write the definitive guides
      (low-competition long-tail). Capture that intent.
- [ ] **Be present where the decision happens:** KBoards/Writer's Cafe,
      r/Wattpad, Royal Road forums, the 20Booksto50K Facebook group. Answer
      questions; never lead with the product.

### Phase 2 — Free-tier flywheel (months 2–4, ~$300–800/mo compute)

- [ ] **Free tier = Chapter 1, fully adapted, with a "Made with Scenewright"
      watermark + credit on the export.** The single most important growth lever:
      authors share their own adaptation to their own audience, each share
      carrying the brand. The free artifact is the acquisition channel.
- [ ] **Pay-per-credit pricing, no subscription, credits never expire**
      (matching ComicInk's resonant model + author-tool norms). Authors resent
      recurring fees for one-off production tasks; "buy 200 credits, use them
      whenever" fits how they actually work (intensive bursts between books).
- [ ] **Suggested entry:** ~$10 for a one-issue (8-page) sample; full-book
      adaptation in the $80–200 range — dramatically under the $6K–$12K
      traditional cost, dramatically over the ~$0 marginal cost of DIY.

### Phase 3 — Proof & scale (months 4–6, ~$1–2k/mo)

- [ ] **Case studies are the only thing that closes this audience.** Sponsor
      3–5 prolific authors to adapt a full book and publish a transparent "what
      it cost, what it earned, what I'd do differently" writeup. No ad beats a
      peer's revenue data.
- [ ] **Consistency is the headline feature.** It's the universal complaint.
      Build one demo reel showing the same character across 50 panels and put it
      above the fold. Nothing else matters if this isn't visibly solved.
- [ ] Light retargeting + newsletter to the waitlist. Still no cold paid — the
      ROI isn't there yet for an AI-skeptical niche at lean budgets.

### What NOT to do (at this tier)

- ❌ No cold Meta/Google paid ads (wrong audience fit, lean budget, anti-AI
  sentiment makes ad creative a minefield).
- ❌ No broad PR / TechCrunch launch (attracts the wrong audience — tire-kickers
  and AI-art Twitter backlash — not buyers).
- ❌ No "AI" in any headline or hero image.

---

## 6. Risks to monitor

| Risk | Severity | Mitigation |
|---|---|---|
| Author anti-AI sentiment | **High** | §4 positioning; never lead with "AI"; human-in-loop as product DNA. |
| Copyright Office denies protection to AI images | **High / structural** | Lean into human-authorship documentation; counsel users honestly; this is a *reason* to buy a tool that records creative direction, not a reason to avoid one. |
| KDP mandatory AI disclosure | Medium | Not a ban; disclosure is to Amazon, not always surfaced to readers. Monitor for tightening. |
| Dashtoon out-spends | Medium | They out-fund but carry contract/ethics baggage and use humans, not pure-AI — wedge is *author ownership + price*, not features. |
| ComicInk feature-overlap | Medium | They're indie-sized too. Win on author-specific positioning (they read generic "AI comic maker"; this reads "your novel, scene by scene"). |

---

## 7. Bottom line

**Name: `Scenewright`** at **`scenewright.ink`** (~$3 first year, ~$25/yr
renewal). Real dictionary word meaning "maker of scenes," reads as human craft in
an AI-hostile market, semantically matches the novel→scene→panel pipeline, and is
domain-clear on the thematically perfect `.ink` TLD. Two free backup domains
(`.co`, `getscenewright.com`) secure the brand for ~$35 total.

Marketing is **community-led growth built on the pipeline itself as content**, a
**free Chapter-1-artifact flywheel** for virality, and **positioning as
author-owned IP / human-directed craft** — the one thing every funded competitor
gets wrong and this AI-hostile audience needs to hear. Budget fits the lean tier
(~$0–2k/mo); paid acquisition waits until there are case studies with real
author revenue.

**Before brand-asset spend:** complete the USPTO trademark clearance (§1.6).

---

## Sources

**Competitive:**
- [ComicPad — Best AI Comic Generators 2026](https://www.comicpad.app/best-ai-comic-generators)
- [ComicInk.ai](https://www.comicink.ai/) / [book-to-comic blog](https://www.comicink.ai/blog/convert-book-to-comic-series) / [pricing](https://www.comicink.ai/pricing)
- [Writer Beware — Contract Critique: Dashtoon](https://writerbeware.blog/2024/05/10/contract-critique-dashtoon/)
- [TechFundingNews — Dashtoon $5M](https://techfundingnews.com/dashtoon-raises-5m-to-deploy-generative-ai-for-comic-creation/)
- [r/Wattpad — Dashtoon outreach & payouts](https://www.reddit.com/r/Wattpad/comments/1h5rpo4/dashtoon_reached_out_to_me_offering_to_adapt_my/)
- [LlamaGen pricing](https://llamagen.ai/pricing) / [novel-to-comic tool](https://llamagen.ai/tools/novel-to-comic)
- [Drawstory.ai](https://www.drawstory.ai/) / [graphic-novel page](https://www.drawstory.ai/graphic-novel)
- [Jenova Comic Creator](https://www.jenova.ai/en/a/comic-creator)
- [AI Comic Factory — HF Space](https://huggingface.co/spaces/jbilcke-hf/ai-comic-factory)
- [Perchance AI Comic Generator](https://perchance.org/ai-comic-generator)
- [r/aicomicmakers — why AI comics are hated](https://www.reddit.com/r/aicomicmakers/comments/1q9azzc/why_are_ai_characterscomics_so_hated/)
- [r/ComicWriting — consistency blocker](https://www.reddit.com/r/ComicWriting/comments/15pig0h/)

**Market:**
- [Publishers Weekly — Book Output Topped Four Million in 2025](https://www.publishersweekly.com/pw/by-topic/industry-news/publisher-news/article/99943-book-output-topped-4-million-in-2025.html)
- [Comics Beat — Graphic novel sales rose 9.2% in 2025](https://www.comicsbeat.com/graphic-novel-sales-rose-9-2-in-2025/)
- [Publishers Weekly — comics/graphic novels ~$1.94B in 2024](https://www.publishersweekly.com/pw/newsbrief/index.html?record=5455)
- [Webtoon IR — FY2024 results](https://ir.webtoon.com/news-releases/news-release-details/webtoon-entertainment-inc-reports-fourth-quarter-and-full-year/)
- [Reedsy — Cost to self-publish 2026](https://reedsy.com/blog/guide/how-to-self-publish-a-book/cost-to-self-publish/)
- [Creator Resource — page-rate finder](https://www.creatorresource.com/page-rate-finder-comic-book-publishers/)
- [Drawphics — How to Hire a Comic Book Artist 2026](https://drawphics.com/how-to-hire-a-comic-book-artist-2026/)
- [Book Cover Hub — cover design cost 2026](https://bookcoverhub.com/blog/book-cover-design-cost/)
- [Wifitalents — self-publishing industry statistics](https://wifitalents.com/self-publishing-industry-statistics/)

**Legal / sentiment:**
- [USCO Part 2 Copyrightability Report (PDF)](https://www.copyright.gov/ai/Copyright-and-Artificial-Intelligence-Part-2-Copyrightability-Report.pdf)
- [USCO AI hub](https://www.copyright.gov/ai/)
- [PatentNext — Zarya of the Dawn registration](https://www.patentnext.com/2023/04/u-s-copyright-office-partially-allows-registration-of-work-having-ai-generated-images-zarya-of-the-dawn/)
- [Brown Rudnick — Thaler / AI work ineligible for copyright](https://briefings.brownrudnick.com/post/102i8q0/copyright-office-rules-that-ai-generated-work-is-ineligible-for-copyright-lack-o)
- [Authors Guild — class action v. OpenAI](https://authorsguild.org/news/ag-and-authors-file-class-action-suit-against-openai/)
- [Authors Guild — Amazon AI disclosure policy](https://authorsguild.org/news/amazons-new-disclosure-policy-for-ai-generated-book-content-is-a-welcome-first-step/)
- [Inkfluence AI — KDP AI disclosure policy 2026](https://www.inkfluenceai.com/blog/amazon-kdp-ai-disclosure-policy-2026)

**Domains:**
- [Namecheap .ink](https://www.namecheap.com/domains/registration/gtld/ink/)
- [Porkbun Domain Pricing](https://porkbun.com/products/domains)
- [TLD-list .ink comparison](https://tld-list.com/tld/ink)

**Trademark:**
- [USPTO Trademark Search (TESS)](https://tmsearch.uspto.gov/)
- [WIPO Global Brand Database](https://www3.wipo.int/branddb/en/)
