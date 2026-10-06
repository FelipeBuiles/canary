# Architecture review implementation — October 6, 2026

**Status: Implementation and local verification record. Production rollout is pending.**

This implements the eleven findings in the [original review](2026-10-06-architecture-review.md),
which examined commit `7885e84a13568467911776601a2a91c5abe9f5fd`.
The changes preserve the eight stages, four checkpoints, series/part artifact
ownership, frozen provider inputs, independent editable lettering, optimistic
revision checks, and conservative handling of ambiguous paid submissions.

## Resulting boundaries

HTTP routes prepare and admit typed commands. The durable executor reconstructs
those commands and owns execution-time credit authorization and settlement.
Stages and page domain operations do not admit server jobs or import HTTP
routers. PostgreSQL still owns dispatch, SQLite still owns admission receipts
and executable outbox intent, and Supabase still owns account and billing state.
Their different recovery responsibilities remain explicit.

The new application modules hide complete responsibilities: page admission,
page batch/progress operations, Cast instruction admission, cover work, and
pipeline orchestration. They replace code previously embedded in routers and
the separate credited closure executor. No new network service, generic
repository layer, provider retry policy, or queue backend was introduced.

## Findings resolved in code

| Finding | Implemented behavior | Main authority |
| --- | --- | --- |
| F01: logout cookie | Backend logout expires the native-read cookie even for expired tokens; explicit frontend logout awaits it. Serialized session refresh/account changes update the cookie, whose lifetime is bounded by JWT expiry. Failed logout remains visible to the user. | [auth.py](../../novel_to_comic/src/novel_to_comic/server/auth.py), [useAuth.ts](../../web/src/hooks/useAuth.ts) |
| F02: schema convergence | Canonical SQL contains the project trust boundary and revokes legacy table **and column** browser writes. Owners retain project reads and a minimal credit-balance projection; raw usage and ledger details remain service-owned. The former delta points to the canonical procedure. | [supabase-schema.sql](../supabase-schema.sql), [release checks](../../scripts/check_release.py) |
| F03: shared locks | Part paths resolve to the series lock for artifact transactions. Translation snapshots/commits, Draw persistence/reconciliation and pipeline failure writes acquire it in worker threads on async paths. Temporary writes use unique siblings. Provider work stays outside the artifact transaction. | [artifact_lock.py](../../novel_to_comic/src/novel_to_comic/artifact_lock.py), [TargetArtifacts](../../novel_to_comic/src/novel_to_comic/target_artifacts.py) |
| F04: ledger blocking | Async callers offload synchronous financial RPCs through a bounded limit of eight. Cancellation waits for a reservation's result and releases an obtained, unstarted hold. Execution and settlement retain existing ambiguous-outcome evidence. RPC/connect timeouts are explicit. | [async_credits.py](../../novel_to_comic/src/novel_to_comic/server/async_credits.py), [job_execution.py](../../novel_to_comic/src/novel_to_comic/server/job_execution.py) |
| F05: export validity | Preflight and downloads share verification of current inputs and the open descriptor. A bounded process-local checksum cache keys on device/inode, size, nanosecond mtime and ctime, after a two-second quiet window; recent files always hash bytes. Replacements and same-size edits invalidate it. Downloads use private/no-store responses. Stale export triggers rebuild through free Finish. Combined exports bind source fingerprints and output checksums. | [page_finishing.py](../../novel_to_comic/src/novel_to_comic/page_finishing.py), [verified_files.py](../../novel_to_comic/src/novel_to_comic/verified_files.py), [combined_export.py](../../novel_to_comic/src/novel_to_comic/combined_export.py) |
| F06: outage gating | Every project mutation declares spending/dispatch and receipt policy, including stage-specific approval and paid recovery opt-in. Local edits do not depend on queue/credit readiness. Drain gates durable mutations, including creation/import. Definite pre-admission errors say `admitted: false` and do not consume a receipt. Frontend callers explicitly mark paid actions. | [action_policy.py](../../novel_to_comic/src/novel_to_comic/server/action_policy.py), [admission.py](../../novel_to_comic/src/novel_to_comic/server/admission.py), [client.ts](../../web/src/api/client.ts) |
| F07: duplicate executor | Production generation uses typed commands and one credited executor. Queued admission checks affordability; the hold is acquired when execution starts. Route fixtures replace dispatch/provider transport while using the production command and settlement path. Obsolete credited closures, frozen-request queue helpers and task registries were removed. | [credited_job.py](../../novel_to_comic/src/novel_to_comic/server/credited_job.py), [queue fixtures](../../novel_to_comic/tests/queue_fixtures.py) |
| F08: unbounded executable history | A fresh process loads all live commands plus at most 200 terminal summaries. Reconnect merges journal records while preserving existing live objects and older in-memory observations. History is indexed and paginated without parsing retired commands. Unsupported unstarted commands require an explicit rerun; started work stays unknown. Draw cohorts query missing terminal outcomes in bounded chunks. | [job_commands.py](../../novel_to_comic/src/novel_to_comic/server/job_commands.py), [job_journal.py](../../novel_to_comic/src/novel_to_comic/server/job_journal.py), [durable_queue.py](../../novel_to_comic/src/novel_to_comic/server/durable_queue.py) |
| F09: part scope | Status separates part and series busy state; the existing part-facing running flag follows backend admission scope. Publication retains one identity per series, labels its published part privately, requires the current version for cross-part replacement, and uses one series cache. Manifest commit failure restores the previous private owner pointer. | [projects.py](../../novel_to_comic/src/novel_to_comic/server/routers/projects.py), [publications.py](../../novel_to_comic/src/novel_to_comic/server/publications.py), [BookPublication.tsx](../../web/src/components/book/BookPublication.tsx) |
| F10: retained storage | Ingestion has a serialized account budget, default 5 GiB, including public snapshots. One usage scan per ingestion covers cumulative uploads, expanded text and replacement publication bytes. Rejected uploads/imports clean up sources. Drained housekeeping only removes unreachable job blobs and superseded public copies; original manuscripts, current/prior public versions, author archives, receipts and unresolved paid evidence survive. | [storage_budget.py](../../novel_to_comic/src/novel_to_comic/server/storage_budget.py), [parts.py](../../novel_to_comic/src/novel_to_comic/server/routers/parts.py), [projects.py](../../novel_to_comic/src/novel_to_comic/server/routers/projects.py) |
| F11: public private exports | The optional R2 export helper, application flags and backend dependency were removed. Private PDF/CBZ downloads remain authenticated; public distribution continues through explicit publication. Existing encrypted bundles can still be read for credential rotation. | [export.py](../../novel_to_comic/src/novel_to_comic/server/routers/export.py), [backend dependencies](../../novel_to_comic/pyproject.toml) |

