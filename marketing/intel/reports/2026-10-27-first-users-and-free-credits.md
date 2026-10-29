# First users and free credits, 2026-10-27

Supporting detail for `intel/reports/2026-10-27-marketing-plan.md`. It answers two owner questions: how to bring in the first authors who test the product, and whether new accounts should get free credits.

Data: PostHog 630262, production, internal users excluded. 3 read-only SQL calls, run 2026-10-28 about 01:00 UTC, on top of the 8 calls in `intel/reports/2026-10-27-growth.md`. No Agentgrown calls in this refresh.

## What the fresh data says

- Since 2026-10-20, PostHog recorded no `account_created`, `project_created`, `page_ready`, or `checkout_started` events from outside users. The only product event was `api_request_completed` (24 rows, 7 people).
- Page views per day since 2026-10-20: 5, 0, 1, 1, 5, 0, 3 people (Oct 20 to Oct 26). Days with no row are counted as 0.
- Cold Open events (`cold_open_printed`, `cold_open_favorite`) appear only in `environment = development`: 2 and 4 rows, 1 person, the last on 2026-10-27 18:19 UTC. **No production Cold Open has ever run.** Whether the production server runs the Cold Open code at all is unknown.

So the problem from this morning hasn't changed. No outside author has seen their own story drawn, and no new authors are arriving.

## Free credits: the recommendation

**Yes, give new authors a free first taste. It has to cover reading the opening chapter, not only the Cold Open. Add hand-given credits only for authors you invite yourself.**

Correction from the owner, 2026-10-27: the Cold Open is free, but it only runs during extraction, and extraction costs credits. A new account with no credits can't start extraction, so it never reaches the free page. The Cold Open on its own is not a free first page.

Three layers, from widest to narrowest:

1. **Every new account: a free read of the opening, which unlocks the Cold Open (needs a canary change).** Canary already pays for one Cold Open per account: one page of the author's opening, in three looks (`docs/proposals/cold-open-2026-10-26.md`, "Who pays"; default 1 per account, `server/cold_open_jobs.py:44`). The Cold Open needs only the first Extract section ("Extract section 1 ... source/opening.json", same doc, "The flow"). The smallest change: canary also pays for Extract section 1 of the account's first project, with a length cap. The author uploads, sees their own page in three looks, and meets the credit wall after that, when the rest of the book is read. This is better than credits in the balance. It leaves no unspent balance that never expires, it cannot be spent on anything else, and its cost is one section plus one Cold Open. Today `JobCommand` rejects a sponsor on any operation other than the Cold Open (same doc, "Who pays"), so this is product code. Before it serves real traffic:
   - Measure what Extract section 1 plus one Cold Open cost. Both are unknown today.
   - Decide the length cap, for example the first chapter only.
   - Finish the doc's three "Before shipping" steps: restart and deploy, review the house looks on two or three sample stories, and run one real upload end to end.
   - Measure what one Cold Open costs. The usage events record provider cost with `sponsor = cold_open`. Today the cost per Cold Open is unknown.
   - Add an overall spending cap. I found only the per-account limit, not a total budget. Throwaway accounts could each take one free page. Canary's own pricing policy asks for "a per-user limit, total budget cap, abuse controls" before any sample grant (`docs/proposals/pricing-and-margin.md`, "Acquisition implications").
   - Fix or accept the sensitive-scene risk. In the first local run, one of three pages was blocked because the chosen scene showed a suicide attempt (same doc, "Observed in the first local run").
2. **Invited authors: an operator grant of 1,200 credits** (credits you add to one account by hand, through `POST /users/{user_id}/credits` in `backoffice.py`). This takes an author past the first page to a short excerpt they can export. The cap is unchanged from the plan: 10 authors, 12,000 credits in total, through 2026-11-24. Put `first-pages-2026-11` in each grant's reason.
3. **No automatic signup credits for now.** Reasons:
   - Credits never expire (fact `no-subscription-credits-never-expire`), so every credit you hand out remains a delivery obligation until it is spent.
   - Nobody is signing up, so a signup bonus would test nothing this month.
   - Canary's pricing policy lists caps, abuse controls, and a measured lift as preconditions. None of them exists yet.
   - If the sponsored opening can't be built soon, the fallback is a small automatic welcome grant sized to Extract section 1 of a short chapter. That needs the same caps, and it leaves balances that never expire.
   - Revisit after 20 or more new accounts have had the free opening.

**What it costs (estimate, not measured).** At full use, 1,200 credits are about US$6 of provider spend at the 2× markup example in `pricing-and-margin.md`, and up to US$12 at the 1.0 runtime fallback. The production setting is unverified. Ten grants come to at most about US$60 to US$120. The Cold Open's cost per account is unknown until it is measured.

**An unexplained case.** The one outside author who hit the credit wall was stopped at the `plan` stage, not at extraction (PostHog `credit_blocked`, `stage = plan`, 60 days, 1 event). That author had already paid for extraction somehow, but no purchase was ever recorded. Check that account's ledger in the back office: an earlier grant, a team member's account that isn't marked internal, or a gap in the events. Separately, PostHog emits `credit_blocked` only from the stage runner (`server/pipeline_operations.py`). An author blocked at extraction may leave no `credit_blocked` event at all, so the two other stalled authors could have hit the wall without a trace.

