# Scenewright Pre-Offer Readiness Implementation Plan

## Status

Proposed (2026-07-18).

This plan turns the findings in
[`docs/proposals/scenewright-prelaunch-acquisition-2026-07-18.html`](../../proposals/scenewright-prelaunch-acquisition-2026-07-18.html)
into the minimum implementation required before Scenewright can offer the
product to a paying author.

It is narrower than a public-launch plan. The target is a controlled,
invite-only **Founding Author Lab** with no more than ten paying customers,
admitted in waves of two. Public signup, a free tier, broad acquisition, and
growth loops are explicitly out of scope.

## Goal

Make it safe and truthful to offer one paid outcome:

> For $12, an invited author can turn one chapter or bonus scene into a 6–12
> page visual reader magnet or first-chapter issue, direct the key creative
> decisions, repair individual panels, and export PDF/CBZ.

The first offer is ready only when:

1. the deployed application is a known green revision;
2. only invited users can enter the paid workflow;
3. the user sees the price and scope before incurring generation cost;
4. billing, recovery, support, monitoring, and backup behavior are proven;
5. the complete customer outcome has been produced with real providers;
6. the product records enough non-sensitive evidence to learn from the cohort;
7. the Scenewright name has a documented use/rename decision.

## Scope Decisions

These are implementation constraints, not open questions for each slice.

### First offer

- **Audience:** invited, AI-open indie genre authors with a finished manuscript
  and clear rights.
- **Outcome:** one 6–12 page visual reader magnet or first-chapter issue.
- **Price:** the existing **Starter** pack — $12 for 1,200 non-expiring credits.
- **Payment:** paid first. Do not add a public free-credit grant before the
  first cohort.
- **Capacity:** ten total customers, admitted two at a time.
- **Language:** English only for the first cohort. The app may retain other
  languages, but the offer and support commitment are English-only.
- **Access:** Supabase admin invitation; public account creation disabled.
- **Sample library:** disabled for the pilot. It is not free, it adds a remote
  import surface, and it confuses the paid first-run contract.
- **Support:** operator-assisted and asynchronous, with a published response
  target. This is a product pilot, not a zero-touch launch.
- **Brand:** no public promotion or brand spend until the SceneWrite /
  Scenewright risk has a written practitioner recommendation.

### Product invariants

- Keep the nine backend stages discrete.
- Keep stations as frontend presentation only.
- Do not move generated text into image generation; lettering remains Stage 9.
- Preserve `visual_anchor` verbatim.
- Preserve the compose page JSON and pinned tail contracts.
- Continue using HTTP/UI entry points for pipeline operations; there is no
  `pipeline run` command.

## Current-State Delta — 2026-07-18

| Area | Current evidence | Remaining gap |
|---|---|---|
| Repository | HEAD `819ca0e`; local `main` is two commits ahead of `origin/main` | The intended release is not pushed or CI-validated; unrelated user worktree changes must remain untouched |
| CI | Latest visible remote runs are failing | Backend CI does not install Playwright Chromium before renderer tests |
| Deployment | One Fly machine is deployed; `/api/health/ready` reports Supabase and LiteLLM healthy | Deployed image is not tied to the current green SHA; full acceptance evidence is absent |
| Deploy safety | Operator-only activity endpoint and deploy-check script exist | No enforced drain; pilot deployment needs a maintenance-window procedure |
| Billing | Packages, reservations, exactly-once crediting, and usage settlement exist | Live-mode internal purchase, approved-exception reversal, and full customer-path proof are absent |
| Auth | Supabase auth and password reset exist | Public signup remains visible; invitation-only posture is not implemented or verified |
| Browser safety | Trusted hosts and HTTPS exist | CSP, HSTS, nosniff, referrer, and frame policies are absent |
| Input safety | Compressed uploads are capped | PDF pages, EPUB expansion, extracted characters, and remote story decompression are not bounded |
| Monitoring | Sentry integrations exist | No deployed DSNs, scrubbed test event, or operator alert is proven |
| Backups | Fly volume is now 10 GB and snapshots are configured | Restore drill and deletion-retention behavior are not proven |
| Support/legal | Terms, Privacy, AUP, and contact configuration exist | Mailboxes, response process, deletion/export, refund, DMCA/abuse, and incident runbooks are not proven |
| First run | Homepage and project wizard promote a sample story | A new account has no credits; the first experience can stop at a surprise credit wall |
| Learning | Ledger and provider usage data exist | No cohort/source record, product events, feedback capture, or outcome report exists |
| Product proof | Eight-panel benchmark and deterministic fixtures exist | No accepted 30–50-panel reader-magnet proof with real provider cost and repair data |
| Name | `scenewright.ink` is owned | Active adjacent SceneWrite product creates unresolved confusion risk |

