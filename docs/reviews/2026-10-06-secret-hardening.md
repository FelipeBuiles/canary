# Secret hardening review and migration gates

**Status: Review snapshot, October 6, 2026. Uncommitted working-tree review.**
No infrastructure changes or live secret reads were performed. Review covers
the current working tree (including untracked files) against the accepted
[secret strategy](../proposals/aws-secret-management.md) and the previously
implemented tooling. It does not certify a production deployment.

## Findings

### Standards/security: P2 — tool trust misses writable ancestors

`scripts/canary_secrets.py`, `trusted_tool`, verifies the resolved binary and
its immediate parent, but not ancestors. A mode-0755 `shared/bin/sops` is
accepted when `shared` is mode-0777. Another user can replace `bin` and execute
a replacement tool that receives plaintext credentials. Reproduced with dummy
files. Validate the full path's replaceability, including appropriate handling
of sticky directories, and test this case. Protected `/usr/local/bin` installation
mitigates the immediate deployment risk but does not satisfy the helper's guarantee.

### Spec: P2 — FAL billed-cost credential cannot be migrated

The bundle allowlist excludes `FAL_ADMIN_KEY`, although
`litellm_handlers/fal_provider.py::_billing_cost` uses it to retrieve actual
request charges. If that credential is configured on Fly, migrating with the
current schema disables billed-cost lookup and falls back to labelled estimates.
The strategy permits this credential when a runtime feature requires it, and
the entrypoint already assigns it to the gateway. Add optional schema support
with tests and include it in the production inventory, or make an explicit
decision to disable this capability. Do not silently omit it during export.

### Corrected assessment: non-Fly rate limiting

The asserted universal Docker-gateway rate-limit bucket is not inherent in the
current code. Installed Uvicorn middleware with trusted peer `172.29.88.1`
rewrites the request client, and the existing limiter uses that value. Focused
checks confirmed distinct visitor handling, ignoring a forged left prefix, and
ignoring forwarding headers from an untrusted peer. Nginx must still validate
Cloudflare's source and overwrite forwarding headers with the verified visitor.
The full Cloudflare/Nginx/Docker path is unverified and remains a launch gate.

## Resolution (October 6, 2026)

Both findings are fixed in the working tree. `trusted_tool` checks every
ancestor up to `/`, allowing only sticky shared directories; Homebrew installs are
therefore refused and the runbook requires root-owned tool paths. `FAL_ADMIN_KEY`
is an optional bundle name, kept gateway-only by the entrypoint split. Tests
cover both; the real SOPS/age tests run private tool copies.

## Verification

- 64 focused tests passed: secret delivery, entrypoint supervision/environment
  splitting, and CLI proxy trust. Real SOPS/age tests ran without skips.
- Independently reproduced the writable-ancestor finding and checked the FAL
  allowlist against its runtime consumer.
- Exercised Uvicorn middleware through `Request` and `ratelimit.client_ip` with
  trusted/untrusted peers and a forged prefix, without network/provider calls.
- The previous report's full backend result was not rerun; it remains reported
  evidence rather than an independent full-suite verification.
- The reported October 1 image smoke test does not validate the newly changed
  entrypoint or loader. Build and exercise the exact candidate image before release.

Root operation is a documented residual risk, not a newly established startup
bug. Environment stripping reduces accidental exposure, but shared UID, mounts,
and supervisor credentials do not provide process-level secret isolation.

## Required order for production activation

1. **Close the two findings and freeze a release.** Run focused regression tests,
   lint and docs checks. Build the current source with public frontend settings
   and the build-only PostHog secret, pin its OCI digest, and record the matching
   host/image loader SHA-256 and ciphertext SHA-256. The old smoke image is not
   the candidate. Preserve an explicit prior compatible image/bundle pair.
2. **Confirm the hosting decision.** Verify the grant's eligible services and
   exact expiry, remaining credits and paid-account budget alerts. Select the
   region and fixed VM size. Restrict Lightsail SSH/snapshot/export permissions
   and host administration; these can grant access to all runtime secrets.
