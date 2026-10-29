# Observable deployed environment updates

**Status: Accepted design, October 28, 2026. Implemented locally; production
installation and isolated-host acceptance remain outstanding. The current
[operating guide](../ops/configuration-updates.md) owns implementation and
activation instructions; this document preserves the reviewed design.**

This revision incorporates the [October 28 review and changed requirements](../reviews/2026-10-28-deployed-environment-updates-review.md).
The backoffice is the primary client; operator SSH is the independent observation
and recovery path. Production mutation requires approval of the specific plan.

## Decision and scope

One host controller owns configuration plans, applies, observations and receipts.
Two clients use the same protocol: a backoffice **Environment** view beside
**Host maintenance**, and `python3 scripts/canary_config.py` over restricted SSH.
The controller reuses the release transaction and exclusive lock. There is no
second restart workflow in the app, browser or CLI.

An update recreates the existing immutable application image with a reviewed
public configuration and/or operator-signed encrypted secret bundle. It does not
build an image, run generation or change settings in place. Each apply has a
persistent UUID, ordered events and a receipt. Losing a connection does not
cancel the worker or authorize a new request.

Version 1 retains per-ID operations, event catch-up and receipts. It omits history
pagination, per-setting affected-process fields, SSE/websockets, a public Nginx
status endpoint and backoffice recovery overrides. The whole container restarts.

## Repository evidence

These observations describe checked-in code, not a fresh live-host inspection:

- [release.py](../../deploy/lightsail/release.py) accepts exactly image, version,
  loader digest and pull token. It takes `/run/canary-release/worker.lock` inside
  the worker, after dispatch; acceptance does not prove lock ownership. It writes
  values with `json.dumps`, reads with `shlex.split`, calls `reset-failed` before
  start and emits fixed success/failure output.
- [host_agent.py](../../deploy/lightsail/host_agent.py) shares that lock, has a
  30-minute package-plan lifetime, runs outside HTTP and retains one latest
  `operation.json`. Its socket directory is mounted into the app by
  [Compose](../../deploy/lightsail/compose.yaml). Its `UnixStreamServer` handles
  one connection at a time with a 20-second timeout; its handler currently
  replaces every error with the same generic message. Both need changing before
  the backoffice can provide responsive observations and actionable rejections.
- [canary_secrets.py](../../scripts/canary_secrets.py) provides allowlisted,
  in-memory secret changes, exact recipient checks and mount-aware pruning.
  `materialize` writes `runtime.json` and credential files into a staging
  directory, then publishes a digest-named runtime directory. Calling it during
  preview would leave candidate plaintext beside the running release.
- [canary.service](../../deploy/lightsail/canary.service) starts only when
  `/etc/canary/maintenance` is absent; its normal `ExecStartPre` materializes
  secrets. [Admission](../../novel_to_comic/src/novel_to_comic/server/admission.py)
  persists drain intent in SQLite and reloads it on process startup.
- [verify_deployment.py](../../scripts/verify_deployment.py) checks public
  contracts, but without `--resume` expects admission open. Add a drained mode
  to separate checks from explicit resume.
- The ops-token-protected [backoffice router](../../novel_to_comic/src/novel_to_comic/server/routers/backoffice.py)
  and [host transport](../../novel_to_comic/src/novel_to_comic/server/host_maintenance.py)
  already forward fixed host actions. The transport caps responses at 256 KiB;
  the host currently accepts a single JSON line of at most 4096 bytes.
  [HostMaintenancePanel](../../web/src/components/HostMaintenancePanel.tsx)
  retains observations when contact fails and polls every 15 seconds.

## Architecture and authority

```text
Backoffice Environment view (ops token over HTTPS)
  → /api/ops/backoffice/config/* (bounded authenticated proxy)
  → private Unix socket under /run/canary-host
  → host configuration controller ← restricted operator SSH / canary_config.py
  → plan worker (snapshot only) OR apply worker (shared release lock)
  → drain → stop → publish → start → verify → resume
  → /var/lib/canary-config/operations/<uuid>/
```

Extend the host agent with fixed `config_plan`, `config_apply`, `config_status`
and `config_events` actions, delegating to a sibling configuration module if
needed. The app validates transport shapes, authenticates, attaches attribution
and forwards; the host owns schema, authorization classes, signature checks,
staleness decisions and every lifecycle action. Reads remain responsive while
a bounded systemd worker runs independently of the request and application.

Suggested HTTP mapping, using the existing mounted router prefix:

| Endpoint under `/api/ops/backoffice/config` | Host action |
| --- | --- |
| `GET /status`, optional operation ID | `config_status` |
| `POST /plan` | `config_plan` |
| `POST /apply` | `config_apply` |
| `GET /events?operation=UUID&after=N` | `config_events` |
| `POST /bundles` (step 4, upload socket) | `config_stage_bundle` |

