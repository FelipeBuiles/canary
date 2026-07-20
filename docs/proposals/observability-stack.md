# Canary observability stack

> **Status: Current implementation; operational activation pending.** Vendor
> facts were verified against first-party pricing and documentation on
> **2026-07-20**. Prices, quotas, retention, and beta terms are not implementation
> contracts; re-check them before enabling a paid plan. Supabase schema changes,
> Fly deployment, Grafana import, and Sentry account setup still require operator
> action.

## Goals

- Understand what customers do in the product and where they get stuck.
- Attribute AI/provider cost and customer credit charges accurately.
- Detect application errors, regressions, and infrastructure saturation.
- Start with useful free allowances and avoid creating a large operations stack.

## Proposed architecture and rollout

### Recommendation

Launch with four deliberately separate responsibilities:

1. **Fly Prometheus + Grafana** for Machine health and low-cardinality,
   short-lived operational metrics.
2. **Sentry** for backend/frontend exceptions, releases, a small trace sample,
   and error-triggered replay.
3. **Supabase** as the durable source of truth for provider cost, credit
   charges, purchases, and server-confirmed customer milestones.
4. **PostHog only when funnels become an active product question**, using an
   explicit event allowlist rather than autocapture. Do not turn on general
   session recording at launch.

Do not self-host Prometheus, Grafana, or Langfuse on Fly for the initial
release. That would add stateful services and operator burden while the
managed/free products cover the immediate need. Langfuse Cloud can be enabled
later for generation diagnosis, but it is not needed to establish cost truth.

```text
Browser                         FastAPI / workers                 Providers
  |                                   |                              |
  +-- frontend errors --------------> Sentry <--- backend errors ----+
  |                                   |
  +-- explicit UX events (optional) -> PostHog
  |                                   |
  +-- customer actions -------------> server-confirmed milestones
                                      |
                                      +--> Supabase
                                      |    - ai_usage_events
                                      |    - credit_ledger
                                      |    - product_events (new)
                                      |    - operator SQL views (new)
                                      |
                                      +--> /metrics (aggregate only)
                                             |
                                             +--> Fly Prometheus/Grafana
```

The systems should correlate on opaque IDs (`user_id`, `project_id`, `job_id`,
`request_id`) where appropriate, but those IDs must not become Prometheus
labels. Prompts, novel text, generated images, emails, auth tokens, and project
names must not be sent as analytics properties.

### What Canary already has

The expensive-call foundation is already implemented:

- `ai_usage_events` records each model call's user, project, stage, feature,
  operation, status, billability, provider/model, token or image count,
  latency, estimated cost, actual/provider cost, pricing source, and error.
- `credit_ledger` records reservations, releases, settled model usage, customer
  credit debits, and Stripe-funded credit additions. `usage_call_id` and
  `job_id` support reconciliation and idempotency.
- `server/credits.py` is the single provider-USD to customer-credit conversion
  boundary. Observability must report that calculation, not reimplement it.
- Backend and frontend Sentry initialization already exist and no-op without a
  DSN. Sensitive authentication headers are scrubbed and PII is disabled.
- OpenTelemetry export and a direct Langfuse ingestion path already exist but
  are disabled by configuration.
- Fly already receives process logs, HTTP/Machine metrics, and health checks.
- `/api/deployment/activity` already exposes aggregate queue and in-flight work
  behind the operator token.

The missing pieces are durable product milestones, purchase amounts for margin
reporting, aggregate application metrics, dashboards, and alerts.

### Data model additions

#### 1. Server-confirmed product events

Add a small append-only `product_events` table in Supabase:

| Column | Purpose |
|---|---|
| `id`, `occurred_at` | Event identity and server timestamp |
| `event_name` | Versioned allowlisted name |
| `user_id`, `project_id` | Pseudonymous customer/project correlation |
| `job_id`, `request_id` | Optional operational correlation |
| `source` | `server` or `web` |
| `properties_json` | Size-capped, allowlisted scalar properties only |

Server code should emit authoritative milestones on a best-effort basis:

