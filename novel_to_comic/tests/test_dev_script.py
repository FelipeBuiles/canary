from __future__ import annotations

import os
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def _write_executable(path: Path, contents: str) -> None:
    path.write_text(contents)
    path.chmod(0o755)


def test_live_start_waits_for_litellm_http_readiness(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    curl_attempts = tmp_path / "litellm-curl-attempts"

    _write_executable(
        bin_dir / "docker",
        """#!/bin/sh
case "$1" in
  info)
    exit 0
    ;;
  compose)
    case "$*" in
      *"ps -q litellm-db") printf '%s\n' 'litellm-db-id' ;;
      *"ps -q litellm") printf '%s\n' 'litellm-id' ;;
      *) exit 1 ;;
    esac
    ;;
  inspect)
    case "$*" in
      *litellm-db-id) printf '%s\n' 'healthy' ;;
      *litellm-id) printf '%s\n' 'running' ;;
      *) exit 1 ;;
    esac
    ;;
  *)
    exit 1
    ;;
esac
""",
    )
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
    printf '%s' '{"checks":{"litellm":"ok"},"model_mode":"api","pipeline_contract":"eight-stage-v2"}'
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
    _write_executable(
        bin_dir / "docker",
        """#!/bin/sh
printf '%s\\n' "$*" >> "$DEV_TEST_DOCKER_LOG"
case "$1" in
  info)
    exit 0
    ;;
  compose)
    case "$*" in
      *"ps -q litellm-db") printf '%s\\n' 'litellm-db-id' ;;
      *"ps -q litellm") printf '%s\\n' 'litellm-id' ;;
      *) exit 1 ;;
    esac
    ;;
  inspect)
    case "$*" in
      *litellm-db-id) printf '%s\\n' 'healthy' ;;
      *litellm-id) printf '%s\\n' 'running' ;;
      *) exit 1 ;;
    esac
    ;;
  *)
    exit 1
    ;;
esac
""",
    )
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
    tmp_path: Path, backend_payload: str, *, check_only: bool = True, default_mode: bool = False
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
    command = ["bash", str(REPO_ROOT / "scripts" / "dev.sh")]
    if not default_mode:
        command.append("--api")
    if check_only:
        command.append("--check")
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
        tmp_path, '{"checks":{"litellm":"ok"},"model_mode":"api"}'
    )

    assert result.returncode == 1, result.stdout + result.stderr
    assert "incompatible" in result.stdout + result.stderr
    assert "up -d" not in docker_log


def test_check_accepts_compatible_api_backend_without_starting_services(
    tmp_path: Path,
) -> None:
    payload = (
        '{"checks":{"litellm":"ok"},"model_mode":"api",'
        '"pipeline_contract":"eight-stage-v2"}'
    )
    result, docker_log = _run_dev(tmp_path, payload)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "up -d" not in docker_log


def test_check_rejects_backend_with_old_pipeline_contract(tmp_path: Path) -> None:
    payload = (
        '{"checks":{"litellm":"ok"},"model_mode":"api",'
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
        '{"checks":{"litellm":"ok"},"model_mode":"codex",'
        '"pipeline_contract":"eight-stage-v2"}'
    )
    result, docker_log = _run_dev(tmp_path, payload, check_only=False)

    assert result.returncode == 1, result.stdout + result.stderr
    assert "incompatible" in result.stdout + result.stderr
    assert "up -d" not in docker_log


def test_default_launcher_mode_uses_api_without_starting_services(tmp_path: Path) -> None:
    payload = (
        '{"checks":{"litellm":"ok"},"model_mode":"api",'
        '"pipeline_contract":"eight-stage-v2"}'
    )
    result, docker_log = _run_dev(tmp_path, payload, default_mode=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "up -d" not in docker_log
