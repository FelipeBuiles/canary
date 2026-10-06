# Encrypted production secret delivery

**Status: Current implementation, October 6, 2026. Not activated in production.**

The [strategy](../proposals/aws-secret-management.md) defines ownership and
rotation. The executable interface is [canary_secrets.py](../../scripts/canary_secrets.py).
It uses Python's standard library, SOPS, and age. The root Dockerfile includes
the loader; Fly's existing environment-based startup is preserved when no bundle
is configured. Lightsail explicitly requires the bundle.

The [October 6 hardening review and activation checklist](../reviews/2026-10-06-secret-hardening.md)
records the review findings, their resolutions, and the ordered production gates.
Passing the unit tests is not approval to activate this deployment.

## Tools and ownership

Install reviewed SOPS and age binaries on the operator machine; the host needs
SOPS, Python 3, and age-keygen for initial identity creation. Verify upstream
release checksums/signatures before installing into root's PATH. Tests exercised
SOPS 3.13.3 and age 1.3.2. There is no auto-download in the production tooling.

The script refuses a `sops`, `age-keygen` or `fly` binary if it, or any directory
from it up to `/`, is owned or writable by anyone other than root or the invoking
user (a sticky shared directory such as `/tmp` is allowed). Linux hosts always
use this strict policy: install verified tools into protected root-owned paths.

On a local Mac, opt in once per terminal session to using Homebrew tools:

```sh
export CANARY_ALLOW_HOMEBREW_TOOLS=1
```

This permits macOS `admin`-group-writable directories within `/opt/homebrew` or
`/usr/local`, only for tools resolved inside that prefix's `Cellar`. It explicitly
trusts members of that group to modify the local tool installation. Ownership
checks, world-write rejection, executable-file checks, and checks above the
Homebrew prefix remain strict. The exception is unavailable on Linux or when
running as root, even if the variable is set. It is not passed into SOPS's clean
environment or added to the remote deployment configuration. No extra copies
of Homebrew tools are needed on the Mac.

It runs SOPS with
only `PATH` (no inherited `SOPS_*` or cloud credentials) and an empty `--config`,
so neither a stray `SOPS_KMS_ARN`/`SOPS_PGP_FP` variable nor a `.sops.yaml` such as
`unencrypted_regex` can add a decryptor or leave a value in plaintext. After
encryption it requires the stored decryptors to be **exactly** the given age
recipients, with no KMS, PGP, Vault, Azure, GCP, key-group or Shamir entries.

The user selected **1Password** for the independent recovery identity. Create a
restricted Document item named **Canary production age recovery** and attach the
generated recovery identity file. Record the public recipient, environment,
creation date, owner, and instructions linking it to the encrypted configuration
repository. Keep an independent offline recovery copy. The host private identity
must be different; never install the recovery identity on the host or in CI.

Only public age recipients, ciphertext digests, paths, and fixed error codes are
printed by the ordinary CLI. Do not enable shell tracing, print private key
files, or paste keys into chat. The internal `_export` subcommand is a transport
implementation detail: never invoke it directly, even with output redirected.

## 1. Bootstrap recipients

Use an owner-only directory outside the application repository on the operator
machine. `create-identity` refuses an existing output and an accessible parent:

```sh
install -d -m 700 ~/.config/canary/recovery
python3 scripts/canary_secrets.py create-identity \
  --output ~/.config/canary/recovery/age.txt
```

Upload that file to the restricted 1Password Document item without printing it.
Confirm it can be downloaded and decrypt a dummy bundle before trusting the
vault. Preserve the offline copy securely; retire unnecessary laptop copies once
recovery is proven. This command has not been run for production during setup.

On the target host, through a verified SSH/admin connection:

```sh
sudo install -d -m 700 /etc/canary/keys /etc/canary/bundles
sudo python3 /usr/local/lib/canary/canary_secrets.py create-identity \
  --output /etc/canary/keys/age.txt
```

This prints the host public recipient. Confirm the host identity out of band
before encrypting to it. Two distinct public recipients are required by the
exporter; tooling cannot prove that one belongs to 1Password or that the backup
has actually been saved. That is an operator acceptance check.

