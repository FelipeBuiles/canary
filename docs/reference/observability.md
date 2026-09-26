# PostHog and launch learning

Status: Current implementation; cloud activation and deployment remain separate.
Last reviewed: 2026-09-26.

## What is consolidated

PostHog replaces the Sentry clients and custom Langfuse exporter. The backend
uses one event client plus HTTP OpenTelemetry exporters directly to PostHog.
No collector or local analytics database is required. The six local Langfuse
Compose services are removed; existing volumes are untouched. Those services
were not running inside the Fly application, so their removal is not a measured
production RAM saving. Measure the rebuilt image and real peak memory before
reducing the Fly machine size.

- Durable `product_events` are forwarded in batches of 100 with stable
  `$insert_id` values. A delivery timestamp is written after HTTP acceptance;
  failures retry after ten seconds. Acceptance is not proof that every event is
  queryable in PostHog. Existing rows were excluded from backfill at cutover.
- Explicit backend/browser errors retain exception types and code locations;
  error messages, locals, source context, URLs, and automatic properties are
  removed. Source maps support browser error investigation when uploads are
  configured.
- `$ai_generation` records include model, duration, usage, funding, outcome and
  known cost. Manuscripts, prompts, output text, image bodies and references are
  excluded. `cost_status` distinguishes reported, estimated and unknown amounts.
  Unknown amounts are omitted; any vendor-derived estimate is not a ledger entry.
- Request → durable worker → stage → AI spans carry bounded identifiers and
  W3C trace context. Only selected `canary.observations` logs are exported.
  Generic tracing is a PostHog alpha capability; the selected project exposes its configuration with the expected
  `posthogDistinctId` correlation key. Live trace ingestion remains unverified. This is not automatic browser tracing or host infrastructure APM.
- Replay, autocapture, page views, surveys, console collection and IP enrichment
  are disabled. Browser identity uses the authenticated account ID and resets on
  account changes; no email or display name is sent.

Financial usage, reservations, paid-request recovery, and the operation journal
remain authoritative first-party data. Local opt-in diagnostic files remain
available for development. Telemetry never initiates paid retries. SDK/OTLP
queues are bounded to 256 records and HTTP calls have finite timeouts; diagnostics
can be dropped under load or shutdown. The application allows five seconds for
concurrent shutdown drains; this is not a delivery guarantee.

## Configuration and activation

The selected project is **630262**, in the US region. Onboarding is complete
on the capped free plan, without invitations or fabricated events. Its public ingestion token
is configured in ignored local `.env` and `web/.env.local` files. The approved personal key is restricted to this project with dashboard, insight,
and error-tracking write scopes, and stored in the ignored local environment with
mode 0600. No private management key is checked into the repository. No application deployment or
server restart was performed as part of configuration.

| Scope | Settings |
| --- | --- |
| Backend runtime | `POSTHOG_PROJECT_TOKEN`, `POSTHOG_HOST=https://us.i.posthog.com` |
| Sampling / release | `POSTHOG_TRACE_SAMPLE_RATE` (default 1), `CANARY_ENV`, `CANARY_VERSION` |
| Frontend build | `VITE_POSTHOG_PROJECT_TOKEN`, `VITE_POSTHOG_HOST`, `VITE_CANARY_ENV` |
| Source-map build only | `POSTHOG_PROJECT_ID`, private `POSTHOG_API_KEY` BuildKit secret |

EU projects must consistently use `https://eu.i.posthog.com`. The personal API
key must never be a `VITE_*` variable, Docker ARG, runtime browser value, or log
entry. The Vite plugin uploads maps only when its private key and project ID are
present, then deletes the generated maps. Without these values the build works
without map upload. A local verification build uploaded all 67 chunks to the live project under
`canary-web@c0ffdf7-posthog-local`. The plugin reported zero skipped uploads.
The public build contains neither source-map files nor the private key. This
verifies upload and cleanup, not a deployed error's symbolication.

The approved [migration](../migrations/2026-09-26-posthog-feedback.sql) was applied
to production Supabase on 2026-09-26. The SQL editor returned a network error;
a separate successful SELECT confirmed `product_events.posthog_exported_at`
and `customer_feedback` exist. The migration is transactional and guarded so a
rerun does not acknowledge newly accumulated events. It enables feedback RLS and
limits table access to the service role. It does not modify billing records.

