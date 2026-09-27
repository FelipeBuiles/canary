"""Launcher configuration checks; never starts services or contacts providers."""
import os
from pathlib import Path
import shutil
import subprocess

REPO_ROOT = Path(__file__).resolve().parents[2]


def fixture_repo(tmp_path):
    (tmp_path / "scripts").mkdir()
    (tmp_path / "web").mkdir()
    for name in ("dev_environment.sh", "dev-prod.sh"):
        shutil.copy2(REPO_ROOT / "scripts" / name, tmp_path / "scripts" / name)
    return tmp_path


def clean_env():
    return {"PATH": os.environ["PATH"], "HOME": os.environ["HOME"]}


def test_shell_values_and_empty_opt_out_win_over_files(tmp_path):
    root = fixture_repo(tmp_path)
    (root / ".env").write_text("POSTHOG_PROJECT_TOKEN=root-token\nPOSTHOG_HOST=https://us.i.posthog.com\nCANARY_LOCAL_DIAGNOSTICS=true\n")
    (root / "web/.env").write_text("VITE_POSTHOG_PROJECT_TOKEN=web-token\n")
    (root / "web/.env.local").write_text("VITE_POSTHOG_PROJECT_TOKEN=local-token\n")
    env = {**clean_env(), "POSTHOG_PROJECT_TOKEN": "shell-token", "VITE_POSTHOG_PROJECT_TOKEN": "", "CANARY_LOCAL_DIAGNOSTICS": "false"}
    result = subprocess.run(["bash", "-c", 'REPO_ROOT="$1"; source "$1/scripts/dev_environment.sh"; printf "%s|%s|%s|%s" "$POSTHOG_PROJECT_TOKEN" "$VITE_POSTHOG_PROJECT_TOKEN" "$VITE_POSTHOG_HOST" "$CANARY_LOCAL_DIAGNOSTICS"', "test", str(root)], env=env, capture_output=True, text=True, check=True)
    assert result.stdout == "shell-token||https://us.i.posthog.com|false"


def test_browser_local_file_wins_and_absent_values_inherit(tmp_path):
    root = fixture_repo(tmp_path)
    (root / ".env").write_text("POSTHOG_PROJECT_TOKEN=root-token\nPOSTHOG_HOST=https://us.i.posthog.com\n")
    (root / "web/.env").write_text("VITE_POSTHOG_PROJECT_TOKEN=web-token\n")
    (root / "web/.env.local").write_text("VITE_POSTHOG_PROJECT_TOKEN=local-token\n")
    result = subprocess.run(["bash", "-c", 'REPO_ROOT="$1"; source "$1/scripts/dev_environment.sh"; printf "%s|%s|%s|%s|%s" "$VITE_POSTHOG_PROJECT_TOKEN" "$VITE_POSTHOG_HOST" "$CANARY_LOCAL_DIAGNOSTICS" "$CANARY_ENV" "$VITE_CANARY_ENV"', "test", str(root)], env=clean_env(), capture_output=True, text=True, check=True)
    assert result.stdout == "local-token|https://us.i.posthog.com|false|development|development"


def test_prod_launcher_passes_configuration_without_printing_secret(tmp_path):
    root = fixture_repo(tmp_path)
    (root / ".env").write_text("SUPABASE_URL=https://test.supabase.co\nPOSTHOG_PROJECT_TOKEN=project-test-token\nPOSTHOG_HOST=https://us.i.posthog.com\nPOSTHOG_PROJECT_ID=123\nPOSTHOG_API_KEY=private-test-secret\n")
    (root / "web/.env.local").write_text("VITE_SUPABASE_PUBLISHABLE_KEY=test-public-key\n")
    bin_dir = root / "bin"
    bin_dir.mkdir()
    docker = bin_dir / "docker"
    docker.write_text('#!/bin/sh\nprintf "%s|%s|%s|%s|%s|%s" "$POSTHOG_PROJECT_TOKEN" "$VITE_POSTHOG_PROJECT_TOKEN" "$POSTHOG_PROJECT_ID" "$POSTHOG_API_KEY" "$VITE_CANARY_ENV" "$*" > "$DEV_ENV_TEST_RESULT"\n')
    docker.chmod(0o755)
    output = root / "result"
    env = {**clean_env(), "PATH": str(bin_dir) + os.pathsep + os.environ["PATH"], "DEV_ENV_TEST_RESULT": str(output)}
    result = subprocess.run(["bash", str(root / "scripts/dev-prod.sh"), "config"], env=env, capture_output=True, text=True, check=True)
    assert output.read_text() == "project-test-token|project-test-token|123|private-test-secret|development|compose --profile prod config"
    assert "private-test-secret" not in result.stdout + result.stderr
    assert "project-test-token" not in result.stdout + result.stderr
    assert "PostHog backend: configured" in result.stdout
    assert "PostHog browser: configured" in result.stdout


def test_compose_telemetry_secret_is_build_only():
    import yaml
    config = yaml.safe_load((REPO_ROOT / "docker-compose.yml").read_text())
    app = config["services"]["canary-prod"]
    assert "POSTHOG_PROJECT_TOKEN" in app["environment"]
    assert "POSTHOG_HOST" in app["environment"]
    assert "POSTHOG_API_KEY" not in app["environment"]
    assert "secrets" not in app
    assert app["build"]["secrets"] == ["POSTHOG_API_KEY"]
    assert "POSTHOG_API_KEY" not in app["build"]["args"]
    assert config["secrets"]["POSTHOG_API_KEY"] == {"environment": "POSTHOG_API_KEY"}
    assert app["build"]["args"]["CANARY_VERSION"] == app["environment"]["CANARY_VERSION"]


def test_release_is_shared_and_explicit_values_win(tmp_path):
    root = fixture_repo(tmp_path)
    command = ['bash', '-c', 'REPO_ROOT="$1"; source "$1/scripts/dev_environment.sh"; printf "%s|%s" "$CANARY_VERSION" "$VITE_CANARY_VERSION"', 'test', str(root)]
    result = subprocess.run(command, env=clean_env(), capture_output=True, text=True, check=True)
    backend, browser = result.stdout.split("|")
    assert backend == browser
    assert backend.startswith("local-")
    another = subprocess.run(command, env=clean_env(), capture_output=True, text=True, check=True)
    assert another.stdout != result.stdout
    result = subprocess.run(command, env={**clean_env(), "CANARY_VERSION": "release-123"}, capture_output=True, text=True, check=True)
    assert result.stdout == "release-123|release-123"
    result = subprocess.run(command, env={**clean_env(), "CANARY_VERSION": "release-123", "VITE_CANARY_VERSION": "web-456"}, capture_output=True, text=True, check=True)
    assert result.stdout == "release-123|web-456"


def test_checkout_release_uses_git_revision():
    # Avoid sourcing the real checkout's private environment files.
    script = (REPO_ROOT / "scripts/dev_environment.sh").read_text().split("# A local build", 1)[1].split("export CANARY_LOCAL_DIAGNOSTICS", 1)[0]
    expected = subprocess.run(["git", "-C", str(REPO_ROOT), "describe", "--always", "--dirty", "--abbrev=12"], capture_output=True, text=True, check=True).stdout.strip()
    result = subprocess.run(["bash", "-c", '# A local build' + script + '\nprintf "%s|%s" "$CANARY_VERSION" "$VITE_CANARY_VERSION"'], env={**clean_env(), "REPO_ROOT": str(REPO_ROOT)}, capture_output=True, text=True, check=True)
    backend, browser = result.stdout.split("|")
    assert backend == browser
    assert backend.startswith(expected + "-")
