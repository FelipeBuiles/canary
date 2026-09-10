# Customer-facing deployment

**Status: Current repository procedure, September 9, 2026.** The filename is
retained for existing links; the target is a bounded self-service release.
These steps are a procedure, not evidence that production has passed them.

1. Prepare the exact release SHA and read [the deploy runbook](../deploy.md).
   If a database change is required, review compatibility/rollback, confirm a
   backup, and apply the canonical SQL before the new binary starts. Preserve
   `/projects`, including request/job journals and Draw recovery records.
2. Establish the maintenance window and any external access restriction needed
   during verification. Drain intent persists across process replacement; reopen it explicitly after readiness and release verification. For an old binary
   without drain, follow the runbook's controlled first-cutover procedure;
   there is no idle-only fallback.
3. Push the intended SHA to `main`; manually dispatch `CI` on that SHA. Each
   dispatch has a unique workflow concurrency group and cannot be automatically
   cancelled by a later dispatch or push. Actual deployments remain serialized;
   up to 100 pending deployment jobs queue without replacing an older request.
   Check maintenance/schema conditions again when a queued release becomes active.
4. Backend, frontend, and Docker jobs must pass before `Deploy production`.
   That job authenticates `POST /api/ops/drain`, then waits for both
   `draining: true` and `safe_to_deploy: true`. Timeout or error does not
   authorize deployment; timeout leaves admission drained.
5. CI records the rollback release, rebuilds/deploys the tested source SHA with
   production arguments, and verifies public release contracts. It has no
   production database credential. The deployed build is not the identical
   digest used by the CI image smoke test.
6. Attach the CI summary and verifier output to a copy of
   [the release evidence template](release-evidence-template.md). Record
   deployed SHA, build timestamp, readiness, rollback image, and schema evidence.
7. Complete the signed-in smoke test and relevant
   [launch gates](../proposals/launch-readiness.md), including a confirmed
   production API model mode and explicit dependency checks. Public liveness
   alone does not prove purchase, recovery, generation, or export works.
8. Remove external restrictions only after acceptance. If a release fails or is
   cancelled, inspect actual Machine/release/activity state; decide explicitly
   whether to roll back or resume. Never automatically reopen a drained process
   or replay ambiguous paid submissions.

Follow [crash recovery and exceptions](crash-recovery.md) to activate the bounded
Machine recovery policy and independent external monitor. Keep deliberate stops
stopped, preserve drain intent, and explicitly verify deployed behavior. Recurring
backup restoration and protected release lifecycle exercises remain required.