HTTP plan/apply returns 202 only for durable acceptance, never as proof of a
ready plan or successful apply. Each request has an ID; clients poll status/events
for `plan_ready`, a rejection or an apply outcome. CLI plan follows that same
asynchronous protocol and may wait for readiness before displaying the preview.

Replace the serial socket server with a threaded server with a hard concurrency
limit: eight control handlers, with a permit acquired BEFORE spawning a thread.
Do not wait for a free permit on the accept loop or create unbounded waiting
threads; reject excess connections with a fixed busy response where possible.
No control handler runs SOPS, Compose, image inspection or long-lived plan/apply
work. Plan launches a short, bounded systemd worker, as the current maintenance
check does, and returns its ID. Bound queued/running preview workers independently
(one per host initially); polling does not occupy a worker slot.

Keep the existing control socket's small request limit. For step 4, add a separate
bounded upload socket under the already mounted `/run/canary-host` directory,
with at most two handlers; its slow uploads cannot consume control slots.
Use the same controller, authorization and operation store behind both sockets,
not an independent workflow. Upload replies contain a staged ciphertext ID;
ordinary plan requests reference it. Status/events read bounded persisted records
without expensive live subprocess probes or waiting for a plan/apply lock.
Mutating handlers and workers protect shared records with short controller locks;
never hold them during upload, subprocess work or external calls.

In step 1 add a structured handler error envelope with an explicit allowlist of
fixed codes, including `rejected_busy`, `baseline_changed`, `plan_expired`,
`ci_release_active`, `configuration_operation_active` and signature/permission
rejections. Only known codes and validated operation IDs cross the boundary;
unknown exceptions retain a generic failure, without exception text or subprocess
output. The app forwards recognized codes and safe context to the UI instead of
collapsing them into its current generic 409. Distinguish transport phases:

- A failed socket connect before any send returns `host_agent_unavailable`, with
  `request_sent=false`: this proxy attempt did not submit the request.
- Once a send is attempted, a partial/failed send, timeout, lost connection or
  missing/invalid reply returns `request_outcome_unknown` with the pre-generated
  request UUID. Never describe this as proof that the agent is unavailable or
  that apply failed. The UI retains the UUID and observes that operation through
  status/events (or SSH), rather than repeating apply or just waiting blindly.

Preserve this distinction in structured proxy errors even if both use HTTP 503;
do not infer submission from the HTTP status alone. A lost browser-to-app reply
also leaves submission uncertain. Keep old maintenance request/result shapes
compatible while allowing
the new structured conflict diagnostic; do not add detail to unrelated errors.

The socket gains bounded configuration mutation authority. A compromised app
already has secrets and recipients and could encrypt a new bundle; encryption
alone therefore cannot authorize a persistent configuration change. Apply the
following additional boundaries to both planning and applying:

- Each public setting declares `backoffice: editable | ssh_only`. Start with
  bounded operational switches such as `CANARY_RUNWARE_FIRST_ENABLED`. Routing,
  origins, authentication and billing settings are SSH-only or structural. The socket
  cannot claim to be SSH: the controller derives transport from its entry point,
  rejects caller-supplied transport overrides, and creates transport-bound plans.
  Applying a plan through a different client rechecks that client's permissions.
- Every new bundle is operator-signed, including SSH uploads. The signing private
  key stays on the operator machine, separate from the host and app. Install the
  pinned verification key with reviewed host tooling; requests cannot choose it.
  Verify the detached signature before decrypting candidate data or running
  candidate preflight. Missing/wrong signatures fail closed. For unchanged active
  bundles, existing accepted provenance remains valid; bootstrap does not require
  sending the current bundle through the browser again.
- Bind the canonical signed manifest to production target, candidate ciphertext
  digest, the accepted bundle digest it REPLACES, a unique authorization ID and
  expiry. Do not sign the image/source SHA or full environment baseline: an
  intervening CI image release requires a new plan/approval, not re-signing an
  otherwise valid bundle replacement. A different accepted bundle invalidates
  that authorization. Store manifest/signature with immutable ciphertext and
  check expiry/replacement digest again at apply; the plan independently binds
  the full deployment/tooling baseline.
