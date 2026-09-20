# Job and queue audit: Dunwich Horror

Status: Current diagnostic snapshot of the working checkout, inspected September 19–20, 2026. Recommendations below are Proposed, not implemented.

## Decision

Refactor the job model and use a durable execution backend. Do not treat installing a queue library or increasing the 900-second timeout as the whole fix. Execution, artifact completeness, stage review, and UI activity currently have conflicting definitions of “running.” Resource conflicts are mostly enforced by blocking an entire project.

Prefer a bounded Procrastinate/PostgreSQL feasibility spike for the execution backend, after introducing serializable operations and resource-scoped admission. Keep the existing StageRuntime, frozen requests, credit settlement, artifact boundaries, and independent lettering revisions. A separate worker can initially run on the same machine/volume as the API. Do not enable arbitrary distributed artifact writers just because the queue supports them.

This audit did not change application behavior, restart the server, submit generation, alter project artifacts, or modify unrelated working-tree changes.

## Recorded incident evidence

Project: `0b6a4e13-093a-445b-8b67-dd647ea00155` (The Dunwich Horror). Read-only evidence: `projects/.request-journal.sqlite3`, project `state.json`, and `samples/` under `projects/947150d4-7d2f-4726-a018-5539f933ea56/the-dunwich-horror/`. Times below are UTC.

| Time | Recorded event |
| --- | --- |
| Sep 19, 21:01:01–21:16:01 | First `style_suggest` job failed with `Generation timed out after 900s`. |
| Sep 19, 21:19:35–21:21:55 | Individual style sample 6 completed. |
| Sep 20, 01:40–02:39 | Nine page jobs completed in total. |
| Sep 20, 02:40:11 | Page 50 interrupted by shutdown. Another 53 page jobs recorded “Server stopped before this job started.” |
| Sep 20, 02:55:19–03:07:02 | New `style_suggest` job completed successfully in approximately 703 seconds. |

All twelve sample PNG paths exist at inspection, including the six newer proofs (7–12). This establishes saved files, not visual quality. The saved Draw state remains `running`, 9/63 items, no finish timestamp. The journal contained no queued/running jobs for this project at inspection; this is persisted evidence, not a live-process attestation.

Therefore the new batch did not ultimately fail in the same way as the earlier batch. The displayed timeout matches historical evidence. The exact browser/cache path that put that old error beside “Close art direction” cannot be conclusively reconstructed without the contemporaneous browser state. Do not report six provider failures based on the cards alone.

## Findings

### 1. P1 — Project-wide mutation veto blocks independent work

Evidence: `server/admission.py:19–20, 138–150`; `server/routers/lettering.py:85`; `server/routers/styles.py:1110` (source paths below are relative to `novel_to_comic/src/novel_to_comic/`).

The middleware rejects every mutation outside its targeted-generation regex when `project_busy()` sees any active job. Both `PATCH /styles/active` and `PUT /pages/{n}/lettering` miss the exception. This directly explains both reported 409s. It happens before the routes can apply their existing artifact locks and optimistic revision checks.

Fix: explicit operation conflict policy. Saving lettering on a completed page should be compatible with drawing other pages, while remaining incompatible with same-presentation translation/reset and conflicting export/publication work. Selecting a ready style should be compatible with independently frozen proof generation.

Do not merely whitelist style selection: it currently resets Cast through Finish and deletes downstream artifacts. Allowing it alongside old-generation Draw jobs would let those jobs publish against invalidated inputs. Version/fence those commits, retain genuinely conflicting restrictions, and reload state under the commit lock rather than saving a captured whole-project state snapshot.

### 2. P1 — One project's activity makes unrelated stages appear alive

Evidence: `server/routers/projects.py:_stage_payload, project_status`; `stages/s7_page_draw.py:run`; `server/routers/pages.py:_sync_draw_progress`; `web/src/components/ui/FloatingIndicator.tsx:29–37`.

