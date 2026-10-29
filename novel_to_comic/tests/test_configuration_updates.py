"""Offline configuration protocol, concurrency and failure-boundary contracts."""

from __future__ import annotations

import base64
import importlib.util
import json
import socket
import subprocess
import threading
import tempfile
import time
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]


def load(path):
    spec = importlib.util.spec_from_file_location(
        "configuration_test_" + path.stem, path
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def host(tmp_path, monkeypatch):
    c = load(ROOT / "deploy/lightsail/config_controller.py")
    r = load(ROOT / "deploy/lightsail/release.py")
    base = tmp_path / "base"
    base.mkdir()
    for name in (
        "release.py",
        "config_controller.py",
        "config_schema.json",
        "verify_config_runtime.py",
        "compose.yaml",
    ):
        (base / name).write_bytes((ROOT / "deploy/lightsail" / name).read_bytes())
    (base / "canary_secrets.py").write_text("loader")
    (base / "verify_deployment.py").write_text("verifier")
    monkeypatch.setattr(c, "BASE", base)
    monkeypatch.setattr(c, "STATE", tmp_path / "state")
    monkeypatch.setattr(c, "ENABLED", tmp_path / "enabled")
    c.ENABLED.touch()
    monkeypatch.setattr(c, "PUBLIC_HOLD", tmp_path / "public-hold")
    monkeypatch.setattr(c, "BOOT", tmp_path / "boot")
    c.BOOT.write_text("boot-one")
    monkeypatch.setattr(c, "BUNDLES", tmp_path / "bundles")
    c.BUNDLES.mkdir()
    monkeypatch.setattr(r, "BASE", base)
    monkeypatch.setattr(r, "CONFIG", tmp_path / "deployment.env")
    monkeypatch.setattr(r, "MAINTENANCE", tmp_path / "maintenance")
    monkeypatch.setattr(r, "RUNTIME", tmp_path / "run")
    r.RUNTIME.mkdir()
    monkeypatch.setattr(r, "CONFIG_STATE", c.STATE)
    monkeypatch.setattr(r, "private_read", lambda p: p.read_bytes())
    bundle_path = c.BUNDLES / ("b" * 64 + ".sops.json")
    bundle_path.write_text('{"env":{"CANARY_OPS_TOKEN":"encrypted"}}')
    config = {
        "CANARY_IMAGE": r.REPOSITORY + "@sha256:" + "a" * 64,
        "CANARY_BUNDLE_PATH": str(bundle_path),
        "CANARY_BUNDLE_SHA256": "b" * 64,
        "CANARY_LOADER_SHA256": c.digest(b"loader"),
        "SCENEWRIGHT_APP_URL": "https://scenewright.ink",
        "CANARY_HEALTH_HOST": "scenewright.ink",
    }
    r.CONFIG.write_bytes(r.serialize_environment(config))
    actions = []
    state = {"resumed": False, "fail": None, "identity": "one"}

    def run(args, **kwargs):
        actions.append(tuple(args))
        if state["fail"] and state["fail"](args):
            raise subprocess.CalledProcessError(1, args, output=b"private-token")
        if args[:3] == ["docker", "image", "inspect"]:
            return json.dumps(
                [{"Config": {"Env": ["CANARY_VERSION=" + "c" * 40]}}]
            ).encode()
        if args[:2] == ["docker", "run"]:
            return (config["CANARY_LOADER_SHA256"] + "  loader").encode()
        return b""

    def api(path, *_args):
        actions.append((path,))
        if path.endswith("/resume"):
            state["resumed"] = True
        if path.endswith("deployment-status"):
            return {
                "draining": state["resumed"] is False
                if r.MAINTENANCE.exists() or state["resumed"]
                else False,
                "safe_to_deploy": True,
                "counts": {"running_generation_jobs": 0},
            }
        return {"git_sha": "c" * 40, "status": "ok"}

    bundle = {
        "env": {
            "CANARY_OPS_TOKEN": "private-token",
            "RUNWARE_API_KEY": "private-provider",
        },
        "files": {},
    }
    loader = SimpleNamespace(
        require_tmpfs=lambda *_: None,
        require_no_swap=lambda *_: None,
        decrypt=lambda *_: bundle,
    )
    monkeypatch.setattr(c, "release", lambda: r)
    monkeypatch.setattr(c, "loader_context", lambda *_: (loader, bundle))
    monkeypatch.setattr(
        c,
        "observe",
        lambda _config, baseline: {
            "match": "match",
            "source_sha": "c" * 40,
            "revision": baseline,
            "observed_at": time.time(),
        },
    )
    monkeypatch.setattr(
        c, "launch", lambda op, action: actions.append(("launch", op, action))
    )
    monkeypatch.setattr(c, "verify_secrets", lambda *_: None)
    monkeypatch.setattr(r, "run", run)
    monkeypatch.setattr(r, "api", api)
    monkeypatch.setattr(
        r,
        "candidate_identity",
        lambda **_: {"container_id": state["identity"], "restarts": "0"},
    )
    monkeypatch.setattr(
        r, "wait_candidate", lambda *_: actions.append(("local-ready",))
    )
    monkeypatch.setattr(
        r,
        "verify_public",
        lambda *_: actions.append(("public-ready",)) or {"public": True},
    )
    c.initialize()
    return c, r, config, actions, state


def plan(c, patch=None, transport="backoffice"):
    request = {
        "action": "config_plan",
        "request_id": str(uuid.uuid4()),
        "patch": patch or {},
    }
    result = c.handle(request, transport=transport)
    c.worker(result["request_id"])
    return c.operation(result["request_id"])


def apply_request(preview):
    return {
        "action": "config_apply",
        "request_id": str(uuid.uuid4()),
        "plan_id": preview["request_id"],
        "plan_digest": preview["plan"]["digest"],
    }


def test_serializer_common_subset_and_ascii_byte_preservation(host):
    _, r, *_ = host
    values = {
        "EMPTY": "",
        "SPACES": " leading ' quoted # URI:?=,& trailing ",
        "FLAG": "true",
    }
    assert r.parse_environment(r.serialize_environment(values)) == values
    assert (
        r.serialize_environment(values)
        == (
            "\n".join(f"{k}={json.dumps(v)}" for k, v in values.items()) + "\n"
        ).encode()
    )
    for value in [
        "café",
        "$HOME",
        'quote"',
        "slash\\",
        "tab\t",
        "line\n",
        "`cmd`",
        "\x00",
    ]:
        with pytest.raises(RuntimeError, match="unsupported_environment_value"):
            r.serialize_environment({"VALUE": value})


def test_plan_is_memory_only_and_does_not_take_release_lock(host):
    c, r, _, actions, _ = host
    import fcntl

    with (r.RUNTIME / "worker.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        preview = plan(c, {"CANARY_RUNWARE_FIRST_ENABLED": "true"})
    assert preview["phase"] == "plan_ready"
    assert not r.MAINTENANCE.exists()
    assert list(r.RUNTIME.iterdir()) == [r.RUNTIME / "worker.lock"]
    assert not any("stop" in action or "start" in action for action in actions)
    assert "private-token" not in json.dumps(preview)
    assert preview["plan"]["source_sha"] == "c" * 40


def test_noop_does_not_drain_or_restart(host):
    c, r, _, actions, _ = host
    preview = plan(c, {"CANARY_RUNWARE_FIRST_ENABLED": "false"})
    assert preview["plan"]["restart_required"] is False
    request = apply_request(preview)
    c.handle(request)
    c.worker(request["request_id"])
    assert c.operation(request["request_id"])["phase"] == "complete"
    assert not any("stop" in action or "start" in action for action in actions)
    assert not r.MAINTENANCE.exists()


def test_apply_orders_drain_stop_publish_verify_and_resume(host):
    c, r, _, actions, _ = host
    preview = plan(c, {"CANARY_RUNWARE_FIRST_ENABLED": "true"})
    request = apply_request(preview)
    c.handle(request)
    c.worker(request["request_id"])
    current = c.operation(request["request_id"])
    assert current["phase"] == "complete", current
    assert actions.index(("/api/ops/drain",)) < actions.index(
        ("systemctl", "stop", "canary.service")
    )
    assert (
        actions.index(("systemctl", "start", "canary.service"))
        < actions.index(("public-ready",))
        < actions.index(("/api/ops/resume",))
    )
    assert "reset-failed" not in json.dumps(actions)
    assert (
        r.parse_environment(r.CONFIG.read_bytes())["CANARY_RUNWARE_FIRST_ENABLED"]
        == "true"
    )
    assert not r.MAINTENANCE.exists()
    assert current["receipt"]["transport"] == "backoffice"
    assert "private-token" not in json.dumps(c.events(request["request_id"]))


def test_lock_loss_never_reserves_authorization_or_creates_hold(host, monkeypatch):
    c, r, _, _, _ = host
    preview = plan(c)
    request = apply_request(preview)
    c.handle(request)
    monkeypatch.setattr(c, "reserve", lambda *_: pytest.fail("reserved before lock"))
    import fcntl

    with (r.RUNTIME / "worker.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        c.worker(request["request_id"])
    assert c.operation(request["request_id"])["phase"] == "rejected_busy"
    assert not r.MAINTENANCE.exists()


def test_reservation_is_after_lock_before_hold(host, monkeypatch):
    c, r, _, _, _ = host
    preview = plan(c, {"CANARY_RUNWARE_FIRST_ENABLED": "true"})
    request = apply_request(preview)
    c.handle(request)

    def reserve(*_):
        assert not r.MAINTENANCE.exists()
        import fcntl

        with (
            (r.RUNTIME / "worker.lock").open("a") as lock,
            pytest.raises(BlockingIOError),
        ):
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)

    monkeypatch.setattr(c, "reserve", reserve)
    c.worker(request["request_id"])
    assert c.operation(request["request_id"])["phase"] == "complete"


@pytest.mark.parametrize(
    "key,value,transport,error",
    [
        ("CANARY_IMAGE", "bad", "ssh", "unsupported_setting"),
        ("SUPABASE_URL", "https://other.test", "backoffice", "ssh_only"),
        ("CANARY_RUNWARE_FIRST_ENABLED", "yes", "backoffice", "invalid_setting"),
        ("VERTEXAI_LOCATION", "", "ssh", "invalid_setting"),
        ("AWS_REGION_NAME", "", "ssh", "invalid_setting"),
    ],
)
def test_host_enforces_schema_and_transport(host, key, value, transport, error):
    c, *_ = host
    preview = plan(c, {key: value}, transport)
    assert preview["phase"] == "rejected"
    assert preview["error"] == error


def test_ssh_only_plan_cannot_be_applied_from_backoffice(host):
    c, *_ = host
    preview = plan(c, {"CANARY_INTERNAL_ACCOUNT_IDS": "reviewed"}, "ssh")
    assert preview["phase"] == "plan_ready"
    request = apply_request(preview)
    c.handle(request)
    c.worker(request["request_id"])
    assert c.operation(request["request_id"])["error"] == "ssh_only"


def test_whole_baseline_change_rejects_before_drain(host):
    c, r, config, actions, _ = host
    preview = plan(c, {"CANARY_RUNWARE_FIRST_ENABLED": "true"})
    r.CONFIG.write_bytes(
        r.serialize_environment({**config, "CANARY_INTERNAL_ACCOUNT_IDS": "other"})
    )
    request = apply_request(preview)
    c.handle(request)
    c.worker(request["request_id"])
    assert c.operation(request["request_id"])["error"] == "baseline_changed"
    assert ("/api/ops/drain",) not in actions


def test_expiry_uses_earlier_clock_with_plan_tie(host):
    c, *_ = host
    now = time.time()
    for plan_time, auth_time, code in [
        (now - 2, now - 1, "plan_expired"),
        (now - 1, now - 2, "authorization_expired"),
        (now - 1, now - 1, "plan_expired"),
    ]:
        with pytest.raises(RuntimeError, match=code):
            c.expiry(
                {"plan_expires_at": plan_time, "authorization_expires_at": auth_time}
            )


def test_idempotency_survives_later_requests_and_payload_mismatch(host):
    c, *_ = host
    request = {"action": "config_plan", "request_id": str(uuid.uuid4()), "patch": {}}
    c.handle(request)
    c.worker(request["request_id"])
    plan(c)
    assert c.handle(request)["phase"] == "plan_ready"
    with pytest.raises(RuntimeError, match="request_id_conflict"):
        c.handle({**request, "patch": {"CANARY_RUNWARE_FIRST_ENABLED": "true"}})


def test_authorization_ledger_survives_reload_and_rejects_reuse(host):
    c, *_ = host
    manifest = {"authorization_id": str(uuid.uuid4()), "expires_at": time.time() + 60}
    c.reserve(manifest, str(uuid.uuid4()))
    other = load(ROOT / "deploy/lightsail/config_controller.py")
    setattr(other, "STATE", c.STATE)
    with pytest.raises(RuntimeError, match="authorization_used"):
        other.reserve(manifest, str(uuid.uuid4()))


def test_manifest_is_bound_to_replaced_bundle_not_image(host):
    c, _, config, *_ = host
    manifest = {
        "target": "production",
        "bundle_sha256": "d" * 64,
        "replaces_bundle_sha256": config["CANARY_BUNDLE_SHA256"],
        "authorization_id": str(uuid.uuid4()),
        "expires_at": int(time.time()) + 60,
        "recovery_verification": True,
    }
    c.manifest_check(manifest, {**config, "CANARY_IMAGE": "changed"}, "d" * 64)
    with pytest.raises(RuntimeError, match="invalid_manifest"):
        c.manifest_check(
            manifest, {**config, "CANARY_BUNDLE_SHA256": "e" * 64}, "d" * 64
        )


@pytest.mark.parametrize("failure", ["stop", "start"])
def test_replacement_failure_retains_hold_and_never_resumes(host, failure):
    c, r, _, actions, state = host
    preview = plan(c, {"CANARY_RUNWARE_FIRST_ENABLED": "true"})
    state["fail"] = lambda args: args[:2] == ["systemctl", failure]
    request = apply_request(preview)
    c.handle(request)
    c.worker(request["request_id"])
    current = c.operation(request["request_id"])
    assert current["phase"] == "failed"
    assert r.MAINTENANCE.exists()
    assert ("/api/ops/resume",) not in actions
    assert "private-token" not in json.dumps(current)


def test_ambiguous_resume_does_not_stop_candidate(host, monkeypatch):
    c, r, _, actions, _ = host
    preview = plan(c, {"CANARY_RUNWARE_FIRST_ENABLED": "true"})
    original = r.api
    attempted = False

    def api(path, *args):
        nonlocal attempted
        if path.endswith("/resume"):
            attempted = True
            raise OSError("private-token")
        if attempted:
            raise OSError("private-token")
        return original(path, *args)

    monkeypatch.setattr(r, "api", api)
    request = apply_request(preview)
    c.handle(request)
    c.worker(request["request_id"])
    assert c.operation(request["request_id"])["phase"] == "needs_inspection"
    assert actions.count(("systemctl", "stop", "canary.service")) == 1
    assert not r.MAINTENANCE.exists()


def test_candidate_restart_rejects_verification(host, monkeypatch):
    c, r, _, actions, state = host
    preview = plan(c, {"CANARY_RUNWARE_FIRST_ENABLED": "true"})
    monkeypatch.setattr(
        r, "wait_candidate", lambda *_: state.update(identity="replacement")
    )
    request = apply_request(preview)
    c.handle(request)
    c.worker(request["request_id"])
    assert c.operation(request["request_id"])["error"] == "candidate_restarted"
    assert ("/api/ops/resume",) not in actions
    assert r.MAINTENANCE.exists()


def test_hold_owner_diagnostic_and_unrelated_hold_protection(host):
    c, r, *_ = host
    op = str(uuid.uuid4())
    c.create_hold(op)
    with pytest.raises(RuntimeError, match="configuration_operation_active") as caught:
        r.configuration_conflict()
    assert getattr(caught.value, "operation_id") == op
    r.MAINTENANCE.unlink()
    r.MAINTENANCE.write_text("other")
    # New inode may be reused by the filesystem; force a mismatched ownership receipt.
    c.atomic(c.STATE / "hold.json", {"operation_id": op, "device": -1, "inode": -1})
    with pytest.raises(RuntimeError, match="maintenance_active"):
        c.remove_hold(op)


def test_real_signature_rejects_wrong_key_and_modified_manifest(
    host, monkeypatch, tmp_path
):
    c, r, config, *_ = host
    real = subprocess.run

    def run(args, **kwargs):
        return real(
            args, input=kwargs.get("data"), capture_output=True, check=True, timeout=5
        ).stdout

    monkeypatch.setattr(r, "run", run)
    key = tmp_path / "key"
    real(
        ["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(key)],
        check=True,
        capture_output=True,
    )
    signers = tmp_path / "allowed"
    signers.write_text("canary-config " + key.with_suffix(".pub").read_text())
    monkeypatch.setattr(c, "SIGNERS", signers)
    raw = b'{"ciphertext":"dummy"}'
    manifest = {
        "target": "production",
        "bundle_sha256": c.digest(raw),
        "replaces_bundle_sha256": config["CANARY_BUNDLE_SHA256"],
        "authorization_id": str(uuid.uuid4()),
        "expires_at": int(time.time()) + 60,
        "recovery_verification": True,
    }
    path = tmp_path / "manifest"
    path.write_bytes(c.canonical(manifest))
    real(
        [
            "ssh-keygen",
            "-Y",
            "sign",
            "-f",
            str(key),
            "-n",
            "canary-production-config",
            str(path),
        ],
        check=True,
        capture_output=True,
    )
    request = {
        "action": "config_stage_bundle",
        "bundle": base64.b64encode(raw).decode(),
        "manifest": manifest,
        "signature": base64.b64encode(Path(str(path) + ".sig").read_bytes()).decode(),
    }
    upload = c.handle(request)
    assert c.signed_bundle(upload["bundle_id"], config)[1] == manifest
    with pytest.raises(RuntimeError, match="signature_invalid"):
        c.handle(
            {**request, "manifest": {**manifest, "authorization_id": str(uuid.uuid4())}}
        )


def test_thin_router_auth_shapes_and_transport(monkeypatch):
    from novel_to_comic.server.routers import configuration as router_module

    monkeypatch.setenv("CANARY_OPS_TOKEN", "operator")
    calls = []
    monkeypatch.setattr(
        router_module,
        "forward",
        lambda value, **_: calls.append(value) or {"phase": "accepted"},
    )
    app = FastAPI()
    app.include_router(router_module.router, prefix="/config")
    client = TestClient(app)
    assert client.get("/config/status").status_code == 401
    headers = {"X-Canary-Ops-Token": "operator"}
    request = {"request_id": str(uuid.uuid4()), "patch": {}}
    assert (
        client.post(
            "/config/plan", json={**request, "transport": "ssh"}, headers=headers
        ).status_code
        == 422
    )
    assert client.post("/config/plan", json=request, headers=headers).status_code == 202
    assert calls[-1] == {"action": "config_plan", **request}
    assert (
        client.post(
            "/config/bundles", content=b"x" * (3 * 1024 * 1024 + 1), headers=headers
        ).status_code
        == 413
    )


@pytest.mark.parametrize(
    "when,code",
    [
        ("connect", "host_agent_unavailable"),
        ("sendall", "request_outcome_unknown"),
        ("readline", "request_outcome_unknown"),
    ],
)
def test_transport_distinguishes_not_sent_from_unknown(monkeypatch, when, code):
    from novel_to_comic.server import configuration as proxy

    class Fake:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def settimeout(self, *_):
            pass

        def connect(self, *_):
            if when == "connect":
                raise OSError("private-token")

        def sendall(self, *_):
            if when == "sendall":
                raise OSError("private-token")

        def makefile(self, *_):
            return self

        def readline(self, *_):
            raise TimeoutError("private-token")

    monkeypatch.setattr(proxy.socket, "socket", lambda *_: Fake())
    op = str(uuid.uuid4())
    with pytest.raises(HTTPException) as caught:
        proxy.forward({"action": "config_apply", "request_id": op})
    assert caught.value.detail == {
        "code": code,
        "request_id": op,
        "request_sent": False if when == "connect" else None,
    }
    assert "private-token" not in json.dumps(caught.value.detail)


def test_threaded_socket_keeps_events_responsive_during_slow_request(
    host, monkeypatch, tmp_path
):
    c, *_ = host
    h = load(ROOT / "deploy/lightsail/host_agent.py")
    monkeypatch.setattr(h, "_configuration", c)
    entered, unblock = threading.Event(), threading.Event()

    def handle(request):
        if request["action"] == "config_plan":
            entered.set()
            unblock.wait(2)
        return {"phase": "observed"}

    monkeypatch.setattr(c, "handle", handle)
    short = tempfile.TemporaryDirectory(prefix="cc-", dir="/tmp")
    path = Path(short.name) / "control.sock"
    server = h.BoundedServer(path)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    def request(action):
        with socket.socket(socket.AF_UNIX) as client:
            client.settimeout(1)
            client.connect(str(path))
            client.sendall(json.dumps({"action": action}).encode() + b"\n")
            return json.loads(client.makefile("rb").readline())

    slow = threading.Thread(target=request, args=("config_plan",), daemon=True)
    slow.start()
    try:
        assert entered.wait(1)
        assert request("config_events")["result"]["phase"] == "observed"
    finally:
        unblock.set()
        slow.join(2)
        server.shutdown()
        server.server_close()
        short.cleanup()


def test_cached_status_does_not_wait_for_live_probe_and_keeps_timestamps(
    host, monkeypatch
):
    c, _, _, _, _ = host
    entered, unblock = threading.Event(), threading.Event()
    count = []

    def slow(config, revision):
        count.append(1)
        entered.set()
        unblock.wait(2)
        return {"match": "match", "revision": revision, "observed_at": 123}

    monkeypatch.setattr(c, "observe", slow)
    started = time.monotonic()
    assert c.status()["observation"]["stale"] is True
    assert entered.wait(1)
    assert c.status()["observation"]["stale"] is True
    assert time.monotonic() - started < 1
    assert len(count) == 1
    unblock.set()
    deadline = time.monotonic() + 2
    while c.PROBE_LOCK.locked() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert c.status()["observation"]["observed_at"] == 123


def test_signed_bundle_is_checked_before_old_secrets_are_decrypted(host, monkeypatch):
    c, _, _, _, _ = host
    monkeypatch.setattr(
        c,
        "signed_bundle",
        lambda *_: (_ for _ in ()).throw(RuntimeError("signature_invalid")),
    )
    monkeypatch.setattr(
        c, "loader_context", lambda *_: pytest.fail("decrypted before signature")
    )
    request = {
        "action": "config_plan",
        "request_id": str(uuid.uuid4()),
        "bundle_id": str(uuid.uuid4()),
        "patch": {},
    }
    c.handle(request)
    c.worker(request["request_id"])
    assert c.operation(request["request_id"])["error"] == "signature_invalid"


def test_candidate_token_rotation_is_rejected_from_socket(host, monkeypatch, tmp_path):
    c, _, _, _, _ = host
    old = {"env": {"CANARY_OPS_TOKEN": "old"}, "files": {}}
    new = {"env": {"CANARY_OPS_TOKEN": "new"}, "files": {}}
    loader = SimpleNamespace(
        ciphertext_recipients=lambda _: {"host", "recovery"}, decrypt=lambda *_: new
    )
    monkeypatch.setattr(c, "loader_context", lambda *_: (loader, old))
    upload = tmp_path / "upload"
    upload.mkdir()
    (upload / "bundle.sops.json").write_text("{}")
    monkeypatch.setattr(
        c, "signed_bundle", lambda *_: (upload, {"bundle_sha256": "d" * 64})
    )
    request = {
        "action": "config_plan",
        "request_id": str(uuid.uuid4()),
        "bundle_id": str(uuid.uuid4()),
        "patch": {},
    }
    c.handle(request)
    c.worker(request["request_id"])
    assert c.operation(request["request_id"])["error"] == "ops_token_rotation_ssh_only"


def test_config_upload_has_specific_preparser_limit():
    from novel_to_comic.server.body_limit import _body_cap_bytes

    assert (
        _body_cap_bytes("/api/ops/backoffice/config/bundles", "POST") == 3 * 1024 * 1024
    )
    assert _body_cap_bytes("/api/ops/backoffice/config/plan", "POST") == 2 * 1024 * 1024


def test_allowlisted_codes_remain_aligned_and_journal_never_corrupts_ssh_stdout(
    host, capsys
):
    from novel_to_comic.server.configuration import CODES

    c, *_ = host
    assert c.CODES <= CODES
    plan(c)
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "operation_id" in captured.err


def test_cli_uses_pinned_forced_command_and_reports_known_rejections(monkeypatch):
    cli = load(ROOT / "scripts/canary_config.py")
    calls = []

    def run(args, **kwargs):
        calls.append((args, kwargs))
        return SimpleNamespace(
            stdout=b'{"ok":false,"code":"rejected_busy"}', returncode=1
        )

    monkeypatch.setattr(cli.subprocess, "run", run)
    with pytest.raises(cli.Rejected, match="rejected_busy"):
        cli.send(
            {"action": "config_status"},
            {
                "identity": "/private/key",
                "known_hosts": "/private/pins",
                "destination": "canary-config@host",
            },
        )
    args, kwargs = calls[0]
    assert args[-1] == "canary-config@host"
    assert "StrictHostKeyChecking=yes" in args
    assert json.loads(kwargs["input"]) == {"action": "config_status"}


def test_exhausted_control_slots_reject_without_spawning_threads():
    h = load(ROOT / "deploy/lightsail/host_agent.py")
    server = object.__new__(h.BoundedServer)
    server.slots = SimpleNamespace(acquire=lambda **_: False)
    closed, replies = [], []
    server.shutdown_request = closed.append
    peer = SimpleNamespace(settimeout=lambda _: None, sendall=replies.append)
    server.process_request(peer, None)
    assert json.loads(replies[0]) == {"ok": False, "code": "rejected_busy"}
    assert closed == [peer]


def test_cli_watch_catches_up_all_batches_before_returning_completed(monkeypatch):
    cli = load(ROOT / "scripts/canary_config.py")

    def send(request, _settings):
        if request["action"] == "config_status":
            return {"operation": {"phase": "complete", "seq": 101}}
        after = request["after"]
        return {
            "events": [
                {"seq": seq} for seq in range(after + 1, min(after + 100, 101) + 1)
            ],
            "after": min(after + 100, 101),
        }

    monkeypatch.setattr(cli, "send", send)
    monkeypatch.setattr(
        cli.time, "sleep", lambda _: pytest.fail("unnecessary catch-up delay")
    )
    output = []
    assert cli.watch("id", {}, emit=output.append) == 0
    assert len(output) == 102  # Every event, then the final operation receipt.
    assert json.loads(output[-2])["seq"] == 101
