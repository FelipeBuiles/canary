# Slices 1–7 — Pre-Offer Readiness

Status: Proposed (2026-07-20)

## Problem Statement

After Slice 0, Scenewright has an agreed invite-only credit offer but does not yet have a trustworthy path from a green release to a paying author's export. The current gaps span CI, release identity, access control, billing recovery, browser and input safety, monitoring, backups, support operations, first-run copy, cohort learning, real-provider proof, and final offer authorization.

Without one identifiable release and an exercised deployed workflow, an author could be admitted to an unverified build, spend credits without understanding the path, lose work after a provider or restart failure, expose another user's data, or leave the operator without enough evidence to diagnose what happened.

The target is a controlled Founding Author Lab of no more than ten paying authors, admitted in waves of two. Slices 1–7 turn the existing application into a safe, observable, evidence-backed pilot. They do not create a public launch, a free tier, or a guaranteed reader-magnet product.

## Solution

Produce a green, immutable release that reports its own SHA and has a tested rollback procedure. Enforce invite-only access and the Slice 0 contract: the author buys repeatable $12 Starter packs of 1,200 non-expiring credits, sees server-sourced estimates before generation, and receives no promised page count or completion outcome.

Close the operational hazards around browser requests, compressed inputs, provider failures, account isolation, observability, backups, support, legal reports, billing recovery, and deletion. Give a funded invited author a clear first-run path from source upload through the existing stations and stages to PDF/CBZ export, with truthful disclosures and no surprise credit wall.

Record only privacy-safe cohort events and bounded feedback. Prove the complete journey in mock mode and once with real providers on the deployed application. Authorize outreach only after the exact deployed release passes automated preflight, the two-user isolation matrix, the live purchase/refund rehearsal, the proof thresholds, and the manual evidence checklist.

## User Stories

