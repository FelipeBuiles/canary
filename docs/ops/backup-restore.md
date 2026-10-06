# Backup and restore

**Status: Application recovery contract. Backup operations belong to the deployed
container and infrastructure setup.**

Capture, scheduling, encryption, retention, destination credentials and monitoring
are managed with the container deployment. This architecture change adds no host
backup scheduler or restore CLI. Use the deployment's established recovery procedure.
The application defines which state must survive and how to check the restored data.

## State that belongs to a recovery point

- The projects volume: manuscripts and original uploads, series/part manifests,
  artwork, provenance and revisions, editable lettering, public snapshots,
  `.request-journal.sqlite3`, the operation outbox, and required `.jobs` inputs.
- Account and billing data: project ownership, balances, holds, usage evidence,
  settlement records, and authentication identity.
- Queue dispatch data, together with the volume journal's accepted commands.
- The release/image identity, deployment configuration and encrypted credential
  bundle, with the independently held recovery key.

Restore these stores from the same recovery window. Artifact snapshots without
ledger/outbox state cannot determine whether a paid operation completed. Account
and authentication recovery must also use the database/platform's recovery procedure.

## Application checks after an isolated restore

Keep the source volume untouched and restore to a separate environment. Start the
recorded application version drained with isolated database/queue settings. Check
SQLite integrity and ownership before admitting work. Serialized workspace paths
must resolve to the restored volume; changing their prefix is an explicit recovery
operation, not a provider retry.

Verify that an owner can read the restored project, another account cannot, and
anonymous PDF/CBZ reads fail. Verify that logout expires the native-read cookie.
Run Finish and authenticated PDF/CBZ downloads, then compare file hashes and page
counts with the recovery point. Check retained original uploads, author revisions,
lettering, accepted action receipts, queued commands and provider-response evidence.
Reapply reviewed database roles/grants when the recovery procedure omits ACLs.

Inspect started or unknown paid operations and reconcile them with provider/ledger
evidence. Never infer a safe retry from missing queue dispatch or replay started
commands automatically. Preserve unresolved inputs and holds until reconciliation.

Record recovery time, release identity, restored store identities, authorization
and export checks, missing evidence and reconciliation decisions. The historical
[Lightsail cutover evidence](lightsail-ci.md#production-cutover-evidence-2026-10-06)
is distinct from the currently deployed container backup controls.