## 2. Inventory and encrypt

Use `fly secrets list -a canary-web` for metadata. Reconcile staged versus active
values and file delivery with the provider/password-manager records. Do not
restart Fly to expose staged values. Select the existing Machine explicitly.

The bundle schema is `{ "version": 1, "env": { ... }, "files": { ... } }`.
`REQUIRED` and `OPTIONAL` in the script are the authoritative name allowlists;
`files` accepts only `google-adc.json`, whose value is the ADC JSON text. Unknown
names, duplicate JSON keys, empty values, unequal gateway keys, partial R2
credentials, and unsupported ADC types fail closed. Public config, build secrets,
admin credentials, and AWS access-key tuples are not accepted. Any needed
additional credential requires a reviewed schema change, not a blanket export.

An example invocation, after substituting **public** recipients and Machine ID:

```sh
python3 scripts/canary_secrets.py export-fly \
  --app canary-web --machine MACHINE_ID \
  --names LITELLM_MASTER_KEY,LITELLM_API_KEY,LITELLM_SALT_KEY,CANARY_OPS_TOKEN,SUPABASE_SECRET_KEY,CANARY_QUEUE_DATABASE_URL,STRIPE_SECRET_KEY,STRIPE_WEBHOOK_SECRET,OPENAI_API_KEY,FAL_KEY \
  --with-adc \
  --recipient HOST_PUBLIC_AGE_RECIPIENT \
  --recipient RECOVERY_PUBLIC_AGE_RECIPIENT \
  --output /ABSOLUTE/PRIVATE/CONFIG/prod/app.sops.json
```

Adjust optional names to the reconciled inventory. Include `FAL_ADMIN_KEY` when
it is set on Fly: without it the gateway cannot look up FAL's billed cost and
falls back to estimates. Omit `--with-adc` only
when Vertex is not configured. This copies active credentials without rotation
or restart. The reviewed exporter source is sent in the SSH command and selects
only the requested names from the **running supervisor's** environment
(`/app/entrypoint.sh`, read from `/proc` as root), not from the SSH session, whose
environment may be missing or differ from the active release. If no supervisor
is running it fails with `runtime_process_not_found`. Plaintext exists in the exporter, SSH transport, and
local process memory; it never goes to tool output or a plaintext disk file.
Subprocess stderr is suppressed because tools can echo their input. Failures
publish no bundle; existing outputs are never overwritten.

For values recovered from the original secret source instead, prepare a
schema-valid JSON file with owner-only permissions outside the repo, using an
editor with swap/history disabled. Then use `encrypt-file --input PATH` with
the same `--recipient` and `--output` arguments. Securely remove that temporary
plaintext after verification; prefer memory-backed storage where available.

The command prints a ciphertext SHA-256. Preserve it in the reviewed release
record; don't hash or publish individual plaintext values. Verify recovery:

```sh
python3 scripts/canary_secrets.py verify \
  --bundle /ABSOLUTE/PRIVATE/CONFIG/prod/app.sops.json \
  --identity /ABSOLUTE/PRIVATE/RECOVERY/age.txt \
  --sha256 CIPHERTEXT_SHA256
```

### Changing values later

Do not decrypt to a file to rotate one credential. `set` decrypts in memory with
an operator identity, reads the new value without echo from the terminal (or
one value from a pipe, e.g. from a password manager CLI), validates the schema,
and writes a **new** ciphertext file:

```sh
python3 scripts/canary_secrets.py set \
  --bundle /ABSOLUTE/PRIVATE/CONFIG/prod/app.sops.json \
  --identity /ABSOLUTE/PRIVATE/RECOVERY/age.txt \
  --sha256 CURRENT_CIPHERTEXT_SHA256 \
  --name STRIPE_SECRET_KEY \
  --recipient HOST_PUBLIC_AGE_RECIPIENT \
  --recipient RECOVERY_PUBLIC_AGE_RECIPIENT \
  --output /ABSOLUTE/PRIVATE/CONFIG/prod/app.next.sops.json
```

