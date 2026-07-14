# Scenewright — Credit Pricing & Margin Recommendation

> Resolves Launch-Readiness **P1 #9** (unit economics) and **Open Questions #1 &
> #3**. Picks concrete values for the three production env vars that currently
> ship at zero-margin / unconfigured defaults. Dated 2026-07-03.
>
> Method: cost-model built from the actual pricing table
> (`litellm_pricing_overrides.yaml`) and the actual models wired per stage
> (`litellm/config.yaml`), cross-checked against competitor pricing and
> AI-SaaS margin benchmarks. This is a *pricing* exercise — the ledger
> mechanics (`pg_advisory_xact_lock`, the `user_credits` computed view,
> atomic reservation/release) are out of scope and untouched.

## TL;DR — the three values

| Env var | Current | **Recommended** | Effect |
|---|---|---|---|
| `PULP_MODEL_COST_MARKUP` | `1.0` (0% margin) | **`2.0`** | 2× provider cost → **~48% net gross margin** after Stripe. A typical book lands at **~$25**. |
| `PULP_CREDITS_PER_PROVIDER_USD` | `100` | **`100`** (keep) | Clean 1 credit = $0.01 of pre-markup provider spend. Don't touch — it's a unit-conversion constant, not a pricing knob. |
| `AI_BILL_FAILED_REQUESTS` | `provider_usage_only` | **`provider_usage_only`** (keep) | User pays for calls the provider actually metered (incl. safety refusals with usage); operator eats hard 5xx/timeout failures. Industry-standard, ~3% book-cost leak. |

**Recommended Stripe packages** (markup baked in via the credit conversion,
not per-package — so margin is uniform across tiers):

| Package | Price | Credits | Covers | Implied GM |
|---|---|---|---|---|
| Starter | $12 | 1,200 | ≈½ a book / a long preview | 47% |
| **Standard** | **$30** | **3,000** | **1 full book + regen headroom** | 48% |
| Creator | $70 | 7,500 | ≈3 books (≈7% bulk bonus) | 45% |
| Studio | $150 | 18,000 | ≈7 books (≈20% bulk bonus) | 38% |

A typical 60k-word novel costs the user **~$25** (Standard package + ~half a
Creator, or one Creator with change). That's 2× the cheapest competitor
(LlamaGen $9.99/mo) but a fraction of a commissioned graphic novel ($6k–12k),
and it buys the consistency + whole-book ingestion + PDF/CBZ export that the
DIY/cheap tier can't deliver.

---

## (a) Representative per-book provider cost

Model built from `litellm_pricing_overrides.yaml` rates (verification dates
in-file) × the models `litellm/config.yaml` actually routes to at the
**balanced** preset (the shipped default). **60,000-word novel → 60 scenes →
250 panels.**

| Stage | Model | Volume | Provider USD |
|---|---|---|---|
| 1 extract | gemini-3.5-flash | 83k in / 75k out tok | $0.80 |
| 2 style | flash-lite brief + 8× flash-lite-image | 4 briefs + 8 imgs | $0.28 |
| 3 cast | flash-lite-image | 18 asset imgs (1.5 refs ea) | $0.61 |
| 4 adapt | claude-sonnet-4-6 | 72k in / 48k out tok | $0.94 |
| 5 plan | gemini-3.5-flash | 90k in / 60k out tok | $0.68 |
| 6 storyboard | gemini-3.5-flash | 72k in / 54k out tok | $0.59 |
| 7 direct | flash-lite (prompt assembly) | 150k in / 100k out tok | $0.19 |
| **8 draw** | **gemini-3.1-flash-lite-image** | **250 imgs × 3 refs** | **$8.61** |
| 9 compose | Playwright/Chromium | no AI | $0.00 |
| | | **Total (balanced)** | **$12.70** |

**Cost distribution:**

- **Image generation is 68% of book cost** (draw alone is $8.61; cast+style
  samples add another $0.88). Text stages combined are $3.20 (25%).
- Compose (Stage 9) is genuinely free — it's a Playwright render, no model
  calls.
- Switching to the **quality** preset (Reve @ $0.04/img, no per-ref charge)
  raises draw to $10.00 and the book to **~$14.09** (+11%). The default stays
  balanced.
  - *Stale as of 2026-07-14:* the quality preset now routes to Gemini 3 Pro
    Image (Nano Banana 2 Pro) at ~$0.134/img (+ ~$0.00112/ref), after Reve v2
    repriced to ~$0.20/img. Redo this margin row before relying on it.