- Keep a root-only durable used-authorization-ID ledger outside `/run`, surviving
  reboot. The order is: WIN the release lock, revalidate baseline/permissions/
  expiries, atomically reserve the authorization ID for this operation and fsync
  it, THEN create the hold and drain. Losing the lock produces `rejected_busy`
  without reserving or consuming any authorization ID. Retain consumed IDs at
  least through signed expiry; fail closed if the ledger cannot be read/written.
  Planning never consumes an ID. Another operation cannot use a reserved ID,
  including after failure; obtain a new signed authorization for another attempt.
  An identical apply request UUID first returns its existing operation, so lost
  responses do not consume twice. Persist the operation binding with the ledger
  reservation; an interrupted reservation requires inspection, never reuse.
  The signature format and signing command must be reviewed and documented
  before bundle delivery is implemented.
- The browser uploads ciphertext, manifest and detached signature only; plaintext
  never enters the browser/app. `CANARY_OPS_TOKEN` rotation, recipient changes
  and structural settings are unavailable from the backoffice in version 1.
  The host compares old/new ops tokens privately rather than trusting a declared
  changed-name list. SSH retains ops-token rotation; recipient changes retain
  their separate reviewed procedure.
- Record transport and authenticated attribution in request, events and receipt.
  Current backoffice authorization is a shared ops token, not an independently
  verified individual admin identity. Label it `ops_token` without storing the
  token; do not invent a user ID. If signed-in admin authentication is available,
  attach its server-verified user ID. Browser-submitted identity is not trusted.
  SSH attribution comes from the installed forced-command key/principal mapping.

The app token cannot authorize arbitrary commands, paths, image selection,
Docker access, signing-key replacement or host tooling installation.

Backoffice-editable does not mean cost-neutral. `CANARY_RUNWARE_FIRST_ENABLED`
and `CANARY_RUNWARE_TEXT_FALLBACK_ENABLED` select which provider receives paid
requests. A compromised app can change these allowed public switches and request
drain/restart cycles WITHOUT a bundle signature. Per-plan human confirmation is
operator UX, not protection against a compromised app bypassing the browser.
This bounded authority and availability/cost exposure must be accepted at
activation; label provider/cost effects in the schema description and preview.
Keep billing rates, arbitrary provider endpoints and credentials outside that
editable class. Signing bundles does not remove this remaining threat.

## Public schema and environment serialization

Install a root-owned setting schema alongside the reviewed Compose file. Each
name declares type, description, empty/unset semantics, validation, backoffice
class and its real projection into the installed template. No affected-process
field: applying any change recreates the complete container. Reject unknown
names, duplicate keys, wrong types and unsupported projections. Adding a name to
`deployment.env` alone cannot make it reach a container.

The image, source version, loader digest, bundle paths, public origin, proxy
trust, volume mounts, worker topology and security controls are structural.
They use reviewed releases/host installation, not generic setters. The host
alone derives bundle paths from ciphertext digests. SSH-only is a permission
class, not a bypass of schema or structural restrictions.

Use ONE environment serializer in shared helpers for CI and configuration
writes. Version 1 conservatively accepts printable ASCII values excluding double
quote, backslash, dollar sign and backtick; reject non-ASCII, CR/LF, NUL and other
controls instead of escaping them with JSON. Write each value inside literal
double quotes, including an empty value when its schema permits it. Existing
out-of-domain accepted values require an explicit reviewed migration; never
silently change or escape them. Keys retain the existing uppercase-name rule.

Require exact round trips through `parse_environment`/`shlex.split` and real
systemd `EnvironmentFile` loading on the isolated host. Include empty values,
spaces, single quotes, leading/trailing spaces and URI punctuation, plus rejected
Unicode/escape/control cases. Also verify Compose receives those exact process
environment values using a clean environment and `--env-file /dev/null`.
For values in this new domain, the current `json.dumps` writer already emits
the same quoted bytes: existing supported ASCII values will not change merely
because the serializer is replaced. The stricter validation rejects unsupported
inputs instead of silently producing a different meaning. The production no-op
rehearsal must privately inspect the LIVE `deployment.env` against the new domain
and report incompatible key names only, without exposing values. Do not extract
the current unrestricted `json.dumps` writer as the shared serializer.

## Planning and approval

`config_status` returns the accepted environment revision, image digest, source
SHA, bundle/loader digests, accepted/running match, schema-readable public values,
secret names only, active/last operation and its receipt. Drift is a blocking
problem. A status request may specify any retained operation ID; version 1 does
not require a browsable paginated history.

Accepted/running match is a CACHED observation, not a fresh Docker/systemd query
inside every `config_status`. A separate bounded probe captures container identity,
systemd state and health, compares them with the accepted revision, and atomically
publishes `observed_at`, the revision it compared, and `match | drift | unknown`.
Run at most one probe at a time, every 15 seconds while observed, with a 10-second
overall deadline. Status returns this cache immediately without waiting for a
probe. A failed probe marks the current result unknown and preserves the last
successful observation with its own timestamp; it never refreshes that timestamp
by merely reading the cache. The UI shows age and treats observations older than
30 seconds, unknown results or mismatched accepted revisions as stale and disables
mutation. Apply still performs its own live revalidation under the release lock;
a fresh cache does not replace that check.

