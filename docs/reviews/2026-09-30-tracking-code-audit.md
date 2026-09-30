# Tracking code audit — September 30, 2026

**Status: Current code audit with local SEO, replay-privacy and purchase-outbox fixes**, against HEAD `67012a9559c30e226c3a395ae448142f4dbb1796` plus local SEO changes. The initial audit was read-only; the two subsequently authorized fixes are implemented and verified below. Live settings remain unchanged.

Baseline: `/Users/jbuiles/Code/canary`, branch `main`, origin `git@github.com:FelipeBuiles/canary.git`, initially clean. No other checkout was used.

The supplied project 630262 baseline (4 dashboards, 50 insights, September 26–30, development events and localhost/backoffice replay metadata) is delegated context, not a fresh data export. A tiny mixed-environment sample does not establish abandonment or zero purchases. The reported saved stage-success insight using `stage_dispatched` measures admission, not completed output.

## Baseline evidence and findings (before the two authorized fixes)

Source paths starting `server/` below are relative to `novel_to_comic/src/novel_to_comic/`.

| Area | Assessment | File/line evidence |
| --- | --- | --- |
| First touch | Bounded campaign tokens/external referring domain captured once per module lifetime. Same-origin SPA navigation preserves acquisition; reload, new tabs and marketing/app origin changes lose it unless explicitly carried. | `web/src/telemetry.ts:44`, `:62`, `:66` |
| OAuth | Signup stores acquisition in auth metadata; callback URL carries bounded source/medium/campaign/referring domain, referral and sample. Google callback fills only fresh accounts (ten minutes) without acquisition. Delayed callback or best-effort update failure can lose attribution. Callback/account observation ordering merits testing. | `web/src/lib/authContext.ts:14`, `:34`, `:48`; `web/src/pages/auth/LoginPage.tsx:75`, `:100`; `web/src/pages/auth/AuthCallbackPage.tsx:23` |
| Signup milestone | Backdated, deterministic account-created UUID emitted on authenticated app load; accounts never loading the app are absent. Internal flag refreshed once per process. | `server/product_events.py:167`, `:179`; `server/routers/events.py:60` |
| Cookieless identity | Memory persistence and identified-only person profiles. Identify links current anonymous visit; reset when leaving/switching accounts. Anonymous/session continuity is not guaranteed through OAuth reload or Stripe return. Auth user ID joins purchases. | `web/src/telemetry.ts:255`, `:299` |
| Environment/internal/test filters | Environment/release defaults development/unknown; internal account IDs set person flag. No hard localhost/backoffice ingestion exclusion. Purchase properties lack explicit Stripe live/test mode. Verify deployed config and dashboard filters before interpretation. | `web/src/telemetry.ts:150`, `:201`; `server/product_events.py:113`, `:158`, `:179`; `server/telemetry.py:165`; `server/routers/billing.py:317` |
| Funnel | Outbox supports user/project/job/request joins. Stage starts supply project but no explicit run/job ID; reruns can mix. Proposed useful-output funnel: account_created → project_created → stage_started → page_ready → export_package_ready/download_requested, grouped by account and project. Add explicit run correlation before same-run claims. Page ready proves an artifact, not visual approval or whole-book completion. | `server/product_events.py:95`; `server/analytics_delivery.py:24`; `server/routers/pipeline.py:194`; `server/routers/pages.py:287` |
| Dispatch/completion | Draw emits stage_dispatched after queue admission; outcome can say succeeded while pages are pending. Page callbacks emit page_ready; draw-state synchronization does not emit stage_succeeded. Saved success chart must separate admission from actual output. | `server/routers/pipeline.py:249`; `server/routers/pages.py:276`, `:292` |
| Payments | Signed webhook validates paid receipt and atomically deduplicates ledger on payment intent. **Reliability gap:** analytics capture is best-effort after settlement; duplicate delivery skips capture, so a failed initial analytics write can be permanently missing. Recommend transactional outbox or deterministic reconciliation from settled ledger, tested without a real purchase. | `server/routers/billing.py:228`, `:283`, `:302`, `:317`; `server/product_events.py:141` |
| Delivery | Persisted events retry independently with stable insert IDs across acknowledgement splits. Protects existing outbox rows, not missing settlement events. | `server/analytics_delivery.py:16`, `:24`, `:41` |
| Costs | Reported/estimated/unknown confidence and source retained. Unknown is omitted, never zero. Vendor auto-calculated total is not authoritative. Keep customer charged credits, provider spend, estimates and gross purchase revenue separate. | `server/telemetry.py:326`, `:333`, `:343`; `server/routers/billing.py:305` |
| Failures | operation_completed includes complete/failed/cancelled status and deterministic terminal ID; filter status, not name. Unstarted queue dispatch reconciliation persists failed state/logs without execution-wrapper terminal capture. Completion-event charts can miss dispatch/restart failures. | `server/generation_jobs.py:485`, `:503`, `:534`; `server/durable_queue.py:255` |
| Replay/privacy | Inputs masked, images/artwork blocked, plugin network/console frames dropped, IDs/query URLs templated. **Review gap:** broad chrome selectors unmask all text in buttons/nav/labels/options; dynamic user titles/names may appear there. Attribute mask preserves non-URL attributes. Verify synthetic unpublished content in real replay, including editor/uploads/dynamic controls, before trusting the privacy claim. No observed disclosure is asserted. | `web/src/telemetry.ts:103`, `:125`, `:130`, `:280` |
| Consent | Configured SDK initializes without a consent gate here. Privacy page discloses replay. Stripe terms consent is payment consent, not replay consent. Product/legal policy should determine replay consent requirements and implementation should match; this is not a jurisdictional legal conclusion. | `web/src/telemetry.ts:266`; `web/src/pages/legal/PrivacyPage.tsx:70`; `server/routers/billing.py:165` |
| Feedback | Existing authenticated path stores text privately with ownership/project context and idempotent ID. Telemetry sends category/rating/feedback ID only. Use this path instead of manuscript-bearing event fields. | `server/routers/feedback.py:1`, `:34`, `:41`, `:46` |