- `project_created`, with `source=upload|sample`
- `stage_started`, `stage_succeeded`, `stage_failed`, and `stage_approved`
- `style_selected`
- `panel_flagged`, `panel_regenerated`
- `checkout_started`, `credits_purchased`
- `export_succeeded`, with format but no filename

Derived events such as “first project,” “first panel,” or “activated customer”
should be SQL queries, not duplicate emitted events. Client-only events should
be limited initially to `station_viewed`, `inspect_drawer_opened`, and
`checkout_cancelled`, because the server cannot infer them.

The event write must never fail a customer action. Use a strict event/property
allowlist, an 8 KiB payload cap, server timestamps, authenticated ingestion,
and no direct anonymous insert policy. Do not enable autocapture: it creates
unstable event names and risks collecting prose or project identifiers from
the DOM and URL.

#### 2. Purchase economics

`credit_ledger` currently persists the Stripe payment-intent ID and credits but
not the package or dollar amount. Add these nullable fields to purchase rows:

- `stripe_checkout_session_id`
- `credit_package_id`
- `gross_amount_cents`
- `currency`

Populate them from the signed paid Checkout webhook. This is sufficient for
gross revenue and provider-cost margin reporting. Stripe processing fees can
be reconciled monthly in Stripe at first; only add a balance-transaction sync
when net-of-fee margin needs to be visible daily.

#### 3. Operator views

Create operator-only SQL views rather than querying JSON from dashboards:

- `ops_ai_cost_daily`: actual and estimated USD by day, stage, feature,
  provider, model, operation, status, and billability.
- `ops_usage_reconciliation`: AI events with no matching settled ledger row,
  settled rows with no AI event, charged failed calls, and cost/credit totals
  per job.
- `ops_unit_economics_daily`: gross purchase cents, provider spend, credits
  granted/used, and pre-processing-fee margin.
- `ops_product_funnel_daily`: unique users/projects reaching each durable
  milestone.

Ledger and usage records should be retained as financial audit data. Product
event retention can start at 13 months and be revisited once volume is known.

### Aggregate application metrics

Expose a private Prometheus-format endpoint and add a `[[metrics]]` stanza to
`fly.toml`. Start with these low-cardinality signals:

| Metric | Type | Labels |
|---|---|---|
| `canary_http_requests_total` | counter | method, route template, status class |
| `canary_http_request_duration_seconds` | histogram | method, route template |
| `canary_generation_jobs` | gauge | status |
| `canary_generation_queue_items` | gauge | none |
| `canary_stage_runs_total` | counter | stage, outcome |
| `canary_stage_duration_seconds` | histogram | stage, outcome |
| `canary_ai_calls_total` | counter | provider, model alias, operation, status |
| `canary_ai_provider_cost_usd_total` | counter | provider, model alias, stage |
| `canary_credit_debit_failures_total` | counter | stage |

Never label metrics with customer, project, job, request, scene, panel, error
message, or raw URL values. Prometheus cost counters are for recent spend rate
and anomaly detection only; counters reset on process replacement and Fly
retains about 15 days. Supabase remains authoritative.

### Dashboards and operating questions

#### Fly operations dashboard

- Machine CPU, memory, disk/volume utilization, restarts, and file descriptors
- request rate, 4xx/5xx rate, and p50/p95 route latency
- queued/running generation jobs and queue depth
- stage run success/failure and duration
- recent AI request rate, failure rate, and provider-cost rate

#### Founder/unit-economics dashboard

- daily/weekly active creators and new projects
- project -> Story -> Look -> Panels -> Book funnel
- median time to first completed extract, first drawn panel, and export
- panel flag and regeneration rate by model/quality preset
- provider spend by customer/project/stage/model/feature
- estimate-versus-actual drift, with p50/p95 and worst outliers
- credits charged versus provider cost
- gross credit purchases and pre-fee gross margin
- paid/failed provider calls that were not debited to the customer

Start the durable dashboard as reviewed SQL queries or a very small operator
page backed by the `ops_*` views. Fly's Grafana should not receive customer IDs
or be treated as the historical business-intelligence store. PostHog can render
the product funnel once its use is justified; it should not calculate billing
or margin.

#### Sentry dashboard

