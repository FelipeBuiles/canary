# Observable deployed environment updates

**Status: Proposed, October 27, 2026. Design only; no production changes or
new commands are implemented by this document.**

## Decision

Add an operator command, `python3 scripts/canary_config.py`, for previewing,
applying and observing production configuration changes. Run the transaction
on the host, outside the application container, through a restricted operator
SSH interface. Reuse the release transaction and its exclusive lock rather
than implementing an independent restart workflow.

An environment update recreates the existing, immutable application image with
a reviewed public configuration and/or encrypted secret bundle. It does not
build an image, run generation, modify a running container, or reload settings
in place. Every apply has a durable operation ID, ordered events and a final
receipt. Disconnecting the client does not cancel the worker. An uncertain
response requires observing that operation, never submitting another update.

## Existing evidence and gaps

- [release.py](../../deploy/lightsail/release.py) validates image requests,
  holds `/run/canary-release/worker.lock`, drains admission, preserves the old
  environment, replaces the container, verifies and explicitly resumes. Its
  request accepts only image/version/loader/pull-token fields. It cannot update
  public settings or select a new encrypted bundle. Its output is a fixed
  success/failure message; captured subprocess output is deliberately suppressed.
- [host_agent.py](../../deploy/lightsail/host_agent.py) uses the same lock for
  maintenance and runs workers independently of HTTP. Its latest-operation
  record is useful precedent, but is insufficient for history and reconnecting
  to any earlier request. Its socket is accessible from the application.
- [secret delivery](../ops/secret-delivery.md) already provides allowlisted,
  in-memory secret changes, exact recipient checks, ciphertext verification,
  tmpfs materialization and mount-aware pruning. Keep that boundary.
- [Compose](../../deploy/lightsail/compose.yaml) explicitly projects public
  settings. Adding a name to `deployment.env` alone does not make it reach the
  container. Some settings are fixed in Compose and require a reviewed host
  template change before this tool can manage them.
- [verify_deployment.py](../../scripts/verify_deployment.py) checks public
  version, readiness, dependencies and headers. Today its non-resume mode
  expects admission open, so it needs an explicit drained-verification mode
  before verification and resume can be separately observable steps.

These are repository observations, not a fresh inspection of the deployed host.

## Operator interface

Proposed commands, shown for an already supported public setting:

```sh
python3 scripts/canary_config.py plan --target production \
  --set CANARY_RUNWARE_FIRST_ENABLED=true
python3 scripts/canary_config.py apply --target production \
  --plan PLAN_ID --expect-plan-sha256 PLAN_SHA256 --request-id REQUEST_UUID --watch
python3 scripts/canary_config.py status --target production --operation REQUEST_UUID
python3 scripts/canary_config.py watch --target production --operation REQUEST_UUID --after 12
python3 scripts/canary_config.py history --target production --limit 20
```

`plan` makes no admission, service or accepted-configuration changes. It may
stage ciphertext and store a private plan. It returns the expected deployment
revision, image/source SHA, changed public values, secret names marked
added/changed/removed, prerequisites, restart requirement, expiry and plan digest.
For a no-op, it reports that no restart is needed and apply records a no-op receipt.

`apply` is the explicit authorization to drain, recreate, verify and resume the
reviewed candidate. It never prompts for each step. `--watch` prints timestamped
progress and the final receipt; without it, the command returns once the host
durably accepts the operation. Stable JSON output is available with `--json`.
Use documented distinct exit statuses for complete, accepted/in progress,
rejected/failed and transport outcome unknown. A disconnected watch is not a
failed host operation.

Secret updates first use the existing `canary_secrets.py set` and `verify`
workflow, including independent recovery-key verification. Then pass only the
candidate ciphertext to `plan --bundle PATH --bundle-sha256 DIGEST`.
No plaintext secret arguments, environment exports, new secret editor or
decrypt-to-disk shortcut. A bundle plan includes a recorded recovery-verification
attestation bound to that ciphertext digest; the host cannot prove independent
recovery custody. Recipient changes retain their separate reviewed procedure.

For an agent, invoking this command means executing the same plan/apply/watch
protocol under the user's authorization. A saved plan is concrete reviewable
evidence; whether another approval is needed follows the user's actual scope,
not an unconditional extra confirmation prompt.

## Allowed changes and preflight

Create a root-owned public-setting schema next to the installed Compose file.
For each editable name declare type, empty/unset behavior, validation, affected
process and its actual projection into the installed template. Start with the
existing interpolated public settings. Reject unknown names, duplicate keys,
wrong types, control characters and values Compose cannot faithfully represent.
Serialize settings for the actual systemd/Compose readers; do not treat shell
quoting as their contract. Secret names belong only in the encrypted bundle.

