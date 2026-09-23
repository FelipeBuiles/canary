# Canary — Fly.io Deploy Runbook

**Status: Current repository runbook, September 9, 2026.** Verify current
provider/dashboard details before executing. This refresh did not inspect or
change production state. Use [launch readiness](proposals/launch-readiness.md)
for launch acceptance and [the platform decision](proposals/deployment-platform-review.md)
for architecture rationale.

The July 4–5 deployment sessions explain the one-app design and historical
failure examples below; they do not establish current account state, pricing,
volume capacity, or a completed production migration.

**Reliability upgrade requirement:** apply reviewed canonical SQL before the
new application starts, preserve `/projects`, and drain before normal releases.
Previously recorded SQL verification was isolated; attach production results
to a release evidence record before calling the upgrade deployed.

## Architecture (one machine, two processes)

```text
  Fly.io
  ┌──────────────────────────────────────────────────────────────┐
  │  canary-web   (public, TLS auto)                             │
  │                                                              │
  │  ┌────────────────────────────────────────────────────────┐  │
  │  │ uvicorn --proxy-headers (1 worker)        :8000 (pub)  │  │
  │  │ mounts: /projects  ← persistent volume                 │  │
  │  └───────────────────────┬────────────────────────────────┘  │
  │                          │ http://127.0.0.1:4000 (loopback)   │
  │                          ▼                                    │
  │  ┌────────────────────────────────────────────────────────┐  │
  │  │ LiteLLM proxy  — holds ALL provider API keys  :4000    │  │
  │  │ (bound to 127.0.0.1, never exposed publicly)           │  │
  │  └────────────────────────────────────────────────────────┘  │
  └──────────────────────────────────────────────────────────────┘
              │                │                │
         Supabase          Stripe         Sentry / OTel
         (managed)        (live keys)      (SaaS)
```

**One Fly app, one container, two processes.** The merged `Dockerfile` installs
both the web app (its own venv) and the LiteLLM proxy (an isolated venv at
`/app/.venv-litellm`, to keep their dependency trees from contending). The
entrypoint (`litellm/entrypoint.sh`) starts the proxy in the background, waits
for `/health/liveliness`, then supervises both processes. If LiteLLM exits after
boot, the entrypoint restarts it with a bounded restart budget instead of
leaving a healthy-looking web app with a dead image gateway. Provider API keys
live in `canary-web`'s Fly secrets. Both child processes inherit the environment;
the proxy's loopback binding provides network isolation, not process-level
secret isolation.

Keep **one uvicorn application worker on one Fly Machine**. Generation queue
workers are concurrent tasks within that application, not additional app
processes. Admission locks and activity counts are process-local; drain intent is persisted.
These are still single-process coordination mechanisms;
horizontal scaling requires a distributed coordinator, not additional Machines
sharing assumptions about `/projects`. Preserve the mounted volume across
upgrades: it holds project artifacts, Draw `.pending`/`.unfinished` recovery
evidence, and `.request-journal.sqlite3` (durable action responses and job
observations). Losing journals can lose the evidence needed to avoid duplicate
paid actions; copying artwork alone is not a recovery backup.

## Prerequisites (before you touch Fly)

1. **A funded Fly account with the required compute/storage allowance.**
   Confirm current billing and trial limits in the dashboard before deploying.
   Budget from the actual 4 GB Machine, storage, transfer, and backup quote;
   July idle-compute estimates are not a current monthly cost promise.
2. **Fly CLI installed + authenticated**: `brew install flyctl && fly auth login`.
3. **A Supabase project** (prod). From its dashboard grab:
   - Project URL (`https://<project>.supabase.co`).
   - **anon / publishable** key (role:`anon` in the JWT) — used by the browser.
   - **service_role** key (role:`service`) — used by the backend only.
   - Database connection string (for schema bootstrap).
4. **A Stripe account** (test mode first, live at launch).
5. **Provider API keys** for whatever models you route through LiteLLM
   (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `OPENROUTER_API_KEY`,
   `FAL_KEY`). Only set the ones you actually use. These live as Fly
   secrets on `canary-web` now (they used to be on `litellm-gw`).