## Dependency Order

```text
Slice 0: external decisions
    ↓
Slice 1: green, identifiable release
    ↓
Slice 2: invite-only access + paid offer contract
    ↓
Slice 3: security, recovery, monitoring, support
    ↓
Slice 4: truthful first-run UX
    ↓
Slice 5: cohort learning instrumentation
    ↓
Slice 6: internal proof production
    ↓
Slice 7: deployed acceptance + offer decision
```

Slices 2–5 may be developed in parallel after Slice 1 is green, but Slice 6
must test their integrated result and Slice 7 is the only authorization to
begin customer outreach.

## Slice 0 — Lock External Decisions and Operators

### Objective

Resolve the decisions that code cannot safely infer and assign a named operator
to every live-system responsibility.

### Tasks

1. Obtain a practitioner recommendation on SceneWrite / Scenewright covering
   federal, state, common-law, domain, and relevant international confusion.
2. Record one explicit outcome:
   - **use Scenewright for the pilot**, with any geographic or copy constraints;
     or
   - **rename before offering**, which blocks customer-facing work in later
     slices until replacement identifiers are chosen.
3. Confirm the offer contract:
   - $12 Starter purchase;
   - 6–12 page outcome;
   - one source chapter or bonus scene;
   - author supplies/attests to rights;
   - estimates vary and credits settle from actual usage;
   - no promise of perfect continuity, copyright protection, or KDP acceptance.
4. Assign named humans for:
   - release/deployment;
   - customer support;
   - billing/refunds;
   - abuse/DMCA/legal notices;
   - security incidents;
   - data export/deletion;
   - provider-cost review;
   - pilot admissions and case-study permissions.
5. Create and verify monitored `support@`/`hello@` and `legal@` inboxes.
6. Choose the support target for the pilot. Recommended: acknowledge within one
   business day; generation-blocking failures within four business hours.

### Artifacts

- `docs/ops/pilot-offer-contract.md`
- `docs/ops/operator-ownership.md`
- written name-clearance recommendation stored outside the repository if it is
  privileged; link only a non-sensitive decision record from the repository.

### Exit Criteria

- [ ] Written use/rename decision exists.
- [ ] Offer scope and exclusions are approved.
- [ ] Every operational lane has a named owner and backup.
- [ ] Support and legal mailboxes receive test messages.

## Slice 1 — Produce a Green, Identifiable Release

### Objective

Make the repository, CI, container, and deployed process agree on one immutable
release identity.

### Primary Files

- `.github/workflows/ci.yml`
- `Dockerfile`
- `fly.toml`
- `novel_to_comic/src/novel_to_comic/server/app.py`
- `novel_to_comic/src/novel_to_comic/server/sentry.py`
- `novel_to_comic/src/novel_to_comic/server/deployment_status.py`
- `scripts/check_deploy_safe.py`
- `novel_to_comic/tests/test_html_renderer.py`
- `novel_to_comic/tests/test_launch_safety.py`
- `docs/deploy.md`

### Tasks

1. Install Playwright Chromium in the backend CI job after dependency sync and
   before pytest. Use the Python environment that executes the renderer tests.
2. Keep `test_multiline_text_is_verified_inside_actual_svg_fill` as a real
   browser test; do not skip it in CI.
3. Add a public, non-sensitive release identity to a metadata endpoint. Extend
   `/api/health` or add `/api/version` with:
   - application version;
   - git SHA;
   - build timestamp.
4. Pass the git SHA through the Docker build as `CANARY_VERSION`; use the same
   value for Sentry release tagging.
5. Document the exact manual deployment sequence:
   - announce maintenance window;
   - stop accepting new pilot work;
   - check `/api/ops/deployment-status` until idle;
   - deploy the green SHA;
   - verify release identity and readiness;
   - reopen work.
6. Add a release evidence template recording:
   - source SHA;
   - CI run URL;
   - image/deployment ID;
   - deployed SHA;
   - health/readiness result;
   - deploy operator and timestamp;
   - rollback target.
7. Push the intended release branch and require every CI job to pass for that
   exact SHA before deploying it.

### Tests

