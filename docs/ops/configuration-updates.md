# Deployed environment updates

**Status: activated on production October 29, 2026. Isolated-host acceptance,
drained deployment, protected API/SSH checks and the explicitly approved
production no-op apply all passed. No production secret values changed.**

Backoffice → **Environment** and `scripts/canary_config.py` use one root-owned
host controller. Public settings recreate the same immutable image. New secret
bundles require an independent operator signature. CI, configuration applies
and package maintenance share the release lock. Previews use short snapshots
and a background worker, never that release lock.

## Compare a local production file and reconcile selected differences

`./scripts/prod-env` is the local companion for Backoffice → Environment. It
runs with the project's locked Python dependencies and reads a dedicated file:
`<repository>/.env.prod`, explicitly gitignored and owned by you with mode `0600`. It never
reads a development `.env` or the ambient shell environment as desired values.

Initial setup writes current **public** settings and commented secret names.
It does not copy production plaintext secrets into the env file. Existing files
are never overwritten:

```sh
./scripts/prod-env init
# Edit .env.prod locally; enter only intended overrides.
# With Homebrew SOPS/age, explicitly opt in once per terminal as in secret delivery:
export CANARY_ALLOW_HOMEBREW_TOOLS=1
./scripts/prod-env diff
./scripts/prod-env reconcile
```

The diff shows `same`, `changed`, `local_only`, `production_only`, empty-secret
errors and unsupported names. Public setting differences show old/new values;
secret and unsupported-name values are always hidden, with no value hashes.
Dotenv parsing performs no interpolation or shell execution. A missing local
name preserves production; an empty secret is rejected, not treated as removal.

`reconcile` proposes all supported changed/local-only values by default. Use
repeated `--select NAME` options for a subset. Unknown names block automatic
selection and require a reviewed secret/schema/Compose release before they can
be reconciled; explicit selection can proceed with other supported names. Never
silently project arbitrary new variables into the production container.

```sh
./scripts/prod-env reconcile --select RUNWARE_API_KEY --select CANARY_RUNWARE_FIRST_ENABLED
./scripts/prod-env reconcile --remove FAL_KEY
```

Only explicit `--remove` removes optional secrets. Public removals reset a
setting to its declared default; required settings/secrets cannot be removed.
Gateway key aliases remain paired. Unselected secrets and credential files are
preserved exactly.

The restricted operator SSH account has one additional read-only action:
`config_export`. It returns only the accepted **encrypted** bundle, its digest,
public settings/schema, revision and public recipient metadata. It never returns
plaintext or arbitrary host files and is rejected through the backoffice socket.
The ciphertext read is owner-only, no-symlink, digest-checked and capped at 2 MiB.
The browser cannot read your local file; comparison runs on the operator machine.

The helper decrypts in memory using `~/.config/canary/recovery/age.txt`, checks
that it is an approved recipient distinct from the host, merges selected local
values, encrypts to the existing recipient set, verifies recovery for that exact
ciphertext, and signs with `~/.config/canary/prod/config_signing_ed25519`. Plaintext
never becomes an artifact, upload or diff field. Local secret values intentionally
entered in the private env file remain there as the desired overrides.

Prepared ciphertext, manifest/signature, redacted diff and public patch live in a
new owner-only folder under `~/.config/canary/prod/reconciliations/`. `reconcile`
then submits the existing asynchronous preview and prints the exact plan plus an
apply command. It **never applies automatically**. Review its changed names,
digest, restart requirement and deadline before running the printed command or
asking an agent to apply that exact plan. In Backoffice → Environment, choose
**Load latest proposal** to review a proposal submitted locally, including after
reopening the page or viewing an older operation. **Prepared — awaiting apply**
means production has not changed. Review the exact digest and changed names,
then choose **Review apply → Apply this plan**. Completion shows **Applied and
verified** only when the receipt revision matches a fresh running observation.
Progress and receipts remain visible in the same page. SSH-only settings and
ops-token rotation show an explanation and keep browser apply disabled; use the
helper's exact SSH apply command for those proposals.

`--prepare-only` creates artifacts without submitting a preview. Resume with
`./scripts/prod-env plan --prepared /PRIVATE/OUTPUT`. The helper checks production's
revision before upload and binds the plan request to that same revision. A
concurrent bundle, image or tooling change rejects the stale reconciliation;
compare and review again rather than rebuilding or retrying silently. Local
preparation requires the same reviewed secret-loader version as production.