Repeat `--name` to change paired values together from a terminal (`R2_ACCESS_KEY`
and `R2_SECRET_KEY`). Setting either `LITELLM_MASTER_KEY` or `LITELLM_API_KEY`
sets both. `--remove` deletes optional names; required names cannot be removed.
`--name google-adc.json` replaces the ADC file. The recipient list must equal the
current bundle's unless `--change-recipients` is given, so a recovery recipient
cannot be dropped by accident. Replace the old file only after `verify` succeeds.

Commit only ciphertext to the separate private configuration repository. Never
store bundles/keys in the application Docker build context. Do not use a public
repo simply because values are encrypted; field names and history remain visible.

## 3. Install host delivery

The templates are [compose.yaml](../../deploy/lightsail/compose.yaml),
[canary.service](../../deploy/lightsail/canary.service), and
[deployment.env.example](../../deploy/lightsail/deployment.env.example).
They are not installed or enabled by this change. They assume the host's root
Docker CLI is `/usr/bin/docker`; confirm that and the Compose plugin on the target.

Install the script and Compose file root-owned in `/usr/local/lib/canary/`, the
unit in `/etc/systemd/system/`, and a reviewed **non-secret** deployment.env in
`/etc/canary/` with mode `0600`. Record `python3 scripts/canary_secrets.py digest`
of the reviewed release as `CANARY_LOADER_SHA256`: `materialize` on the host and
`run` in the container both refuse a loader whose SHA-256 differs, so the host
copy and the image copy cannot drift apart unnoticed. Set `CANARY_HEALTH_HOST` to
a name in `CANARY_ALLOWED_HOSTS`; the entrypoint's local health probe otherwise
sends Fly's hostname and is rejected. Copy the encrypted bundle to its digest-named
path under `/etc/canary/bundles/`. Use a tested image digest and pull it before
draining. The image must include the new loader. Prepare `/srv/canary/projects`
from the complete consistent migration backup, not an empty directory, and keep
it `root:root`: the container runs as root with every capability dropped, so it
cannot write files owned by another user.

The unit creates `/run/canary/secrets` with owner-only permissions. Materialization
requires Linux root and verifies tmpfs. It checks the ciphertext digest, decrypts
with the host identity, validates the schema, writes private files in a temporary
directory, and atomically publishes a digest-named directory. Repeating the same
version validates and reuses it; corrupted existing files cause failure, not repair
in place. Old mount sources remain intact until their containers stop.

Materialization refuses to run while any swap is active, because tmpfs pages can
be written to swap. If the host uses encrypted swap, the operator may attest that
by adding `--allow-encrypted-swap` to the unit's `materialize` line.

Compose explicitly projects only public settings; it does not use a secret env
file. Secret-bearing files are read-only bind mounts. Docker restart is disabled;
systemd owns bounded restarts, and the existing application crash budget remains
active. Core dumps are disabled. The container has a read-only image filesystem,
an in-memory `/tmp`, no Linux capabilities, and `no-new-privileges`. A fixed
network makes `172.29.88.1` the only peer whose `X-Forwarded-For` Uvicorn trusts
(`CANARY_FORWARDED_ALLOW_IPS`), so a header injected before Nginx is not taken as
the client address. Nginx must still replace client-supplied forwarding headers.

Inside the container the entrypoint gives each process only its own credentials:
LiteLLM receives provider keys, `LITELLM_MASTER_KEY`, `LITELLM_SALT_KEY` and its
`DATABASE_URL`; the web process receives `LITELLM_API_KEY`, Supabase, Stripe,
queue, R2 and operations credentials. The supervisor shell keeps both sets so it
can restart the gateway.

This narrows inherited environments; it is not isolation between compromised
processes. Both children still run as root, the runtime secret bundle is mounted
in their shared container, and the supervisor retains the complete environment.
Do not claim that the web process cannot obtain provider credentials.

For Vertex set `GOOGLE_APPLICATION_CREDENTIALS=/run/credentials/google-adc.json`
and its project settings in the public config. The loader validates that file
before launching the app. It does not contact Google or validate token renewal.
Do not mount AWS profiles or registry credentials into the container.

## 4. Activation and changes

**Do not start this service against the production queue while Fly is active.**
Complete the [single-owner cutover](../proposals/aws-lightsail-migration.md)
and proxy/IP-trust changes first; these templates are secret delivery support,
not a completed network migration.

