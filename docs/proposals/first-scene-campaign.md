# Test campaign: A scene worth seeing

**Status: Superseded, September 26, 2026,** by [showcase-and-growth-2026-09.md](showcase-and-growth-2026-09.md). Kept for rationale only.

**Status: Draft, prepared September 9, 2026. Nothing sent, published, or purchased.**
Execution depends on the [self-service launch gates](self-service-launch.md).
All budgets and thresholds are proposed. Current customer demand and acquisition
cost are unknown. The local landing uses user-selected dcc1.2 development
pages provisionally; confirm rights to promote that adaptation or substitute a
permissioned example before activating this campaign. Do not spend this phase
chasing perfect images. The planned image-model change is a later quality and
cost revalidation, not part of this campaign implementation.

## Experiment brief

**Buyer hypothesis:** independent fantasy authors with a finished scene and
readers they already reach. **Job:** make a visual excerpt they can evaluate and
choose to share. **Offer:** an author-directed comic adaptation, paid through
existing credit packs from US$12; no subscription and no promised page count.

**Question:** does inspectable source-to-page proof bring authors who buy and
finish their first excerpt without help? “Likes” and email signups cannot answer
this. Primary outcome: a unique newly paying author with a successful first
export within seven days of first paid generation. Track actual download/open
confirmation separately from export generation.

Use one landing page and one offer. Test two creative messages sequentially
with equal planned exposure and the same audience/placement, recognizing that
timing creates confounding. This is a directional smoke test, not a significant
A/B winner. Do not spend on four channels or a new analytics suite at once.

## Ready-to-use copy

### Creative A: the scene

**Headline:** Your readers know the story. Let them see a scene.

**Body:** Bring a short excerpt from your fantasy story. Choose its visual
direction and cast, review the comic pages, and export an edition you can share.
Scenewright uses AI to help with adaptation and illustration. You make the
creative decisions. Credit packs from US$12. No subscription.

**CTA:** Start with your first scene

**Creative direction:** source paragraph beside the matching, readable full
page from the approved proof kit. Small visible caption: “Development example
from [source title] · AI-assisted · [run date].” Brackets are production fields,
not publishable text; replace them with recorded facts before approval. Do not
use a made-up mockup, the Cthulhu sample, or an unrelated reference as the result.

### Creative B: the author's control

**Headline:** A comic adaptation. With you in the director's chair.

**Body:** Your scene is the starting point. You choose the look, approve the
cast, and decide which pages need another pass. Start small with Scenewright's
AI-assisted comic studio, then decide where the story goes next. Credit packs
from US$12. No subscription. Costs vary with length, quality, and revisions.

**CTA:** Direct your first scene

**Creative direction:** same permissioned example, showing approved reference
and its appearance in the final page. No before/after time or cost claim without
the underlying run record. No testimonial or sales-lift claim.

### Organic introduction, for a community that permits promotion

I'm building Scenewright for authors who want to see a scene from their story
as a comic. It uses AI for adaptation and illustration, with author decisions
on the story, look, cast, and page corrections.

The useful first step is a short excerpt. You can inspect the development
example before creating an account. Generation uses credits; packs start at
US$12 with no subscription, and there is no fixed page count per pack.

If that fits your work, try a scene and tell me where you get stuck. I'm
especially interested in whether you can get to an export without my help.

**Publishing gate:** the “development example” sentence requires the clean
source-to-page kit to be live. Adapt community language to its rules; never
post as an unaffiliated customer or send unsolicited bulk DMs.

## Destination and attribution

The existing route is `/` with `/signup` as the conversion destination. Use
these relative campaign URLs only once first-party attribution is implemented
and verified; append to the approved live origin when activating:

- Creative A: `/?utm_source=meta&utm_medium=paid_social&utm_campaign=first_scene_v1&utm_content=scene`
- Creative B: `/?utm_source=meta&utm_medium=paid_social&utm_campaign=first_scene_v1&utm_content=control`
- Permissioned community post: `/?utm_source=author_community&utm_medium=organic&utm_campaign=first_scene_v1&utm_content=introduction`

These links do not themselves create tracking. The current authenticated
product-event path captures production/payment milestones; the repository has
no complete anonymous acquisition-to-signup attribution funnel. Implement a
small allowlisted campaign record and reconcile it through signup, checkout,
paid start, first export and repeat purchase before paid traffic. Do not store
raw URLs, manuscript content, author names, emails, or arbitrary ad parameters
in marketing properties. Respect the applicable consent settings and deletion
policy. Fraud/billing records and marketing data have different purposes.