## Original follow-up priorities (replay/privacy and payment capture now fixed below)

1. Close payment settlement/event atomicity gap with a failure-injection test.
2. Validate replay on synthetic unpublished content; narrow chrome unmasking, audit retained attributes and confirm consent policy.
3. Correct saved Draw-success semantics and production/internal/test/Stripe-mode segmentation after explicit settings authorization.
4. Add run correlation and terminal queue/restart outcomes; keep cost confidence separate.
5. Test cross-origin, reload, delayed OAuth callback and Stripe return acquisition with synthetic fixtures before funnel conclusions.

## Verification limits

No tracking source, live settings, billing behavior or generation changed. No push, commit, deployment, paid generation or real purchase. Live URLs were inaccessible through the web tool. No local development server was listening; repository instructions prohibit starting one without explicit request. DOM regression tests cover metadata after React and navigation; server-response tests cover before-JS metadata, XML/robots and private/unpublished-publication exclusion. Real-browser end-to-end verification remains outstanding.

## Check results

- Full frontend aggregate: 114 test files, 796 tests passed.
- SEO reader/sample/head regression group: 13 tests passed; acquisition/auth/telemetry focused group also passed (40 tests before the additional head-navigation test).
- Production build (ICU catalogs, TypeScript and Vite) and frontend lint passed. Build reports its existing large-chunk advisory; telemetry tests report package sourcemap warnings.
- Publication suite: 22 passed, four failed in existing hybrid lettering export tests because local Playwright Chromium was unavailable. These failures are outside SEO assertions. After the final unavailable-reader change, six focused metadata/sitemap/unpublished tests passed; the added actual-app crawler-route test also passed.
- Backend observability, events and billing-receipt integration: 35 passed, provider-free.
- Docs reliability and `git diff --check` passed. Generated API references were regenerated and had no tracked delta (crawler document endpoints are excluded from API schema).
- Live verification blocked: web tool could not access the URLs; shell curl reported DNS resolution failure for scenewright.ink. No local server/browser session was started.

## Follow-up verification — September 30, 2026

The previous browser blocker was a sandbox launch restriction, **not missing Chromium**. Installed pinned Chromium 153.0.8010.12 launched after sandbox escalation; no software installation or production renderer changes were needed. All 27 publication tests then passed, including the four hybrid-lettering tests previously reported as failed. An additional empty-curation/untrusted-host regression passed separately.

A disposable real `create_app(..., dev=False)` instance served the built frontend on loopback port 18763 with synthetic public book/private-publication/manuscript fixtures in a temporary directory. Uvicorn lifespan was disabled to avoid DB, queue and provider startup; ingestion/billing/provider environment keys were removed from the harness process, and all external browser requests were blocked. This verifies public-route rendering and navigation, not live auth/provider integration.

**20 real Chromium checks passed:** server startup; title/description/canonical before JS; escaped public introduction without injected scripts; unique metadata after JS; reader Close and reopen; SPA home navigation; Back and Forward; sample deep-link before/after-JS agreement; sample Close canonical; unknown and unpublished 404/noindex without private text; XML sitemap content/type/fixed host/private exclusion; robots content/type; empty showcase; absence of browser JS errors; server shutdown. The first sample-Close assertion checked before React effects settled; rerunning with URL/canonical condition waits passed without production code changes.

