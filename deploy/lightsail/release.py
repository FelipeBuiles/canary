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
from contextlib import contextmanager
from pathlib import Path

BASE = Path("/usr/local/lib/canary")
CONFIG = Path("/etc/canary/deployment.env")
MAINTENANCE = Path("/etc/canary/maintenance")
ENABLED = Path("/etc/canary/ci-enabled")
RUNTIME = Path("/run/canary-release")
CONFIG_STATE = Path('/var/lib/canary-config')
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


def serialize_environment(config):
    """Literal common subset of shlex and systemd EnvironmentFile syntax."""
    lines = []
    for key, value in config.items():
        require(re.fullmatch(r'[A-Z][A-Z0-9_]*', key), 'invalid_environment')
        require(isinstance(value, str) and all(32 <= ord(c) <= 126 and c not in '\\"$`' for c in value),
                'unsupported_environment_value')
        lines.append(f'{key}="{value}"')
    encoded = ('\n'.join(lines) + '\n').encode()
    require(len(encoded) <= 65536, 'invalid_environment')
    return encoded


def configuration_conflict():
    """Only an inode-matched hold belongs to a configuration operation."""
    try:
        record = json.loads(private_read(CONFIG_STATE / 'hold.json'))
        info = MAINTENANCE.stat(follow_symlinks=False)
        if (record['device'], record['inode']) == (info.st_dev, info.st_ino):
            identifier = record['operation_id']
            require(re.fullmatch(r'[0-9a-f-]{36}', identifier), 'invalid_request')
            error = RuntimeError('configuration_operation_active')
            error.operation_id = identifier
            raise error
    except (FileNotFoundError, KeyError, ValueError):
        pass


def atomic_write(path, value):
    fd, temporary = tempfile.mkstemp(prefix=".release-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(value)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        Path(temporary).unlink(missing_ok=True)


@contextmanager
def configuration_publication():
    """Coordinate short snapshot/publication windows without taking the release lock."""
    if not CONFIG_STATE.exists():
        yield
        return
    with (CONFIG_STATE / 'control.lock').open('a') as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        yield


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


def drain(config, token, progress=None):
    api("/api/ops/drain", config, token, "POST")
    deadline = time.monotonic() + 1800
    while True:
        status = api("/api/ops/deployment-status", config, token)
        if progress:
            progress(status, deadline)
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


def candidate_identity(timeout=10):
    deadline = time.monotonic() + timeout
    ids = run(['docker', 'ps', '--no-trunc', '--filter', 'label=com.docker.compose.project=canary',
               '--filter', 'label=com.docker.compose.service=canary', '--format', '{{.ID}}'], timeout=min(5, timeout)).decode().split()
    require(len(ids) == 1, 'candidate_identity_unknown')
    unit = dict(line.split('=', 1) for line in run([
        'systemctl', 'show', 'canary.service', '--property=InvocationID,NRestarts,ActiveState,Result'],
        timeout=max(0.01, min(5, deadline - time.monotonic()))).decode().splitlines() if '=' in line)
    require(unit.get('ActiveState') == 'active' and unit.get('InvocationID') and unit.get('NRestarts', '').isdigit(),
            'candidate_identity_unknown')
    return {'container_id': ids[0], 'invocation': unit['InvocationID'], 'restarts': unit['NRestarts']}


def pin_candidate():
    # Type=simple systemd startup returns before Compose creates the container.
    deadline = time.monotonic() + 30
    while True:
        try:
            return candidate_identity()
        except (RuntimeError, subprocess.SubprocessError):
            require(time.monotonic() < deadline, 'candidate_identity_unknown')
            time.sleep(1)


def verify_public(config, token, version):
    try:
        raw = run(['python3', str(BASE / 'verify_deployment.py'), '--drained'], env={**SYSTEM_ENV,
            'CANARY_OPS_TOKEN': token, 'EXPECTED_CANARY_VERSION': version,
            'SCENEWRIGHT_APP_URL': config['SCENEWRIGHT_APP_URL']}, timeout=120)
    except subprocess.SubprocessError:
        raise RuntimeError('public_verification_failed') from None
    # Publish only known check outcomes, never arbitrary verifier payloads/errors.
    evidence = json.loads(raw)
    require(evidence.get('status') == 'passed', 'public_verification_failed')
    return {'version': True, 'readiness': True, 'security_headers': True, 'admission_drained': True}


def start_candidate():
    try:
        run(['systemctl', 'start', 'canary.service'], timeout=90)
    except subprocess.SubprocessError:
        result = run(['systemctl', 'show', 'canary.service', '--property=Result', '--value'], timeout=5)
        require(result.strip() != b'start-limit-hit', 'start_limit_hit')
        raise


def activate(request):
    configuration_conflict()
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
    updated = serialize_environment(candidate)  # Reject before disrupting a healthy owner.
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
    resume_attempted = False
    try:
        require(not MAINTENANCE.exists(), "maintenance_hold")
        replacement_started = True  # Ambiguous stop failure must also fail closed.
        run(["systemctl", "stop", "canary.service"], timeout=90)
        with configuration_publication():
            atomic_write(CONFIG, updated)
        start_candidate()
        pinned = pin_candidate()
        wait_candidate(candidate, token, request["version"])
        require(candidate_identity() == pinned, 'candidate_restarted')
        verify_public(candidate, token, request['version'])
        require(candidate_identity() == pinned, 'candidate_restarted')
        resume_attempted = True
        api('/api/ops/resume', candidate, token, 'POST')
        require(api("/api/ops/deployment-status", candidate, token).get("draining") is False, "resume_failed")
        print("release_verified_and_resumed", flush=True)
    except BaseException:
        if replacement_started and not resume_attempted:
            MAINTENANCE.touch(mode=0o600)
            run(["systemctl", "stop", "canary.service"], timeout=90)
        raise


def worker(path):
    require(path.parent == RUNTIME and path.name.startswith("request-"), "invalid_request_path")
    request = validate_request(json.loads(private_read(path)))
    path.unlink()  # The pull token remains only in worker memory.
    with (RUNTIME / "worker.lock").open("a") as lock:
        configuration_conflict()
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            configuration_conflict()
            raise
        activate(request)


def dispatch():
    require(not os.environ.get("SSH_ORIGINAL_COMMAND"), "remote_commands_forbidden")
    configuration_conflict()
    require(ENABLED.is_file() and not MAINTENANCE.exists(), "ci_not_activated")
    request = validate_request(json.loads(sys.stdin.buffer.read(16385)))
    RUNTIME.mkdir(mode=0o700, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix="request-", dir=RUNTIME)
    path = Path(name)
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(request, stream)
        # No --pipe: the worker logs to journald and survives SSH/runner loss.
        try:
            run(["systemd-run", "--unit=canary-release", "--collect", "--wait",
                 "--property=RuntimeMaxSec=2400", "--property=TimeoutStopSec=120",
                 "--property=UMask=0077", "--property=LimitCORE=0",
                 "/usr/bin/python3", str(BASE / "release.py"), "--worker", str(path)], timeout=2600)
        except subprocess.SubprocessError:
            configuration_conflict()
            raise
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
    except BaseException as error:  # noqa: BLE001 — redact credential-bearing boundary errors.
        if isinstance(error, RuntimeError) and str(error) == 'configuration_operation_active':
            print('configuration_operation_active ' + error.operation_id, file=sys.stderr)
        else:
            print("release_failed_admission_not_automatically_resumed", file=sys.stderr)
        raise SystemExit(1) from None
