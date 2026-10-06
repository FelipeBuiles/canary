# Lightsail releases from Depot CI

**Status: Lightsail became production on 2026-10-06. Fly is stopped and fenced.
CI activation is enabled; the first complete live CI release passed.**
See the dated cutover evidence below for checks and remaining limitations.

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

Configure the deployment credentials and connection entries scoped to repository
`FelipeBuiles/canary`, branch `main`, workflow `.depot/workflows/ci.yml`, environment
`production`, with no unscoped fallback:

| Kind | Name | Value |
| --- | --- | --- |
| Secret | `LIGHTSAIL_SSH_PRIVATE_KEY` | Dedicated forced-command deployment key |
| Variable | `LIGHTSAIL_HOST` | `52.203.15.28` (current static IPv4) |
| Variable | `LIGHTSAIL_SSH_KNOWN_HOSTS` | Verified full ED25519 known-hosts entry for that IP |
| Variable | `LIGHTSAIL_CI_ROLE_ARN` | Scoped firewall role ARN |
| Variable | `CANARY_DEPLOY_TARGET` | Leave unset until activation; then `lightsail`; see scope exception below |

The non-secret `CANARY_DEPLOY_TARGET` activation flag is scoped to repository,
main and workflow, without an environment selector, so it can be evaluated by
the job-level condition. Keep the SSH secret and connection variables scoped
to `production` as above. Run `mcf4dgqxgk` passed its tests/build but skipped
deployment when the flag also had the environment selector.

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
  IAM role creation were denied. Live main-branch OIDC federation and restricted
  SSH subsequently passed in preflight run `clhzrddvrt`.
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
migration CI changes, now published on main. Dispatch it with:

```sh
depot ci dispatch --org 6ntrqswcbt --repo FelipeBuiles/canary \
  --workflow lightsail-preflight.yml --ref main
```

The AWS-only preflight passed on 2026-10-06 in run `j1jxgsn23z`; the extended
SSH preflight passed in run `clhzrddvrt`. An independent AWS read confirmed
the temporary runner rule was removed and the original firewall preserved.
The extended preflight also runs `deploy_lightsail.py --check-access`: it opens
TCP 22 for the runner's public IPv4 only, uses the pinned SSH key, sends an empty
JSON object (never a valid release request), and requires the controller's fixed
rejection. It obtains no registry token and cannot start a release even if
deployment is subsequently enabled. It removes its temporary rule in `finally`
and verifies that the rule is absent. A hard runner termination can still leave
a rule; inspect the logged CIDR and remove it manually if needed.

The SSH secret and host/known-host variables also have a separate
`lightsail-preflight` variant scoped to this workflow, main, repository and
production environment. Production CI retains its original scope. The published
workflow builds the candidate image and skips Lightsail deployment while
`CANARY_DEPLOY_TARGET` is unset. Automatic Fly deployment has been removed.

### Isolated host runtime evidence (2026-10-06)