```bash
cd novel_to_comic
rtk uv run ruff check .
rtk uv run pytest -q tests/test_html_renderer.py tests/test_launch_safety.py
rtk uv run pytest -q

cd ../web
rtk npm run lint
rtk npm run test
rtk npm run build

cd ..
rtk docker build \
  --build-arg VITE_SUPABASE_URL=https://ci-smoke.supabase.co \
  --build-arg VITE_SUPABASE_PUBLISHABLE_KEY=sb_publishable_ci_smoke \
  --build-arg VITE_CANARY_ENV=production \
  -t canary:pre-offer .
```

### Exit Criteria

- [ ] Chromium-backed renderer test passes in CI.
- [ ] Backend, web, dependency audit, and Docker jobs pass on one SHA.
- [ ] Local branch is pushed; no customer release depends on unpushed commits.
- [ ] Running app reports the same SHA as the green CI revision.
- [ ] Rollback target and deploy evidence are recorded.

## Slice 2 — Enforce Invite-Only Access and the Paid Pilot Contract

### Objective

Ensure that only accepted authors can enter the product and that the first
commercial action is the agreed $12 Starter purchase.

### Primary Files and Systems

- Supabase Authentication dashboard
- `web/src/pages/auth/LoginPage.tsx`
- `web/src/pages/auth/SignupPage.tsx`
- `web/src/pages/HomePage.tsx`
- `web/src/pages/landingCopy.ts`
- `web/src/App.tsx`
- `web/src/pages/Library.tsx`
- `web/src/pages/CreditsPage.tsx`
- `web/src/components/wizard/UploadStep.tsx`
- `novel_to_comic/src/novel_to_comic/server/routers/projects.py`
- `novel_to_comic/src/novel_to_comic/server/routers/billing.py`
- `novel_to_comic/src/novel_to_comic/server/credits.py`
- new operator-only refund route under
  `novel_to_comic/src/novel_to_comic/server/routers/`
- `docs/supabase-schema.sql`
- `docs/deploy.md`

### Tasks

1. Disable public email signup in Supabase for the pilot.
2. Use Supabase admin invitations for admitted authors; test confirmation and
   password creation on the production domain.
3. Add `CANARY_PILOT_MODE=true` as an explicit production flag.
4. In pilot mode:
   - remove the public “Create Account” tab;
   - make `/signup` explain that access is invitation-only;
   - change homepage CTAs from account creation to “Founding access is
     invite-only” or a monitored contact/application route;
   - retain normal sign-in and reset-password flows.
5. Add a `pilot_members` table keyed by authenticated `user_id` with:
   - cohort;
   - acquisition source;
   - admitted timestamp;
   - status (`invited`, `active`, `paused`, `complete`, `removed`);
   - offer version;
   - internal notes reference, not manuscript content;
   - metrics-consent timestamp;
   - separate nullable marketing/case-study permission timestamps.
6. Add a backend `require_pilot_member` dependency for project creation,
   generation, regeneration, and export routes while pilot mode is on.
   Authentication alone must not grant generation access.
7. Keep account, legal, support, and purchase pages reachable so an invited but
   not-yet-funded member can prepare the account.
8. Disable the remote short-story catalog and import endpoints in pilot mode.
   Return 404 or a stable unavailable response; do not leave a hidden frontend
   tab pointing at a live public endpoint.
9. Validate the existing package contract from the server response:
   `starter = $12 / 1,200 credits`. Do not duplicate package price constants in
   pilot copy.
10. Keep the published policy aligned with the current Terms: credits are
    non-refundable except where required by law or when an operator approves a
    documented exception. Do not advertise a general refund window.
11. Add a safe exception-refund workflow before taking money:
    - operator-only authorization;
    - look up the original Stripe payment intent and ledger grant;
    - refuse an automatic refund when any credits from that grant may have been
      consumed or ownership is ambiguous;
    - issue the Stripe refund and compensating ledger debit as one documented
      operation with recovery steps;
    - persist Stripe refund ID, operator, reason, amount, credits reversed, and
      timestamps;
    - make retries idempotent on Stripe refund ID;
    - never silently leave refunded money and spendable credits together.
12. Configure Stripe live mode only after a complete test-mode rehearsal.
13. Perform one internal live $12 purchase and an approved exception refund
    before accepting a customer payment. Confirm the ledger and Stripe stay
    consistent.
14. Record the accepted offer version on the pilot membership/purchase so later
    changes do not silently alter the cohort contract.

### Tests

- Frontend:
  - pilot mode hides public account creation;
  - `/signup` shows invite-only state;
  - normal mode retains existing signup behavior;
  - disabled sample library has no reachable UI.