The image, source version, loader digest, bundle paths, public origin, proxy trust,
volume mounts, worker topology and security controls are not arbitrary setters.
Bundle paths are derived by the host from validated ciphertext digests. Changes
to these structural settings use a reviewed release/host installation instead.
Do not add arbitrary commands, caller-selected file paths or a bypass flag.

Under the shared lock, preflight must:

1. Require the configured production target, active single owner, no existing
   maintenance hold, and an installed configuration-update activation marker.
   Refuse an already-drained application; recovery is a separate operation.
2. Capture the accepted environment revision, installed controller/schema/Compose/
   verifier hashes, loader digest, image digest, source SHA and bundle digest.
   Read the running container and local version; reject accepted/running drift.
3. Construct a candidate from the accepted configuration plus the allowed patch.
   Validate Compose using a clean environment and no ambient `.env` file. Keep
   rendered output private; never forward raw rendering/errors to the client.
4. Verify candidate ciphertext, exact existing recipient set, schema and any
   required credential dependencies. For example, enabling a Runware route
   requires `RUNWARE_API_KEY`. Validate ADC delivery without paid model calls.
5. Materialize the candidate through the existing loader with tmpfs, swap and
   mount-integrity checks. Verify the cached, unchanged image and loader match.
   No registry token or image pull is required for configuration-only changes.
6. Store an immutable, private plan, expiring after 30 minutes. Bind its digest
   to the baseline, candidate and installed tooling. Apply repeats preflight and
   compares the entire baseline while holding the lock. CI, maintenance or an
   operator edit makes the plan stale; there is no last-write-wins behavior.

For secret diffs, decrypt old and candidate only in host memory and retain names
and change categories. Never retain values or individual secret hashes. Recovery
verification and readiness establish limited evidence; neither proves that a
provider will accept a future paid request.

## Host transaction

Extract small shared host functions from `release.py`: deployment context,
candidate validation, drain, checkpoint/save, replacement, verification and
resume. Keep image-specific acquisition/provenance checks in the CI path.
Keep the existing CI forced-command JSON protocol and fixed output compatible.
Both paths and host maintenance retain `/run/canary-release/worker.lock`.

The new controller accepts only fixed actions: `plan`, `apply`, `status`,
`events`, `history`. Apply launches a bounded systemd worker without tying its
lifetime to SSH. Persist acceptance before launch; reconcile the launch result
without blindly launching a duplicate. Request IDs are UUIDs, retained across
all operations. Repeating the same ID and identical payload returns that
operation; a different payload with the same ID is rejected. Concurrent mutations
are refused with the active operation ID; reads remain available.

Successful phases:

```text
accepted → preflight → draining → saving_previous → stopping
         → installing → starting → verifying_local → verifying_public
         → resuming → complete
```

Before drain, exclusively create an operation-owned maintenance hold and persist
its ownership. Wait for BOTH `draining=true` and `safe_to_deploy=true`, preserving
durable unstarted work. Use the current 30-minute drain deadline. Never infer
idleness from container state or a quiet log.

Save the complete previous environment/image/bundle/loader pairing, then stop
the service. Atomically publish the candidate environment and its revision with
file and parent-directory fsync. Retain ciphertext under immutable digest names;
never edit live mount sources. Start exactly one container through systemd.
Preserve bounded restart policy; report start-limit failures instead of repeatedly
resetting the budget to force a start.

The existing maintenance file must be absent for systemd startup. Add a durable
transaction startup fence alongside it: the unit's start check permits a pending
configuration transaction only when its recorded worker is active on the same
boot and has authorized the candidate-start phase. Record this before temporarily
removing the worker's own hold. An unrelated hold is never removed. A crash/reboot
in that gap cannot permit an unverified normal startup; interrupted configuration
transactions require inspection and do not use host-maintenance reboot recovery.

Verify the exact image, source SHA, new container identity, bundle mount digest,
and allowed effective public settings. Compare secret delivery privately against
the loader's process scopes and report only match/mismatch by name, never raw
`docker inspect`, `/proc` output, values or value hashes. Then verify local
readiness and persisted drain, followed by public liveness, readiness, dependency,
model-mode, pipeline and security-header checks. These checks issue no paid jobs.

Use the OLD ops token to drain the old process and the CANDIDATE token to verify
and resume the new process. This also supports rotating `CANARY_OPS_TOKEN`.
Separate verifier checks from resume; publish each result. Only after all checks
pass may the worker explicitly resume. Confirm admission open, commit the receipt
and clear its transaction fence. A lost resume response is reconciled by reading
admission, never treated as permission to stop a potentially working container.

## Observability and recovery

