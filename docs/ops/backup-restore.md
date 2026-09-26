# Backup restore

Status: Current

A consistent recovery point spans three stores: the `/projects` volume
(including `.request-journal.sqlite3`, its operation outbox, and `.jobs` inputs),
the generation queue PostgreSQL database, and Supabase. Keep an off-Fly copy of
the volume in addition to Fly snapshots (see the
[deploy runbook](../deploy.md#step-4--volume-backups-do-not-skip)).

1. Record the source volume, snapshot ID/time, queue database backup time,
   Supabase backup time, deployed release SHA, and expected projects.
2. Restore into a separate volume and isolated machine; never overwrite the
   active production volume for a drill.
3. Restore the queue database into an isolated database, then boot the same
   application release against the restored volume and that database, drained.
   Mismatched backup times require the reconciliation in the
   [job queue reference](../reference/job-queue.md); never replay work.
4. Open an owned test project and export both PDF and CBZ.
5. Verify project isolation and record missing/corrupt artifacts.
6. Destroy the isolated drill resources after retaining non-sensitive
   evidence.

A configured snapshot schedule is not a completed backup control until this
drill passes.