- Backend:
  - authenticated non-member cannot create/run/regenerate/export;
  - active member can;
  - paused/removed member cannot start new paid work;
  - pilot gating is off outside pilot mode;
  - package display is server-sourced.
- Refund workflow:
  - unknown, duplicate, partially used, and already-reversed grants fail safely;
  - approved unused grant refunds once and removes the same credits once;
  - Stripe success plus local-write failure has a documented recoverable state.
- Deployed:
  - direct Supabase public signup fails;
  - an admin-invited author can confirm, sign in, and reset a password.

### Exit Criteria

- [ ] Anonymous and ordinary authenticated users cannot enter generation work.
- [ ] One admin-invited pilot member can reach the Credits page.
- [ ] The remote sample catalog/import is unavailable in pilot mode.
- [ ] Test-mode and internal live-mode Starter purchases settle exactly once.
- [ ] Approved exception refund/reversal behavior is idempotent, documented,
      and reconciled.

## Slice 3 — Close Security, Recovery, Monitoring, and Support Gaps

### Objective

Prevent one malformed input, failed provider call, restart, account mix-up, or
unanswered report from becoming the cohort's defining experience.

### Primary Files and Systems

- `novel_to_comic/src/novel_to_comic/server/app.py`
- `novel_to_comic/src/novel_to_comic/server/body_limit.py`
- `novel_to_comic/src/novel_to_comic/server/ratelimit.py`
- `novel_to_comic/src/novel_to_comic/server/routers/projects.py`
- `novel_to_comic/src/novel_to_comic/stages/s1_extract.py`
- new `novel_to_comic/src/novel_to_comic/server/security_headers.py`
- new `novel_to_comic/src/novel_to_comic/input_limits.py`
- `novel_to_comic/tests/test_launch_safety.py`
- `.env.example`
- `fly.toml`
- Sentry, Supabase, Stripe, Fly volumes, and email-provider dashboards
- new `docs/ops/` runbooks listed below

### Tasks — Browser and Request Safety

1. Add production security-header middleware:
   - `Strict-Transport-Security`;
   - `Content-Security-Policy` with deliberate `connect-src`, image, font,
     Stripe, Supabase, and Sentry allowances;
   - `X-Content-Type-Options: nosniff`;
   - `Referrer-Policy`;
   - `frame-ancestors` in CSP;
   - a deliberate `Permissions-Policy`.
2. Add tests for headers on HTML, API, error, and redirect responses.
3. Verify Fly's forwarded client IP behavior with real requests and configure
   trusted proxy handling so rate-limit keys cannot be spoofed.
4. Add a per-user expensive-job ceiling in addition to process-local/IP limits.
   For the pilot, one active heavy generation job per user is sufficient.

### Tasks — Input and Remote Import Safety

5. Introduce shared input limits with production defaults for:
   - uploaded compressed bytes;
   - PDF pages;
   - EPUB document count;
   - extracted characters;
   - remote compressed bytes;
   - remote decompressed characters;
   - extraction elapsed-time budget where enforceable.
6. Apply the same limits to upload estimation and actual Stage 1 extraction so
   the accepted input cannot expand beyond the execution limit later.
7. Reject encrypted, malformed, or over-budget PDFs/EPUBs with a stable user
   message and no partial project state.
8. Even though the sample library is off in pilot mode, bound remote download
   and gzip decompression before the endpoint can be enabled again.

### Tasks — Monitoring and Recovery

9. Provision real backend and frontend Sentry DSNs.
10. Send a scrubbed test exception from each surface and verify:
    - no auth header, cookie, manuscript, prompt, or signed asset URL appears;
    - release SHA is attached;
    - an alert reaches the operator.
11. Monitor `/api/health/ready` separately from Fly's cheap routing health
    check; alert on sustained dependency failure.
12. Confirm the 10 GB Fly volume, snapshot schedule, and retention.
13. Perform a restore drill into a separate volume/machine and prove that a
    project can be opened and exported after restore.
14. Document how deleted-account project files and snapshots age out; manual
    execution is acceptable for ten users, but the procedure must be real.

### Tasks — Support and Incident Operations

15. Add a reusable in-product support link that includes only:
    - release SHA;
    - project ID;
    - station/stage;
    - job/request ID when present;
    - error category.

    Never include manuscript text, prompts, images, auth data, or provider keys.
16. Place the support link on:
    - insufficient-credit errors;
    - failed generation jobs;
    - provider refusal/quota/timeout states;
    - account and billing pages;
    - export failures.
