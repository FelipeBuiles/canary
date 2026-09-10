# Scenewright — market and pre-launch readiness reassessment

**Date:** 2026-07-30
**Status:** Historical assessment. The September 9
[self-service launch strategy](../proposals/self-service-launch.md),
[readiness refresh](../proposals/launch-readiness.md), and
[commercial refresh](../proposals/branding-and-marketing.md) replace this
report's launch decision, market snapshot, and operator-assisted sales motion.
All statements below describe the July assessment, not today's deployed state.
**Product:** Scenewright (Canary is the internal codename)
**Assessment scope:** the full-page and lettering refactor, the recovered
pre-offer/readiness material, the current application and tests, checked-in
deployment/billing/operations documentation, and a refreshed market scan.

> **Current decision:** do not launch publicly yet. The product is ready for a
> tightly controlled, operator-assisted proof run once the release,
> production, full-page visual, economics, name, and support gates below have
> evidence. The previous panel-era readiness plan is a source of useful gates,
> not evidence that those gates passed.

This report is the current bridge between the deleted pre-offer documents and
the post-refactor product. The repository implementation, tests, and accepted
ADRs outrank older proposals. The supporting repository-only audit is
[2026-07-30-launch-readiness-agent-audit.md](2026-07-30-launch-readiness-agent-audit.md).
The execution checklist is
[docs/plans/2026-07-30-prelaunch-readiness/README.md](../plans/2026-07-30-prelaunch-readiness/README.md).

## 1. Executive readout

The refactor improved the product story. Scenewright can now be described as
an author-directed, source-accounted visual adaptation workflow that produces
complete, lettered comic pages and a finished PDF/CBZ edition. The strongest
customer-facing idea remains: the author makes the creative decisions while
the system carries the production workload.

The launch risk moved. Before the refactor, the question was whether a
panel-based comic pipeline could be sold safely. Now the questions are whether
complete-page generation is visually repeatable, whether lettering survives
the full render/review/export loop, whether the credit offer is profitable,
and whether the operating/support path works in production.

| Area | Current answer | Decision |
|---|---|---|
| Product architecture | Eight backend stages, four author-facing stations, complete-page Draw, page issue review, Finish/export | Adapt the existing positioning |
| Local engineering health | Backend 906 passed / 4 skipped; web 226 passed; Ruff, web lint, and web build pass | Good evidence for a release candidate, not a launch |
| Release identity | Current branch has uncommitted changes and is not a deployed release record | Block |
| Production operations | Runbooks and code-level controls exist; live schema, billing, monitoring, restore, and recovery evidence is missing | Block |
| Full-page proof | Contract tests exist; an authorized provider-backed deployed run is not evidenced | Block |
| Unit economics | Code has page-profile estimates; the published book model is still panel-based | Block |
| Audience and offer | Author-control / source-fidelity narrative is credible; first-value path and page-count promise are unvalidated | Pilot only after clarification |
| Brand | Scenewright is coherent, but adjacent SceneWrite creates confusion risk | Written name decision required |
| Public launch | No | Reassess after a small paid learning cohort |

## 2. What was recovered and how it should be used

The deleted material was recoverable from pre-refactor Git history. It should
not be restored verbatim because it encodes the old nine-stage, panel-first
architecture.

| Material | What survives | How to use it now |
|---|---|---|
| Pre-offer implementation plan | Slice-based sequence for release identity, safety, billing, support, proof, learning, and launch authorization | Retain the gates; replace panel acceptance and old stage names with complete-page evidence |
| Slice 0 pilot-offer/operator contract | Small waves, explicit offer/name/rights/support decisions, operator ownership, and consent before promotion | Use as the operating shape for the first design-partner cohort |
| Slices 1–7 readiness spec | Release, deployment, auth, billing, input safety, observability, backup, support, and real-provider exits | Convert each exit into a dated evidence record; do not treat the old checkboxes as complete |
| branding-and-marketing.md | Audience, author-control positioning, rights posture, credit-pack strategy, and channel hypotheses | Keep as strategic research, but correct page/panel language and refresh market facts |
| launch-readiness.md | Operational checklist and previously identified code risks | Keep as a checklist; its July deployment snapshot and test counts are historical |
| 2026-07-18 acquisition brief | Seven pre-invite gates, small-cohort sequencing, permissioned proof, and acquisition hypotheses | Adapt to complete-page proof and mark thresholds as hypotheses until measured |

