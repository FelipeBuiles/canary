# Lightsail releases from Depot CI

**Status: CI access provisioned on 2026-10-06; deployment is
not activated or live-deploy verified.** Fly is
still production. Do not enable unattended releases until the initial migration,
single-owner fencing, edge checks, candidate-image tests and restore rehearsal
in [the migration plan](../proposals/aws-lightsail-migration.md) pass.

Depot remains the CI runner and image builder. `.depot/workflows/ci.yml` saves
the production image in Depot's OCI registry (`registry.depot.dev/js338b6zll`),
smoke-tests its immutable digest and passes that exact digest to Lightsail.
The old Fly registry login, Fly deploy command and `skip_drain` bypass are removed.
Changing these files does not start a deployment. Publishing them stops automatic
Fly deployments; the Lightsail deploy job skips until explicitly enabled below.

## Release transaction

All existing backend, web, gateway, tooling and PostgreSQL checks remain gates.
The release build runs alongside them, before any drain. The build pins
`linux/amd64`, embeds the source SHA and checks its loader hash against source.
The deployment job is serialized and never cancels a running deployment.

1. CI assumes an AWS role through Depot OIDC, opens TCP 22 for the runner's
   public IPv4 `/32` only, and connects with a dedicated deployment SSH key and
   a pre-pinned host key. Existing operator/browser SSH rules remain unchanged.
2. The SSH forced command accepts only a bounded JSON request containing an
   immutable allowed-registry digest, full source SHA, loader hash and a
   short-lived read-only Depot pull token. It does not offer a shell or forwarding.
3. The host starts `canary-release.service` as a transient systemd unit. It has
   its own runtime limit and lock and continues if the SSH connection disappears.
   CI waits for the result; a lost response is an unknown outcome, not permission
   to retry or roll back blindly. Inspect the host first.
4. The host requires both `/etc/canary/ci-enabled` and an already active
   `canary.service`, and refuses `/etc/canary/maintenance`. It decrypts the existing
   bundle in memory to obtain the ops token. No app/Google/age credentials go to CI.
5. It requires tmpfs, disabled swap and at least 8 GiB free in Docker's filesystem.
   It pulls the image before draining, checks its source SHA and loader bytes,
   and validates Compose configuration. Registry login files are created under
   `/run` and removed after the pull. Candidate-loader changes require an explicit
   reviewed host update; CI never silently replaces host deployment tooling.
6. It drains the local app and waits for both `draining` and `safe_to_deploy`.
   It saves the old complete deployment environment under `/etc/canary/releases/`,
   stops the owner, atomically updates the image setting, and starts the candidate.
7. The candidate must report the expected SHA, readiness and persisted drain.
   The installed public verifier checks the public SHA, security headers and
   dependencies before explicitly resuming. A successful local admission check
   completes the release.
8. CI removes only its temporary SSH rule in `finally`, including ordinary
   errors and SIGTERM. Hard termination or loss of AWS access can leave the rule;
   the runner CIDR is logged for operator removal. This is not a firewall lease.

Failures before replacement leave the existing process in place (possibly
drained). Failures during replacement create a maintenance hold and stop the
candidate. There is no automatic resume, image rollback, data rollback, secret
rotation, schema migration, instance provisioning, or initial cutover.

## One-time host installation

Install these reviewed files root-owned, with mode `0755` for Python files and
`0644` for the unit and Compose file:

| Repository file | Host path |
| --- | --- |
| `deploy/lightsail/release.py` | `/usr/local/lib/canary/release.py` |
| `scripts/verify_deployment.py` | `/usr/local/lib/canary/verify_deployment.py` |
| `scripts/canary_secrets.py` | `/usr/local/lib/canary/canary_secrets.py` |
| `deploy/lightsail/compose.yaml` | `/usr/local/lib/canary/compose.yaml` |
| `deploy/lightsail/canary.service` | `/etc/systemd/system/canary.service` |

Use `systemd-analyze verify /etc/systemd/system/canary.service`, then
`systemctl daemon-reload`. Keep the maintenance hold throughout setup. Configure
the root-owned `0600` environment and encrypted bundle as described in
[secret delivery](secret-delivery.md). The image's loader digest, host loader
digest and `CANARY_LOADER_SHA256` must all match.

