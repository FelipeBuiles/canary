#!/usr/bin/env python3
"""CI transport only: temporary SSH ingress, pinned host, bounded release request."""
from __future__ import annotations

import argparse
import ipaddress
import json
import os
import signal
import subprocess
import tempfile
import urllib.request
from pathlib import Path


def command(argv, **kwargs):
    return subprocess.run(argv, check=True, capture_output=True, timeout=2700, **kwargs)


def deploy(env, run=command, discover_ip=None, *, check_access=False):
    required = ("LIGHTSAIL_HOST", "LIGHTSAIL_SSH_KNOWN_HOSTS", "LIGHTSAIL_SSH_PRIVATE_KEY",
                )
    if not check_access:
        required += ("CANARY_RELEASE_IMAGE", "CANARY_RELEASE_VERSION", "CANARY_LOADER_SHA256")
    if any(not env.get(key, "").strip() for key in required):
        raise ValueError("missing_ci_configuration")
    host = str(ipaddress.IPv4Address(env["LIGHTSAIL_HOST"]))
    if discover_ip is None:
        def discover_ip():
            with urllib.request.urlopen("https://checkip.amazonaws.com", timeout=10) as response:
                return response.read(100).decode().strip()
    runner_ip = ipaddress.IPv4Address(discover_ip())
    if not runner_ip.is_global:
        raise ValueError("runner_ip_not_public")
    # Never replace the firewall or touch the operator/browser SSH rules.
    ports = json.dumps({"fromPort": 22, "toPort": 22, "protocol": "tcp", "cidrs": [f"{runner_ip}/32"]})
    aws = ["aws", "lightsail"]
    suffix = ["--region", "us-east-1", "--instance-name", "canary-prod", "--port-info", ports]
    # Do not remove a pre-existing operator rule if a self-hosted runner shares it.
    existing = json.loads(run(aws + ["get-instance-port-states", "--region", "us-east-1",
                                    "--instance-name", "canary-prod"]).stdout)
    already_allowed = any(p.get("fromPort") == 22 and p.get("toPort") == 22
                          and p.get("protocol") == "tcp" and f"{runner_ip}/32" in p.get("cidrs", [])
                          for p in existing.get("portStates", []))
    attempted_open = False
    with tempfile.TemporaryDirectory(prefix="canary-ci-ssh-") as folder:
        key, known = Path(folder) / "key", Path(folder) / "known_hosts"
        key.write_text(env["LIGHTSAIL_SSH_PRIVATE_KEY"].rstrip() + "\n")
        key.chmod(0o600)
        known.write_text(env["LIGHTSAIL_SSH_KNOWN_HOSTS"].rstrip() + "\n")
        known.chmod(0o600)
        try:
            if not already_allowed:
                print(f"Temporary SSH ingress: {runner_ip}/32 on canary-prod", flush=True)
                attempted_open = True  # Also clean up after an ambiguous API response.
                run(aws + ["open-instance-public-ports"] + suffix)
            request = {}  # Always invalid as a release, even if the host is activated.
            if not check_access:
                token = run(["depot", "pull-token", "--project", "js338b6zll"]).stdout.decode().strip()
                request = {"image": env["CANARY_RELEASE_IMAGE"], "version": env["CANARY_RELEASE_VERSION"],
                           "loader_sha256": env["CANARY_LOADER_SHA256"], "pull_token": token}
            try:
                result = run(["ssh", "-T", "-i", str(key), "-o", "IdentitiesOnly=yes", "-o", "BatchMode=yes",
                              "-o", "StrictHostKeyChecking=yes", "-o", f"UserKnownHostsFile={known}",
                              "-o", "ConnectTimeout=20", "-o", "ServerAliveInterval=15",
                              "-o", "ServerAliveCountMax=4", f"canary-deploy@{host}"],
                             input=json.dumps(request).encode())
            except subprocess.CalledProcessError as error:
                if (not check_access or error.returncode != 1 or error.stdout
                        or error.stderr.strip() != b"release_failed_admission_not_automatically_resumed"):
                    raise
                print("Pinned SSH reached the restricted release controller; invalid request rejected.")
            else:
                if check_access:
                    raise ValueError("probe_unexpectedly_accepted")
                # Host output is intentionally a fixed result, never a command transcript.
                if result.stdout.strip() != b"release_verified_and_resumed":
                    raise ValueError("unexpected_release_result")
                print("Lightsail release verified and resumed.")
        finally:
            if attempted_open:
                run(aws + ["close-instance-public-ports"] + suffix)
                if check_access:
                    remaining = json.loads(run(aws + ["get-instance-port-states", "--region", "us-east-1",
                                                     "--instance-name", "canary-prod"]).stdout)
                    if any(f"{runner_ip}/32" in p.get("cidrs", [])
                           and p.get("fromPort", 0) <= 22 <= p.get("toPort", 0)
                           for p in remaining.get("portStates", [])):
                        raise ValueError("temporary_ssh_rule_still_present")
                    print("Temporary SSH rule removed and absence verified.")


def interrupted(*_):
    raise InterruptedError("ci_interrupted")


if __name__ == "__main__":
    os.umask(0o077)
    signal.signal(signal.SIGTERM, interrupted)
    try:
        parser = argparse.ArgumentParser()
        parser.add_argument("--check-access", action="store_true")
        args = parser.parse_args()
        deploy(os.environ, check_access=args.check_access)
    except Exception:  # noqa: BLE001 — credential-bearing subprocess boundary.
        # subprocess errors may embed the stdin registry token; never print them.
        print("Lightsail deployment failed. Inspect the host release journal; do not assume rollback or resume.")
        raise SystemExit(1) from None