**Where the markup applies:** `provider_usd_to_credits()` in
`server/credits.py:43` is the *single* conversion point —
`credits = cost_usd × credits_per_provider_usd × markup`, ceiling-rounded.
Every stage debit, every panel regen, and every estimate flows through it.
There is no second markup layer, so margin is applied exactly once and
uniformly across all stages.

**Sanity check on the panel count:** 250 panels/book = ~4 panels/scene across
60 scenes. The `max_panels_per_scene` default is 8; real books average lower
because many scenes (dialogue, transition) need fewer panels. 250 is the
right central estimate; ±50 panels swings the book cost by ±$1.72 (±14%),
which the credit model absorbs without margin distortion.

---

## (b) Recommended `PULP_MODEL_COST_MARKUP` = **2.0**

### The decision

| Markup | Pre-Stripe GM | Book price (user pays) | Net after Stripe |
|---|---|---|---|
| 1.0 (current) | 0% | $12.70 | **−5.6% (loss after Stripe fees)** |
| 1.5 | 33% | $19.04 | 30% |
| **2.0 (recommended)** | **50%** | **$25.39** | **48%** |
| 2.5 | 60% | $31.74 | 58% |
| 3.0 | 67% | $38.09 | 65% |

**Pick 2.0.** It lands the product at ~$25/book — competitive with the
emerged AI-comic pricing band ($10–30/mo equivalents; ComicInk ~$10/issue and
this product produces a ~30-issue-equivalent graphic novel for 2.5× that),
delivers a defensible ~48% net gross margin, and stays well under the
"AI-skeptical author bounces" ceiling.

### Why 2.0 and not higher

- **AI-SaaS margin benchmarks:** traditional SaaS runs 75–85% GM; AI-native
  SaaS with meaningful inference COGS runs 50–65% early, improving to 70%+
  at scale (KeyBanc/Bessemer/OpenView/Meritech bands). A launch-tier product
  targeting ~48% net is at the *healthy* end of the early-AI-SaaS range, not
  the thin "wrapper" end.
- **The audience is price-sensitive *and* AI-hostile.** The branding research
  (`branding-and-marketing.md` §3.4) is explicit: median active self-pub
  author earns ~$12–15k/yr; ~50% earn under $1k. They are conditioned to
  $15–60/mo for AI writing tools. A $25 one-book price reads as "serious tool
  I can budget for"; a $38–50 book (markup 3.0+) reads as "AI company
  gouging" — the exact framing the positioning works to avoid.
- **The whole value proposition is undercutting commissioned art** ($6k–12k
  for a 120-page graphic novel). At $25 the pitch is *"2,000× cheaper than
  hiring an artist, ~the cost of one printed trade paperback."* That's the
  marketing copy. At $50 it's still cheap vs. a commission but loses the
  clean rhetorical contrast.

### Why 2.0 and not lower

- **Stripe fees eat low markups alive.** At 1.0× you sell at a *loss*
  (−5.6%) because the 2.9% + $0.30 fee has no margin to absorb it. At 1.5×
  you're at 30% — below the "healthy AI-SaaS" floor, with no buffer for the
  failed-request leak (see §c), support/refund costs, or provider price
  spikes.
- **The failure mode of pricing too low is asymmetric and bad.** You eat
  provider cost spikes, failed-run retries, model deprecations, and the
  ~3%/book failed-request leak with no headroom. Raising prices later
  triggers "they got greedy" backlash; lowering them reads as a sale. Start
  at a defensible margin.

### Uniform vs per-stage markup

The code applies **one** multiplier globally. Worth a per-stage split? **No.**

- Image gen is 68% of cost *and* the stage where the margin matters most —
  but a split would mean text stages at, say, 1.5× and images at 2.5×, which
  complicates the mental model (credits would no longer be a clean function
  of provider spend) and the estimates users see pre-run.
- The simplicity of "1 credit = $0.01 provider spend × 2" is a feature: it
  keeps the reservation/estimate math transparent and the audit trail in
  `credit_ledger` self-consistent. A per-stage split is a Phase-2
  optimization only if image-cost share grows further or a specific stage's
  margin profile diverges badly.

---

## (c) Recommended failed-request policy = **`provider_usage_only`** (keep current)

### The three options, and what each leaks

The risk vector is **image-gen retries**: a single bad panel triggers 2–5
retry attempts, each a real provider charge. Quantified against the cost
model (assuming 8% of panels retry, avg 1.5 attempts each → **30 extra image
calls/book = $1.03 leaked provider spend**, ~8% of book cost):