3. **Bootstrap recovery and host custody.** Save the independent recovery key
   as a restricted 1Password Document, retrieve it, and prove decryption. Keep
   an offline copy. Create a different host identity; pin its public recipient
   through a verified SSH connection. Install reviewed tools into protected
   paths. Do not expose either identity to CI or the app.
4. **Reconcile and prepare credentials while Fly is still running.** Inventory
   active and staged secrets; preserve gateway salt/key relationships, Stripe
   endpoint identity, queue credentials, and required provider billing credentials.
   Export only the reviewed names into encrypted storage, verify both recipients,
   and separately reconcile staged-only values. Replace personal Vertex refresh
   credentials with an approved dedicated production identity. Confirm Google
   organization policy permits the chosen mechanism; if service-account keys
   are prohibited, resolve federation/approved credential issuance before cutover.
   Check Bedrock expiry/renewal if enabled. Neither JSON validation nor startup
   proves provider token refresh. No paid generation is needed for these checks.
5. **Prepare the isolated candidate.** Install templates, pinned image and matching
   loader, root-owned project files (including nested files and write directories),
   root-only tmpfs/keys, no swap or explicitly verified encrypted swap, bounded
   logs and maintenance hold. Use an isolated queue/database and sanitized data;
   never attach a rehearsal worker to the production queue alongside Fly.
6. **Finish platform controls.** Configure Nginx, origin TLS, Cloudflare-only
   ingress and authenticated origin access; validate the actual Docker peer.
   Verify two visitors get distinct rate limits, forged headers cannot bypass
   them, direct origin access is blocked, and auth cookies/SSE/uploads work.
   Exercise PDF/CBZ export and representative sustained load under the read-only
   filesystem, dropped capabilities, 1 GB tmpfs and 4 GB RAM limits. Do not
   assume the health check proves export compatibility or sustainable performance.
7. **Prove recovery and releases on Linux.** Exercise real systemd cold boot,
   maintenance stop/reboot, bounded crash recovery, swapped-memory refusal,
   and prune with a live container mount. Confirm bad candidate verification
   leaves the healthy release running. Establish private off-AWS backups and
   a timed restore of files, journals, queue and billing state; preserve ambiguous
   paid outcomes without replay. Implement or rehearse the documented drain,
   verify and explicit resume transaction before unattended deployment.

## Cutover and retirement

1. Enter public maintenance for **all mutations**, including lettering and
   metadata. Coordinate Stripe webhook retry/reconciliation without acknowledging
   discarded events. Drain generation through the authenticated API and require
   both `draining: true` and `safe_to_deploy: true`; queued work may remain queued.
2. Stop and fence Fly. Make the final consistent complete `/projects` copy,
   including hidden journals/outbox/recovery inputs, and record database recovery
   coordinates. Verify transfer integrity. Prefer retaining the same Supabase
   app/queue data for this move rather than doing a database migration too.
3. Start AWS **drained**, with the production queue only after Fly has stopped.
   Verify version, dependency readiness and file ownership. Switch the Cloudflare
   origin, run safe production checks, reconcile webhooks, then explicitly resume
   and remove public maintenance. A local file lock does not fence two hosts.
4. Observe workload, cost, CPU bursts, memory, errors and a complete backup cycle
   for 48–72 hours. Retain the documented seven-day rollback window before
   deliberately retiring Fly resources and unnecessary credentials/copies.
5. Before AWS has accepted writes, rollback can stop AWS and restart unchanged
   Fly. After AWS accepts writes, first drain/stop AWS and reverse-transfer the
   latest files/journals to Fly while reconciling queue/billing events. DNS reversal
   alone is unsafe. Do not overwrite the live credit ledger with an old backup.

## Setup evidence — 2026-10-06

Initial host setup has begun; production activation and cutover have not run.

- The user created `canary-prod` in `us-east-1a`: Ubuntu 24.04, bundle
  `medium_3_0`, static IPv4 attached. AWS reports SSH restricted to the
  operator's IPv4 plus Lightsail browser SSH, with no IPv6 SSH rule.