The existing package-maintenance `status` action remains an inline sequence of
systemctl, Docker and health calls. Each such request occupies ONE of the eight
control-handler slots for its entire lifetime, not a free background slot. Give
that sequence a 20-second overall execution budget; a socket I/O timeout alone
does not bound subprocess execution. Include these legacy requests in concurrency limits and
responsiveness tests alongside cached config status and event reads.

A plan NEVER takes `/run/canary-release/worker.lock`: a preview must not make CI's
non-blocking lock attempt fail. Its short worker captures immutable configuration
and tooling metadata under only the short controller lock, then releases that
lock before decryption/rendering/inspection. Shared publication helpers briefly
use the controller lock when publishing accepted config/ownership metadata, not
throughout a deployment. Read-only observations may race a deployment: compare
the snapshot/revision again before publishing `plan_ready`, and report
`baseline_changed` if it moved. This is an advisory preview, not a reservation;
apply rechecks the whole baseline under the release lock. The plan makes no
admission, service or accepted configuration changes. It may store private plan
metadata and reference staged ciphertext.
It MUST NOT invoke `materialize`, write decrypted files to tmpfs/disk, or mount a
candidate. Decrypt existing and candidate bundles in host memory only; store
secret names and added/changed/removed categories, never values or per-secret
hashes. Memory-only validation does not establish future provider acceptance.

Preflight must:

1. Require the production target, installed activation marker, active single
   owner, no maintenance hold and no already-drained application. Recovery is
   separate. Report conflicting CI/maintenance operations without changing them.
2. Capture the accepted environment revision, controller/schema/Compose/verifier
   hashes, image/source SHA, loader and bundle digests. Check actual running
   container/local version; refuse accepted/running drift.
3. Apply the typed patch, validate projection and render Compose privately with
   a clean environment. Do not forward raw renderer output/errors.
4. For a new bundle, verify signature/manifest before candidate preflight;
   validate ciphertext digest, exact existing recipients, bundle schema and ADC
   delivery configuration in memory. Reject forbidden token rotation by transport.
5. Check credential prerequisites (for example Runware requires `RUNWARE_API_KEY`),
   cached unchanged image/loader agreement, tmpfs and swap policy without writing
   plaintext. No registry token, image pull or paid provider request is needed.
6. Store an immutable ready plan with a 30-minute expiry starting at readiness,
   baseline/tooling/candidate digest and authorization class. Include public
   old → new values, secret change
   names, prerequisite results, restart/no-op, current generation activity and
   expiry. Apply repeats validation and compares the WHOLE baseline under lock;
   any change requires a fresh preview and approval.

For a signed bundle, expose both `plan_expires_at` and
`authorization_expires_at`; `effective_expires_at` is the earlier one. Without a
new signed bundle, effective expiry is the plan expiry. The preview countdown and
Apply enablement use effective expiry and host time. Return `plan_expired` when
the plan deadline is the first expired deadline, or `authorization_expired` when
the signed authorization deadline is first (plan takes precedence on an exact
tie); display which limit expired and both deadlines. Allowlist both codes.
Recheck both under the release lock before reserving the authorization ID or
creating a hold. Once validly committed to apply, a deadline passing during drain
does not cancel that authorized transaction or cause replay.

Secret preparation remains `canary_secrets.py set` and `verify` on the operator
machine, with values read privately and no decrypt-to-disk shortcut. Record
**operator-recorded recovery verification for ciphertext `<digest>`** in plans
and receipts. This is an attestation, never host-verified independent custody.
The signature authenticates the operator's statement, not its truth.

A human reviews the backoffice confirmation for this exact plan before Apply.
An agent must show the plan digest, changed names and restart requirement and get
the user's explicit yes for that plan before production apply. General task
authorization, an earlier plan's approval or bundle signing is insufficient.
A replacement, changed or expired plan requires a new yes. Once approved, the
worker completes that plan without repeated step-by-step confirmations.

A no-op plan reports no restart; its approved apply records a no-op receipt
without draining or recreating anything.

## Acceptance, concurrency and shared behavior

Extract shared context, validation, serializer, drain, save/publish, replacement,
verification and resume helpers from `release.py`. Keep image acquisition and
image provenance in CI. CI retains its existing four-field request and success
output; new conflict errors are intentional protocol diagnostics.

