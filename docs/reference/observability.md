# PostHog and launch learning

Status: Current implementation; cloud activation and deployment remain separate.
Last reviewed: 2026-10-11.

## What is consolidated

### Optional GA4 acquisition analytics

GA4 is implemented alongside PostHog; deployment and database activation are
separate. The production web stream is `G-R9Q5LX1E00`, set only in the Depot
CI build as `VITE_GA4_MEASUREMENT_ID`. Docker, Compose, and `dev-prod` builds
default to no ID, so local production-mode builds never report to the live stream. Development builds
and builds without a valid ID do not load Google. The public measurement ID
is configuration, not an API secret.

`web/src/lib/ga4.ts` loads Google's tag only after an explicit Google Analytics
choice. The banner offers allow/decline; `/legal/privacy` provides a way to
change that choice. It controls GA4 specifically, independently of the existing
PostHog diagnostics. Declining disables subsequent GA4 collection, removes
host-only `_ga` cookies, and drops pending page views. Re-accepting in the same
visit does not resend a page view already sent, and the loaded tag may keep its
in-memory client ID until the page reloads. Preference storage denial
limits the choice to the current visit. Choices also synchronize across tabs.

React Router sends manual page views using canonical route templates, static
page titles, bounded campaign tokens, and referring origins or canonical routes.
Raw query strings, fragments, project/book IDs, private titles, and account IDs
are omitted. Global tag defaults use the same sanitized values for automatic
engagement events. Google signals and advertising personalization are disabled.
Enhanced Measurement must remain **off** in the GA4 web stream; `send_page_view:
false` disables the initial automatic view but cannot alone disable history
events. The stream setting was disabled in the Google UI on 2026-10-11.

After the tag loads with consent, authenticated browsers may claim one `sign_up`
attempt via `POST /api/events/ga4-signup`. An atomic update claims only their
server-confirmed `account_created` row from the preceding 24 hours. Tabs and
devices cannot claim it twice. Apply
`docs/migrations/2026-10-11-ga4-signup-claim.sql` before the release: it adds the
claim marker and excludes existing signups. A lost response, navigation during
the claim, ad blocker, or Google outage can lose this optional report; it is
never retried as a new conversion. Supabase's signup record remains authoritative.
Delayed confirmations beyond 24 hours do not generate a GA4 signup conversion.
The browser coordinator retains its one attempt across React remounts and checks
the current account and consent again before reporting a successful claim.

Rollout verification: accept on a public landing page, navigate and check one
sanitized page view per route in GA4 DebugView/Realtime; decline and verify no
further collection and no `_ga` cookies; confirm a new account produces one
`sign_up`, with returning accounts producing none. Production receipt has not
been established by local mocked tests. `sign_up` was registered as a key event
in GA4 on 2026-10-11, without a default monetary value. Revenue/Measurement
Protocol reporting is a later integration and is not implemented here.

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
  arbitrary error messages, locals, source context, URLs, and automatic properties
  are removed. Recognized error codes and diagnostic message templates survive.
  Source maps support browser error investigation when uploads are
  configured.