- The independent recovery identity was downloaded from its 1Password Document
  and successfully tested against a dummy encrypted bundle. The server has a
  distinct age identity, stored root-owned with mode `0600` inside a `0700`
  directory. No recovery private key was copied to the server.
- SSH from the operator Mac was verified against the ED25519 fingerprint
  obtained through the AWS browser terminal. The login key and dedicated
  known-hosts file are owner-only under `~/.ssh/canary-prod/`.
- Docker Engine 29.8.2 and Compose 5.6.0 were installed from Docker's signed
  repository. SOPS 3.13.3 was checked against the upstream release SHA256 file
  and installed root-owned. The Linux tool-ownership checks passed.
- The installed secrets loader SHA256 is
  `327e1376e546fae0f2a64d8f2a4a08403fbc7ee0110e00d80ce9e8dce10bff61`.
  This records the setup copy, not approval of a candidate image; later changes
  require matching host/image copies and an updated deployment digest.
- A fresh dummy bundle encrypted to the actual host and recovery recipients
  decrypted successfully with each identity independently. Real Linux tmpfs
  materialization and idempotent reuse passed with swap disabled; a mismatched
  loader digest was refused. Prune preserved a file mounted by an isolated
  BusyBox test container and removed it after that container was removed.
  Temporary dummy files and the test container were removed.
- `/etc/canary/maintenance` is present. No Canary service or production image
  was started, and no production secrets, project files, queue connections,
  or traffic were migrated. HTTP port 80 remains publicly reachable at the
  Lightsail firewall; edge configuration is still pending.

Credit eligibility/expiry and budget alerts, dedicated provider credentials,
exact candidate-image tests, edge verification, full Linux service rehearsal
(including reboot and swap refusal), and a restore drill remain prerequisites
to activation. The live-container prune test above does not establish these
other release gates.

### Fly credential inventory and encrypted draft

Read-only inspection of running Machine `48e7295a973948` found all eight
required bundle credentials and seven optional credentials: `OPENAI_API_KEY`,
`ANTHROPIC_API_KEY`, `FAL_KEY`, `OPENROUTER_API_KEY`, `TOGETHER_API_KEY`,
`R2_ACCESS_KEY`, and `R2_SECRET_KEY`. The gateway keys match. Fly reports all
31 configured secret entries as deployed, with none staged. `FAL_ADMIN_KEY`,
`DATABASE_URL`, and `AWS_BEARER_TOKEN_BEDROCK` were absent from the running
supervisor; do not invent replacement values during migration.

A 15-credential draft was exported directly from the running supervisor to
`~/.config/canary/prod/2026-10-06-fly-without-google.sops.json`, with no plaintext
disk intermediate or credential values in output. Its SHA256 is
`7057f749764dee278ce6bec22c555dabe1f28356bcb4449ef248741027a25604`.
The exact host/recovery recipient set and recovery-key decryption passed.
This draft remains on the operator Mac, excludes all Google credentials, and
is not an activation-ready bundle. Host decryption of this actual draft is
still pending; the earlier host proof used dummy credentials only.

The live Vertex ADC impersonates `canary-vertex` in
`project-b9574d1f-6b2c-4762-aff` using `authorized_user` source credentials.
The legacy `GCP_CREDENTIALS_B64` also contains an `authorized_user` credential;
neither personal credential was exported. The user identified
`juan@scenewright.ink` as the project administrator. Its CLI login is needed
to inspect effective IAM permissions and service-account key policy before
selecting the production credential mechanism.

The Lightsail template now preserves `CANARY_BACKOFFICE_ORIGINS` and
`CANARY_INTERNAL_ACCOUNT_IDS` as explicit non-secret settings. Populate them
from the active configuration before cutover. Compose configuration validation
passed with dummy settings. Legacy Sentry names have no consumers in the
current backend source and are not added to the encrypted credential schema.

### Vertex IAM and credential-policy decision