Store root-only operations under `/var/lib/canary-config/operations/<uuid>/`:
immutable request/plan metadata, ordered event records, current snapshot and
final receipt. Persist an intent event before each consequential action and a
result after observing it. Sequence numbers are monotonic within an operation;
events include UTC timestamp, phase, elapsed duration, fixed result/error code
and selected evidence. The snapshot is recoverable from the event journal.
An intent with no result means an uncertain action, not proof of execution.

Use the same sanitized events for journald and SSH watch. Drain progress includes
allowlisted blocking counters, deadline and last successful check. Checks report
pass/fail and duration. The receipt includes before/after revisions, image/SHA,
ciphertext digest, changed names, verification outcomes, observed admission and
service state, hold owner and the next recovery action. No raw subprocess output,
tokens, plaintext config dumps, manuscript/project data or provider prompts.
Redaction is by constructing allowlisted records, not by filtering secret-looking
strings after logging. Restrict event sizes and paginate history/events.

Status/watch use operator SSH to the host, independently of the stopped app.
Reconnect with the operation ID and last event sequence. When the host cannot be
reached, show the last observation time and `host_unreachable`; do not invent a
current phase. Full observability means retained process evidence and explicit
uncertainty, not guaranteed connectivity or an independent outage monitor.

| Failure boundary | Required result |
| --- | --- |
| Validation or stale plan before drain | Reject; accepted config and running owner untouched. |
| Drain timeout/error | Keep existing process running and admission drained; retain own hold/fence for explicit recovery. Do not automatically resume. |
| Stop/install/start/check failure | Retain fence/hold; stop an unverified candidate once stop is safe; preserve both config pairings and evidence. No automatic rollback or resume. |
| Resume response lost | Query admission. If unknown, record `needs_inspection`; do not stop, roll back or repeat apply. Work may already have started. |
| Worker killed or host reboots | Reconcile durable intent with boot ID, systemd, accepted revision and actual container. Record interrupted/unknown state; retain fencing. No automatic replay. |
| Client disconnect | Worker continues; status/watch retrieves the same operation. |

Before resume has been attempted, failures after replacement can stop the
candidate under the existing fail-closed policy. After resume has been attempted,
any subsequent stop needs a fresh authenticated drain and positive idle proof.
This distinction must also be covered when extracting shared release helpers.

Recovery uses operator inspection and the existing release verification/resume
procedure. Selecting a previous bundle may restore a revoked credential or alter
database routing; restarting an old pairing is not inherently safe rollback.
Reconcile any writes and queue/credit state first. Do not offer a generic retry
or rollback button in the initial version. Retain receipts and rollback pairings;
pruning them is a separate reviewed maintenance action.

## Access and delivery

Use a separately installed operator forced-command entry point and dedicated key,
pinned host verification and exact sudoers command. The existing CI key retains
image-release authority only; the application socket gains no configuration
mutation action. The operator endpoint accepts bounded JSON/ciphertext on stdin,
never an arbitrary remote command, destination path or private recovery identity.
Ciphertext uploads use exclusive, root-owned staging, digest checks and atomic
publication; reject symlinks and unsafe ownership. Request bounds must accommodate
the loader's bundle limit plus SOPS/transport overhead while remaining finite.

Reuse verified operator access and existing firewall rules. Do not open SSH to
the world, import production secrets into CI, or grant the app Docker access.
Initial installation of host code/schema/start checks and the operator key is a
separate reviewed host change. An application image deployment cannot install it.

## Implementation and acceptance

1. Implement the shared transaction helpers and drained verifier mode; preserve
   CI request/response compatibility and existing host-maintenance behavior.
2. Add typed setting schema, operator transport, immutable plans, operation
   journal, startup fence and configuration worker. Deliver public-setting
   updates first, with the same bundle and image.
3. Add candidate ciphertext delivery and old/new-token handling, reusing the
   existing loader. Document plan/apply/watch and recovery in a current runbook
   only after implementation; this proposal is not an executable procedure.

Provider-free tests must cover validation/projection, no-op, stale baselines,
concurrent CI/maintenance/config apply, same-ID deduplication across history,
payload mismatch, secret redaction (including exception paths), both ops tokens,
drain deadlines, phase ordering, startup fencing, atomic publication, interrupted
launches, disconnect/reconnect, and ambiguous resume without unsafe stopping.
Exercise real SOPS with disposable recipients and dummy bundles where available.

On an isolated host, exercise the real systemd/Compose path, simulated long-running
work, all failure boundaries, worker kill, reboot at the start gap, active-mount
pruning and SSH loss. Verify non-secret settings reach the correct processes and
secret values never reach tool output. Then install reviewed host tooling and
rehearse a production no-op plan. Activate mutation only after that evidence;
the first real production change remains a separately authorized operation.
