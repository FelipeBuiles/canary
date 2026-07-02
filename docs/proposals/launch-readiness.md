# Canary — Launch Readiness Plan

> Findings from a deep audit of the codebase + web research on SaaS / AI-product
> launch best practices. Dated 2026-07-01.
>
> **Status (2026-07-02):** the following items from the P0/P1 list below are now
> **closed** in `main` — see `deployment-platform-review.md` §6 for the living
> checklist: #1 deployment artifacts (`fly.toml`, `fly.litellm.toml`,
> `Dockerfile.litellm`, `--proxy-headers`), #2 upload cap + project cap + rate
> limiting (`slowapi` on create/run/all `*/regen*`), #3 Sentry (backend init in
> `_lifespan` + frontend), #4 ToS/Privacy/AUP + abuse-report + DMCA contact
> (legal pages, Stripe ToS consent, `legal@` report channel), #5 billing-test
> fix, #6 cookie `secure` + `verify_aud` (enforced by default in production),
> #8 readiness probe (Supabase + LiteLLM).
> **Still open:** #9 credit margin, plus CI/CD.
>
> **Decisions locked:** host = **Fly.io**; launch scope = **public signup from
> day 1**. Public scope means every P0 item below is mandatory before launch.

## TL;DR

The **core product is launch-ready** — auth, billing, credits, the 9-stage
pipeline, and resilience are well-built and well-tested (476/477 backend tests,
217 web tests). The **gaps are operational, not product**: no deployment story,
no abuse/rate-limiting layer, no error tracking, and no legal/safety posture.

For a **public** launch you must close **all four P0 gaps** (deployment,
abuse-layer, error-tracking, ToS/moderation) plus the P1 correctness items. That
is a focused **~1.5–2 week hardening pass**, after which you ship a single Fly.io
machine + a persistent volume, with LiteLLM as a sibling Fly app on the private
6PN network. Horizontal scaling is a Phase 3 refactor (the in-memory job queue
and filesystem storage pin you to one instance until then).

---

## What's Already Solid (do not break)

Audited and found production-grade — preserve these:

| Area | Verdict | Evidence |
|---|---|---|
| **Auth** | ✅ Solid | Supabase JWT via JWKS (RS256/ES256). Ownership enforced by DB-scoped queries in `deps._resolve_project_slug`. HttpOnly session cookie for browser-native consumers (img/EventSource). |
| **Credits ledger** | ✅ Excellent | Atomic reservations via `pg_advisory_xact_lock`; `user_credits` is a live computed view (no double-count); reservations always released on failure + on startup (`release_all_stale_reservations`). |
| **Stripe billing** | ✅ Solid | Webhook signature verification + idempotency on `stripe_payment_intent_id`; structured 402 payload drives the buy-credits UI. |
| **Secrets isolation** | ✅ Good | All provider keys live in the LiteLLM proxy; the app only holds `LITELLM_BASE_URL` + gateway key. |
| **Supabase RLS** | ✅ Defense-in-depth | Policies on projects/ledger/usage even though service_role bypasses them. |
| **Retry/backoff** | ✅ Good | 429 exponential backoff (4→60s, 5 retries); malformed-JSON retries on structured calls. |
| **Pipeline resilience** | ✅ Good | Stages resumable; state persisted to `state.json`; draw stage auto-reconciles on `GET /status` poll; `/reset-stale` recovers crashed runs. |
| **Test coverage** | ✅ Good | ~476 backend tests across pricing, credited jobs, generation jobs, panel lifecycle; 217 frontend tests. Clean tech debt (only 2 TODOs). |

---

## Gaps — Prioritized

### 🔴 P0 — Block public launch (all mandatory)

#### 1. No deployment story exists

No hosting config, no deploy docs, no production run command.

