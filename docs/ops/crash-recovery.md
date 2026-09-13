# Crash recovery and actionable exceptions

Status: Current repository procedure. Local tests are not deployed verification.

This remains one Fly Machine, one uvicorn worker, and persistent `/projects`.
Process recovery never dispatches paid work. Request journals, durable jobs,
usage events, credit holds, saved page results, and creative checkpoints remain
authoritative.

## Recovery boundaries

Unexpected nonzero container exits use Fly's bounded `on-failure` policy.
Intentional SIGTERM/shutdown exits successfully; `auto_start_machines = false`
keeps deliberately stopped Machines stopped. Deployment drain and maintenance
intent persist in the request journal across process replacement. A restart does
not reopen admission. Keep `/projects` mounted and retain its hidden files.

The entrypoint persists its own crash budget in `/projects/.ops/recovery.json`.
It permits three recovery attempts with default delays of 2, 4 and 8 seconds;
the budget resets only after 300 seconds of continuously healthy web liveness.
Fly separately permits at most three `on-failure` retries within five minutes.
Exhaustion stops recovery and requires diagnosis. The external monitor alerts
on both unavailability and observed exhausted recovery budgets.

`CANARY_RESTART_LIMIT`, `CANARY_RESTART_BACKOFF_SECONDS`,
`CANARY_RESTART_BACKOFF_MAX_SECONDS`, and `CANARY_RESTART_STABLE_SECONDS`
configure the application budget. `CANARY_WEB_READY_TIMEOUT_SECONDS` defaults
to 60 seconds for initial local web liveness; `CANARY_HEALTH_HOST` must be an
allowed application host (production defaults to `canary-web.fly.dev`). The
initial proxy wait is 60 seconds plus at most a three-second probe overrun.
Allow up to 150 seconds from supervisor start for the default third-attempt
backoff, initial proxy wait, web startup and polling overhead. A web process
that never becomes live fails that attempt; a dependency outage instead leaves
diagnostics running and readiness failing. Fly scheduling and public routing
add platform latency, so validate the end-to-end recovery window during activation.
Keep the application and Fly limits aligned;
a platform stop can exhaust recovery before application status records the last
attempt. Web liveness is not dependency readiness. Dependency outages leave the
web diagnostic API available and admission closed when required. LiteLLM retains
its existing bounded child recovery; an unavailable gateway must not create an
endless Machine restart cycle.

Credit-lease initialization retries every 30 seconds behind closed paid admission,
while liveness remains available. The existing lease manager's failed renewal or
90 seconds without a successful renewal makes readiness fail and prevents new
admission. Recovery of that manager restores dependency readiness, but never
clears an operator's durable drain.

## Maintenance and reopening admission

1. Establish the exact release and maintenance reason. Authenticate
   `POST /api/ops/drain` with `X-Canary-Ops-Token` and wait for
   `draining: true` and `safe_to_deploy: true`. Timeout leaves the service
   drained; it never grants permission to terminate paid work.
2. Preserve the journal, artwork and recovery state. Use a deliberate Fly stop
   only after drain is safe. Do not kill the process to simulate maintenance:
   an unexplained kill is a crash and consumes the restart budget.
3. After maintenance, explicitly start the Machine. Confirm the release and
   dependency readiness; inspect `GET /api/ops/exceptions` and interrupted jobs.
   A liveness success alone does not authorize customer admission.
4. Authenticate `POST /api/ops/resume` only after the operator has completed
   those checks. Resume requires dependency readiness and explicitly clears the
   durable drain. It does not replay interrupted work or approve checkpoints.

## Independent monitoring and notification activation

Run `scripts/monitor_operations.py` on an independently supervised host outside
this Fly Machine, with persistent storage for its SQLite database. A watchdog
inside the application container cannot report a dead container. Configure the
host's service manager to restart the monitor, retain its database, and alert on
monitor failure; this application change does not provision that external host.

First activate queue-only observation, with no webhook configured:

```sh
export SCENEWRIGHT_MONITOR_URL=https://canary-web.fly.dev
# Supply SCENEWRIGHT_OPS_TOKEN through the host's restricted secret store.
python3 scripts/monitor_operations.py --database /var/lib/scenewright/operations.sqlite3 --interval 30 --outage-seconds 60 --readiness-seconds 300
```

