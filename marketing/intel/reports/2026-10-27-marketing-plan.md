# Marketing plan, 2026-10-27

Data: PostHog 2026-09-29 to 2026-10-27 (28 days, UTC, production, internal users excluded), rechecked 2026-10-28 about 01:00 UTC · Sources: PostHog 630262 (8 calls, plus 3 in the evening recheck), GA4 and Search Console through Agentgrown (6 calls, US$0.30), keyword estimates (DataForSEO through Agentgrown), canary at lock `83b9d06a`, today's competitor and community reports · Blocked: none. Search Console query wording is unknown because Google returned no query rows. Reddit and Royal Road rules pages were not fetched (earlier today).

This refresh replaces this morning's plan, which had no live numbers. The evening recheck adds the free-credits answer and a ranked list of where the first testers come from: `intel/reports/2026-10-27-first-users-and-free-credits.md`.

## The short version

Seven people created accounts in the week of September 28. Nobody has signed up since October 4. Of those seven, three started a project and one picked a style. **None reached a finished first page.** Nobody has exported or bought credits yet. New accounts most likely have to buy before any page is drawn. One author hit the credit wall, opened checkout, and cancelled.

So the job is not more visitors yet. It is getting a few real authors all the way to their own first pages, by hand. Then we see what they do next. No ads, no price change, and no public coupon.

On free credits: yes to a free first taste. It has to cover reading the author's opening chapter, because the Cold Open's free page only runs during extraction, which costs credits. Give hand-added credits to authors you invite now. Then build a free read of the first chapter in canary. Don't add automatic credits to the balance.

## This week

1. Get the three authors who started a project to their first pages. Add credits to each account by hand, then send a short personal note asking what stopped them. · Who: you · Time: 1.5 hours · Draft: none (personal message; see "Coupons and offers")
2. Port the homepage line fix. The homepage is the most-viewed page (117 people in 28 days). · Who: drafted, then you port it into canary · Time: 30 min · Draft: `drafts/landing/2026-10-27-process-intro-matches-product.md`
3. Invite 10 AI-open writers to be founding testers. They get the same hand-added credits once they start a project. · Who: you · Time: 3 hours · Draft: none. Use the invitation note in `intel/reports/2026-10-27-first-users-and-free-credits.md`. It is canary's "Spotlight DM" without the line about cost.

In canary, separately: have canary pay for Extract section 1 of each account's first project, with a length cap and a total spending cap. Then finish the Cold Open's "Before shipping" steps. With both, an author who signs up later sees their own page before paying. · Who: needs a canary change · See "Coupons and offers".

No public post this week. Reddit blocked the r/WritingWithAI rules page again (HTTP 403), and drafts wait for verified rules.

## Where things stand

All numbers below are from PostHog, 2026-09-29 to 2026-10-27. "People" counts browsers, and one person can appear twice. Details: `intel/reports/2026-10-27-growth.md`.

- **Visits:** 182 people viewed a page. By week: 134 (Sep 29 to Oct 4), 33, 7, 11, then 3 on Oct 26. The launch spike is over.
- **Sign up:** 20 people opened `/signup`, 7 submitted it, and 7 accounts were created. All 7 came in the first week. Since then: 0.
- **Create a project:** 3 of 7 accounts (within 14 days).
- **Choose a style:** 1 of 7.
- **First page ready:** 0 of 7.
- **Export:** 0. The export event has never reached PostHog.
- **Buy credits:** 0 purchases. 1 person was blocked for credits, 1 started checkout, and 1 cancelled it. Purchases have never been recorded. Check Stripe once to confirm.
- **Where accounts came from:** 5 of 7 have no recorded source (`unknown`). The other 2 come from two known sources, combined here because each is under 5.
- **The public reader works as proof.** 26 people opened a showcase book (`/read/:id`).
- **Google:** GA4 counted 48 sessions in 28 days, every one "direct" or unattributed (2026-09-29 to 2026-10-26). Search Console: 27 impressions and 1 click, 2026-09-27 to 2026-10-24. Search brings almost no one yet.
- **Production can draw pages.** The team's internal test account produced 84 `page_ready` events in production over the last 56 days. The pipeline works. Outside authors aren't reaching it.

