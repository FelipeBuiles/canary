---
name: marketing-plan
description: Build or refresh Scenewright's marketing plan for an owner who is new to marketing. Combines live PostHog and Agentgrown numbers, competitor and community research, and canary's own strategy docs into one plain-language plan covering where to post what, whether ads are ready, promos to showcase, pricing, coupons, and missing features, then drafts this week's posts. Use for "marketing strategy", "what should I do this week", "where should I post", "should I run ads", "pricing", "coupons", or "what features are we missing". Recommends and drafts only. Never spends, sends, posts, or changes prices.
---

Migration layout: the skill is at Canary root in `.agents/skills/`; run its commands from `<Canary root>/marketing`. Treat that directory as `ROOT`, and paths below as relative to it unless explicitly marked Canary-root-relative. Canary is its parent directory and is read-only to marketing workflows.


# Marketing plan

The owner knows little about marketing. The plan is their main view of it, so write for them:

- Recommend one path per area. Do not hand them a menu of options.
- Define each marketing term the first time it appears, in a few plain words.
- Say who does each action: **you** (the owner), **drafted** (an agent wrote it and it is waiting in the desk), or **needs a canary change** (product code; the owner decides and builds it).
- Keep the whole plan readable in five minutes. Put supporting detail in separate reports and link to them.

## Ground rules

- Follow `AGENTS.md`. Every product claim in a draft cites a marketable fact from `knowledge/facts.yaml`.
- Never create an ad campaign, coupon, price change, email, or post. Never call a write tool. Every outward action is the owner's.
- Every number comes from a tool result or a cited file. Record its source, date window, and count of people beside it. Missing data is `unknown`, never zero.
- When fewer than 20 people reach a funnel step in the window, say the data is too thin to compare. Choose by the rule in step 4, not by percentages.
- A recommendation is a bet, not a forecast. Never promise a lift in signups, sales, or rankings.

## Read first

1. `knowledge/claims-policy.md` and `knowledge/canary-changes.md`.
2. The newest `intel/reports/*-marketing-plan.md`, if one exists. The new plan reports what happened since then.
3. Canary's current strategy, read-only. Check each file's **Status** line first. Treat superseded documents as background only.
   - `docs/proposals/showcase-and-growth-2026-09.md` is the current growth strategy. Read its sections "Who we are for", "Channels and sequencing", "Calendar", "Budget options", "Risks and guardrails", and "Decisions needed". Its core idea: showcase books prove the product, a creator loop spreads finished comics, and paid ads come last.
   - `docs/proposals/launch-readiness.md`, plus "Gates for a bounded paid test" in `docs/proposals/self-service-launch.md`. These decide when ads may start.
   - `docs/proposals/pricing-and-margin.md` for pricing constraints.
   - `novel_to_comic/src/novel_to_comic/server/routers/billing.py` (packs and checkout) and `routers/backoffice.py` (manual credit grants).

## Steps

### 1. Since the last plan

Compare the previous plan's "This week" actions with the desk. Draft statuses show what was approved and posted. Also check `intel/reports/` for new reports. List each action as done, not done, or unknown. Don't guess why.

### 2. Measure where things stand

Load the `growth-analytics` skill and run its Workflow 1 for the last 30 days. If a growth report from the last 7 days exists, reuse it. Write the readout as its own `intel/reports/<date>-growth.md`. Then make at most six read-only Agentgrown calls:

- `ga4_query`: sessions by source and medium, last 28 days, to show where visitors come from.
- `gsc_query`: top queries and pages by impressions, last 28 days, to show what people search for before they find the site.
- `keyword_volume` for at most ten phrases taken from those queries or from community threads. Label the results as provider estimates.

Read each tool's schema before calling it. Agentgrown bills each call (about US$0.01), so put the number of calls and the cost in the plan's Data line. `site_notes` with `add` writes, so don't pass `add`. If a source fails, mark that part `BLOCKED` with the real error and continue with the rest. If the session has no `mcp__posthog__*` or `mcp__agentgrown__*` tools, tell the owner to run this skill from `pi` opened in this directory.

### 3. Look outside

- **Competitors.** Reuse profiles in `intel/competitors/` updated in the last 30 days. Otherwise load `competitor-intel` and refresh at most three direct competitors, pricing pages first.
- **Community demand.** Reuse `intel/opportunities/` files from the last 14 days. Otherwise load `community-scan` and do one bounded search pass. Save the opportunities, but don't write replies yet.

### 4. Find the one bottleneck