For an update, copy the candidate ciphertext without changing the accepted
deployment file. Run `verify` with the host identity and candidate digest before
stopping the healthy app. If desired, prepare its mount files with `materialize`
and the same arguments. A failed verification/materialization leaves the running
container and selected version untouched. The service itself is a startup unit,
not a transactional release controller: directly restarting it with invalid
settings would stop the healthy process before failure.

After successful preflight: authenticated drain, confirm `draining` and
`safe_to_deploy`, establish maintenance hold, stop the service, install the
reviewed deployment.env, remove the hold, then start. Verify readiness/version
and resume explicitly through the existing operations API. Keep the previous
image/ciphertext pairing for rollback. Never expose the ops token in arguments;
the release controller must load it privately on the host. Automation of that
full release transaction belongs to the remaining AWS deployment work.

Use `/etc/canary/maintenance` as a persistent hold before an intentional stop;
the unit skips startup while it exists, including after host reboot. Removing
the hold does not start the service by itself. A full host reboot requires an
actual systemd/VM acceptance drill before launch; an isolated container test
does not establish reboot behavior.

After every stop the unit runs `prune`, which removes each plaintext version and
staging directory that no process on the host (including container mount
namespaces) still mounts. A maintenance hold therefore leaves no decrypted
secrets behind; the next start decrypts again. `prune --keep DIGEST` can also be
run by hand after a candidate `materialize`. Never replace files under a live mount. Host snapshots contain the age key, so they
remain credential-bearing even though `/run` is not persistent. Portable data
backups exclude `/etc/canary/keys` and `/run/canary`.

## Access that equals secret access

The host key is deliberately persistent, so these AWS permissions are equivalent
to reading every production secret. Grant them only to the account owner with MFA,
and deny them to automation and day-to-day IAM users:

- `lightsail:GetInstanceAccessDetails` (browser SSH; issues a root-capable key);
- `lightsail:CreateInstanceSnapshot`, `CreateInstancesFromSnapshot`,
  `ExportSnapshot`, `CopySnapshot`, and the automatic-snapshot add-on settings;
- `lightsail:DownloadDefaultKeyPair` and `lightsail:CreateKeyPair`/`ImportKeyPair`.

Do not keep the Lightsail default key pair on the instance after the admin key is
installed. Any user in the host's `docker` group is root; keep that group empty.

Vertex is a cutover gate, not a follow-up: production must use a dedicated Google
service account granted only `roles/aiplatform.user` on the Vertex project, not a
person's `authorized_user` refresh token. A personal token usually carries the
`cloud-platform` scope for everything that person can reach and would sit in
every host snapshot. Store the service-account credential in the bundle's
`google-adc.json` with `set --name google-adc.json`.

## Validation and outstanding activation evidence

Provider-free tests:

```sh
novel_to_comic/.venv/bin/python -m pytest \
  novel_to_comic/tests/test_secret_delivery.py \
  novel_to_comic/tests/test_entrypoint.py -q
```

Real encryption tests require `sops` and `age-keygen` in PATH; skips do not prove
encryption/recovery. Tests cover both recipients, a wrong key, export failure,
redacted errors, special characters, permissions, materialization integrity,
ignored ambient SOPS settings, exact decryptor sets, untrusted tool paths,
in-memory `set`, loader digests, swap refusal, and mount-aware pruning.
`test_entrypoint.py` verifies the per-process credential split. A hardened
container (read-only, no capabilities, no network) was started from a local
image to confirm both processes boot and the health probe passes.
An isolated network-disabled Linux container also exercised tmpfs, actual loader
exec and ADC delivery; its configured Docker environment did not contain the
dummy values. Compose configuration rendering was checked with dummy public settings.

Remaining live gates: 1Password recovery custody/readback, host bootstrap,
Vertex service-account replacement, Lightsail IAM/snapshot restrictions,
active/staged Fly inventory, credential expiry/refresh (including Bedrock if
used), both-recipient recovery with the real encrypted bundle, isolated candidate
startup, systemd maintenance/reboot drill, and the controlled production cutover.