1. As an operator, I want every customer release tied to one immutable git SHA, so that I can identify exactly what a customer used.
2. As an operator, I want CI to run the real Chromium-backed renderer test, so that browser-dependent export behavior is not silently skipped.
3. As an operator, I want backend, frontend, dependency, and container jobs to pass for the same SHA, so that deployment evidence refers to one green revision.
4. As an operator, I want the running application to report its version, SHA, and build timestamp, so that support can distinguish releases quickly.
5. As an operator, I want Sentry release tags to use the deployed SHA, so that an alert maps to the code that produced it.
6. As an operator, I want a maintenance-window deploy procedure that waits for active work to drain, so that deployment does not interrupt generation.
7. As an operator, I want a release evidence record with a rollback target, so that a bad deployment can be reversed deliberately.
8. As an invited author, I want only an admin invitation to grant pilot access, so that the paid workflow is not open to arbitrary accounts.
9. As an invited author, I want to confirm my invitation, create a password, sign in, and reset my password on the production domain, so that access is usable without operator intervention for routine account actions.
10. As an unauthorised user, I want project, generation, regeneration, and export requests denied consistently, so that authentication alone cannot grant paid workflow access.
11. As an operator, I want pilot capacity reserved in waves of two and capped at ten paid customers, so that admissions cannot exceed support capacity.
12. As an invited author, I want the sample library/import surface unavailable during the pilot, so that the first-run contract is about paid credits and my own source.
13. As an author, I want the Starter price and quantity fetched from the server, so that displayed billing terms cannot drift from Stripe or the ledger.
14. As an author, I want repeated Starter purchases to add exactly 1,200 credits each, so that additional purchases are predictable.
15. As an operator, I want duplicate, unpaid, failed, and out-of-order payment notifications handled safely, so that money and credits remain reconciled.
16. As an operator, I want an approved unused-credit refund to reverse the matching grant exactly once, so that refunded money never leaves spendable credits behind.
17. As an operator, I want partially used or ambiguous grants to stop for manual review, so that an unsafe refund cannot corrupt the ledger.
18. As a pilot author, I want malformed, encrypted, oversized, or decompression- bomb inputs rejected before partial project state exists, so that one file cannot exhaust resources or leave a confusing project.
19. As an operator, I want upload estimation and Stage 1 extraction to share the same input budgets, so that accepted inputs cannot expand beyond the execution limit.
20. As an operator, I want per-user limits on expensive concurrent generation, so that one customer cannot monopolize the only machine.
21. As a pilot author, I want security headers on HTML, API, error, and redirect responses, so that ordinary browser protections are present in production.
22. As an operator, I want Sentry test events scrubbed of credentials, manuscript content, prompts, images, and signed URLs, so that monitoring does not become a content leak.
23. As an operator, I want readiness alerts separate from cheap routing health, so that a dependency outage is visible without unnecessarily removing the only machine from service.
24. As an operator, I want to restore a snapshot into an isolated volume or machine and open/export a project, so that backups are proven rather than merely configured.
25. As a pilot author, I want every customer-facing failure to provide a monitored support route with a safe diagnostic reference, so that I can ask for help without exposing my manuscript or credentials.
26. As an operator, I want exercised runbooks for support, billing, failed generation, deletion/export, abuse/DMCA, security incidents, backup restore, and deployment, so that the single-operator pilot has repeatable recovery actions.
27. As a newly invited author with no balance, I want to understand the offer and purchase credits before creating a project, so that I do not hit a surprise credit wall after uploading material.
28. As a funded author, I want the first-run path to explain upload, Story, Look, Panels, and Book steps, so that I know what I must decide and what runs automatically.
29. As an author, I want file limits and a recommendation to submit one chapter or bonus scene, so that I can choose a source appropriate for the pilot.
30. As an author, I want a warning when my source is unlikely to fit the illustrative 6–12-page use case, so that I can replace it before spending credits.
31. As an author, I want to acknowledge rights, third-party provider use, and the pilot's limitations once per offer version, so that my consent is explicit and auditable.
32. As an author, I want all paid actions to show authoritative `~N credits` estimates and settled usage, so that the UI does not overstate precision.
33. As an author, I want an always-visible support route during pipeline work, so that a failed stage does not strand me.
34. As an author, I want the first export summary to show actual credits, remaining balance, pages/panels, and feedback, so that I can assess value without being pushed into an upsell.
35. As an operator, I want lifecycle events created from server truth, so that button clicks cannot falsely report purchases, approvals, generation, or exports.
36. As an operator, I want event retries to be idempotent, so that a webhook or restarted job does not inflate the cohort funnel.
37. As an operator, I want events to exclude manuscript text, prompts, visual anchors, images, secrets, and provider responses, so that cohort learning remains privacy-safe.
38. As a pilot author, I want only short bounded feedback prompts at first panel, first export, and pilot end, so that feedback does not interrupt the creative workflow.
39. As an author, I want feedback permission separated from marketing and case-study permission, so that answering product questions does not opt me into promotion.
40. As an operator, I want a read-only report joining membership, source bucket, milestones, ledger, provider usage, retries, flags, support time, feedback, and permissions, so that I can decide whether to continue.
41. As an operator, I want a deterministic mock journey, so that recovery and UX states can be tested without provider spend.
42. As an operator, I want one real-provider journey on the deployed release, so that local fixtures cannot conceal production routing or export issues.
43. As an operator, I want a 30–50-panel proof with recurring characters and locations, so that visual continuity and repair workload are evidenced.
44. As an internal reviewer, I want predeclared proof thresholds, so that the offer decision is not changed after seeing a convenient result.
45. As an operator, I want a two-user matrix covering auth, project access, credits, generation, recovery, export, and deletion, so that cross-user exposure and account mix-ups are caught before outreach.
46. As the pilot operator, I want a read-only readiness checker to fail on missing release, safety, billing, monitoring, or manual evidence, so that “GO for two users” requires a complete record.
47. As an author, I want the pilot to stop for cross-user exposure, unreconciled billing, unrecoverable project loss, material legal/abuse incidents, invalid economics, or support overload, so that safety outranks cohort growth.

## Implementation Decisions

