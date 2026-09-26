# Simplify production telemetry and tracing

Implementation follow-up: the user authorized consolidation without a separate
synthetic-journey gate. See the [current operating guide](../reference/observability.md)
for implemented behavior and remaining activation steps. This research records the
decision basis, not evidence that cloud delivery is live.

**Status: Proposed.** September 26, 2026. Based on repository inspection at
`c0ffdf7` and current primary-source vendor research. This expands the
[launch learning plan](2026-09-26-launch-learning-system.md). No services,
instrumentation, credentials, or deployment settings were changed during this
investigation. Production delivery and account entitlements remain unverified.

## Current recommendation and scope of this earlier plan

The [single-vendor follow-up](2026-09-26-posthog-single-vendor.md) is the current
preferred proposal: **PostHog for application analytics, errors, logs, and AI
observations, with standard OTel for general traces/logs**, subject to the
specified integration proof. General tracing is shipped but alpha. Preserve
Fly monitoring, independent operation checks, and first-party recovery data.

This earlier plan retains the repository audit and shared operation, privacy,
and recovery contracts. **Its Sentry-specific architecture and migration below
are the fallback if the PostHog proof fails**, not a second simultaneous
implementation. In the preferred PostHog path, simplify and retain OTel;
do not follow the fallback's instruction to replace it with native Sentry.

The practical target remains: given a support reference, find the operation,
see where its time went, identify the failing phase/provider call, check whether
art was saved and credits settled, and follow the associated feedback. Sampled
telemetry never becomes billing or recovery authority.

## What the audit found

| Path | Observed implementation | Problem to solve |
| --- | --- | --- |
| Langfuse | [Compose](../../docker-compose.yml) contains six Langfuse services: web, worker, Postgres, ClickHouse, Redis, and MinIO. [dev.sh](../../scripts/dev.sh) starts them only with `--observability`. | Optional already, but substantial infrastructure for one developer to operate when debugging. Do not move this stack onto the production Machine. |
| Custom AI export | [ai/client.py](../../novel_to_comic/src/novel_to_comic/ai/client.py) builds direct Langfuse ingestion batches for start/end/cost, with calls also threaded through [image finalisation](../../novel_to_comic/src/novel_to_comic/ai/finalisation.py). | Vendor-specific payload plumbing is mixed into billing-sensitive lifecycle code. Fire-and-forget HTTP work is not a durable observation record. |
| Trace identity | Langfuse's `trace_id` is a request ID or per-call event ID. [StageRuntime](../../novel_to_comic/src/novel_to_comic/stage_runtime.py) creates separate OTel spans; [API logging](../../novel_to_comic/src/novel_to_comic/clients/api_logging.py) deliberately skips provider spans for common LLM routes. | The IDs do not establish one connected execution trace. A provider dashboard can show calls without explaining the user operation that caused them. |
| Queue context | [JobCommand](../../novel_to_comic/src/novel_to_comic/server/job_commands.py) has no tracing envelope; [job execution](../../novel_to_comic/src/novel_to_comic/server/job_execution.py) restores account/stage context without a general originating request/trace context. | ContextVars and HTTP instrumentation alone cannot reconnect work restored from a durable queue or process restart. |
| Production OTel | [telemetry.py](../../novel_to_comic/src/novel_to_comic/server/telemetry.py) has a separately configured provider/exporter. [Fly](../../fly.toml) disables it and [Docker](../../Dockerfile) installs `web`, not the `otel` extra. | Local tracing behavior is not production tracing coverage. Turning on an environment flag alone would not fix this. |
| Sentry | Backend (historical Sentry integration) and frontend (historical Sentry integration) support errors and sampling controls. Explicit worker/provider lifecycle spans, centralized structured log delivery, and durable queue propagation were not found. | Build on the existing SDKs rather than introduce a second operational platform. Frontend trace sampling configuration by itself does not prove browser tracing integration. |
| Logs | [Server logging](../../novel_to_comic/src/novel_to_comic/server/logging.py) uses Rich text and raw request paths. [Local diagnostics](../../novel_to_comic/src/novel_to_comic/server/diagnostics.py) append `.canary/diagnostics.jsonl` only when explicitly enabled outside production. | Useful console output exists, but there is no consistent structured correlation envelope across all records. Local journals are intentionally unavailable as the production debugging solution. |
| Sensitive fields | Langfuse input/output are redacted by default, but metadata includes project name/workspace path and error strings. Backend Sentry config has `before_send`, not dedicated transaction/log scrub hooks; frontend filtering is narrower. | Default prompt redaction does not establish that every export is content-free. Centralize the allowlist before increasing collection. |
| Financial and recovery evidence | AI usage updates, credit ledger, operation journal, saved requests, checkpoints, OCR responses, and pending paid results already serve different purposes. AI usage insert/update failures can be logged without stopping settlement. | Preserve these boundaries. Even the usage table is not guaranteed to contain every observation; reconcile it with ledger and saved-result evidence. Missing telemetry is not proof of no charge. |
| Existing monitor | [monitor_operations.py](../../scripts/monitor_operations.py) and the [recovery runbook](../ops/crash-recovery.md) cover domain incidents and require independent hosting. | Preserve checks for a dead/stuck worker and ambiguous outcomes; exception capture alone cannot detect a silent process or all domain failures. |