The current report, rather than any recovered panel-era file, is the launch
decision record. The old plan/specs can be found with Git history when a
historical audit is needed.

## 3. Current product truth

### Product architecture

The implementation now defines these backend stages in
[state.py](../../novel_to_comic/src/novel_to_comic/state.py#L73-L83):

extract → brief → style → cast → adapt → plan → draw → finish

The frontend groups them into four stations in
[stations.ts](../../web/src/lib/stations.ts#L37-L81):

- **Story:** extract and approve the Brief.
- **Look:** select a visual direction and approve the cast and places.
- **Pages:** inspect the background adaptation/page plan, then review complete
  page renders and correct exceptions.
- **Book:** run preflight and export the edition.

The important contract change is that Draw produces a complete page revision.
Lettering is part of the canonical page/adaptation contract, OCR and render
analysis provide review evidence, page issues target a render revision, and
Finish exports without changing the creative pixels. The approval endpoint
requires page renders and rejects unresolved blocking page invariants before
Draw can continue
([pipeline.py](../../novel_to_comic/src/novel_to_comic/server/routers/pipeline.py#L471-L520)).

### Public product story

The current landing copy is close to the right story:

- “Turn your novel into a graphic novel you direct.”
- full-novel EPUB/PDF/TXT input and PDF/CBZ output;
- four decisions: Story, Look, Pages, Book;
- approved character/location references and book-level continuity;
- AI assistance disclosed, manuscript ownership retained, and no claim of
  ownership over generated output;
- no subscription, credits that do not expire, and an estimate before paid
  steps.

Those claims are in
[landingCopy.ts](../../web/src/pages/landingCopy.ts#L103-L219). Keep them,
but avoid making “verified book” sound like a quality guarantee. It currently
means the Finish preflight/export path completed; it does not mean an author,
printer, distributor, or reader will judge every page publish-ready.

### Local evidence

The following checks passed on this working tree on 2026-07-30:

- backend: 906 passed, 4 skipped;
- Ruff: all checks passed;
- web tests: 42 files, 226 tests passed;
- web lint: passed;
- production web build: passed.

The build still reports a large JavaScript chunk. That is not a launch blocker
for a small pilot, but it is worth measuring on a real mobile connection.
These are local checks, not evidence of the exact SHA deployed to production.

## 4. Market and positioning refresh

### Category baseline has moved up

Whole-book ingestion, recurring references, export, ownership language, and
pay-as-you-go credits are no longer safe differentiators by themselves.
ComicInk's current public pricing page advertises credit packs, no expiry, and
roughly 30 pages for its entry pack and 240 pages for a larger pack; its
product pages also advertise whole-book workflows, references, export, and a
storefront. LlamaGen advertises free entry, paid plans, and novel-to-comic
conversion. These are competitor-controlled claims and should be rechecked
before publishing a comparison:

- [ComicInk pricing](https://www.comicink.ai/pricing)
- [ComicInk product page](https://www.comicink.ai/)
- [LlamaGen pricing](https://llamagen.ai/app/pricing)
- [LlamaGen novel-to-comic tool](https://contextbase-cloudflare.llamagen.ai/tools/novel-to-comic)

The defensible Scenewright wedge is narrower and more useful:

> A manuscript-first production instrument with visible editorial
> checkpoints: source → brief → book adaptation → page plan → complete
> lettered page → issue/correction review → finished edition.

That gives the author an inspectable trail and focused correction surface. It
does not promise a magic one-prompt book, perfect character identity, or
cheaper output than every competitor.

### Audience and trust

The target author is not uniformly anti-AI, but is protective of authorship,
consent, privacy, and disclosure. BookBub's survey of 1,229 authors is useful
directional evidence, not a Scenewright demand study:
[How authors are thinking about AI](https://insights.bookbub.com/how-authors-are-thinking-about-ai-survey/).

The public trust posture should remain explicit:

- the customer must have rights to the manuscript and supplied references;
- the workflow is AI-assisted;
- the author retains manuscript ownership;
- output rights/copyrightability should be described precisely, not as a
  universal guarantee;
- customers decide what to accept, correct, export, and publish.

The U.S. Copyright Office says protection depends on the human-authored
expressive contribution, and that a prompt alone is not enough:
[Copyright and Artificial Intelligence, Part 2](https://www.copyright.gov/newsnet/2025/1060.html).
Amazon KDP separately requires disclosure of AI-generated text, images, or
translations while distinguishing that from AI-assisted work:
[KDP Content Guidelines](https://kdp.amazon.com/en_US/help/topic/G200672390).
These are product-copy inputs, not a substitute for legal advice.

### Name risk

An active adjacent product uses the phonetically identical name SceneWrite
for AI storytelling/video work:
[SceneWrite](https://scenewrite.app/).

This does not automatically require a rename, but it makes “Scenewrite is
clear” an unsupported claim. Before brand spend or broad acquisition, obtain a
written practitioner review covering federal marks, related goods/services,
common-law use, domains, and international confusion. Start with the
[USPTO trademark search](https://www.uspto.gov/trademarks/search) and the
[USPTO federal-search guidance](https://www.uspto.gov/trademarks/search/federal-trademark-searching),
then record the decision.

## 5. What to keep, adapt, change, and drop

| Treatment | Decision |
|---|---|
| **Keep** | Indie/self-published author focus; author-directed workflow; source fidelity; approved cast/places; four stations; credit packs; no subscription; non-expiring credits; AI/rights disclosure; community-led and permissioned proof |
| **Adapt** | “Panels” → “Pages”; panel flags/retries → page issues and complete-page corrections; storyboard/direct/compose → plan/draw/finish; deterministic lettering → exact visible lettering plus OCR/review evidence; 30–50-panel benchmark → a measured complete-page pilot and, only if affordable, a larger internal benchmark |
| **Change** | Recalculate pricing from page-profile actuals; choose trial versus paid-first first value; add acquisition-source/cohort capture; obtain the name decision; publish real complete-page proof; exercise production support and recovery |
| **Drop** | Perfect consistency; “publish-ready” or “KDP-ready”; fixed page count/cost; “full book in minutes”; “copyright-safe”; the old free-credit promise; mass-DM acquisition; any implication that the current Starter pack guarantees a book or a fixed-length issue |

The old “$12 / 6–12-page” concept can survive only as a bounded pilot
hypothesis. The commercial contract should be the credit pack and its
estimate, not a guaranteed page count. Do not put that page-count example on
the public site until the full-page run proves it is affordable and repeatable.

## 6. Launch gates

### P0 — required before a paid pilot

| Gate | Current state | Required evidence |
|---|---|---|
| Release candidate | **Missing** — the current checkout is a feature branch with uncommitted changes; the release-evidence template is blank | Merge/reconcile the intended changes, run exact-SHA CI, deploy that SHA, and fill [release-evidence-template.md](../ops/release-evidence-template.md) |
| Production foundation | **Missing** | Verify Supabase schema/RLS, two-user project and credit isolation, auth/reset email, trusted URL/hosts, domain/TLS, readiness, and a rollback target |
| Billing | **Code present; live evidence missing** | Test paid Checkout, duplicate webhook idempotency, unpaid event rejection, refund/credit reconciliation, and insufficient-credit recovery |
| Monitoring and recovery | **Runbooks present; exercise missing** | Verify Sentry alerting, application metrics/logs, a mid-draw interruption/recovery, backup snapshot restore, and operator escalation |
| Full-page visual acceptance | **Missing** | Run an authorized public-domain or licensed manuscript through deployed Extract → Brief → Look → Pages → Book; inspect complete pages, exact visible lettering, OCR results, page issues, corrections, and PDF/CBZ output |
| Economics | **Missing** | Record provider usage, retries, OCR, reference count, credits held/settled/released, operator minutes, elapsed time, refunds, and export success; recompute gross margin from those measurements |
| First value and offer | **Not decided** | Choose either a capped, verified trial grant or purchase-first Starter access. The landing page must not promise a sample path that cannot start truthfully at zero balance |
| Name, rights, support | **Missing decision/evidence** | Record the name review/rename decision, monitored support and legal contacts, manuscript/reference rights acknowledgement, retention/deletion path, AI disclosure, and refund policy |

### P1 — required before broad public promotion

- permissioned customer-owned complete-page proof and at least one case study;
- a public pricing/credits explanation with measured examples and uncertainty;
- acquisition attribution (UTM or a deliberately small first-party source log),
  cohort outcomes, feedback, and case-study consent;
- an exercised account export/deletion and support triage path;
- current internal product/stage documentation with no active panel-era
  instructions;
- mobile/error-flow QA and a decision on the large web bundle;
- a written threshold for contribution margin, support minutes, successful
  export rate, and repeat use before increasing traffic.

Analytics do not need a heavyweight growth stack for the first cohort.
Existing product events are privacy-bounded and useful for stage, checkout,
credit, and export milestones, but the allowlist still contains stale
panel_* names and has no acquisition source, campaign, cohort, feedback, or
case-study consent path
([product_events.py](../../novel_to_comic/src/novel_to_comic/server/product_events.py#L20-L39)).
A manual source field and a small weekly cohort sheet are acceptable for the
first two authors; broad promotion needs a repeatable first-party path.

## 7. Recommended first launch shape

The safest next offer is a **paid, operator-assisted design-partner pilot**,
not a broad self-serve launch:

1. Admit no more than two authors at a time.
2. Use a public-domain or explicitly licensed excerpt for internal proof, then
   use customer work only with written permission for case-study use.
3. Scope the pilot around a bounded 6–12 complete-page excerpt only after the
   economics gate confirms that scope. Treat the page count as a planning
   example, not a guarantee.
4. Hold one approved look/cast direction; let adaptation and page planning run
   as inspectable background work; review complete pages by exception.
5. Allow complete-page corrections, then finish and export PDF/CBZ.
6. Capture actual credits, provider cost, retries, time, operator intervention,
   issue corrections, export success, satisfaction, and permission for proof.
7. Expand only when the same workflow works for multiple authors without
   cross-user, billing, data-loss, or unresolved support failures.

The existing Starter package is $12 / 1,200 credits in code, but the current
page profile is only a cost input: complete-page Draw uses a fixed provider
profile with a $0.134 base page estimate, $0.00112 reference estimate, and
$0.004 OCR estimate before retries, upstream stages, and operating overhead
([config.py](../../novel_to_comic/src/novel_to_comic/config.py#L70-L93);
[page_drawing.py](../../novel_to_comic/src/novel_to_comic/page_drawing.py#L105-L122)).
Do not publish “Starter covers X pages” until the measurements above replace
the old panel-based model in
[pricing-and-margin.md](../proposals/pricing-and-margin.md).

## 8. Marketing work that is still missing

Before public acquisition, create and verify:

- three to five real complete-page examples showing lettering and varied
  issue states, labelled as development, internal, or customer work;
- one short product walkthrough showing the four stations and the correction
  loop;
- an honest cost explainer that leads with credits and shows why totals vary;
- a rights/AI-use page that is visible before upload and purchase;
- a customer-owned case study with explicit display consent;
- a simple comparison page focused on author control and source accounting,
  without unsupported competitor takedowns;
- a support promise, refund path, and response owner;
- a small acquisition-source/cohort record tied to signup, paid start, first
  page, export, repeat use, and consent.

The existing landing page uses “Development sample” art, which is the correct
label for internal references. It is not customer proof. Do not turn those
images into testimonials, outcome claims, or implied production guarantees.

## 9. Recommended sequence from here

1. **Decide the offer and name posture.** Pick paid-first versus a verified
   capped trial; assign owners for support, billing, legal, recovery, and
   proof; record the SceneWrite decision.
2. **Make a clean release candidate.** Reconcile the current dirty branch,
   update current product documentation, run the full gates, deploy the exact
   SHA, and fill the release record.
3. **Exercise production safety.** Verify schema/RLS, auth, billing,
   monitoring, recovery, backup restore, support, and export.
4. **Run the real full-page proof.** Measure page quality, lettering, OCR,
   correction workload, economics, latency, and PDF/CBZ output.
5. **Run the two-author pilot.** Keep it operator-assisted, collect
   privacy-bounded evidence, and publish only permissioned work.
6. **Reprice and rewrite the offer from actuals.** Update public copy and
   package guidance; remove any claim the measurements do not support.
7. **Open public acquisition gradually.** Start with warm referrals, author
   communities, partners, newsletters/podcasts, and high-intent search. Add
   paid traffic only after conversion, support burden, name, and margin are
   proven.

## 10. Go/no-go rule

**No-go today for public launch.** The current branch has strong local
engineering evidence and a credible product narrative, but it lacks a
release-identifiable deployment, provider-backed complete-page proof,
measured economics, exercised production operations, a first-value decision,
permissioned customer proof, and a written name decision.

**Conditional go for a private pilot** after all P0 gates have dated evidence
and the internal full-page run meets the agreed quality, cost, support, and
export thresholds. The pilot is the experiment that should answer whether
Scenewright deserves a public launch—not a substitute for those gates.
