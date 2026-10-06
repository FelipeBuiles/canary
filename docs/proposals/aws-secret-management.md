# Secret management for the Fly-to-Lightsail migration

**Status: Accepted strategy, October 6, 2026. Secret tooling and delivery templates
implemented; production activation pending. No live secrets exported, rotated,
or installed.** Part of the [AWS migration design](aws-lightsail-migration.md).
See the [executable runbook](../ops/secret-delivery.md) for current commands,
verification, 1Password recovery custody, and remaining launch gates.

## Decision

Use **SOPS with age encryption** for versioned production secret bundles,
with decryption on the Lightsail host immediately before starting the app.
Mount the resulting files read-only from host memory-backed storage. A small
Python bootstrap loader passes the application secrets to the existing
entrypoint as environment variables. Preserve application variable names.

The encrypted production bundle is the authoritative deployed configuration.
Its accepted version is recorded with each release. Keep a recovery copy and
recovery identity outside AWS. Provider consoles remain the authority for
issuing and revoking credentials; password-manager entries record ownership,
expiry, and recovery instructions, not a competing automatically synced config.

[SOPS](https://getsops.io/docs/) supports encrypted structured files and age
recipients. This choice avoids recurring secret-service charges and runtime
cloud API dependencies, but makes key custody, change audit, and rotation our
responsibility. It does not provide managed per-read auditing or automatic
third-party credential rotation.

AWS Secrets Manager is a credible alternative, particularly with EC2 instance
roles or a larger team. Its [published price](https://aws.amazon.com/secrets-manager/pricing/)
is $0.40 per secret-month plus API requests. Price alone is not the reason to
avoid it. On Lightsail, authentication and recovery still need an explicit
design; do not assume an EC2 instance profile is available. An alternative is
CI federation to AWS, runtime resolution, and SSH delivery, with an encrypted
local restart cache. That adds both CI plaintext exposure and AWS integration.
Revisit managed storage when its audit/rotation benefits justify that complexity.

## Storage and trust boundaries

| Material | Authoritative location | Delivery/access |
|---|---|---|
| Non-secret runtime config | Application deployment config | Ordinary reviewed deployment |
| Public `VITE_*` settings | Build configuration | Inlined into browser bundle intentionally |
| Production app secrets | Private configuration repository, `prod/app.sops.json` | Ciphertext delivered over verified SSH; decrypted only by host/operator |
| Vertex ADC JSON | Encrypted field in the same app bundle | Materialized as `/run/credentials/google-adc.json` |
| Backup/registry credentials, origin TLS key | Separate encrypted host-operations bundle | Host services only, never mounted into Canary |
| `POSTHOG_API_KEY` | Protected CI build secret | Existing BuildKit secret mount only |
| Production age private identity | `/etc/canary/keys/age.txt`, root-owned `0600` | Host startup only; never in container, CI, Git, or cloud-init/user-data |
| Recovery age private identity | Independent password-manager vault plus offline recovery copy | Operator access with MFA; never installed on server |
| Deployment SSH private key | Protected deployment environment | Separate from encryption identities; host key pinned |

Create the production age identity on the target host through a verified admin
session. Export only its public recipient. Encrypt each production bundle to
both that host recipient and an independent recovery recipient. Staging has
different keys, bundles, queue, and provider credentials. Operators may use
individual recipients if multiple people need routine secret editing; record
and review this recipient list.

Keep ciphertext outside the application build context in a private config
repository with restricted write access and protected changes. A release
manifest identifies image digest, config version, and **ciphertext digest**.
Do not publish secret-value hashes. Encryption does not prove who authored a
bundle: production deployment accepts only an operator-approved manifest from
the protected workflow. SOPS authentication validates file integrity, not the
release's provenance.

Root/Docker administrators and code deployed to production can access runtime
secrets. So can any AWS principal allowed to open Lightsail browser SSH or to
create, copy, export or restore instance snapshots; the
[runbook](../ops/secret-delivery.md#access-that-equals-secret-access) lists the
permissions to restrict. CI without a decryption key can still exfiltrate secrets if it is
allowed to deploy malicious application code. Protect application releases as
carefully as secret changes; do not describe this as isolation from deployers.

The host private key is persistent so reboot can recover without a human or
external secret API. Consequently **a full host snapshot contains both the
encrypted bundle and its decryption key**. Treat it as credential-bearing:
restrict snapshot/restore access and retention. Portable application backups
exclude the host key and plaintext runtime directory. This design protects
configuration copies, not a compromised host or a stolen restorable host image.

## Secret inventory and migration treatment

Start with names from `fly secrets list -a canary-web`, checked-in config, and
provider ownership records. Do not print values or run an environment dump.
For every name record owner, consumer, source, required/optional status, active
versus staged state, expiry, and rotation procedure. The table below is a
repository-derived starting inventory, not a verified list of deployed secrets.

| Group | Treatment |
|---|---|
| `LITELLM_MASTER_KEY`, `LITELLM_API_KEY` | Preserve initially; validate equality in memory. Rotate together later. |
| `LITELLM_SALT_KEY` | Preserve exactly. Determine gateway persistence/encryption dependencies before any rotation. |
| `CANARY_OPS_TOKEN` | Preserve for cutover/rollback; later coordinate rotation with operator tools and deployment checks. |
| `SUPABASE_SECRET_KEY` | Preserve; server-only. Do not substitute the public/publishable key. |
| `CANARY_QUEUE_DATABASE_URL` | Preserve private queue role/schema and TLS; never substitute a database administrator URL. |
| `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET` | Preserve mode and existing webhook endpoint identity; changing hosting alone does not require new keys. |
| `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `FAL_KEY`, optional `OPENROUTER_API_KEY`, `TOGETHER_API_KEY` | Carry only providers actually enabled. Rotate independently after migration. |
| `FAL_ADMIN_KEY` | Optional gateway-only secret. The FAL handler uses it to fetch actual billed cost; carry it if set on Fly, otherwise costs fall back to estimates. |
| `R2_ACCESS_KEY`, `R2_SECRET_KEY` | Preserve export access initially; use separate bucket-scoped credentials for private backups. |
| `CANARY_VERTEX_ADC_B64` | Fly transport encoding only. Recover the mounted ADC bytes, store encrypted, then materialize the same file path; no base64 runtime env needed. |
| `AWS_BEARER_TOKEN_BEDROCK` or AWS credential tuple, if present | Establish actual route use and expiry. Never copy an admin profile, laptop login cache, or expired session into production. A temporary credential is not an unattended production solution. |
| Gateway `DATABASE_URL`, if present | Verify the actual deployed dependency; do not infer it from local Compose's database. Preserve access and encryption salt if used. |

`SUPABASE_URL`, `VERTEXAI_PROJECT`, `VERTEXAI_LOCATION`, quota project,
`GOOGLE_APPLICATION_CREDENTIALS`, R2 endpoint/bucket/public URL,
`POSTHOG_PROJECT_TOKEN`, and `POSTHOG_HOST` are configuration rather than private
authentication secrets. Keep private tokens out of all `VITE_*` variables.
Google OAuth client secrets configured inside Supabase stay there. Fly deploy
tokens remain available only for the bounded rollback window, then retire.

Vertex requires special attention: the [current ADC workflow](../reference/vertex-ai.md)
can contain a user refresh credential used for service-account impersonation.
Do not carry a personal refresh credential to Lightsail: replacing it with a
dedicated service account limited to `roles/aiplatform.user` on the Vertex
project is a cutover gate. Record that account's owner and key-rotation
procedure, verify token refresh across a normal access-token expiry, and revoke
the personal credential's production use afterwards. Workload federation remains
a separate follow-up design.

If Bedrock is enabled, its production identity and renewal path are a cutover
gate. The secret bundle solves storage, not issuance or renewal. It is not a
reason to install broad long-lived AWS access keys.

## One-time extraction from Fly

[Fly's secret API](https://docs.fly.io/apps/secrets) lists metadata, not plaintext.
Values are supplied to the running Machine, while staged changes may not yet
be active. A local import file may therefore be incomplete or stale.

1. **Reconcile sources.** Prefer provider/password-manager records and the
   existing outside-repository import file. Compare names with Fly metadata.
   Freeze secret changes during the migration. Explicitly identify staged-only
   values; do not restart production simply to make them extractable.
2. **Recover missing active values.** A reviewed one-time exporter runs in the
   existing Fly Machine through authenticated SSH, selects only the approved
   names, and reads the mounted ADC file. Read from the actual runtime context:
   the exporter selects names from the running supervisor's environment, not the
   SSH session's, and fails if no supervisor runs. Never print `/proc` or all
   environment variables.
3. **Encrypt the transfer.** The exporter streams JSON through the SSH channel
   directly into local SOPS encryption with the approved public recipients.
   Redirect only ciphertext to a new file. Both processes run in one command
   pipeline with tracing disabled and failure propagation enabled; no tool
   output, terminal, `tee`, clipboard, temporary plaintext file, or log captures
   the stream. If remote encryption is available, encrypt before SSH transfer.
4. **Validate privately.** The validator checks presence, types, key equality,
   ADC shape, and approved names without logging values or parser excerpts.
   Failures report field names/error codes only. Promote the encrypted file
   only after all pipeline stages and validation succeed. Capture non-secret
   evidence: bundle version, ciphertext checksum, completeness, operator/time.
5. **Reconcile unavailable values.** Retrieve staged-only values from their
   original source. If an original is lost and the Machine is unavailable,
   reissue through that provider. Do not pretend Fly's metadata can recover it.
   Coordinate replacement on both platforms if rollback still needs it.

These requirements are implemented by `export-fly` in the runbook. Never replace
it with a manual `printenv` export. Preserve Fly's existing secrets until rollback
is retired; production export has not been performed.

## Runtime delivery and reboot

The app bundle has a versioned schema with `env` (allowlisted string values)
and `files` (the ADC content). Reject unknown fields, duplicates, missing
required values, null bytes, and unexpected file paths. Never source it as shell
code or perform interpolation. Secret values containing `$`, quotes, newlines,
or backticks must survive unchanged.

1. The host service validates the selected encrypted release before stopping a
   healthy app. Missing/decryption-invalid updates leave the running release
   alone. On cold boot, invalid/missing material fails closed.
2. Decrypt with root-only access into a version-specific directory under
   `/run/canary/secrets/`; verify that it is tmpfs. Use `0700` directories and
   `0600` files, matching the current container UID. Keep swap disabled or
   encrypted, disable core dumps, and exclude this directory from backups.
3. Mount only `runtime.json` and ADC read-only into the app. The host key and
   encrypted host-operations bundle never enter the container.
   [Compose secrets are file mounts](https://docs.docker.com/compose/how-tos/use-secrets/),
   not an encrypted vault; enforce actual source-file permissions.
4. A tested bootstrap loader reads the JSON and calls `execve` on the existing
   `/app/entrypoint.sh` with the allowlisted environment. Do not put resolved
   values in Compose `environment`, `env_file`, Docker command arguments, or
   image metadata. This avoids storing these values in Docker's configured
   environment; process memory/environment still contains them and root can
   inspect them. The entrypoint passes provider keys only to the gateway and
   billing, database and operator credentials only to the web process.
5. Preserve `/run/credentials/google-adc.json` and the corresponding path config.
   SDK refresh reads the file normally. No cloud credentials are required to
   decrypt this local bundle.
6. The systemd supervisor owns recreation after reboot; Docker has no competing
   automatic restart policy. Materialize secrets before container creation and
   respect the persistent maintenance hold and existing crash budget.
7. Delete the old plaintext directory only after its container stops; the unit's
   `prune` step does this automatically and skips anything still mounted. Single-file
   bind mounts do not follow replacement inodes reliably: changing a bundle
   requires controlled container recreation, not overwriting a mounted file.

The loader and host service templates are implemented but not activated. Merely mounting a
Compose secret does not teach the existing app to consume it, and `_FILE`
variables are not automatically supported by third-party SDKs.

## Releases, rotation, rollback, and recovery

**Ordinary code release:** reuse the accepted bundle version. CI builds using
public config and its build-only PostHog credential, publishes an image digest,
and asks the host deploy service to install the approved image/config pair.
CI never receives an age private key. The host uses its local operations token
for drain/resume so CI need not hold another runtime token copy.

**Secret change:** the operator updates the encrypted bundle in a trusted
environment with editor swap/history/crash artifacts disabled. Record a reason
and affected names. Issue the replacement credential first where the provider
supports overlap; stage the bundle, validate, drain, recreate, check readiness,
then resume. A read-only authenticated provider check is preferable to paid
generation. Revoke the old provider credential after the agreed rollback window.

Database passwords without overlap require coordinated updates and downtime,
or a deliberately provisioned second least-privilege role. Stripe signing-key
rotation must account for pending deliveries and application support for
overlap. LiteLLM salt rotation needs a separate data migration assessment.
No blanket “rotate everything at cutover” step.

**Rollback:** record which previous credentials are still valid. Reverting an
encrypted file does not undo provider revocation. Keep one explicit compatible
prior image/bundle pair during the seven-day migration rollback window, and
carry current valid credentials back to Fly if necessary. Compromised credentials
are revoked immediately; security recovery overrides that rollback window.

**Lost host:** use the independent recovery identity and encrypted bundle copy
on a new Linux host, create a new host identity, update recipients, and prove
startup/refresh. No surviving Fly Machine or AWS secret API is required.

**Compromised host or departing recipient:** revoke affected provider secrets,
replace the host/recipient identity, remove the old recipient, and rotate the
bundle data key. Recipient removal cannot revoke access to old ciphertext
copies; service-side credential rotation is essential. Destroy obsolete
credential-bearing snapshots per retention policy after recovery is secured.

## Implementation acceptance

- Schema/exporter/loader tests use dummy secrets and exercise special characters,
  malformed input, missing required fields, unintended names, and redacted errors.
- Dummy sentinel values never appear in CI/build logs, Docker inspect configuration,
  image history, Compose rendering, or captured deploy output; the running child
  receives them correctly. Test ADC delivery and absent-file failure.
- Reboot restores the accepted bundle before app startup; a deliberate maintenance
  stop remains stopped. Missing keys fail closed; bad updates preserve the old app.
- Drain/recreation preserves durable work and does not retry ambiguous paid calls.
- A recovery drill succeeds using only the off-AWS encrypted backup and recovery
  identity, including restoring outside AWS. Document credential expiry ownership.
- Record live inventory completeness and staged-secret reconciliation before
  deleting any Fly resources. Confirm that no leftover Fly/local import copy is
  the sole surviving source of a required credential.

The schema, loader, host materializer, exporter, and dummy-data tests are
implemented. Actual production export/install belongs to the controlled migration;
it has not happened as part of this work.
