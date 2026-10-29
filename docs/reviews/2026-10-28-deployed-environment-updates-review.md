# Review: Observable deployed environment updates

**Status: Review and changed requirements, October 28, 2026. For the author of
the "Observable deployed environment updates" proposal (dated October 27, 2026).
Nothing here is implemented or installed.**

This document does two things:

1. It records review findings against the proposal, checked against the current
   repository (not the live host).
2. It adds a new requirement from the owner: **run previews, applies and
   observation from the backoffice**, with full context and observability, not
   only from an operator SSH command.

Revise the proposal to cover both. Keep the parts this review confirms.

## What the review confirmed

The proposal accurately describes the existing code:

- `deploy/lightsail/release.py` accepts only `{image, version, loader_sha256,
  pull_token}` (`validate_request`, line 42) and prints a fixed message.
- `deploy/lightsail/host_agent.py` keeps one `operation.json`, uses a 30-minute
  plan expiry, and shares `/run/canary-release/worker.lock`.
- `compose.yaml` mounts `/run/canary-host` into the app (lines 58–61).
- `scripts/verify_deployment.py` without `--resume` expects admission open
  (line 121), so a drained-verification mode is needed.
- `canary.service` decides whether to start from `ExecCondition=/usr/bin/test ! -e
  /etc/canary/maintenance` only.

Keep these parts unchanged: the per-name public-setting schema, refusing
structural settings, comparing the whole baseline under the lock, old/new ops
token use, refusing an already-drained start, no automatic rollback or retry,
allowlisted event records instead of filtered logs, and the failure table.

## Required fixes to the proposal

### F1. One serializer for `deployment.env`

`release.py:175` writes values with `json.dumps(value)`. `parse_environment`
reads them back with `shlex.split`, and systemd reads the same file with its own
`EnvironmentFile` rules. JSON escapes non-ASCII as `\uXXXX`, and neither reader
decodes that. The shared helpers would be extracted from this writer.

Required: one serializer whose output both readers parse to identical values,
with a round-trip test against `shlex` and `systemd` semantics (for example
through `systemd-run --property=EnvironmentFile=` on the isolated host). The
schema rejects any value outside the character set both readers agree on.

### F2. Decide the restart-budget policy explicitly

`release.py:177` runs `systemctl reset-failed canary.service` before every start.
The proposal says not to reset the restart budget. A shared helper either
changes CI behavior or silently keeps resetting. Decide once in implementation
step 1, apply it to both paths, and test it.

### F3. Lock race between acceptance and the worker

In `release.py` the lock is taken inside the systemd worker (`worker`, line 199),
after the caller was told the request started. CI `dispatch` does not see
configuration operations. A configuration apply can be durably accepted and then
lose the non-blocking lock to CI.

Required: if the worker cannot take the lock, record `rejected_busy` before any
hold, fence or drain exists, and report it as a rejection, not a failure that
needs inspection. While a configuration hold exists, CI should receive a distinct
code (for example `configuration_operation_active` with the operation ID), not
the current `ci_not_activated`.

### F4. `plan` must not write plaintext to disk

Preflight step 5 materializes the candidate during `plan`. If `materialize`
writes files to the `RuntimeDirectory` (verify this in `canary_secrets.py`),
candidate plaintext sits beside the running container for up to the 30-minute
plan lifetime. `prune` runs only after a stop.

Required: `plan` decrypts and validates candidate ciphertext in memory only.
Materialization happens during `apply`, after the old container stops, through
the unit's normal `ExecStartPre`.

### F5. Justify or simplify the startup fence

The proposal's own verification relies on drain persisting across restarts
(`wait_candidate` requires `draining=true` on the new process). If that holds,
an unexpected reboot after publishing starts the candidate drained: unverified
but not accepting work. A simpler design may be enough: keep the plain
`ExecCondition`, create the hold at stop time (as the current fail-closed path
does), and always require an explicit resume.

Required: either adopt the simpler form, or state the specific failure the fence
prevents that persisted drain does not, and keep it.

### F6. Name the recovery attestation for what it is

The host cannot prove independent recovery-key custody. In plans and receipts,
show it as "operator-recorded recovery verification for ciphertext `<digest>`",
never as host-verified evidence.

### F7. Agent use needs per-plan approval

Applying to production is outward-facing and hard to undo. An agent must show
the plan (digest, changed names, restart requirement) and get the user's yes for
that plan before `apply`. One approval never covers a later plan.