## Step 0 — prepare secret file (outside the repo)

Keep this **out of the working tree** (e.g. `~/.config/canary/`). A gitignored
file at repo root is a hint, not a guarantee — `git add -A` slips happen. The
password manager or `~/.config/` is safer. This file is only the input to
`fly secrets import`; Fly's encrypted secret store is the runtime source of
truth.

Generate the two random LiteLLM secrets (do not paste the output anywhere):

```bash
echo "LITELLM_MASTER_KEY=sk-litellm-$(openssl rand -hex 24)"
echo "LITELLM_SALT_KEY=$(openssl rand -hex 32)"
```

**`~/.config/canary/canary-web.env`** — one consolidated secret file. Note
`LITELLM_API_KEY` is the **same value** as `LITELLM_MASTER_KEY` (the web app
authenticates to the loopback proxy with the proxy's master key). Provider
keys that used to live on `litellm-gw` now live here too:

```env
# ─── LiteLLM proxy (loopback subprocess) ───────────────────────────────
LITELLM_MASTER_KEY=sk-litellm-<from above>
LITELLM_SALT_KEY=<from above>
LITELLM_API_KEY=<same value as LITELLM_MASTER_KEY>
CANARY_OPS_TOKEN=<random operator-only token, e.g. openssl rand -hex 32>
CANARY_BACKOFFICE_ORIGINS=http://localhost:5173  # only when a local desk connects to prod
OPENAI_API_KEY=sk-...
ANTHROPIC_API_KEY=sk-ant-...
FAL_KEY=...
OPENROUTER_API_KEY=sk-or-...      # only if you use OpenRouter

# ─── Web app ───────────────────────────────────────────────────────────
SUPABASE_URL=https://<project>.supabase.co
SUPABASE_SECRET_KEY=<service_role key — server only, NEVER in the browser>
STRIPE_SECRET_KEY=sk_test_...           # test mode while gating
STRIPE_WEBHOOK_SECRET=whsec_...         # from test-mode webhook endpoint
# SENTRY_DSN=<only if you have a real https://...@... DSN; omit to no-op>
# LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY / OTEL_EXPORTER_OTLP_ENDPOINT
#   if you wire Langfuse/OTel.
```

> **⚠️ Critical key distinction.** Supabase exposes two keys that both look like
> `eyJ...` JWTs. The **anon/publishable** key goes into the browser bundle via
> `VITE_SUPABASE_PUBLISHABLE_KEY`. The **service_role** key bypasses RLS and
> must **never** leave the server. If you accidentally bake service_role into
> the frontend, Supabase rejects login with *"Forbidden use of secret API key
> in browser"* — and the key is now compromised, so rotate it in the dashboard.

## Step 1 — Supabase schema + auth config

The canonical schema is required for startup, not merely for later queries.

Database changes are a separately reviewed production operation. CI never
receives a production Postgres connection string and never applies this file
automatically. Before running it, review the exact diff, confirm a current
backup, and record the operator and result in the release evidence.

```bash
# 1a. Apply the reviewed canonical schema manually
psql "<prod database url>" --set ON_ERROR_STOP=1 --single-transaction \
  --file docs/supabase-schema.sql
```

For upgrades as well as fresh installs, apply the reviewed current
`docs/supabase-schema.sql` **before starting the new application**. Its owned
reservation leases and idempotent usage-settlement RPCs are required: startup
calls lease renewal before admitting work and fails closed if that contract is
missing. Review compatibility with the running/rollback binary before applying;
for the first drain-capable upgrade, use the controlled cutover below.

For the per-call credit authorization cutover, drain active jobs before applying
[`docs/sql/2026-09-22-credit-call-authorization.sql`](sql/2026-09-22-credit-call-authorization.sql)
or the updated canonical schema. Apply it before starting the matching binary.
The new reservation RPC requires frozen billing terms; an older binary cannot
place new holds after this migration. Reconcile any started expired holds before
resuming paid jobs.

Reservations have a one-hour owner lease renewed every 30 seconds. Only expired
never-started holds can be reclaimed automatically. Started-expired holds,
legacy unowned holds, and ambiguous settlements need manual reconciliation
against provider usage, call IDs, jobs, and saved output. Do not mass-release
holds on startup, reset, or lease expiry, and do not assume an interrupted paid
request was free. A lost ledger response can replay the same idempotent database
settlement; it must not trigger another provider submission.

In the **Supabase dashboard → Authentication → URL Configuration**:

- Add the production domain(s) to **Site URL** and **Redirect URLs**.
- **Include `/reset-password`** in the redirect URLs — the password-reset flow
  (wired 2026-07-03) lands there. Missing it = reset emails 404.
- **Email delivery:** the default `noreply@mail.app.supabase.io` sender is
  rate-limited. Configure custom SMTP in the dashboard before a public launch
  or expect deliverability problems.

## Step 2 — Canary app (`canary-web`) — the only Fly app

```bash
# 2a. Register + seed secrets + deploy
fly launch --no-deploy        # uses fly.toml (app = "canary-web")
fly secrets import -a canary-web < ~/.config/canary/canary-web.env

# 2b. Deploy with build-time VITE_* args.
#     These are inlined into the JS bundle at BUILD time (the browser talks to
#     Supabase directly), so they CANNOT be runtime fly secrets.
fly deploy \
  --build-arg CANARY_VERSION="$(git rev-parse HEAD)" \
  --build-arg CANARY_BUILD_TIMESTAMP="$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  --build-arg VITE_SUPABASE_URL=https://<project>.supabase.co \
  --build-arg VITE_SUPABASE_PUBLISHABLE_KEY=<anon/publishable key, NOT service_role> \
  --build-arg VITE_CANARY_ENV=production
  # --build-arg VITE_SENTRY_DSN=<frontend DSN>   # optional
  # --build-arg VITE_SENTRY_TRACES_SAMPLE_RATE=0.05
  # --build-arg VITE_SENTRY_REPLAYS_ON_ERROR_SAMPLE_RATE=0

# 2c. Verify boot
fly logs -a canary-web
#   Look for, in order:
#     "[entrypoint] waiting for litellm proxy at 127.0.0.1:4000..."
#     "[entrypoint] litellm proxy ready (after Ns)"
#     "Uvicorn running on http://0.0.0.0:8000"
#   Then the machine must stay up past the 1m readiness grace period.
```

The app disables Fly Proxy autostop/autostart and uses `on-failure` with a
maximum of three retries. Deliberate SIGTERM stops exit successfully and remain
stopped; unexpected failures receive bounded recovery backed by persistent
`/projects/.ops/recovery.json`. Dependency failure retains the web diagnostic
API and does not trigger endless Machine restarts. Preserve durable drain intent
and explicitly reopen admission only after readiness checks.

See [crash recovery and actionable exceptions](ops/crash-recovery.md) for
configuration, crash-loop reset, independent external monitoring, maintenance,
and local fault injection. Activation must verify the actual Machine policy:
`fly.toml` is desired configuration, not evidence of the deployed state. Existing
Machines need the new policy applied through an explicitly authorized release.
Neither restart nor budget reset may replay interrupted paid work.

If the proxy fails readiness, inspect local dependency status and sanitized logs.
The entrypoint starts the web diagnostic API after its bounded startup wait;
readiness remains unavailable until dependencies recover.


### Readiness probe contract

Fly's service-level routing check points at the cheap, process-local
`GET /api/health`. Monitor `GET /api/health/ready` separately for dependency
health; it returns `error` if **either** dependency is unreachable:

- **Supabase** — runs `select id from projects limit 1`. Needs the schema from
  Step 1 and a valid `SUPABASE_SECRET_KEY`.
- **LiteLLM** — `GET <LITELLM_BASE_URL>/health/liveliness` with the bearer
  `LITELLM_API_KEY`. Hits the loopback proxy inside the same container.

In local development, a dependency is skipped when both of its settings are
absent. In `CANARY_ENV=production`, missing or partial dependency configuration
is an error and the endpoint returns HTTP 503. Keeping this deep check out of
the routing path prevents a transient provider outage from making the only
Machine unroutable.

`GET /api/version` is the public release-identity contract. After every deploy,
verify that `git_sha` matches the exact green CI revision and record the
`build_timestamp`. The backend and frontend receive the same
`CANARY_VERSION`, which is also used for Sentry release grouping.

### Maintenance-window upgrades

1. Announce the maintenance window. Confirm every CI job is green for the exact
   release SHA and record the current Fly release/image as a rollback target.
2. On a drain-capable binary, run the authenticated guard below. It closes
   admission **before** waiting for idle. Do not deploy unless it succeeds.
3. Apply any separately reviewed canonical SQL changes from Step 1 before the
   new app starts; preserve the existing `/projects` volume and journals.
4. Deploy with the release build arguments shown above.
5. Verify `/api/version`, `/api/health`, and `/api/health/ready`, then complete a
   short signed-in smoke test. Drain intent survives restart: keep any external
   maintenance access restriction in place until verification is complete.
6. Explicitly resume admission as shown below after readiness and verification,
   then remove external maintenance restrictions. An aborted release remains
   drained until an operator decides it is safe to admit work again.

**First cutover from an old binary without `/api/ops/drain`:** the automatic
guard cannot establish its admission barrier. Schedule a controlled maintenance
cutover: enforce an external block on new user generation/mutation traffic while
the old process is still running, let admitted work finish, inspect activity and
unresolved provider/ledger outcomes, then stop the old process before applying
the reviewed schema and starting the new release on the preserved volume.
Keep maintenance restrictions until verification is complete. If work cannot
finish, explicitly reconcile the interruption; do not call it an idle cutover.
There is **no idle-only fallback** when drain is unavailable, unauthorized, or
fails. If intake cannot be reliably blocked, do not proceed with the cutover.

Copy `docs/ops/release-evidence-template.md` for each customer-facing release.

### CI-managed production deployment

Run the `CI` workflow manually against `main` to request a production release.
The manual dispatch is the operator's confirmation that the maintenance window
is active. The `Deploy production` job starts only after the backend, frontend,
and production-image jobs pass for the exact SHA; it then:

1. Authenticates `POST /api/ops/drain`, then waits for deployment status to show
   both `draining: true` and `safe_to_deploy: true`.
2. Rebuilds the exact tested source SHA with production frontend arguments and
   release metadata. This is not deployment of the CI smoke-test image digest.
3. Verifies `/api/version`, liveness, the production readiness contract, and
   required security-header presence. Signed-in behavior and policy values
   still need their release exercises.

The workflow deliberately has no production database credential and cannot
apply schema changes. If a release requires a database change, complete the
reviewed manual operation in Step 1 before dispatching the deployment.

**Release cancellation protection:** each manual dispatch has a unique
workflow concurrency group and disables automatic cancellation; ordinary
push/PR runs still cancel superseded CI on the same ref. The existing
`production-deploy` job group runs one deployment at a time and uses
`queue: max` so later dispatches do not replace an earlier pending deploy.
GitHub caps this queue at 100 pending jobs; additional requests are cancelled.
These semantics follow [GitHub's concurrency documentation](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax#concurrency).

This protects against superseding runs, not deliberate operator cancellation,
job timeouts, or runner failure. Those can leave the old process drained or a
new process already running: inspect actual release/activity state before
explicitly resuming or rolling back. Queued releases still require valid
maintenance and schema conditions when they reach deployment.

Configure a GitHub environment named `production`, limit it to the `main`
branch, and add these environment secrets:

- `FLY_API_TOKEN` — an app-scoped deploy token for `canary-web`.
- `CANARY_OPS_TOKEN` — the same value configured on the Fly app.
- `VITE_SUPABASE_URL` — the public production project URL.
- `VITE_SUPABASE_PUBLISHABLE_KEY` — the browser-safe publishable key.
- `VITE_SENTRY_DSN` — optional frontend Sentry DSN.

Do not store the Supabase service-role key as a `VITE_*` value. The deploy job
closes server admission but does not announce a customer maintenance window.
It cannot bootstrap drain on an old binary: complete the controlled first
cutover before using this workflow. If the repository plan supports required
environment reviewers, enabling one adds a useful second approval.

### Drain, wait for idle, and explicitly resume

All three endpoints require `X-Canary-Ops-Token: $CANARY_OPS_TOKEN`:
`POST /api/ops/drain`, `GET /api/ops/deployment-status`, and
`POST /api/ops/resume`. Drain closes new project mutation/paid-action admission;
recorded idempotent responses can still replay. Status counts in-progress HTTP
admissions, pipeline/style tasks, queued/running generation jobs, queue items,
and in-flight Draw work without revealing account/project details.
`safe_to_deploy` means all counts are zero; it is safe as a release gate only
when `draining` is also true on this single application process.

```bash
# Requires CANARY_OPS_TOKEN in the operator environment.
# SCENEWRIGHT_APP_URL selects the target (default: https://canary-web.fly.dev).
# The script has no drain/resume flags: it always POSTs drain, then polls.
SCENEWRIGHT_APP_URL=https://canary-web.fly.dev python scripts/check_deploy_safe.py

# Inspect a drain already established by the script:
curl -fsS https://canary-web.fly.dev/api/ops/deployment-status \
  -H "X-Canary-Ops-Token: $CANARY_OPS_TOKEN"

# Explicitly reopen an existing drained process after a cancelled/failed release:
curl -fsS -X POST https://canary-web.fly.dev/api/ops/resume \
  -H "X-Canary-Ops-Token: $CANARY_OPS_TOKEN"
```

The guard polls every five seconds for up to 30 minutes. Timeout exits nonzero
and **leaves admission drained**; errors never justify deploying anyway or
automatically resuming. Inspect status and resolve the cause before choosing
deploy or explicit resume. Drain intent persists in the mounted request journal across
restart; it is not a distributed lock. Resume is dependency-readiness gated. A status-only idle observation cannot
replace the authenticated drain-then-idle sequence for normal releases.

### Use the operator desk

Open `/backoffice` on the deployed app or the local Vite server. It asks for
`CANARY_OPS_TOKEN` instead of embedding the secret in the frontend. Leave the
server URL blank to connect to the same origin, or enter the production origin
from a local desk. A production server must allow that local origin in
`CANARY_BACKOFFICE_ORIGINS`. **Stage models** changes the defaults for new jobs
in all projects; it does not change an existing Draw edition. See
[model settings](reference/account-model-settings.md).

The desk labels the active Stripe mode from the server-only secret key: local
and staging should use `sk_test_...` (shown as **sandbox**), while production
should use `sk_live_...` (shown as **live**). A mismatch is surfaced as a
warning. Manual credit grants are ledger adjustments and never call Stripe;
they are written once with an idempotency marker and recorded as an operator
product event.

### Verify the proxy is reachable from the web process

```bash
fly ssh console -a canary-web \
  --command "curl -s http://127.0.0.1:4000/health/liveliness"
#   Expect JSON with status. Empty/timeout → the proxy didn't boot; check logs.
```

## Step 3 — Stripe webhook

In the Stripe **dashboard** (test mode first):

1. Developers → Webhooks → **Add endpoint**.
2. URL: `https://<canary-web-public-url>/api/billing/webhook` (the route is
   `POST /webhook` on the `billing` router at prefix `/api/billing`).
3. Event: `checkout.session.completed` (the event handled by the current
   billing router). Credits require `payment_status = paid` and a payment intent;
   an unhandled `payment_intent.succeeded` event does not grant credits.
4. Copy the signing secret (`whsec_...`) into `canary-web.env` as
   `STRIPE_WEBHOOK_SECRET` and re-import:
   `fly secrets set -a canary-web STRIPE_WEBHOOK_SECRET=whsec_...`.

The handler verifies signatures and is idempotent on
`stripe_payment_intent_id`, so duplicate deliveries are safe.

## Step 4 — volume backups (do not skip)

Fly volumes are single-region. Scheduled snapshots protect against a damaged
volume, but are not an off-provider backup. Earlier sessions recorded automatic
snapshots and five-day retention; inspect the actual volume and record today's
schedule, retention, and most recent successful snapshot before changing them:

```bash
fly volumes show <volume-id>
fly volumes update <volume-id> --scheduled-snapshots=true --snapshot-retention 14
# Optional: configure R2 delivery for finalized exports (instructions below).
```

Perform one restore drill before launch; a snapshot that has never been restored
is not yet a proven recovery path.

An earlier runbook recorded a 10 GB `canary_projects` volume; confirm actual
capacity and use now. Monitor disk utilization and alert before the agreed
headroom threshold (80% is an initial operational target). Verify the current
platform procedure before extending it. Back up the journals and recovery
records as well as artwork; finalized-export R2 delivery is not that backup.

## Optional — Cloudflare R2 delivery for finalized exports

The app can upload each finalized PDF/CBZ to R2 and redirect downloads to an
immutable content-addressed URL. Configure it only with an R2 **custom domain**
such as `https://media.scenewright.ink`; `r2.dev` is development-only and is
not served through Cloudflare's cache controls.

Create a dedicated bucket and an API token limited to Object Read & Write for
that bucket. Add these values to the same server-only Fly secret file, then
import it:

```env
R2_ENDPOINT=https://<cloudflare-account-id>.r2.cloudflarestorage.com
R2_ACCESS_KEY=<R2 API token access key>
R2_SECRET_KEY=<R2 API token secret>
R2_BUCKET=scenewright-exports
R2_PUBLIC_URL=https://media.scenewright.ink
```

Exports receive `Cache-Control: public, max-age=31536000, immutable` and the
object key includes its SHA-256, so a cached URL can never serve a later export
revision. Verify this after the first export:

```bash
curl -I "https://media.scenewright.ink/<export URL path returned by Canary>"
```

Expect `cache-control: public, max-age=31536000, immutable`; repeat after a
short delay and check `cf-cache-status`. This bucket deliberately serves only
finalized downloads. Draw/Book screen images remain authenticated, private app
responses until an authenticated edge design is introduced — a public R2 bucket
must not be used for authors' in-progress material.

## Step 5 — go-live checklist

When you're ready to drop the gating posture and open to the public:

- [ ] Swap Stripe to **live** keys: `fly secrets set -a canary-web
      STRIPE_SECRET_KEY=sk_live_... STRIPE_WEBHOOK_SECRET=whsec_live_...`
- [ ] Update the Stripe webhook endpoint URL to the production domain.
- [ ] `fly certs add app.<yourdomain>` + point DNS. TLS auto-provisions.
- [ ] Set `SCENEWRIGHT_APP_URL=https://app.<yourdomain>` and add the custom
      hostname to `CANARY_ALLOWED_HOSTS`, then redeploy. Stripe return URLs never
      reflect the request's `Origin` header.
- [ ] In Stripe Dashboard public business settings, publish the production
      Terms and Privacy URLs. Credit checkout always requires explicit Terms
      acceptance and Stripe renders the legal-policy links from those settings.
- [ ] Update Supabase **Site URL** and **Redirect URLs** to the production
      domain.
- [ ] Configure custom SMTP in Supabase for deliverability.
- [ ] Redeploy `canary-web` so the VITE build-args match the production URL
      (only needed if the Supabase URL changed).
- [ ] In an isolated recovery exercise, interrupt Draw and inspect persisted jobs,
      original-action recovery, and provider/ledger evidence. Do not promise that
      `/reset-stale` makes an interrupted paid action uncharged, and do not use
      production paid work as an unapproved crash test.

---

## Known gotchas (read once, save an hour each)

### Sentry disabled: invalid DSN

`server/sentry.py` skips init cleanly when `SENTRY_DSN` is *empty*, but a
non-empty invalid value is logged and Sentry remains disabled; it no longer
prevents the app from booting. Use a real DSN and verify a test event, or unset
the secret with `fly secrets unset SENTRY_DSN -a canary-web`.

### Boot-loop: OOM on `canary-web` (litellm proxy resident)

`Out of memory: Killed process (litellm) total-vm:~926MB` → the machine couldn't
fit both the proxy's then-resident baseline (~870 MB) and Playwright/Chromium
plus uvicorn. The checked-in co-located Machine pins `memory = '4gb'`.
The historical ~500 MB composition-process observation was from the retired
panel pipeline; it is not a current Finish memory measurement. Alert on OOM
exits and measure current peak memory during Cast, complete-page Draw, and
Finish/export before changing worker concurrency. Diagnose the process that
actually exited rather than assuming the old composition path is responsible.

### Boot-loop: `Trial machine stopping ... 5m0s`

This happened during the July trial deployment. Check the account's current
funding/trial restriction and the Machine event log; resolve the stated
restriction before explicitly restarting. Do not assume current trial terms
from that historical observation.

### `Forbidden use of secret API key in browser`

You baked **service_role** into the frontend instead of **anon/publishable**.
Both keys are `eyJ...` JWTs sitting next to each other in the Supabase
dashboard. The frontend needs the one with `"role":"anon"` in its payload.
**Rotate the leaked service_role key** in the dashboard — it was shipped in a
publicly fetchable JS bundle. Fix the build-arg value and redeploy:
`--build-arg VITE_SUPABASE_PUBLISHABLE_KEY=<anon key>`.

### OpenTelemetry is intentionally disabled

`CANARY_OTEL_ENABLED=false` is the launch default because the production image
does not install the `otel` extra. Sentry still captures errors. Do not enable
OTel until the extra is installed and an export has been verified.

### Deploy error: `app not found`

You ran `fly deploy` before `fly launch`. `fly deploy` only works on apps that
already exist in Fly. Run `fly launch --no-deploy` first to register the app
record, then deploy.

### Deploy error: `failed to get VM ... no route to host`

This was observed during a historical Fly provisioning attempt. Inspect the
Machine/release state first: the deployment may have partially completed.
Re-establish drain on the running process before retrying a normal release,
preserve the volume, and record the outcome. An error alone does not prove the
old release is still running or that it is safe to deploy again.

---

## Reference: what the app needs

### `canary-web` — runtime secrets (via `fly secrets`)

One consolidated set, since the proxy and web app share a container:

- **Proxy layer:** `LITELLM_MASTER_KEY`, `LITELLM_SALT_KEY`, plus the provider
  keys you actually use (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`,
  `FAL_KEY`, optionally `OPENROUTER_API_KEY`). Both processes inherit the container environment, but
  only the loopback proxy uses these keys for provider requests.
- **Web-app layer:** `LITELLM_API_KEY` (== `LITELLM_MASTER_KEY`), `SUPABASE_URL`,
  `SUPABASE_SECRET_KEY`, `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`,
  `CANARY_OPS_TOKEN`,
  `SENTRY_DSN` and `SENTRY_TRACES_SAMPLE_RATE` (optional — omit the DSN to
  disable), `LANGFUSE_*` /
  `OTEL_EXPORTER_OTLP_ENDPOINT` (optional).

Provider keys never leave the container or reach the browser — the proxy is
bound to `127.0.0.1`, and the public `http_service` only exposes port 8000.
This is network isolation, not process-level secret isolation: uvicorn inherits
the same environment.

Non-secret runtime config is in `fly.toml [env]`: `CANARY_ENV`,
`CANARY_COOKIE_SECURE`, `CANARY_OTEL_ENABLED`, `CANARY_LABS_ENABLED`,
`CANARY_ALLOWED_HOSTS`, `SCENEWRIGHT_APP_URL`, `LITELLM_BASE_URL`, pricing
policy, worker counts, body limits, and timeouts.

### `canary-web` — build args (via `fly deploy --build-arg`)

`VITE_SUPABASE_URL`, `VITE_SUPABASE_PUBLISHABLE_KEY` (anon, not service_role),
`VITE_CANARY_ENV=production`, `VITE_SENTRY_DSN`,
`VITE_SENTRY_TRACES_SAMPLE_RATE`, and
`VITE_SENTRY_REPLAYS_ON_ERROR_SAMPLE_RATE` (all Sentry values optional). These are inlined
into the JS bundle by Vite at build time and are not available at runtime.