- `docker-compose.yml` has the `canary` service **commented out**.
- `cli.py` hardcodes `uvicorn.run(app, host, port)` — single worker, **no
  `--proxy-headers`** (breaks the secure-cookie / client-IP detection behind
  Fly's proxy).
- `.github/workflows/` is empty — no CI/CD.
- The Dockerfile builds a correct multi-stage image (React → Python → Playwright
  Chromium), so the artifact exists; it just isn't shipped.

**Action:** see the **Fly.io Deployment** section below — `fly.toml`, the LiteLLM
sibling app, the GitHub Actions pipeline, and the prod env-var set.

#### 2. No abuse / rate-limiting layer + unbounded upload

Credits gate *cost*, not *abuse* — and a public launch invites bots:

- `POST /api/projects/` (`server/routers/projects.py`) accepts an `UploadFile`
  and streams it to disk with **no size limit** and **no per-user project cap**
  → disk exhaustion / DoS.
- No rate limiting anywhere (no `slowapi`). Auth, run, regen endpoints are
  unthrottled.
- No per-user concurrency cap on expensive ops (the global semaphore protects
  the *provider*, not the *user's wallet* from a runaway script).

**Action (concrete):**

- In `create_project`: cap `file.size` (e.g. reject > ~10 MB before streaming),
  count existing projects for the user and reject over `MAX_PROJECTS_PER_USER`
  (e.g. 25).
- Add `slowapi` with a `Request`-arg limiter; apply `@limiter.limit(...)` to
  auth + create + run + regen routes. Note slowapi needs the `request: Request`
  param on the handler and `app.state.limiter = limiter` + the
  `_rate_limit_exceeded_handler`.
- Gate LiteLLM/image calls behind the existing per-credit pre-check (already
  present via `assert_sufficient_credits`) — that is your cost ceiling.

#### 3. No error tracking / alerting

No Sentry. `CANARY_OTEL_ENABLED` defaults **false**. You'll be blind in prod.

**Action:** add `sentry-sdk[fastapi]` initialized in `server/app.py`
(`before_send` to scrub auth headers), `@sentry/react` in `web/src/main.tsx`,
enable OTel/Langfuse export, and a Sentry alert rule on `level:error` spike.

#### 4. Legal / content-safety posture (mandatory for public) — ✅ CLOSED

Users upload arbitrary prose that becomes generated imagery. Providers
(Gemini/Vertex) have built-in safety and `s7_draw.py` already classifies
"filtered out / safety rating" refusals — but there is **no Terms of Service,
no acceptable-use policy, no abuse-report flow, and no moderation gate**.

**Done (templated docs, no attorney):**

- Published **Terms of Service** + **Privacy Policy** + **Acceptable-Use
  Policy** at `/legal/{terms,privacy,acceptable-use}` (public routes), linked
  from the app footer on every page and from the signup screen. ToS grants the
  license to *process and render* uploaded text, states the AI-output
  copyright reality, and carries **indemnity**, **liability cap** (3 months of
  spend or $50), and **arbitration + class-action waiver**.
- Abuse-report + DMCA takedown handled via a **`mailto:legal@scenewright.ink`**
  channel surfaced on the footer and the AUP page — lighter than a
  `POST /report` + admin view, sufficient at hail-mary scale. This is the
  "actual knowledge" path that triggers any NCMEC reporting duty.
- Stripe checkout now sends `terms_of_service_url` +
  `consent_collection={"terms_of_service": "required"}` — enforceable consent
  captured at payment (stronger than the signup browsewrap text). Also fixed
  the line-item name **"Pulp" → "Scenewright"**.
- Brand/contact identifiers centralized in `server/branding.py` + the public
  `GET /api/branding` endpoint; env-overridable (`SCENEWRIGHT_*`).

**Decisions locked for v1:**

- Moderation stance = **(a) rely on provider safety filters + reporting**. No
  input-scan gate on `extract` (Open Question #2 → resolved). The existing
  `ai_usage_events` audit trail (with its reserved `status='refused'` value)
  remains the audit spine.
- No `user_consent` table — browsewrap + Stripe-at-checkout consent is the
  chosen posture for a solo launch.

**Still on the operator (not code):** stand up `legal@scenewright.ink` as a
monitored forward; sanity-read the three docs before going live; set
`SCENEWRIGHT_TERMS_URL` to the production URL. (Registering a DMCA agent with
the Copyright Office is $6 and recommended if traction develops.)

---

### 🟠 P1 — Correctness, fix before launch

#### 5. Failing test in the billing path

`tests/test_image_failure_meta.py::test_panel_estimate_counts_actual_uploaded_references`
fails (expected `$0.06868`, got `$0.03444` — ≈half, a reference-count or
per-image-cost change). **On the cost-estimation path** — confirm it's a stale
test, not a real billing bug. Either way: green CI is a launch gate.

#### 6. Cookie `secure` flag breaks behind Fly's proxy

`auth.py` sets `secure=request.url.scheme == "https"`. Behind Fly's TLS proxy,
`request.url.scheme` reports `http` unless Uvicorn starts with `--proxy-headers`
(and Fly sends `X-Forwarded-Proto`). Without it the session cookie goes over
plain HTTP. Also flip `verify_aud` to `True` (currently `False`).

**Action:** drive `secure` from `CANARY_ENV == production` (or an explicit
`CANARY_COOKIE_SECURE` flag) instead of scheme detection; start Uvicorn with
`--proxy-headers --forwarded-allow-ips='*'`.

#### 7. In-flight generation work lost on restart

Credit reservations are released on startup (no user charge for lost work ✅),
but mid-flight image work is lost and must be re-run. Acceptable for single-box
with rare restarts — just document the recovery UX (`/reset-stale` exists).

#### 8. Health check is shallow

`GET /api/health` returns `{"status":"ok"}` unconditionally. Add a readiness
probe that pings Supabase + LiteLLM so Fly's checks don't route to a half-up
machine.

#### 9. Unit economics

`PULP_MODEL_COST_MARKUP=1.0` = selling AI compute at **zero gross margin**.
`AI_BILL_FAILED_REQUESTS=provider_usage_only` means failed provider calls you
*still pay for* may not be charged to the user. Confirm the intended margin and
the failed-request billing policy before opening purchases.

---

### 🟡 P2 — Defer to scaling phase

#### 10. Single-instance ceiling

In-memory job queue (`generation_jobs.py`), SSE queues, and semaphores are
process-local; project files are on disk. This caps you to **one instance**.
Fine at launch; Phase 3 refactor = move queue to Postgres/Redis, move files to
R2 (the `storage.py` upload helper already exists).

#### 11. Labs router

`/api/labs/*` fetches an external URL (short-story import). It's
domain-constrained, but for a public v1, gate labs behind an env flag
(`CANARY_LABS_ENABLED=false`) to shrink surface area.

#### 12. Observability depth

`ai_usage_events` records per-user cost, but there's no margin / provider-spend
vs revenue view. Build it post-launch to prove unit economics.

---

## Fly.io Deployment (concrete)

### Architecture

```text
  Fly.io org (6PN private network)
  ┌──────────────────────────────────────────────────────────┐
  │                                                          │
  │  Machine A: canary-web  (public, TLS auto)               │
  │  ┌────────────────────────────────────────────┐          │
  │  │ uvicorn --proxy-headers (1 worker)         │          │
  │  │ + Sentry + slowapi                         │          │
  │  │ mounts: /projects  ← persistent volume     │          │
  │  └───────────────┬───────────────────────────┘          │
  │                  │  http://litellm.internal:4000         │
  │  Machine B: litellm-gw  (private, Flycast/6PN)           │
  │  ┌────────────────────────────────────────────┐          │
  │  │ LiteLLM proxy — holds ALL provider keys     │          │
  │  │ OpenAI / Gemini / Anthropic / Reve / Fal    │          │
  │  └────────────────────────────────────────────┘          │
  └──────────────────────────────────────────────────────────┘
            │                  │                  │
       Supabase            Stripe            Sentry/Langfuse
       (managed)          (live keys)         (SaaS)
```

- **Machine A** = the Canary app. Public. Persistent volume for `/projects`.
  **One** uvicorn worker (in-memory state forbids more). Needs enough RAM for
  Playwright/Chromium in the compose stage — start at `shared-cpu-2x, 2GB`
  (`vm_size`) and watch for Chromium OOMs.
- **Machine B** = LiteLLM as a **separate Fly app** on the same org's private
  network, reached as `http://litellm-gw.internal:4000` (`.internal` DNS is
  private/6PN only — never exposed). This mirrors your `docker-compose` model
  exactly and keeps provider keys off the public machine.
- **Supabase / Stripe / Sentry / Langfuse** stay as managed SaaS.

### `fly.toml` (Machine A — Canary)

```toml
app = "canary-web"
primary_region = "iad"   # pick closest to users

[build]
  dockerfile = "Dockerfile"

[env]
  CANARY_ENV = "production"
  CANARY_GENERATION_WORKERS = "5"
  CANARY_GENERATION_JOB_TIMEOUT_SECONDS = "900"
  CANARY_OTEL_ENABLED = "true"
  CANARY_LABS_ENABLED = "false"
  CANARY_COOKIE_SECURE = "true"
  LITELLM_BASE_URL = "http://litellm-gw.internal:4000"
  # LITELLM_API_KEY, SUPABASE_*, STRIPE_*, SENTRY_DSN, LANGFUSE_* → fly secrets

# Persistent volume for project files (survives redeploy)
[mounts]
  source = "canary_projects"
  destination = "/projects"

[http_service]
  internal_port = 8000
  force_https = true
  auto_stop_machines = false      # long-running image jobs can't survive stop
  auto_start_machines = true
  [http_service.concurrency]
    type = "requests"
    hard_limit = 200
    soft_limit = 150

[[http_service.checks]]
  interval = "30s"
  timeout = "5s"
  grace_period = "60s"
  method = "GET"
  path = "/api/health"            # deepen to readiness probe (P1 #8)

[[vm]]
  size = "shared-cpu-2x"
  memory = "2g"                   # Playwright/Chromium needs headroom
```

### Provisioning runbook (Machine A)

```bash
fly launch --no-deploy              # creates app from Dockerfile + fly.toml
fly volumes create canary_projects --region iad --size 10   # 10 GB to start
fly secrets set \
  LITELLM_API_KEY="<litellm master key>" \
  SUPABASE_URL="<prod url>" SUPABASE_SECRET_KEY="<service-role key>" \
  STRIPE_SECRET_KEY="<live sk>" STRIPE_WEBHOOK_SECRET="<live whsec>" \
  SENTRY_DSN="<dsn>" LANGFUSE_PUBLIC_KEY="<pk>" LANGFUSE_SECRET_KEY="<sk>" \
  OTEL_EXPORTER_OTLP_ENDPOINT="<langfuse otlp host>"
fly certs add app.yourdomain.com     # TLS auto-provisioned
fly deploy
```

### LiteLLM (Machine B) — sibling app

Run your existing `litellm/config.yaml` as its own Fly app (no public port —
bind to the 6PN network only):

```bash
cd litellm && fly launch --name litellm-gw --no-deploy
fly secrets set OPENAI_API_KEY=... ANTHROPIC_API_KEY=... GEMINI_API_KEY=... \
  REVE_API_KEY=... FAL_KEY=... LITELLM_MASTER_KEY=... VERTEXAI_PROJECT=...
fly deploy
# confirm: fly ssh console -a canary-web → curl http://litellm-gw.internal:4000/health
```

Keep the same `litellm/config.yaml` + `litellm_handlers/` you use locally.

### CI/CD (GitHub Actions)

A `main`-triggered workflow: run `pytest` + `npm test` (fail-fast on the
billing test), `fly deploy -a canary-web --image` (or `fly deploy` building
remotely). Gate on green tests. Add a manual dispatch for prod.

### Prod env-var checklist

`SUPABASE_URL`, `SUPABASE_SECRET_KEY`, `STRIPE_SECRET_KEY` (live),
`STRIPE_WEBHOOK_SECRET` (live endpoint), `LITELLM_BASE_URL`,
`LITELLM_API_KEY`, `SENTRY_DSN`, `LANGFUSE_*`, `OTEL_EXPORTER_OTLP_ENDPOINT`,
`PULP_CREDITS_PER_PROVIDER_USD`, `PULP_MODEL_COST_MARKUP` (set > 1.0 if margin
intended), `CANARY_ENV=production`, `CANARY_COOKIE_SECURE=true`,
`CANARY_LABS_ENABLED=false`, `CANARY_OTEL_ENABLED=true`.

---

## Phased Execution Plan

### Phase 0 — Pre-launch hardening (~4–6 days) — MANDATORY for public

1. Fix the failing billing test (P1 #5); confirm pricing correctness.
2. `projects.py`: upload size cap + `MAX_PROJECTS_PER_USER` cap (P0 #2).
3. `slowapi` rate limiting on auth/create/run/regen routes (P0 #2).
4. `cli.py`: `uvicorn.run(..., proxy_headers=True, forwarded_allow_ips="*")`;
   `auth.py`: cookie `secure` from env flag + `verify_aud=True` (P1 #6).
5. Sentry backend + frontend; enable OTel/Langfuse (P0 #3).
6. Deepen `/api/health` to a readiness probe (P1 #8).
7. Confirm unit economics — set `PULP_MODEL_COST_MARKUP` (P1 #9).
8. ~~Write + publish ToS / Privacy / Acceptable-Use; add abuse-report endpoint +
   DMCA contact (P0 #4).~~ **Done** — legal pages shipped; report channel is
   `mailto:legal@` (not a `POST /report` endpoint, by scope choice). Operator
   to-dos remain: monitor `legal@`, set `SCENEWRIGHT_TERMS_URL`.
9. Gate labs behind `CANARY_LABS_ENABLED` (P2 #11 — cheap, do now).

### Phase 1 — Ship to Fly.io (~2–3 days)

1. Provision Machine A (canary-web) + volume; Machine B (litellm-gw) (P0 #1).
2. Wire GitHub Actions: test → build → deploy on `main` (P0 #1).
3. Provision prod secrets; Stripe **live** webhook endpoint; custom domain + TLS.
4. End-to-end run against prod keys in staging first (a private Fly app).

### Phase 2 — Public launch

1. Flip the domain public; verify Stripe live charges land in the ledger.
2. Soak test: crash mid-draw → confirm `/reset-stale` + reservation release leave
    the user uncharged and the project recoverable.
3. Monitor dashboard: error rate, provider-spend vs credits-sold, p95 stage
    latency, job-failure rate, the failed-request margin leak.

### Phase 3 — Scale (when one box isn't enough)

1. Externalize the job queue (Postgres-backed or Redis/RQ).
2. Move project storage to R2 (`storage.py` upload helper already exists).
3. Multiple uvicorn/gunicorn workers behind Fly's LB.
4. CDN for `/static` fonts + generated panel images.

---

## Open Questions

1. **Unit economics** — is `MODEL_COST_MARKUP=1.0` intentional (loss-leader) or
   unconfigured? What's the target gross margin? (Sets the launch price.)
2. ~~**Moderation stance** — rely on provider safety filters + reporting (fast), or
   add an explicit input-scan moderation gate on `extract` before launch?~~
   **Resolved:** rely on provider safety filters + the `legal@` report channel
   for v1 (no input-scan gate). See §4.
3. **Failed-request billing** — keep `AI_BILL_FAILED_REQUESTS=provider_usage_only`
   (user-friendly, you eat the cost) or charge for consumed provider calls?
4. **Box size** — start `shared-cpu-2x / 2GB`, or go bigger for Playwright headroom?