Decide restart-budget behavior in the first implementation step: **remove the
unconditional `systemctl reset-failed canary.service` from CI and configuration
start paths**. Both use the same bounded policy and report `start_limit_hit`.
Only an operator who has diagnosed the cause may reset the budget during explicit
recovery. Test both paths. Existing host-package maintenance's separate policy
is unchanged by this extraction; do not silently move its reset into a shared
start helper or claim that all existing callers already use the new policy.

Retain `/run/canary-release/worker.lock` across each transaction. Acceptance is
recorded under a separate short controller lock before launching the worker.
Per-ID operation records retain immutable request identity and payload digest:
repeating an ID with the same payload returns its operation; a changed payload
is rejected. A lost launch result is inspected, not blindly relaunched.

The accepted worker may lose the non-blocking release-lock race to CI or host
maintenance. It must record terminal `rejected_busy`, with the conflicting
operation ID when known, before creating any hold, draining or mutating config.
This is a rejection, not `needs_inspection`. Known conflicts before acceptance
are rejected immediately. Acceptance alone never claims the release lock or
reserves a bundle authorization ID; reservation happens only after winning the
lock and revalidating the candidate.

While a configuration-owned hold exists, CI reports the fixed code
`configuration_operation_active` and its operation ID, not `ci_not_activated`.
Check that ownership before the generic maintenance/activation gate in dispatch
and again in the worker. Existing host-maintenance submit and worker checks must
also return `configuration_operation_active` with the ID when this hold exists,
instead of `existing_maintenance_hold_requires_operator`. Other holds retain
their own diagnostics. Use a private
durable ownership record tied to the exact hold inode; never remove or claim an
unrelated/replaced hold. Lost/ambiguous ownership requires inspection.

## Host transaction and restart safety

A bounded systemd worker survives browser/SSH disconnects. Successful phases:

```text
accepted → preflight → draining → saving_previous → stopping
         → installing → starting → verifying_local → verifying_public
         → resuming → complete
```

After winning the release lock and revalidating the approved plan and both
applicable expiries, reserve/fsync any new bundle authorization ID, then create
the owned maintenance hold before drain; keep the existing plain systemd
`ExecCondition`. Wait for BOTH `draining=true` and `safe_to_deploy=true`, with the
current 30-minute deadline. Preserve unstarted durable work. Report queued work
separately from blockers: queued durable commands remain preserved, not a reason
to wait for an empty queue. Never infer idle from container state or quiet logs.
Drain gates project mutations; backoffice operations remain accessible during
this phase. Configuration operations NEVER create
`/var/lib/canary/public-maintenance`: Nginx tests that independent file across
all `location /`, including `/api/ops`, and would black out the backoffice.
If an operator has already enabled that external gate, report it during preflight
and require them to resolve it; the tool neither creates nor removes it.

Save the complete prior environment/image/bundle/loader pairing. Stop the service,
then atomically publish the candidate environment and revision with file and
parent-directory fsync. Retain ciphertext under immutable digest names. Remove
only this worker's hold immediately before deliberate start. The unit's normal
`ExecStartPre` materializes the candidate AFTER the old container stopped; plan
and pre-stop apply validation never materialize it. Never edit live mount sources.

Adopt the simpler startup model; remove the proposed additional startup fence.
Persisted drain is the admission barrier across restart. A crash/reboot while
hold is present prevents startup; after its removal the candidate may start,
but must remain drained and cannot accept new work until verified and explicitly
resumed. That distinction is acceptable: an unverified running process is not
proof of release acceptance. Verify persistence on an isolated host before
activation; fail the rollout if a candidate can start undrained. Configuration
operations do not use the host-maintenance automatic reboot-recovery path.

Verify exact image/source SHA, new container identity, bundle mount digest and
allowed effective public settings. Compare secret delivery privately against the
loader's process scopes; publish only match/mismatch by name, never values,
value hashes, raw `docker inspect` or `/proc` output. Verify local readiness and
persisted drain, then public liveness, readiness, dependencies, model mode,
pipeline contract and headers. These checks submit no paid work.

`Restart=on-failure` remains active during verification, with three starts per
300 seconds. Compose sets `restart: "no"`, so Docker has no independent automatic
restart policy: systemd is the restart owner. Pin the candidate container ID and
record the systemd invocation,
restart counter and start identity when local verification begins. Recheck them
at public verification and immediately before resume; inspect the recorded
restart transitions as well, so a crash/restart with a healthy replacement cannot
pass verification. Any candidate restart during verification is a failed check,
even if the image/SHA is unchanged. Missing or ambiguous restart evidence fails
closed. Do not silently repin to the replacement container or reset the budget.

Use the OLD ops token to drain the old process and the CANDIDATE token to verify
and resume the new one. Backoffice token rotation is forbidden, so the browser's
token remains valid after restart; SSH can rotate it. Separate drained verifier
checks from explicit resume and emit each check's result. Confirm admission open
before committing completion. A lost resume response requires reading admission;
never stop a potentially working candidate just because the response was lost.