The encrypted-export extension and exact-revision guard were installed on
production October 29, 2026 after explicit approval; only the host agent was
refreshed. Readiness remained `ok`. The first real local comparison matched all
14 public settings and preserved all 18 production-only secret names.
`reconcile` returned `already_matches`, without creating an apply. The repository
`.env.prod` was initialized with public settings and commented secret names,
verified gitignored and mode `0600`. No production settings or secrets changed.

Other hosts require the updated `config_controller.py` and a host-agent refresh
before first use. Installation, `init` and `diff` change no production values;
`reconcile` only prepares and previews a proposal.

## Before installation

Use the [release runbook](lightsail-ci.md) and [secret delivery](secret-delivery.md).
Preserve the single artifact/queue owner, pinned loader, encrypted bundles,
recovery identity custody and existing operator SSH. This feature does not
install itself through an application image, start services or authorize a
production change merely because its code is present.

Review/install these files root-owned alongside the existing host tooling:

| Repository file | Installed path | Mode |
| --- | --- | --- |
| `deploy/lightsail/release.py` | `/usr/local/lib/canary/release.py` | `0755` |
| `deploy/lightsail/host_agent.py` | `/usr/local/lib/canary/host_agent.py` | `0755` |
| `deploy/lightsail/config_controller.py` | `/usr/local/lib/canary/config_controller.py` | `0755` |
| `deploy/lightsail/config_schema.json` | `/usr/local/lib/canary/config_schema.json` | `0644` |
| `deploy/lightsail/verify_config_runtime.py` | `/usr/local/lib/canary/verify_config_runtime.py` | `0644` |
| `scripts/verify_deployment.py` | `/usr/local/lib/canary/verify_deployment.py` | `0644` |
| `deploy/lightsail/compose.yaml` | `/usr/local/lib/canary/compose.yaml` | `0644` |

The current unit/secret loader remain prerequisites. Deploy through the normal
drained release path after installing the reviewed Compose template; the existing
container does not acquire newly projected settings until recreation. Keep the existing
`/run/canary-host` directory mount; the agent adds a private `config-upload.sock`
inside it. Its control socket has eight handler slots, upload socket two, and
only one preview worker is accepted at once. Ciphertext is capped at 2 MiB,
manifest at 4 KiB, signature at 16 KiB and encoded request at 3 MiB. Responses
are capped at 256 KiB, with events returned in batches of 100. At most 32
ciphertext uploads are retained; inspect/reference-check and remove obsolete
staging during reviewed maintenance rather than deleting a live operation's input.

State is root-only under `/var/lib/canary-config`: per-UUID request, plan,
SQLite event journal and receipt; accepted-operation pointers; timestamped drift
cache; hold ownership; staged ciphertext; and a durable authorization ledger.
Preserve this directory across host recovery, especially used authorization IDs.
The host private age key remains in `/etc/canary/keys/age.txt`. Neither recovery
nor signing private keys belong on the host, application, or CI.

Install a separate operator SSH key/account forced to this exact no-argument
command, with no shell or forwarding and exact sudoers authorization:

```text
sudo -n /usr/bin/python3 /usr/local/lib/canary/config_controller.py
```

Follow the `restrict`, forced-command and sudoers validation patterns of the
existing CI account, using a separate `canary-config` account. Do not authorize
arbitrary Python, `--worker`, remote arguments or environment overrides. In
version 1 the single operator key is attributed as `operator_ssh`; the app is
attributed as `ops_token`, not as an independently verified individual admin.
The existing CI account must retain only its release controller authority.

Set `/etc/ssh/authorized_keys` to root-owned `0755` and this account's public
key file to root-owned `0644`; sshd reads it under the target account, so an
owner-only root directory/file prevents authentication. Private operator keys
remain local `0600`. Preserve `SSH_ORIGINAL_COMMAND` through the exact sudo rule
so the controller can reject remote arguments:

```text
Defaults:canary-config env_keep += "SSH_ORIGINAL_COMMAND"
canary-config ALL=(root) NOPASSWD: /usr/bin/python3 /usr/local/lib/canary/config_controller.py
```