### F8. Smaller first version

For one host with infrequent changes, cut from version 1: `history` pagination
and the per-name "affected process" field (a configuration change recreates the
whole container). Keep per-ID operation records, ordered events and receipts;
the backoffice requirement below depends on them.

## New requirement: run it from the backoffice

### The constraint

The backoffice is served by the Canary application, the process this operation
stops and replaces. Nginx returns its fixed `@maintenance` 503 text while the app
is down (`nginx.conf`, lines 42–47). So the backoffice cannot be the only window
into the operation, and "full observability" has to mean:

- **live** while the old app drains (the longest phase, up to 30 minutes) and
  after the candidate is up,
- **durable and complete on reconnect** for the stop → start → readiness gap,
  because every event is journaled on the host,
- **an honest gap** in between: the page shows when it last heard from the host
  and never invents a current phase.

The existing Host maintenance panel already works this way
(`web/src/components/HostMaintenancePanel.tsx`; `docs/ops/host-maintenance.md`).
Follow its patterns.

### Architecture

One host controller, two clients:

```text
Backoffice (browser)
   │  ops token, HTTPS
   ▼
Canary app  /api/backoffice/config/*   (thin, bounded proxy; no decisions)
   │  private Unix socket (existing /run/canary-host mount)
   ▼
Host controller (extended host agent, root)  ◄── operator SSH forced command
   │  shared /run/canary-release/worker.lock          (CLI: break-glass and
   ▼                                                    recovery, same protocol)
systemd worker → drain, stop, publish, start, verify, resume
   │
   └─ /var/lib/canary-config/operations/<uuid>/  (request, plan, events, receipt)
```

- Extend `host_agent.py` (or add a sibling controller on the same socket
  directory) with fixed actions `config_plan`, `config_apply`, `config_status`,
  `config_events`. Do not build a second, independent workflow.
- The app router only validates shapes and forwards, like
  `server/routers/backoffice.py:1031–1047` and `server/host_maintenance.py`.
  The controller makes every decision.
- Keep `scripts/canary_config.py` over SSH as the break-glass path. It must be
  able to observe and recover an operation the backoffice started, and the
  reverse.

### Security: what the app socket may and may not change

This reverses the proposal's "the application socket gains no configuration
mutation action". The ops token already authorizes host updates and reboots, but
configuration is a larger blast radius:

- A compromised app process already holds every secret value and the bundle's
  public recipients. It could encrypt a valid bundle that points database,
  Supabase or Stripe settings at attacker infrastructure. That change would
  survive the compromised container.

Required boundaries:

1. **Bundles are operator-signed.** The operator runs `canary_secrets.py set`
   and `verify` on their own machine, then signs the ciphertext digest with a
   key that never reaches the host or the app. The controller verifies the
   signature against a pinned public key installed with the host tooling. The
   backoffice only uploads the ciphertext and detached signature; plaintext
   never enters the browser or the app. An unsigned bundle is rejected before
   any work.
2. **Public settings are classed in the schema.** Each name declares
   `backoffice: editable | ssh_only`. Start with low-risk operational switches as
   editable (for example `CANARY_RUNWARE_FIRST_ENABLED`). Anything that changes
   routing, origins, auth or billing is `ssh_only` or structural.