| Policy | Who eats failed-attempt cost | Recovery | Operator leak/book |
|---|---|---|---|
| `never` | Operator eats **all** failed attempts | $0.00 | **$1.03 (8.1% of cost)** |
| **`provider_usage_only`** ✅ | Operator eats hard 5xx/timeout; user pays refusals-with-usage | $0.62 | **$0.41 (3.3% of cost)** |
| `estimate_all` | User pays **every** attempt (synthesized usage) | $1.03 | $0.00 |

### Why keep `provider_usage_only`

1. **It matches industry norms.** OpenAI, Stability, and Vertex all bill for
   successfully-metered calls (including safety refusals that consumed
   inference) but do *not* bill for hard server failures / timeouts. The
   policy name is literal: "bill the user only when the provider reported
   usage." Authors coming from any other AI tool will find this expected.
2. **The leak is bounded and cheap.** At 3.3% of book cost (~$0.41), the
   operator leak is a rounding error against the ~$11.66 gross profit per
   book at markup 2.0. Not worth the UX cost of charging for every blip.
3. **`estimate_all` is the wrong trade for this audience.** Charging a user
   for a panel that errored on *our* side (gateway hiccup, Reve 5xx, a
   malformed-response retry) is the kind of thing that becomes a
   /r/SelfPublish complaint thread. The ~$0.41/book saved is not worth the
   trust cost with an AI-skeptical audience that the entire positioning is
   built around not alienating.
