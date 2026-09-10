# Scenewright — Credit Pricing and Sustainable Self-Service

> **Status: Proposed commercial policy, with code-backed pricing facts.**
> Refreshed 2026-09-09. This replaces the July panel-based book-cost model.
> Package amounts are implemented; production configuration, measured margin,
> and any pages-per-pack promise require separate evidence. No runtime price
> or customer terms are changed by this document.

## Decision

Keep the existing one-time credit packages for the first self-service launch.
Sell the ability to turn a short excerpt into a reviewed comic, then expand
when the author likes the result. Do not sell “a full book for $25,” claim a
package covers a particular number of pages, or assume a first purchase will
finish an excerpt until current complete-page runs substantiate it.

The launch offer should reduce commitment through scope and visible proof,
not through an unbounded free chapter or founder-operated production service.
A small successful output that a customer can make unaided is more useful
commercial evidence than a cheap nominal page price.

## What the implementation actually does

| Setting or behavior | Checked-in evidence | Consequence |
|---|---|---|
| Credit conversion | `ceil(provider USD × credits per provider USD × markup)` in [credits.py](../../novel_to_comic/src/novel_to_comic/server/credits.py) | Conversion applies to usage debits; credit-pack purchase price is separate |
| Conversion factor | `PULP_CREDITS_PER_PROVIDER_USD=100` in [.env.example](../../.env.example); runtime default 100 | At 2× markup, $1 of metered provider cost converts to 200 credits before per-call rounding |
| Markup | Example environment specifies `PULP_MODEL_COST_MARKUP=2.0`; runtime fallback is **1.0** | Never infer live 2× markup from the package table; record effective deployed value |
| Reservation cushion | Default `PULP_RESERVATION_BUFFER=1.25` in credits.py | Temporary hold, not an extra final charge |
| Failed requests | `provider_usage_only` in example environment; billing behavior in [ai/client.py](../../novel_to_comic/src/novel_to_comic/ai/client.py) and [ai/finalisation.py](../../novel_to_comic/src/novel_to_comic/ai/finalisation.py) | Failure billing depends on the usage evidence reaching finalisation; it is not a universal guarantee that providers charge nothing on timeouts |
| Non-production funding | Mock and Codex-subscription usage bypass public credit debit in credits.py | Local free runs cannot establish production paid-run economics |
| Unknown pricing | [usage.py](../../novel_to_comic/src/novel_to_comic/usage.py) can return zero for unknown pricing; credits.py applies a one-credit floor to billable activity | Zero recorded provider cost is not proof of free inference; unresolved cost rows must be excluded from margin claims and investigated |
| Purchase contract | [billing.py](../../novel_to_comic/src/novel_to_comic/server/routers/billing.py); [TermsPage.tsx](../../web/src/pages/legal/TermsPage.tsx) | One-time packages, no expiry under current terms; do not invent a refund guarantee or free grant |

**Current packages (USD):**

| Package | Price | Credits | Credits per dollar |
|---|---:|---:|---:|
| Starter | $12 | 1,200 | 100.00 |
| Standard | $30 | 3,000 | 100.00 |
| Creator | $70 | 7,500 | 107.14 |
| Studio | $150 | 18,000 | 120.00 |

These prices buy credits, not books or guaranteed page quantities. No evidence
was found that Standard is “most popular.” Keep its label descriptive.

Customer copy can say: **“Credit packs start at $12. No subscription. See the
estimated credits before each paid step. Total use depends on your story,
quality choices and revisions.”** Show estimates as `~N credits`, distinguish
holds from settled charges, and let the author inspect remaining balance.

## Correct package economics

Credit conversion and credit purchasing are different units. A credit is not
universally one cent of provider spend. At the example 2× markup, 200 credits
represent approximately $1 of rated provider spend. Starter sells those 200
credits for $2; Studio sells them for about $1.67. Per-call ceiling rounding and
minimum debits can affect this calculation.

The table below is a **theoretical full-redemption scenario** at conversion
100 and markup 2.0. It assumes all credits are consumed on correctly rated
billable usage and no uncharged provider liability. These are approximate contribution
illustrations before payment fees and other costs, not measured gross margins.
They ignore per-call rounding; actual rated provider spend can be lower.

| Package | Revenue | Approximate rated provider spend at full redemption | Revenue less rated provider spend | Fraction of revenue remaining |
|---|---:|---:|---:|---:|
| Starter | $12.00 | $6.00 | $6.00 | 50.0% |
| Standard | $30.00 | $15.00 | $15.00 | 50.0% |
| Creator | $70.00 | $37.50 | $32.50 | 46.4% |
| Studio | $150.00 | $90.00 | $60.00 | 40.0% |

Use actual payment processor fees, currency conversion, taxes handled by the
business, refunds, and disputes from the account and settlement records.
The old universal `2.9% + $0.30` assumption was not verified for this merchant.
Include hosting/storage, uncharged failed calls, and support effort before
deciding how much acquisition spend is affordable. Include the provider cost
of granted-credit work once, with zero credit-sale revenue for the grant;
do not also subtract the grant's face value as a second delivery expense.

At the **1.0 runtime fallback**, provider spend at full redemption would be
$12, $30, $75, and $180 respectively, before rounding. Starter and Standard
have no provider margin before fees; Creator and Studio are already negative.
Effective production configuration is therefore a revenue gate, not a setup
footnote. Do not change it blindly for existing customers: verify the intended
commercial setting, deploy deliberately, and retain the evidence.

