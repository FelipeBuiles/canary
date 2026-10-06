#!/usr/bin/env python3
"""Root-owned, forced-command release controller. No arbitrary remote commands.

Install with its reviewed loader, compose file and verify_deployment.py. CI can
request only a digest-pinned image from the configured repository. Production
credentials never enter CI. Initial migration and offline recovery are manual.
"""
from __future__ import annotations

import fcntl
import hashlib
import importlib.util
import json
import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

BASE = Path("/usr/local/lib/canary")
CONFIG = Path("/etc/canary/deployment.env")
MAINTENANCE = Path("/etc/canary/maintenance")
ENABLED = Path("/etc/canary/ci-enabled")
RUNTIME = Path("/run/canary-release")
REPOSITORY = "registry.depot.dev/js338b6zll"
HEX = re.compile(r"[0-9a-f]{64}")
SYSTEM_ENV = {"PATH": "/usr/local/bin:/usr/bin:/bin", "HOME": "/root"}


def require(condition, code):
    if not condition:
        raise RuntimeError(code)


def validate_request(data):
    require(isinstance(data, dict) and set(data) == {"image", "version", "loader_sha256", "pull_token"}, "invalid_request")
    require(all(isinstance(v, str) for v in data.values()), "invalid_request")
    require(re.fullmatch(re.escape(REPOSITORY) + r"@sha256:[0-9a-f]{64}", data["image"]), "invalid_image")
    require(re.fullmatch(r"[0-9a-f]{40}", data["version"]), "invalid_version")
    require(HEX.fullmatch(data["loader_sha256"]), "invalid_loader_digest")
    require(0 < len(data["pull_token"]) <= 8192 and not any(c.isspace() for c in data["pull_token"]), "invalid_pull_token")
    return data


def private_read(path):
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW), "rb") as stream:
        info = os.fstat(stream.fileno())
        require(info.st_uid == 0 and info.st_mode & 0o077 == 0, "unsafe_permissions")
        return stream.read(65537)


def parse_environment(raw):
    result = {}
    for line in raw.decode().splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        key, sep, value = line.partition("=")
        require(sep and re.fullmatch(r"[A-Z][A-Z0-9_]*", key) and key not in result, "invalid_environment")
        parts = shlex.split(value)
        require(len(parts) <= 1, "invalid_environment")
        result[key] = parts[0] if parts else ""
    return result


