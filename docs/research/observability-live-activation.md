# Observability live activation research

> Verified against first-party documentation on 2026-07-20. This note is an
> operator companion to `ops/README.md` and
> `docs/proposals/observability-stack.md`; it does not record any live changes.

## Recommended activation order

1. Apply and verify the Supabase schema.
2. Provision two Sentry projects and collect their DSNs.
3. Deploy once with the backend DSN as a Fly secret and the frontend DSN as a
   Docker build argument. This deploy also activates Fly's custom-metrics
   scrape because `fly.toml` already contains `[[metrics]]` for port `8000` and
   path `/metrics`.
4. Verify Sentry events and Fly metrics with a test account.
5. Import `ops/grafana/canary-application.json` into Fly's managed Grafana.
6. Complete one Stripe test purchase and one paid model call, then inspect the
   four `ops_*` views.

## 1. Supabase

### Apply the schema

For this repository's current one-file schema workflow, use either:

- **Dashboard:** Supabase project -> **SQL Editor**, paste the complete contents
  of `docs/supabase-schema.sql`, review the selected production project, and
  run it once.
- **Direct Postgres:** from the repository root, run
  `psql "<production session/direct database URL>" -v ON_ERROR_STOP=1 -f docs/supabase-schema.sql`.
  Keep the connection URL in the shell or password manager, never in the repo.

