# Scenewright: earn the first scene, then the book

**Status: Proposed strategy, September 9, 2026.** This replaces the July
operator-assisted acquisition strategy. It does not certify production readiness
or authorize an ad purchase, email send, provider run, or deployment.

## The decision

Build a product an independent author can buy, use, and return to without a call.
Lead with **one strong excerpt brought to life**, then let a useful result sell
the larger adaptation. Keep the complete-book engine; reduce the commitment
required to experience its value.

The founder's job becomes reviewing exceptions and improving the system. A
customer still makes creative decisions: approves the Brief, selects Style,
approves Cast, reviews Draw. Hands-off operations must not silently approve
creative choices or resubmit ambiguous paid requests.

Our first audience hypothesis is English-speaking independent fantasy authors
who own a finished story, are comfortable with disclosed AI illustration, and
want an excerpt to share with existing readers. This is a segment to test,
not validated demand. Avoid promising sales lift or a publish-ready book.

## What changes

| Previous approach | New direction | Why |
| --- | --- | --- |
| Sell the whole graphic novel first | Start with a short, self-contained excerpt | Lower cost exposure and a clearer first success |
| Founder guides two authors through every step | Observe independent use; count every rescue | Assisted success hides product friction |
| Lead with broad AI/continuity claims | Let visitors inspect real artifacts, including limitations | Trust comes from something they can evaluate |
| Old panel-based book prices | Existing credit packs, measured complete-page costs | A pack is a balance, not a book guarantee |
| Launch date and checklist completion | Evidence gates, bounded acquisition, stop rules | Growth follows reliability and contribution |
| Daily manual outreach | One reusable campaign, self-service funnel, exception digest | A repeatable motion fits a small team |

The customer promise: **“Bring a scene worth seeing. Direct its comic
adaptation.”** No subscription; credit packs currently start at US$12.
Account creation does not imply free generation. A short excerpt is recommended,
not a new enforced input limit, fixed-price product, or promised page count.

## Product truth and remaining gaps

The repository implements eight stages, source-based adaptation, approved style
and cast conditioning, complete lettered pages, correction review, and PDF/CBZ
exports. It also implements durable paid-action admission, credit reservations,
account scoping, extraction budgets, and deployment drain. Local code and tests
are evidence of those mechanisms; they do not establish their deployed behavior.

The current [runtime guide](../reference/agent-context.md),
[readiness audit](launch-readiness.md), and
[deployment procedure](../deploy.md) take precedence over July snapshots.
This review did not inspect live customer, payment, or production telemetry.

### Deliver first, in this order

| Priority | Smallest useful delivery | Acceptance evidence | Suggested owner |
| --- | --- | --- | --- |
| P0: unattended recovery | Crash recovery for the single Machine/process, with admission journals retained; safe cached recovery separated from paid work | Kill/restart during idle, queued work, provider response, settlement, and export; no duplicate paid submission or lost balance; surface unresolved actions | Engineering |
| P0: production confidence | Exact release identity, strict readiness, live auth/billing checks, alert route, restored backup | Dated release packet; real two-account isolation, duplicate-payment/refund tests, backup restore and alert receipt | Engineering/operator |
| P0: representative proof | Use a few current dcc1.2 pages now; confirm public-use permission or replace before an external campaign | Clearly labelled development output now; current production source/export and spend record before cost or reliability claims | Product/author |
| P0: purchase clarity | Explain zero-balance behavior, packs, variable costs, held versus spent credits, and explicit Resume after top-up | Five independent users can explain what they buy before checkout; no expectation of a free book or fixed page count | Product |
| P1: first-scene setup | Excerpt selection guidance inside new-project flow, sensible defaults, readable progress and recovery actions | Author uploads a self-contained scene without support; no artificial approval bypass | Product/engineering |
| P1: reliable measurement | First-party source/cohort attribution joined to purchase and export; deduped business outcomes | Known test journeys reconcile to Stripe/ledger and artifact export; no manuscript or email in marketing event properties | Engineering |
| P1: exception operations | One actionable queue for stuck jobs, ambiguous charges, outages, refunds and restore failures | Alert once per incident, include safe next action and age; never auto-redraw an ambiguous paid result | Engineering/operator |
| P2: earned expansion | After successful export, invite another scene or a larger adaptation | Repeat purchase and second export measured independently of email opens | Product |

Keep the current one-Machine architecture for the first bounded launch. A queue
migration, second provider, subscriptions, affiliate program, marketplace, and
full rebrand are not prerequisites. Distributed execution is a separate design
once measured capacity requires it. Resolve the documented name-confusion risk
before material brand spend; a research finding is not legal clearance.

## What “low-touch” means in practice

Automate repeatable checks and reporting. Retain deliberate decisions around
paid ambiguity, refunds, rights, and creative acceptance.

| Trigger | Desired behavior | Human involvement |
| --- | --- | --- |
| Release candidate | CI, image build, drain, exact-version and strict dependency readiness checks | Approve promotion until recovery has been exercised |
| Web process exits | Bounded restart with durable journal inspection; no automatic paid replay | Only repeated crash or unresolved action |
| Page exists but its text check is incomplete | Replay saved evidence when possible; price missing paid OCR separately | User authorizes additional spend |
| Generation stalled / provider outcome unknown | Preserve receipt and credit state, block duplicate execution, notify with recovery context | Resolve ambiguity before resubmission |
| Checkout returns | Refresh the ledger; webhook is authoritative for credits | User explicitly resumes work |
| Export ready | Clear in-product download action; opted-in transactional notification is future work | User reviews the result |
| Weekly cohort closes | Calculate completion, intervention, cost, and acquisition outcomes | Review exceptions and one experiment decision |