## The bottleneck

**Create a project → first page ready: 3 accounts started a project, 0 got a page.**

Every step has fewer than 20 people, so the percentages mean little. The rule for thin data is to fix the latest broken step before buying traffic. That step is the first page. More visitors won't help if nobody who signs up ever sees their own story drawn.

Likely cause (inference, not proven): canary's server code shows no free starting credits, so the first page sits behind a purchase. The one checkout attempt was cancelled. Other explanations are still open: an author who simply lost interest, a confusing step before pages, or events that never arrived.

Inflow also stopped after October 4. That matters next. With zero new signups, any fix to the first page will go untested unless we bring in a few authors by hand. That is why actions 1 and 3 go together.

## Where to post what

A **self-promotion rule** is a community's rule about when you may mention your own product.

**1. Personal invitations to AI-open indie authors** (main channel this month)

- Do: 10 personal invitations this week, then 5 a week, to authors who have publicly used AI covers or tools.
- Why: we need a few authors we can follow to a finished page. Canary's strategy ranks author partnerships second (`docs/proposals/showcase-and-growth-2026-09.md`, "Channels and sequencing"). Web-serial and indie genre authors are its first segment.
- What to send: the "Spotlight DM" from canary `docs/ops/tester-recruitment-2026-10.md`, plus a link to a finished book in the reader. No prices, credit amounts, or free offers in writing (claims policy).
- Rules: each platform's messaging rules. Never message someone who has spoken against AI art.
- Who: you · Effort: 3 hours this week · Cost: none, plus the credits in "Coupons and offers"
- How we'll know: invited authors who reach `page_ready` within 14 days, from PostHog. Check 2026-11-10.

**2. Reddit: r/WritingWithAI, with r/SideProject as backup**

- Do: one showcase post of The Monkey's Paw that links to the reader and explains how it was made, honestly.
- Why: the reader is already the third most-viewed public page (26 people). Canary's tester kit names r/WritingWithAI as the best fit. Its Monkey's Paw kit lists r/SideProject, the r/aiArt self-promotion thread, and r/AIcomics (`docs/ops/monkeys-paw-community-posts.md`).
- What to post: the page 1, 4, and 9 carousel from the canary kit, plus "what worked, what's hard". Open the reader link yourself first; the kit says it was never checked live.
- How often: one post this week at most, then the weekly tools thread.
- Rules: unverified. Our fetch of the rules pages failed. Read https://www.reddit.com/r/WritingWithAI/ rules before posting. Per canary's kit, tools belong in the weekly "Promote, Share, Discover" thread.
- Who: you · Effort: 1 hour · Cost: none
- How we'll know: new accounts with first-touch source `reddit.com` in PostHog. Check 2026-11-03.

**3. Royal Road forums** (later in November)

- Do: join in for a week, then ask staff whether you may share an AI-assisted comic in an author-tools area.
- Why: web-serial authors are canary's first segment (strategy, "Who we are for").
- Rules: unverified (our fetch got "HTTP 403: Forbidden"). Read https://www.royalroad.com/forums first.
- Who: you · Effort: 1 hour · Cost: none
- How we'll know: accounts with source `royalroad.com`. Check 2026-11-24.

Not now: search articles. "ai comic generator" has about 2,400 US searches a month, but that is a provider estimate for a broad phrase. Our own phrases ("novel to comic", "turn my novel into a comic") returned no volume data. Short videos also wait until authors finish.

## Ads: Not yet

Each gate is pass, fail, or unknown. Unknown counts as not passed.

