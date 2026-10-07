"""Exercise the real Git hook against a local bare remote, without network calls."""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def run_git(*args, cwd):
    return subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, check=True,
    )


@pytest.fixture
def checkout(tmp_path):
    repo = tmp_path / "checkout with spaces"
    repo.mkdir()
    run_git("init", "-q", "-b", "main", cwd=repo)
    (repo / "scripts").mkdir()
    (repo / ".githooks").mkdir()
    shutil.copy2(ROOT / "scripts/check_all.sh", repo / "scripts/check_all.sh")
    shutil.copy2(ROOT / ".githooks/pre-push", repo / ".githooks/pre-push")
    (repo / ".nvmrc").write_text("24.21.0\n")
    (repo / "scripts/check_release.py").write_text('''
import json
import os
import sys
from pathlib import Path

Path(__file__).with_name("check-run.json").write_text(json.dumps({
    "arguments": sys.argv[1:],
    "url": os.environ["VITE_SUPABASE_URL"],
    "key": os.environ["VITE_SUPABASE_PUBLISHABLE_KEY"],
    "uploads": os.environ["POSTHOG_API_KEY"],
    "stdin": sys.stdin.read(),
}))
print("test gate invoked", flush=True)
raise SystemExit(int(os.environ.get("TEST_GATE_EXIT", "0")))
''')
    run_git("config", "core.hooksPath", ".githooks", cwd=repo)
    run_git("add", ".", cwd=repo)
    run_git(
        "-c", "user.name=Hook test", "-c", "user.email=tests@example.invalid",
        "-c", "commit.gpgsign=false",
        "commit", "-qm", "test checkout", cwd=repo,
    )
    remote = tmp_path / "remote.git"
    run_git("init", "--bare", "-q", str(remote), cwd=tmp_path)
    run_git("remote", "add", "origin", str(remote), cwd=repo)
    (repo / "nested").mkdir()
    return repo, remote


def gate_environment(tmp_path, version="24.21.0"):
    binaries = tmp_path / "bin"
    binaries.mkdir()
    node = binaries / "node"
    node.write_text(f"#!/bin/sh\nprintf 'v{version}\\n'\n")
    node.chmod(0o755)
    return {
        **os.environ,
        "PATH": f"{binaries}{os.pathsep}{os.environ['PATH']}",
        "NVM_DIR": str(tmp_path / "absent-nvm"),
        "VITE_SUPABASE_URL": "https://local-settings.example.invalid",
        "VITE_SUPABASE_PUBLISHABLE_KEY": "local-settings",
        "POSTHOG_API_KEY": "would-upload",
    }


@pytest.mark.parametrize("gate_exit", [0, 23])
def test_push_requires_successful_gate(checkout, tmp_path, gate_exit):
    repo, remote = checkout
    env = {**gate_environment(tmp_path), "TEST_GATE_EXIT": str(gate_exit)}
    pushed = subprocess.run(
        ["git", "push", "origin", "main"], cwd=repo / "nested", env=env,
        capture_output=True, text=True, timeout=20,
    )
    assert "test gate invoked" in pushed.stdout + pushed.stderr
    record = json.loads((repo / "scripts/check-run.json").read_text())
    assert record == {
        "arguments": ["local"], "url": "https://ci.supabase.co",
        "key": "sb_publishable_ci", "uploads": "", "stdin": "",
    }
    remote_head = subprocess.run(
        ["git", "rev-parse", "--verify", "refs/heads/main"], cwd=remote,
        capture_output=True, text=True,
    )
    if gate_exit:
        assert pushed.returncode != 0
        assert remote_head.returncode != 0
    else:
        assert pushed.returncode == 0, pushed.stdout + pushed.stderr
        assert remote_head.returncode == 0
        assert remote_head.stdout == run_git("rev-parse", "HEAD", cwd=repo).stdout


def test_wrong_node_blocks_push_before_running_checks(checkout, tmp_path):
    repo, remote = checkout
    pushed = subprocess.run(
        ["git", "push", "origin", "main"], cwd=repo,
        env=gate_environment(tmp_path, version="22.0.0"),
        capture_output=True, text=True, timeout=20,
    )
    assert pushed.returncode != 0
    assert "Node 24.21.0 is required" in pushed.stderr
    assert not (repo / "scripts/check-run.json").exists()
    assert not (remote / "refs/heads/main").exists()