- `$ai_generation` records include model, duration, usage, funding, outcome and
  known cost. Manuscripts, prompts, output text, image bodies and references are
  excluded. `cost_status` distinguishes reported, estimated and unknown amounts.
  Unknown amounts are omitted; any vendor-derived estimate is not a ledger entry.
  Generations nest in an AI trace tree and carry version and timing fields; see
  [AI traces and author outcomes](#ai-traces-and-author-outcomes).
  Text calls carry instruction-template and response-schema fingerprints;
  image calls carry a rendered-request fingerprint (`request_sha`) and provider
  wire schema version. A rendered-request fingerprint varies with story content
  and is not a prompt-template version. Author metrics include the generation ID
  and exact render revision they judge. Fingerprints do not assert provider deduplication.
- Request → durable worker → stage → AI spans carry bounded identifiers and
  W3C trace context. Browser API calls send `traceparent`, `X-Request-ID`, and
  a recorder session UUID in `X-Canary-Session-ID`; validated context survives
  durable job serialization. Responses expose `X-Request-ID` and `X-Trace-ID`.
  `api_request_completed` records route templates, method, status, outcome, job
  IDs returned by the API, and elapsed
  time, including failure context retained on browser exceptions. Backend events
  carry the recorder session as `$session_id` for replay correlation. Request and
  response bodies, auth headers, query strings, and public baggage are excluded.
  Only selected `canary.observations` logs are exported.
  Generic tracing is a PostHog alpha capability; the selected project exposes its configuration with the expected
  `posthogDistinctId` correlation key. Live request, worker, stage, and AI span ingestion was verified on 2026-09-26; worker and AI spans retain parent links. This is not automatic browser tracing or host infrastructure APM.
- Browser telemetry initializes after page load in an idle slot. The bundled
  `web-vitals` entry explicitly enables LCP, INP, CLS, and FCP capture. The privacy
  boundary retains finite nonnegative scalar values and canonical route templates;
  metric entries, DOM attribution, private image URLs, and network timing stay
  excluded. These are document Web Vitals, not independent LCP measurements for
  every client-side room change. See the [performance audit](../reviews/2026-10-06-web-vitals.md)
  for the baseline and verification limits.
- Session replay and click autocapture (including `$rageclick`) feed
  Self-driving Replay Vision. The recorder is bundled (`posthog-recorder`;
  the no-external SDK loads no scripts). Replays mask all inputs and author text.
  Shared buttons and station navigation may expose literal catalog labels via
  `data-ph-safe-label`; interpolated labels and `[data-ph-unmask]` cannot bypass
  masking. Images, SVG, media,
  canvas, iframes, embedded objects and `[data-ph-block]` are blocked. A second
  boundary scrubs serialized full snapshots and mutations: arbitrary attributes,
  inline styles, content-bearing URLs, custom/plugin frames and opaque packed
  events are excluded. Class names survive only when present in a trusted app
  stylesheet. Same-origin build CSS links survive; development CSS is rebuilt
  from the live application stylesheet, with unsafe URLs and imports removed.
  Structural roles/types/geometry and route templates survive. Replay
  event packing is disabled so this boundary can inspect the DOM; transport
  compression remains available. Dynamic inline styling and artwork stay omitted.
  The SDK reads its remote config, which enables recording, from the regional
  `*-assets.i.posthog.com` host. The production CSP `connect-src` must allow it
  alongside the ingestion host; blocking it keeps events flowing but silently
  disables replay (no production replays were captured before 2026-10-02).
  Autocapture retains known HTML tag chains without classes, text or attributes. `scrubEvent`
  in `web/src/telemetry.ts` enforces these limits; the Privacy page states them.
- Browser events retain the configured public ingestion token (required by
  PostHog after `before_send`), SDK/version and event/pageview IDs, browser/OS
  versions, language, device type, screen/viewport dimensions, timezone, and
  session timing metadata. Navigation and session-entry URLs use route
  templates; referrers keep domains only. Unknown properties, raw user agents,
  page titles, and automatic person-property payloads remain excluded.
- Application metrics (`http.server.*`, `jobs.*`, `pipeline.stage_*`,
  `ai.call*`) come from the app client. The LiteLLM gateway emits
  `http.server.*`, `llm.provider.*`, and `gateway.completions` as service
  `canary-gateway` from `litellm/canary_metrics*.py`, using the same
  `POSTHOG_PROJECT_TOKEN`/`POSTHOG_HOST`; its exception reports redact messages.
  Metric attributes are bounded labels, never IDs or paths.
- Automatic page views, surveys, heatmaps, dead clicks, console collection and
  GeoIP enrichment are disabled; explicit canonical page views are described
  under [launch analytics dashboards](#launch-analytics-dashboards). Browser
  identity uses the authenticated account ID and resets on account changes; no
  email or display name is sent. Anonymous identity and SDK session state persist
  in first-party localStorage; sign-in merges the anonymous visit, and sign-out
  or account switching resets the device identity. Denied storage falls back to
  memory with anonymous merging disabled. The SDK's `ip: false` does not stop PostHog
  storing `$ip` on ingested events; only the project's "Discard client IP data"
  setting does.

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

## AI traces and author outcomes

AI Observability shows each job as one tree. `ai_span` (`server/telemetry.py`)
emits a node only when an AI generation ran beneath it, so provider-free work
exports nothing:

```text
$ai_trace  job.<operation>            trace ID = operation ID; status, run_id, stage_attempt_id
  $ai_span   stage.<name>             one per StageRuntime.execute
    $ai_span   structured.<feature>   outcome: accepted | accepted_after_retry | repaired | failed
      $ai_span   attempt              attempt_number; outcome: accepted | rejected | repaired | unparseable
        $ai_generation                attempt_number, prompt_sha, schema_sha, timing, tokens, cost
    $ai_span   image_route            route (openai | fal-queue), fallback_reason
      $ai_generation                  one per route attempt, including an absorbed one
```

Labs stage arms are roots named `labs.<stage>` with `experiment_id` (the run),
`variant` (the arm) and an opaque `fixture_id`; image comparisons are
`labs.image`. `$ai_session_id` is the experiment for Labs and the project
otherwise, so the Sessions view groups one comic's traces.

Generation fields worth comparing:

- `prompt_sha`, `schema_sha`: first 16 hex digits of the SHA-256 of the
  effective system prompt and the requested output schema. They change when a
  template or schema changes; user content is never hashed into them.
- `admission_ms`: from call start to provider execution (usage-row insert,
  credit authorization, serialized Codex/Claude queue). `execution_ms`: the
  rest of `latency_ms`. `$ai_time_to_first_token`: first streamed content after
  execution began. A phase that was not observed is absent, never zero.
- `$ai_reasoning_tokens`: a subset of `$ai_output_tokens`, never added to it.
- A provider success whose output failed validation is a successful generation
  under a `rejected` attempt. Judge task success by the `structured.*` span.

Author verdicts are the primary quality signal. Each is a durable
`page_outcome` product event with `outcome`, `page_number`, the judged
`render_revision`, and `generation_id` (the render's `$ai_span_id`). Outcomes:
`redraw_requested`, `correction_submitted` (`category` = issue type or
`manual`, `mode` = correction mode), `render_selected`, `issue_reported`,
`issue_accepted`, `issue_dismissed`, `visual_review_requested`,
`replan_requested`, `lettering_saved` (`mode` = `edited` | `reviewed`) and
`lettering_reset`. Renders record their `ai_trace_id` in provenance; art
verdicts on such renders are also `$ai_metric` events named `author_<outcome>`
on that trace, parented to the generation. Lettering verdicts never score the
art. Renders drawn before this field existed have product events only; join
them to generations through `generation_id`.

[Canary — AI quality & decisions](https://us.posthog.com/project/630262/dashboard/2167063)
reads these fields: author rejection rate by draw model, structured task
outcomes by feature, calls by feature and prompt version, Labs variants, and
weekly verdicts. Its tiles are HogQL; they fill once the instrumented backend runs.

### Local content capture

Local development traces are complete: text generations carry `$ai_input`
and `$ai_output_choices` whenever `CANARY_ENV=development`. Set
`CANARY_AI_CONTENT_CAPTURE=false` to keep local traces metadata-only. The
environment is checked at capture and again in the send scrubber, so
production never sends bodies. Local manuscripts therefore reach PostHog;
PostHog keeps them for the AI events retention period (30 days by default).
Messages are truncated to 60,000 characters. Images and references are never
attached. Spans, metrics, logs and OTLP attributes never carry content.

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
| Launch-view exclusion | `CANARY_INTERNAL_ACCOUNT_IDS` (comma-separated account UUIDs) |
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

## Launch analytics dashboards

Two pinned dashboards answer the launch questions; both filter
`environment=production` and exclude the project's **Internal / Test users**
cohort (`$internal_or_test_user = true`):

- [Canary — Launch pulse](https://us.posthog.com/project/630262/dashboard/2145123):
  7-day KPIs with prior-week comparison (new accounts, active authors, pages
  drawn, exporting authors, gross credit revenue, homepage visits); daily growth
  and output; activation funnel (account → project → style → first page →
  export, 14-day window); visit → signup funnel; accounts by acquisition source;
  homepage visits by referrer; weekly retention and lifecycle; credit block →
  checkout → purchase; friction signals; station views.
- [Canary — Pipeline health & cost](https://us.posthog.com/project/630262/dashboard/2145124):
  stage success rate and known AI spend KPIs; per-stage reliability and duration;
  AI calls by feature (failure rate, error types, p50/p95 latency, spend); queue
  wait and run time; daily spend by cost confidence; cost per page drawn; spend
  by stage; AI failures by error type; stage failures by cause; exceptions.

"Active author" is the **Author active** action: `project_created`,
`stage_started`, `stage_approved`, `style_selected`, `station_viewed`,
`page_outcome` (author page verdicts; replaced the never-emitted `panel_regenerated` on 2026-10-03), `export_download_requested`, `checkout_started`, and
`feedback_submitted`. Background completions such as `page_ready` never count as
activity. A project annotation marks the production launch on 2026-09-28.
The earlier **Canary launch learning** dashboard and the configuration script
remain valid; the new dashboards were provisioned with the PostHog MCP.

Data added for these views:

- **Canonical page views.** The browser sends `$pageview` on each route change
  after auth state is known. Paths become route templates (`/`, `/library` for
  a signed-in root, `/read/:id`, `/project/:id/<room>`, `/other`); the URL is
  rebuilt from the template, the referrer is reduced to an external domain, and
  only bounded `utm_source`/`utm_medium`/`utm_campaign` tokens and browser, OS,
  and device labels survive the scrubber. Anonymous visitors stay personless.
  LocalStorage preserves identity across reloads and tabs. Signing in from an
  anonymous visit identifies that visit; switching accounts resets the device
  identity. Storage denial uses memory and counts separate visits.
- **Signup attribution.** First-touch source (UTM source, `book_referral`,
  external referring domain, or `direct`) is captured on landing, sent as
  anonymous `signup_submitted`, and saved in Supabase user metadata as
  `acquisition`, so it survives the email-confirmation hop.
- **`account_created`.** On each app load the browser calls
  `POST /api/events/account`. The server records one outbox event per account,
  dated at the Supabase signup time, with a deterministic ID (repeat writes are
  ignored) and `acquisition_*`/`referring_domain`/`referred_by_book` properties
  plus `$set_once` person properties (`signed_up_at` and the same attribution).
  Accounts created before attribution capture report `acquisition_source=unknown`.
  Existing accounts are recorded on their next visit; accounts that never return
  are not backfilled. A best-effort `$set` sends `$internal_or_test_user` once per
  process from `CANARY_INTERNAL_ACCOUNT_IDS`.
- **Durations and causes.** Stage outcome events carry `latency_ms`;
  `stage_failed` carries `error_type` (the stage `error_code`, else
  `stage_error`); `operation_completed` carries run `latency_ms` beside
  `queue_ms`. Earlier events have none of these.

Person properties cross the wire only through an allowlist in `telemetry.py`
(`$internal_or_test_user`, `signed_up_at`, and attribution fields). Revenue
tiles use gross `credits_purchased.gross_amount_cents`; refunds are not netted
and the ledger stays authoritative. No alert, subscription, or recurring report
was created.

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


## Atomic purchase analytics outbox

Apply `docs/migrations/2026-09-30-purchase-event-outbox.sql` before deploying the
updated billing writer; do not run a historical backfill. The full schema also
includes the change. A settled Stripe purchase INSERT and its content-free
`credits_purchased` event commit in the same PostgreSQL transaction. Event IDs
are deterministic from the ledger row ID; duplicate payment-intent deliveries
retain the original grant and event. A lost webhook response after commit leaves
both durable. Outbox delivery retries vendor failures with the same `$insert_id`;
a lost vendor acknowledgement can resend the event and relies on PostHog insert-ID
deduplication, rather than claiming exactly-once network delivery.

The writer freezes environment, release and Stripe `livemode` as `test`, `live`
or `unknown` (missing legacy evidence is never guessed). The trigger preserves
the account UUID and purchase amount/package/currency only; no Stripe IDs,
payment payloads, customer details or attribution URLs enter telemetry. Existing
account attribution joins remain unchanged. The new writer's environment marker
activates atomic capture; old releases retain their best-effort path during the
migration-before-code interval, avoiding duplicate events. The guarantee starts
when the updated writer runs. Do not remove the migration while that writer is
active; missing columns or a failed event INSERT must leave the webhook
unacknowledged for retry, not silently settle without an event.

## Tracking correction contract (production rollout)

**Status: Production signup cutover 2026-10-01T00:02:36.520134Z; initial
tracking rollout verified at `002e5e0d`.** Supersedes the historical app-load
signup interpretation above. Terminal summaries preserve request-estimate
provenance with the validated follow-up correction.

- `stage_started`, `stage_dispatched`, `stage_succeeded`, `stage_failed` carry
  `run_id` (owning pipeline operation UUID) and `attempt_id` (new stage attempt
  UUID). Dispatch means scheduling only. Draw terminal success waits for all
  admitted page jobs; reruns cannot succeed from previous artwork. Terminal
  outcomes distinguish `awaiting_review`, `failed`, `cancelled`, `outcome_unknown`,
  and credit-admission `blocked`. Awaiting review is generated, not accepted.
- `operation_completed` records persisted job terminal states, including dispatch
  failure and restart recovery, with `operation_id=attempt_id=job UUID`, owning
  `run_id`, optional `stage_attempt_id`, operation/stage, status/outcome/phase and
  queue/run durations. Pipeline operation completion can mean dispatch completed;
  use stage terminal events for generated output. An explicit retry is a new job.
- Stage/page/job intents retry from the existing local SQLite journal into the
  product-event outbox with stable UUIDs. Vendor retries never retry generation.
  Environment/release are fixed at capture, not changed by delayed delivery.
  Local journal I/O failure is logged and cannot guarantee analytics recovery.
- `page_ready` means generated artwork, with page number/render revision and
  operation/stage correlation. `page_viewed` requires a deliberate review open
  and successful main artwork load. Restored/deep-linked/automatic views are
  excluded. Repeated loads within the same review emit once. It is not acceptance.
- `output_accepted` means a successful existing Draw approval, `scope=edition`.
  It does not assert visual quality or per-page acceptance. Repeated approval of
  the same attempt uses the same event UUID.
- `account_observed` replaces app-load `account_created`: current observation
  time; original auth signup date remains only person metadata. True
  `account_created` requires the new auth insert trigger migration, without
  historical backfill. The production-target migration uses creation time and
  content-free metadata; outbox failure preserves signup; a service-role-only bounded reconciler recovers post-migration gaps. Verify prerequisites
  and existing named objects before any approved production application. A partial
  unique index rejects existing duplicate signup rows and prevents the prior app
  writer from duplicating new signups during a migration-before-deploy gap.
- Bounded first-touch tokens persist locally for 24 hours across reload/new tabs;
  PostHog identifiers now persist in first-party localStorage and merge pre-login
  visits on sign-in. Storage denial uses memory with `reuseAnonymousId` enabled.
  Static control labels and trusted app styling are replayable; creative content,
  inputs, media, network bodies, and credentials remain protected.
  OAuth callback carries only bounded tokens and an advisory flow-start time.
  Delayed returns up to 24 hours fill attribution only if the account was created
  during that flow; existing acquisition metadata is never overwritten.
- `checkout_started` adds Stripe session `stripe_mode=test|live|unknown`; missing
  mode stays unknown. Purchase settlement/credit semantics are unchanged.
- Stage costs distinguish provider-reported, pricing-estimated, and unknown
  usage. Missing usage does not become measured zero; reserved estimates remain
  separate from known spend and charged credits.

Run `npm run check:push`, `npm run check:release` with an explicitly disposable
loopback database, and `novel_to_comic/.venv/bin/python
scripts/verify_tracking_continuity.py` (installed Chromium only, intercepted
external traffic, own fixture server stopped afterward). Tests are not live
proof of signup, purchases, acceptance, or provider image quality.

### Signup capture production cutover

The new signup migration was applied and verified on production Supabase
`dfzwfinycjaaxbqayceh` at **2026-10-01T00:02:36.520134Z**.
Fail-open trigger behavior was verified with a rolled-back temporary fixture;
reconciliation is service-role-only. Application deployment is tracked by
the exact main commit's CI run. No historical signup backfill or purchase
migration reapplication was performed.
