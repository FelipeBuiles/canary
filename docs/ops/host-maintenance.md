# Lightsail host maintenance

**Status: host tooling installed and socket-verified on production, 2026-10-23.
The backoffice activates with the next reviewed application release. Package
installation and reboot/recovery still require an isolated-host rehearsal.**

Backoffice → **Host maintenance** uses the existing operations token. It shows
systemd services, application readiness, Canary's container, uptime, load, Docker-filesystem disk space,
Ubuntu's reboot flag, a dated APT upgrade preview, and the last maintenance
operation. Status refreshes every 15 seconds while the view is open. A preview is
valid for 30 minutes. It describes the configured APT repositories, not a CVE
scan or a security-only upgrade policy. Held or phased packages can remain.

The browser and application cannot report a dead host independently: while
Canary is stopped, the view keeps its last observation and reports lost contact.
Keep the independent [availability monitor](crash-recovery.md#independent-monitoring-and-notification-activation)
for outage notification. This view does not configure alerts or scheduled updates.

## Host packages and image packages

Ubuntu's `/run/reboot-required` indicates a requested host reboot; the adjacent
`.pkgs` file identifies requesting packages when available. Absence of that flag
is not proof that every service is using updated libraries. See
[Ubuntu's automatic-update documentation](https://ubuntu.com/server/docs/how-to/software/automatic-updates/).
The view also reports whether the APT timers are active, without asserting that
unattended security updates are configured correctly. Existing unattended-update
configuration is preserved; an independently scheduled upgrade may run outside
a backoffice maintenance operation.

Updating Ubuntu does not change dependencies inside the immutable Canary image.
Update the Docker base image/application dependencies, rebuild, pass release
checks, and deploy the tested digest through [Lightsail CI](lightsail-ci.md).
Do not install packages into the running application container.

## One-time installation

Use an existing operator SSH session, not the restricted `canary-deploy` account.
Review and copy these repository files to the indicated root-owned paths:

| Source | Destination | Mode |
| --- | --- | --- |
| `deploy/lightsail/host_agent.py` | `/usr/local/lib/canary/host_agent.py` | `0755` |
| `deploy/lightsail/canary-host.service` | `/etc/systemd/system/canary-host.service` | `0644` |
| `deploy/lightsail/canary-host-recover.service` | `/etc/systemd/system/canary-host-recover.service` | `0644` |
| `deploy/lightsail/canary.service` | `/etc/systemd/system/canary.service` | `0644` |
| `deploy/lightsail/compose.yaml` | `/usr/local/lib/canary/compose.yaml` | `0644` |

The existing reviewed `release.py`, `verify_deployment.py`, `canary_secrets.py`,
deployment environment, encrypted bundle and age identity remain prerequisites.
The installed host loader must match `CANARY_LOADER_SHA256`. Host tooling is
reviewed and installed separately; deploying an application image does not
silently replace these files.

Validate before activating:

```sh
sudo systemd-analyze verify /etc/systemd/system/canary-host.service /etc/systemd/system/canary-host-recover.service /etc/systemd/system/canary.service
sudo systemctl daemon-reload
sudo systemctl enable --now canary-host.service
sudo systemctl enable canary-host-recover.service
sudo systemctl status canary-host.service --no-pager
```

Do not start the recovery unit manually during an active operation. It only
recovers a recorded `rebooting` operation on a different Linux boot ID. Enabling
it does not request a reboot. Enabling the host agent does not stop Canary.

The updated Compose file adds a read-only bind of `/run/canary-host`, which must
exist before recreating Canary. The directory survives host-agent restarts;
mount the directory rather than the socket inode. Recreate the application only
through the normal drained release process, with an image containing the new
backoffice API. Existing containers do not acquire a new mount automatically.
After deployment, verify the backoffice status view and **Check for updates**
before scheduling disruptive maintenance.

The socket is root-only, has no TCP listener, and accepts fixed actions, never
shell commands or caller-selected package names. The app gets neither Docker's
socket nor general host filesystem access. Access to the operations token now authorizes
host updates/reboots as well as the existing backoffice functions; treat that
token accordingly. An application compromise can invoke these bounded actions.
Operation records under `/var/lib/canary-host` are root-only and contain request
IDs, phases, package previews and the expected release SHA, never runtime secrets.

## Operator flow

1. **Check for updates** refreshes package indexes with repository failures treated
   as errors and simulates `apt-get --with-new-pkgs --no-remove upgrade`. It does
   not drain generation or install packages.
2. Review the preview, then choose **Review package update → Apply updates**.
   The worker refreshes indexes and checks the preview digest again; if packages
   changed, review the new preview. This updates all eligible configured APT
   packages, permits new dependencies, and refuses removals.
3. The worker shares the release lock, creates the host maintenance hold, drains
   admission, waits for active work, and stops Canary. Package configuration keeps
   existing config files using dpkg's defaults/keep-old policy. `needrestart` runs
   in list mode for this invocation. Docker and Nginx explicitly restart afterward;
   other services may still need a restart. Existing unattended APT jobs use their
   own configuration, not this worker's environment.
4. It starts the same application release, checks its exact SHA and persisted
   drain, then uses the existing public verifier to check readiness, dependencies
   and security headers before resuming generation. A failure leaves a maintenance
   hold and stops Canary once replacement has begun. If draining fails, the
   existing process stays running with admission paused so in-flight work can
   finish. There is no automatic rollback or retry.
5. If needed, choose **Review host reboot → Reboot host** separately. This drains
   and stops Canary, records the release SHA and boot ID, then requests a reboot.
   The enabled recovery unit removes its hold, starts Canary and verifies before
   resuming. An unrelated reboot never triggers automatic generation resume.

Requests launch a transient `canary-host-maintenance` systemd unit, independent
of the HTTP connection. Repeating the last request ID returns its recorded result.
A different request is refused while an operation is active. Closing the browser
or losing an HTTP response is not cancellation; refresh status before acting.
The worker has a 90-minute maximum lifetime; termination may leave its last phase
and hold intact. The tool does not silently retry an uncertain operation.

## Failed or uncertain maintenance

Inspect using operator SSH:

```sh
sudo cat /var/lib/canary-host/operation.json
sudo journalctl -u canary-host-maintenance -u canary-host-recover -u canary-host --no-pager -n 100
sudo systemctl status canary docker nginx --no-pager
sudo test -e /etc/canary/maintenance
sudo dpkg --audit
```

A daemon/transport error can coexist with a running or completed worker. Do not
clear an operation or repeat upgrades while `canary-host-maintenance` is active.
A timeout/SIGKILL may leave `queued`, `updating`, or another active phase even
though the unit exited; inspect systemd and APT/dpkg before resetting state.
Check `/var/log/apt/history.log`, `/var/log/apt/term.log` and the existing release
journal. Repair incomplete dpkg configuration under the existing maintenance hold.
Never delete a hold belonging to another maintenance task.

For a stopped owner, reconcile the failed operation, confirm the installed image,
bundle/loader and recorded expected SHA, then explicitly remove the maintenance
hold and start Canary. Use the existing public verifier with the ops token and
expected SHA supplied securely, and `--resume` only after verification. Follow
[release recovery](lightsail-ci.md#release-transaction); never print decrypted
credentials or copy them into a shell command history. After verifying recovery,
mark the operation failed/complete in the root-only state file (or archive it)
before submitting another action. A failed operation is intentionally not a
browser-controlled override of the maintenance fence.

Provider-free tests establish protocol, authorization and sequencing only.
Rehearse an update, SSH/browser disconnect and reboot/recovery on an isolated host
before production use; Linux systemd, Docker socket permissions, APT behavior,
boot order and real network readiness require that live evidence.

## Production setup evidence (2026-10-23)

The reviewed host agent, systemd units, application unit and Compose file were
installed under the existing release lock after confirming the previous host
files matched source. The host passed `systemd-analyze verify`; the private agent
is active and the reboot recovery unit is enabled. Existing host files are saved
in `/etc/canary/host-setup-backups/1792805363779084461/`.

A real socket status request reported Canary, Docker, Nginx and both APT timers
active, application readiness `ok` with all three dependencies `ok`, and about
54 GiB available on the Docker filesystem. Ubuntu reported a pending reboot for
libc and AWS kernel updates. Setup did not restart Canary, upgrade packages or
request a host reboot. The pending reboot remains an explicit operator action.