## Backoffice Environment experience

Follow the existing Host maintenance panel's operator connection and contact-loss
patterns, extending its context and operation detail:

- **Current state:** accepted revision, image/source SHA, bundle/loader digests,
  drift status, public values with schema descriptions, SSH-only names read-only,
  secret names only and the last operation/receipt. Do not display secret values
  or per-secret hashes. Disable mutation on drift, stale observations or conflicts.
- **Preview:** editable public form and optional signed ciphertext attachment.
  Preview returns a worker ID; show its bounded checking progress while polling
  until `plan_ready` or a fixed rejection. Other operation observations remain live.
  Show each public old → new value, secret additions/changes/removals,
  prerequisite results, restart/no-op, active/preserved queued work, plan digest
  and host-based countdown to the earlier plan/authorization expiry, including
  provider/cost effects for switches. Show which deadline limits the plan.
  Disable Apply with a specific reason such as
  `baseline_changed`, `plan_expired`, `authorization_expired` or
  `ci_release_active`; the host still makes the authoritative decision at apply.
- **Confirm:** restate digest, changed names, restart requirement, the 30-minute
  drain deadline and “Generation stops accepting new work and Canary restarts.”
  No-op confirmation states no restart instead. Explain before apply that a
  candidate which never returns requires SSH recovery, and show the exact status
  command with this request UUID. Generate/preserve the UUID BEFORE submission;
  retain non-secret plan/operation IDs across refresh without storing the token.
- **Observe:** phase timeline with timestamps/durations, ordered intent/result
  events, unpaired intent shown as “unconfirmed”, allowlisted drain counters and
  deadline, last successful check and verification pass/fail/duration. Poll events
  every 2–3 seconds while active and status every 15 seconds when idle. Use bounded
  event batches with `after`/next sequence for catch-up; no history pagination.
- **Connection gap:** display “last heard from host at T”. On losing the app,
  retain observations and say “Contact lost; Canary may be restarting. Current
  host state is unknown.” Retry read-only requests with bounded backoff; never
  guess a phase, mark failure from a 503 alone or automatically repeat apply.
  Resume fast polling and fetch events after the last confirmed sequence on
  reconnect. A poll predating apply cannot overwrite the submitted operation.
- **Outcome:** completion receipt with before/after revisions, image/SHA,
  ciphertext digest, changed names, check results, observed admission and duration.
  Rejection explains the conflict without suggesting recovery. Failure/inspection
  shows failed phase, fixed error, hold/container/admission observations with their
  timestamps, and a plain-language next recovery action.

The old app remains observable during drain, usually the longest phase. Stop,
start and readiness can make the backoffice unreachable through Nginx's fixed
503 maintenance response. Events during that gap remain durable on the host and
are complete on reconnect. If the candidate never returns, use SSH independently.
No client can promise live observations of an unreachable host.

A future sanitized Nginx-served status file could expose coarse phase during the
gap. Version 1 does not add it. Public exposure versus separate Nginx credentials
is explicitly an owner decision for a later change, not assumed authorization.

## Observation, failure and recovery

Store root-only records at `/var/lib/canary-config/operations/<uuid>/`: immutable
request/plan metadata, ordered events, snapshot and final receipt. Persist intent
before consequential actions and result after observing them. Events use monotonic
per-operation sequences, UTC time, phase, duration, fixed error/result code and
allowlisted evidence. Recover snapshots from the journal; an unpaired intent is
uncertainty, not proof that an action executed. Return bounded event batches so
large operations never overflow the 256 KiB response cap.

Use the same allowlisted events for the browser, SSH watch and journald. Include
transport/attribution, drain blockers and preserved queued counts, deadline,
verification results, hold owner and next recovery action. Never emit tokens,
plaintext config dumps, per-secret hashes, manuscript/project data, prompts or
raw subprocess errors. Construct safe records rather than filtering raw logs.

| Failure boundary | Required result |
| --- | --- |
| Validation or stale plan before drain | Reject; accepted config and running owner untouched. |
| Worker loses lock after acceptance | Terminal `rejected_busy`; no authorization-ID reservation, hold, drain or config mutation; no recovery required. |
| Drain timeout/error | Keep existing process running and admission drained; retain own hold for explicit recovery. Do not automatically resume. |
| Stop/install/start/check failure | Retain or re-establish own hold; stop an unverified candidate once stop is safe; preserve both config pairings and evidence. No automatic rollback or resume. |
| Resume response lost | Query admission. If unknown, record `needs_inspection`; do not stop, roll back or repeat apply. Work may already have started. |
| Worker killed or host reboots | Reconcile intent, boot ID, systemd, accepted revision and actual container; record interrupted/unknown state. Preserve existing hold; no automatic replay or resume. Candidate may already be running drained if the hold had been removed. |
| Client disconnect | Worker continues; either client retrieves the same operation and events by ID. |