Candidate `bee4fdb1b12f91e83852b6deed48bd8f7ae05efb` passed all CI gates in
[workflow z2dvcn4sp4](https://depot.dev/orgs/6ntrqswcbt/workflows/z2dvcn4sp4);
production deployment was skipped. The tested image is
`registry.depot.dev/js338b6zll@sha256:d0b7892911bcf8f9adeb1592405f520d3b260efebc1f110642ff56d420a0cfbf`.

The existing Lightsail VM ran that exact image under a temporary
`canary-rehearsal.service`. The candidate's unit and Compose templates retained
the read-only filesystem, dropped capabilities, secret loader, restart policy
and cleanup commands. Rehearsal paths and the Compose project name were separate;
network mode was `none`, published ports were removed, and all credentials were
dummy values. No production identity, bundle, project data or queue was used.

Verified on the real host:

- Two disposable age identities independently decrypted the dummy SOPS bundle.
- systemd materialized secrets on `/run` and started both application processes.
  The version endpoint matched the candidate, liveness returned 200, and
  readiness correctly returned 503 with dependencies unavailable.
- The loader's real `/proc` mount scan preserved plaintext mounted by the running
  container. Stopping the service removed the decrypted dummy bundle.
- Killing the container triggered systemd restart; the fixture project marker
  survived. Restoring the fixture directory from its copy and restarting with
  the encrypted bundle also passed.
- A separate maintenance-gate check prevented startup and plaintext materialization.
  The first attempt at this check hit the configured three-start limit after
  the preceding restart drills; a fresh temporary unit isolated the condition.

Compose returned 130 during an intentional systemd stop, so systemd recorded an
exit-code failure even though the processes stopped and pruning succeeded. An
explicit stop did not restart the service. Diagnose the journal before treating
that status alone as an application crash; repeated starts also consume the
configured start-limit budget. Do not routinely reset that budget to bypass
an unexplained production failure.

All temporary units, containers, dummy keys, fixture data and plaintext were
removed. The candidate image remains cached on the VM. Production maintenance
remained present, CI activation remained absent, and `canary.service` remained
inactive. The registry pull used temporary credentials under `/run`, then removed them.

This was a runtime/secret-lifecycle drill, not a complete migration rehearsal.
It did not prove a healthy disposable queue/database, authenticated user flows,
Nginx/Cloudflare headers and TLS, a real project-volume restore, reboot behavior,
or the release controller's drain/replacement/failure transaction. Those remain
activation gates. The fixture marker restore is not evidence of a production backup.

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


### Production cutover evidence (2026-10-06)

- Drained Fly and verified zero in-flight work, cordoned its machine, stopped
  application writers, and copied the final volume. All 597 files matched by
  SHA-256, size, mode and ownership on Lightsail. The source archive hash is
  `daf70834be6c83dbf4ec7b8b58103e2bd8f0629364289f2805d92f4259da96a4`.
- Encrypted volume and database backups are in the operator's protected
  `~/.config/canary/backups/` directory. Recovery-key decryption verified the
  volume archive; an isolated PostgreSQL restore recovered 32 projects, 52
  queue records and 6 auth users. These are cutover backups, not an automated
  off-AWS backup service.
- Final Fly snapshot `vs_O1g72J0pJ2pIzxl1zoPD1Z7` reached `created`.
  Machine `48e7295a973948` is stopped and cordoned, with autostart disabled.
  Its volume and snapshots remain for recovery and can still incur storage cost.
  Never restart it while Lightsail owns the production queue.
- Lightsail `canary-prod` owns production on static IP `52.203.15.28`.
  Cloudflare's proxied apex A/AAAA records point to this VM; `www` points to
  the apex. The public release verifier passed before admission resumed.
  Supabase, LiteLLM and generation queue readiness all passed; the queue client
  connection uses TLS. No paid generation was submitted for these checks.
- Nginx uses the checked-in `deploy/lightsail/nginx.conf`. Ports 80/443 accept
  only Cloudflare ranges; SSH retains the operator `/32` and Lightsail browser
  access. Cloudflare global authenticated origin pulls are enforced, and origin
  logs show `mtls=SUCCESS`. This authenticates the Cloudflare network, not a
  unique zone certificate. Proxy headers are overwritten at the origin.
- Let's Encrypt covers apex and www, initially expiring 2027-01-04. Certbot
  reconfiguration passed its staging HTTP challenge and saved webroot renewal
  with an Nginx reload hook. A subsequent `renew --dry-run --run-deploy-hooks`
  passed with client-certificate enforcement active. `certbot.timer` and
  `canary.service` are enabled.
  The latter's boot enablement is verified; an actual host reboot is not yet tested.
- An isolated candidate-image PostgreSQL queue drill passed interrupted-work
  recovery, FIFO continuation and duplicate-delivery suppression without providers.
- A project-specific schema error was seen during authenticated browsing. The
  operator identified it as unrelated existing failed-project state and requested
  that it be excluded from this infrastructure migration investigation. Authenticated
  PDF/CBZ exports have not been established by that browser check.
- Daily Lightsail automatic snapshots are enabled at 07:00 UTC. The first
  scheduled snapshot has not yet run. Snapshot storage is billed separately.
- Existing AWS budgets include a $10 gross-cost budget excluding credits/refunds
  and a separate $1 net-spend budget. Alert delivery is not verified. Credits'
  exact date interpretation and Lightsail eligibility remain as documented in
  the migration proposal; a remaining balance alone does not verify eligibility.

Keep the stopped Fly resources through a complete workload and backup cycle.
Before retiring them, finish recurring encrypted off-AWS application-consistent
backups, verify alert delivery, and complete the authenticated export/restore
check with a known-good project. A scheduled VM snapshot alone does not prove
application/database consistency. Do not claim a measured performance improvement
from health checks alone.


### First complete CI release (2026-10-06)

[Workflow sppfgkz3lm](https://depot.dev/orgs/6ntrqswcbt/workflows/sppfgkz3lm),
run `p70jrl2qf9`, passed every test/build gate and its production deploy job.
The host controller pulled and verified the immutable image, drained, replaced
and restarted the owner, verified public readiness/security headers/source SHA,
and resumed admission. Final local checks confirmed `draining=false`,
`safe_to_deploy=true`, all three dependencies `ok`, no maintenance hold, and CI
activation enabled. AWS independently confirmed runner `52.206.49.240/32` was
removed; only the original operator `/32` and browser SSH alias remain.

Deployed source: `bee4fdb1b12f91e83852b6deed48bd8f7ae05efb`.
Build timestamp: `2026-10-06T20:03:49Z`.
Image: `registry.depot.dev/js338b6zll@sha256:26d09ba5e191f73724205c2768a37d21ab346fc575a2c6005b0292b549f450e1`.
The earlier same-source candidate is retained as a rollback image; different
build timestamps produce different immutable images. Local unrelated model
changes were not included in either production build.

This live success proves the normal release transaction, not every injected
failure/disconnect/reboot case listed above. Keep those limitations distinct
from the isolated runtime and queue drills. The environment-scope diagnosis is
supported by run `mcf4dgqxgk` skipping deploy and this run deploying after only
the non-secret flag's environment selector was removed.