Create a dedicated `canary-deploy` account with a locked password, a valid shell
for SSH's forced-command execution, and no Docker/admin group membership.
Create a separate SSH key solely for CI; never reuse the operator's Lightsail
default private key. Store its public key with the `restrict` option in the
root-owned `/etc/ssh/authorized_keys/canary-deploy`. Set this SSH configuration:

```text
Match User canary-deploy
    AuthorizedKeysFile /etc/ssh/authorized_keys/%u
    PasswordAuthentication no
    KbdInteractiveAuthentication no
    PermitTTY no
    AllowTcpForwarding no
    AllowAgentForwarding no
    X11Forwarding no
    PermitTunnel no
    ForceCommand sudo -n /usr/bin/python3 /usr/local/lib/canary/release.py
Match all
```

Install this exact sudoers entry with `visudo` validation:

```text
canary-deploy ALL=(root) NOPASSWD: /usr/bin/python3 /usr/local/lib/canary/release.py
```

The argument path in the sudoers entry is intentional: it must not authorize
arbitrary Python programs or the controller's `--worker` invocation. Validate
with `sshd -t` before reloading SSH. Keep the browser/admin session available.
Treat the deployment key as privileged: choosing executable application images
ultimately grants access to runtime secrets even without an interactive shell.

## AWS and Depot configuration

Create an AWS OIDC provider for `https://identity.depot.dev`, audience
`sts.amazonaws.com`. The deployment role trust must match this repository's
**main branch**, not all repositories or all refs:

```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": {"Federated": "arn:aws:iam::ACCOUNT_ID:oidc-provider/identity.depot.dev"},
    "Action": "sts:AssumeRoleWithWebIdentity",
    "Condition": {
      "StringEquals": {"identity.depot.dev:aud": "sts.amazonaws.com"},
      "StringLike": {
        "identity.depot.dev:sub": "spiffe://identity.depot.dev/org/6ntrqswcbt/ci/github/FelipeBuiles/canary/ref/refs/heads/main/sandbox/*"
      }
    }
  }]
}
```