For deployment, configure the runtime values in Fly. CI uses secret
`POSTHOG_PROJECT_TOKEN`, variables `POSTHOG_HOST` and `POSTHOG_PROJECT_ID`, and
private secret `POSTHOG_API_KEY` for build-time map upload. The checked-in workflow
passes the latter as a BuildKit secret. See [deployment](../deploy.md). Existing
Sentry/Langfuse credentials can be removed from deployment configuration after
cutover; they no longer activate code. Do not delete diagnostic volumes as part
of deployment.

With a scoped management credential loaded into the shell, provision launch
views using `python3 scripts/configure_posthog.py`. It creates a dashboard and
three named insights, reusing matching names in the first 100 returned results.
The views filter production events. The ordered account funnel has a seven-day
window and can include multiple projects per account; do not call it first-project
activation without a cohort analysis. The [launch dashboard](https://us.posthog.com/project/630262/dashboard/2139283)
and all three insights were provisioned and verified in the UI. PostHog currently
shows vendor sample charts because the project has no events; they are not user
evidence. Live ingestion remains unverified. The official wizard was not run: explicit instrumentation applies
the documented integration recipes while keeping content out of telemetry.

## Feedback and learning loop

Authenticated users can select **Give feedback** in the footer, choosing a
frustration, feature request, praise, or other comment. Messages are stored in
Supabase, not PostHog. The API checks project ownership, validates text length,
limits submission rate, and uses an account-scoped receipt for safe retries.
Only feedback ID/category/rating metadata enters analytics. Editing a failed
submission starts a new receipt; an ambiguous earlier success can therefore
produce two distinct comments, rather than silently losing the edit.

The operator Backoffice feedback inbox lists the latest 200 comments and marks
them reviewed, planned, or resolved using the existing operator credential.
It does not send customer replies. Account deletion cascades its feedback rows;
PostHog person/event deletion and logs/traces retention must be handled separately.
Review project retention and usage limits before inviting users.

Review once a week, or after the first few real authors:

1. Look at account milestones and the ordered first-output funnel. Distinguish
   `stage_dispatched` from completion, `page_ready` from a dispatch, and
   `export_package_ready` from `export_download_requested`. None proves that
   a reader liked an output or finished downloading it.
2. Inspect failures and credit blocks, then read associated private feedback.
   Keep staff/test traffic and incomplete observation windows out of decisions.
3. With the application's Supabase environment loaded, run
   `novel_to_comic/.venv/bin/python scripts/launch_learning_report.py --since 2026-09-26 --output work/launch-learning.md`.
   This creates a first-party count snapshot and a question/evidence/uncertainty/
   decision template. It does not infer sentiment, establish conversion rates,
   or automatically exclude staff. Review cohorts before filling conclusions.
4. Document one supported learning and one next change in a dated research note.
   Link evidence, record denominator/window, and state what would disprove it.
   No actual user learnings have been fabricated or claimed by this integration.

Keep the existing external uptime check and Fly operational monitoring. No alert
recipient, notification subscription, paid upgrade, or automatic weekly report
schedule was created. PostHog outage or quota exhaustion must not affect drawing,
billing, or recovery.

## Evidence and limits

Provider-free tests cover sanitization, cost handling, exporter failures, durable
retry IDs, worker context, and feedback authorization/idempotency. Frontend tests
cover privacy filtering and account lifecycle. Local frontend build and lint
passed during implementation. The full backend run passed 2,431 tests with 26
skipped and three outdated telemetry-test failures. After updating event
expectations and the stage mock, all 24 focused observability/feedback tests pass.
The frontend suite passes all 697 tests across 102 files with CI's non-secret
Supabase placeholders. Source-map upload and public-build cleanup were verified
successfully. `git diff --check` passes. Documentation checking reports only two
pre-existing missing showcase links, in `public-books.md` and the September 22
product-polish proposal; no new broken links remain.

The user waived a separate synthetic-journey gate. No paid generation, fake
customer journey, live event delivery, or real trace rendering has been used as
evidence. The separate source-map upload check is recorded above. Check those surfaces with the first authorized real
usage after deployment, without treating missing observations as user behavior.

Primary documentation and exact recipe decisions are recorded in the
[PostHog integration research](../research/2026-09-26-posthog-integration-recipes.md).
