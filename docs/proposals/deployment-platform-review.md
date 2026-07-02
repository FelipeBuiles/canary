# Canary — Deployment Platform Review

> Architecture review + platform comparison for launching Canary. Dated
> 2026-07-02. Companion to `launch-readiness.md` (which locks Fly.io and gives
> the hardening plan); this doc explains *why* Fly and what the alternatives
> cost.

## TL;DR

**Proceed with Fly.io** — it is the only cheap platform that satisfies all three
hard constraints without forcing a refactor first. Launch cost is ~**$18/mo**
vs $60–154/mo for the alternatives. The AI provider spend (Vertex, Anthropic,
Reve) dwarfs hosting, so the bigger lever is credit margin (`PULP_MODEL_COST_MARKUP`),
not infra choice. Deployment artifacts now exist: `fly.toml`, `fly.litellm.toml`,
`Dockerfile.litellm`, and the `--proxy-headers` Dockerfile fix.

---

## 1. What needs to run

Canary is a **single FastAPI/Uvicorn process** serving a bundled React SPA, a
REST API, and SSE progress streams. The 9-stage pipeline delegates all AI work
to external providers through a self-hosted **LiteLLM proxy**. No GPU, no local
inference — everything is API calls.

### Services you must host

| Component | Why it's yours | Notes |
|---|---|---|
| **Canary app** | Web server + pipeline | Needs Playwright/Chromium (2 GB+ RAM), persistent `/projects` volume |
| **LiteLLM proxy** | Custom handlers (Vertex multimodal, Reve, fal) + holds all provider keys | Must be **private** — keys never public |

### Managed SaaS (already external — no hosting decision)

| Service | Role | Criticality |
|---|---|---|
| **Supabase** | Auth (JWT/JWKS) + Postgres (`projects`, `user_credits`, `credit_ledger`, `ai_usage_events`) | Critical — readiness probe fails if down |
| **Stripe** | Credit purchases + webhook | Critical for monetization |
| **Cloudflare R2** | Export PDF/CBZ CDN | Optional (falls back to local disk) |
| **Sentry / OTel** | Error tracking / tracing | Optional (no-op without DSN) |

### Droppable / defer

**Langfuse** is a 6-container stack (web + worker + Postgres + ClickHouse + MinIO
+ Redis). Every Langfuse call **no-ops** when `LANGFUSE_*` env vars are unset, so
at launch either use **Langfuse Cloud** or **leave it off** — don't self-host the
stack on Fly (it would roughly triple your container count and cost).

---

## 2. Hard constraints that filter the field

Three architectural facts dominate platform choice:

### 2a. Filesystem is the source of truth → persistent volume mandatory

`/projects` holds **300 MB–2 GB per project** (panel PNGs, compose pages, refs)
with atomic `state.json` writes. A real block-storage volume is required.

- **Eliminates DigitalOcean App Platform** — no persistent volumes for containers.
- **Weakens Cloud Run** — only GCS FUSE (object store posing as a filesystem).
  Poor for the write-heavy artifact store; would force the Phase 3 storage
  refactor before launch.

### 2b. In-memory `asyncio.Queue` + `app.state` → single-instance ceiling

Jobs, SSE queues, and semaphores live in process memory; **lost on restart**.
This is explicitly a Phase 3 refactor (externalize queue to Postgres/Redis).

- **Hurts serverless platforms** (Cloud Run, Lambda) that auto-spawn stateless
  instances. To preserve state you'd pin `min_instances=1, max_instances=1`,
  defeating the serverless cost benefit.
- Means **no horizontal scaling** of the app until Phase 3.

### 2c. Co-located private LiteLLM → private networking + long timeouts

The app makes synchronous, long-lived HTTP calls (600 s read timeout) to LiteLLM,
which holds Vertex/Anthropic/Reve keys. Needs **private networking** so the
gateway is never public, plus **long request timeouts**.

