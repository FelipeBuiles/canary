from __future__ import annotations

import os
import subprocess
import sys
import json
import importlib.util
import time
import signal
import shlex
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def _write_executable(path: Path, contents: str) -> None:
    path.write_text(contents)
    path.chmod(0o755)


def _entrypoint_environment(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    # Supervision tests assert lifecycle transitions, not wall-clock sleeps.
    # Exact recovery delays have deterministic coverage below. Keep genuine
    # child processes/signals, with short polling/restart/shutdown intervals.
    _write_executable(bin_dir / "sleep", '''#!/bin/sh
case "$1" in
  1|2|3) exec /bin/sleep 0.02 ;;
  *) exec /bin/sleep "$@" ;;
esac
''')
    recovery_python = bin_dir / "recovery-python"
    _write_executable(recovery_python, f'''#!/bin/sh
# Health probes fail immediately; never contact a developer's live server.
if [ "$1" = "-c" ]; then exit 1; fi
exec {shlex.quote(sys.executable)} "$@"
''')
    env = os.environ.copy()
    env.pop("GCP_CREDENTIALS_B64", None)
    env.pop("VERTEXAI_PROJECT", None)
    env.update(
        PATH=str(bin_dir) + os.pathsep + env.get("PATH", ""),
        CANARY_RECOVERY_PYTHON=str(recovery_python),
        CANARY_RECOVERY_SCRIPT=str(REPO_ROOT / "litellm/recovery.py"),
        CANARY_RECOVERY_STATE=str(tmp_path / "recovery.json"),
        CANARY_RESTART_BACKOFF_SECONDS="0.01",
        CANARY_SHUTDOWN_TIMEOUT_SECONDS="1",
    )
    return env


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
kill -TERM \"$PPID\"
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

    env = _entrypoint_environment(tmp_path)
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


def _recovery_module():
    spec = importlib.util.spec_from_file_location("recovery", REPO_ROOT / "litellm/recovery.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_durable_crash_budget_backoff_and_explicit_reset(tmp_path):
    recovery = _recovery_module()
    path = tmp_path / "recovery.json"
    state = {}
    for index, expected_delay in enumerate((0, 2, 4, 8)):
        state, delay = recovery.transition(state, "begin", now=index)
        assert delay == expected_delay
        assert not state["budget_exhausted"]
        recovery.save_state(path, state)
        state = recovery.read_state(path)  # Simulated replacement process.
    state, _ = recovery.transition(state, "crash", now=4)
    assert state["budget_exhausted"]
    # Waiting out Fly's rolling window does not reopen a latched budget.
    state, _ = recovery.transition(state, "begin", now=3600)
    assert state["budget_exhausted"] and not state["running"]
    state, _ = recovery.transition(state, "reset", now=3601)
    state, delay = recovery.transition(state, "begin", now=3602)
    assert delay == 0 and not state["budget_exhausted"]


def test_budget_resets_only_after_continuous_local_health():
    recovery = _recovery_module()
    state, _ = recovery.transition({}, "begin", now=0)
    state, _ = recovery.transition(state, "begin", now=1)
    state, _ = recovery.transition(state, "healthy", now=10)
    state, _ = recovery.transition(state, "healthy", now=309)
    assert state["restart_count"] == 1
    state, _ = recovery.transition(state, "unhealthy", now=310)
    state, _ = recovery.transition(state, "healthy", now=320)
    state, _ = recovery.transition(state, "healthy", now=620)
    assert state["restart_count"] == 0


def _fake_entrypoint(tmp_path, pipeline="exit 17", proxy="while :; do sleep 1; done", ready=True):
    fake_proxy = tmp_path / "proxy"
    fake_python = tmp_path / "proxy-python"
    fake_pipeline = tmp_path / "pipeline"
    _write_executable(fake_proxy, "#!/bin/sh\ntrap 'exit 0' TERM INT\n" + proxy + "\n")
    _write_executable(fake_python, "#!/bin/sh\nexit " + ("0" if ready else "1") + "\n")
    pipeline = pipeline.replace("exit 0", 'kill -TERM "$PPID"; exit 0')
    _write_executable(fake_pipeline, "#!/bin/sh\ntrap 'exit 0' TERM INT\n" + pipeline + "\n")
    script = (REPO_ROOT / "litellm/entrypoint.sh").read_text()
    for source, target in (("/app/.venv-litellm/bin/litellm", fake_proxy),
                           ("/app/.venv-litellm/bin/python", fake_python),
                           ("/app/novel_to_comic/.venv/bin/pipeline", fake_pipeline)):
        script = script.replace(source, str(target))
    entrypoint = tmp_path / "entrypoint.sh"
    _write_executable(entrypoint, script)
    env = _entrypoint_environment(tmp_path)
    env.update(LITELLM_READY_TIMEOUT_SECONDS="1", LITELLM_RESTART_LIMIT="1")
    return entrypoint, env


def test_children_receive_only_their_own_secrets(tmp_path):
    gateway, web = tmp_path / "gateway.env", tmp_path / "web.env"
    entrypoint, env = _fake_entrypoint(
        tmp_path,
        proxy=f'env > "{gateway}"; while :; do sleep 1; done',
        pipeline=f'env > "{web}"; while [ ! -s "{gateway}" ]; do sleep 0.05; done; exit 0',
    )
    gateway_only = {"OPENAI_API_KEY", "FAL_KEY", "LITELLM_MASTER_KEY", "LITELLM_SALT_KEY",
                    "AWS_BEARER_TOKEN_BEDROCK", "DATABASE_URL"}
    web_only = {"LITELLM_API_KEY", "CANARY_OPS_TOKEN", "SUPABASE_SECRET_KEY",
                "CANARY_QUEUE_DATABASE_URL", "STRIPE_SECRET_KEY", "STRIPE_WEBHOOK_SECRET",
                "R2_ACCESS_KEY", "R2_SECRET_KEY"}
    env.update({name: "dummy-" + name for name in gateway_only | web_only})
    env["CANARY_ENV"] = "production"
    result = subprocess.run(["bash", str(entrypoint)], env=env, capture_output=True, timeout=10)
    assert result.returncode == 0, result.stderr

    def names(path):
        return {line.split("=", 1)[0] for line in path.read_text().splitlines() if "=" in line}

    assert gateway_only <= names(gateway) and not web_only & names(gateway)
    assert web_only <= names(web) and not gateway_only & names(web)
    assert "CANARY_ENV" in names(gateway) & names(web)


def test_web_crashes_recover_then_latch_without_touching_customer_files(tmp_path):
    entrypoint, env = _fake_entrypoint(tmp_path)
    artwork = tmp_path / "page.png"
    artwork.write_bytes(b"saved artwork")
    results = [subprocess.run(["bash", str(entrypoint)], env=env, capture_output=True,
                              timeout=10).returncode for _ in range(5)]
    assert results == [17, 17, 17, 17, 0]
    assert json.loads((tmp_path / "recovery.json").read_text())["budget_exhausted"]
    assert artwork.read_bytes() == b"saved artwork"


def test_deliberate_termination_during_readiness_exits_successfully(tmp_path):
    entrypoint, env = _fake_entrypoint(tmp_path, ready=False)
    env["LITELLM_READY_TIMEOUT_SECONDS"] = "60"
    with subprocess.Popen(["bash", str(entrypoint)], env=env,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE) as child:
        deadline = time.monotonic() + 5
        while not (tmp_path / "recovery.json").exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        time.sleep(0.1)
        child.send_signal(signal.SIGTERM)
        child.communicate(timeout=5)
        assert child.returncode == 0
    assert json.loads((tmp_path / "recovery.json").read_text())["last_exit_reason"] == "intentional_stop"


def test_dependency_failure_exhausts_gateway_without_restarting_web(tmp_path):
    # Stop on the observed terminal event, not after an arbitrary five seconds.
    pipeline = f'''while ! grep -q '"gateway_status": "exhausted"' '{tmp_path / "recovery.json"}'; do sleep 0.02; done; exit 0'''
    entrypoint, env = _fake_entrypoint(tmp_path, pipeline=pipeline, proxy="exit 18", ready=False)
    result = subprocess.run(["bash", str(entrypoint)], env=env, capture_output=True, timeout=10)
    assert result.returncode == 0
    state = json.loads((tmp_path / "recovery.json").read_text())
    assert state["gateway_status"] == "exhausted"
    assert state.get("restart_count", 0) == 0


def test_corrupt_recovery_state_fails_closed(tmp_path):
    entrypoint, env = _fake_entrypoint(tmp_path)
    (tmp_path / "recovery.json").write_text("broken")
    result = subprocess.run(["bash", str(entrypoint)], env=env, capture_output=True, timeout=5)
    assert result.returncode == 0
    assert (tmp_path / "recovery.json").read_text() == "broken"


def test_operator_reset_id_is_consumed_once(tmp_path):
    entrypoint, env = _fake_entrypoint(tmp_path)
    recovery = _recovery_module()
    recovery.save_state(tmp_path / "recovery.json", {"schema": 1, "budget_exhausted": True})
    env["CANARY_RECOVERY_RESET_ID"] = "local-incident-1"
    # An unchanged configured ID cannot refill the crash budget on each boot.
    results = [subprocess.run(["bash", str(entrypoint)], env=env, capture_output=True,
                              timeout=10).returncode for _ in range(5)]
    assert results == [17, 17, 17, 17, 0]
    state = recovery.read_state(tmp_path / "recovery.json")
    assert state["last_reset_id"] == "local-incident-1" and state["budget_exhausted"]


def test_web_local_readiness_deadline_is_bounded(tmp_path):
    entrypoint, env = _fake_entrypoint(tmp_path, pipeline="while :; do sleep 1; done")
    env["CANARY_WEB_READY_TIMEOUT_SECONDS"] = "0"
    result = subprocess.run(["bash", str(entrypoint)], env=env, capture_output=True, timeout=5)
    assert result.returncode == 1
    assert b"local startup health deadline" in result.stderr


def test_ordinary_crash_next_boot_recovers_and_clean_stop_keeps_budget(tmp_path):
    marker = tmp_path / "crashed-once"
    entrypoint, env = _fake_entrypoint(
        tmp_path, pipeline=f"if [ ! -f '{marker}' ]; then touch '{marker}'; exit 17; fi\nexit 0"
    )
    started = time.monotonic()
    codes = [subprocess.run(["bash", str(entrypoint)], env=env, capture_output=True,
                            timeout=10).returncode for _ in range(3)]
    assert codes == [17, 0, 0]
    assert time.monotonic() - started < 10
    state = json.loads((tmp_path / "recovery.json").read_text())
    assert state["restart_count"] == 1  # Deliberate clean starts do not spend budget.
    assert state["last_exit_reason"] == "intentional_stop"
    assert not state["budget_exhausted"]


def test_unexpected_clean_web_exit_is_a_failure(tmp_path):
    entrypoint, env = _fake_entrypoint(tmp_path, pipeline="true")
    result = subprocess.run(["bash", str(entrypoint)], env=env, capture_output=True, timeout=5)
    assert result.returncode == 1
    assert json.loads((tmp_path / "recovery.json").read_text())["last_exit_reason"] == "unexpected_exit"
