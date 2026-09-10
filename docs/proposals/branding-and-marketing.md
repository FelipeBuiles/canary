# Scenewright — Proof-Led, Self-Service Launch Positioning

> **Status: Proposed launch positioning; implemented capabilities and external
> claims are identified separately below.** Refreshed 2026-09-09. Replaces the
> July naming/marketing research as the active proposal. This does not certify
> production readiness, name clearance, user demand, or legal rights.

## The strategic change

Help an indie fantasy author turn a short piece of their own story into a
comic excerpt they want to show readers. Let the author choose the story's
intent, visual direction and cast, then review the pages and export. The
product must complete that journey without the founder directing production,
fixing ordinary failures, or explaining billing in a call.

**Proposed positioning:** “Your story deserves to be seen.” Follow immediately
with the concrete explanation: “Turn a scene from your novel into a comic you
direct. Choose the look, review the pages, and export with one-time credits.”

The first target is **AI-open indie fantasy authors with an existing scene or
chapter and a reason to show it to readers**. Fantasy is a testable focus, not
a claim that other genres cannot work or that these authors already pay us.
Test a newsletter excerpt, launch teaser, or reader bonus as use cases; do not
promise that a comic will increase book sales. The alternative is postponing
visual adaptation or assembling a result across writing/image/layout tools.

“Hands-off” describes operating effort. It does not remove the author's
creative approval points or authorize silent paid retries. The business gets
more automated when ordinary users can succeed and recover through the
product, with exceptions visible to the operator.

## Current product baseline and claim boundaries

The code-backed workflow has eight stages, extract → brief → style → cast →
adapt → plan → draw → finish, grouped as Story, Look, Pages and Book. Creative
checkpoints are brief, style, cast and draw. See
[stage contracts](../reference/stage-contracts.md) and
[agent context](../reference/agent-context.md).

| Customer-facing claim | Evidence | Boundary |
|---|---|---|
| Bring your manuscript | Existing project upload/import flow and [UploadStep.tsx](../../web/src/components/wizard/UploadStep.tsx) | Starting with an excerpt is an onboarding recommendation; no measured universal page or runtime promise |
| Choose the look and approve the cast | Style selection, references and explicit checkpoints | Reference conditioning supports continuity; it does not prove perfect consistency |
| Review and revise complete pages | Draw, page issues, correction revisions and Finish contracts | Correction can cost credits; generating a revision alone does not verify a visual concern |
| Export PDF and CBZ | Finish/export implementation | Export success is not a printer/distributor acceptance or publication-quality guarantee |
| One-time credits; no subscription | [billing.py](../../novel_to_comic/src/novel_to_comic/server/routers/billing.py) and [TermsPage.tsx](../../web/src/pages/legal/TermsPage.tsx) | Packs begin at $12; no fixed pages-per-pack claim. See [pricing-and-margin.md](pricing-and-margin.md) |
| You retain your manuscript; we claim no ownership over generated output | Current Terms page | Do not substitute “copyright-safe,” exclusive rights, guaranteed copyrightability, or an unimplemented training/privacy promise |
| AI-assisted, directed by you | Actual workflow | State the AI role plainly near the workflow/proof, not only in a tiny footer |

No customer count, revenue result, testimonial, unassisted completion rate,
production reliability percentage, or measured cost per accepted page was
established by this review. Blank proof categories should stay blank until
there is evidence.

## Proof register: what is available now

At the start of this refresh the repository included four public marketing assets:

| Asset | What it can illustrate | What it cannot prove |
|---|---|---|
| [cthulhu-page.webp](../../web/public/marketing/cthulhu-page.webp) | An existing three-panel illustrated, lettered example, labeled in the library as *The Call of Cthulhu* by H. P. Lovecraft | Current-production provenance, generation time/cost, passing OCR, cross-page continuity, customer success, or an unassisted source-to-export journey |
| [anya-reference.webp](../../web/public/marketing/anya-reference.webp) | Example character reference imagery | The same character remaining faithful across a book |
| [rurik-reference.webp](../../web/public/marketing/rurik-reference.webp) | A second example character reference | A customer-approved cast or a measured fantasy cohort |
| [tavern-reference.webp](../../web/public/marketing/tavern-reference.webp) | Example location reference imagery | A location consistently realized in finished pages |

