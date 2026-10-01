# Tracking corrections and controlled validation

**Status: Production rollout approved; signup migration applied, deployment pending.** Checkout
`/Users/jbuiles/Code/canary`, main, baseline
`a6a0fc567d9f0177a6113199a02b40ba7ecd3676`; baseline clean. No worktree,
commit, push, deployment, production migration, backfill, paid generation or
purchase was performed for this change set.

## Findings and changes

| Priority | Finding | Local correction and evidence |
| --- | --- | --- |
| High | Dispatch counted as successful generated output; Draw terminal absent | `server/routers/pipeline.py:194` persists run/stage attempt IDs; `server/routers/pages.py:254` emits terminal outcomes from actual rendered output and admitted job cohort states. Existing art cannot complete a rerun; empty plans cannot succeed. Success/failed share a terminal UUID per attempt (`server/lifecycle_events.py:19`). |
| High | Dispatch failure/restart recovery missed terminal telemetry | `server/generation_jobs.py:557` journals terminal intent in the same SQLite transaction as job state. `server/durable_queue.py:100` reconciles after all jobs restore. `server/analytics_delivery.py:57` retries journal transfer before vendor delivery; stable IDs survive acknowledgement splits. Recovery never resubmits generation. |
| High | App load backdated a fictitious signup observation | `server/product_events.py:176` now emits `account_observed` at observation time, retaining original signup date only as person metadata. New `docs/migrations/2026-09-30-account-created-outbox.sql` captures true auth inserts with fail-open analytics, without backfill. **Not applied**. Production rollout needs approval and prerequisite/object/duplicate checks. Outbox failure preserves signup; a service-role-only bounded reconciler recovers post-migration gaps; partial uniqueness prevents the old app-load writer duplicating trigger signups during rollout. |
| Medium | Generated pages treated as viewed or accepted | `web/src/pages/rooms/PagesRoom.tsx:434` emits `page_viewed` only after deliberate review opening and actual artwork load, once per mounted page/revision; excludes deep links/restored/automatic review. `server/routers/pipeline.py` emits `output_accepted` only after successful Draw approval, scope edition. It does not assert visual quality or per-page acceptance. |
| Medium | First touch disappeared across reload/new tab/OAuth delay | `web/src/telemetry.ts:65` stores only validated tokens for 24 hours. SDK identity stays memory-only. `web/src/lib/authContext.ts:34` carries bounded attribution and flow-start time across OAuth; existing metadata is not overwritten. The privacy page explicitly discloses token storage. No consent/replay configuration changes. |
| Medium | Costs mixed known/estimated/unknown | `server/lifecycle_events.py:63` uses existing usage/pricing calculation, retains estimated reservation separately, reports unknown usage counts and confidence. Unknown spend is absent on the serialized wire, not zero. Credit entitlement and pricing semantics unchanged. |
| Medium | Checkout did not expose mode | `server/routers/billing.py:223` adds `stripe_mode=test/live/unknown` from the created session; absent mode stays unknown. Existing settlement/webhook writer unchanged. |