The storage budget limits ingestion, rather than promising an exact ceiling on
generated artwork or retained financial evidence. Housekeeping is intentionally
conservative and does not purge author revisions or unknown paid operations.
Removing the upload path does not revoke objects already uploaded to an old
public bucket; those require a separate inventory and retirement action.

## Recovery and documentation

Backup capture, scheduling and retention belong to the deployed container and
infrastructure setup, as the user confirmed after reviewing this PR. The added
host backup script, service/timer, configuration and their tests were removed.
The [application recovery contract](../ops/backup-restore.md) describes the stores
and authorization/export checks required after recovery, without adding a
second backup implementation.

[Deployment](../deploy.md), [agent navigation](../reference/agent-context.md),
[queue contracts](../reference/job-queue.md), [public-book routes](../reference/public-books.md)
and generated references describe the current Lightsail/code boundaries.
Original Fly cutover procedures remain identified as recovery/history. The
original reproduction results remain historical JSON evidence; the old-commit-only
harness was removed. Current regression tests assert the corrected contracts.

## PR review follow-up

The changes remain in one PR, per the user's early-stage rollout preference.
The concurrency/retention concerns were addressed within that change:

- Async artifact transactions and Draw completion/reconciliation run in worker
  threads. Event channels hand worker-thread notifications to their owning loop.
  The series lock still serializes transactions so shared invalidation and
  optimistic writes remain coherent; it does not cover provider execution.
- Warm verification of settled files checks current typed provenance and file identities without
  rereading artwork/package bytes. Cold verification still reads every byte.
  Cache entries are bounded to 4,096 files and are not persisted across processes.
  A provider-free two-part fixture with 200 exported pages, 300.19 MiB of
  verified inputs and 200 concurrent Draw commits measured 190.17 ms for the
  first checksum pass (401 file hashes), 60.64 ms warm (zero file hashes),
  a 5.73 ms maximum event-loop heartbeat interval, and 189.74 ms maximum
  Draw commit elapsed time including lock wait and disk write. These are local
  fixture measurements after the timestamp quiet window, with a warm OS filesystem
  cache, not production latency.