The Cthulhu page was added in commit `5a932e2` on 2026-09-07. No matching
source-to-render manifest, usage record, or current-profile revision chain was
located for the public asset. Its polished appearance is useful illustration,
not a substitute for provenance. The checked-in mock-replay documentation also
references Cthulhu fixtures; that does not establish this image's generation
mode. Do not present replay evidence as a real paid production.

**Editorial judgment after visual inspection:** the Cthulhu page's third
caption reproduces racialized language from the source. It is a poor opening
impression for a broadly welcoming author product. Prefer neutral existing
reference imagery or an explicitly labeled first-panel detail until a better
full-page sample exists. Do not silently alter a caption and present the result
as unchanged product output. Any detail crop must be labeled as a detail, not
as a complete page or a continuity test.

Do not label source text “public domain everywhere.” Before promoting a new
sample, record the precise source edition, territory/rights basis, reference
permissions, and authorization to publish. This is an evidence requirement,
not a new customer legal promise.

### Immediate proof: the latest development project

**User direction, 2026-09-09:** use a few assets from the latest `dcc1. 2`
project, which adapts *Dungeon Crawler Carl*. Local use of these artifacts for
this review is authorized; public promotion rights have not been established.
Keep the landing proof provisional, and confirm publication permission or
replace the examples before an external campaign. The current development
workflow uses `gpt-image-2` through a
Codex development adapter restriction. These can be shown now as authentic
**development examples**, once their exact source files and publication basis
are recorded. Preserve the output and label any crop or presentation edit.
They do not establish the deployed production profile, paid provider cost,
production latency or production completion rate.

The user's intended future move to `gpt-image-2.5` is a roadmap direction.
Expected quality improvement is a hypothesis; do not market it as an available
model or a demonstrated result. Record actual model/profile and funding per
sample rather than updating old samples' attribution to the future model.
See [self-service launch strategy](self-service-launch.md) and
[test campaign](first-scene-campaign.md) for the current delivery plan.

### The next measured proof asset: an inspectable mini edition

Make the next flagship demonstration a **small, consecutive sequence**, not
a collage of the best isolated generations. Use an owned original fantasy
excerpt or a source with recorded permission. Include the source excerpt,
approved character references, complete pages, one honestly documented
correction, and the downloadable export.

A proof manifest should record source/permissions, release SHA, fixed profile,
run date, page/revision identities, provider funding, number of attempts,
measured credits/cost scope, and which checks/human reviews occurred. Keep
private metadata internal; expose a readable account of the result and any
editing on the public page. Three to five consecutive pages is a proposed
proof scope, not the customer pack entitlement.

A useful caption is “Example adaptation · AI-assisted · [source/author] ·
[run date] · [scope and edits].” Add time or credits only once measured, with
all retries included. Add a customer quote only with their exact approved
wording and consent to publish. Never invent social proof to fill a layout.

## Updated market evidence

**Official sources accessed 2026-09-09.** These are vendor statements, not
independent product benchmarks. This focused comparison replaces the older
market-size tables, alleged universal author hostility, competitor funding
numbers, forum anecdotes, and unsupported willingness-to-pay estimates.
Those were not necessary to choose the first experiment and were not
revalidated.