- new/regressed backend and frontend errors by release
- affected users, using only opaque user IDs
- failed and slow generation requests by stage/provider/model tags
- a small sample of end-to-end API traces
- error-triggered frontend replays after text/input masking is verified

Use separate frontend and backend Sentry projects. Keep normal-session replay
at zero initially and set error replay to a quota-aware sample. Start tracing
at 5% for ordinary requests and 100% for errors only if the SDK behavior and
quota usage are verified. Filter polling, static assets, health checks, and
expected 4xx responses.

### Alerts

Sentry should own the initial actionable alerts because Fly's managed Grafana
does not include alerting:

- new error or regression in production
- backend 5xx affecting a customer action
- `Credit debit failed` (provider charged, customer not debited)
- Stripe paid webhook handling failure
- generation/provider timeout or refusal spike

Use Fly dashboards for manual infrastructure checks during the pilot. Before
unattended growth, add an external alert path for sustained memory >85%, volume
>80%, repeated Machine exits, health-check failure, queue depth, and a sharp
provider-spend-rate increase. A daily reconciliation job should alert when
`ops_usage_reconciliation` is non-empty; this is more reliable than trying to
infer margin leakage from logs.

### Privacy and security rules

- Treat product analytics as personal data even when IDs are pseudonymous.
- Update the privacy disclosure before enabling customer analytics or replay.
- Do not send emails, IP addresses, novel text, prompts, generated assets,
  project names, auth headers, or Stripe secrets.
- Mask all form text in replay and block media by default; verify with a test
  account before production.
- Keep Sentry `send_default_pii` / `sendDefaultPii` false.
- Restrict operator views to a dedicated read-only database role or server-side
  operator endpoint; never expose cross-customer views through the normal API.
- Add a kill switch for product analytics and replay independent of error
  capture.

The current Langfuse integration sends generation input and output payloads.
Do not point it at Langfuse Cloud until that data path has an explicit content
policy, redaction controls, and customer disclosure. Cost and latency fields in
`ai_usage_events` are sufficient for the initial operating dashboard without
exporting creative content.

### Rollout

#### Slice 0 — enable what exists (half day, no schema change)

1. Claim the Fly Sentry promotion if its displayed terms are acceptable;
   otherwise use Sentry Developer.
2. Create separate frontend/backend Sentry projects, set DSNs and release
   identifiers, send scrubbed test errors, and create the critical email
   alerts.
3. Open the existing Fly Grafana dashboards and save a launch operations
   dashboard for CPU, memory, volume, exits, HTTP failures, and latency.
4. Record a baseline from the current `ai_usage_events` and `credit_ledger`.

#### Slice 1 — make money flows queryable (one day)

1. Persist Stripe package/amount/currency on paid purchase rows.
2. Add the cost, reconciliation, and unit-economics SQL views.
3. Add tests for paid webhook idempotency and AI-event/ledger reconciliation.
4. Verify totals against one Stripe test purchase and one real provider call.

#### Slice 2 — durable customer journey (one to two days)

1. Add `product_events`, the strict event API/helper, and RLS/permissions.
2. Instrument server-confirmed lifecycle milestones.
3. Add the three explicit client events only if they answer a current question.
4. Build the first funnel query and verify a complete sample-project journey.

#### Slice 3 — live application metrics (one day)

1. Add the Prometheus endpoint and bounded metric registry.
2. Instrument request, queue, stage, AI call, provider-cost, and debit-failure
   signals.
3. Add `[[metrics]]` to `fly.toml` and import the application dashboard.
4. Load-test cardinality and confirm that no customer identifiers appear.

#### Slice 4 — optional analytics tools

- Enable PostHog only when cohort/funnel iteration is frequent enough to
  justify another processor and privacy disclosure.
- Enable Langfuse Cloud only when prompt/model diagnosis needs outweigh content
  sensitivity and its payloads have been redacted.
- Move from Fly's Grafana to an external Grafana/alerting setup only when
  infrastructure alerts or more than 15 days of metrics justify it.

### Launch definition of done