Validate the sudoers file with `visudo -cf`, SSH configuration with `sshd -t`,
and test a forbidden remote command with a valid JSON request on stdin before
activation.

Keep the operator signing key separate from its SSH access key. Install its
PUBLIC key in root-owned `0600` `/etc/canary/config-allowed-signers`, using the
OpenSSH allowed-signers format:

```text
canary-config ssh-ed25519 OPERATOR_PUBLIC_KEY_DATA
```

Signatures use namespace `canary-production-config`. The signed canonical JSON
manifest contains target, ciphertext SHA-256, replaced bundle SHA-256,
authorization UUID, expiry, and the operator's recovery-verification attestation.
An image-only CI release needs a new plan and approval, not a new signature.
An accepted bundle change invalidates authorization for the previous bundle.
The apply worker wins the release lock and revalidates before consuming the ID;
then it fsyncs the ledger before creating a maintenance hold. A busy rejection
never consumes an ID. A consumed ID remains used after failure or reboot.

Create root-owned `0600` `/etc/canary/config-enabled` only during reviewed
activation after the isolated rehearsal. It gates plans/applies. Refresh the
host agent only as part of that authorized installation, and deploy the app
containing the router/view through normal CI. The dated installation evidence
below distinguishes completed host setup from pending activation/apply.

## Public settings and previews

The installed schema is authoritative. Only the two Runware operational switches
are backoffice editable initially. They change which provider gets paid; an app
compromise can flip them and request drain/restart cycles without a bundle
signature. Treat that cost and availability exposure as part of activation.
Other declared settings are SSH-only; structural image/origin/proxy/mount/loader
changes remain reviewed releases, not generic setters.

The environment serializer accepts literal printable ASCII excluding double
quote, backslash, dollar sign and backtick. Existing allowed ASCII values retain
the same bytes as the former JSON writer. Before production no-op rehearsal,
privately check live `deployment.env` for names whose values this schema rejects.
Do not print values. An incompatible value requires a reviewed migration, not an
escape/compatibility shim.

In **Environment**, inspect accepted revision, image/source, bundle/loader,
timestamped drift observation, public settings and secret NAMES. Stale/unknown
observations or drift disable changes. The independent probe is bounded to ten
seconds, refreshes at most every 15 seconds and is stale after 30 seconds. Status
reads do not wait for it. Existing package-status probes consume control handler
capacity and have a separate 20-second overall budget.

Choose public values or attach signed ciphertext/manifest/signature, then choose
**Preview changes**. The host queues the preview and clients poll its UUID. The
ready plan shows old/new public values, secret change categories, prerequisites,
activity, exact digest and restart/no-op. Planning decrypts only in memory and
never calls `materialize`. Apply revalidates the entire baseline under the release
lock. A plan is valid for 30 minutes; a signed authorization may expire earlier.
The countdown uses the earlier deadline and reports `plan_expired` or
`authorization_expired` specifically. No-op apply records a receipt without drain
or restart.

Review the confirmation for this exact plan. An agent must show its digest,
changed names and restart requirement and obtain the user's yes for THAT plan
before production apply. An earlier approval or general task authorization does
not cover a replacement plan. Approval covers the transaction's steps without
further step-by-step prompts.

## Operator CLI

Create a private `~/.config/canary/production-operator.json` outside this repository:

```json
{
  "identity": "/ABSOLUTE/PATH/TO/OPERATOR_ACCESS_KEY",
  "known_hosts": "/ABSOLUTE/PATH/TO/VERIFIED_KNOWN_HOSTS",
  "destination": "canary-config@VERIFIED_HOST"
}
```

Commands enforce pinned host checking and never send a shell command. Output is
structured JSON; plan follows its preview worker automatically. Apply prints its
request UUID before sending, returns exit 2 for accepted work, or follows with
`--watch`. Terminal rejection is exit 3, failed/inspection exit 4 and an
unconfirmed transport/client result exit 5. Success is exit 0. Do not infer
completion from acceptance.

```sh
python3 scripts/canary_config.py plan --target production --set CANARY_RUNWARE_FIRST_ENABLED=true
python3 scripts/canary_config.py apply --target production --plan PLAN_UUID --expect-plan-sha256 PLAN_DIGEST --request-id APPLY_UUID --watch
python3 scripts/canary_config.py status --target production --operation APPLY_UUID
python3 scripts/canary_config.py watch --target production --operation APPLY_UUID --after 12
```