| Competitor | Verified public statement | Implication / uncertainty |
|---|---|---|
| ComicInk | Dedicated pricing page says Plus is required to create, at $19.99/month with 4,500 monthly credits; one-off packs top up the plan, starting $9.99/1,500 credits. It describes 50 credits per comic page. [Pricing](https://www.comicink.ai/pricing) | The July assumption that its paid offer is purely one-off is stale. Its homepage still describes free entry and $9.99 packs without consistently disclosing the prerequisite: do not build an attack ad from this inconsistency |
| ComicInk | Markets recurring character/world references, multi-issue stories, and PDF/image exports. [Product page](https://www.comicink.ai/) | Continuity and export are category expectations, not safe exclusive advantages. Performance was not independently tested |
| LlamaGen | Pricing displays Standard at $18/month, alongside an annual offer billed $172.80; lists multi-page layouts, AI lettering and custom characters. [Pricing](https://llamagen.ai/pricing) | The old $9.99 subscription anchor is stale. Annual discounts and top-up packs must not be confused with monthly plan prices; credits are not comparable across products |
| SceneWrite | Adjacent storytelling app advertises storyboarding, persistent characters/worlds, conversational editing and AI video workflows. [Features](https://www.scenewrite.app/features/) | Similar spelling/sound remains a brand-confusion question. This product page is not a trademark search or clearance opinion |

**Response strategy:** say what our product lets the author do, show the
actual work, and make the spending decision understandable. Our no-subscription
purchase flow is a truthful benefit to state on its own. Do not claim that no
competitor supports it, that only we preserve rights, or that we outperform
another tool without a like-for-like reviewed experiment.

A prospect's “Why not use a generic image tool?” objection should lead to a
source-to-page demonstration: approved story decisions, cast references,
lettering, corrections and an export in one workspace. If that cannot be shown
clearly, the differentiation is not yet proved.

## Naming posture

Use **Scenewright** consistently in the current product and tests; keep
**Canary** for repository/internal references. The earlier domain availability
and registrar price tables are withdrawn. The app already uses Scenewright
and links under `scenewright.ink`; that alone is not proof of registrant
ownership or clearance.

Do not restart a naming exercise as a substitute for product validation.
Record a deliberate name decision before substantial irreversible brand
spend, accounting for the adjacent SceneWrite product. No legal clearance was
performed in this refresh, and no earlier “FREE domain” statement should be
reused. The substantive rationale worth retaining from July is the name's
craft-oriented tone; it does not establish rights or customer preference.

## Landing page and acquisition direction

The page should answer five practical questions in order:

1. **What can I make?** A short comic adaptation of my own story, beginning
   with an excerpt. Lead with the result and an honest visual example.
2. **Does it look good enough to try?** Let visitors inspect existing examples
   at useful size, with accurate labels; add the consecutive mini edition
   once verified. Avoid burying all output behind account creation.
3. **What do I control?** Explain Story → Look → Pages → Book in plain language.
   Make the AI role and author approvals visible.
4. **What will I spend?** Show actual credit packages or a clear link to them,
   no subscription, variable usage and pre-step estimates. Do not imply a
   signup grant, free generation or guaranteed full issue for Starter.
5. **What happens if I get stuck?** Explain saved progress, review/correction
   and the real support route, without promising instant human intervention
   or an unimplemented automatic remedy.

Use a direct start action plus a secondary “see an example” action. Account
creation should lead to a focused excerpt/sample path rather than a blank
workspace. “First issue” is a useful aspiration but should not imply an
implemented fixed-size bundle. Keep full-book capability available after
first value; it need not be the first purchase commitment.

### Proposed repeatable acquisition loop

Publish useful, high-intent content around adapting an existing scene and
show the result. Send relevant traffic to the matching proof and excerpt
start path. Measure completed paid exports and contribution, improve the
largest drop-off, then repeat. This can become a repeatable product funnel;
it does not depend on months of founder community participation or free
whole-book adaptations for influencers.

A bounded paid-search/message test can be appropriate **after delivery and
billing gates pass**. The old blanket ban on cold paid acquisition was an
unsupported channel assumption. Likewise, “80% of users from community” and
“authors resent every subscription” were assertions, not measured findings.
Use the [campaign plan](first-scene-campaign.md) for a spending ceiling, creative variants,
tracking, and stop rules; drafting it is not authorization to spend or send.

A customer-controlled share/export flow can later earn discovery from readers.
Sharing must be opt-in, with clear publication permissions. Do not impose an
unimplemented mandatory watermark or auto-publish private manuscripts.
Opt-in lifecycle messages should help a user return to the actual next step;
marketing consent, delivery limits and unsubscribe behavior must exist before
switching them on. No outreach is sent by this proposal.

## Retired launch ideas and remaining evidence

Retire the free full-Chapter-1 flywheel, unpaid influencer full-book service,
“AI only in the footer,” perpetual community posting as the acquisition engine,
fixed commissioned-art savings, blanket all-output copyright promises, and
“full novel in minutes.” They either increase operating burden, misrepresent
the workflow, or lack supporting evidence.

Retain the author-control position, precise rights language, flexible credit
purchases and proof from the author's actual story. Validate the narrow
fantasy/excerpt audience with real unaided use and payment. Repository evidence
supports product capabilities; public vendor pages support only the market
snapshot. Neither proves that Scenewright has achieved customer demand or
production reliability. The next decisive evidence is a real first paid
export completed without founder rescue.