def atomic_write(path, value):
    fd, temporary = tempfile.mkstemp(prefix=".release-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(value)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def run(argv, *, data=None, env=None, timeout=600):
    # Keep command output out of the journal, including possible credential echoes.
    return subprocess.run(argv, input=data, env=env or SYSTEM_ENV, capture_output=True,
                          check=True, timeout=timeout).stdout


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def api(path, config, token=None, method="GET"):
    headers = {"Host": config["CANARY_HEALTH_HOST"]}
    if token:
        headers["X-Canary-Ops-Token"] = token
    request = urllib.request.Request("http://127.0.0.1:8000" + path, headers=headers, method=method)
    with urllib.request.urlopen(request, timeout=15) as response:
        return json.load(response)


def drain(config, token):
    api("/api/ops/drain", config, token, "POST")
    deadline = time.monotonic() + 1800
    while True:
        status = api("/api/ops/deployment-status", config, token)
        if status.get("draining") is True and status.get("safe_to_deploy") is True:
            return
        require(time.monotonic() < deadline, "drain_timeout")
        time.sleep(5)


def wait_candidate(config, token, version):
    deadline = time.monotonic() + 180
    while True:
        try:
            identity = api("/api/version", config)
            ready = api("/api/health/ready", config)
            status = api("/api/ops/deployment-status", config, token)
            if identity.get("git_sha") == version and ready.get("status") == "ok":
                require(status.get("draining") is True, "candidate_not_drained")
                return
        except (OSError, ValueError):
            pass
        require(time.monotonic() < deadline, "candidate_readiness_timeout")
        time.sleep(3)


def activate(request):
    require(ENABLED.is_file() and not MAINTENANCE.exists(), "ci_not_activated")
    run(["systemctl", "is-active", "--quiet", "canary.service"])
    old = private_read(CONFIG)
    config = parse_environment(old)
    require(config.get("SCENEWRIGHT_APP_URL") == "https://scenewright.ink", "invalid_public_origin")
    loader_path = BASE / "canary_secrets.py"
    digest = hashlib.sha256(loader_path.read_bytes()).hexdigest()
    require(digest == request["loader_sha256"] == config.get("CANARY_LOADER_SHA256"), "host_loader_update_required")
    require(HEX.fullmatch(config.get("CANARY_BUNDLE_SHA256", "")), "invalid_bundle_digest")
    loader = load_module("canary_secrets", loader_path)
    loader.require_tmpfs(RUNTIME)
    loader.require_no_swap(False)
    require(shutil.disk_usage("/var/lib/docker").free >= 8 * 1024 ** 3, "insufficient_image_disk_space")
    bundle = loader.decrypt(Path(config["CANARY_BUNDLE_PATH"]), Path("/etc/canary/keys/age.txt"), config["CANARY_BUNDLE_SHA256"])
    token = bundle["env"]["CANARY_OPS_TOKEN"]
    candidate = {**config, "CANARY_IMAGE": request["image"]}
    with tempfile.TemporaryDirectory(prefix="registry-", dir=RUNTIME) as folder:
        env = {**SYSTEM_ENV, "DOCKER_CONFIG": folder}
        run(["docker", "login", "registry.depot.dev", "--username", "x-token", "--password-stdin"],
            data=request["pull_token"].encode(), env=env)
        run(["docker", "pull", request["image"]], env=env)
    # Confirm image provenance and loader BEFORE disrupting the active release.
    inspected = json.loads(run(["docker", "image", "inspect", request["image"]]))[0]
    image_env = dict(v.split("=", 1) for v in inspected["Config"].get("Env", []) if "=" in v)
    require(image_env.get("CANARY_VERSION") == request["version"], "image_version_mismatch")
    image_hash = run(["docker", "run", "--rm", "--network", "none", "--read-only", "--cap-drop", "ALL",
                      "--security-opt", "no-new-privileges:true", "--entrypoint", "sha256sum",
                      request["image"], "/app/canary_secrets.py"]).decode().split()[0]
    require(image_hash == digest, "image_loader_mismatch")
    run(["docker", "compose", "--env-file", "/dev/null", "--project-name", "canary", "--file",
         str(BASE / "compose.yaml"), "config", "--quiet"], env={**SYSTEM_ENV, **candidate})
    require(not MAINTENANCE.exists(), "maintenance_hold")
    drain(config, token)
    # Preserve the full previous image/bundle/loader/config combination.
    history = CONFIG.parent / "releases"
    history.mkdir(mode=0o700, exist_ok=True)
    backup = history / (str(time.time_ns()) + ".env")
    with backup.open("xb") as stream:
        stream.write(old)
    replacement_started = False
    try:
        require(not MAINTENANCE.exists(), "maintenance_hold")
        replacement_started = True  # Ambiguous stop failure must also fail closed.
        run(["systemctl", "stop", "canary.service"], timeout=90)
        updated = "\n".join(f"{key}={json.dumps(value)}" for key, value in candidate.items()) + "\n"
        atomic_write(CONFIG, updated.encode())
        run(["systemctl", "reset-failed", "canary.service"])
        run(["systemctl", "start", "canary.service"])
        wait_candidate(candidate, token, request["version"])
        # The reviewed host verifier checks SHA, dependencies, headers, then resumes.
        run(["python3", str(BASE / "verify_deployment.py"), "--resume"], env={**SYSTEM_ENV,
             "CANARY_OPS_TOKEN": token, "EXPECTED_CANARY_VERSION": request["version"],
             "SCENEWRIGHT_APP_URL": candidate["SCENEWRIGHT_APP_URL"]}, timeout=120)
        require(api("/api/ops/deployment-status", candidate, token).get("draining") is False, "resume_failed")
        print("release_verified_and_resumed", flush=True)
    except BaseException:
        if replacement_started:
            MAINTENANCE.touch(mode=0o600)
            run(["systemctl", "stop", "canary.service"], timeout=90)
        raise


def worker(path):
    require(path.parent == RUNTIME and path.name.startswith("request-"), "invalid_request_path")
    request = validate_request(json.loads(private_read(path)))
    path.unlink()  # The pull token remains only in worker memory.
    with (RUNTIME / "worker.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        activate(request)


def dispatch():
    require(not os.environ.get("SSH_ORIGINAL_COMMAND"), "remote_commands_forbidden")
    require(ENABLED.is_file() and not MAINTENANCE.exists(), "ci_not_activated")
    request = validate_request(json.loads(sys.stdin.buffer.read(16385)))
    RUNTIME.mkdir(mode=0o700, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix="request-", dir=RUNTIME)
    path = Path(name)
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(request, stream)
        # No --pipe: the worker logs to journald and survives SSH/runner loss.
        run(["systemd-run", "--unit=canary-release", "--collect", "--wait",
             "--property=RuntimeMaxSec=2400", "--property=TimeoutStopSec=120",
             "--property=UMask=0077", "--property=LimitCORE=0",
             "/usr/bin/python3", str(BASE / "release.py"), "--worker", str(path)], timeout=2600)
        print("release_verified_and_resumed", flush=True)
    finally:
        path.unlink(missing_ok=True)


def interrupted(*_):
    raise InterruptedError("release_interrupted")


if __name__ == "__main__":
    os.umask(0o077)
    signal.signal(signal.SIGTERM, interrupted)
    try:
        require(os.geteuid() == 0, "root_required")
        if len(sys.argv) == 3 and sys.argv[1] == "--worker":
            worker(Path(sys.argv[2]))
        else:
            require(len(sys.argv) == 1, "invalid_arguments")
            dispatch()
    except BaseException:  # noqa: BLE001 — redact credential-bearing boundary errors.
        print("release_failed_admission_not_automatically_resumed", file=sys.stderr)
        raise SystemExit(1) from None