The older [activation research](observability-live-activation.md) says frontend
release injection is missing. Current Docker source supplies it; retain and
verify that plumbing. Source-map upload was not found in the inspected Vite/CI
configuration and should be part of the replacement verification.

## Sentry fallback: keep, replace, and retire

| Component | Proposed action |
| --- | --- |
| Sentry | Expand to the single application errors/traces/logs destination; retain separate frontend/backend service identities and a shared release. |
| PostHog | Keep curated product events, cohorts, feedback metadata, and learning reports. Do not duplicate every operational log or provider span here. |
| Langfuse HTTP exporter and associated call parameters | Replace with narrow vendor-independent operation/provider observation helpers backed by Sentry. Remove only the telemetry plumbing; preserve usage settlement and paid-result handling. |
| Local Langfuse Compose services and launcher flag | Retire after synthetic parity checks. Preserve existing volumes until the owner chooses archival/deletion; no automatic `down -v`. Keep LiteLLM and its database and the durable queue database. |
| Standalone OTel provider/exporter and legacy API-span map | Retire once their useful coverage has moved to the chosen Sentry integration. Avoid two competing tracer providers. OTel concepts remain useful; a separate collector is not required for this launch design. |
| Rich terminal logging | Keep as the development presentation of the same safe structured fields. Production writes JSON stdout and selected structured application logs to Sentry. |
| Per-project diagnostic JSONL | Keep only as explicit local debugging if still needed, with bounded retention. Production support must not depend on it. Remove duplicate records only after demonstrating that useful context survives elsewhere. |
| Fly metrics and stdout | Keep built-in CPU/memory/disk/process metrics and a small aggregate app dashboard. These are platform diagnostics/fallback, not another maintained application trace backend. |
| Application state and paid recovery files | Keep. They are required data, not optional telemetry. Expose safe summaries and provenance through the operator surface. |

Do not create a general observability event bus, a trace database, or a new
self-hosted collector/log/search stack. A small context type, safe field
projection, existing logging integration, and explicit span hooks are sufficient.

## A shared context across the entire operation

Separate identities by meaning, then carry them consistently:

| Field | Meaning |
| --- | --- |
| `request_id` | One HTTP exchange; server-issued/validated and returned for support. Do not treat an arbitrary client header as trusted identity. |
| `operation_id` | The durable admitted customer action. Reuse the existing operation/job identity; map any separate ledger job ID explicitly. |
| `execution_attempt_id` | One execution or explicit recovery attempt, when distinct from the operation. Never use it to bypass paid-action replay protection. |
| `provider_call_id` | Existing immutable usage/call identity for a real provider invocation; separate calls in a batch have distinct IDs. |
| `trace_id`, `span_id` | Tracing SDK identities. Never substitute a request UUID, project name, or input hash. |
| `project_id`, `page_number`, `stage`, `operation_kind` | Bounded product context for diagnosis. No title, entity name, manuscript, instruction, or workspace path. |
| `analytics_id`, `environment`, `release` | Same opaque account mapping and provenance as the product analytics plan, subject to the signal's privacy purpose. |

Persist a small validated tracing envelope when admitting a job: originating
request ID, operation correlation, and the chosen SDK's trace propagation
fields. Restore it under an isolated task context when the worker executes.
Propagate to application-to-gateway requests where supported; never attach
arbitrary baggage or customer context to third-party provider calls.

