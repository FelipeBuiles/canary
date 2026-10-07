"""Provider-free freshness, credential preservation, and refresh lifecycle checks."""
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import gateway_refresh as refresh
from gateway_state import (
    BUILD_ENV, BUILD_INPUTS, BUILD_LABEL, RUNTIME_INPUTS, SCHEMA_VERSION,
    build_fingerprint, record_startup, runtime_files,
)


@pytest.fixture
def checkout(tmp_path):
    for name in {*BUILD_INPUTS, *RUNTIME_INPUTS, "docker-compose.yml",
                 "docker-compose.vertex.yml", "docker-compose.aws-login.yml"}:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("initial contents")
    (tmp_path / "litellm_handlers").mkdir()
    (tmp_path / "litellm_handlers/provider.py").write_text("original handler")
    return tmp_path


def current_state(root):
    build = build_fingerprint(root)
    files = runtime_files(root)
    return dict(
        build=build, files=files, config_hash="compose-current",
        expected_models={"image-nano-banana-2.1"},
        image={"Id": "image-current", "Config": {"Labels": {BUILD_LABEL: build}}},
        container={"Id": "container", "Image": "image-current", "State": {"Running": True},
                   "Config": {"Labels": {"com.docker.compose.config-hash": "compose-current"}}},
        live={"state": {"schema_version": SCHEMA_VERSION, "build_sha256": build,
                        "runtime_files": files}, "models": ["image-nano-banana-2.1"]},
    )


def test_current_gateway_needs_no_action_and_timestamps_do_not_matter(checkout):
    state = current_state(checkout)
    (checkout / BUILD_INPUTS[0]).touch()
    (checkout / RUNTIME_INPUTS[0]).touch()
    assert build_fingerprint(checkout) == state["build"]
    assert runtime_files(checkout) == state["files"]
    assert refresh.plan_refresh(**state).action == "current"


@pytest.mark.parametrize("filename", BUILD_INPUTS)
def test_image_inputs_require_rebuilding(checkout, filename):
    state = current_state(checkout)
    (checkout / filename).write_text("changed contents")
    state["build"] = build_fingerprint(checkout)
    assert refresh.plan_refresh(**state).action == "build"


@pytest.mark.parametrize("filename", [*RUNTIME_INPUTS, "litellm_handlers/provider.py"])
def test_mounted_changes_only_require_recreation(checkout, filename):
    state = current_state(checkout)
    (checkout / filename).write_text("changed contents")
    assert build_fingerprint(checkout) == state["build"]
    state["files"] = runtime_files(checkout)
    plan = refresh.plan_refresh(**state)
    assert plan.action == "recreate"
    assert filename in " ".join(plan.reasons)


def test_added_and_removed_handler_files_are_detected(checkout):
    state = current_state(checkout)
    (checkout / "litellm_handlers/provider.py").unlink()
    (checkout / "litellm_handlers/new_provider.py").write_text("new handler")
    (checkout / "litellm_handlers/test_provider.py").write_text("test changes are excluded")
    state["files"] = runtime_files(checkout)
    plan = refresh.plan_refresh(**state)
    assert plan.action == "recreate"
    assert "provider.py" in " ".join(plan.reasons)
    assert "new_provider.py" in " ".join(plan.reasons)
    assert "test_provider.py" not in " ".join(plan.reasons)


def test_startup_record_stays_frozen_after_bind_mount_changes(checkout, tmp_path):
    app = tmp_path / "app"
    app.mkdir()
    for name in RUNTIME_INPUTS:
        (app / Path(name).name).write_bytes((checkout / name).read_bytes())
    (app / "litellm_handlers").mkdir()
    (app / "litellm_handlers/provider.py").write_text("original handler")
    output = app / "gateway-state.json"
    record_startup(app, output, {BUILD_ENV: "built", "OPENAI_API_KEY": "private-key"})
    original = output.read_text()
    assert json.loads(original)["runtime_files"] == runtime_files(checkout)
    (app / "config.yaml").write_text("new configuration")
    assert output.read_text() == original
    assert json.loads(original)["runtime_files"] != runtime_files(app, container=True)
    assert "private-key" not in original


@pytest.mark.parametrize("case", ["older_image", "settings", "missing_route", "missing_stamp", "stopped", "missing_container"])
def test_other_staleness_requires_recreation_without_rebuilding(checkout, case):
    state = current_state(checkout)
    if case == "older_image":
        state["container"]["Image"] = "older-image"
    elif case == "settings":
        state["config_hash"] = "changed-settings"
    elif case == "missing_route":
        state["live"]["models"] = []
    elif case == "missing_stamp":
        state["live"]["state"] = None
    elif case == "stopped":
        state["container"]["State"]["Running"] = False
    else:
        state["container"] = None
    assert refresh.plan_refresh(**state).action == "recreate"


def test_untracked_image_requires_one_bootstrap_build(checkout):
    state = current_state(checkout)
    state["image"]["Config"]["Labels"] = {}
    assert refresh.plan_refresh(**state).action == "build"