17. Write minimal runbooks:
    - `docs/ops/support-triage.md`
    - `docs/ops/billing-refunds.md`
    - `docs/ops/failed-generation-recovery.md`
    - `docs/ops/account-export-deletion.md`
    - `docs/ops/abuse-dmca.md`
    - `docs/ops/security-incident.md`
    - `docs/ops/backup-restore.md`
    - `docs/ops/pilot-deployment.md`
18. Test each runbook once with a synthetic case and record the result.

### Exit Criteria

- [ ] Required headers are present on the live origin.
- [ ] Oversized/malformed PDF, EPUB, and remote gzip cases fail safely.
- [ ] One user cannot monopolize all expensive generation capacity.
- [ ] Backend and frontend Sentry events alert with safe payloads.
- [ ] Readiness failure alerts without removing the only machine from routing.
- [ ] Snapshot restore produces an openable/exportable project.
- [ ] Every customer-facing failure has a monitored support route.
- [ ] Support, billing, deletion, abuse, incident, and recovery runbooks have
      been exercised.

## Slice 4 — Build a Truthful Paid First-Run Experience

### Objective

Make the invited author's path unambiguous from first sign-in to first useful
export, with no surprise credit wall and no promise that exceeds the pilot.

### Primary Files

- new `web/src/pages/PilotWelcomePage.tsx`
- `web/src/App.tsx`
- `web/src/pages/Library.tsx`
- `web/src/pages/CreditsPage.tsx`
- `web/src/components/wizard/UploadStep.tsx`
- `web/src/components/InsufficientCreditsDialog.tsx`
- `web/src/pages/rooms/StoryBibleRoom.tsx`
- `web/src/pages/rooms/StyleRoom.tsx`
- `web/src/pages/rooms/CastRoom.tsx`
- `web/src/pages/rooms/DrawRoom.tsx`
- `web/src/pages/rooms/ComposeRoom.tsx`
- `web/src/i18n.tsx`

### Tasks

1. Route a newly invited pilot member with no purchase/project to `/welcome`.
2. Show the five-step pilot contract:
   - buy the $12 Starter pack;
   - choose one chapter/bonus scene and upload it;
   - approve story, look, and cast;
   - review/repair panels;
   - export the 6–12 page issue.
3. Show what is and is not included:
   - included: one pilot issue, existing editing/export tools, non-expiring
     unused credits;
   - not promised: a specific page count from every input, perfect continuity,
     fixed total compute, copyright protection, or publication acceptance.
4. Require the user to acknowledge:
   - they own or control the submitted source rights;
   - generated interior images may require platform disclosure;
   - the pilot processes the selected source using third-party generative
     providers under the published terms/privacy policy.
5. Keep the acknowledgment version and timestamp with the pilot membership.
6. Move the purchase before project creation for zero-balance pilot members.
   Do not create a project and automatically start `extract` only to fail on
   insufficient credits.
7. For funded members, change the wizard to upload-only in pilot mode and state
   the accepted file/size limits before selection.
8. Add a pilot-size helper:
   - recommend one chapter/bonus scene;
   - show extracted word count before generation if cheaply available;
   - warn when the source is unlikely to fit the 6–12 page pilot scope;
   - allow the user to go back and upload a smaller source.
9. Keep backend estimates authoritative at every paid gate. Treat the current
   client-side project range as orientation only and label it accordingly.
10. Add an always-visible “Need help?” route during pilot stages.
11. After the first export, show:
    - actual credits used;
    - remaining credits;
    - pages/panels exported;
    - a link to structured feedback;
    - no upsell until feedback is captured or dismissed.
12. Gate pilot-only strings behind the pilot flag. Do not add unfinished
    Spanish/French pilot translations; launch the cohort explicitly in English.

### Tests

- Zero-balance member reaches purchase before project creation.
- Funded member can create a project and start extract.
- Oversized pilot source can be replaced without orphaned project data.
- Offer acknowledgment is versioned and required once.
- Every paid action still uses server estimates and `~N credits` phrasing.
- Export summary uses settled ledger data, not estimates.
- Non-pilot UI retains the normal project path.

### Exit Criteria

- [ ] An invited user can explain the price, scope, and risks before paying.
- [ ] No first-run path promises a free sample.
- [ ] Zero balance cannot trigger a surprise paid-stage failure.
- [ ] One funded user can upload, complete all gates, and export.
- [ ] Actual cost and remaining credits are visible after export.

## Slice 5 — Add Minimum Cohort Learning Instrumentation

### Objective