- CI exposed rapid writes sharing a ctime tick. Nanosecond fields do not imply
  unique timestamps; the [Linux kernel documents this behavior](https://docs.kernel.org/filesystems/multigrain-ts.html).
  Files with mtime/ctime less than two seconds old bypass checksum reuse. An
  isolated Linux container passed 128 rapid same-size/restored-mtime mutation
  checks, with 126 ctime collisions observed, plus settled-cache reuse checks.
  The normal suite also models a deterministic coarse timestamp collision.
- Uploads use one account/publication usage snapshot under the ingestion lock,
  then check cumulative new bytes. No persistent size counter was introduced.
- Housekeeping skips hidden account directories and retains every author upload.
  Original-source deletion is an explicit project-deletion operation.
- A same-process queue reconnect preserves running objects. A fresh process still
  fences interrupted work as unknown rather than replaying it.
- Restore constructs detached jobs in a worker and merges them on the event loop,
  rechecking existing IDs after loading. Registry iterations and restore's
  reconciliation use a snapshot of entries; job objects retain their identity.
  A deterministic HTTP regression holds a threaded deployment-status read open
  while restore/new admissions add jobs. Additional regressions cover cancelled
  loading, retrying a failed quarantine write and queued payload serialization.
  Cancelling a loader cannot publish partial results or quarantine journal rows.
  Once reconciliation writes begin, repeated cancellation waits for them before
  releasing the volume lock, including the write-failure path.
- Cancellation remains cancellation when a completed ledger RPC/cleanup fails;
  the failure is logged and ledger evidence remains available.
- The stalled-ledger concurrency regression supplies its executor capacity
  explicitly. The previous CI failure came from a small runner's default pool
  never reaching eight blocked calls; the production limit remains eight.
- Approval/recovery/preflight exceptions live in route metadata. Stale cached
  exports rebuild, and every replacement publication is budgeted before commit.
  The export rebuild regression compares decoded pixels and current manifest
  checksums, since regenerated color profiles may contain a new timestamp.

Logout intentionally requires backend acknowledgment: the HttpOnly native-read
cookie is still an authentication credential until expired. An unreachable backend
leaves the account signed in with a visible failure rather than reporting a
completed sign-out with that credential still usable.

## Verification

- Full backend suite after the restore follow-up: **3,430 passed, 50 optional tests skipped**.
  The final reconciliation-cancellation ownership guard was then checked with
  **172 focused tests passed, one optional skip**. Coverage includes threaded
  HTTP reads, loader cancellation, failed quarantine-write recovery, queue-startup
  responsiveness, explicit CI executor capacity and coarse filesystem timestamps.
  All seven export-router tests passed after correcting that metadata-sensitive
  assertion. Backend Ruff checks passed.
  The opt-in real database checks below ran separately with explicit
  disposable credentials. The two backend warnings are existing Starlette/httpx deprecations.
- Full frontend suite: **973 passed across 129 files**, including cross-part
  publication confirmation. ESLint and the production TypeScript/Vite build
  passed. The build retains its existing large-chunk warning.
- PostgreSQL 17.11: eight fresh-install and eight permissive-legacy-upgrade
  authorization checks passed using the canonical SQL alone, including replay.
  Eighty-one financial/outbox/queue checks passed, followed by the corrected
  execution-time credit race. That race proves only one competing connection
  acquires the shared balance and that its completed uncharged hold is released.
- Focused fault/concurrency checks include repeated cancellation after a hold
  commits, 24 stalled ledger calls, two-part optimistic style edits, a 450-job
  Draw cohort, stale-art/package rejection, account-wide quota races, late
  initialization failure cleanup and conservative reachability cleanup.

Checks used Python 3.12 and Node 24, reusing installed dependencies from the
primary checkout while importing this checkout's source. A fresh dependency
installation was not tested. Checks use disposable accounts/databases, offline
signing keys and fake provider operations. Local Chromium renders editable lettering; no development server
was started/restarted and no paid generation ran. Disposable database containers
were removed. Mocked provider tests do not establish generated image quality.

## Production work still required

1. Review and deploy this application revision through the existing single-owner
   drained release procedure. Audit saved unstarted commands against the current
   typed argument models before release. Incompatible **unstarted** saved commands may
   require an explicit rerun; existing terminal history and unresolved outcomes
   remain visible. Do not reinterpret started operations as safe retries.
2. Audit live database grants, then apply canonical SQL through the reviewed
   database rollout. Local role tests establish installation convergence, not
   live production privileges. Inspect any existing unsafe project storage names.
3. Inventory/revoke any old public export objects and rotate unused bucket
   credentials through the encrypted-bundle procedure. Repository cleanup alone
   cannot revoke cached public URLs.

No production SQL, deployment or bucket retirement was performed. Existing
container/infrastructure backup controls were not changed or inspected by this PR.
The primary checkout's uncommitted work is separate from this PR and still needs
integration before deployment; those edits were inspected read-only and preserved.