def test_unavailable_inventory_does_not_trigger_a_blind_restart(checkout):
    state = current_state(checkout)
    state["live"]["models"] = None
    assert refresh.plan_refresh(**state).action == "unhealthy"


def test_compose_context_preserves_credentials_mounts_and_custom_project(checkout):
    (checkout / "docker-compose.yml").write_text("${LITELLM_MASTER_KEY} ${OPENAI_API_KEY} ${VERTEXAI_PROJECT}")
    existing = {
        "Config": {"Env": ["LITELLM_MASTER_KEY=private-master", "OPENAI_API_KEY=private-provider",
                           "VERTEXAI_PROJECT=credited", "DATABASE_URL=postgresql://private-db"],
                   "Labels": {"com.docker.compose.project": "custom-canary",
                              "com.docker.compose.project.config_files": str(checkout / "docker-compose.yml")}},
        "Mounts": [{"Destination": target, "Source": str(checkout / name)} for name, target in (
            ("adc.json", "/run/credentials/google-adc.json"), ("aws.conf", "/run/aws/config"),
            ("aws-cache", "/run/aws/login/cache"))],
    }
    command, env = refresh.compose_context(checkout, existing, {"PATH": "/host/bin", "OPENAI_API_KEY": "rotated"})
    assert command[:4] == ["docker", "compose", "--project-name", "custom-canary"]
    assert str(checkout / "docker-compose.vertex.yml") in command
    assert str(checkout / "docker-compose.aws-login.yml") in command
    assert env["LITELLM_MASTER_KEY"] == "private-master"
    assert env["OPENAI_API_KEY"] == "rotated"
    assert env["VERTEXAI_PROJECT"] == "credited"
    assert env["LITELLM_DATABASE_URL"] == "postgresql://private-db"
    assert env["CANARY_VERTEX_CREDENTIALS_FILE"] == str(checkout / "adc.json")
    assert env["CANARY_AWS_CONFIG_FILE"] == str(checkout / "aws.conf")
    assert env["CANARY_AWS_LOGIN_CACHE_DIRECTORY"] == str(checkout / "aws-cache")
    assert env["PATH"] == "/host/bin"
    assert all("private-master" not in arg and "private-provider" not in arg for arg in command)


@pytest.mark.parametrize("check", [True, False])
def test_check_never_mutates_and_refresh_reuses_a_current_gateway(monkeypatch, capsys, check):
    actions = []
    class Stub:
        def __init__(self, *args):
            pass
        def inspect(self):
            return refresh.RefreshPlan("recreate", ("Changed handler",)) if check else refresh.RefreshPlan("current")
        def execute(self, plan):
            actions.append(plan)
    monkeypatch.setattr(refresh, "Gateway", Stub)
    assert refresh.main(["--check"] if check else []) == (1 if check else 0)
    assert actions == []
    if check:
        assert "./scripts/gateway.sh" in capsys.readouterr().out


@pytest.mark.parametrize("action", ["build", "recreate"])
def test_refresh_orders_build_before_recreate_and_verifies_inventory(checkout, action):
    commands = []
    gateway = refresh.Gateway(checkout, {})
    gateway.build = build_fingerprint(checkout)
    gateway.compose = ["docker", "compose"]
    gateway.run = lambda args: commands.append(args)
    gateway.capture = lambda *args, **kwargs: "healthy-database"
    gateway.discover = lambda: {"State": {"Running": True}}
    gateway.probe = lambda container: {"models": ["image-nano-banana-2.1"]}
    gateway.inspect = lambda: refresh.RefreshPlan("current")
    gateway.execute(refresh.RefreshPlan(action))
    assert commands[-1] == ["up", "-d", "--no-deps", "--force-recreate", "litellm"]
    assert (commands[0][0] == "build") is (action == "build")
    assert all("down" not in args and "litellm-db" not in args for args in commands)


def test_failed_build_leaves_running_gateway_untouched(checkout):
    commands = []
    gateway = refresh.Gateway(checkout, {})
    gateway.build = build_fingerprint(checkout)
    def fail(args):
        commands.append(args)
        raise RuntimeError("Build failed")
    gateway.run = fail
    with pytest.raises(RuntimeError, match="Build failed"):
        gateway.execute(refresh.RefreshPlan("build"))
    assert len(commands) == 1
    assert commands[0][0] == "build"


def test_private_docker_payload_is_not_printed(monkeypatch, capsys):
    class Stub:
        def __init__(self, *args):
            pass
        def inspect(self):
            raise ValueError("private-token in malformed Docker configuration")
    monkeypatch.setattr(refresh, "Gateway", Stub)
    assert refresh.main(["--check"]) == 1
    assert "private-token" not in capsys.readouterr().err


def test_read_only_and_forced_build_flags_cannot_be_combined():
    with pytest.raises(SystemExit) as captured:
        refresh.main(["--check", "--rebuild"])
    assert captured.value.code == 2