- Launch readiness Gate 1 (money, accounts, recovery): unknown. The checklist in `docs/proposals/launch-readiness.md` is still open.
- Launch readiness Gate 2 (an author finishes without help): **fail**. 0 of 7 accounts reached a first page (PostHog cohort, accounts created 2026-09-15 to 2026-10-13).
- Launch readiness Gate 3, P0 items (crash recovery, alerts, release drill): unknown. No exercise recorded.
- Paid-test gate 1, production safety: unknown. Every scorecard item reads "unverified".
- Paid-test gate 2, demonstration: pass. Finished showcase books are public with honest labels, and 26 people opened them in 28 days.
- Paid-test gate 3, independent use (10 paid authors, at least 80% export in 7 days): **fail**. 0 paid authors, 0 exports.
- Paid-test gate 4, economics (positive contribution after costs): **fail**. 0 purchases.
- Paid-test gate 5, acquisition measurement: **fail**. 5 of 7 accounts have no recorded source.

The gate that unlocks ads is **independent use**: real authors who pay and finish. This week's actions 1 and 3 are the start. For scale: the broad phrase "ai comic generator" is estimated at US$4.50 per click (**CPC**, cost per click; provider estimate). With no purchase yet, every paid click would be pure cost.

## Promos to showcase

"Promo" here means a post that shows finished pages, not a discount. These are cleared for organic posts only. Credit the author every time, and label each post "AI-assisted, made by the Scenewright team, not customer work".

- **"Three wishes, one quiet evening."** The Monkey's Paw (W. W. Jacobs, public domain), pages 1, 4, and 9: `../showcase/books/06-the-monkey-s-paw/2a5fa050a4314db58d5540dd392a8d56/1.jpg`, `4.jpg`, `9.jpg`. Zoom in on "road's" in page 1's last balloon before posting. Not cleared for ads.
- **"A whole novel-length story, finished."** The Call of Cthulhu (H. P. Lovecraft, public domain), page 40: `../showcase/books/00-the-call-of-cthulhu/ccf1a606bd1747c4864d8a4770000891/40.jpg`. Horror needs a placement check.
- **"A fantasy for serial readers."** Elm and Keep (@strnglft, CC0), page 1: `../showcase/books/03-elm-and-keep/a689ec9c6e554562bdda2831d82a3ba2/1.jpg`. Review every other page before using it.

Never use Janitor pages 2 and up, Masque pages 1–2 and 13–24, or Kaitlin pages 4, 8, 10, and 15. Never use anything from `samples/`, `projects/`, or `showcase/video/`.

## Pricing

Current packs (facts `pack-starter`, `pack-standard`, `pack-creator`, `pack-studio`; checked against `billing.py`):

- Starter: US$12 for 1,200 credits, 1.00¢ per credit
- Standard: US$30 for 3,000 credits, 1.00¢ per credit
- Creator: US$70 for 7,500 credits, about 0.93¢ per credit
- Studio: US$150 for 18,000 credits, about 0.83¢ per credit

