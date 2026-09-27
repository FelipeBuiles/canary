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
  `posthogDistinctId` correlation key. Live request, worker, stage, and AI span ingestion was verified on 2026-09-26; worker and AI spans retain parent links. This is not automatic browser tracing or host infrastructure APM.
- Replay, autocapture, page views, surveys, console collection and IP enrichment
  are disabled. Browser identity uses the authenticated account ID and resets on
  account changes; no email or display name is sent.

New `ai_usage_events` writes keep compact database projections: allowlisted
scalar request controls, SHA-256/byte-count summaries of response schemas and
provider envelopes, and selected runtime IDs/statuses. They omit nested request
content, revised prompts, runtime event lists, feature dumps, and duplicated
identity metadata. Source-unit lists become counts and fingerprints. Scalar
diagnostic strings are capped at 256 characters. Page/correction labels, funding,
costs, token usage, provider IDs, and reconciliation fields remain available.
Database writes request minimal responses; provider payloads and in-memory
diagnostics are not mutated. This changes future writes only, without deleting
or compacting historical records.

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
five named insights, reusing matching names in the first 100 returned results.
The three launch views filter production events. The two diagnostics tables show the last seven days, grouped by environment: cost confidence and AI outcomes by feature/model. Unknown costs remain blank and are counted separately; the cost view uses Canary’s `cost_usd` with `cost_status`, never PostHog’s inferred `$ai_total_cost_usd`. The ordered account funnel has a seven-day
window and can include multiple projects per account; do not call it first-project
activation without a cohort analysis. The [launch dashboard](https://us.posthog.com/project/630262/dashboard/2139283)
and its three launch insights were provisioned and verified in the UI. The two diagnostic insights were added and their queries verified against live development events on 2026-09-26. Events, logs, and traces are arriving; production traffic and browser exception symbolication remain unverified. The official wizard was not run: explicit instrumentation applies
the documented integration recipes while keeping content out of telemetry.

## Local launchers

`dev.sh` and `dev-prod.sh` load root `.env`, then `web/.env`, then
`web/.env.local`; exported shell values always win, including empty values.
Absent browser PostHog settings inherit the public backend token and host.
The default environment label is `development` for both browser and backend,
including the local production-image test. Production dashboards exclude it.
Local releases default to the Git revision with a dirty suffix for tracked edits (`local` outside Git), plus a UTC timestamp and launcher PID. Each restart has a distinct release, including when untracked code changed; this identifies a launcher session rather than a reproducible source snapshot. Explicit versions still win. `VITE_CANARY_VERSION` inherits `CANARY_VERSION` unless explicitly set; Docker builds and runtime receive the same backend version. Backend and browser errors include environment, release, and schema version; delayed product delivery preserves the original release. Product `source` describes creation source, while `event_origin` records `server` or `web`.

AI observations preserve known cache-read and cache-creation token counts and
explicitly mark Canary's input totals as cache-inclusive. Claude's runtime cache
writes are retained in `UsageRecord` alongside reads. Calls that fail without
usage still carry the selected funding and inferred provider, without invented
token counts or costs. Historical events are not rewritten. PostHog's built-in
cost display can still show catalog estimates or zero for unknown subscription
costs; use the cost-confidence view, where unknown costs remain blank.

Both launchers report configured/disabled status without printing credentials;
this is not a delivery probe. Restart existing services manually after changes.

`CANARY_LOCAL_DIAGNOSTICS=true` opts into detailed local files; the default is
false. Financial accounting and recovery records remain active independently.
There is no `--observability` flag or local Langfuse service. Docker forwards
backend telemetry settings and uses `POSTHOG_API_KEY` only as a build secret for
optional source-map upload, together with `POSTHOG_PROJECT_ID`. No key means no
upload. Old analytics volumes are not deleted by these launchers.

## Local terminal output

Local logs keep one job completion summary, actionable warnings, and failures.
Successful HTTP requests, AI request starts, and job starts are debug-level;
queue-worker success/defer chatter and duplicate telemetry records are filtered
only at the terminal handler. PostHog logs/events and metrics are unaffected by
that handler filter. AI error summaries include feature, model, page, and operation
context when available. Missing generated assets stay quiet, but asset HTTP 5xx
responses are visible.
Missing or incompatible artifact reads during stage loading use debug-level
local logs, including their 404/409 request summaries. The API still returns the
same recovery instructions; unrelated conflicts and failed writes remain visible.

Exceptions show a short type/message summary by default. Set
`CANARY_LOG_TRACEBACKS=true` for full Rich tracebacks, and `CANARY_LOG_LEVEL=DEBUG`
for verbose progress. Tracebacks omit locals and terminal width is capped at 140
columns. Usage database failures show their event ID, exception type, and database
code rather than dumping a failed row. This does not repair database schema drift
or provider session limits. Restart the local process manually to apply changes.

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

The user waived a separate synthetic-journey gate. No paid generation or fake customer journey was initiated for verification. A later read-only audit verified existing development event/log/span delivery and parent relationships, without establishing production delivery or visual trace rendering. The separate source-map upload check is recorded above. Check those surfaces with the first authorized real
usage after deployment, without treating missing observations as user behavior.

Primary documentation and exact recipe decisions are recorded in the
[PostHog integration research](../research/2026-09-26-posthog-integration-recipes.md).
