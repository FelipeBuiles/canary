from __future__ import annotations

import fcntl
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]


def _write_executable(path: Path, contents: str) -> None:
    path.write_text(contents)
    path.chmod(0o755)


def _gateway_environment(tmp_path: Path, env: dict, *, stale=False) -> dict:
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    from gateway_state import BUILD_LABEL, SCHEMA_VERSION, build_fingerprint, runtime_files
    import yaml
    directory = tmp_path / "gateway-fixtures"
    directory.mkdir()
    build = build_fingerprint(REPO_ROOT)
    files = runtime_files(REPO_ROOT)
    models = [route["model_name"] for route in yaml.safe_load((REPO_ROOT / "litellm/config.yaml").read_text())["model_list"]]
    fixture = {
        "inspect": [{"Id": "litellm-id", "Image": "image-current", "State": {"Running": True},
                     "Config": {"Env": [], "Labels": {
                         "com.docker.compose.project.working_dir": str(REPO_ROOT),
                         "com.docker.compose.config-hash": "fixture-hash"}}, "Mounts": []}],
        "image": [{"Id": "image-current", "Config": {"Labels": {BUILD_LABEL: build}}}],
        "service": {"services": {"litellm": {"image": "fixture-image", "volumes": []}}},
        "live": {"state": {"schema_version": SCHEMA_VERSION, "build_sha256": build,
                           "runtime_files": files}, "models": models},
    }
    (directory / "live-current.json").write_text(json.dumps(fixture["live"]))
    if stale:
        fixture["live"]["state"]["runtime_files"] = {**files, "litellm/config.yaml": "old"}
        fixture["live"]["models"] = [model for model in models if model != "image-nano-banana-2.1"]
    for name, value in fixture.items():
        (directory / f"{name}.json").write_text(json.dumps(value))
    env["DEV_TEST_GATEWAY_FIXTURES"] = str(directory)
    for variable, filename in (("DEV_TEST_DOCKER_LOG", "docker-invocations"),
                               ("DEV_TEST_START_LOG", "start-invocations")):
        if variable not in env:
            path = tmp_path / filename
            path.write_text("")
            env[variable] = str(path)
    return env


def _write_docker_stub(bin_dir: Path) -> None:
    _write_executable(bin_dir / "docker", """#!/bin/sh
printf '%s\n' "$*" >> "$DEV_TEST_DOCKER_LOG"
case "$1" in
  info) exit 0 ;;
  ps) printf '%s\n' litellm-id ;;
  compose)
    case "$*" in
      *"ps -q queue-db") printf queue-db-id ;;
      *"ps -q litellm-db") printf '%s\n' litellm-db-id ;;
      *"ps -q litellm") printf '%s\n' litellm-id ;;
      *"config --format json") cat "$DEV_TEST_GATEWAY_FIXTURES/service.json" ;;
      *"config --hash litellm") printf '%s\n' 'litellm fixture-hash' ;;
      *"up -d --no-deps --force-recreate litellm")
        cp "$DEV_TEST_GATEWAY_FIXTURES/live-current.json" "$DEV_TEST_GATEWAY_FIXTURES/live.json" ;;
      *) exit 1 ;;
    esac ;;
  inspect)
    if [ "$2" = --format ]; then
      case "$*" in
        *queue-db-id|*litellm-db-id) printf healthy ;;
        *litellm-id) printf running ;;
        *) exit 1 ;;
      esac
    else
      cat "$DEV_TEST_GATEWAY_FIXTURES/inspect.json"
    fi ;;
  image) cat "$DEV_TEST_GATEWAY_FIXTURES/image.json" ;;
  exec) cat "$DEV_TEST_GATEWAY_FIXTURES/live.json" ;;
  *) exit 1 ;;
esac
""")