- Preserve the existing nine discrete backend stages and four frontend stations. These slices add readiness controls around the pipeline; they do not merge or reorder stages.
- Use the deployed pre-offer acceptance harness as the primary integration seam. It combines a read-only readiness checker, the two-user matrix, the mock first-run journey, the real-provider proof run, billing reconciliation, and the cohort report.
- CI installs the Python environment's Playwright Chromium before renderer tests. The multiline SVG verification remains a real browser test.
- The application exposes non-sensitive version, git SHA, and build timestamp metadata. The Docker build receives the SHA through `CANARY_VERSION`, and Sentry uses the same release identity.
- Deployment is a manual, maintenance-window operation: announce, stop new pilot work, wait for the activity endpoint to become idle, deploy the green SHA, verify readiness and identity, and reopen work.
- A release evidence record captures source SHA, CI evidence, image/deployment identifier, deployed SHA, health/readiness result, operator, timestamp, and rollback target.
- Pilot mode is explicit. Supabase public email signup is disabled, admin invitations are used, and an active pilot-member authorization is required for project creation, generation, regeneration, and export.
- Pilot membership records cohort, source code, admission time, status, offer version, internal-note reference, and separate consent timestamps. Internal notes never contain creative content.
- The remote sample library and import endpoints are unavailable in pilot mode; there is no hidden live endpoint behind a removed tab.
- Billing continues to use server-sourced package data, existing credit reservations, exactly-once settlement, and the ledger. Repeated Starter packs are allowed. Refunds are operator-only exceptions or legally required reversals and must reconcile Stripe and the ledger idempotently.
- Production security headers include HSTS, deliberate CSP and `frame-ancestors`, `nosniff`, referrer policy, and permissions policy. CSP allowances are limited to required application, Supabase, Stripe, Sentry, image, and font origins.
- Trusted proxy behavior is verified against real forwarded requests. Expensive work has both existing process/IP controls and a per-user active-job ceiling.
- Shared input budgets cover compressed uploads, PDF pages, EPUB documents, extracted characters, remote compressed bytes, remote decompressed characters, and enforceable extraction time. Estimation and execution use the same limits. Unsafe PDF, EPUB, gzip, and remote-import inputs fail with a stable message and no partial project.
- Backend and frontend Sentry DSNs are configured in the deployed environment. Scrubbed test events prove that auth data, manuscripts, prompts, images, signed URLs, and provider secrets are absent and that alerts reach the operator.
- Snapshot configuration is verified by a restore drill into an isolated volume or machine. Account deletion and snapshot aging are documented; a manual process is acceptable for ten users.
- Customer-facing failure states expose a support link carrying only release SHA, project ID, station/stage, job/request ID, and error category.
- The first-run experience routes a zero-balance invited member to purchase before project creation. Funded members see the pilot contract, rights and provider acknowledgment, source limits, stage/station explanation, support route, and truthful post-export settled usage.
- Pilot-only copy is English. Other UI localization may remain, but the pilot does not add unfinished localized offer/support commitments.
- Product events are server-owned and limited to the approved lifecycle set: invitation, confirmation, checkout/purchase, project, checkpoint decisions, first panel, draw, export, support, failure, refund, feedback, and pilot completion.
- Event properties are small and bounded: file type, word-count bucket, quality preset, duration, page/panel count, flags, retries, settled credits, failure category, and acquisition source code. Creative content, secrets, names, prompts, images, and free-text support are excluded.
- Event writes are idempotent at the relevant user/project/job boundary. A separate feedback record stores moment, one rating/choice, bounded reason, optional free text, and follow-up permission. Marketing/case-study consent stays separate and off by default.
- The operator report is read-only and joins cohort membership, authoritative events, credit ledger, AI usage, feedback choices, support minutes, revenue, provider cost, retries, flags, and outcome state. Free text is redacted by default.
- Mock mode exercises the complete web journey and failure states without provider spend. One real-provider journey runs on the deployed application using a public-domain or explicitly licensed 6–12-page source.
- The proof package records source length, station duration, provider cost, settled credits, retries, flags, continuity misses, operator minutes, export counts, artifacts, and release SHA. It includes 30–50 accepted panels across recurring characters and locations.
- Proof thresholds are predeclared: no cross-user, auth, billing, reservation, or missing-export errors; every failed item recoverable without restarting the whole project; no accepted lettering inside panel images; repairable visual misses; and economics that fit the Starter offer or cause the offer to be resized before sale.
- A read-only pre-offer checker verifies deployed/CI SHA, health/readiness, headers, pilot mode, sample disablement, contacts, Sentry, Stripe mode, idle deployment status, and supplied manual evidence identifiers without printing secrets or mutating production.
- Outreach is authorized only by a documented GO for two users after the checker, two-user matrix, internal live purchase/refund, mock journey, real-provider proof, and every manual checklist item pass.
- After GO, invite two authors at a time. Do not invite the next wave until both current users export, withdraw, or are explicitly closed after support follow-up. Stop for cross-user exposure, billing mismatch, project loss, material legal/abuse incident, invalid economics, or operator overload.