The old document incorrectly described bulk-tier margins as uniform and
claimed conversion-factor changes merely rescale the currency. Changing the
factor while holding package credits/prices fixed changes how much compute
customers can buy. Treat any factor or markup change as a pricing decision.

## Replace the panel model with measured complete-page cost

The active stages are extract → brief → style → cast → adapt → plan → draw →
finish. Draw generates a complete lettered page revision, and validation and
correction can consume additional calls. Finish is not the old free browser
composition stage. A 250-panel count is not a usable denominator.

The checked-in complete-page profile in
[config.py](../../novel_to_comic/src/novel_to_comic/config.py) currently records
`nano-banana-pro-complete-page-v1`, provider `vertex-multimodal`, model
`gemini-3-pro-image`, up to eight references, and estimator constants of
$0.134 base plus $0.00112 per reference. It also has $0.004 OCR and $0.02
optional visual-review allowances. These are **configuration estimates**, not
fresh provider quotes or observed accepted-page costs. Model routing remains
in [litellm/config.yaml](../../litellm/config.yaml); do not copy provider names
into the customer offer or silently change a frozen edition's profile.

A useful per-production equation is:

```
provider liability = source/brief work + style/cast references
                   + adaptation/planning + every page-render attempt
                   + OCR/visual analysis + corrections/finishing
                   + charged failures and unresolved submissions
```

Track **accepted exported pages** separately from generated attempts. Report
both first-pass acceptance and all-in cost to the first export. One cheap
render that needs three revisions is not one cheap finished page.

For each real run, retain:

- release SHA, configuration/price-table version, funding mode and frozen
  edition profile;
- source length, genre, target scope, accepted pages, reference count, and
  changes in appearance state;
- each provider event, usage provenance/confidence, request identity, attempt,
  charge, refusal, ambiguous submission, and unknown-cost row;
- initial and subsequent estimates, temporary holds, final credit debits,
  purchased/granted credits, and operator adjustments;
- first-pass lettering and visual review, correction count, final exported
  artifact, elapsed time, and active customer/operator minutes;
- processor settlement, refunds and support incidents at customer/cohort
  scope, reconciled without exposing manuscript content in analytics.

Never automatically resubmit an ambiguous paid image request merely to make a
run finish. Unknown provider liability remains an operating exception until
reconciled. Price-table drift, model changes and higher revision rates can all
make cost volatility a launch risk despite a nominal markup.

## Commercial gates for the excerpt offer

These are proposed management thresholds, not existing results:

1. Measure at least ten independent, rights-cleared short-excerpt productions
   on the intended production profile, including dialogue, multiple recurring
   characters, and an appearance-state change. Retain failures as well as
   successes; this small sample is discovery evidence, not a stable p95.
2. Publish an observed range only with source scope, sample size, date,
   revision allowance, and profile. Do not translate a provider estimate into
   guaranteed pages per $12 pack.
3. The first paid cohort must show positive contribution after actual provider
   liabilities (including granted-credit work), processor fees, refunds, storage
   and support. Report
   operator time even when the founder does not pay themself a salary.
4. Before increasing acquisition spend, require a conservative path to at
   least 30% contribution after variable delivery/support costs, with no
   unresolved billing liabilities. This is a proposed operating target, not a
   claim that today's packages achieve it.
5. Use realized contribution from consumed credits in the first cohort to cap
   acquisition spend.
   Do not justify CAC with assumed repeat purchases or unused-credit breakage.
   Non-expiring prepaid balances represent future delivery obligations.

If a first useful excerpt routinely consumes more than Starter, fix the scope
or make the required budget clear before purchase. Do not create a trap where
“start for $12” silently means “pay again to get anything usable.” A future
fixed-price excerpt bundle is worth testing only after its scope, worst-case
cost allowance, and completion/refund behavior are designed and implemented.

The latest development project's `gpt-image-2` examples are useful visual
proof under the user's current development adapter setup, but must not enter
API-funded production cost statistics as zero-cost paid runs. The intended
future `gpt-image-2.5` move needs its own supported profile, measurement and
release validation; better quality or margins are not assumed.

## Acquisition implications

Follow the [self-service launch strategy](self-service-launch.md) and
[bounded campaign plan](first-scene-campaign.md). Use the existing gallery and
explanation as the zero-spend demonstration.
A metered personal sample grant is a future experiment requiring a per-user
limit, total budget cap, abuse controls and a real measured conversion lift;
a free full chapter is not the default. A customer's successful export is the
activation event. An upgrade or second project is repeat-use evidence, not a
prerequisite for calling the first paid cohort a success.

Keep external pricing comparisons in the dated
[branding refresh](branding-and-marketing.md). Competitor credits and page
claims are not comparable units of accepted, reviewed output. The current
commercial advantage we can state about ourselves is simple purchasing with
no subscription, not a speculative “thousands of times cheaper” claim.

## Superseded assumptions

The July recommendations to implement these same packages have been carried
out. Their supporting `60k words → 60 scenes → 250 panels`, `$12.70 provider
cost`, `~$25/full book`, `Standard covers a book`, `~48% net margin`, `3% failure
leak`, and fixed commissioned-art savings claims are withdrawn. No measured
replacement was located in this review. The old arithmetic is available in
Git history; it should not remain a pricing source beside current contracts.