**Secondary needs:** 2 GB+ RAM (Chromium), SSE/WebSocket support, TLS termination
+ `--proxy-headers` for secure cookies.

---

## 3. Platform comparison

| Platform | Persistent vol | Private net | Scale-to-zero | SSE fit | Docker + Chromium | Launch cost (est.) | Verdict |
|---|---|---|---|---|---|---|---|
| **Fly.io** | ✅ native ($0.15/GB) | ✅ 6PN / `.internal` | ✅ auto-start/stop | ✅ | ✅ | **~$18/mo** | **Best fit** |
| **Render** | ✅ disks ($0.25/GB) | ✅ private svcs (Pro) | ❌ paid runs 24/7 | ✅ | ✅ | ~$60/mo | Good, pricier |
| **Railway** | ✅ ($0.15/GB) | ✅ project net | ❌ no scale-to-zero | ✅ | ✅ | ~$90/mo | Simplest UX, costly always-on |
| **AWS Fargate** | ✅ EFS (real NFS) | ✅ VPC/SG | ⚠️ manual stop/start | ✅ | ✅ | ~$150/mo+ | Capable, high ops + ancillary fees |
| **Cloud Run** | ❌ only GCS FUSE | ⚠️ VPC connector ($$$) | ✅ | ⚠️ per-instance state breaks | ✅ | ~$200/mo | **Not viable pre-refactor** |
| **Koyeb** | ✅ NVMe (Pro+) | ✅ | ✅ | ✅ | ✅ | ~$42/mo | Viable Fly alternative |
| **DO App Platform** | ❌ none | ✅ | ❌ | ✅ | ✅ | — | **Eliminated** (no volumes) |

### Why each non-Fly option falls short

- **Cloud Run** — No real persistent volume (GCS FUSE only), and the in-memory
  queue + per-instance SSE state break its multi-instance model. You'd pin to a
  single always-on instance, paying Cloud Run's higher per-vCPU rates for none
  of the serverless benefit. Viable only **after** Phase 3.
- **Render** — Solid and simple, but compute is fixed-tier (Standard $25/mo =
  2 GB/1 vCPU) and the Pro workspace adds $25/mo. No scale-to-zero on paid
  plans, so you pay 24/7. Disks at $0.25/GB and egress at $0.15/GB add up fast
  given every image-gen round-trip to Vertex/Reve is billable outbound.
- **Railway** — Best DX of the lot, but per-second always-on (CPU $20/vCPU/mo,
  RAM $10/GB/mo) with no scale-to-zero makes a 2 vCPU / 2 GB app + a 1 vCPU /
  1 GB gateway ≈ $90/mo before any storage/egress.
- **AWS Fargate** — Real EFS (NFS) and full VPC isolation, but you pay for an
  ALB (~$16/mo), NAT gateway (~$32/mo), and per-task IPv4 (~$3.50/mo each) on
  top of compute. High ops overhead (VPC, SGs, ECS task defs, EFS access points).
- **Koyeb** — Closest Fly competitor (NVMe volumes, $0.02/GB egress, 1 TB free).
  Viable, but Pro is $29/mo + compute and fewer regions (Frankfurt/DC). Worth
  keeping as a fallback if Fly reliability disappoints.
- **DigitalOcean App Platform** — **Eliminated**: no persistent volumes for app
  containers, which is a hard requirement here.

---

## 4. Cost modeling at launch scale