## Budget, schedule and stop rules

Proposed initial paid channel: one Meta campaign, manually approved. This is a
channel hypothesis, not evidence of efficient author targeting. Begin with
organic self-selected users for the ten-author reliability cohort first.

- Maximum **US$300 media spend across 14 days**, US$150 per creative phase.
  Set the hard ceiling in the ad account; this document and scorecard cannot
  enforce it. No automatic budget increases or additional channel.
- Separately approve a provider-generation allowance for the proof kit and
  any test credits. No public free-credit promise and no unused-credit breakage
  assumption in margin calculations.
- Review day 3 for broken routes/attribution; day 7 for spend and qualified
  progress; day 14 for stopping spend. Close the cohort after the final
  entrant's seven-day outcome window (up to day 21).
- Stop immediately for incorrect charges, lost work, isolation failures,
  missing alerts, or unapproved proof. Pause paid acquisition while resolving.
- At US$100 spend with zero newly paying authors, pause and inspect message,
  audience, checkout and traffic quality. Do not wait out the full budget.
- If at least five paid starts have matured and fewer than 60% export in seven
  days, pause acquisition and fix the product. Include all failed starts.
- Reach the budget or date ceiling: stop automatically in the ad platform.

## Score the result

| Measure | Denominator / method | Decision use |
| --- | --- | --- |
| Visitor → signup | Deduped attributable visitors; report consent coverage | Diagnose message/friction, not revenue |
| Signup → purchase | Unique new signups, server-confirmed first credit purchase | Detect pricing/trust/checkout friction |
| Purchase → paid start | New purchasers | Separate unused balances from activated customers |
| Paid start → seven-day export | All matured new paid starters | Primary activation and reliability signal |
| Operator rescue | Started authors needing staff intervention / all matured starters | Whether the motion is hands-off |
| Cost per completed paying author | Media spend / unique new payers who export | Primary acquisition cost; zero exports means no finite CAC |
| First-excerpt contribution | Revenue allocated to consumed credits minus delivery costs | How much acquisition can be afforded today |
| Repeat purchase at 30 days | All original purchasers whose 30-day window closed | Expansion signal; no invented lifetime value |

Do not choose a winner based on clicks with zero purchases. Ten completed
paying authors is directional evidence; if the ceiling is reached first, record
“inconclusive” and the bottleneck. Scale only if total contribution across
**all paid starters**, including failed and abandoned productions, covers total
media spend for that same cohort, the reliability gates remain met, and a second
cohort reproduces the outcome. Otherwise revise one variable, or stop.

## Reusable lifecycle drafts

Future behavior, not implemented automation. Send only with the appropriate
transactional basis or explicit marketing opt-in; do not mix promotional copy
into operational incident notices. No emails have been sent in this task.

**Account created / in-product guidance:**
“Start with a scene that stands on its own: a clear setting, a small cast, and
something that changes. Bring an excerpt you have the rights to use. You'll
see an estimate before starting paid work.”

**Export ready / transactional draft:**
“Your comic edition is ready to download. Open the Book station to review the
result and download your PDF or CBZ.”

**After a successful export / opted-in message draft:**
“Now you've seen the first scene. If the direction feels right, bring the next
one into your studio. Or tell us what stopped this edition from being useful.”

**Proof request / separately opted-in draft:**
“Would you be comfortable letting us feature an excerpt from your adaptation?
We would show you the exact pages, source text, credit and accompanying copy
before publication. Saying no won't affect your account or support.”

## Activation checklist

- [ ] Current production and independent-use gates pass.
- [ ] Source-to-page proof has permission, provenance, and visual review.
- [ ] Final landing, signup, credit purchase, generation and export work on mobile.
- [ ] Campaign attribution and server payment/export reconciliation verified.
- [ ] Source/offer/creative version and cohort dates recorded.
- [ ] Ad-account ceiling and stop date configured; operator alert confirmed.
- [ ] Owner approves exact creative, destination, audience and total budget.

Suggested experiment owner: founder. Engineering owns reliability and data
reconciliation. At the final review, write one decision: keep the offer, change
one part, or stop. Save evidence; do not turn the review into daily content work.