Draw intentionally remains `running` until every page has a render—even between manual one-page actions. `project_status()` then passes one project-wide `running` boolean as `is_task_alive` for every stage. Starting a style job suppresses Draw's stale flag. The floating widget finds the first persisted running stage and calls it the active work. A completed Style checkpoint plus incomplete Draw therefore displays “Pages” during a style batch.

Provider-free reproduction: a two-hour-old running Draw stage reports `stale=True` without activity and `stale=False` when given unrelated activity. Dunwich's persisted state matches the required precondition.

Fix: stage/artifact readiness separate from execution. Return explicit active operations with job ID, stage, resource, and progress. Derive widgets from those operations. An incomplete but idle edition is not a live Draw worker.

### 3. P1 — Style batch errors leave unowned child work running

Evidence: `stages/s2_style.py:1055–1098`; `server/routers/styles.py:suggest_styles`; `server/credited_job.py:enqueue_reserved_generation_job`.

`generate_samples_for_indices()` uses plain `asyncio.gather`. When one child raises an ordinary exception, gather propagates it without cancelling/awaiting remaining children. The credited wrapper finalizes the parent and releases its cleanup/guard while sibling proofs can continue writing and invoking providers. Another project mutation can then be admitted against work no longer represented by an active job. This is different from cancelling the whole gather on timeout, which does propagate cancellation.

Provider-free reproduction patched only the sample provider and brief/template helpers: child 1 raised after child 2 started; the batch returned failure; child 2 then completed after the parent returned. No paid calls were made.

Fix: durable child jobs per proof with an aggregate batch, or structured ownership that waits for all children to settle before finalization. Partial success should remain visible. Cancelling siblings does not prove an already-submitted provider operation was never executed.

### 4. P1 — Queue history is durable; executable work and ownership are not

Evidence: `server/generation_jobs.py:GenerationJob, enqueue_generation_job, recovered_generation_jobs`; `server/app.py:_lifespan`; `server/routers/pipeline.py:_run_job`.

Execution consists of process-local closures, dictionaries, semaphores, and an asyncio queue. SQLite persists display payloads but not a reconstructible runner, owner lease, resource claims, or a dispatch transaction. Startup does not restore execution. Recovery projects every absent queued/running journal row as failed, without persisting that recovery transition. Graceful shutdown fails queued work, as Dunwich's 53 never-started pages demonstrate. Full pipeline tasks use a separate in-memory task registry rather than this job ledger.

Not automatically replaying ambiguous image submissions is correct. Treating known never-started work and potentially submitted work alike is the missing distinction.

Fix: serializable commands, durable attempts, worker leases, claim-before-execution, persisted interrupted/unknown states, and reconciliation against frozen request/output evidence. Resume provably unsubmitted work only under explicit policy and valid funding. Never turn worker redelivery into an unconditional new paid submission.

### 5. P2 — Proof cards infer failure from missing files and local state

Evidence: `web/src/pages/rooms/StyleRoom.tsx:91–107, 204–240, 550–558`; `web/src/components/style/StyleProofCard.tsx:57–87, 111–122`; `web/src/api/queries.ts:369–389`; `server/routers/styles.py:suggest_styles`.

A suggestion with no sample starts with `imgFailed=true`. It shows a loading placeholder only if local pending/generation flags say it should. Suggestion-batch state is component-local, and the endpoint returns only `{status: "started"}`, not the batch ID. Additional suggestions do not own the already-complete Style checkpoint. After navigating away/reloading, the room cannot reconstruct the batch from that checkpoint; its job polling is disabled when local IDs are empty. Missing images can therefore be labelled “SAMPLE PROOF FAILED” while work is pending/running. Existing SSE progress can refresh files, but is not a reliable state snapshot.

Fix: server-owned batch membership and per-proof states: not requested, queued, running, ready, failed, interrupted, unknown. Always reconcile active style operations on mount/reconnect. Error messages must identify their attempt and stop acting like current failures after a successful replacement.

The header's `sampleError` is separately maintained from suggestion success/error state. This is additional stale-error risk, but the exact historical timeout-to-header path remains unproven.

### 6. P2 — Timeout budget covers a whole heterogeneous batch