Final diff review confirms title/author/synopsis use HTML escaping, React text/DOM attribute assignment, catalog-matched sample queries, and escaped XML locations. Canonical hosts are configuration/fixed constants, never incoming Host/X-Forwarded-Host; the added spoofed-host regression confirms this. Empty curation yields only homepage/sample-shelf URLs. Sitemap never scans private projects or owner publication snapshots. Trusted server `SCENEWRIGHT_PUBLIC_URL` override and the fixed production frontend origin remain a configuration limitation for alternate-host deployments, already documented in public-books.md.

The harness `/tmp/canary-seo-browser-verify.py` is local supporting evidence, not a repository deliverable. Its temporary fixtures were deleted, browser closed, own server stopped; a port check confirmed no remaining listener. Live DNS access remains unresolved, so this establishes fixture-browser behavior, not deployed-site verification.

## Baseline audit severity and next actions (before authorized implementation)

- **High privacy validation risk (no observed leak):** replay chrome unmasking covers broad dynamic controls; non-URL attributes survive. Next: synthetic unpublished manuscript/title replay inspection, narrower explicit static-chrome allowlist, attribute allowlist, and a documented replay consent decision.
- **Medium analytics reliability:** settled payment may lack a purchase event after best-effort capture failure. Next: transactional purchase outbox or deterministic ledger reconciliation, plus failure-injection/dedup tests.
- **Medium measurement correctness:** Draw dispatch is counted as success in the supplied insight. Next: separate queued/dispatched from page-ready/completed, add durable draw terminal events, then correct the saved insight under separate authorization.
- **Medium funnel integrity:** no stable run join on stage starts, queue/restart terminal gaps, development/internal traffic and absent purchase Stripe-mode segmentation. Next: explicit run correlation and terminal contracts; validate production/internal/test/mode filters before interpreting conversion.
- **Medium attribution completeness:** memory-only first touch, origin transitions and delayed OAuth callbacks can lose acquisition. Next: provider-free cross-origin/reload/callback cases and account-observation ordering tests; avoid unsupported anonymous-session continuity claims.

No tracking code or live settings were modified during this follow-up.


## Authorized implementation — replay privacy and purchase recovery

**Fixed locally and tested; not deployed.** The initial audit established a risk,
not an observed real-user disclosure. Verification below uses distinctive synthetic
secrets exclusively, with no real user content or live analytics transmission.

Replay now masks all text, including dynamic controls and `data-ph-unmask`,
redacts arbitrary attributes and all unrecognized destinations, blocks SVG,
images/media/canvas/iframes/embedded objects, and rebuilds serialized full and
incremental rrweb frames from a structural allowlist. Arbitrary CSS, attribute
keys/values, plugin/custom frames and opaque packed snapshots cannot pass. It
also drops automatic top-level person-property envelopes and bounds exception
types. Known structural HTML tags, roles, geometry and route templates remain.
Event packing is disabled before the final scrubber; transport compression is
unchanged. This sacrifices visual styling and text visibility for privacy.
Consent behavior, sampling settings and memory identity were not broadened.

Actual Chromium 153.0.8010.12 verification (`scripts/verify_replay_privacy.py`)
passed with **5 replay events, 132 frames and 13 decoded SDK transport requests**.
The secret was absent from both before-send serialized events and intercepted
outgoing payloads, with usable full snapshots and mutation frames retained.
Coverage includes actual login/password inputs; authenticated Story editor with
synthetic manuscript title, author and brief; editing and a save-error response;
backoffice, auth-callback error, navigation and Back/Forward; dynamic attributes,
URLs, artwork, opt-out markers and exceptions. Test-owned bot-filter bypass and
recording activation are local SDK fixtures only. All ingestion/auth/API traffic
was intercepted, every other external browser request blocked. Its own Vite
server and browser were stopped. This establishes behavior in synthetic browser
fixtures, not a guarantee for untested future SDK versions or real-user payloads.

Payments now use `docs/migrations/2026-09-30-purchase-event-outbox.sql` and its
matching full-schema trigger. The billing writer freezes environment/release and
signed-session Stripe mode on the ledger INSERT; the trigger creates the purchase
outbox row in that same transaction. An event INSERT failure rolls back the grant
and leaves the webhook unacknowledged. A committed grant survives a process crash
with its event already persisted. A deterministic event UUID derived from ledger
ID becomes the stable vendor `$insert_id`; account attribution, package, credits,
gross amount and currency survive, without Stripe IDs or payment/customer payloads.
Existing ledger entitlement amounts and payment-intent uniqueness are unchanged.
The existing delivery worker retries outage/acknowledgement splits; duplicate
network delivery relies on vendor insert-ID deduplication, not exactly-once claims.