The token matches the application's `CANARY_OPS_TOKEN` but has a different
monitor environment variable name. Probe failures are persisted across monitor
restarts. Defaults require 60 seconds of failed availability or 300 seconds of
failed readiness before opening an incident; polling and HTTP timeouts add
detection latency. An unavailable or incomplete exception snapshot never
resolves unseen internal incidents. A stopped application can still produce an
availability incident without access to its diagnostic API.

Inspect the durable queue on the external host:

```sh
python3 scripts/monitor_operations.py --database /var/lib/scenewright/operations.sqlite3 --queue
```

Each incident carries stable identity, first/last observation, release, severity,
affected IDs when known, credit state when relevant, safe action, and diagnostic
and runbook links. Notification versions change for meaningful state, severity,
release, or resolution changes; age/count jitter alone does not create another
notification. Unresolved incidents persist across polling and process restarts.
The queue's delivery records expose pending sends, attempts, next retry, and
`delivery_failed`; inspect these even when notification delivery is broken.

Only after explicit authorization, configure `SCENEWRIGHT_ALERT_WEBHOOK` with
an HTTPS receiver that accepts the JSON incident envelope. No webhook means no
live notifications. Delivery uses bounded exponential backoff and an
`Idempotency-Key` per incident version; the receiver must deduplicate that key
because a lost delivery response can cause a repeated send. Verify notification
receipt and resolution in an authorized activation exercise.

Before a deliberate outage, mark a bounded maintenance window **on the external
host**, separately from application admission drain:

```sh
python3 scripts/monitor_operations.py --database /var/lib/scenewright/operations.sqlite3 --maintenance-seconds 3600
# Once maintenance has finished and admission is ready:
python3 scripts/monitor_operations.py --database /var/lib/scenewright/operations.sqlite3 --end-maintenance
```

Maintenance suppresses expected availability/readiness alerts until its deadline,
then escalates overdue maintenance. It does not suppress paid-work reconciliation
or change Machine state. Never leave an indefinite outage exemption.

After reconciling an orphaned action whose historical journal must remain
immutable, operators may acknowledge its incident with `--resolve <incident-key>
--reason reconciled`. Supported reasons also include `customer_contacted` and
`expected_stop`; select the factual reason and retain supporting operator notes.
This suppresses an unchanged historical observation, not a new escalation. It
does not modify job, ledger, admission, or provider state.

## Crash-loop handling

Keep admission drained. Inspect Machine state, release, recovery status,
dependency readiness and storage before changing the restart budget. Fix the
specific cause; do not keep resetting a dependency outage or configuration error.
When a shell is available, `python /app/recovery.py reset` resets the crash budget
only. For a stopped Machine, configure a new unique, nonsecret
`CANARY_RECOVERY_RESET_ID` on that Machine through the authorized Fly control
plane and explicitly start it. The entrypoint remembers the token and consumes
it once, so leaving that value configured cannot create unlimited resets. This
reset preserves journals and maintenance intent. Verify actual health and release
before explicitly resuming admission; leave ambiguous work for reconciliation.

## Reconciliation and safe actions

Use [failed generation recovery](failed-generation-recovery.md) for individual
jobs. Never automatically replay an ambiguous image request, globally release
holds, or treat an issue's new revision as verification. Customer-authorized
spend, provider-free saved-evidence recovery, and operator ledger reconciliation
are distinct operations.

The authenticated exception snapshot contains sanitized IDs, release, evidence,
credit state, and a recommended safe action. Defaults identify progress stalled
for 1,800 seconds, three failures in 3,600 seconds, and storage at 85% utilization
or below 2 GiB free. Configure `CANARY_OPS_STALL_SECONDS`,
`CANARY_OPS_FAILURE_COUNT`, `CANARY_OPS_FAILURE_WINDOW_SECONDS`,
`CANARY_OPS_STORAGE_PERCENT`, and `CANARY_OPS_STORAGE_FREE_BYTES` for actual
production latency and volume capacity. Progress timestamps take precedence over
start time when available; a long-running stage with recent progress is not
stalled solely because it is old. Started expired holds and ambiguous usage
remain visible for inspection; alerts do not mutate the ledger.

An ambiguous bounded image submission (disconnect, cancellation, or gateway 5xx)
retains its existing credit hold. A successful HTTP response whose image cannot
be decoded also requires inspection; success at the HTTP layer alone does not
prove saved output or settled usage. Do not release these holds to clear an alert.