Record enough authoritative, privacy-safe data to decide whether to continue,
without building a general analytics platform before ten customers exist.

### Primary Files

- `docs/supabase-schema.sql`
- new `novel_to_comic/src/novel_to_comic/server/product_events.py`
- `novel_to_comic/src/novel_to_comic/stage_runtime.py`
- `novel_to_comic/src/novel_to_comic/server/credited_job.py`
- `novel_to_comic/src/novel_to_comic/server/routers/projects.py`
- `novel_to_comic/src/novel_to_comic/server/routers/pipeline.py`
- `novel_to_comic/src/novel_to_comic/server/routers/pages.py`
- `novel_to_comic/src/novel_to_comic/server/routers/billing.py`
- new `novel_to_comic/src/novel_to_comic/server/routers/pilot.py`
- new `web/src/components/PilotFeedbackPrompt.tsx`
- new `scripts/pilot_report.py`

### Data Contract

Add a server-owned `product_events` table with:

- `id`
- `user_id`
- `project_id` nullable
- `event_name`
- `stage` nullable
- `job_id` nullable
- `properties` small JSON object
- `occurred_at`
- `release_sha`
- `offer_version`

Allowed event names:

- `pilot_invited`
- `account_confirmed`
- `starter_checkout_started`
- `starter_purchase_settled`
- `project_created`
- `extract_approved`
- `style_selected`
- `cast_approved`
- `first_panel_generated`
- `draw_approved`
- `first_export_completed`
- `support_requested`
- `generation_failed`
- `refund_completed`
- `pilot_feedback_submitted`
- `pilot_completed`

Allowed property examples:

- source file type;
- source word-count bucket;
- quality preset;
- stage duration;
- page/panel count;
- flag count;
- retry count;
- settled credits;
- failure category;
- acquisition source code.

Forbidden analytics content:

- manuscript or screenplay text;
- prompts or visual anchors;
- character/location names;
- images or signed asset URLs;
- email address in event properties;
- auth headers, cookies, tokens, provider responses, or model reasoning;
- free-text support or feedback content in `properties`.

### Tasks

1. Make server lifecycle points authoritative. Do not infer purchase, stage
   approval, generation, or export completion from button-click analytics.
2. Insert events idempotently using a stable uniqueness key where retries can
   occur (`event_name + user/project/job` as appropriate).
3. Add a separate `pilot_feedback` table with:
   - moment (`first_panel`, `first_export`, `pilot_end`);
   - one rating/choice;
   - one bounded reason code;
   - optional free text stored separately and treated as customer content;
   - permission to follow up.
4. Ask only three times:
   - after first panel: “Does this feel like your story?”
   - after first export: “Is this useful enough to share with readers?”
   - at pilot end: “Would you continue with another issue/book?”
5. Keep marketing/case-study permission separate from product feedback.
   No checked-by-default permission.
6. Build `scripts/pilot_report.py` as a read-only operator report that joins:
   - pilot membership/source;
   - authoritative events;
   - credit ledger;
   - AI usage events;
   - feedback choices.
7. Report per customer and cohort:
   - invited → confirmed → paid → project → cast → panel → export;
   - time between milestones;
   - pages/panels;
   - retries/flags/failures;
   - provider cost, settled credits, revenue, contribution before support;
   - operator support minutes entered manually;
   - final contribution after support time;
   - case-study/quote permission state.
8. Add deletion behavior for events and feedback to the account-deletion
   runbook and privacy page if retention language changes.

### Tests

- Duplicate webhook/stage/export retries do not duplicate milestone events.
- Events reject forbidden/oversized property keys.
- User RLS cannot read another user's events or internal cohort metadata.
- Pilot report is read-only and redacts free text by default.
- Account deletion handles cohort data according to the documented policy.
- Mock mode produces lifecycle events but zero provider cost/credit debit.

### Exit Criteria

- [ ] A synthetic pilot appears end-to-end in the cohort report.
- [ ] Purchase, stage, generation, and export milestones come from server truth.
- [ ] No creative content or secret appears in product events.
- [ ] Cost, revenue, retries, support time, and outcome can be compared per user.
- [ ] Feedback and marketing permission are separate records.

## Slice 6 — Produce the Internal Proof Package

### Objective

Demonstrate the exact paid outcome internally before asking an author to buy it.

### Inputs

- local mock replay mode for deterministic UX/recovery testing;
- one public-domain or explicitly licensed 6–12 page pilot source;
- real production provider routes and pricing;
- the visual-consistency evaluator and panel flags;
- the deployed application, not a local-only pipeline shortcut.

