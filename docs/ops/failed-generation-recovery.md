# Failed generation recovery

Status: Current

Inspect the incident in the external operator queue and authenticated
`GET /api/ops/exceptions` (`X-Canary-Ops-Token`). See
[crash recovery](crash-recovery.md) for service recovery and maintenance.
Record release, opaque project/job/action IDs, stage, page/render revision,
provider call ID when available, and credit reservation/settlement status.
Do not copy manuscript text, prompts, raw exception payloads, or credentials.

## Automatic recovery

Process recovery restores availability only. Durable request and job records
remain authoritative; interrupted work is displayed for inspection and is never
automatically dispatched. A replayed indeterminate HTTP action returns 409.
Do not delete its journal entry or change its key to bypass that guard.

Preserve `/projects`, including `.request-journal.sqlite3`, complete-page Draw
requests, pending paid results, renders, provenance, OCR evidence, and state.
Never release all holds at startup, approve a checkpoint, or overwrite artwork
to make a project appear complete.

## Saved complete pages

1. Inspect the canonical ComicPage, saved render and provenance, and pending
   recovery evidence. Keep completed **pages** and all immutable revisions.
   Draw creates a complete lettered page; there is no independent panel retry.
2. If artwork is saved but checks are incomplete, use the Pages recovery view.
   `GET /api/projects/{project}/pages/checks/estimate` identifies cached versus
   paid checks. `POST /api/projects/{project}/pages/checks/recover` with
   `allow_paid: false` performs only recovery supported by saved OCR evidence.
3. New OCR requires explicit customer consent to the estimated render identities:
   submit `allow_paid: true` and the exact `renders` map from the estimate.
   A replacement render invalidates earlier consent. Recovery must retain
   successful cached results and inspect failed pages separately.
4. Image generation or a correction requires a distinct customer-authorized
   action after the existing request has been reconciled. A correction creates
   a complete new page revision, retaining identity references and exact Adapt
   lettering. Do not redraw merely because OCR or settlement failed.
5. OCR establishes only its lettering checks. A new revision is not proof that
   visual issues were verified; retain visual review requirements.

## Operator reconciliation

- **Before submission:** confirm the durable job/action and usage evidence show
  no submission. Absence of a response alone is not sufficient. Unstarted expired
  holds follow the ledger's existing lease rules; started holds need inspection.
- **After submission, no response:** preserve the reservation and request identity.
  Look up the provider operation and usage event. If acceptance or settlement is
  uncertain, retain the incident and hold; never automatically submit another image.
- **Saved output, settlement incomplete:** preserve image bytes, provenance, usage
  call ID, ledger job ID and pending completion evidence. Reconcile the original
  usage with `ai_usage_events` and `credit_ledger`. The existing settlement RPC
  deduplicates by original call identity; never manufacture another call ID,
  debit, refund, or revised amount to silence an alert. Escalate missing or
  conflicting evidence. Release a specific hold only after its liabilities are
  proved settled or absent, using the ledger's owner/lease rules.
- **Export interrupted:** rerun the normal Finish/export HTTP operation after
  inspecting preflight. Packaging can rebuild derived PDF/CBZ files from saved
  complete pages without an image submission. A partial package is not a valid
  export. Preserve source renders; resolve blocking checks before export.

Record reconciliation evidence in restricted operator notes using the incident ID, then verify that the
source observation clears. Resolving an incident does not settle credits,
release a hold, approve creative work, or reopen admission.