**What we don't know.** Whether 1,200 credits are enough to finish and export a short excerpt. Canary says not to assume that (`pricing-and-margin.md`, "Decision"). Watch `credit_blocked` among grant recipients. If several hit it before exporting, the problem is scope or price, and the grant size is not the fix.

**Public copy.** Never advertise free credits, free pages, or "on the house" in posts, ads, or the site (`knowledge/claims-policy.md`, banned claims). The workspace rule also keeps credit amounts and free offers out of outreach. Canary's tester kit says the opposite: covered generation may be mentioned "only in the private welcome message" (`docs/ops/tester-recruitment-2026-10.md`, "The tester offer"). You decide which rule applies. Until you do, the notes below promise nothing about cost.

## Where the first ten authors come from

Ranked by how likely each is to produce an author who reaches a first page in the next two weeks. All of these are personal, unpaid, and done by you.

1. **The 7 people who already have accounts.** They are the cheapest to reach, and 3 of them started a project. Grant credits to the 3, then send the "stalled author" note below. The other 4 get the "signed up, never started" note. This is the plan's action 1.
2. **Personal invitations to AI-open indie authors.** Choose authors who have publicly used AI covers or AI writing tools. Good places to find them: the Royal Road and Kindle Unlimited genre authors in canary's first segment, and members of AI writing tool communities (Sudowrite, NovelCrafter, NovelAI, Future Fiction Academy), as listed in the tester kit's Tier 1. Send 10 this week. The base copy is the kit's "Spotlight DM". Use the version below, which removes the line about cost.
3. **AI writing tool Discord servers and groups.** Join two, take part for a week, then ask a moderator whether you may share a showcase book and look for testers. Canary's kit calls these "highest intent". Their rules are unverified here, so start next week.
4. **BetaList.** It exists to match pre-launch products with early testers (tester kit, Tier 2). Read its submission terms at https://betalist.com/ before submitting. Wait until the Cold Open runs in production, so that testers arriving from it get their first page.
5. **r/WritingWithAI, weekly tools thread only.** The kit names it as the best fit on Reddit. Its rules could not be fetched (Reddit returned HTTP 403 twice today), so no draft yet. Read https://www.reddit.com/r/WritingWithAI/ rules yourself first.

Not yet: ads, search articles, Show HN. Show HN needs a product someone can try without a sales call. A first page behind a purchase does not meet that bar yet.

**What every tester gets:** a direct line to you, and a comic from their own chapter they can share. **What you ask of them:** make one comic within a week, answer five questions, and say where they got stuck. Use the intake questions from canary's tester kit, "The tester offer".

**The best result** is an author who posts their own comic with a link back. Ask everyone who finishes whether they would share it.

## Note templates (private, sent by you)

These are 1:1 messages, not public drafts. They make no claims about prices, credits, or free pages. Read each one before sending, and personalize the first line.

### Stalled author (started a project, no page yet)

> Hi [name], I'm [your name], and I build Scenewright. You started adapting [project or "a story"] a few weeks ago and didn't get to your first page. I'd like to know what stopped you. I've set your account up so you can carry on and draw your first pages whenever you want. If you'd tell me in a line or two where it got confusing or what put you off, that would help me a great deal.

### Signed up, never started

> Hi [name], I'm [your name], and I build Scenewright. You made an account but didn't start a project. Was something unclear, or was it just not the right moment? If you'd like to try it with one chapter, I'm happy to walk you through it, and I'd value a reply even if it's "not for me".

### Spotlight invitation (AI-open indie author)

> Hi [name], I've been reading [book or serial], and I think [specific scene] would make a great comic. I build Scenewright, a studio that turns a novel into a comic (here's a finished example: [reader link to The Monkey's Paw]). I'm looking for a few authors to adapt an opening chapter and tell me honestly where it falls short. You choose the look and approve the characters before pages are drawn, and the comic is yours to share. If you'd rather not, no worries at all.

Claim notes for the invitation: "turns a novel into a comic" is fact `what-it-is`. Choosing the look and approving the cast are facts `step-look` and `step-cast`. The Monkey's Paw is fact `book-monkeys-paw`, and the reader link must be the published showcase URL, which you open yourself first. "Yours to share" rests on `author-owns-manuscript`. Don't say anything stronger about copyright (fact `generated-copyright-limits`).

## How we'll know

- Accounts that reach `page_ready` within 14 days, among grant recipients and invited authors. Checks on 2026-11-10 and 2026-11-24. Baseline: 0 of 7.
- Once the Cold Open is live: `cold_open_printed` in production, its `latency_ms`, and the absorbed provider cost per Cold Open.
- Grant recipients who hit `credit_blocked` before exporting.
- Replies to the notes, counted by hand.

## Sources

- PostHog 630262, three `execute-sql` calls (event counts since 2026-10-20, Cold Open events by environment for the last 30 days, daily page views). Filters: `properties.environment = 'production'` and `$internal_or_test_user` false, except the environment split.
- Canary (read-only, lock `83b9d06a`): `docs/proposals/cold-open-2026-10-26.md`, `docs/proposals/pricing-and-margin.md`, `docs/proposals/showcase-and-growth-2026-09.md` ("Decisions needed", item 5), `docs/ops/tester-recruitment-2026-10.md`, `novel_to_comic/src/novel_to_comic/server/cold_open_jobs.py`, `server/routers/backoffice.py`.
- Rules pages not fetched: https://www.reddit.com/r/WritingWithAI/ (HTTP 403 on 2026-10-27). https://betalist.com/ was not fetched.