### Tasks

1. Run the complete journey in mock mode through the web UI:
   - invited member;
   - Starter balance fixture;
   - upload;
   - all four stations;
   - panel flag and regeneration;
   - compose edit;
   - PDF and CBZ export;
   - feedback and cohort report.
2. Use mock mode to exercise failure states without provider spend:
   - insufficient credits;
   - provider failure/refusal/timeout;
   - partial draw failure;
   - page-render failure;
   - browser refresh/deep link;
   - session expiry;
   - support request.
3. Run the same outcome once with real providers in the deployed environment.
4. Produce 30–50 accepted panels across recurring characters and locations.
5. Record:
   - source length;
   - elapsed time by station;
   - actual provider cost and settled credits;
   - retries and panel flags;
   - continuity failures by type;
   - operator intervention minutes;
   - export page/panel count;
   - final artifacts and release SHA.
6. Predeclare acceptable pilot thresholds before reviewing results:
   - zero cross-user/auth/billing errors;
   - zero unrecovered reservations;
   - zero missing export pages;
   - no generated lettering inside panel images accepted as final;
   - every failed item recoverable without restarting the entire project;
   - cost fits within the Starter contract or the offer is resized before sale;
   - visual misses are repairable within a documented retry/flag budget.
7. Review the proof as a prospective author:
   - Does it preserve recognizable story beats?
   - Is the cast/world coherent enough to continue?
   - Is the repair workload understandable?
   - Is the exported artifact useful as a reader magnet?
8. Create an internal proof report. Do not publish it until claims, rights, and
   artifact permissions are reviewed.

### Artifacts

- `docs/launch/pre-offer-proof-report.md`
- retained test PDF/CBZ in an approved non-repository location if too large or
  rights-sensitive
- machine-readable evaluation record under the existing visual-evaluation
  structure
- cohort report for the synthetic/internal pilot member

### Exit Criteria

- [ ] Complete mock UI journey passes.
- [ ] Required failure/recovery scenarios pass.
- [ ] One real-provider deployed journey reaches PDF and CBZ export.
- [ ] 30–50 panel proof and miss log exist.
- [ ] Actual cost fits the offer or the offer has been corrected.
- [ ] Internal reviewer accepts the artifact as useful enough to offer.

## Slice 7 — Deployed Acceptance and Offer Authorization

### Objective

Run one final evidence-based gate on the exact release that will serve the first
two paying authors.

### Automated Preflight

Add `scripts/check_pre_offer_ready.py` as a read-only checker. It should fail
unless it can verify:

- expected release SHA equals deployed release SHA;
- CI evidence URL/SHA is supplied;
- `/api/health` and `/api/health/ready` are healthy;
- required security headers are present;
- pilot mode is enabled;
- sample import is disabled;
- support/legal contacts are configured;
- Sentry DSNs are configured;
- Stripe mode is explicitly selected;
- the deployment is idle before maintenance operations;
- the operator supplies paths/IDs for manual evidence that cannot be checked
  automatically.

It must not print secrets or mutate production state.

### Manual Acceptance Matrix

Run with two real Supabase users and Stripe test mode first.

| Scenario | User A | User B | Expected |
|---|---|---|---|
| Auth | confirm/login/reset/logout | confirm/login/reset/logout | independent sessions |
| Project access | create/read/run A | attempt A URL/API | B receives no data/access |
| Credits | buy/settle A | read A ledger | B receives no ledger/balance |
| Generation | run/regenerate A | start own job | per-user ceiling and fair queue |
| Recovery | interrupt A draw | continue B | A reservation releases; B remains usable |
| Export | export A PDF/CBZ | request A assets | B receives no assets |
| Deletion | delete/export A account data | continue B | A handled per runbook; B unaffected |

Then repeat the commercial path with one internal live Stripe purchase and
refund before taking an external payment.

### Offer-Ready Checklist

No outreach or payment request goes out until every box is checked.

#### Brand and Contract

- [ ] Scenewright use/rename decision recorded.
- [ ] $12 / 6–12 page offer copy approved.
- [ ] Rights, AI-use, cost, copyright, disclosure, and refund language agree
      across homepage/pilot page, signup, Terms, Privacy, AUP, and Stripe.

#### Release

- [ ] Exact release SHA pushed and green in every CI job.
- [ ] Deployed app reports the same SHA.
- [ ] Release evidence and rollback target recorded.
- [ ] Maintenance/deploy procedure exercised.

#### Access and Billing