Evidence: `server/generation_jobs.py:199–205`; `server/app.py:411–414`; `stages/s2_style.py:SAMPLE_CONCURRENCY`; `ai/codex_runtime.py:34–35`.

The same 900-second worker timeout wraps individual work and a style batch consisting of suggestion text, shared brief work, and six image operations. Samples have local concurrency two; provider/model gates can reduce effective throughput further. The Codex text call alone permits 900 seconds. Healthy sequential phases can exhaust the parent budget. The earlier recorded batch hit precisely that boundary; the newer batch needed 703 seconds.

Fix: bounded per-operation deadlines, separately measured capacity wait, heartbeat/progress, and an explicit batch policy. Parent timeout must not discard completed children. Increasing the budget is only a temporary mitigation. The exact slow provider phase in the older timeout was not established by this audit.

### 7. P2 — Fairness loop breaks FIFO and displayed queue positions

Evidence: `server/generation_jobs.py:209–220, generation_job_payload`.

Workers dequeue and append jobs to the back every 50 ms while a user semaphore is locked. Queue positions are instead sorted by original sequence within the project. Thus displayed order and execution order disagree. Dunwich's accepted page sequence is visibly non-FIFO: page 2, then 45, 58, 42, 32, 57, 53, 26 before interruption at 50. Other resource-semaphore waits can also occupy worker slots before the execution timeout starts.

Fix: choose eligible jobs with stable ordering within a fairness group; acquire capacity at dispatch rather than repeatedly rotating accepted work. Report scheduling state separately from provider execution. Avoid presenting queue positions as precise if the scheduler does not honor them.

### 8. P2 — Incomplete work is labelled retry because idle Draw ages into stale

Evidence: `web/src/pages/rooms/PagesRoom.tsx:690–692, 909`; `state.py:is_stale`; `stages/s7_page_draw.py:run`.

The button uses “retry” if any page failed, Draw failed, or Draw is stale. Since manual Draw stays running between pages, an ordinary pause eventually counts as stale even without a failed page. This provides a code-supported explanation for the reported wording; the exact pre-restart browser snapshot is unavailable.

Fix: “Draw remaining pages” for mixed/incomplete work. Show failed/interrupted counts separately and explicit retry affordances for those attempts. Work not requested yet is not failure.

### 9. P1 — Journal failure can kill a worker without replacing it

Evidence: `server/generation_jobs.py:generation_worker finally`; `server/app.py:_lifespan, health_ready`.

The worker persists terminal state in `finally`, before `queue.task_done()`, without an outer containment/supervision loop. A journal write failure escapes, loses that worker, and skips queue acknowledgement. Workers are created once at startup; readiness checks dependencies/credit leases but not worker task survival. Repeated storage failures can consume all workers while newly accepted jobs wait indefinitely. This is a static fault-path finding, not evidence that it happened in Dunwich.

Fix: fail admission closed when durable job storage is unhealthy, supervise worker exits, and surface worker/oldest-queued health. Do not silently replay uncertain paid work when replacing a worker.

## Proposed implementation sequence

1. **Correct current behavior:** explicit active-operation status, Draw idle/incomplete semantics, contextual errors, proof-state recovery, neutral remaining-pages copy. Contain and await batch children. Add worker failure visibility. Preserve all saved art.
2. **Define resource ownership:** operation IDs and parent batch IDs; immutable input revisions; resource conflict matrix; commit-time fencing. Remove blanket edit blocks only with corresponding conflict tests. Keep page lettering independent of Draw and preserve Finish invalidation/revision rules.
3. **Make commands durable:** registry of typed operation handlers receiving serialized IDs/revisions instead of HTTP-request closures. One execution service owns admission, attempts, terminal transitions, and reconciliation. Stages still receive StageRuntime and do not call one another; orchestration retains the explicit auto-chain.
4. **Adopt durable dispatch:** validate PostgreSQL worker access and same-volume deployment, then migrate style batches and targeted page jobs, followed by stage orchestration. Reconcile old journal history as evidence; do not replay legacy closures or ambiguously submitted jobs.