Snapshot action IDs hash `account + NUL + route + NUL + idempotency-key` with
SHA-256 and retain the first 24 hexadecimal characters. Operators can compute
that value locally while inspecting the restricted journal to correlate an
incident; do not publish the account or raw request body. Project names, raw
errors and creative payloads are deliberately excluded from notifications.

## Local fault injection and evidence limits

From the repository root, without production credentials or network access:

```sh
novel_to_comic/.venv/bin/python -m pytest novel_to_comic/tests/test_crash_fault_injection.py -q
novel_to_comic/.venv/bin/python -m pytest novel_to_comic/tests/test_server_admission.py novel_to_comic/tests/test_complete_page_draw.py novel_to_comic/tests/test_page_recovery_routes.py novel_to_comic/tests/test_page_finishing.py -q
novel_to_comic/.venv/bin/python -m pytest novel_to_comic/tests/test_entrypoint.py novel_to_comic/tests/test_operations.py novel_to_comic/tests/test_operations_monitor.py -q
```

The first command launches disposable child processes that terminate with
`os._exit(73)` before submission, after submission before response, after saved
Draw output before settlement, and during PDF packaging. It verifies durable
HTTP deduplication after restart, interrupted job visibility, unchanged holds,
retained image/provenance bytes, and offline export rebuilding. The provider and
ledger are explicit local doubles; the SQLite journal and page artifacts are
real. These tests prove that recovery does not invoke another submission/debit
or release a hold; they do not prove a production provider's accounting outcome.
Existing publication tests also prove saved paid results can be recovered without
a second image submission.

The monitor test opens only a loopback HTTP server and mocks notification
delivery. It then stops that server completely and checks that an external
availability incident opens. A restricted development sandbox may require local
socket permission. See [recorded local verification](crash-recovery-local-verification.md)
for this change's results and remaining activation checks.

Run `novel_to_comic/tests/test_credit_ledger_postgres.py` against an isolated
PostgreSQL database provisioned with `docs/supabase-schema.sql`, explicitly
setting `CREDIT_TEST_DATABASE_URL`. Never point this test at production. It
checks settlement response loss, immutable call identity, owner isolation and
started expired holds. Without that database the tests skip; record skips as
missing database evidence rather than a successful ledger verification.

Production activation requires a separate authorized release and maintenance
window. Record the actual release, Fly policy, persistent volume, ordinary-crash
recovery duration, deliberate-stop behavior, dependency outage behavior,
crash-loop escalation, external alert delivery, deduplication and resolution.
Local subprocess exits do not establish Fly scheduling/restart latency or live
notification delivery. No provider spend is necessary for these infrastructure
checks; any customer generation smoke test requires separate explicit spend
consent.

## Expired hold isolation

Apply `docs/sql/2026-09-11-reservation-isolation.sql` to existing databases.
The canonical schema includes the same change. Started or legacy expired holds
remain deducted from available credit and require explicit reconciliation; they
do not veto unrelated reservations when the account has sufficient balance.
An expired job still fails its ownership/lease check and cannot resume paid work.
Never release an uncertain hold simply because it expired.

If the live database still returns `Expired credit reservation requires
reconciliation`, reservation admission reports a maintenance error before any
model call and logs the migration path. Story also recognizes the previously
saved raw error. Changing models or recreating projects cannot repair this
database rule. Deleting a project clears ledger project links; it does not erase
charges or release uncertain holds. The PostgreSQL regression tests cover
deletion followed by recreation with the same project name.

Vertex terminal image policy refusals return HTTP 400 rather than HTTP 500.
This prevents a known refusal from being retained as an ambiguous submission.
Unknown empty responses, transport timeouts and server failures still retain
their holds. Provider-cost evidence remains separate from reservation release.

Both gateway Docker builds apply `litellm/patch_http_errors.py` to the pinned
LiteLLM version. Without it, masking a multipart HTTP error reads an unread
upload stream and replaces the provider's rejection with `RequestNotRead` /
HTTP 500. The patch preserves the original response status and body without
reading or resending the upload. Run `litellm/test_http_errors.py` inside the
built gateway with networking disabled to verify this boundary. Old masked
failures still require reconciliation; this patch does not release their holds
or retry images automatically.