**23 real PostgreSQL tests passed** using only an existing postgres:17.11 Docker
image with tmpfs storage and a loopback port, then stopping/removing that container.
Coverage includes atomic rollback and recovery, concurrent duplicate/retry delivery,
test/live/unknown mode, account identity, fresh DB connections after restart,
actual billing-handler commit/response loss, vendor failure and lost acknowledgement,
same insert-ID delivery and empty outbox after acknowledgement, migration reruns,
no historical backfill and old-writer rollout guard. These include the existing
credit-ledger regressions. The existing independent checkout-session unique index
can reject a racing concurrent insert; its unacknowledged retry converges to one
grant/event. This existing entitlement behavior was preserved.

### Deployment requirements (not performed)

1. Apply the new migration before releasing the updated billing writer. The
   full schema also contains it. No production application, migration or backfill
   was performed here.
2. Deploy the updated backend and frontend normally. The new writer's explicit
   environment marker activates atomic trigger capture; old writers retain their
   existing best-effort path during rollout, avoiding two events per settlement.
   The durable guarantee begins with the new writer. New code must not run against
   the old schema; a missing column must produce an unacknowledged webhook retry.
3. Verify schema/trigger availability and the existing analytics outbox worker's
   production configuration on deployment; do not replay historical purchases
   without separate authorization. Keep the migration if rolling application
   code back. Current replay consent/settings remain unchanged.

### Remaining audit findings

Dispatch-vs-completion insight semantics, stable run correlation, queue/restart
terminal gaps, environment/internal/test dashboard filtering, acquisition across
reload/origin/delayed OAuth and the product/legal replay-consent decision remain
recommendations. They were not changed in this implementation. No real purchases,
paid generation, commit, push, deployment or live settings change occurred.

### Final regression checks and current implementation evidence

The final frontend suite passed **114 files / 798 tests**, including 20 focused
telemetry tests. Frontend lint and production build passed. The focused backend
observability, billing, launch-safety and error suites passed **90 tests**; the
disposable PostgreSQL suite passed **23 tests** as documented above. The existing
SEO Chromium harness passed **20 checks** against the final build, including
pre/post-JavaScript metadata, Close, Back/Forward, unavailable/private readers,
sample canonicals, XML sitemap, robots and an empty curated catalog. Docs
reliability and `git diff --check` passed. No production behavior was verified.

Current source evidence: replay serialization is in `web/src/telemetry.ts:139`,
attribute filtering at `web/src/telemetry.ts:168`, final event scrubbing at
`web/src/telemetry.ts:216`, and inspectable snapshot configuration at
`web/src/telemetry.ts:334`. The settlement writer freezes attribution at
`novel_to_comic/src/novel_to_comic/server/routers/billing.py:313`; the atomic
outbox trigger is `docs/migrations/2026-09-30-purchase-event-outbox.sql:9`,
with the rollout guard at line 18. Durable synthetic browser verification is
`scripts/verify_replay_privacy.py`; PostgreSQL failure/restart regressions are
`novel_to_comic/tests/test_purchase_outbox_postgres.py`.

## Authorized production migration — 2026-09-30

Operator: Codex executing the user’s explicit production migration and main-release
approval. Confirmed project `canary` (`dfzwfinycjaaxbqayceh`) and existing
production release `347e658`. The named function/trigger did not exist. Created a
private local custom-format PostgreSQL backup at
`/Users/jbuiles/.local/share/canary-backups/20260930T162609Z-purchase-outbox`
(directory 0700, archive 0600); listed the archive, fully decoded it offline to
`/dev/null`, and recorded its SHA-256 locally. No backup contents entered Git.
Applied the exact reviewed migration transaction with 5-second lock and 30-second
statement timeouts. Verified three text columns, enabled AFTER INSERT trigger,
SECURITY DEFINER with empty search path, and no public/anon/authenticated EXECUTE.
No purchase rows, entitlement changes or historical backfill were performed.
Release Ruff caught test formatting and fixture import warnings, corrected
without changing assertions; all backend Ruff and 23 disposable PostgreSQL
regressions passed afterward. Main push includes the existing user-authored
`67012a9` labs-fixes commit in addition to these reviewed changes.
