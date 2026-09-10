# Launch-readiness audit — 2026-07-30

**Status: Historical.** The September 9
[self-service launch strategy](../proposals/self-service-launch.md) and
[readiness refresh](../proposals/launch-readiness.md) replace this assessment.
Historical counts and missing-feature findings below are not current
production observations.

## Scope and verdict

This is a repository-only audit of branch `render-full-pages` at `716485c`, its
dirty working tree, checked-in deployment/product evidence, and the deleted
pre-offer materials recovered from `db98a9d` (removed by the full-page reset in
`aa627f9`). No paid provider calls, outreach, or production mutations were
performed. Per `docs/README.md:14-23`, implementation, tests, and configuration
win when proposals or plans disagree.

**Verdict: no-go for public launch, and no-go for a paid pilot until a new
full-page release and evidence package exists.** The product architecture has
moved forward materially; the launch proof has not. The old readiness plan is a
useful checklist, not evidence that its exits passed.

## 1. Reusable claims

- **Audience and positioning:** writers and indie authors bring a manuscript,
  keep the creative decisions, and use Scenewright as a directed instrument.
  This is supported by `PRODUCT.md:7-14`, `web/src/pages/landingCopy.ts:103-109`
  and `web/src/pages/landingCopy.ts:176-184`.
- **Four user-facing decisions remain a good explanation.** The implementation
  now groups eight backend stages into Story, Look, Pages, and Book in
  `web/src/lib/stations.ts:37-79`. Keep the simple station story, but say
  “Pages,” not “Panels.”
- **Trust posture:** AI assistance is disclosed, manuscript ownership is not
  claimed, and purely generated imagery is not promised copyright protection;
  the current public copy states this at `web/src/pages/landingCopy.ts:176-184`
  and `:210-215`.
- **Credit economics:** one-time packs, non-expiring credits, server-sourced
  estimates, and no subscription are implemented in
  `novel_to_comic/src/novel_to_comic/server/routers/billing.py:19-29,135-144`
  and `web/src/pages/landingCopy.ts:186-191`. Market copy should sell credits,
  not a guaranteed page count.
- **Controlled learning before broad promotion** remains correct. The deleted
  Slice 0 spec made the offer, support, rights, consent, and name decision
  explicit before customer-facing activity (`docs/superpowers/specs/2026-07-20-slice-0-pilot-offer-and-operator-contract.md`, recovered at
  `db98a9d`, lines 13-17 and 50-72). Use this as operating policy, not as proof
  that those decisions have been completed.

## 2. Stale claims that must change

| Old material | Current correction |
|---|---|
| Nine stages with `storyboard`, `direct`, and `compose`; deterministic lettering in the final stage. `PRODUCT.md:18-28` and `docs/reference/stage-contracts.md:15-33` still say this. | The code and accepted ADR define eight stages: `extract`, `brief`, `style`, `cast`, `adapt`, `plan`, `draw`, `finish` (`novel_to_comic/src/novel_to_comic/state.py:73-84`; `docs/adr/0008-eight-stage-page-generation-pipeline.md:8-20`). |
| Independently generated/replaced panels, panel acceptance, panel flags, and panel-level regeneration. The July marketing copy still says “focused panel revision” (`docs/proposals/branding-and-marketing.md:52-59`). | Draw generates complete lettered page revisions only; crops/regions are review evidence. Issues are reviewed by exception and one Pages decision continues to Book (`docs/adr/0013-complete-page-generation-only.md:8-26`; `docs/adr/0015-page-issue-review-by-exception.md:8-33`). |
| “Stage 9 lettering,” compose-page editing, and panel-era cost tables. `docs/proposals/pricing-and-margin.md:3-7,48-64` explicitly says its economics are stale. | Recompute price/margin from complete-page generation, OCR/lettering analysis, correction attempts, and Finish export actuals. Do not use the old 250-panel/book model as launch evidence. |
| A guaranteed or implied `$12 / 6–12-page` outcome, or “repair individual panels.” The deleted plan framed that as its goal (recovered `docs/superpowers/plans/2026-07-18-pre-offer-readiness-implementation-plan.md`, `db98a9d`, lines 33-49). | Retain 6–12 pages only as an illustrative pilot use case if measured and affordable. The commercial contract is the Starter credit pack, with variable output and revisions; the deleted Slice 0 spec says this explicitly (recovered path, `db98a9d`, lines 15-27). |
| Invite-only authorization, disabled public signup, and disabled sample import. These were superseded by the 2026-07-24 amendments (`docs/superpowers/specs/2026-07-20-slices-1-7-pre-offer-readiness.md`, recovered at `db98a9d`, lines 5-15). | Current signup is ordinary auth (`web/src/pages/auth/SignupPage.tsx:1-4`) and the homepage sends users to a sample-story signup path (`web/src/pages/landingCopy.ts:103-109`). Decide explicitly between a public trial and an invitation-led paid pilot; do not reuse the old access-control exit criteria without reimplementing them. |

The dated launch proposal also needs to be treated carefully: its “four code
blockers fixed” statement is about the July working tree, while its deployment
snapshot is historical (`docs/proposals/launch-readiness.md:9-28`). The HTML
acquisition brief itself says that the “no machine deployed” statement in that
proposal is stale (`docs/proposals/scenewright-prelaunch-acquisition-2026-07-18.html:339-355`). Neither is current deployment proof.

## 3. Current blockers

