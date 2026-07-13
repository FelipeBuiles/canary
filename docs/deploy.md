# Canary — Fly.io Deploy Runbook

> A from-scratch, copy-pasteable guide to deploying Canary on a **fresh** Fly.io
> account. Distilled from real deploy sessions — every gotcha below was hit in
> practice, not theorized. Companion to `docs/proposals/launch-readiness.md`
> (the *why*) and `docs/proposals/deployment-platform-review.md` (the *what else
> we considered*). Read this one top to bottom before the first deploy.
>
> **Updated 2026-07-05:** collapsed the previous two-app split (`canary-web` +
> `litellm-gw`) into a single Fly app. The LiteLLM proxy now runs as a loopback
> subprocess inside the web container — provider keys are isolated to that
> process and never exposed publicly, but they live on one machine instead of
> two. Trims ~$10-15/mo idle compute and halves the deploy surface.
>
> **Dated 2026-07-04.** Verify against current Fly/Supabase/Stripe dashboards
> before launch — UI labels drift.

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
for `/health/liveliness`, then `exec`s uvicorn as PID 1. Provider API keys live
in `canary-web`'s fly secrets; only the proxy process reads them.

## Prerequisites (before you touch Fly)

1. **A payment method on the Fly account.** The free trial caps each machine
   at **5 minutes** of runtime, then SIGINTs it — the container will boot-loop
   on a 5-min cycle forever and never reach ready. Add the card at
   **fly.io/app/billing** before the first deploy. Floor cost is ~$15–25/mo
   for the one machine idle (4GB VM); provider usage is on top.
2. **Fly CLI installed + authenticated**: `brew install flyctl && fly auth login`.
3. **A Supabase project** (prod). From its dashboard grab:
   - Project URL (`https://<project>.supabase.co`).
   - **anon / publishable** key (role:`anon` in the JWT) — used by the browser.
   - **service_role** key (role:`service`) — used by the backend only.
   - Database connection string (for schema bootstrap).
4. **A Stripe account** (test mode first, live at launch).
5. **Provider API keys** for whatever models you route through LiteLLM
   (`OPENAI_API_KEY`, `GEMINI_API_KEY`, `ANTHROPIC_API_KEY`, `REVE_API_KEY`,
   `FAL_KEY`, etc.). Only set the ones you actually use. These live as fly
   secrets on `canary-web` now (they used to be on `litellm-gw`).
6. **A GCP service account JSON** for Vertex (only if you use Vertex models).
   The repo expects one at `litellm/gcp-credentials.json` locally; you'll
   base64-encode it into the `GCP_CREDENTIALS_B64` secret.

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
OPENAI_API_KEY=sk-...
ANTHROPIC_API_KEY=sk-ant-...
GEMINI_API_KEY=AIza...
REVE_API_KEY=...
FAL_KEY=...
OPENROUTER_API_KEY=sk-or-...      # only if you use OpenRouter
TOGETHER_API_KEY=...              # only if you use Together
VERTEXAI_PROJECT=your-gcp-project-id
GCP_CREDENTIALS_B64=<see next line>

# ─── Web app ───────────────────────────────────────────────────────────
SUPABASE_URL=https://<project>.supabase.co
SUPABASE_SECRET_KEY=<service_role key — server only, NEVER in the browser>
STRIPE_SECRET_KEY=sk_test_...           # test mode while gating
STRIPE_WEBHOOK_SECRET=whsec_...         # from test-mode webhook endpoint
# SENTRY_DSN=<only if you have a real https://...@... DSN; omit to no-op>
# LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY / OTEL_EXPORTER_OTLP_ENDPOINT
#   if you wire Langfuse/OTel.
```

```bash
echo "GCP_CREDENTIALS_B64=$(base64 < litellm/gcp-credentials.json)" >> ~/.config/canary/canary-web.env
```

> **⚠️ Critical key distinction.** Supabase exposes two keys that both look like
> `eyJ...` JWTs. The **anon/publishable** key goes into the browser bundle via
> `VITE_SUPABASE_PUBLISHABLE_KEY`. The **service_role** key bypasses RLS and
> must **never** leave the server. If you accidentally bake service_role into
> the frontend, Supabase rejects login with *"Forbidden use of secret API key
> in browser"* — and the key is now compromised, so rotate it in the dashboard.

## Step 1 — Supabase schema + auth config

`canary-web` will 500 on every query without these.

```bash
# 1a. Apply the canonical schema (idempotent — IF NOT EXISTS throughout)
psql "<prod database url>" -f docs/supabase-schema.sql
```

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
  --build-arg VITE_SUPABASE_URL=https://<project>.supabase.co \
  --build-arg VITE_SUPABASE_PUBLISHABLE_KEY=<anon/publishable key, NOT service_role> \
  --build-arg VITE_CANARY_ENV=production
  # --build-arg VITE_SENTRY_DSN=<frontend DSN>   # optional

# 2c. Verify boot
fly logs -a canary-web
#   Look for, in order:
#     "[entrypoint] waiting for litellm proxy at 127.0.0.1:4000..."
#     "[entrypoint] litellm proxy ready (after Ns)"
#     "Uvicorn running on http://0.0.0.0:8000"
#   Then the machine must stay up past the 1m readiness grace period.
```

If the proxy fails to come up, the entrypoint aborts early (it polls
`/health/liveliness` for ~60s, then bails if the proxy process died). Check
`fly logs` for the litellm traceback — most commonly a missing provider key
or a malformed `config.yaml`.

### Readiness probe contract