- One dashboard answers “what did customers complete this week?”
- One dashboard answers “where did provider money go, and what was charged?”
- A provider-charged/customer-not-debited call is detectable within one day.
- A production frontend or backend error reaches the operator by email.
- The operator can see memory, disk, restarts, 5xx rate, queue depth, and recent
  provider-spend rate without SSH access.
- A complete test journey correlates project, stage, job, AI usage, debit, and
  purchase records without storing creative content in telemetry.

## Vendor facts (verified 2026-07-20)

### Fly.io managed Prometheus and Grafana

Fly already supplies a useful infrastructure-metrics base at no additional
charge:

- Fly runs a managed, Prometheus-compatible time-series service backed by
  VictoriaMetrics and a managed Grafana instance at `fly-metrics.net`. The
  Grafana data source and Fly infrastructure dashboards are preconfigured, and
  custom dashboards can be created or imported. There is currently **no
  additional charge** for either service. [Fly metrics documentation](https://fly.io/docs/monitoring/metrics/)
- Built-in metrics include edge/app HTTP request counts and latency, concurrent
  requests, CPU/load, memory, network, filesystem, file descriptors, Machine
  exits, and volume metrics. [Fly built-in metrics](https://fly.io/docs/monitoring/metrics/#built-in-metrics)
- An application can expose Prometheus-format custom metrics by adding one or
  more `[[metrics]]` sections to `fly.toml`; Fly scrapes each endpoint every
  **15 seconds**. [Fly custom metrics](https://fly.io/docs/monitoring/metrics/#custom-metrics)
- Metrics retention is approximately **15 days**. Fly describes the service as
  operational monitoring rather than long-term analytics. The metrics endpoint
  response is capped at **16 MB**, and Fly may drop very high-cardinality custom
  metrics. [Fly retention, cost, and limits](https://fly.io/docs/monitoring/metrics/#retention-cost-and-limits)
- Fly does **not** provide built-in metrics alerting. Alerts require an external
  or self-hosted Grafana connected to Fly's Prometheus endpoint, or a separate
  Prometheus/Alertmanager stack. [Fly alerting documentation](https://fly.io/docs/monitoring/metrics/#alerting)

This makes Fly Grafana a strong zero-extra-cost home for aggregated operational
signals (request rate, failure rate, latency, active jobs, queue depth, and cost
totals by stage/provider/model). It is a poor source of truth for customer-level
or financial records: a `user_id`, `project_id`, trace ID, or request ID in
Prometheus labels would create the high cardinality Fly warns it may drop, and
15-day retention is too short for cohort or margin analysis.

#### Fly logs

- Fly's searchable application logs are exposed through Grafana, backed by
  VictoriaLogs, retained for **7 days**, and free while the feature remains in
  beta. [Fly log-search documentation](https://fly.io/docs/monitoring/search-logs/)
- Fly also supports live log tailing, programmatic access, and exporting logs to
  another service. [Fly logging overview](https://fly.io/docs/monitoring/logging-overview/)

Seven-day searchable logs are sufficient for first-response debugging, but not
for durable customer-history or billing audits. Logs should carry correlation
IDs and low-sensitivity operational context, not become the cost ledger.

### Sentry Developer (free)

Sentry's current free Developer plan is useful for code health and a small
amount of tracing/replay, but it is not a customer-behavior or cost-accounting
system.

| Capability | Free Developer allowance |
|---|---:|
| Seats | 1 user |
| Projects | Unlimited |
| Errors | 5,000/month |
| Logs | 5 GB/month |
| Application metrics | 5 GB/month |
| Tracing | 5 million spans/month |
| Session replay | 50 replays/month |
| Uptime monitoring | 1 monitor |
| Cron monitoring | 1 monitor |
| Metric monitors | 20 |
| Attachments | 1 GB |
| Custom dashboards | 10 |
| Data lookback | 30 days |

These quotas and plan features are from Sentry's live
[plan comparison](https://sentry.io/pricing/). The free plan includes Error
Monitoring and Tracing plus email alerts/notifications, is limited to one user,
and caps usage at the free-tier limits rather than billing overages.

Practical use for Canary:

- Use separate backend and frontend projects under the same free organization;
  unlimited projects are included.
- Capture backend exceptions, frontend crashes, releases, and a deliberately
  sampled set of traces. Five million spans is generous, but indiscriminate
  trace sampling can still obscure the important paths and increase client
  overhead.
- Spend the 50 monthly replays on error sessions or a small sample, not every
  visit. Treat replay as a debugging aid rather than product analytics.
- Point the single uptime monitor at a public liveness endpoint. A cron monitor
  only becomes useful when Canary has a real scheduled job to check.
- The one-seat limit means this is founder/operator tooling. Team access or
  third-party alert integrations requires a paid tier; Developer lists email
  alerts, while Team adds third-party integrations.
- Expect events over quota to be dropped. Sentry's usage view distinguishes
  accepted, filtered, rate-limited, and quota-dropped events, so configure SDK
  filtering and sampling before launch. [Sentry usage statistics documentation](https://docs.sentry.io/product/stats/)

#### Fly's Sentry promotion

Fly currently says each Fly organization can claim **one year of Sentry Team
Plan credits** through `fly ext sentry create`. Fly's extension documentation
advertises monthly allowances of 50,000 errors, 100,000 performance units, 500
session replays, and 1 GB of attachments; after the promotional year the
organization can fall back to Developer without an SDK migration. It also warns
that voluntarily upgrading to a paid plan prevents returning to the sponsored
plan. [Fly Sentry extension documentation](https://fly.io/docs/monitoring/sentry/)

The promotion page's “performance units” terminology and 500-replay allowance
do not match Sentry's current public Team-plan table (which lists spans and 50
replays). Treat the Fly page as evidence that the promotion exists, then verify
the actual quotas shown in **Sentry Settings → Usage & Billing** immediately
after claiming it. Do not design a permanent retention or sampling policy
around promotional quotas.

### Langfuse Cloud Hobby

Langfuse is the most directly relevant low-cost addition for AI-call
observability. Its free Hobby plan includes LLM tracing, session/user tracking,
token and cost tracking, LiteLLM proxy logging, custom dashboards, and two
monitors. The allowance is **50,000 units/month**, **30 days** of data access,
**two users**, and an ingestion limit of **1,000 requests/minute**; no credit
card is required. [Langfuse pricing and feature comparison](https://langfuse.com/pricing)

This is a good visualization and diagnosis layer for prompt/model latency,
token usage, and provider-reported cost. It should not replace Canary's own
usage ledger: vendor prices and usage reporting can lag or disagree, and the
free plan exposes only 30 days of history. The next hosted tier is currently
Core at **$29/month**, with 100,000 included units, 90-day access, unlimited
users, and additional usage starting at $8/100,000 units.

### PostHog Free (optional product analytics)

If the goal expands from operational observability to funnels, feature usage,
and customer journeys, PostHog is a clearer fit than forcing those events into
Sentry or Prometheus:

- Product analytics includes the first **1 million events/month free** and
  session replay includes the first **5,000 recordings/month free**.
  [PostHog usage pricing](https://posthog.com/pricing)
- The free plan is capped at the free allowances, requires no credit card, and
  includes one project, unlimited tracked users, unlimited team members, API
  access, and **one-year retention**. [PostHog plan comparison](https://posthog.com/pricing#compare)

PostHog is optional rather than launch-critical. Add it only when there are
specific product questions to answer, define a small event taxonomy first, and
configure consent/redaction before enabling replay. The durable source of truth
for charged credits and provider cost should remain Canary's database even if
PostHog displays aggregate product and revenue-adjacent trends.

## Vendor-role boundary

| Question | Best-fit system |
|---|---|
| Is the Fly Machine saturated or returning 5xx responses? | Fly Prometheus + managed Grafana |
| What happened in the last few days around a deployment or request? | Fly searchable logs |
| Which code error affected a customer, and what trace/replay explains it? | Sentry |
| Which LLM call, prompt, or model was slow or expensive? | Langfuse, reconciled to Canary's usage ledger |
| Which customer was charged, for what, and did provider cost settle? | Canary/Supabase ledger (authoritative) |
| Which station/funnel step do customers abandon? | PostHog if/when product analytics is enabled |