Baseline footprint: app (2 shared vCPU / 2 GB, always-on), LiteLLM (1 vCPU /
512 MB–1 GB, always-on), 10 GB volume, ~10 GB egress. Per-second platforms
assume always-on (the in-memory queue can't safely auto-stop while jobs run).

| Platform | App compute | LiteLLM | Volume | Egress | Sub / ancillary | **Total/mo** |
|---|---|---|---|---|---|---|
| **Fly.io** | ~$12 | ~$4 | $1.50 | $0.20 | — | **~$18** |
| **Render (Pro)** | $25 (Std) | $7 (Starter) | $2.50 | $0 (25 GB incl.) | $25 workspace | **~$60** |
| **Railway (Hobby)** | $60 (2cpu/2gb) | $30 (1cpu/1gb) | $1.50 | $0.50 | $5 (−$5 incl.) | **~$92** |
| **AWS Fargate** | $66 | $33 | $3 (EFS) | $0.45 | ALB $16 + NAT $32 + IPs $4 | **~$154** |
| **Koyeb (Pro)** | ~$15 | ~$8 | incl. | $0 (1 TB incl.) | $29 (−$10 incl.) | **~$42** |

### Growth levers

- **Volume dominates over time** — 1–2 GB/project, never auto-cleaned. Fly and
  Railway at $0.15/GB beat Render's $0.25/GB and EFS's ~$0.30/GB. Add a retention
  policy or offload `compose/pages/` PNGs to R2 (the `storage.py` helper exists).
- **Egress** stays cheap on Fly ($0.02/GB) and Koyeb ($0.02/GB, 1 TB free);
  Render's $0.15/GB and Fargate's NAT egress get expensive since every image-gen
  round-trip to Vertex/Reve is billable outbound.
- **Hosting is not the real cost center.** AI provider spend dwarfs it, and
  `launch-readiness.md` already flags `PULP_MODEL_COST_MARKUP=1.0` = **zero
  gross margin** on credits. Fix the margin before optimizing hosting further.

---

## 5. Recommendation: Fly.io (proceed)

The existing `launch-readiness.md` plan is the right shape: two machines on a
6PN private network — `canary-web` (public, TLS, volume, 2 GB) + `litellm-gw`
(private, holds keys, `litellm-gw.internal:4000`), Supabase/Stripe/Sentry as
SaaS. Fly wins on every axis that matters: native persistent volumes, private
networking for the key-holding gateway, per-second billing, cheap egress, and a
Docker-first model that runs the Playwright image as-is. Cheapest by a wide
margin and the only cheap option that doesn't force a refactor first.

### Caveats / get these right on Fly

1. **`--proxy-headers` is now fixed** in the Dockerfile `CMD` (was the P1 #6
   gap). Behind Fly's TLS proxy, this makes secure cookies + client-IP detection
   work.
2. **No `fly.toml` existed** — now extracted from the proposal into a real
   `fly.toml` (canary-web) plus `fly.litellm.toml` + `Dockerfile.litellm` +
   `litellm/entrypoint.sh` for the private gateway.
3. **Single-instance ceiling persists.** `auto_stop_machines = false` is correct
   for launch (in-memory queue can't survive stop); you pay 24/7. Real savings
   unlock only after Phase 3 (externalize queue + move artifacts to R2), at
   which point auto-stop *and* Cloud Run both become viable.
4. **Volume backups.** Fly volumes are single-region, not auto-backed-up. Add
   `fly volumes snapshots` or sync `exports/` to R2 (R2 plumbing already exists).
5. **Langfuse** — don't self-host the 6-container stack on Fly at launch. Use
   Langfuse Cloud or leave it off (app no-ops without it).
6. **GCP creds for litellm-gw** — materialized at startup from the
   `GCP_CREDENTIALS_B64` secret (see `litellm/entrypoint.sh`); never baked into
   the image.

### When to reconsider

- **Outgrow single-region volume / need VPC compliance** → **Fargate + EFS** is
  the natural escalation (real NFS, full VPC isolation), ~$150/mo + ops overhead.
- **After the Phase 3 storage/queue refactor** → **Cloud Run** becomes
  attractive: scale-to-zero + GCS could cut idle cost significantly once the app
  is stateless and storage is object-based.
- **Fly reliability disappoints** → **Koyeb** is the closest drop-in alternative
  (NVMe volumes, cheap egress, scale-to-zero), ~$42/mo.

---

## 6. Deployment artifacts (now in repo)

| File | Purpose |
|---|---|
| `fly.toml` | canary-web app config (public, TLS, volume, 2 GB) |
| `fly.litellm.toml` | litellm-gw app config (private, 6PN only) |
| `Dockerfile.litellm` | Gateway image (bakes in config + handlers) |
| `litellm/entrypoint.sh` | Materializes GCP creds from secret, starts LiteLLM |
| `Dockerfile` (CMD) | Added `--proxy-headers` for behind-proxy secure cookies |

### Deploy order

1. **LiteLLM gateway** (from repo root): `fly deploy --config fly.litellm.toml`
   after `fly secrets set -a litellm-gw` (all provider keys + `GCP_CREDENTIALS_B64`).
2. **Canary web**: `fly volumes create canary_projects --region iad --size 10`,
   `fly secrets set` (Supabase/Stripe/Sentry/LiteLLM gateway key), `fly deploy`.
3. **Verify**: `fly ssh console -a canary-web --command "curl -s http://litellm-gw.internal:4000/health"`.

Status of the remaining `launch-readiness.md` P0/P1 items, as of this branch:

**Closed in this branch** (no longer blocking):

- Upload size cap + `MAX_PROJECTS_PER_USER` — `projects.py` has `_save_upload_capped`
  and `_max_projects_per_user()` (env `CANARY_MAX_PROJECTS_PER_USER`, default 25).
- Billing-test fix (P1 #5) — `test_image_failure_meta.py` + `test_usage.py` updated
  for the Nano Banana 2 Lite (`gemini-3.1-flash-lite-image`) pricing.
- `--proxy-headers` in the Dockerfile CMD (see §5 #1).
- Cookie `secure` from env flag (P1 #6) — `auth.py::_cookie_secure` honors
  `CANARY_COOKIE_SECURE=true`.
- Labs gate — `CANARY_LABS_ENABLED=false` in `fly.toml`.
- **Rate limiting** — `slowapi` configured; throttles project create, `/pipeline/run`,
  and the full `*/regen*` family (10 routes) via `cost_limit` (env-tunable). *Note:*
  there is no backend login endpoint to throttle — Supabase issues JWTs client-side,
  so the "auth" part of "auth/create/run/regen" is moot; the abuse surface is the
  credit-gated API, which is now covered.
- **Sentry** — backend `configure_sentry()` is now called at the top of `_lifespan`
  in `server/app.py` (no-op without `SENTRY_DSN`, runs before the pricing audit so
  startup errors are captured); frontend was already wired (`web/src/sentry.ts`).
- **Readiness probe** — `GET /api/health/ready` now pings both Supabase **and**
  LiteLLM (`/health/liveliness`, 2 s timeout); `fly.toml` check path flipped to
  `/api/health/ready` so Fly's LB uses the deepened probe.
- **`verify_aud`** (P1 #6) — now enforced by **default in production**
  (`CANARY_ENV=production` → audience `"authenticated"`, Supabase's standard claim),
  with `SUPABASE_JWT_AUDIENCE` as an explicit override and empty-string opt-out.
  Dev/test unchanged (no audience check).
- **Legal / content-safety posture (P0 #4)** — three templated legal pages
  (`/legal/{terms,privacy,acceptable-use}`) wired as public routes, linked from
  the footer + signup + checkout; abuse/DMCA channel via
  `mailto:legal@scenewright.ink`; Stripe checkout now passes
  `terms_of_service_url` + `consent_collection` (and the line-item name is
  `Scenewright`, not `Pulp`). Brand + contact identifiers centralized in
  `server/branding.py` + `GET /api/branding`. See `launch-readiness.md` §4 for
  the locked moderation stance (rely on provider filters + reporting; no input
  gate) and the operator to-dos (monitor `legal@`, set `SCENEWRIGHT_TERMS_URL`).

**Still open:**

- CI/CD (GitHub Actions) — no `.github/workflows/` yet.
- Credit-margin confirmation — `PULP_MODEL_COST_MARKUP` still defaults to 1.0 (P1 #9).
