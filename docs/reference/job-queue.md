# Durable generation queue

**Status: Current implementation.** Verified with provider-free tests, including
an isolated PostgreSQL 17 instance. Production deployment is a separate operation.

## Ownership and execution

The API lifespan runs a Procrastinate worker beside the artifact volume. PostgreSQL
owns dispatch, FIFO account locks, worker heartbeats and stalled-dispatch recovery.
A transactional outbox in the volume's `.request-journal.sqlite3` stores the
versioned command and author-visible operation outcome together. Dispatch contains
only the operation ID. Large page inputs are content-addressed under each project's
`.jobs/inputs/`; the worker validates their hashes before executing.

This is a single-owner artifact architecture. An exclusive `.queue-owner.lock`
prevents two workers from owning the same volume. Do not run multiple API processes
against that volume or run a standalone Procrastinate CLI worker: handlers need the
API's artifact, credit and event services. A future independent worker deployment
requires a shared artifact authority and distributed mutation ownership first.

Commands cover pipeline stages and their explicit auto-chain, page draws and
corrections, cast references, covers, style proofs and lettering translation.
Prepared page inputs retain their model profile, reference bytes, request hash and
their page checks (read-back and visual review). Stage implementations continue to receive `StageRuntime`.
Synchronous analysis/review APIs keep their existing request lifecycle.

One account executes ordinary queued operations exclusively. Complete-page Draw
jobs whose frozen provider is FAL or OpenAI (`PARALLEL_PAGE_PROVIDERS`) use three
durable dispatch lanes and an account gate that admits up to three together;
ordinary operations wait for those pages to finish, and vice versa. Other
accounts can proceed concurrently. Provider rate limits answer with 429s, which
are retried before anything is generated. The old process-local per-user
concurrency override does not raise this durable limit.
`CANARY_GENERATION_WORKERS` controls total concurrent operations (default 5),
so its value must remain at least 3 for full parallel Draw throughput. A style batch owns its bounded
parallel proof calls until every sibling has finished or acknowledged cancellation.
Each proof has its own persisted status. Draw batch preflight runs in a worker
thread so preparing many pages cannot starve the queue heartbeat. Page publication
yields between items and emits page-start events only after durable admission.
Failures while publishing child jobs also fail the parent stage visibly.

The legacy closure executor exists for focused route fixtures only. `create_app`
always requires the durable queue; missing PostgreSQL never selects a memory queue.

## Failure contract

- Cast approval prerequisite rejections use `cast_approval_rejected`. Retrying
  an explicit rejected approval rechecks current prerequisites, including the
  older journaled visual-review rejection. Successful and indeterminate
  receipts retain their replay protection; no provider work retries automatically.
- Admission commits the operation and outbox intent in one SQLite transaction.
  Losing the process between admission and PostgreSQL dispatch does not lose work.
- Queued operations resume after restart. Credit availability is checked at
  admission and the actual hold is acquired at execution, so queued work does not
  accumulate expiring holds. A later balance change can reject execution.
- Pages offers **Cancel queued pages** for current page draws that have not started.
  Cancellation marks only waiting jobs terminal, without submitting them to a provider
  or acquiring a credit hold. A running or ambiguously submitted call is never
  cancelled by this action; its outcome and possible charge remain visible.
- Execution is recorded before calling a provider. Interrupted execution becomes
  `outcome_unknown`; inspect saved output and provider evidence before explicitly
  retrying. No automatic provider retry is added by the queue. A duplicate dispatch
  of a started or terminal operation cannot execute that operation again.
- Queue/storage/worker failures close generation admission and readiness. The
  supervisor reconnects with backoff up to 30 seconds. A stale worker dispatch is
  reclaimed after Procrastinate's heartbeat threshold (30 seconds); the operation
  state still determines whether execution is permitted.
- A scheduler dispatch that ends failed, cancelled, or aborted before its
  operation starts is reconciled to a retryable `dispatch` failure. It must not
  remain queued forever. This does not resubmit work or change running operations.
- Ordinary jobs retain the 900-second deadline. Pipeline and style batches use
  `CANARY_BATCH_JOB_TIMEOUT_SECONDS` (default 7200). A timeout does not establish
  that a paid provider call failed to execute.
- Operator drain closes new admission and holds accepted operations that have
  not started: they remain `queued` (never marked running) until resume. Running
  operations continue. The pause check and the running transition are one
  synchronous step, so a deployment-status snapshot taken after drain cannot miss
  an operation about to start. Deployment therefore waits only for running work;
  queued work survives process replacement. Process shutdown preserves queued
  work and interrupts running work conservatively.
- Missing credit leases hold unstarted operations the same way. (The dispatch
  task has `retry=False`; raising Procrastinate's `JobRetry` would fail the
  dispatch rather than defer it.)
- Old closure-only journal entries cannot be reconstructed and are reported as
  interrupted history. They are never silently replayed by the new worker.