def test_live_start_waits_for_litellm_http_readiness(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    curl_attempts = tmp_path / "litellm-curl-attempts"

    _write_docker_stub(bin_dir)
    _write_executable(
        bin_dir / "curl",
        """#!/bin/sh
for arg do
  url="$arg"
done

case "$url" in
  http://127.0.0.1:4000/health/liveliness)
    attempts=0
    if [ -f "$DEV_TEST_CURL_ATTEMPTS" ]; then
      attempts="$(sed -n '1p' "$DEV_TEST_CURL_ATTEMPTS")"
    fi
    attempts=$((attempts + 1))
    printf '%s\n' "$attempts" > "$DEV_TEST_CURL_ATTEMPTS"
    [ "$attempts" -ge 2 ]
    ;;
  http://127.0.0.1:8000/api/health/ready)
    printf '%s' '{"checks":{"litellm":"ok","generation_queue":"ok"},"model_mode":"api","pipeline_contract":"eight-stage-v2"}'
    ;;
  http://127.0.0.1:5173)
    exit 0
    ;;
  *)
    exit 1
    ;;
esac
""",
    )
    _write_executable(bin_dir / "sleep", "#!/bin/sh\nexit 0\n")

    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"
    env["DEV_TEST_CURL_ATTEMPTS"] = str(curl_attempts)
    _gateway_environment(tmp_path, env)
    result = subprocess.run(
        ["bash", str(REPO_ROOT / "scripts" / "dev.sh"), "--api"],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert curl_attempts.read_text().strip() == "2"
    assert "LiteLLM (http://127.0.0.1:4000/health/liveliness)" in result.stdout
    assert "[dev] ready: http://127.0.0.1:5173" in result.stdout


def _write_check_stubs(bin_dir: Path) -> None:
    _write_docker_stub(bin_dir)
    _write_executable(
        bin_dir / "curl",
        """#!/bin/sh
for arg do
  url="$arg"
done

case "$url" in
  http://127.0.0.1:4000/health/liveliness)
    exit 0
    ;;
  http://127.0.0.1:8000/api/health/ready)
    printf '%s' "$DEV_TEST_BACKEND_PAYLOAD"
    ;;
  http://127.0.0.1:5173)
    exit 0
    ;;
  *)
    exit 1
    ;;
esac
""",
    )
    _write_executable(bin_dir / "sleep", "#!/bin/sh\nexit 0\n")
    for command in ("uv", "npm"):
        _write_executable(
            bin_dir / command,
            """#!/bin/sh
printf '%s\\n' "$*" >> "$DEV_TEST_START_LOG"
exit 1
""",
        )


def _run_dev(
    tmp_path: Path, backend_payload: str, *, check_only: bool = True, default_mode: bool = False,
    stale_gateway: bool = False, refresh_gateway: bool = False,
) -> tuple[subprocess.CompletedProcess[str], str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_check_stubs(bin_dir)
    docker_log = tmp_path / "docker-invocations"
    docker_log.write_text("")
    start_log = tmp_path / "start-invocations"
    start_log.write_text("")

    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"
    env["DEV_TEST_BACKEND_PAYLOAD"] = backend_payload
    env["DEV_TEST_DOCKER_LOG"] = str(docker_log)
    env["DEV_TEST_START_LOG"] = str(start_log)
    _gateway_environment(tmp_path, env, stale=stale_gateway)
    command = ["bash", str(REPO_ROOT / "scripts" / "dev.sh")]
    if not default_mode:
        command.append("--api")
    if check_only:
        command.append("--check")
    if refresh_gateway:
        command.append("--refresh-gateway")
    result = subprocess.run(
        command,
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert start_log.read_text() == "", result.stdout + result.stderr
    return result, docker_log.read_text()


def test_check_rejects_backend_missing_pipeline_contract(tmp_path: Path) -> None:
    result, docker_log = _run_dev(
        tmp_path, '{"checks":{"litellm":"ok","generation_queue":"ok"},"model_mode":"api"}'
    )

    assert result.returncode == 1, result.stdout + result.stderr
    assert "incompatible" in result.stdout + result.stderr
    assert "up -d" not in docker_log


def test_check_accepts_compatible_api_backend_without_starting_services(
    tmp_path: Path,
) -> None:
    payload = (
        '{"checks":{"litellm":"ok","generation_queue":"ok"},"model_mode":"api",'
        '"pipeline_contract":"eight-stage-v2"}'
    )
    result, docker_log = _run_dev(tmp_path, payload)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "up -d" not in docker_log


def test_check_rejects_backend_with_old_pipeline_contract(tmp_path: Path) -> None:
    payload = (
        '{"checks":{"litellm":"ok","generation_queue":"ok"},"model_mode":"api",'
        '"pipeline_contract":"seven-stage-v1"}'
    )
    result, docker_log = _run_dev(tmp_path, payload)

    assert result.returncode == 1, result.stdout + result.stderr
    assert "incompatible" in result.stdout + result.stderr
    assert "up -d" not in docker_log


def test_api_start_rejects_backend_with_mismatched_mode_without_starting_services(
    tmp_path: Path,
) -> None:
    payload = (
        '{"checks":{"litellm":"ok","generation_queue":"ok"},"model_mode":"codex",'
        '"pipeline_contract":"eight-stage-v2"}'
    )
    result, docker_log = _run_dev(tmp_path, payload, check_only=False)

    assert result.returncode == 1, result.stdout + result.stderr
    assert "incompatible" in result.stdout + result.stderr
    assert "up -d" not in docker_log


def test_default_launcher_mode_uses_api_without_starting_services(tmp_path: Path) -> None:
    payload = (
        '{"checks":{"litellm":"ok","generation_queue":"ok"},"model_mode":"api",'
        '"pipeline_contract":"eight-stage-v2"}'
    )
    result, docker_log = _run_dev(tmp_path, payload, default_mode=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "up -d" not in docker_log


@pytest.mark.parametrize("check_only", [False, True])
def test_launcher_rejects_stale_gateway_without_restarting_it(tmp_path, check_only):
    payload = '{"checks":{"litellm":"ok","generation_queue":"ok"},"model_mode":"api","pipeline_contract":"eight-stage-v2"}'
    result, docker_log = _run_dev(tmp_path, payload, check_only=check_only, stale_gateway=True)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "Model routes missing" in result.stdout
    assert "./scripts/gateway.sh" in result.stdout
    assert "up -d" not in docker_log
    assert " build " not in docker_log


def test_explicit_launcher_refresh_recreates_only_stale_gateway(tmp_path):
    payload = '{"checks":{"litellm":"ok","generation_queue":"ok"},"model_mode":"api","pipeline_contract":"eight-stage-v2"}'
    result, docker_log = _run_dev(tmp_path, payload, check_only=False, stale_gateway=True, refresh_gateway=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "startup fingerprints and all configured model routes verified" in result.stdout
    assert "up -d --no-deps --force-recreate litellm" in docker_log
    assert " build " not in docker_log
    assert " down" not in docker_log


@pytest.mark.parametrize("option", ["--check", "--no-docker", "--mock"])
def test_refresh_flag_rejects_read_only_and_mock_combinations(option):
    result = subprocess.run(["bash", str(REPO_ROOT / "scripts/dev.sh"), "--refresh-gateway", option],
                            capture_output=True, text=True, timeout=5)
    assert result.returncode == 2
    assert "cannot be combined" in result.stderr


def test_second_interrupt_releases_lock_held_by_server_descendant(tmp_path: Path) -> None:
    """The first interrupt drains; the second must kill an inherited lock owner."""
    worker = tmp_path / "worker.py"
    worker.write_text(
        """import fcntl
import os
import signal
import sys
import time
from pathlib import Path

lock = Path(sys.argv[1]).open("a+b")
fcntl.flock(lock, fcntl.LOCK_EX)
if os.fork() == 0:
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    Path(sys.argv[2]).write_text(str(os.getpid()))
    while True:
        time.sleep(0.1)
while True:
    time.sleep(0.1)
"""
    )
    lock_path = tmp_path / "owner.lock"
    ready_path = tmp_path / "child-ready"
    service_pid_path = tmp_path / "service-pid"
    env = os.environ.copy()
    env.update(
        DEV_LIFECYCLE=str(REPO_ROOT / "scripts" / "dev_lifecycle.sh"),
        DEV_PYTHON=sys.executable,
        DEV_WORKER=str(worker),
        DEV_LOCK=str(lock_path),
        DEV_READY=str(ready_path),
        DEV_PIDFILE=str(service_pid_path),
    )
    launcher = subprocess.Popen(
        ["bash", "-c", """set -euo pipefail
CHILD_PIDS=()
source "$DEV_LIFECYCLE"
"$DEV_PYTHON" -c "$DEV_SERVICE_EXEC" "$DEV_PYTHON" "$DEV_WORKER" "$DEV_LOCK" "$DEV_READY" &
CHILD_PIDS+=("$!")
printf '%s' "$!" > "$DEV_PIDFILE"
wait "${CHILD_PIDS[@]}" || true
if [ "$SHUTDOWN_REQUESTED" = true ]; then
  wait_for_owned_services
  exit 130
fi
"""],
        cwd=REPO_ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    try:
        deadline = time.monotonic() + 5
        while not ready_path.exists():
            assert launcher.poll() is None, "launcher exited before its worker acquired the lock"
            assert time.monotonic() < deadline, "worker did not become ready"
            time.sleep(0.02)
        launcher.send_signal(signal.SIGINT)
        time.sleep(0.2)
        assert launcher.poll() is None
        with lock_path.open("a+b") as probe:
            with pytest.raises(BlockingIOError):
                fcntl.flock(probe, fcntl.LOCK_EX | fcntl.LOCK_NB)
        launcher.send_signal(signal.SIGINT)
        output, _ = launcher.communicate(timeout=5)
        assert launcher.returncode == 130, output
        assert "waiting for running jobs" in output
        assert "forcing services" in output
        with lock_path.open("a+b") as probe:
            fcntl.flock(probe, fcntl.LOCK_EX | fcntl.LOCK_NB)
    finally:
        if service_pid_path.exists():
            try:
                os.killpg(int(service_pid_path.read_text()), signal.SIGKILL)
            except ProcessLookupError:
                pass
        if launcher.poll() is None:
            launcher.kill()
            launcher.communicate(timeout=5)
