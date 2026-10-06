# Canary — Deployment platform decision

**Status: Current repository architecture assessment, September 9, 2026;
restart, queue, and edge facts refreshed September 25, 2026.**
Supersedes the July 2 comparison as operational guidance. External platform
prices and account state were not rechecked here. The original July cost table
was based on a retired two-app architecture; its ~$18/month total must not be
used as a current budget or purchasing comparison.

For the October 6 AWS migration request, see the proposed
[Lightsail migration design](aws-lightsail-migration.md), including newly
verified AWS prices and corrections to queue/release evidence below. It does
not change the deployed platform.

## Decision

Keep the checked-in Fly deployment for the first bounded self-service launch.
The fastest path to lower operator workload is to exercise recovery, alerting,
backups, and release automation on the current architecture. A platform move
would leave the same application coordination and billing requirements to solve.
This is a fit assessment of the existing implementation, not a claim that Fly
is the cheapest or only suitable provider.

## What actually runs

| Component | Current contract |
|---|---|
| Fly app | `canary-web`, primary region `iad`; one Machine, shared 2 CPU / 4 GB in `fly.toml` |
| Public app | One uvicorn application worker, bundled React SPA and FastAPI API/SSE on port 8000 |
| Model gateway | LiteLLM subprocess on loopback port 4000, installed in a separate dependency environment; bounded child-process restart in `litellm/entrypoint.sh` |
| Persistent data | `/projects` mounted from `canary_projects`: source, stage artifacts, page revisions, Draw paid-result recovery records, durable request/job journal and operation outbox; daily snapshots, 14-day retention, auto-extend declared in `fly.toml` |
| Generation queue | Dedicated PostgreSQL (`CANARY_QUEUE_DATABASE_URL`) for Procrastinate dispatch; required for generation admission. Production provisioning is not yet recorded |
| Edge | Cloudflare proxies `scenewright.ink`; `canary-web.fly.dev` remains directly reachable |
| External services | Supabase auth/database, Stripe billing, optional Sentry and finalized-export R2 delivery |
| Pipeline | `extract → brief → style → cast → adapt → plan → draw → finish`; complete lettered pages, not panel composition |
| Release | Manual `CI` dispatch on `main`, exact-source-SHA test/build gates, authenticated drain, deployment and public verification; database changes remain separately reviewed operations |

Provider credentials are network-private: the gateway is not publicly exposed.
Both processes inherit the container environment; separate dependency
environments do **not** provide process-level secret isolation.

Operations are dispatched through the PostgreSQL queue but executed by the
single API process that owns the volume lock. Queued operations survive restart
and resume; operations that had started become `outcome_unknown` rather than
being replayed. New Machines or application
workers would bypass process-local project locks and drain coordination.
Horizontal scaling therefore needs distributed admission/coordination and a
shared artifact design before changing instance counts.

R2 currently distributes finalized exports. It does not replace the private
artifact store, request journal, database backup, or recovery backup. Do not
publish author sources or in-progress imagery in a public export bucket.

## The material hands-off gap

`fly.toml` sets autostop off, autostart false, and restart policy `on-failure`
with three retries, backed by the entrypoint's persisted crash budget
(`/projects/.ops/recovery.json`). Deliberate stops remain stopped; a crash gets
bounded automatic recovery, after which an operator must diagnose. LiteLLM
restarts within its own bounded child budget. The routing check uses local
`/api/health`; separately monitor `/api/health/ready` for dependencies.

Before claiming unattended availability, exercise that bounded crash recovery
in production (it is configured, not yet evidenced), confirm it distinguishes
maintenance from failure, retains journals, and does not replay ambiguous paid
submissions. Couple it with alert delivery
and backup restoration. See the concrete acceptance gates in
[launch readiness](launch-readiness.md).

The release pipeline reduces manual work but is not unattended CD: it needs a
human dispatch/maintenance decision and manually applied database changes.
Manual release workflows now have unique concurrency groups with cancellation
disabled; actual deployment jobs remain serialized, with pending requests queued
instead of replaced (up to GitHub's 100-pending-job limit). This configuration
still needs a production exercise. The release image is built once before
draining, pushed as `registry.fly.io/canary-web:<sha>`, smoke-tested, and
deployed with `flyctl deploy --image`; the rollback target is the previous
release's image reference (`flyctl releases --image`).

## Cost and capacity inputs to collect

Budget from the actual current bill and measured full-page projects:

- always-on 4 GB Machine compute, allocated storage, snapshot/independent-backup
  retention, data transfer, database/auth, SMTP, and monitoring;
- median and high-percentile bytes per project including references, complete
  page revisions, saved OCR/provider evidence, and exports;
- queue wait and peak memory under concurrent author sessions and export work;
- actual provider usage, failed/ambiguous calls, corrections, OCR, fees, refunds,
  and operator time per successful customer export.

The markup is `PULP_MODEL_COST_MARKUP=2.0` with
`PULP_CREDITS_PER_PROVIDER_USD=100` in Fly configuration. That does not prove
net margin or settle whether any pack covers a fixed page count; use the
[pricing decision](pricing-and-margin.md) and recorded project actuals.

Measure storage before setting retention or capacity claims. No current volume
size, usage, snapshot schedule, deployed image, or monthly bill was inspected
for this review. July and later runbook observations are historical until
confirmed in a release evidence record.

## When a platform review becomes useful again

Reopen the hosting decision when measured queue wait, storage/recovery needs,
regional requirements, incident frequency, or operational spend cannot meet the
chosen service level on the existing setup. At that point compare current
provider documentation and quotes against an explicit workload, including
migration and operator time. Do not reuse the July assertions about competitors'
volumes, networking, scale-to-zero, or prices as current facts.

Scaling to multiple Machines requires application work regardless of provider.
For now, the operational source of truth is
[the deploy runbook](../deploy.md); executable artifacts are `fly.toml`,
`Dockerfile`, `litellm/entrypoint.sh`, `.github/workflows/ci.yml`,
`scripts/check_deploy_safe.py`, and `scripts/verify_deployment.py`.
The retired `fly.litellm.toml` and `Dockerfile.litellm` are not deployment inputs.
