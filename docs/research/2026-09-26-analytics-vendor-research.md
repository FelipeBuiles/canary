# Launch analytics and feedback: vendor research

Implementation follow-up: the user authorized consolidation without a separate
synthetic-journey gate. See the [current operating guide](../reference/observability.md)
for implemented behavior and remaining activation steps. This research records the
decision basis, not evidence that cloud delivery is live.

**Status: Proposed.** Research checked on 2026-09-26. Recommendations are design judgments, not implemented behavior. Prices are published USD amounts before tax; recheck at purchase. This note compares vendor capabilities; the [launch learning plan](2026-09-26-launch-learning-system.md) owns Canary's implementation design.

The later [single-vendor assessment](2026-09-26-posthog-single-vendor.md) extends this recommendation to PostHog operational observability, subject to a synthetic integration proof. Sentry is the fallback.

## Recommendation

Use **PostHog Cloud for product exploration, the existing first-party event store for durable business outcomes, and a small private feedback inbox in Canary's existing backoffice**. Keep session replay off for launch. Send deliberately selected events, not arbitrary UI content. Do not build a general analytics dashboard or adopt a separate public feature-voting service yet.

For a sole developer, the scarce resource is time spent finding and fixing the next obstacle. Buying the funnel/path/cohort interface is a better trade than building it; collecting private contextual feedback is a much smaller feature than recreating analytics. This is a recommendation based on the capabilities and costs below, not a measured productivity result.

First-party-only is a reasonable fallback for a small invited cohort if weekly SQL review is acceptable. It removes one processor but leaves ordered funnels, return behavior, identity stitching, and exploratory analysis to the developer. A count of stage events per day does not establish how many individual users completed a journey in order.

## Options and current commercial facts

