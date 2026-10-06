# Canary deployment

**Status: Current repository contract, October 6, 2026.** Lightsail became
production that day; Fly is stopped and fenced. Dated live evidence is in the
[Lightsail release runbook](ops/lightsail-ci.md#production-cutover-evidence-2026-10-06).
The architecture changes in this checkout still require their own release.

## One artifact owner

One Lightsail host runs one application container, one Uvicorn worker, and its
Procrastinate worker tasks. Nginx terminates origin TLS behind Cloudflare.
The container supervises a loopback-only LiteLLM gateway. The host's systemd unit
owns process restart and explicit maintenance intent. Build images in Depot;
release immutable image digests through the reviewed host controller.

The persistent `/srv/canary/projects` directory is mounted as `/projects`.
It owns manuscripts, revisions, artwork, editable lettering, public snapshots,
request receipts, the operation outbox, and paid-result recovery evidence.
Supabase owns account/project metadata and the credit ledger. PostgreSQL's private
queue schema owns dispatch and heartbeats. Keep one volume owner; additional API
processes would invalidate local admission and artifact transaction assumptions.

## Installation and releases

Use [secret delivery](ops/secret-delivery.md) for the SOPS/age bundle, independent
recovery identity, protected host configuration, and process credential scopes.
Use [Lightsail CI](ops/lightsail-ci.md) for host installation, Depot OIDC/SSH
controls, image qualification, drain, replacement, verification and explicit
resume. Those files contain the commands; this page owns the deployment choice.

Apply [canonical SQL](supabase-schema.sql) before admitting work on a new release.
It converges project privileges, accounting access, constraints, and RPC grants
on fresh and previously permissive installations. An isolated upgrade test is
not evidence that production SQL was applied. Record production migration and
verification in the [release evidence template](ops/release-evidence-template.md).
Queue schema/version upgrades remain separate reviewed operations.

Ordinary releases drain before waiting for idle. Running work finishes; unstarted
commands remain durable and paused. Keep the candidate drained until its version,
readiness and public checks pass. A lost deployment response is an unknown
outcome: inspect the host before retrying. Never restart the old Fly copy against
the live volume or production queue. Rollback after new writes requires data
reconciliation, not merely selecting an old image.

## Generation queue database

Configure `CANARY_QUEUE_DATABASE_URL` in the encrypted application bundle with a
dedicated role whose search path selects the private `canary_queue` schema.
Bootstrap with the locked Procrastinate version, as described in the
[job queue reference](reference/job-queue.md#setup-and-operation).
Never use Supabase's `public` schema or a transaction pooler for dispatch.
Readiness includes queue liveness and owned credit leases; local edits require
only the dependencies they use. Operator drain still closes every mutation,
including project creation/import.

## Private exports and capacity

Working PDF/CBZ files stream through authenticated, verified descriptors. The
application no longer uploads private exports to public R2 URLs. Explicit public
book snapshots remain on the volume and are revocable through Canary's reader.
Previously uploaded public objects require an operator inventory and deletion or
public-access revocation; removing application configuration does not revoke them.
Legacy R2 keys may remain readable in an existing encrypted bundle, but no
application upload path consumes them. Retire them during a reviewed bundle update.

`CANARY_ACCOUNT_STORAGE_BYTES` defaults to 5 GiB for retained account data and
owned public copies. `/api/account/storage` reports usage. Capacity checks serialize
ingestion across an account; already admitted paid results remain persistable.
Drained, idle housekeeping removes only provably unreachable job inputs and obsolete
public versions. Original manuscripts, receipts, job outcomes, unknown paid attempts,
author archives and artwork are retained. This budget complements host disk monitoring.

## Backups and recovery

Backup operations belong to the deployed container and infrastructure setup.
The [application recovery contract](ops/backup-restore.md) identifies the state and
checks needed after restoring that deployment. This PR adds no host backup automation.