- [ ] Public signup disabled at Supabase and in the UI.
- [ ] Only active pilot members can create/run/regenerate/export.
- [ ] Sample catalog/import disabled.
- [ ] Test purchase, duplicate webhook, unpaid webhook, refund, and internal
      live purchase all reconcile.

#### Safety and Operations

- [ ] Security headers verified live.
- [ ] PDF/EPUB/remote import limits tested.
- [ ] Per-user expensive-job ceiling tested.
- [ ] Backend/frontend Sentry events and alert verified.
- [ ] Dependency-ready alert verified.
- [ ] Snapshot restore drill passed.
- [ ] Support/legal mailboxes and all runbooks exercised.

#### Product Outcome

- [ ] Mock journey and failure matrix passed.
- [ ] Real-provider 6–12 page journey exported PDF and CBZ.
- [ ] 30–50 panel proof, cost record, repair log, and internal review exist.
- [ ] Starter economics cover the promised pilot scope with reasonable repair
      headroom.

#### Learning

- [ ] Pilot membership/source is recorded.
- [ ] Server milestone events reach the cohort report.
- [ ] Cost/revenue/retry/support/outcome report works.
- [ ] Feedback and permissions are captured separately.
- [ ] Privacy/deletion behavior covers new records.

### Exit Criteria

- [ ] `check_pre_offer_ready.py` passes for the deployed release.
- [ ] Two-user matrix passes.
- [ ] Internal live purchase/refund passes.
- [ ] Every manual checklist item links to evidence.
- [ ] Named product, operations, and billing owners sign a **GO for two users**.

## First Customer Rollout After GO

This is execution of the validated offer, not another product-development
phase.

1. Invite two authors.
2. Do not invite the next two until both current users have either:
   - exported;
   - withdrawn;
   - or been explicitly closed after support follow-up.
3. Review the cohort report and support log after each wave.
4. Fix any repeated blocker before the next wave.
5. Stop immediately for:
   - cross-user data exposure;
   - double charge or unreconciled ledger;
   - unrecoverable project loss;
   - material legal/abuse incident;
   - provider cost that invalidates the Starter offer;
   - support load exceeding the named operator's capacity.
6. After ten paid pilots, use the scorecard from the acquisition brief to
   choose one of:
   - expand to 25 invitees;
   - repeat the 10-user lab after fixes;
   - change the offer/ICP;
   - stop.

## Explicitly Deferred Until After the First Ten

Do not put these on the critical path to the first offer:

- public signup;
- public free credits or a free Chapter 1 tier;
- automated cold email or community posting;
- affiliate/referral rewards;
- CRM integration;
- lead scoring and enrichment automation;
- programmatic SEO or broad content production;
- retargeting or paid ads;
- public case-study automation;
- creator storefront or reader marketplace;
- subscription pricing;
- multi-language pilot support;
- horizontal scaling, external queue, or multi-machine orchestration;
- automatic CD;
- a user-facing analytics dashboard;
- full self-service data export/deletion if the documented manual process is
  reliable for ten users;
- authorship-log marketing claims beyond what legal review and real evidence
  support.

## Rough Effort and Critical Path

Effort classes assume one engineer plus part-time operator/legal work. They are
planning ranges, not delivery promises.

| Slice | Engineering | External/ops | Critical-path note |
|---|---:|---:|---|
| 0 — decisions/operators | S | M | Name review may dominate elapsed time |
| 1 — green release | S–M | S | Must finish first |
| 2 — invite/offer gate | M | M | Requires Supabase and Stripe dashboard work |
| 3 — safety/operations | L | L | Restore, Sentry, and runbooks require real drills |
| 4 — first-run UX | M | S | Depends on offer/access decisions |
| 5 — cohort learning | M–L | S | Keep schema/event set intentionally small |
| 6 — proof package | M | M | Provider latency and visual review dominate |
| 7 — acceptance | M | M | Cannot be compressed into a code-only check |

Likely critical path:

```text
name decision → green release → pilot access → security/ops → first-run UX
→ instrumentation → real-provider proof → two-user/live-payment acceptance
```

## Recommended First Execution Slice

Start with **Slice 1 only**:

1. install Playwright Chromium in backend CI;
2. add release identity to the container and health/version response;
3. add release evidence template;
4. run full local verification;
5. push the two local commits plus the CI/release fix;
6. require one all-green CI run before developing against a new release base.

This converts the current unpushed, unvalidated state into a stable foundation
for every later slice and removes the risk of building pilot gating,
instrumentation, and support behavior on a revision that cannot pass its own
release gate.