4. **`never` is needlessly generous.** Safety refusals (content the provider
   wouldn't draw) and partial-success retries *did* consume provider compute;
   passing that to the user is fair and expected.

### The one thing to monitor post-launch

The 8% retry rate is an assumption. If real-world image-gen retry rates run
higher (Reve quota issues, Vertex cold-start failures), the
`provider_usage_only` leak grows linearly. The launch-readiness soak test
(Phase 2) should measure actual retry rate from `ai_usage_events` and
revisit only if the leak exceeds ~8% of book cost. The
`estimated_cost_usd`-vs-`cost_usd` drift column already captured per-event
makes this directly observable.

---

## (d) Recommended package pricing

### `PULP_CREDITS_PER_PROVIDER_USD` = **100** (keep)

This is a **unit-conversion constant**, not a pricing knob. 100 credits =
$1 of pre-markup provider spend = 1 credit = $0.01. With markup at 2.0, a
user effectively gets 50 credits per $1 of provider compute they consume.
Changing this number just re-scales the credit currency without changing
economics; the only reason to touch it would be a future desire for
sub-cent granularity, which rounding already handles. **Leave it.**

### Stripe packages

The current `CREDIT_PACKAGES` (`billing.py:17`) prices 1k/2.75k/6k credits
at $10/$25/$50 — but at the *current* zero margin those prices equal cost.
At markup 2.0 the same packages need re-pricing so a typical book is
buyable in one transaction with regen headroom.

A balanced book is **2,539 credits** at markup 2.0; a quality book is
**2,817**. Packages must cover a full book plus the retry/iteration buffer
users will burn reworking panels. Four tiers:

| Package | Price | Credits | cr/$ | Covers | Net GM |
|---|---|---|---|---|---|
| **Starter** | $12 | 1,200 | 100 | ½ book / a long preview | 47% |
| **Standard** *(most popular)* | $30 | 3,000 | 100 | 1 full book + ~20% regen headroom | 48% |
| **Creator** | $70 | 7,500 | 107 | ~3 books (7% bulk bonus) | 45% |
| **Studio** | $150 | 18,000 | 120 | ~7 books (20% bulk bonus) | 38% |

**Design notes:**

- **Standard is the anchor** — $30 buys one complete book with room to
  rework ~50 panels. This is the package a first-time buyer lands on, and
  $30 sits exactly in the emerged mid-tier band ($19–30/mo equivalents,
  per branding §2.3).
- **Bulk tiers discount via more credits per dollar, not lower per-credit
  pricing** — same mental model as ComicInk's "credits never expire." The
  GM drops slightly on bulk (48% → 38%) because Stripe's fixed $0.30
  amortizes less, but absolute gross profit per package rises ($14 → $57).
  This is the right trade for a pay-per-credit, no-subscription product.
- **$12 Starter exists for the free-tier-to-paid conversion** — the
  branding plan's Chapter-1 free artifact flywheel produces a user who has
  seen ⅛ of a book and wants the rest. $12 to finish what they started is
  the lowest-friction upgrade; it covers ~½ a book so they need Standard
  next. (Consider making this a "finish your preview" one-click upsell.)
- **No subscription tier.** The branding research is unambiguous: authors
  resent recurring fees for one-off production tasks. Pay-per-credit +
  never-expire is the resonant model. Stick to it.

### Stripe fee headroom

At all tiers, markup 2.0 absorbs Stripe's 2.9% + $0.30 with margin to spare.
The worst case is the $12 Starter (fixed fee is 2.5% of price): net GM 47%.
No package drops below 38% net even at the deepest bulk discount.

---

## Sensitivity table — provider prices +25%

Because `provider_usd_to_credits()` computes credits *at call time* from the
live pricing table, **provider price changes auto-pass-through to the user.**
Margin % is structurally protected; only the absolute $ gross and the
per-book price move. At markup 2.0:

| Scenario | Book cost | Credits charged | User pays | Net rev (post-Stripe) | Gross $ | GM% |
|---|---|---|---|---|---|---|
| baseline | $12.70 | 2,539 | $25.39 | $24.36 | $11.66 | **47.9%** |
| provider +10% | $13.97 | 2,793 | $27.93 | $26.82 | $12.86 | 47.9% |
| **provider +25%** | **$15.87** | **3,174** | **$31.74** | **$30.52** | **$14.65** | **48.0%** |
| provider +50% | $19.04 | 3,809 | $38.09 | $36.68 | $17.64 | 48.1% |

**The margin % is effectively flat** across the range (rounding noise from
Stripe's fixed fee). This is the key structural insight: **cost volatility
is not a launch risk.** The two real risks are (1) the failed-request leak
(bounded, ~3% — see §c) and (2) pricing psychology (the $25→$38 drift if
providers raise prices 50% would need a positioning check, but providers
have been *cutting* image prices, not raising them).

The flip side: if providers *cut* prices (the historical trend — flash-lite-
image is already ~half the flash-image price), users automatically pay less
per book and the operator's absolute margin compresses, but the % holds. A
future lever is to *lower* markup if volume scales, passing some efficiency
gain to users as a goodwill/positioning move — but that's a Phase-2 decision
once real volume data exists.

---

## Implementation checklist

Production env changes (all in `fly secrets`, per `launch-readiness.md`'s
prod env-var checklist):

```bash
fly secrets set \
  PULP_MODEL_COST_MARKUP=2.0 \
  PULP_CREDITS_PER_PROVIDER_USD=100 \
  AI_BILL_FAILED_REQUESTS=provider_usage_only
```

Code change — re-price `CREDIT_PACKAGES` in
`novel_to_comic/src/novel_to_comic/server/routers/billing.py:17`:

```python
CREDIT_PACKAGES: dict[str, dict] = {
    "starter":  {"label": "1,200 credits",  "price_cents": 1200,  "credits": 1200},
    "standard": {"label": "3,000 credits",  "price_cents": 3000,  "credits": 3000},
    "creator":  {"label": "7,500 credits",  "price_cents": 7000,  "credits": 7500},
    "studio":   {"label": "18,000 credits", "price_cents": 15000, "credits": 18000},
}
```

(Package IDs change from `"10"/"25"/"50"` to named tiers — a breaking change
to the `/api/billing/checkout` `package` param, acceptable per the "no legacy
shims" rule. Update the frontend buy-credits flow in the same change.)

**No changes to:** the credit ledger, `provider_usd_to_credits`,
`reservation_buffer` (1.25× hold is healthy and released on completion), or
any stage code. This is configuration + one package-table edit.

## Open follow-ups (not blocking launch)

1. **Measure real retry rate** during the Phase-2 soak test. If the 8%
   retry-rate assumption is wrong by >2×, revisit the failed-request policy
   (the only decision sensitive to it).
2. **Build the margin/provider-spend view** (P2 #12 in launch-readiness).
   `ai_usage_events` records per-call cost; `credit_ledger` records charges.
   A view joining them gives live gross-margin monitoring — the soak test
   hand-rolls this; formalize it once there's volume.
3. **Revisit markup if volume scales.** If Scenewright hits meaningful
   volume (hundreds of books/mo), a lower markup (1.5–1.8×) passing
   efficiency gains to users becomes a positioning win — "we got cheaper as
   we grew." Not now; the launch priority is sustainable margin, not
   growth-pricing.