The journey is: visit → sign up → create a project → first page ready → export → buy credits. Name the step where the most people are lost, with the counts. If counts are too thin, apply this rule: fix the latest broken step before buying more traffic. More visitors do not help if people who sign up never reach a finished page.

### 5. Decide each area

Give every recommendation the same fields:

```text
Do: <one sentence>
Why: <evidence, with its source>
Who: you | drafted | needs a canary change
Effort: <hours> · Cost: <money, credits, or none>
How we'll know: <one metric, its source, and the date we check it>
```

**Where to post what.** Choose at most three channels. Each must show real evidence of the audience, such as threads found in step 3, search queries from step 2, or a channel named in canary's growth strategy. For each channel, give who is there, what to post, how often, which skill drafts it, and the channel's own self-promotion rules with their URL. Prefer showing finished comic pages over describing the product.

**Ads.** The verdict is "Not yet" or "Ready for one small test". List each launch gate from `launch-readiness.md` and `self-service-launch.md` as pass, fail, or unknown, with evidence. Unknown counts as not passed. If the verdict is "Not yet", name the gate that would unlock ads and what the owner can do about it. If ready, propose one platform and one audience. Take a spending ceiling and stop rules from "Budget options" in canary's strategy and label them as proposals. Then load `ad-creative` to draft the ads. The owner sets the ceiling in the ad account.

**Promos to showcase.** "Promo" here means content that shows off the product, not a discount. Pick showcase books and pages that `knowledge/claims-policy.md` clears for the channel, with exact paths. Give a one-line story for each, such as "same chapter, two styles". Follow every page exclusion in the policy.

**Pricing.** State the current packs from the facts ledger and the price per credit for each pack. Compare competitors' prices only with a source URL and date, and say that credits don't compare across products. Respect the constraints in `pricing-and-margin.md`. Recommend at most one change, or say to keep the current pricing and why. A change names what changes, where it lives in canary (packs in `billing.py` and the displayed copy in `web/src/locales/*.json`), the risk, and how to tell whether it worked.

**Coupons and offers.** Check whether checkout accepts codes. Search `billing.py` for `allow_promotion_codes` or `discounts` in the Stripe session arguments. On 2026-10-27 neither was present, so customer-entered coupons need a canary change. One option needs no code: the operator credit grant (`POST /users/{user_id}/credits` in `backoffice.py`, behind the ops token) can give credits to hand-picked authors. Examples are beta testers, contest winners, or a creator who will share their comic. Public copy must never advertise free credits (see claims policy). Recommend at most one offer, with a total credit ceiling and how to track who used it.

**Missing features.** Propose at most three. Each needs evidence of one of these kinds: a funnel drop from step 2, a competitor feature with a source URL, or the same request in several community threads (link them). Write each as a canary issue proposal: title, problem, evidence, smallest useful version, and how to measure it. Do not edit canary or file issues. The owner does that.

### 6. Write the plan

Write `intel/reports/<YYYY-MM-DD>-marketing-plan.md`. Use headings and short lists, not wide tables, because the desk shows raw Markdown. Follow this template:

```markdown
# Marketing plan, <date>

Data: <window> · Sources: PostHog 630262, GA4, Search Console, <others> · Blocked: <none or which>

## The short version
<3-5 sentences: where things stand, the bottleneck, what to do this week.>

## This week
1. <action> · Who: … · Time: … · Draft: <drafts/... path or "none">
(at most three)

## Where things stand
## The bottleneck
## Where to post what
## Ads: <Not yet | Ready for one small test>
## Promos to showcase
## Pricing
## Coupons and offers
## Missing features
## Decisions only you can make
## Since the last plan
## Words used in this plan
## Evidence
```

Under "Words used in this plan", define only terms the plan actually uses. Examples: funnel, conversion rate, first-touch attribution, impressions, CTR. Under "Evidence", list every report file and source URL used.

### 7. Draft this week's work

For each "This week" action that is a post, reply, article, or ad, load the matching skill (`community-scan`, `content-seo`, or `ad-creative`) and write the draft. Write at most three drafts. Put each draft's path in the plan.

### 8. Check and hand back

Run `npm run check` and fix any errors in files you wrote. Then reply to the owner in chat with:

- the bottleneck, in one sentence;
- the three things to do this week;
- the decisions waiting on them;
- where to read the plan: open the local Canary `/backoffice`, select **Marketing**, then **Plans & reports**.

## Cadence

Refresh weekly and reuse fresh research. Refresh competitors and pricing monthly, or when `knowledge/canary-changes.md` shows a pricing or billing change.