After the administrator login, live reads confirmed the dedicated
`canary-vertex` account is enabled, has `roles/aiplatform.user` in the project,
and has no user-managed keys. Its impersonation policy grants the administrator
`roles/iam.serviceAccountTokenCreator`. The organization IAM policy showed no
direct or broad-domain grant to this service account; group-based or external
resource grants were not exhaustively audited.

The Organization Policy API was enabled to inspect effective policy; no
constraint was changed. Effective `iam.disableServiceAccountKeyCreation` is
enforced, even though `iam.managed.disableServiceAccountKeyCreation` is not.
Therefore creating a JSON key is currently prohibited. The administrator's
observed organization bindings did not include Organization Policy Administrator
or Tag Administrator; policy/tag changes may require temporary scoped grants.

Proposed bounded exception, pending user approval: preserve the organization
default and add a conditional exception in this Vertex project for a dedicated
issuance tag attached only to `canary-vertex`. Create one server key, encrypt
it directly into a new host/recovery bundle, validate authentication without
generation, then remove the exception/tag and any temporary administrative
grants. Recheck effective enforcement after cleanup. The issued key remains
valid until explicitly rotated/revoked; restoring the creation restriction
does not revoke it. Do not leave the exception in place as a convenience for
future rotations. Save the prior policy and use its concurrency controls during
any approved update.

Alternative: retain the restriction and implement workload identity federation;
this requires a supported external workload identity and changes to the current
ADC delivery schema. No policy exception, IAM grant, new key, or federation
configuration has been created. Source: Google's
[service-account policy troubleshooting](https://docs.cloud.google.com/iam/docs/troubleshoot-org-policies).

### Approved credential issuance completed — 2026-10-06

The user explicitly approved the scoped exception and, after automatic review
blocked the initial broader role grant, separately approved temporary
organization-wide Policy Administrator and Tag Administrator roles. Those
bindings had a one-hour expiry and were removed immediately after cleanup.
A Tag User grant existed only on the temporary tag value and disappeared when
that value was deleted. The exception was a conditional project policy tied to
a tag on `canary-vertex` only; the organization default was never changed.

- Exactly one user-managed key was issued:
  `a069e44e3cc3aee31596a4438c236bc77c83f822`. The JSON key was handled in process
  memory and encrypted directly into a new bundle, without a plaintext file.
- The completed bundle contains the 15 inventoried credentials and the dedicated
  service-account ADC. It contains neither personal Google refresh credential.
  Local path: `~/.config/canary/prod/2026-10-06-production.sops.json`.
  SHA256: `2ca9b6bdae2297b95dee42fec127d75ba621f0399d7e8d310053649925a4c0fa`.
- Recovery-key decryption passed. The same ciphertext was installed root-owned
  under `/etc/canary/bundles/<SHA256>.sops.json` on Lightsail; host-key decryption
  and schema/service-account checks passed in memory, with no plaintext files
  materialized. `/etc/canary/maintenance` remains present.
- The new service-account credential successfully refreshed twice and read the
  Vertex locations API. No paid generation was invoked. An optional Resource
  Manager `testIamPermissions` call was unavailable because that API was
  disabled for the calling context; it was not enabled solely for this probe.
  These checks do not replace candidate-image/provider integration verification.
- The temporary project policy was deleted using its exact etag to restore
  inheritance. The tag binding, tag value, tag key, and both temporary
  organization IAM bindings were removed. Follow-up reads confirmed effective
  key-creation enforcement, no remaining issuance tags or temporary IAM bindings,
  and exactly one user-managed key.
- The key has no practical automatic expiry. Plan rotation by 2027-01-04
  (90 days after issuance), or earlier if exposure is suspected. Rotation must
  include a fresh approved issuance exception, new encrypted bundle, verification,
  controlled deployment, and revocation of the previous key. No rotation
  automation has been configured.

Fly credentials, the running Fly Machine, production traffic, and the production
queue remain unchanged. No Canary process has started on Lightsail. The older
encrypted draft remains local as a clearly named draft; deploy only the completed
bundle after the remaining activation gates pass.