The first operational target is at most **one scheduled 30-minute review per
week**, plus incident response. This is an aspiration to earn, not current
staffing capacity or a customer support SLA. Any mandatory rescue is recorded;
it is never hidden as “onboarding.”

## Gates for a bounded paid test

Thresholds below are initial decision rules, not industry benchmarks or proof of
statistical significance. Count unique authors, include failed starts, and use
an explicit seven-day outcome window. Do not select only attractive successes.

1. **Production safety:** release, auth/isolation, billing/reconciliation,
   restore/recovery, monitoring/support, and rights/name decisions have current
   evidence. No open severe billing, data-loss, or privacy incident.
2. **Demonstration:** at least one representative example can be inspected
   publicly with permission and accurate limitations. Perfection is not a gate;
   legibility, honest provenance, and suitability for the audience are.
3. **Independent use:** at least 10 paid authors have started their first
   adaptation; at least 80% export within seven days, at most 20% need operator
   rescue, and average operator effort is at most 10 minutes per started author.
4. **Economics:** positive contribution after consumed-credit revenue,
   provider cost (including failures/corrections), payment fees, refunds,
   variable infrastructure and support labor. Keep unused credits as a remaining
   fulfillment obligation; do not mistake top-up cash for earned margin.
5. **Acquisition measurement:** source attribution, payment and export outcomes
   reconcile. A CTA click or download request is not a purchase or an opened book.

Recruit the initial measurement cohort from permissioned, self-selected interest
without buying traffic. Let them use the product independently; offer help when
needed, and count it. The goal is no required kickoff calls. If ten authors
cannot finish economically without repeated rescue, fix that before amplifying
the funnel. Passing a ten-person sample authorizes only a small test, not scale.

The [campaign kit](first-scene-campaign.md) defines the next experiment and its
spend ceiling. The local [launch scorecard](../../scripts/launch_scorecard.py)
turns the recorded evidence into a repeatable hold/test recommendation. It does
not fetch telemetry, enforce ad spend, or replace evidence review. Copy the
[blank packet](../ops/launch-scorecard-template.json), fill it with reconciled
cohort counts and dated evidence links, then run:

```sh
python3 scripts/launch_scorecard.py path/to/completed-packet.json
```

Exit 0 recommends a bounded test; exit 1 holds for incomplete evidence or failed
thresholds; exit 2 rejects an unreadable packet. The blank packet intentionally
holds. Evidence links must record date, owner, environment and tested release;
the script checks their presence, not their contents or freshness. Review them
again after model, pricing, infrastructure or materially relevant code changes.
Count each paid starter once; include abandoned/failed productions and all
operator effort. Allocate gross revenue to consumed credits consistently;
`consumed_credit_refunds_usd` deducts only refunds against that consumed revenue,
once. Refunds of unused balances reduce the remaining fulfillment obligation,
not consumed-credit revenue. Include provider cost for granted work with zero
grant revenue; do not also deduct the grants' face value. Costs must include
failed attempts and support labor; unknown usage means `costs_reconciled: false`.

## Proof that sells honestly

Create a **“From the author's page to the reader's page”** example: exact source
excerpt, selected reference art, three consecutive complete comic pages, and
the downloadable short edition. Include one genuine correction with its actual
cost when available; showing what needed work makes the result believable.

Publish the source permission, run date, chosen production profile, actual
credits, correction count, and elapsed time as one example's facts. Separate
machine lettering checks from human review of story, continuity and art. Use
“development example” until it is customer work, and written consent before
using a customer's manuscript, images, name, or quote. Do not imply a reference
collage is a finished comic, or synthetic imagery is generated product output.

Existing Anya/Rurik/tavern references demonstrate visual direction. The user
selected the latest **dcc1.2** project for provisional page examples; use a few
consecutive pages without chasing perfect output. Identify them as development
examples, retain source/revision provenance, and revisit later. This project
adapts *Dungeon Crawler Carl*; public promotion rights are not established by
the local artifact. Confirm permission or replace it before publishing the
campaign. The old Cthulhu asset remains unsuitable and unused.

Per the user's development context, the dev-only Codex adapter currently uses
**gpt-image-2**. The intended future move is **gpt-image-2.5**, with an expectation
of improved continuity and less visual noise. That improvement is a hypothesis
to evaluate, not a claim on the landing page or a reason to delay process work.
Do not change routing in this launch pass. When switching, create a new fixed
edition profile and compare the same short source, cast/state references,
lettering, correction rate, actual cost and completion time. Existing editions
retain their profile; development subscription runs do not prove API margins.

## The first month, conditional on evidence

- **Week 1:** finish recovery/readiness gaps, validate a deploy and restored
  project, select existing development pages and establish the permissioned
  public proof kit. No new image generation is needed for the local landing pass.
- **Week 2:** observe the first independent users, reconcile actual costs and
  credit outcomes, remove the largest source of rescue. No launch-date promise.
- **Week 3:** if the gates pass, run the bounded campaign; review on days 3, 7,
  and 14 instead of publishing daily new content.
- **Week 4:** reconcile seven-day outcomes for the last entrant. Keep, revise,
  or stop the offer based on completed paid outcomes and contribution.

Success is a repeatable paid first excerpt with a useful export and manageable
exceptions. A larger launch is a consequence of that evidence.
