# Slice 10 — Frozen Request Submission and Immutable Reference Bytes

## Fresh-session assignment

Implement only this slice. Read `AGENTS.md`, the sibling `README.md`, this file,
and verify Slice 09's conditioned state request snapshots. Do not begin Slice
11.

## Goal

Make queued image jobs consume an immutable request manifest and immutable
reference-byte snapshots. A request must not change because project files,
prompts, model defaults, or state metadata change after submission.

## Current problem

`ProviderWireRequest` contains reference digests but callers can still pass
mutable project paths. If a file is replaced between compilation and upload, a
job can send bytes that do not match the reviewed request. Recomputing prompt or
reference inputs inside the job creates the same race for structured data.

## Required reading

- Slice 07 wire schema/execution fingerprint and Slice 09 state request handoff
- `novel_to_comic/src/novel_to_comic/server/credited_job.py`
- `novel_to_comic/src/novel_to_comic/stage_runtime.py`
- `novel_to_comic/src/novel_to_comic/artifacts.py`
- draw/rerender job creation and failure-metadata code
- project/version cleanup and storage helpers located through targeted `rg`
- credit reservation/debit tests and image-failure tests

## Domain contract

Introduce a submitted/frozen request record containing:

- immutable request id and timestamps;
- exact portable `ProviderWireRequest` plus `execution_fingerprint`;
- stable content-addressed locators for every selected reference snapshot;
- a manifest digest;
- preparation/source/request versions;
- submission status and result/provenance link;
- no credentials, signed URLs, or provider secrets.

Snapshot locators are storage metadata and must not change
`execution_fingerprint`; selected content digests already identify the bytes.

## Deliverables

1. During submission, read each selected source once, verify its expected digest,
   and write a real immutable copy into a request/content-addressed store. Do not
   use symlinks or mutable hard links. Write atomically and verify the stored
   digest before publishing the manifest.
2. Deduplicate identical content safely by digest. Make blobs write-once and
   reject an existing blob whose bytes do not match its name/digest.
3. Persist the exact wire request and snapshot manifest before enqueuing or
   reserving provider work. If preparation/staging fails, no generation job may
   start.
4. Make the queued job load only the frozen manifest and snapshots. It must not:
   - re-run a prompt LLM;
   - rediscover references;
   - rebuild prompt sections;
   - recalculate model route/capabilities from mutable defaults;
   - read original mutable asset paths for upload.
5. Verify manifest and blob digests again immediately before transport. Corrupt
   staged data fails closed before network I/O.
6. Define retention and garbage collection. Keep manifests with image/version
   provenance. Retain deduplicated blobs while any live request/result record
   references them; remove only unreferenced blobs through an explicit safe GC.
7. Preserve existing credit guarantees: staging/preparation failure does not
   debit image credits, duplicate/idempotent submission cannot double-charge,
   and provider failure follows the existing credited-job contract.
8. If asynchronous prompt preparation is needed, perform it once before request
   freezing under the existing prompt-cost/accounting contract. The queued image
   job consumes the prepared result and never repeats it.
9. Keep request snapshots project-scoped and behind existing authorization. Do
   not expose server paths or cross-project content-addressed blobs through APIs.

## Tests first

- Replace the original reference after enqueue: the job uploads the snapshotted
  bytes and retains the same execution fingerprint.
- Mutate/corrupt a staged blob: transport fails before network I/O.
- Symlink/hard-link shortcuts cannot make a snapshot follow later mutations.
- Same bytes deduplicate; digest collision/mismatch is rejected.
- Prompt/model/config files changed after submission do not change job payload.
- Job code performs no prompt/reference discovery or prompt-model call.
- Partial staging leaves no published request and no credit debit.
- Idempotent duplicate submission does not create two charged jobs.
- GC retains referenced blobs and removes only truly unreferenced content.
- Cross-project request/blob access is rejected.

## Exit criteria

- A submitted job consumes immutable structured data and immutable reference
  bytes.
- Original project-file mutation cannot alter provider input after submission.
- Request manifests are atomic, digest-verified, authorized, and safely retained.
- Credit/idempotency behavior remains correct.
- Focused tests, full backend tests, Ruff, and security review where storage/auth
  boundaries changed all pass.

## Handoff to Slice 11

Write `handoffs/10.md` using the durable handoff template before replying.

Report request/blob storage layout, manifest schema, atomic-write behavior,
retention/GC policy, submission API, job consumption seam, credit behavior, and
security-review result. Slice 11 will route all panel entry points through this
submission contract.