`fly.toml` points the health check at `GET /api/health/ready`, defined in
`server/app.py`. It returns `error` (and Fly will keep the machine unhealthy)
if **either** dependency is unreachable:

- **Supabase** — runs `select id from projects limit 1`. Needs the schema from
  Step 1 and a valid `SUPABASE_SECRET_KEY`.
- **LiteLLM** — `GET <LITELLM_BASE_URL>/health/liveliness` with the bearer
  `LITELLM_API_KEY`. Hits the loopback proxy inside the same container.

In local development, a dependency is skipped when both of its settings are
absent. In `CANARY_ENV=production`, missing or partial dependency configuration
is an error and the endpoint returns HTTP 503. Fly therefore keeps the machine
unhealthy until both checks report `ok`.

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
3. Events: `checkout.session.completed`, `payment_intent.succeeded`.
4. Copy the signing secret (`whsec_...`) into `canary-web.env` as
   `STRIPE_WEBHOOK_SECRET` and re-import:
   `fly secrets set -a canary-web STRIPE_WEBHOOK_SECRET=whsec_...`.

The handler verifies signatures and is idempotent on
`stripe_payment_intent_id`, so duplicate deliveries are safe.

## Step 4 — volume backups (do not skip)

Fly volumes are single-region. Scheduled snapshots protect against a damaged
volume, but are not an off-provider backup. The current volume has automatic
snapshots enabled with five-day retention. Confirm that state and increase the
retention before inviting testers:

```bash
fly volumes show <volume-id>
fly volumes update <volume-id> --scheduled-snapshots=true --snapshot-retention 14
# Optional: wire a post-compose hook to push exports/ to R2 (storage.py exists).
```

Perform one restore drill before launch; a snapshot that has never been restored
is not yet a proven recovery path.

## Step 5 — go-live checklist

When you're ready to drop the gating posture and open to the public:

- [ ] Swap Stripe to **live** keys: `fly secrets set -a canary-web
      STRIPE_SECRET_KEY=sk_live_... STRIPE_WEBHOOK_SECRET=whsec_live_...`
- [ ] Update the Stripe webhook endpoint URL to the production domain.
- [ ] `fly certs add app.<yourdomain>` + point DNS. TLS auto-provisions.
- [ ] Set `SCENEWRIGHT_APP_URL=https://app.<yourdomain>` and add the custom
      hostname to `CANARY_ALLOWED_HOSTS`, then redeploy. Stripe return URLs never
      reflect the request's `Origin` header.
- [ ] Set `SCENEWRIGHT_TERMS_URL=https://<domain>/legal/terms` so Stripe
      checkout captures enforceable ToS consent.
- [ ] Update Supabase **Site URL** and **Redirect URLs** to the production
      domain.
- [ ] Configure custom SMTP in Supabase for deliverability.
- [ ] Redeploy `canary-web` so the VITE build-args match the production URL
      (only needed if the Supabase URL changed).
- [ ] Soak test: kill the machine mid-draw → confirm `/reset-stale` leaves the
      user uncharged and the project recoverable.

---

## Known gotchas (read once, save an hour each)

### Sentry disabled: invalid DSN

`server/sentry.py` skips init cleanly when `SENTRY_DSN` is *empty*, but a
non-empty invalid value is logged and Sentry remains disabled; it no longer
prevents the app from booting. Use a real DSN and verify a test event, or unset
the secret with `fly secrets unset SENTRY_DSN -a canary-web`.

### Boot-loop: OOM on `canary-web` (litellm proxy resident)

`Out of memory: Killed process (litellm) total-vm:~926MB` → the machine can't
fit both the proxy's resident baseline (~870 MB) and Playwright/Chromium plus
uvicorn. `fly.toml` pins `memory = '4gb'`; do not drop below 3 GB. The
proxy's 870 MB is *idle baseline* — request handling grows on top of it, and
the compose stage spawns a Chromium process that peaks near 500 MB.

If you see OOMs mid-generation specifically, Playwright is the likeliest
culprit, not litellm.

### Boot-loop: `Trial machine stopping ... 5m0s`

Account has no payment method. Trial tier kills every machine at 5 min. Add a
card at fly.io/app/billing, then `fly machine restart -a canary-web`.

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

Transient Fly control-plane networking blip (Fly's API lost contact with the
machine it just provisioned). Not a code or config problem. Just `fly deploy`
again; usually succeeds on retry.

---

## Reference: what the app needs

### `canary-web` — runtime secrets (via `fly secrets`)

One consolidated set, since the proxy and web app share a container:

- **Proxy layer:** `LITELLM_MASTER_KEY`, `LITELLM_SALT_KEY`, plus the provider
  keys you actually use (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`,
  `GEMINI_API_KEY`, `REVE_API_KEY`, `FAL_KEY`, optionally
  `OPENROUTER_API_KEY` / `TOGETHER_API_KEY`), `VERTEXAI_PROJECT`,
  `GCP_CREDENTIALS_B64`. Both processes inherit the container environment, but
  only the loopback proxy uses these keys for provider requests.
- **Web-app layer:** `LITELLM_API_KEY` (== `LITELLM_MASTER_KEY`), `SUPABASE_URL`,
  `SUPABASE_SECRET_KEY`, `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`,
  `SENTRY_DSN` (optional — omit if invalid), `LANGFUSE_*` /
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
`VITE_CANARY_ENV=production`, `VITE_SENTRY_DSN` (optional). These are inlined
into the JS bundle by Vite at build time and are not available at runtime.