3. **Not from the backoffice in version 1:** `CANARY_OPS_TOKEN` rotation (the
   browser's token stops working on the candidate mid-operation; see below),
   recipient changes, and structural settings.
4. **Attribution.** Record the backoffice user identity (if the backoffice has a
   signed-in admin in addition to the ops token, record that user's ID) and the
   transport (`backoffice` or `ssh`) in the request and receipt.
5. **Bounded upload.** The current socket protocol is one JSON line with a
   256 KiB response cap. Ciphertext for a bundle up to the loader's 1 MiB limit
   plus SOPS and base64 overhead needs an explicit, finite request bound, or a
   separate staged-upload action with digest checks, exclusive root-owned
   staging and atomic publication.

### Backoffice experience

A new Backoffice view, **Environment**, next to **Host maintenance**.

**Current state (always visible)**

- Accepted environment revision, image digest, source SHA, bundle digest,
  loader digest, and whether accepted and running state match (drift is shown
  as a blocking problem).
- The editable public settings with their current values and schema
  descriptions; `ssh_only` names listed read-only.
- Secret names in the current bundle. Names only, never values or hashes.
- The last operation and its receipt.

**Plan**

- Edit public values in a form validated against the schema, and/or attach a
  signed ciphertext bundle.
- **Preview** calls `config_plan`. The result shows: each public value old →
  new; secret names marked added/changed/removed; prerequisites and their
  results (for example "Runware route requires `RUNWARE_API_KEY`: present");
  restart required or no-op; current generation activity that a drain will wait
  for; plan digest; and an expiry countdown.
- A stale or expired plan disables Apply and says why
  (`baseline_changed`, `plan_expired`, `ci_release_active`).

**Apply**

- A confirmation step restates the plan digest, the changed names, "generation
  stops accepting new work and Canary restarts", and the 30-minute drain
  deadline. Apply sends the plan ID, its digest and a client-generated request
  UUID. Repeating the same request returns the same operation.

**Live operation view**

- A phase timeline with timestamps and elapsed time:
  `accepted → preflight → draining → saving_previous → stopping → installing →
  starting → verifying_local → verifying_public → resuming → complete`.
- An ordered event log with each event's intent and result. An intent with no
  result is shown as "unconfirmed", never as done.
- During draining: the allowlisted blocking counters (active and queued work by
  kind), the deadline, and the time of the last successful check.
- Each verification check with pass/fail and duration.
- A connection indicator: "last heard from host at T". When the app goes away,
  the page says contact is lost because Canary is restarting, keeps the last
  observation, and retries with backoff. It does not show a guessed phase.
- On reconnect, it fetches events after the last sequence it has, so the gap is
  filled in from the journal.
- Poll `config_events?after=N` every 2–3 seconds while an operation is active
  (the existing panel's 15 seconds is too slow for this), and 15 seconds when
  idle. Polling is enough; do not add SSE or websockets.

**Outcome**

- Complete: receipt with before/after revisions, image/SHA, bundle digest,
  changed names, every check result, observed admission state and duration.
- Failed or needs inspection: the failed phase, the fixed error code, what state
  the host is in (hold present, which container is running, admission state)
  and the next recovery action in plain words. If the candidate never comes up,
  the backoffice is unreachable; the page must already have told the operator
  that recovery then needs the SSH command, and which command.

### Optional: status while the app is down

Nginx could serve a small, sanitized status file written by the worker (for
example `/_ops/config-operation.json` with operation ID, coarse phase, sequence
number and last update time) when the app is down. That would close the
observability gap without SSH. The cost is that nginx cannot check the ops token
while the app is down, so either the file is public (it reveals that maintenance
is happening and which phase failed) or it needs a separate credential in the
nginx configuration. **This is the owner's decision.** Version 1 can ship
without it; design the event records so the file can be added later.

### Ops token handling across the restart

The browser holds the old ops token. Version 1 forbids token rotation from the
backoffice, so the same token works on the candidate. The controller still uses
the token from each process's own bundle internally (old for drain, candidate
for verify and resume), as the proposal says. Rotation stays an SSH operation.

## Tests to add (provider-free)

Add these to the proposal's existing list:

- Serializer round trip for `shlex` and systemd `EnvironmentFile` (F1).
- `reset-failed` policy shared by CI and configuration paths (F2).
- Lock lost after acceptance → `rejected_busy`, no hold, no drain (F3).
- `plan` leaves no plaintext under the runtime directory (F4).
- Backoffice router: shape validation, forwarding only, no decision logic,
  identity recorded, oversized upload rejected.
- Unsigned or wrongly signed bundle rejected before preflight.
- `ssh_only` names rejected from the backoffice transport; accepted over SSH.
- Ops token rotation rejected from the backoffice.
- Frontend: plan diff rendering, stale-plan disabling Apply, live timeline from
  events, intent-without-result shown as unconfirmed, contact-lost state, event
  catch-up after reconnect, failure receipt with recovery instructions.
- An operation started from the backoffice is observable and recoverable over
  SSH, and the reverse.

## Delivery order

1. Shared transaction helpers with F1–F3, drained verifier mode; CI behavior
   unchanged except for the explicit F2 decision.
2. Controller actions, schema with backoffice classes, operation journal, SSH
   CLI. Public settings only, same bundle and image.
3. Backoffice **Environment** view: state, plan, apply, live operation view,
   receipts.
4. Signed bundle upload (CLI and backoffice) with in-memory plan validation (F4).
5. Isolated-host rehearsal of every failure boundary from both clients, then a
   production no-op plan from the backoffice. The first real production change
   stays a separately authorized operation.