1. **No clean, release-identifiable candidate.** The current checkout is a
   feature branch with uncommitted changes in CI and tests. The deploy workflow
   only deploys `main` after backend, web, and Docker jobs pass for the exact
   SHA (`.github/workflows/ci.yml:140-219`); the release-evidence template is
   still blank (`docs/ops/release-evidence-template.md:1-30`). Do not treat the
   current working tree as deployable evidence.
2. **No new full-page visual acceptance run.** The current contracts and tests
   prove schemas, hashes, exact lettering fields, page provenance, and issue
   targeting (`novel_to_comic/tests/test_full_page_contracts.py:741-749,1134-1184`),
   but they do not prove a real deployed run through Draw → Finish → PDF/CBZ.
   The full-page plan requires authorized visual acceptance and complete-page
   correction evidence (`docs/plans/2026-07-25-full-page-generation/README.md:391-430`).
3. **Deployment acceptance is unproven.** Code-level controls now exist for
   readiness, security headers, input budgets, and Stripe safety
   (`novel_to_comic/tests/test_launch_safety.py:253-377`; `novel_to_comic/src/novel_to_comic/input_limits.py:30-58,183-248`; `novel_to_comic/src/novel_to_comic/server/security_headers.py:30-49`).
   Missing are current production results: exact SHA/version, two-user
   Supabase isolation, Stripe test purchase/duplicate/unpaid paths, mid-draw
   recovery, Sentry alert, restored-volume export, auth email/reset, and
   mobile/error-flow checks. The repository’s observability note explicitly
   says it records no live changes (`docs/research/observability-live-activation.md:1-18`),
   and the backup runbook says snapshots are not proven until restored
   (`docs/ops/backup-restore.md:5-16`).
4. **First value and offer are not coherent.** The landing page promises a
   sample-story start, but there is no checked-in trial grant or pilot welcome/
   rights-acknowledgment flow; the homepage test only proves that an old “500
   free credits” claim is absent (`web/src/__tests__/homePage.test.tsx:38-52`).
   Choose and implement one truthful path: a capped, verified trial grant, or
   an explicit paid Starter purchase before generation.
5. **Full-page economics and quality thresholds are unknown.** The old pricing
   model is panel-based, and the old benchmark was an eight-panel benchmark
   (`docs/proposals/launch-readiness.md:230-241`). The new evidence must measure
   complete pages, exact visible lettering, page issues/corrections, retries,
   provider cost, settled credits, elapsed time, operator minutes, and export
   success.
6. **Name/legal/support decisions remain open.** The adjacent phonetically
   identical SceneWrite product and unresolved practitioner review remain
   documented risks (`docs/proposals/branding-and-marketing.md:45-51`; deleted
   Slice 0 spec, recovered `db98a9d`, lines 13-17). No public promotion should
   proceed under that name until a written use/rename decision, monitored
   support/legal routes, and refund/abuse/deletion procedures are evidenced.

## 4. Evidence still missing

The minimum new evidence package should contain:

- a filled release record tying source SHA, green CI, image/deployment ID,
  `/api/version`, readiness, security headers, rollback target, and operator to
  one release;
- a deployed acceptance record covering auth, two-user isolation, billing and
  recovery, Sentry, backup restore, support triage, and PDF/CBZ export;
- a provider-backed complete-page sample at the intended pilot scope, with
  recurring characters/locations, exact lettering/OCR results, page revisions,
  derived panel/crop counts, actual credits and cost, retries, timing, and
  operator intervention;
- a recalculated Starter/Standard offer decision from those actuals, including
  whether a 6–12-page issue is affordable and repeatable;
- a first-party funnel/reporting path. The repository has privacy-bounded event
  plumbing (`novel_to_comic/src/novel_to_comic/server/product_events.py:20-39`)
  and operator funnel views (`docs/supabase-schema.sql:626-635`), but not the
  planned acquisition-source/cohort/feedback/case-study workflow; and
- a written name decision, rights/AI disclosure, monitored support and legal
  contacts, and permissioned proof assets or case studies.

Also update stale internal product and stage-contract references before launch;
otherwise support, marketing, and operators will describe a pipeline the
customer no longer receives.

## 5. Recommended launch sequence

1. **Lock the offer and name posture.** Decide public trial versus
   invitation-led paid pilot; keep credits as the contract; make the page count
   illustrative; obtain the written name decision; assign support, billing,
   legal, recovery, and proof owners.
2. **Create a clean release candidate.** Reconcile the dirty branch, update
   stale current docs, run the complete CI/web/Docker gates, deploy the exact
   SHA through the guarded `main` workflow, and fill release evidence.
3. **Run the deployed safety acceptance.** Apply/verify the schema, then execute
   the two-user, Stripe, recovery, Sentry, restore, headers, auth, and export
   checks. Stop on any cross-user exposure, unreconciled billing, lost project,
   or unmonitored failure.
4. **Run the new full-page proof internally.** Use a public-domain or licensed
   source, with explicit cost authorization. Measure the complete-page and
   lettering contract, correction workload, economics, and export quality.
5. **Operate a small paid learning cohort.** If the proof passes, admit two
   authors at a time, keep support operator-assisted, collect privacy-bounded
   product evidence, and publish only separately permissioned work. Do not
   expand on waitlist interest alone.
6. **Open public signup only after cohort evidence.** Require repeatable first
   value, acceptable support burden and contribution margin, permissioned proof,
   resolved name risk, and a completed live billing/operations checklist before
   broad promotion or live-mode acquisition.