## Testing Decisions

- Prefer deployed behavioral tests over implementation assertions. The primary acceptance test should exercise the same public UI/API paths an invited author and operator use.
- Keep pure policy tests for input budgets, event-property validation, offer disclosures, authorization status, refund eligibility, and readiness checks.
- Backend tests cover auth/membership dependencies, project isolation, credit settlement/refunds, security headers, input expansion limits, job ceilings, support diagnostics, event idempotency, and deletion behavior.
- Frontend tests cover pilot mode, invitation-only messaging, zero-balance purchase routing, source-limit guidance, disclosures, support links, settled export summary, feedback prompts, and non-pilot regression behavior.
- CI must run the existing renderer browser test plus the full backend and web suites. No browser-dependent renderer test may be skipped to make CI green.
- The two-user matrix is the highest-value deployed test for authorization, billing isolation, asset access, recovery, and deletion. Use separate real Supabase users and Stripe test mode before internal live rehearsal.
- The mock journey is the highest-value deterministic test for refresh, deep-link, session expiry, insufficient credits, provider refusal/timeout, partial draw failure, render failure, support, panel repair, and PDF/CBZ export.
- The real-provider proof is an acceptance test of provider routing, actual credit settlement, visual continuity, panel repair, and export—not a unit test and not a benchmark detached from the deployed product.
- Sentry, readiness, snapshot restore, support mailboxes, and every runbook require synthetic or manual evidence, not merely configuration assertions.
- The cohort report test uses a synthetic member and verifies correct funnel, cost, credits, retry, support, feedback, and permission aggregation while redacting free text and creative content.
- Prior art includes existing launch-safety, renderer, credit-estimate, billing, frontend room, stage-progress, and panel-review tests. New tests should follow their external-behavior style and preserve current stage, visual-anchor, compose-page, pinned-tail, and `~N credits` contracts.

## Out of Scope

- Public signup, public free credits, a free Chapter 1 tier, broad acquisition, paid advertising, automated cold outreach, referrals, CRM, lead scoring, programmatic SEO, subscriptions, storefronts, and marketplaces.
- A reader-magnet domain model, guaranteed page count, guaranteed completion, perfect continuity, copyright-protection guarantee, or KDP-acceptance claim.
- Multi-language pilot support, automated CD, horizontal scaling, external queues, multi-machine orchestration, a user-facing analytics dashboard, or self-service deletion/export beyond the reliable documented manual process.
- Automatic rights verification, automatic genre classification, legal advice, or publication approval.
- A backup operator, redundant support organization, or zero-touch operations.
- Public case-study automation or unsupported authorship-log marketing claims.
- Changes to the nine-stage pipeline decomposition, station grouping, Stage 9 lettering ownership, visual-anchor preservation, compose page JSON, pinned bubble-tail contract, or HTTP/UI pipeline entry points.
- Any customer outreach or payment request before Slice 7 issues a documented GO for two users.

## Further Notes

- Slice 0 is a prerequisite and supplies the name decision, offer contract, single-operator policy, mailboxes, support target, consent posture, and jurisdiction constraints.
- Slice 1 must finish before Slices 2–5 are treated as release work. Slices 2–5 may proceed in parallel after the release foundation is green.
- Slice 6 must test the integrated result of Slices 2–5. Slice 7 is the only authorization to begin customer outreach.
- The plan's proposed 6–12-page reader-magnet language is retained as an illustrative use case only; the enforceable commercial unit remains 1,200 credits per Starter purchase.
- The first ten customers are a learning cohort. After the cohort, choose whether to expand, repeat after fixes, change the offer/ideal customer profile, or stop.