Before resume is attempted, replacement failures can stop the candidate under
the fail-closed policy. After resume is attempted, any further stop requires a
fresh authenticated drain and positive idle proof. Cover this distinction when
extracting release helpers.

Recovery uses operator inspection and the existing release verification/resume
procedure under the shared lock, regardless of which client started the change.
SSH status/watch can observe backoffice operations; backoffice status/events can
observe SSH operations whenever the app and its current token are reachable.
An operation rotating the ops token requires the browser to reconnect with the
new token. There is no browser bypass for clearing a hold or overriding a failure.

Version 1 supplies recovery instructions rather than a generic retry/rollback
button or automatic recovery command. Selecting an old bundle can restore revoked
credentials or change database routing. Reconcile writes and queue/credit state
before rollback. Keep both pairings and receipts; pruning is separate maintenance.

## SSH interface and bounded delivery

Proposed commands (not implemented):

```sh
python3 scripts/canary_config.py plan --target production --set CANARY_RUNWARE_FIRST_ENABLED=true
python3 scripts/canary_config.py apply --target production --plan PLAN_ID --expect-plan-sha256 PLAN_SHA256 --request-id REQUEST_UUID --watch
python3 scripts/canary_config.py status --target production --operation REQUEST_UUID
python3 scripts/canary_config.py watch --target production --operation REQUEST_UUID --after 12
```

After approval of a concrete plan, apply authorizes its drain/recreate/verify/resume
sequence. `--watch` follows progress; otherwise return after durable acceptance.
Provide stable JSON output and distinct exit statuses for complete, accepted,
rejected, failed and transport outcome unknown. Do not equate durable acceptance
with completion. For signed bundles, plan also takes ciphertext path/digest,
manifest and detached signature paths; those local paths are never remote paths.

Use a dedicated operator forced-command entry point with pinned SSH host checking,
exact sudoers authorization and installed key-to-principal mapping. It invokes the
same host actions, but with host-derived SSH authority. The CI key retains image
release authority only. Retain verified operator firewall access; do not open SSH
worldwide, move recovery/signing identities onto the host or import secrets into CI.

For version 1 use an explicitly bounded upload request: cap ciphertext at 2 MiB,
its canonical manifest at 4 KiB and detached signature at 16 KiB; cap the complete
base64 JSON socket request at 3 MiB before parsing. Keep ordinary actions at their
small bound and responses at 256 KiB. Reject any file exceeding its bound before
upload; a loader-valid bundle whose encrypted representation exceeds the delivery
cap is refused explicitly, never truncated or silently given a larger limit.
Validate the allowance against real worst-case dummy SOPS output in tests.

The proxy must enforce HTTP body bounds before buffering and use the separate
bounded upload socket with explicit limits/timeouts. Apply the complete base64
JSON request cap to that socket only; control requests remain at their small
limit. Reject excess concurrent uploads immediately without blocking control
acceptance or observation. The host verifies strict encoding, declared lengths,
digest, signature and scope before decrypting candidate data. Stage ciphertext
exclusively in root-owned files, reject symlinks/unsafe ownership, atomically
publish digest-named files and clean incomplete staging. No plaintext staging.
Concurrent uploads cannot replace an accepted ciphertext path. Cap upload time
and count as well as size so observation requests are not starved.

## Delivery and acceptance

1. Shared helpers with the common serializer (F1), chosen no-automatic-reset
   policy in CI/config starts (F2), acceptance/lock rejection and CI/maintenance
   conflict diagnostics (F3), plus drained verifier mode and candidate-restart
   detection. Add allowlisted structured error envelopes to the handler and app
   transport now, distinguishing failed connect from post-send unknown outcome.
   Test release-lock acquisition before authorization reservation. Keep CI
   request/success behavior; conflict diagnostics and restart-budget policy are
   deliberate exceptions.
2. Fixed-limit threaded control server, asynchronous preview workers with
   snapshot-only planning (no release lock), controller actions, public schema
   with backoffice classes, per-ID journal, receipts and SSH CLI. Verify status/
   events responsiveness during preview, timestamped cached drift probes and
   legacy inline status requests counted in handler capacity. Public settings
   only, same bundle/image.
3. Backoffice Environment: current state, diff/confirmation, apply, live timeline,
   honest connection gap, event catch-up and receipts with recovery commands.