Allow only `lightsail:OpenInstancePublicPorts` and
`lightsail:CloseInstancePublicPorts` on the exact `canary-prod` instance ARN.
Use a separate `lightsail:GetInstancePortStates` statement with `Resource: "*"`:
that read action does not support instance resource scoping in the
[AWS authorization reference](https://docs.aws.amazon.com/service-authorization/latest/reference/list_lightsail.html).
Both statements require `aws:RequestedRegion = us-east-1`. The code restricts changes
to TCP 22 and one `/32`; the role can still modify other ports on that instance,
so protect main and the workflow. It needs no instance creation, snapshots,
browser SSH, default-key download, S3, billing or general administrator access.
Use Depot's documented [OIDC claim format](https://depot.dev/docs/ci/oidc), and
verify the actual subject during setup before enabling deployment.

Configure the following Depot entries, each scoped to repository
`FelipeBuiles/canary`, branch `main`, workflow `.depot/workflows/ci.yml`, environment
`production`, with no unscoped fallback:

| Kind | Name | Value |
| --- | --- | --- |
| Secret | `LIGHTSAIL_SSH_PRIVATE_KEY` | Dedicated forced-command deployment key |
| Variable | `LIGHTSAIL_HOST` | `52.203.15.28` (current static IPv4) |
| Variable | `LIGHTSAIL_SSH_KNOWN_HOSTS` | Verified full ED25519 known-hosts entry for that IP |
| Variable | `LIGHTSAIL_CI_ROLE_ARN` | Scoped firewall role ARN |
| Variable | `CANARY_DEPLOY_TARGET` | Leave unset until activation; then `lightsail` |

Retain the frontend build and PostHog source-map settings. This workflow no longer
uses `FLY_API_TOKEN` or `CANARY_OPS_TOKEN`. Retire their Depot copies after the
rollback window and checking other workflows. Do not import the encrypted app
bundle, Google key, host age identity or recovery identity into CI. Depot supplies
its own short-lived job authentication; the host receives only a
[read-only pull token](https://depot.dev/docs/cli/authentication).

## Activation and recovery

### Provisioning evidence (2026-10-06)

- Created OIDC provider `arn:aws:iam::569757033859:oidc-provider/identity.depot.dev`
  and role `arn:aws:iam::569757033859:role/canary-depot-lightsail-deploy`.
  The trust uses the audience and main-branch subject shown above. Its only
  inline policy, `CanaryInstanceFirewall`, targets instance
  `arn:aws:lightsail:us-east-1:569757033859:Instance/050a6c71-cc30-4f86-a1e2-30a6fa5b69ae`
  for mutations, with the separate read statement described above.
- IAM simulation allowed the three intended actions in `us-east-1`, denied
  mutations on another instance, and denied all three in another region.
  Snapshot creation, default-key download, browser SSH, instance creation and
  IAM role creation were denied. This verifies policy evaluation, not live OIDC
  federation; the actual Depot token and AWS session still need a CI rehearsal.
- Installed the release controller, public verifier, Compose file and systemd
  unit on the host. The existing secrets loader was retained. `visudo`, `sshd -t`
  and `systemd-analyze verify` passed; SSH was reloaded and operator access retested.
- Created the locked `canary-deploy` account with only its own group. The key is
  forced to the controller; live SSH tests rejected both an empty request and
  an arbitrary shell command while activation was disabled. Separate sudo probes
  rejected arbitrary commands and the controller's `--worker` arguments.
- Created `LIGHTSAIL_SSH_PRIVATE_KEY` and the three `LIGHTSAIL_*` variables in
  Depot, each under the `lightsail-production` variant and all four scopes
  listed above. The dedicated local key is
  `~/.ssh/canary-prod/depot_ed25519` (mode `0600`); it is separate from the
  operator key. No application or age secrets were uploaded to Depot.
- Confirmed `/etc/canary/maintenance` exists, `/etc/canary/ci-enabled` is absent,
  `CANARY_DEPLOY_TARGET` is absent in Depot, and `canary.service` is inactive.
  No production drain, image pull, application startup, DNS change, or Fly
  mutation was performed during this provisioning step.

### Remaining activation steps

The first live authentication attempt on 2026-10-06 exposed a Depot local-run
limitation: `depot ci run` uses a commit SHA as the OIDC `ref`. A direct `Run`
API request with `ref: refs/heads/main` produced the same SHA-based token.
The role correctly rejected it; its trust was not broadened. The diagnostic
printed only selected identity claims, never the token. Runs:
`5dr7xk9qs5` (AWS rejection), `6j44vjn6sm` (identity diagnostic).

The manual-only `.depot/workflows/lightsail-preflight.yml` is included with the
migration CI changes. Once published on main, dispatch it with:

```sh
depot ci dispatch --org 6ntrqswcbt --repo FelipeBuiles/canary \
  --workflow lightsail-preflight.yml --ref main
```

It assumes the production role and reads firewall state only. It neither uses
the SSH key nor changes the firewall. Publishing to main is a separate step:
the currently published CI still deploys to Fly on a main push. Review and land
the migration CI changes with Lightsail activation disabled before using this
preflight; do not inadvertently dispatch the old deployment workflow.

Only after the manual first migration has fenced Fly, transferred the complete
project volume, started and verified Lightsail, switched the origin, and passed
the migration gates, create root-owned `0600` `/etc/canary/ci-enabled` and set
the Depot activation variable. Normal CI requires an active existing owner and
cannot perform the first startup. There is no `skip_drain` override.

Rehearse the controller with isolated data/queue before activation: invalid image
and loader, drain timeout, failed startup, public verification failure, runner
disconnect, reboot, cancellation, and two competing requests. Unit tests are not
evidence of production-safe systemd, IAM, network or proxy behavior.

For an uncertain release inspect `journalctl -u canary-release`,
`systemctl status canary`, the current environment, `/api/version` and admission
status before acting. A CI failure can coincide with a successful host release.
Saved environments contain the image, bundle path/hash and loader hash; retain
the corresponding image and ciphertext. Do not restore an old environment while
the service is running. A failed candidate may have changed data; apply the
migration plan's data/queue/billing reconciliation rules before any rollback.
Explicit resume follows verification, never cleanup.

No image or environment-history pruning is automatic. Monitor disk usage and
retain the rollback pair plus needed evidence; remove obsolete images during
reviewed maintenance. These workflows add no new AWS instance, load balancer,
database, container service or persistent registry credential.