The operation outcome is authoritative. A Procrastinate dispatch can finish
successfully after recording an operation failure; monitoring only PostgreSQL job
success would miss domain failures. Back up PostgreSQL and the whole artifact
volume, including its journal and `.jobs` inputs. Do not delete queued dispatches
or edit operation statuses directly. Restoring mismatched database/volume backups
requires explicit reconciliation; it is not an automatic replay mechanism.

## Author interactions

Project status returns explicit `active_jobs`; an unfinished Draw checkpoint no
longer implies that pages are executing. Style cards distinguish queued, running,
failed and unrequested proofs. A completed style can be selected while sibling
proofs run. Lettering on a completed page can be edited while other pages draw;
the same page remains protected. Cast changes (characters, locations, props and
alternate appearances), style directions, proof retries and auditions, covers
and page corrections can be queued while stages or other jobs run. The worker
keeps corrections unstarted until conflicting project work finishes, including
Extract/Brief and lettering translation in the separate text lane. Same-asset
duplicate submissions retain their existing guards. Review panels remain
accessible during generation; page issue decisions and editorial decisions wait
only for writers of their own evidence. Source replacement, resets, selection
and other immediate artifact-changing mutations retain their conflict guards.
The remaining-page action says **Draw remaining pages**.

Cast reference jobs expose the style hash from their admitted command, including
recovered history. The jobs response also identifies the current selected style;
Cast cards recover status and correction drafts only from jobs in that style.
Selecting a different style refreshes every part's Cast caches and clears obsolete
correction submission errors. Earlier failures remain in the operation history.

## Setup and operation

Install the locked web dependencies from `novel_to_comic` with `uv sync --extra web`.
Use a dedicated PostgreSQL database or a private schema with a dedicated login
role and set `CANARY_QUEUE_DATABASE_URL`. It must be a direct or session-mode
PostgreSQL connection, not an HTTP API URL or transaction pooler. For a private
schema, set the role's database `search_path` to that schema only; bootstrap and
runtime both use the same role and inherit that setting.

Local `scripts/dev.sh` starts Compose's `queue-db` on loopback port 55432 when no
external queue URL is supplied, and bootstraps the schema before starting a new
backend. The PostgreSQL data uses the `canary_queue_data` named volume. Credentials
in Compose are for local development; use a managed secret in production.
The launcher runs each service in its own process group. The first Ctrl-C requests
graceful shutdown and waits for active jobs; a second Ctrl-C stops the groups,
including a child server that has already closed its HTTP listener. On restart,
the OS-released volume lock lets the queue restore waiting jobs. Work recorded as
started remains `outcome_unknown` for inspection and is never replayed automatically.

For explicit bootstrap, with the queue URL set in the environment:

```sh
novel_to_comic/.venv/bin/python -m novel_to_comic.server.queue_schema
```

This creates a missing schema and leaves an existing schema untouched. The server
never migrates production PostgreSQL automatically. Before a Procrastinate upgrade,
back up the queue database, drain work and apply the version's documented SQL
migration separately. Canary currently locks Procrastinate 3.9 and Psycopg 3.3.

For a local production-container smoke run, start `queue-db`, build `canary-prod`,
then bootstrap inside the image before bringing up the server:

```sh
docker compose up -d --wait queue-db
docker compose --profile prod build canary-prod
docker compose --profile prod run --rm --no-deps --entrypoint python canary-prod -m novel_to_comic.server.queue_schema
docker compose --profile prod up canary-prod
```

For Fly, follow [deploy runbook Step 1b](../deploy.md#step-1b--generation-queue-database):
provision a dedicated PostgreSQL database or Supabase's private `canary_queue`
schema and login role (never Supabase's `public` schema), set
`CANARY_QUEUE_DATABASE_URL` as a Fly secret and bootstrap it with the locked
dependency version before deployment.
The existing persistent projects volume remains required. `/api/health/ready`
includes `generation_queue`; an unavailable worker returns HTTP 503.

Provider-free verification:

```sh
novel_to_comic/.venv/bin/python -m pytest novel_to_comic/tests/test_durable_queue.py -q
# Point only at an isolated test PostgreSQL database with the schema initialized:
CANARY_TEST_QUEUE_DSN="$TEST_QUEUE_URL" novel_to_comic/.venv/bin/python -m pytest novel_to_comic/tests/test_durable_queue.py -q
```

The integration test interrupts a running operation, preserves two queued
operations, restarts the worker, checks FIFO completion and explicitly redelivers
terminal dispatches to prove they do not execute twice. Unit tests exercise
atomic outbox rollback, worker supervision, saved input reconstruction and style
sibling ownership. These checks do not establish model output quality.

Upstream contracts: [FIFO resource locks](https://procrastinate.readthedocs.io/en/stable/howto/advanced/locks.html),
[retry policy](https://procrastinate.readthedocs.io/en/stable/howto/advanced/retry.html).