A project can take days and should not be one transaction. Trace each admitted
action and its units of work; link later independent operations by project and
operation IDs. For delayed execution and restart recovery, use a linked worker
trace rather than hold an HTTP span open. Verify how the chosen Sentry SDK/UI
represents those links. OTel explicitly supports causal links between separate
asynchronous traces. [Trace concepts](https://opentelemetry.io/docs/concepts/signals/traces/)

An example diagnostic view should distinguish:

```text
Request: generate page 3
  validate → admit → enqueue                         request trace
  queued 38s                                        durable timestamps
Worker operation: page_draw                         linked execution trace
  acquire account lane / credit hold
  compile request
  provider image call                               provider_call_id
  persist image and recovery evidence
  OCR/read-back                                     separate provider_call_id
  settle credits / acknowledge saved result
  publish terminal outcome
```

Use existing StageRuntime hooks for stage observation, queue/admission hooks for
operation observation, and centralized AI start/finalisation hooks for provider
calls. Do not instrument every function or introduce a parallel stage lifecycle.
Label queue wait, execution, provider latency, validation, storage, and settlement
separately. Long batches should contain bounded unit traces/spans; validate SDK
duration/size limits with a synthetic long-running fixture before relying on
complete waterfalls.

Capture domain status, not merely HTTP or scheduler status. The
[queue contract](../reference/job-queue.md) explicitly permits a successful
dispatch that recorded a failed operation. Distinguish art saved/OCR failed,
provider outcome unknown, credit block, cancellation before execution, and
successful completion. An infrastructure timeout does not prove a paid provider
submission failed. A retry event must describe what actually retried.

## Logs and AI metadata that answer useful questions

Standard production log fields: timestamp, severity, stable event name, service,
release/environment, correlation IDs, phase/outcome, safe error code, and numeric
duration. Use canonical route templates. Omit polling/asset successes and token
stream chunks. Emit one meaningful start/terminal record per operation and
provider call, plus exceptional transitions. Avoid exporting duplicate logs via
both an SDK handler and a stdout shipping integration.

Provider observations should include configured model alias, actual provider
model, feature, operation type, duration, token/image counts, attempt outcome,
funding mode, and cost provenance. Show provider-reported cost, configured-price
calculation, estimate, and unknown cost as distinct. Keep unknown as unknown,
not zero. Credit holds and charged credits are separate fields and remain
ledger-owned. Do not let a vendor's model-price catalog overwrite Canary's
fixed-edition pricing/configuration authority.

Custom gateway and image routes need explicit instrumentation. Successful text
SDK auto-instrumentation would not prove coverage of image generation, raw
HTTP, local development adapters, OCR, or settlement. No new AI gateway is
needed to collect this evidence.

Default exported observations exclude all prompt/completion bodies, images,
local file paths, signed URLs, free-form error/provider text, and function
locals. Preserve safe exception type, static stack locations, error code and
fingerprint so failures remain actionable. Apply policy to exceptions, logs,
breadcrumbs, transactions/spans, browser URLs, and automatic integrations—not
just one error hook. Failed sanitization emits a minimal safe record or drops
the payload; it must not export the original unsanitized record.

Replace the ambiguous global prompt logging flags with an explicitly local
debug mode that cannot enable production export. Access to exact saved inputs
or provider evidence remains an authorized operator action against the project,
not an automatic attachment to a vendor error. Keep replay off.

## One operator workflow

Add a small **operation detail** view to the existing backoffice, not a custom
trace viewer. Search by support/request/operation ID; show authoritative status,
queue/execution times, page/artifact availability, settlement/unknown-cost
state, and links to the associated Sentry trace/error/log query and PostHog
journey. Include feedback context and existing recovery instructions. Link to
existing operator APIs; do not place service keys or unrestricted file access
in the browser.

Three initial views are enough:

1. **Needs attention:** ambiguous paid outcomes, settlement mismatch, stopped
   workers, repeated actionable failures, and feedback needing review.
2. **Operation detail:** what happened, where time went, what was saved, what
   was charged, and the safe next action.
3. **Weekly learning:** journey conversion and recurring friction, as defined
   in the analytics proposal.

A missing trace must display “not captured / expired / delivery unavailable”
when known, never imply no operation occurred. The authoritative operation
summary should work while Sentry or PostHog is down.

## Alerting, cost, and production behavior

Start with a small actionable alert set: unhandled customer-affecting errors,
unavailable service/worker, stuck execution beyond its operation-specific
deadline, ambiguous paid results, and unresolved settlement failures. Suppress
normal review waits, expected insufficient-credit responses, and polling noise.
Group incidents by stable fingerprint and record resolution rather than sending
a new notification for every retry or repeated check.

Keep an independent uptime/domain monitor; a crashed Machine cannot reliably
report its own absence. Reuse the existing incident state machine and adapt its
delivery to the selected operator channel instead of building another incident
queue. Verify no accidental duplicate Sentry log/error notifications. Do not
assume a Fly dashboard sends alerts: managed Fly metrics currently has no
built-in alerting. [Fly metrics](https://fly.io/docs/monitoring/metrics/)

For a small launch cohort, initially capture bounded generation-operation
traces at 100%, sample ordinary successful HTTP/browser navigation, and exclude
polling. Independently capture actionable errors. Head sampling cannot recover
an unsampled trace after it fails; do not promise “all failures have full
traces.” SDK delivery, quotas, crashes and long-transaction limits still apply.
Measure volume/overhead before tuning rates. Prefer short retention for raw
operational telemetry and long-lived redacted learning summaries; confirm each
vendor's actual retention and deletion controls before activation.

Use bounded SDK buffers, short network timeouts, graceful flush within the
existing shutdown budget, drop counters, and a delivery health indicator.
Observability outage must not block application startup, saturate the AI HTTP
client, prevent paid-result settlement, or trigger provider retries. Do not
make tracing failure equivalent to failure of the durable usage/credit/recovery
path. Add no durable local trace spool for launch: durable business outcomes
already have recovery sources, while diagnostic traces may be lossy.

## Migration sequence and acceptance

Planning estimate: **4–7 additional focused developer days**, with overlap in
the analytics plan's event identity, outcome, and backoffice work. Re-estimate
the combined work after the instrumentation proof; do not simply add both
estimates. This is a scope estimate, not a promised launch date.

| Slice | Work | Evidence before moving on |
| --- | --- | --- |
| 1. Instrumentation proof | One provider-free API → durable queue → worker → fake text/image call → saved-result → fake settlement journey using Sentry native instrumentation, plus structured logs. | Correlation survives queued restart and concurrent users; image/partial/unknown outcomes are visible; logs/errors/trace can be found together. No Langfuse dependency. |
| 2. Shared context and policy | Persist tracing envelope outside creative input hashes; canonical identities, allowlisted fields, release and source-map plumbing. | Seeded secrets/manuscript/path/error strings never leave via any signal. Foreign baggage is excluded. Telemetry changes do not alter model requests or paid deduplication. |
| 3. Migrate hooks | Move stage, operation, AI and log observation to the chosen adapter; wire safe task scopes and delivery lifecycle. | Mocked success, refusal, cancellation, timeout, output-save failure, OCR failure, and settlement failure retain correct domain outcomes and existing recovery behavior. |
| 4. Operator usefulness | Operation detail with links, actionable alerts, independent monitor delivery, collection health and budget checks. | Diagnose a synthetic customer failure from one reference without shelling into production. Missing vendor data is explicit. Alert receipt and dedup verified. |
| 5. Retire duplication | Remove custom Langfuse payload plumbing, separate OTel exporter, obsolete flags and optional Compose/launcher services; update docs/tests. | Test runs and local development need no telemetry infrastructure. Runtime behavior is intact with all vendor credentials absent. Existing data/volumes are preserved. |

The proof is a hard decision gate: if Sentry cannot render the custom worker and
image path with safe metadata and tolerable overhead, revise the choice before
migrating the rest. Do not keep a permanent Langfuse/Sentry/PostHog triple trace
export to compensate for an untested integration.

Use targeted logging, observability, AI finalisation, queue, isolation, and
credit/recovery tests; broaden because this crosses shared execution contracts.
Use captured outbound envelopes and fake providers for correctness. A synthetic
event delivered to the chosen hosted account verifies delivery separately; no
paid AI generation or real manuscript is needed. Activation also requires
real retention/region/budget settings and an alert-receipt check.

Implementation should update `ops/README.md`, deployment guidance, and the older
observability proposal together. Until then, those documents describe the
existing configuration; this proposal does not claim the overhaul is deployed.