| Option | Verified entry cost and constraints | Fit for Canary (judgment) |
| --- | --- | --- |
| PostHog Cloud | Monthly free allowances: 1 million analytics events, 5,000 recordings, 1,500 survey responses. Free includes one project, one year of event retention; free replay retention is one month. Additional usage is dropped at a free/billing limit. Paid usage has per-product caps. [Pricing](https://posthog.com/pricing) | Best fit for cross-session activation, abandonment, cohorts, and joining browser intent with server outcomes. Enough allowance for a carefully instrumented launch. |
| Existing Supabase/Postgres + backoffice | No new analytics subscription if added to the existing database. Supabase Free has 500 MB database allowance; Pro starts at $25/month, with 8 GB disk per project and $10 compute credit covering one Micro instance. Compute, disk, and other use can add cost. [Pricing](https://supabase.com/pricing), [billing](https://supabase.com/docs/guides/platform/billing-on-supabase) | Best authority for server outcomes and private feedback. Low incremental cash cost, higher analysis/UI maintenance if used alone. |
| Plausible Cloud | At the displayed 10,000 monthly pageview tier, Starter is $9/month, Growth $14, Business $19; 30-day trial. Funnels, journeys, and custom properties require Business. Pageviews **and custom events** consume the allowance. [Pricing](https://plausible.io/), [plans](https://plausible.io/docs/subscription-plans) | Good alternative when the question is marketing traffic and same-visit conversion. Does not meet the main need to follow an author returning on another day. |
| Canny | Free supports 25 tracked feedback users. Pro starts at 100 tracked users for $99/month, or $79/month billed annually. A tracked user has a post, vote, or comment attributed to them. [Billing plans](https://help.canny.io/en/articles/9131812-canny-s-billing-plans) | Useful later for public requests, voting, changelog, and duplicate-request management. Too much process and potentially cost for the first small cohort. |

PostHog supplies funnels, paths, lifecycle analysis, dashboards, and notebooks for writing findings beside insights. This avoids a separate visualization product. [Product overview](https://posthog.com/products) The pricing page's static response did not expose the interactive overage unit-rate table; this note intentionally does not project paid per-event rates. Set a $0 launch budget and monitor dropped events instead of assuming collection continues beyond a cap.

Canny automatically increases paid tiers when tracked-user limits are exceeded unless a spend limit is configured; at that limit it stops tracking feedback from new users. Its Free offering includes public roadmap/changelog and unlimited posts/boards. [Pricing](https://canny.io/pricing), [plan details](https://help.canny.io/en/articles/9131812-canny-s-billing-plans) That feedback-specific identity/pricing model is separate from an analytics monthly-active-user count.

## Why PostHog fits, and what must be configured

**Identity:** PostHog can merge a locally assigned anonymous identifier with a stable authenticated `distinct_id`, then use that same ID for backend events. It supports cross-device/session analysis for identified people. Logout must reset identity. [Identity documentation source](https://github.com/PostHog/posthog.com/blob/master/contents/docs/product-analytics/identify.mdx)

For Canary, use an opaque analytics identifier derived from the authenticated account, not email, title, or manuscript name. Resolve account identity on the server; do not trust a browser-submitted account ID. Optional browser session IDs provide correlation, not authentication. Do not attribute a background job finishing hours later to a currently active browser session. Define environment and event-schema version explicitly; exclude development/operator traffic from launch metrics.

**Capture control:** The JavaScript SDK supports disabling autocapture, pageviews, recording, console capture, and other automatic collection; `before_send` can amend/drop events; opt-out and persistence controls exist. Disabling autocapture alone does not disable pageviews. SDK defaults change over time. [Configuration documentation source](https://github.com/PostHog/posthog.com/blob/master/contents/docs/libraries/js/config.mdx)

Proposed launch setup: explicit curated events only; replay, DOM autocapture, automatic pageviews/pageleaves, heatmaps, dead/rage clicks, browser logs, and duplicate error capture disabled. Under the single-vendor proposal, enable one deliberate PostHog browser exception path to replace Sentry after validation. Allowlist outbound properties after SDK enrichment so automatic URLs/referrers cannot bypass application validation. Use canonical room/route names, not raw project URLs or query strings. Test the actual outgoing payloads against the pinned SDK version. Retain Sentry until the replacement proof passes.

**Storage and deletion:** PostHog offers US and EU clouds; its EU service is hosted in Frankfurt. It can discard client IPs, although enrichment may process them before discard. Deleting a person requires explicit event/recording deletion options; event deletion is asynchronous. [Storage controls source](https://github.com/PostHog/posthog.com/blob/master/contents/docs/privacy/data-storage.mdx)

Choose the cloud region deliberately, minimize location/IP collection, and include both systems in account-deletion handling. A pseudonymous ID remains linkable by Canary; describe collection accordingly. First-party transport does not itself make product analytics exempt from privacy requirements. Decide launch jurisdictions, consent/opt-out behavior, disclosure, and retention before production activation; this research does not establish a jurisdiction-specific legal basis.

## Replay is unusually sensitive for this product

PostHog masks form inputs by default, but **general rendered text is not masked by default**. Other elements require explicit blocking, such as `ph-no-capture`; URL redaction is separate. Masking runs before data leaves the browser. [Web replay privacy source](https://github.com/PostHog/posthog.com/blob/master/contents/docs/session-replay/_snippets/web-privacy.mdx) Replay can also capture network requests/responses; headers and bodies can contain sensitive data. [Replay privacy source](https://github.com/PostHog/posthog.com/blob/master/contents/docs/session-replay/privacy.mdx)

A novel preview, cast description, generated comic, lettering canvas, signed asset URL, prompt, and filename may all expose private creative work even if every input is masked. Accordingly, keep replay off at launch. If explicit user-approved debugging later justifies it, use an opt-in, limited safe surface, blocked manuscript/art/editor subtrees, all text/input masking, no network bodies/headers or console capture, short retention, and a verification pass using seeded sensitive strings and images. Default input masking is not sufficient evidence that creative content is protected.

Plausible avoids persistent identifiers and deliberately cannot recognize a visitor across days/devices. It retains event/session records for aggregate analytics, excludes most query parameters, and processes/stores visitor data in the EU. [Data policy](https://plausible.io/data-policy) This is attractive for acquisition measurement, but its privacy model makes it a poor replacement for Canary's multi-day author journey analysis. Adding it beside PostHog at launch creates overlapping instrumentation with little immediate benefit.

## Feedback: minimal private inbox versus vendor surveys

PostHog supports a feedback button/tab, popover surveys, custom API-driven UI, and hosted surveys. In-app responses can join identified users; surveys can target a user event. Its survey creation docs say multiple questions require subscribing to surveys, despite the general pricing page's free response allowance. Confirm the exact account entitlement before depending on multi-question surveys. [Survey documentation source](https://github.com/PostHog/posthog.com/blob/master/contents/docs/surveys/creating-surveys.mdx)

**Recommended initial feature:** a persistent “Feedback” action opens a small form: category (`problem`, `idea`, `praise`), message, and optional permission to follow up. Attach minimal trusted context (account, room, project/edition/page ID where permitted, app release, safe error reference). Display the attached context before submission. Save prose privately in Supabase and expose a simple existing-backoffice list with new/reviewing/resolved status and a link to a manually created issue. Send analytics only category, safe context, and feedback ID. Do not collect screenshots or manuscript excerpts automatically.

This is a proposed implementation, not a claim of existing functionality. Protect feedback reads with authorization/RLS; Supabase warns that service keys bypass RLS and must not be exposed in browsers. [RLS documentation](https://supabase.com/docs/guides/database/postgres/row-level-security) Bound message size, rate-limit submissions, preserve ownership checks, and include retention/deletion. Keep a working email fallback when the form fails.

If launch time cannot cover even this small inbox, a single-question PostHog feedback button is a reasonable faster substitute after disclosing its processor role. Do not operate both free-text pipelines initially. Move to Canny only when duplicate requests, public status communication, or voting have become a demonstrated workload.

## Turn measurements into learning

Proposed weekly review, requiring roughly 30–45 minutes rather than a new reporting platform:

1. Review one ordered activation funnel, time-to-first-page distribution, and first-week return behavior. Show counts and denominators; separate incomplete observation windows from abandonment.
2. Inspect the largest drop-off using server failures and private feedback. Distinguish paid generation waiting, deliberate approval checkpoints, browser abandonment, and actual terminal failures.
3. Read all new feedback from the initial cohort. Tag the underlying need, not just the requested solution. Contact users only through the agreed follow-up workflow.
4. Write a short dated learning record: question, cohort/time window, evidence links/counts, observations, competing explanations, confidence, decision, owner, and next measurement date. Redact prose before putting it in the repository.
5. Select at most one or two changes and compare the next eligible cohort. At small samples, treat repeated reports as hypotheses and individual feedback as qualitative evidence; avoid claiming causality from a before/after chart.

Use PostHog notebooks for live linked analysis and repo learning notes for durable decisions. No vendor automatically establishes why an author stopped. Human review connects the behavioral evidence, feedback, and the specific product change.