Competitors (accessed 2026-10-27, `intel/reports/2026-10-27-competitor-gaps-plan.md`): LlamaGen packs from US$9.99 (https://llamagen.ai/pricing). Narrora has a free account and a US$100/month Studio tier (https://narrora.com/). Novel2Comic sells packs at unknown prices (https://novel2comic.com/en). Credits measure different things in each product, so these prices don't compare.

- Do: keep current pricing.
- Why: one checkout attempt, cancelled, is far too little to blame the price. The data shows the problem comes before the price: no author has seen a page yet. Canary's pricing policy keeps these packs for the first launch (`docs/proposals/pricing-and-margin.md`, "Decision").
- Who: you · Effort: none · Cost: none
- How we'll know: `checkout_started` and `credits_purchased` in PostHog, plus Stripe. Check 2026-11-10.

## Coupons and offers

Checkout still accepts no codes. `billing.py` has no `allow_promotion_codes` or `discounts` (checked 2026-10-27, canary unchanged). A public coupon would need a canary change, and there is no reason for one yet.

Should new accounts get free credits? **Yes to a free first page, no to free credits in the balance.** There are three layers. Details and costs are in `intel/reports/2026-10-27-first-users-and-free-credits.md`.

- Every new account gets a free read of its opening, which unlocks the free Cold Open. Canary already pays for the Cold Open (`docs/proposals/cold-open-2026-10-26.md`, "Who pays"). But the Cold Open runs during extraction, which costs credits, so an account with no credits never reaches it. The change: canary also pays for Extract section 1 of the first project, with a length cap. The credit wall then comes after the author has seen their page. Who: needs a canary change. The remaining work: sponsor Extract section 1 (today only the Cold Open can be sponsored), measure the cost of one section plus one Cold Open, add a total spending cap (I found only a per-account limit, `server/cold_open_jobs.py:44`), and finish the Cold Open's "Before shipping" steps. How we'll know: share of new accounts with `cold_open_printed` in production, and later `page_ready`, within 14 days.
- Invited authors get the operator grant below.
- Automatic signup credits: not now. Credits never expire, so every grant stays an obligation until it is spent. Nobody is signing up, so a bonus would test nothing. Canary's pricing policy asks for caps, abuse controls, and a measured lift first. If the free opening can't be built soon, fall back to a small welcome grant sized to that first section. Revisit after 20 or more accounts have had the free opening.

- Do: give an **operator grant** (credits you add to one account by hand, through `POST /users/{user_id}/credits` in `backoffice.py`) of 1,200 credits to each author who has started a project but not bought. That means the 3 stalled authors now, then founding testers as they start. Cap: 10 authors, 12,000 credits in total, through 2026-11-24.
- Why: the funnel stops at the first page, and the likely wall is paying before seeing anything. A grant tests that guess with real authors and needs no code. It is the same size as the Starter pack. Don't promise a page count.
- Who: you · Effort: 10 min per author · Cost: up to 12,000 credits of generation cost
- How to track: put `first-pages-2026-11` in each grant's reason, and keep a private list outside this repo. In the note, say their account is ready to draw their first pages. Don't put credit amounts or "free" in writing. Never advertise free credits publicly (claims policy).
- How we'll know: grant recipients who reach `page_ready` within 14 days, and how many later buy. Check 2026-11-10 and 2026-11-24.

## Missing features

These are proposals for canary issues. You decide whether to file them.

**1. Let a new author see their own opening drawn before paying**

- Problem: no new author has seen their own story drawn. The first page sits behind a purchase.
- Evidence: 0 of 7 accounts reached `page_ready`. 1 hit `credit_blocked`, 1 started checkout, and 0 bought (PostHog, 28 days). Narrora offers "a free Narrora account — no credit card" (https://narrora.com/novel-to-comic). Novel2Comic gives "some free credits to try it on their own story" (https://novel2comic.com/en).
- Smallest useful version: Cold Open is built, with one sponsored Cold Open per account by default in production, but it has not run on paid providers (`docs/proposals/cold-open-2026-10-26.md`). But it runs during extraction, which costs credits, so a new account with no credits never sees it. Have canary also pay for Extract section 1 of the first project, with a length cap. Finish the Cold Open's "Before shipping" steps, measure the cost of both, and add a total budget cap next to the per-account limit. Canary's strategy already lists a related open decision: "Decide whether to test a free first style proof at sign-up" ("Decisions needed", item 5).
- Measure: share of new accounts reaching `page_ready` within 14 days. Today: 0 of 7.

**2. Record where every new account came from**

- Problem: we can't tell which channel works.
- Evidence: 5 of 7 accounts have first-touch source `unknown`. GA4 attributes none of its 48 sessions to a source. The export and purchase events have never reached PostHog, so a real export or purchase can't yet be told apart from none.
- Smallest useful version: check that `acquisition_source` reaches `account_created` across the confirmation email hop, and send one test export and one test purchase in staging to confirm the events arrive.
- Measure: share of new accounts with a known source. Target: most of them.

**3. A clear rule for failed pages**

- Problem: authors don't know what a failed page costs.
- Evidence: Novel2Comic states "a failed page is refunded" (https://novel2comic.com/en). Scenewright's failure billing can't be promised today (claims policy).
- Smallest useful version: decide the rule, make billing follow it, then say it on the pricing page.
- Measure: support questions about charges, counted by hand monthly.

## Decisions only you can make

1. Approve the first-pages grant: 10 authors, 12,000 credits in total, through 2026-11-24.
2. Approve and port the homepage line fix, including the Spanish and French lines.
3. Keep paid ads at US$0 until the independent-use gate passes.
4. Build the free first-chapter read so new accounts reach the free Cold Open, with a length cap and a total spending cap you choose (canary strategy, "Decisions needed", item 5). Recommended: yes. Until it ships, invited authors get hand-added credits, and there are no automatic signup credits.
5. Check in the back office how the one author blocked at `plan` paid for extraction. No purchase was recorded.
6. Decide whether a private welcome note to a tester may say generation is covered. Canary's tester kit allows it in private welcome messages. This workspace's rule keeps free offers out of all outreach. Until you decide, the notes promise nothing about cost.
7. Decide where the approved article goes. The public site has no blog route (fact `public-pages`).

## Since the last plan

Last plan: earlier today, 2026-10-27, with no live data.

- "Get the funnel numbers": done. This refresh ran the queries.
- "Fix the homepage line": not done. The draft is still `draft` in the desk.
- "Invite 10 founding testers": unknown. No record in this workspace.
- `drafts/blog/2026-10-27-start-with-one-chapter.md`: approved, not published.

Evening recheck (PostHog, since 2026-10-20): no new accounts, projects, pages, or checkouts from outside users. Cold Open has run only in development.

What changed: the bottleneck moved from "unknown" to a measured stop at the first page. The offer moved from rewarding authors who export (there are none) to unblocking authors who started a project.

## Words used in this plan

- **Funnel**: the steps from first visit to purchase, and how many people reach each one.
- **Bottleneck**: the step where the most people drop out.
- **Cohort**: a group of accounts that started in the same window, followed together.
- **First-touch source**: where a person first came from before signing up.
- **Session**: one visit, as Google Analytics counts it.
- **Impressions**: how often the site appeared in Google results. A **click** is when someone clicked it.
- **CPC**: cost per click, what an ad platform charges each time someone clicks an ad.
- **Gate**: a condition canary's launch docs say must be true before ads.
- **Operator grant**: credits you add to one account by hand.
- **Promo**: a post that shows off finished pages, not a discount.
- **Self-promotion rule**: a community's rule about mentioning your own product.

## Evidence

Reports and profiles:

- `intel/reports/2026-10-27-growth.md` (all PostHog and Agentgrown numbers, with query text)
- `intel/reports/2026-10-27-first-users-and-free-credits.md` (evening recheck, free-credit layers, ranked tester sources, note templates)
- `intel/reports/2026-10-27-competitor-gaps-plan.md`
- `intel/reports/2026-10-27-community-scan-plan.md`
- `intel/competitors/llamagen.md`, `intel/competitors/narrora.md`, `intel/competitors/novel2comic.md`

Canary files (read-only, lock `83b9d06a`, unchanged at today's sync):

- `docs/proposals/showcase-and-growth-2026-09.md`, `launch-readiness.md`, `self-service-launch.md`, `pricing-and-margin.md`, `cold-open-2026-10-26.md`
- `docs/ops/tester-recruitment-2026-10.md`, `docs/ops/monkeys-paw-community-posts.md`, `docs/ops/launch-scorecard-template.json`
- `novel_to_comic/src/novel_to_comic/server/routers/billing.py`, `routers/backoffice.py`, `server/product_events.py`

URLs (fetched earlier today for the competitor report): https://llamagen.ai/pricing, https://narrora.com/, https://narrora.com/novel-to-comic, https://novel2comic.com/en. Rules pages to read before posting: https://www.reddit.com/r/WritingWithAI/, https://www.royalroad.com/forums.