An identical request UUID returns the retained operation; changing its payload
is rejected. Watch/status do not retry apply. Either client can observe the
other's operation. SSH remains available while the application is stopped.

## Secret bundle preparation

Use `canary_secrets.py set` and `verify` from the secret-delivery runbook, with
both independent age recipients. Verify recovery for the EXACT candidate
ciphertext on the operator machine. Then sign it with the separate operator key:

```sh
python3 scripts/canary_config.py sign --bundle /PRIVATE/app.next.sops.json --replaces-bundle-sha256 ACCEPTED_BUNDLE_DIGEST --signing-key /PRIVATE/config-signing-key --recovery-verified --output /PRIVATE/new-authorization
```

The output directory must not exist; it contains `manifest.json` and
`manifest.json.sig`, never decrypted values. Default expiry is one hour, with a
maximum CLI lifetime of 24 hours. `--recovery-verified` records an operator
statement; the host cannot verify independent key custody or the truth of that
statement. It reports “operator-recorded recovery verification for ciphertext …”.

Attach these three files in the backoffice, or preview through SSH:

```sh
python3 scripts/canary_config.py plan --bundle /PRIVATE/app.next.sops.json --bundle-sha256 CANDIDATE_DIGEST --manifest /PRIVATE/new-authorization/manifest.json --signature /PRIVATE/new-authorization/manifest.json.sig
```

The host verifies the pinned signer, manifest scope/digest/expiry, existing age
recipients, secret schema and prerequisites before drain. Recipient changes retain
the separate reviewed procedure. Backoffice ops-token rotation is refused by
comparing the bundles in memory; perform supported token rotation through SSH.
The controller drains with the old token and verifies/resumes with the new one.
The browser must reconnect with the new token after an SSH rotation.

## Observation and recovery

The timeline retains intent/result events, timestamps, durations, drain counts,
checks and a receipt. An intent without a result stays unconfirmed. Public and
local verification pin container identity and systemd invocation/restart counter;
Compose disables Docker restarts. Any restart during verification fails the check.
CI/config starts no longer reset the restart budget automatically. Diagnosing and
resetting an exhausted budget is an explicit operator recovery action.

The backoffice remains reachable during project drain. Config operations never
create/remove Nginx's independent `/var/lib/canary/public-maintenance` file; an
existing external gate blocks preflight. During stop/start/readiness the app may
be unreachable. The page retains its last observation, retries reads with backoff,
and fills the gap from the journal on reconnect. No public Nginx status endpoint
is added. Failure to return requires SSH; the page shows that recovery command
before apply. A failed proxy connect reports `host_agent_unavailable` and no send;
a partial send, lost reply or timeout reports `request_outcome_unknown`. Keep
observing that UUID rather than resubmitting apply.

Inspect the operation, its receipt and relevant systemd journal using independent
operator access. A worker interrupted by reboot/death is never automatically
replayed. Hold ownership is inode-checked. A configuration-owned hold is reported
to CI and host maintenance as `configuration_operation_active`, with the UUID.
Never clear an unrelated hold. Drain failure leaves the old process running,
drained, with its hold retained. Replacement failure retains/re-establishes the
hold and stops the unverified candidate. After resume has been attempted, an
uncertain outcome NEVER authorizes stopping; inspect admission and positively
drain/confirm idle again before any stop. No automatic rollback or paid request
replay is included.

Recovery uses the existing release verification/resume procedure under the shared
lock after inspecting actual config/container/queue/billing state. Keep both
image/bundle/config pairings; restoring old credentials may be unsafe. A drained
candidate may start after a reboot in the start window, but it cannot accept work
until explicit verified resume. Do not use package-maintenance reboot recovery
for a configuration operation.

## Evidence and remaining acceptance

Provider-free tests cover serialization, plan isolation, full-baseline checks,
permissions, old/new credential handling, real disposable-key signatures, durable
ledger/idempotency, lock races, safe failure/resume behavior, asynchronous socket
observations, upload bounds, proxy send-state classification, browser confirmation,
stale observations and event catch-up. Mocked provider/process data does not prove
credential usability, image quality or real systemd behavior.