Supabase documents the SQL Editor for running SQL and recommends versioned
migrations for an established deployment workflow. If Canary is moved to the
Supabase CLI workflow, first reconcile any dashboard-only remote changes, put
the observability SQL in `supabase/migrations/<timestamp>_observability.sql`,
run `supabase db push --dry-run`, and then `supabase db push`; the repository
does not currently contain that migration layout. Sources:
[database overview](https://supabase.com/docs/guides/database/overview),
[database migrations](https://supabase.com/docs/guides/local-development/database-migrations),
[`supabase db push`](https://supabase.com/docs/reference/cli/v1/supabase-db-push).

### Verify security and objects

Run this in SQL Editor after the schema succeeds:

```sql
select to_regclass('public.product_events') as product_events;

select column_name
from information_schema.columns
where table_schema = 'public'
  and table_name = 'credit_ledger'
  and column_name in (
    'stripe_checkout_session_id',
    'credit_package_id',
    'gross_amount_cents',
    'currency'
  )
order by column_name;

select c.relname, c.relrowsecurity, c.reloptions
from pg_class c
join pg_namespace n on n.oid = c.relnamespace
where n.nspname = 'public'
  and c.relname in (
    'product_events',
    'ops_ai_cost_daily',
    'ops_usage_reconciliation',
    'ops_unit_economics_daily',
    'ops_product_funnel_daily'
  )
order by c.relname;

select
  has_table_privilege('anon', 'public.product_events', 'select')
    as anon_can_read_events,
  has_table_privilege('authenticated', 'public.product_events', 'select')
    as authenticated_can_read_events,
  has_table_privilege('service_role', 'public.product_events', 'insert')
    as service_can_insert_events;
```

Expected results: all four purchase columns exist; `product_events` has
`relrowsecurity = true`; each `ops_*` view has `security_invoker=true` in
`reloptions`; the first two privilege checks are false and the service insert
check is true. Supabase warns that raw-SQL tables need explicit RLS and that
views are security-definer by default; on Postgres 15+, `security_invoker=true`
makes a view obey the caller's permissions/RLS. The canonical schema also
revokes `anon` and `authenticated` access to these operator objects. The
backend's service/secret key can bypass RLS and therefore must remain
server-only. Sources: [RLS and view security](https://supabase.com/docs/guides/database/postgres/row-level-security),
[API keys](https://supabase.com/docs/guides/getting-started/api-keys).

## 2. Sentry

### Provision the organization and projects

Fly currently documents a one-year sponsored Sentry Team plan per Fly
organization. From this repo, with the correct Fly organization/app selected:

```bash
fly ext sentry create
fly ext sentry dashboard
```

The create command makes a Sentry account and organization, creates a project,
and sets that project's `SENTRY_DSN` as a Fly app secret. Current documented
monthly promotional allowances are 50,000 errors, 100,000 performance units,
500 session replays, and 1 GB of attachments. Upgrading to a paid plan prevents
returning to the sponsored plan; after one year, allowing it to expire
downgrades the organization to Developer and the DSN continues to work.
Source: [Fly's Sentry integration](https://fly.io/docs/monitoring/sentry/).

Canary is designed for **two projects**:

- backend/FastAPI: use the DSN installed as `SENTRY_DSN` by Fly;
- frontend/React: in the same Sentry organization create a second React
  project, then copy its public DSN into the deploy command as
  `VITE_SENTRY_DSN`.

Project DSNs are project-bound client keys. Sentry's official API documents
both project creation and listing a project's client keys:
[create project](https://docs.sentry.io/api/projects/create-a-project-for-an-organization/),
[list client keys/DSNs](https://docs.sentry.io/api/projects/list-a-projects-client-keys/).

The SDK dependencies and initialization already exist in Canary. Sentry's
FastAPI integration is automatically enabled when FastAPI is installed and the
Python SDK is initialized. For React/Vite, Sentry requires initialization
before rendering; Canary calls `initSentry()` before `createRoot`. Sources:
[Python/FastAPI setup](https://docs.sentry.io/platforms/python/integrations/fastapi/),
[React setup](https://docs.sentry.io/platforms/javascript/guides/react/).

### Configure and deploy

Keep the initial settings conservative:

```bash
fly secrets set -a canary-web \
  SENTRY_DSN='<backend DSN>' \
  SENTRY_TRACES_SAMPLE_RATE='0.05' \
  CANARY_VERSION='<git commit SHA or release name>'

fly deploy -a canary-web \
  --build-arg VITE_SUPABASE_URL='https://<project>.supabase.co' \
  --build-arg VITE_SUPABASE_PUBLISHABLE_KEY='<publishable key>' \
  --build-arg VITE_CANARY_ENV='production' \
  --build-arg VITE_SENTRY_DSN='<frontend public DSN>' \
  --build-arg VITE_SENTRY_TRACES_SAMPLE_RATE='0.05' \
  --build-arg VITE_SENTRY_REPLAYS_ON_ERROR_SAMPLE_RATE='0'
```

The backend maps `CANARY_ENV` and `CANARY_VERSION` to Sentry environment and
release. The frontend maps `VITE_CANARY_ENV` and `VITE_CANARY_VERSION`, but see
the release blocker below. Sentry recommends setting releases explicitly so
they stay synchronized with deploys, and uses environments to separate
production from staging. Sources: [Python SDK options](https://docs.sentry.io/platforms/python/configuration/options/),
[React SDK options](https://docs.sentry.io/platforms/javascript/guides/react/configuration/options/).

Canary explicitly keeps `send_default_pii`/`sendDefaultPii` false, scrubs
authentication headers, and only sends opaque user IDs. Keep replay at zero
until a controlled error test confirms text is masked and media blocked.
Sentry documents that FastAPI request metadata may be attached but PII is not
included unless explicitly enabled; React's `sendDefaultPii` also defaults to
false. Sources: [FastAPI event behavior](https://docs.sentry.io/platforms/python/integrations/fastapi/),
[React options](https://docs.sentry.io/platforms/javascript/guides/react/configuration/options/).

### Verify

Use a non-customer test account. Trigger one controlled backend exception and
one controlled frontend exception, then confirm each arrives in the correct
project with environment `production`, an opaque user ID, and no token, email,
novel text, prompt, input value, or media payload. Remove any temporary error
trigger immediately. Do not verify by throwing an error only from browser dev
tools: Sentry notes those errors are sandboxed and may not be captured.

## 3. Fly Prometheus and Grafana

The current `fly.toml` is already configured correctly:

```toml
[[metrics]]
  port = 8000
  path = '/metrics'
```

Fly scrapes a configured custom endpoint every 15 seconds, requires the
endpoint to listen on `0.0.0.0`, and adds standard `app`, `region`, `host`, and
`instance` labels. Its managed Prometheus/Grafana currently has no additional
charge, approximately 15 days of retention, a 16 MB endpoint-response limit,
and may drop very high-cardinality metrics. Canary's endpoint is aggregate and
bounded accordingly. Source: [Metrics on Fly.io](https://fly.io/docs/monitoring/metrics/).

After the deploy:

1. Open the Fly dashboard's **Metrics** tab for `canary-web` for built-in
   metrics, or sign in to [Fly managed Grafana](https://fly-metrics.net).
2. In Grafana **Explore**, select the preconfigured Prometheus data source and
   query `canary_http_requests_total{app="canary-web"}`. If it is empty, send a
   normal request to the app, wait at least one 15-second scrape interval, and
   retry. Check the running app's logs and `/metrics` output if it remains empty.
3. Use **Dashboards -> New -> Import**, upload
   `ops/grafana/canary-application.json`, and select Fly's preconfigured
   Prometheus data source when prompted.
4. Run a test pipeline stage and confirm request rate, latency, job/queue,
   stage, AI-call, provider-cost, and debit-failure panels populate. Use Fly's
   built-in dashboards for Machine CPU, memory, filesystem/volume, exits, and
   edge HTTP metrics.

Fly explicitly supports creating/importing dashboards in managed Grafana, but
does **not** include built-in metric alerting. Keep initial alerts in Sentry; an
external/self-hosted Grafana or Prometheus/Alertmanager is required for metric
alerts. Source: [Fly dashboards and alerting](https://fly.io/docs/monitoring/metrics/).

## 4. End-to-end business verification

With Stripe still in test mode:

1. Create a project and move it through at least one stage.
2. Complete one test Checkout purchase.
3. Run one paid model operation and allow its credit debit to settle.
4. In Supabase SQL Editor, inspect:

```sql
select * from public.ops_product_funnel_daily order by day desc limit 25;
select * from public.ops_ai_cost_daily order by day desc limit 25;
select * from public.ops_unit_economics_daily order by day desc limit 25;
select * from public.ops_usage_reconciliation order by occurred_at desc limit 25;
```

The first three should contain the test activity. Reconciliation should be
empty for a correctly settled paid call. Prometheus spend is only a recent
rate signal and resets with process replacement; these Supabase records and
views are the durable source of truth.

## Known blockers and caveats

- **Frontend release names are not currently injectable into the production
  image.** `web/src/sentry.ts` reads `VITE_CANARY_VERSION`, but the Dockerfile
  neither declares nor exports that build argument. Frontend events will still
  be captured, but release grouping will be unset until that build plumbing is
  added. This research task intentionally did not change application code.
- **The Fly extension provisions one project/DSN.** The separate frontend
  project recommended by Canary must be created in Sentry and passed at build
  time.
- **The schema is not represented as Supabase migration files.** Apply the
  canonical SQL file for this activation, then adopt a migration directory
  before later incremental production schema changes.
- **Managed Fly Grafana has no alerting and only short retention.** Do not use
  it for financial reconciliation or historical product analytics.
- **Do not enable replay merely because the promotion has replay quota.** First
  inspect a masked test recording and update customer privacy disclosure.