4. Operator-signed bundle delivery for both clients, pinned verification key,
   manifest bound to the replaced bundle rather than full deployment baseline,
   durable used-authorization ledger, separate fixed-limit upload socket and
   memory-only planning (F4). Verify polling during slow/max-size uploads. Keep
   both expiry clocks and expose their minimum with distinct expiry codes. Keep
   recovery attestation wording explicit (F6), SSH-only ops-token rotation and
   separate recipient procedure.
5. Isolated-host rehearsal from both clients, then reviewed host installation
   and a production backoffice no-op plan. First actual production change needs
   explicit approval of its specific plan (F7). No history pagination or affected-
   process schema in version 1 (F8); retain the simpler hold/drain model (F5).

Provider-free acceptance tests must cover:

- Schema/projection/transport permissions, structural rejection, no-op, whole-
  baseline staleness, expiry, paired gateway keys and prerequisite checks.
- Serializer exact round trip through shlex and rejection of unsupported values;
  byte preservation for supported current ASCII values and private live-domain
  compatibility check at production no-op rehearsal; shared CI/config restart-
  budget behavior with no unconditional `reset-failed`.
- Competing CI/maintenance/config operations, lock lost after acceptance producing
  `rejected_busy` without authorization reservation or hold/drain, release lock
  acquired before ledger reservation and reservation before hold creation,
  distinct CI configuration-active diagnostic,
  request-ID deduplication across retained operations and payload mismatch.
- Preview never takes the release lock; concurrent CI is not failed by preview,
  and baseline movement while preview runs prevents a ready stale plan. Slow
  SOPS/Compose/image checks run only in preview workers; fixed handler/worker
  limits and exhausted upload slots do not block status/events polling. Confirm
  both clients can observe an apply while another preview/upload is pending.
- Cached drift observations retain actual probe timestamps and compared revision;
  bounded probes are single-flight, failures become unknown, and age/revision
  mismatch disables Apply. Include legacy inline status requests in the eight-
  handler capacity tests; cache reads do not run or wait for live probes.
- Known handler codes reach the UI with safe operation IDs; unknown exceptions
  stay generic, including credential-bearing subprocess failures. Host maintenance
  and CI both identify config-owned holds with `configuration_operation_active`.
- Plan performs no materialization and leaves no candidate plaintext in runtime
  directories, including errors; signatures rejected before candidate preflight,
  manifest replay/scope rejection, current recipient checks and both ops tokens.
  An intervening image-only CI release allows the same unexpired signed bundle
  after a fresh plan/approval; changing the replaced bundle invalidates it.
  Concurrent authorization reuse, reboot, failed apply and interrupted reservation
  cannot free a consumed ID; same-request observation remains idempotent.
  Either expiry can limit the preview; countdown/Apply use the minimum and report
  `plan_expired` versus `authorization_expired`, including the tie rule. A valid
  apply can finish draining after the authorization deadline passes.
- Backoffice rejects SSH-only names and ops-token rotation; SSH permits supported
  SSH-only changes. Host-derived transport cannot be spoofed; verified attribution
  is retained without treating the shared token as an individual identity.
- Router shape/size validation and bounded forwarding without deployment decisions;
  oversized uploads/responses rejected, event batching and fixed error codes.
  Failed connect proves no send and returns `host_agent_unavailable`; attempted/
  partial send, post-send timeout or lost/malformed reply returns
  `request_outcome_unknown`. The UI observes the original UUID without repeating
  apply, including when the browser loses the proxy response.
- Frontend public/secret diffs, stale/expired disabling, confirmation, UUID retained
  across lost responses, ordered timeline, unconfirmed intents, contact loss/backoff,
  catch-up, stale poll suppression and failure receipts with recovery commands.
- Phase ordering, atomic publication, hold ownership, interrupted launch/start,
  disconnect/reconnect and ambiguous resume without unsafe stopping. Config never
  creates/removes Nginx's public-maintenance file; backoffice remains usable during
  drain. A candidate restart between local/public checks or before resume fails
  verification; a healthy same-SHA replacement cannot hide the restart.
- An operation started by either client is observable by the other and recoverable
  through the SSH operator procedure. Secret redaction includes exception paths.

Use real SOPS with disposable recipients/dummy bundles where available. On an
isolated host, test systemd `EnvironmentFile` round trips, actual restart budgets,
Compose projection, long-running work, both-client connection loss, all failure
boundaries, worker kill and reboots with/without the hold. Prove drain persists
and the candidate never accepts work before explicit verification/resume; check
materialization timing and active-mount pruning. Mocked tests do not establish
these host behaviors or provider credential usability. Installation of reviewed
controller/schema/verifier/operator keys is a separate host change; an application
image deployment cannot install them. Publish a current runbook only when the
implementation and acceptance evidence exist.