Before production activation, rehearse on an ISOLATED host with dummy bundles and
queue/data: real systemd EnvironmentFile round trips, restart/start-limit behavior,
container/public-env/process-secret matching, long-running work, plan/CI races,
slow uploads alongside polling, every failure boundary, SSH/browser disconnect,
worker kill and reboot on each side of hold removal. Prove persisted drain and
normal post-stop materialization/pruning. Then privately check the live environment
character domain and run a production no-op preview. The first actual production
apply still requires approval of its concrete plan. This document records no
production secret rotation; installation and no-op activation evidence follow.

## Isolated activation rehearsal (2026-10-29)

Eighty-one focused configuration/release/maintenance tests passed. A disposable
Ubuntu 24.04 Lightsail VM then passed 22 live acceptance checks with dummy
processes, data and bundles: actual systemd environment parsing, no-op receipts,
release-lock races, long-running work, SOPS encryption/recovery, OpenSSH signing,
process/public-env matching, injected transaction-boundary failures, start-rate
limits, slow uploads alongside status polling, killed workers, restricted SSH
CLI access, and real reboots before and after hold removal. Interrupted operations
were not replayed; after hold removal the restarted app remained drained.

The dummy supervisor lacks the application's shutdown trap, so a fixture-only
unit drop-in used a one-second stop timeout. Failure injection wrapped journal
calls in a separate fixture worker without changing controller source. On this
Ubuntu systemd build a denied rate-limited start retained `Result=exit-code`;
the rehearsal verified denial and an unchanged process-start timestamp rather
than assuming `Result=start-limit-hit`. No production credential usability or
paid provider output was tested.

The local Docker Desktop attempt correctly stopped at the loader's active-swap
guard; no guard was relaxed and existing containers were untouched. The approved
temporary Lightsail VM was deleted successfully at 13:20:59 UTC. Local dummy-only
evidence is retained under `work/configuration-activation/2026-10-29/`. Production
access/configuration was not changed by the isolated rehearsal itself.

## Approved production installation (2026-10-29)

After explicit approval of the account/sudo/signer access settings, the reviewed
controller, release and host-agent files, schema, runtime verifier, public verifier
and Compose template were installed under the shared release lock. Prior host
files are retained in `/etc/canary/config-install-backups/1793280454508835575/`.
The separate `canary-config` account and public signer trust were installed;
private keys stayed on the operator machine. Sudoers and sshd validation passed,
and refreshing the host agent left application readiness and all three
dependencies healthy. Read-only restricted-account access was verified.

The live environment contains no values outside the serializer's character
domain. The only schema/container mismatch is the missing
`CANARY_RUNWARE_TEXT_FALLBACK_ENABLED` projection; its configured/default behavior
is `false`. The new Compose template differs by that projection alone. A normal
drained release must recreate the container before drift can match. No secret
rotation or production configuration apply is included in this installation.

## Production activation and no-op receipt (2026-10-29)

[Depot workflow n1mfxwn325](https://depot.dev/orgs/6ntrqswcbt/workflows/n1mfxwn325)
passed every CI gate and deployed source `2953fa0c40926186316b8a615e3e8031d2287ccc`.
The container now projects the declared default-false text-fallback setting. A
fresh observation matched, local/public readiness passed, generation admission
was open, and the approved root-only `config-enabled` flag was created. The
protected configuration API returned 200 with the token and 401 without it.
Only the existing operator `/32` and Lightsail browser SSH rule remain; the
temporary test VM was confirmed absent.

The owner explicitly approved no-op plan
`7185d84c-c006-4089-87cd-5c04ade3f819`, digest
`e57cac8317f0039601267d9175bac75ccdff14025f771b0239362bbe7811f3c5`.
Apply `a0241ad5-08f9-4b77-af60-9087cf96c260` completed with identical before/after
revisions, no changed public settings or secret names, and open admission.
The same running container was observed afterward. Its receipt is visible in
Backoffice → Environment and retained in the root-only host journal; local
evidence is in `work/configuration-activation/2026-10-29/`.

The owner-only operator profile is `~/.config/canary/production-operator.json`.
Separate access/signing private keys remain local, outside the repository. No
production candidate bundle was signed or rotated; future secret changes still
require exact-ciphertext recovery verification, a separate signature, preview,
and approval of that concrete plan.
