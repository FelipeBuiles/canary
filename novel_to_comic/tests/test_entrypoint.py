from __future__ import annotations

import os
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def _write_executable(path: Path, contents: str) -> None:
    path.write_text(contents)
    path.chmod(0o755)


def test_entrypoint_restarts_litellm_after_child_exit(tmp_path: Path) -> None:
    """The web process must not outlive an unexpectedly exited gateway."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    launch_count = tmp_path / "litellm-launch-count"
    restarted = tmp_path / "litellm-restarted"

    fake_litellm = bin_dir / "litellm"
    _write_executable(
        fake_litellm,
        f"""#!/bin/sh
count=0
if [ -f '{launch_count}' ]; then
  count=$(cat '{launch_count}')
fi
count=$((count + 1))
printf '%s' "$count" > '{launch_count}'
if [ "$count" -eq 1 ]; then
  sleep 0.3
  exit 17
fi
touch '{restarted}'
trap 'exit 0' TERM INT
while :; do sleep 1; done
""",
    )

    fake_python = bin_dir / "python"
    _write_executable(fake_python, "#!/bin/sh\nexit 0\n")

    fake_pipeline = bin_dir / "pipeline"
    _write_executable(
        fake_pipeline,
        f"""#!/bin/sh
while [ ! -f '{restarted}' ]; do sleep 0.05; done
exit 0
""",
    )

    entrypoint = (REPO_ROOT / "litellm" / "entrypoint.sh").read_text()
    entrypoint = entrypoint.replace(
        "/app/.venv-litellm/bin/litellm", str(fake_litellm)
    )
    entrypoint = entrypoint.replace(
        "/app/.venv-litellm/bin/python", str(fake_python)
    )
    entrypoint = entrypoint.replace(
        "/app/novel_to_comic/.venv/bin/pipeline", str(fake_pipeline)
    )
    test_entrypoint = tmp_path / "entrypoint.sh"
    _write_executable(test_entrypoint, entrypoint)

    env = os.environ.copy()
    env.pop("GCP_CREDENTIALS_B64", None)
    env.pop("VERTEXAI_PROJECT", None)
    env["LITELLM_READY_TIMEOUT_SECONDS"] = "2"
    env["LITELLM_RESTART_LIMIT"] = "3"
    env["LITELLM_RESTART_WINDOW_SECONDS"] = "30"

    result = subprocess.run(
        ["bash", str(test_entrypoint)],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert launch_count.read_text() == "2"
    assert "restarting" in (result.stdout + result.stderr).lower()