Suggested execution states: queued, claimed, running, succeeded, failed, cancelled, interrupted, outcome unknown. Keep provider submission and billing settlement as separate recorded dimensions; a single `recoverable` boolean cannot mean both “safe to retry” and “requires inspection.” Batch outcome is aggregated from children, including partial completion. Artifact/checkpoint state remains its own projection.

Suggested conflict examples:

| Operation | Compatible work | Conflicts requiring a gate/fence |
| --- | --- | --- |
| Save page A lettering | Draw page B | Same lettering revision/translation; conflicting publication snapshot |
| Select ready style | Frozen independent proof generation | Downstream jobs using the old style; destructive invalidation |
| Generate proof B | Inspect/select ready proof A once selection commits safely | Same proof attempt/output replacement |
| Delete/reset project | None that can still publish | All active writers and unknown submissions requiring reconciliation |

## Library assessment

- **Procrastinate: preferred spike.** Python async tasks, PostgreSQL persistence, execution/queueing locks, priorities, and configurable retry provide a compact fit. Its documented worker-heartbeat recovery and cancellation interfaces are useful. Default task retry is off. We must implement reconciliation, not copy a periodic “retry every stalled job” recipe. Existing Supabase usage is through its client API; direct PostgreSQL connectivity, permissions/migrations, and worker connection behavior must be validated rather than assumed. Sources: [task API](https://procrastinate.readthedocs.io/en/stable/reference.html), [worker recovery](https://procrastinate.readthedocs.io/en/main/howto/production/retry_stalled_jobs.html), [cancellation](https://procrastinate.readthedocs.io/en/main/howto/advanced/cancellation.html).
- **Celery: viable, not my first choice here.** Its acknowledgement/redelivery controls explicitly require attention to task idempotence and worker-loss behavior. It does not remove Canary's resource, artifact, or unknown-submission problems. Choose it if its operational ecosystem is a deliberate requirement, not as a shortcut around the domain refactor. Source: [Celery tasks](https://docs.celeryq.dev/en/latest/userguide/tasks.html).
- **Continue custom asyncio + SQLite:** least immediate infrastructure change, but durable claiming, leases, supervision, fair dispatch, cancellation, and recovery would all become our maintained queue implementation. Reasonable only if remaining explicitly single-process is a firm product constraint. The current SQLite journal is useful evidence, not yet that implementation.

No library was installed or benchmarked. Recommendation is architectural judgment based on this code and the linked primary documentation, not a completed production qualification.

## Verification and release gates

Existing targeted checks: **29 backend tests passed** across generation jobs, admission, credited jobs, and operations; **77 frontend tests passed** across Pages room, style proof cards, style comparison, pipeline reconnect, and status events. They establish existing covered behavior, not absence of the findings above. Backend emitted two dependency deprecation warnings.

Additional provider-free harness verified sibling work continuing after style-batch failure and unrelated activity suppressing stale Draw detection. Temporary harness: `/tmp/canary_queue_audit.py` (not an application change or durable test suite).

Required regression coverage for implementation:

- Manual page 1 completes, idle pause, restart, then style batch: widget identifies Look; remaining pages are not all called failed.
- Reload/navigate during proof generation; completed proofs remain selectable; unstarted proofs never show failed.
- Edit completed page lettering while another page draws; check optimistic revisions and Finish invalidation.
- Style selection versus old-generation commit: no deleted/stale artifact resurrection or lost state updates.
- One child fails while others run: no released ownership until all work is accounted for; partial successes survive.
- Process exit before claim, after claim, after submission, after saved output, and during settlement: recovery never duplicates an ambiguous paid submission.
- Journal outage and worker exit: admission/readiness reflect failure, no silently stranded accepted work.
- Same-user ordering, cross-user fairness, bounded capacity waits, and multiple tabs/reconnects.

Uncertainty: no contemporaneous browser snapshot, no reconstruction of the older provider's exact slow phase, no image-quality assessment, and no multi-process deployment qualification. Application fixes and data repair remain unimplemented because this request is a review and architecture assessment.