Server source paths above are relative to
`novel_to_comic/src/novel_to_comic/`. Exact local contracts are documented in
[observability](../reference/observability.md#local-tracking-correction-contract-not-deployed).

## Controlled matrix and limits

- Provider-free backend: terminal dependency outage/restart, deterministic event
  identity, conflicting terminal reconciliation, privacy allowlists, partial Draw,
  empty Draw, rerun while old art exists, failure/cancel/unknown outcomes,
  rejected approval and successful approval. Existing credit-race/checkpoint,
  queue dispatch/restart and billing regressions remain active.
- Synthetic disposable PostgreSQL: true signup insert, idempotent/nonduplicated
  creation, bounded metadata, restricted trigger function execution,
  old-writer conflict, and forced outbox failure preserving signup and eventual idempotent recovery. Purchase
  outbox and ledger regressions use the same disposable database, never live.
- Frontend: deliberate open + loaded artwork, no pre-load milestone, no duplicate
  load, no restored/deep-link milestone, failed artwork, attribution TTL,
  malformed/denied storage, OAuth return context and delayed new-account matching.
- Installed Chromium 153.0.8010.12: seven checks in
  `scripts/verify_tracking_continuity.py`; reload, navigation, new tab, OAuth URL,
  storage secret exclusion, actual image failure/load. Every external/API/auth
  request intercepted; own loopback fixture server stopped. This is actual
  Chromium, not JSDOM, but it does not claim full real OAuth or real production
  stage execution.
- Browser product events remain best-effort and can be dropped by network failure
  or a closed tab. Local journal I/O failure is logged; analytics reliability
  depends on the existing persistent volume. Repeated independent review visits
  can generate repeated view events; use distinct account/project/page/revision
  counts, not raw events for accepted output. Actual visual review remains human.
- OAuth signup metadata is unavailable at the initial auth insert: those true
  signup events can have unknown acquisition. On return, `account_observed`
  sets bounded person attribution after metadata update; source charts should
  use that person attribution where available, not assume the initial event
  knew it. Users who never return remain unattributed.
- Historical app-load `account_created` events retain their old semantics; no
  historical event rewriting/backfill. New charts must use the new contract only
  after approved migration/deployment. Parent separately owns dashboard changes.

## Read-only production payment reconciliation

Aggregate-only transaction against Canary Supabase project
`dfzwfinycjaaxbqayceh`: 3 legacy settled purchases with unknown historical Stripe
mode; 3 exported `credits_purchased` events with unknown mode; 0 marked
outbox-managed settlements missing an event. There are no marked settlements,
so this does **not** establish a new production purchase through the deployed
outbox. Do not infer zero historical purchases or classify unknown as live.
No credentials, user identities, payment IDs or payloads were logged/shared.

## Verification record

The expanded shared fast gate passed: locked app/gateway audits, installed
compatibility, docs, Ruff, 168 backend tests (1 skipped), 122 frontend tests,
lint/build and root audit. The complete frontend release component passed 804
tests plus audits/lint/build. A full backend run passed 2,756 tests (9 skipped)
plus 61 stage contracts; later focused final lifecycle/queue/lettering checks
passed 106 (1 skipped), with final additions independently passing 12 lifecycle
cases. Earlier signup PostgreSQL checks passed 2; the fail-open revision passed all 4 signup cases. The final full shared gate result
is recorded below once complete; prior stops were real fixture failures and were
corrected rather than suppressed. Sandbox-only browser/cache checks were blocked
and rerun with the installed local-tool access needed by those checks.

New migration/deployment is required to enable true signup creation events.
The previously deployed purchase-outbox migration was neither changed nor reapplied.


### Earlier aggregate gate (before final refinements)

`npm run check:release` passed: 32 database checks, 2,758 backend tests (9
skipped), 61 stage contracts, 804 frontend tests, 36 gateway tests, both
gateway Docker startup modes (with/without PostgreSQL), production Docker
build, dependency audits, Ruff, frontend lint/type/build, and docs checks.
Final stage reconciliation/scheduling refinements additionally passed 91
focused tests. The earlier full gate stops and sandbox-only launch failures
were resolved; no checks were bypassed or weakened. Own PostgreSQL tmpfs
container was stopped and removed; own browser fixture server was stopped.
This earlier aggregate pass preceded the final stage refinements and fail-open signup revision. A final-state aggregate rerun is required. Live signup/payment/provider proof was never run.

### Exact changed files

- `docs/agents/pre-push.md`
- `docs/reference/observability.md`
- `docs/reviews/2026-09-30-tracking-code-audit.md`
- `novel_to_comic/src/novel_to_comic/server/analytics_delivery.py`
- `novel_to_comic/src/novel_to_comic/server/app.py`
- `novel_to_comic/src/novel_to_comic/server/durable_queue.py`
- `novel_to_comic/src/novel_to_comic/server/generation_jobs.py`
- `novel_to_comic/src/novel_to_comic/server/product_events.py`
- `novel_to_comic/src/novel_to_comic/server/routers/billing.py`
- `novel_to_comic/src/novel_to_comic/server/routers/events.py`
- `novel_to_comic/src/novel_to_comic/server/routers/pages.py`
- `novel_to_comic/src/novel_to_comic/server/routers/pipeline.py`
- `novel_to_comic/src/novel_to_comic/server/telemetry.py`
- `novel_to_comic/src/novel_to_comic/state.py`
- `novel_to_comic/tests/test_hybrid_lettering.py`
- `novel_to_comic/tests/test_observability.py`
- `novel_to_comic/tests/test_posthog.py`
- `scripts/check_release.py`
- `web/src/__tests__/authContext.test.ts`
- `web/src/__tests__/authForms.test.tsx`
- `web/src/__tests__/pageArtwork.test.tsx`
- `web/src/__tests__/pagesRoom.test.tsx`
- `web/src/__tests__/telemetry.test.ts`
- `web/src/api/events.ts`
- `web/src/components/pages/PageArtwork.tsx`
- `web/src/components/pages/RevisionDraft.tsx`
- `web/src/lib/authContext.ts`
- `web/src/pages/legal/PrivacyPage.tsx`
- `web/src/pages/rooms/PagesRoom.tsx`
- `web/src/telemetry.ts`
- `docs/migrations/2026-09-30-account-created-outbox.sql`
- `docs/reviews/2026-09-30-tracking-corrections-validation.md`
- `novel_to_comic/src/novel_to_comic/server/lifecycle_events.py`
- `novel_to_comic/tests/test_account_outbox_postgres.py`
- `novel_to_comic/tests/test_lifecycle_events.py`
- `scripts/verify_tracking_continuity.py`

## Fail-open signup rollout review

Apply the reviewed signup migration first, after production object/duplicate
checks and explicit approval. Verify trigger, cutover boundary and restricted
RPC grants; then deploy the worker/application. Trigger analytics errors produce
a SQLSTATE-only warning and preserve the auth insert. Recovery scans only accounts
created after the migration boundary, in batches of 100; it exports counts only
and grants no auth-table access. The trigger uses a 250 ms lock timeout.
Missing RPC/outbox remains observable and retryable; recovery needs a healthy
auth/database and product-events table. No historical signup backfill.

The old app-load writer and new trigger share the partial per-account uniqueness
constraint. Existing legacy events are retained, reported as legacy_observed,
and never rewritten. Repeated reconciliation uses the same deterministic ID.
The activation event name remains account_created with production environment;
account_observed stays a separate observation. The denominator changes after
cutover to include signups that never load the app: annotate the rollout and
do not compare pre/post conversion percentages as identical populations.

The three legacy purchases occurred July 20–30, 2026. Their export acknowledgement
is September 26, 2026; it does not change their occurrence timestamps. Their
environment and Stripe mode are unknown, so September launch/live-production
filters exclude them. An export acknowledgement alone does not prove current
PostHog retention/query visibility. No new managed production settlement was
observed, and no real purchase was conducted.

Live insight-filter verification was blocked by the PostHog project-settings
read approval review because that endpoint can return an API token. No
credential was printed. Event-contract compatibility is verified in local
code/tests; exact live insight filters and historical PostHog visibility remain
unverified in this follow-up. The parent owns dashboard changes.

## Final-state aggregate rerun

After all stage refinements and the fail-open signup revision,
`npm run check:release` passed (exit 0): 34 disposable PostgreSQL checks,
2,763 backend tests (9 skipped), 61 stage contracts, 804 frontend tests,
36 gateway tests, both gateway smoke modes, production Docker build,
locked app/gateway dependency audits, installed compatibility, root/web
audits, Ruff, frontend lint/type/build and documentation checks. Evidence:
`/tmp/tracking-release-failopen-final.log`. No implementation changed after
this gate began. The owned disposable PostgreSQL container was stopped.

Recommend the fail-open migration instead of gating signup on analytics.
Production migration and deployment require fresh approval. Inspect existing
named objects and duplicate account_created rows before rollout; do not overwrite
conflicting definitions. The already deployed purchase migration is unchanged
and must not be reapplied. Exact live insight filters and actual production
signup/purchase emission remain unverified; local controlled tests do not
establish that live proof.

Final-state `npm run check:push` also passed (exit 0); evidence:
`/tmp/tracking-push-failopen-final.log`. Documentation reliability and
`git diff --check` passed after recording results. HEAD remains
`a6a0fc567d9f0177a6113199a02b40ba7ecd3676`; 36 local changed/new files.

## Approved production rollout — 2026-10-01

Production Supabase `dfzwfinycjaaxbqayceh` prerequisites passed; new named
objects were absent and duplicate account_created accounts were zero. Backup:
`/Users/jbuiles/.local/share/canary-backups/20261001T000115Z-signup-outbox`,
6,196,228 bytes, private directory/archive permissions, archive listing and
full SQL decode verified (no live restore).

Only the new signup migration was applied, transactionally with 5-second
lock and 30-second statement timeouts. Cutover:
**2026-10-01T00:02:36.520134Z**. SQL SHA256:
`b199d16fce854e266bc8eb554ae78ddfc687875894b697ac161afc02eb1092fc`.
Exact function bodies, security-definer/search-path settings, 250 ms trigger
lock timeout, enabled auth trigger and service-role-only reconciliation were
verified. The installed trigger preserved a temporary fixture insert when
analytics failed; the fixture transaction was rolled back without creating
an auth user or event. The purchase migration was not reapplied. Earlier
local-only status statements describe the pre-approval validation history.
