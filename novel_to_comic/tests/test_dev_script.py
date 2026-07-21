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
    printf '%s' '{"dependencies":{"litellm":"healthy"}}'
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
        ["bash", str(REPO_ROOT / "scripts" / "dev.sh")],
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
