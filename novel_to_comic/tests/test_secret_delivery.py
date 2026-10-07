"""No real account credentials: tests use only generated keys and sentinel data."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/canary_secrets.py"
spec = importlib.util.spec_from_file_location("canary_secrets", SCRIPT)
secrets = importlib.util.module_from_spec(spec)
spec.loader.exec_module(secrets)
SENTINEL = 'dummy-secret-$HOME-$(id)-`whoami`-"quote"\nsecond-line'


@pytest.fixture
def bundle():
    return {"version": 1, "env": {k: SENTINEL for k in secrets.REQUIRED}, "files": {}}


def private_file(path, value):
    path.write_text(value)
    path.chmod(0o600)
    return path


def fake_proc(root, processes):
    """A /proc stand-in: {pid: (argv, env)}; argv/env are NUL-joined like the kernel's."""
    for pid, (argv, env) in processes.items():
        folder = root / str(pid)
        folder.mkdir(parents=True)
        (folder / "cmdline").write_bytes(b"\0".join(a.encode() for a in argv) + b"\0")
        (folder / "environ").write_bytes(
            b"\0".join(f"{k}={v}".encode() for k, v in env.items()) + b"\0")
    return root


def supervisor_proc(root, env):
    return fake_proc(root, {
        40: (["/bin/bash", "/app/entrypoint.sh"], env),
        41: (["/bin/bash", "/app/entrypoint.sh"], {"PATH": "/usr/bin"}),  # transient subshell
        7: (["sshd"], {}),
    })


@pytest.fixture
def memory_only(monkeypatch):
    monkeypatch.setattr(secrets, "require_tmpfs", lambda _: None)
    monkeypatch.setattr(secrets, "require_no_swap", lambda _: None)


@pytest.mark.parametrize("change,code", [
    (lambda b: b.update(version=True), "unsupported_version"),
    (lambda b: b.update(version=2), "unsupported_version"),
    (lambda b: b.update(unknown=SENTINEL), "invalid_schema"),
    (lambda b: b["env"].pop("CANARY_OPS_TOKEN"), "invalid_secret_names"),
    (lambda b: b["env"].update(LD_PRELOAD=SENTINEL), "invalid_secret_names"),
    (lambda b: b["env"].update(AWS_ACCESS_KEY_ID=SENTINEL), "invalid_secret_names"),
    (lambda b: b["env"].update(LITELLM_API_KEY="mismatch"), "gateway_key_mismatch"),
    (lambda b: b["env"].update(OPENAI_API_KEY="\0"), "invalid_secret_value"),
    (lambda b: b["env"].update(OPENAI_API_KEY=None), "invalid_secret_value"),
    (lambda b: b["env"].update(R2_ACCESS_KEY=SENTINEL), "incomplete_r2_pair"),
    (lambda b: b["files"].update({"../../escape": SENTINEL}), "invalid_file_names"),
    (lambda b: b["files"].update({"google-adc.json": SENTINEL}), "invalid_json"),
])
def test_bundle_fails_closed_without_values(bundle, change, code):
    change(bundle)
    with pytest.raises(secrets.SecretError, match=code) as error:
        secrets.validate(bundle)
    assert SENTINEL not in str(error.value)


def test_duplicate_keys_and_malformed_json_do_not_echo_values():
    for raw, code in [(b'{"x":1,"x":2}', "duplicate_field"),
                      (SENTINEL, "invalid_json")]:
        with pytest.raises(secrets.SecretError, match=code):
            secrets.parse(raw)


def test_loader_preserves_values_and_removes_ambient_secrets(tmp_path, bundle, monkeypatch):
    path = private_file(tmp_path / "runtime.json", json.dumps(bundle))
    monkeypatch.setenv("OPENAI_API_KEY", "stale")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "administrator")
    monkeypatch.setenv("CANARY_ENV", "production")
    env = secrets.child_environment(path)
    assert env["CANARY_OPS_TOKEN"] == SENTINEL
    assert env["CANARY_ENV"] == "production"
    assert "OPENAI_API_KEY" not in env
    assert "AWS_ACCESS_KEY_ID" not in env


def test_loader_refuses_readable_or_symlink_files(tmp_path, bundle):
    path = private_file(tmp_path / "runtime.json", json.dumps(bundle))
    path.chmod(0o644)
    with pytest.raises(secrets.SecretError, match="unsafe_file_permissions"):
        secrets.child_environment(path)
    path.chmod(0o600)
    link = tmp_path / "link"
    link.symlink_to(path)
    with pytest.raises(OSError):
        secrets.child_environment(link)


def test_required_bundle_fails_without_starting(monkeypatch, capsys):
    monkeypatch.delenv("CANARY_SECRETS_FILE", raising=False)
    monkeypatch.setenv("CANARY_SECRET_BUNDLE_REQUIRED", "1")
    assert secrets.main(["run"]) == 2
    assert capsys.readouterr().err == "canary-secrets: bundle_required\n"


@pytest.mark.parametrize("pinned", [None, "0" * 64, "not-a-digest"])
def test_required_bundle_rejects_unreviewed_loader(tmp_path, bundle, monkeypatch, capsys, pinned):
    path = private_file(tmp_path / "runtime.json", json.dumps(bundle))
    monkeypatch.setenv("CANARY_SECRETS_FILE", str(path))
    monkeypatch.setenv("CANARY_SECRET_BUNDLE_REQUIRED", "1")
    monkeypatch.delenv("CANARY_LOADER_SHA256", raising=False)
    if pinned:
        monkeypatch.setenv("CANARY_LOADER_SHA256", pinned)
    monkeypatch.setattr(os, "execve", lambda *args: pytest.fail("must not start"))
    assert secrets.main(["run"]) == 2
    assert capsys.readouterr().err == "canary-secrets: loader_digest_mismatch\n"


def test_required_bundle_starts_with_pinned_loader(tmp_path, bundle, monkeypatch, capsys):
    path = private_file(tmp_path / "runtime.json", json.dumps(bundle))
    assert secrets.main(["digest"]) == 0
    digest = json.loads(capsys.readouterr().out)["loader_sha256"]
    monkeypatch.setenv("CANARY_SECRETS_FILE", str(path))
    monkeypatch.setenv("CANARY_SECRET_BUNDLE_REQUIRED", "1")
    monkeypatch.setenv("CANARY_LOADER_SHA256", digest)
    calls = []
    monkeypatch.setattr(os, "execve", lambda *args: calls.append(args))
    assert secrets.main(["run"]) == 0
    assert calls[0][2]["CANARY_OPS_TOKEN"] == SENTINEL


def test_existing_fly_startup_keeps_environment(monkeypatch):
    monkeypatch.delenv("CANARY_SECRETS_FILE", raising=False)
    monkeypatch.delenv("CANARY_SECRET_BUNDLE_REQUIRED", raising=False)
    monkeypatch.setenv("LITELLM_API_KEY", SENTINEL)
    calls = []
    monkeypatch.setattr(os, "execve", lambda *args: calls.append(args))
    assert secrets.main(["run"]) == 0
    assert calls[0][0] == "/app/entrypoint.sh"
    assert calls[0][2]["LITELLM_API_KEY"] == SENTINEL


def test_adc_missing_or_wrong_path_fails(tmp_path, bundle, monkeypatch):
    path = private_file(tmp_path / "runtime.json", json.dumps(bundle))
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", "/wrong/path")
    with pytest.raises(secrets.SecretError, match="invalid_adc_path"):
        secrets.child_environment(path)
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", secrets.ADC_PATH)
    with pytest.raises(OSError):
        secrets.child_environment(path)


def test_materialize_is_private_idempotent_and_detects_tampering(tmp_path, bundle, memory_only):
    adc = {"type": "authorized_user", "client_id": "dummy", "client_secret": SENTINEL,
           "refresh_token": SENTINEL}
    bundle["files"][secrets.ADC_NAME] = json.dumps(adc)
    target = secrets.materialize(bundle, tmp_path, "a" * 64)
    assert target.stat().st_mode & 0o777 == 0o700
    assert (target / "runtime.json").stat().st_mode & 0o777 == 0o600
    assert json.loads((target / "runtime.json").read_text())["files"] == {}
    assert json.loads((target / "credentials" / secrets.ADC_NAME).read_text()) == adc
    assert secrets.materialize(bundle, tmp_path, "a" * 64) == target
    (target / "runtime.json").write_text('{"tampered":true}')
    with pytest.raises(secrets.SecretError, match="runtime_version_mismatch"):
        secrets.materialize(bundle, tmp_path, "a" * 64)


def test_materialize_failure_cleans_staging(tmp_path, bundle, monkeypatch, memory_only):
    def fail(*args):
        raise OSError(SENTINEL)
    monkeypatch.setattr(secrets, "write_private", fail)
    with pytest.raises(OSError):
        secrets.materialize(bundle, tmp_path, "a" * 64)
    assert list(tmp_path.iterdir()) == []


def test_swap_must_be_absent_or_attested_encrypted(tmp_path):
    swaps = tmp_path / "swaps"
    swaps.write_text("Filename\tType\tSize\tUsed\tPriority\n/swapfile file 1048572 0 -2\n")
    with pytest.raises(secrets.SecretError, match="swap_enabled"):
        secrets.require_no_swap(False, swaps)
    secrets.require_no_swap(True, swaps)
    swaps.write_text("Filename\tType\tSize\tUsed\tPriority\n")
    secrets.require_no_swap(False, swaps)


def test_export_reads_the_running_supervisor_not_the_ssh_session(tmp_path, bundle, monkeypatch):
    proc = supervisor_proc(tmp_path / "proc", {**bundle["env"], "PATH": "/usr/bin"})
    for name in bundle["env"]:
        monkeypatch.setenv(name, "stale-ssh-session-value")
    assert secrets.export_active(sorted(secrets.REQUIRED), False, proc) == bundle
    with pytest.raises(secrets.SecretError, match="invalid_export_names"):
        secrets.export_active(sorted(secrets.REQUIRED) + ["PATH"], False, proc)
    with pytest.raises(secrets.SecretError, match="runtime_process_not_found"):
        secrets.export_active(sorted(secrets.REQUIRED), False,
                              fake_proc(tmp_path / "empty", {9: (["sshd"], {})}))


def test_export_fails_for_missing_runtime_credentials(tmp_path, bundle):
    env = dict(bundle["env"])
    del env["CANARY_OPS_TOKEN"]
    proc = supervisor_proc(tmp_path / "proc", env)
    with pytest.raises(secrets.SecretError, match="invalid_secret_value"):
        secrets.export_active(sorted(secrets.REQUIRED), False, proc)


def test_subprocess_failure_never_relays_output(capsys):
    with pytest.raises(secrets.SecretError, match="subprocess_failed"):
        secrets.checked_process([sys.executable, "-c",
            "import sys;print(sys.stdin.read(),file=sys.stderr);sys.exit(1)"], data=SENTINEL.encode())
    assert not capsys.readouterr().err


def test_cli_os_errors_are_redacted(tmp_path, capsys):
    assert secrets.main(["encrypt-file", "--input", str(tmp_path / "missing"),
                         "--recipient", "invalid", "--output", str(tmp_path / "out")]) == 2
    assert capsys.readouterr().err == "canary-secrets: operation_failed\n"


@pytest.fixture
def crypto(tmp_path, monkeypatch):
    if not shutil.which("sops") or not shutil.which("age-keygen"):
        pytest.skip("Install sops and age-keygen for real encryption coverage")
    # Package-manager installs (e.g. Homebrew's group-writable Cellar) fail the
    # tool trust check by design; run private copies, inherited by subprocesses.
    trusted_bin = tmp_path / "trusted-bin"
    trusted_bin.mkdir()
    for tool in ("sops", "age-keygen"):
        shutil.copy2(Path(shutil.which(tool)).resolve(), trusted_bin / tool)
    monkeypatch.setenv("PATH", f"{trusted_bin}{os.pathsep}{os.environ['PATH']}")
    keys, recipients = [], []
    for name in ("host", "recovery", "stranger"):
        key = tmp_path / name
        subprocess.run(["age-keygen", "-o", str(key)], capture_output=True, check=True)
        recipient = subprocess.run(["age-keygen", "-y", str(key)], capture_output=True,
                                   text=True, check=True).stdout.strip()
        key.chmod(0o600)
        keys.append(key)
        recipients.append(recipient)
    return keys, recipients


def test_real_encryption_host_and_recovery_and_wrong_key(tmp_path, bundle, crypto):
    keys, recipients = crypto
    out = tmp_path / "app.sops.json"
    digest = secrets.encrypt_export(json.dumps(bundle).encode(), recipients[:2], out)
    assert SENTINEL.encode() not in out.read_bytes()
    assert secrets.decrypt(out, keys[0], digest) == bundle
    assert secrets.decrypt(out, keys[1], digest) == bundle
    with pytest.raises(secrets.SecretError, match="subprocess_failed"):
        secrets.decrypt(out, keys[2], digest)
    with pytest.raises(secrets.SecretError, match="ciphertext_digest_mismatch"):
        secrets.decrypt(out, keys[0], "0" * 64)
    before = out.read_bytes()
    with pytest.raises(FileExistsError):
        secrets.encrypt_export(json.dumps(bundle).encode(), recipients[:2], out)
    assert out.read_bytes() == before


def test_partial_export_is_not_encrypted(tmp_path, bundle, crypto):
    _, recipients = crypto
    output = tmp_path / "app.sops.json"
    with pytest.raises(secrets.SecretError, match="invalid_json"):
        secrets.encrypt_export(json.dumps(bundle).encode()[:-2], recipients[:2], output)
    assert not output.exists()


def test_export_requires_two_recipients(tmp_path, bundle, crypto):
    _, recipients = crypto
    with pytest.raises(secrets.SecretError, match="host_and_recovery_recipients_required"):
        secrets.encrypt_export(json.dumps(bundle).encode(), [recipients[0]] * 2, tmp_path / "out")


def test_fly_export_protocol_encrypts_without_capturing_plaintext_output(tmp_path, bundle, crypto, monkeypatch, capsys):
    keys, recipients = crypto
    # Stand-in SSH client executes the exact embedded exporter in a child.
    # It reads a stand-in /proc, as the real Machine's supervisor would be read.
    proc = supervisor_proc(tmp_path / "proc", bundle["env"])
    fly = tmp_path / "fly"
    fly.write_text('#!' + sys.executable + '\nimport shlex,subprocess,sys\n'
                   'argv = shlex.split(sys.argv[sys.argv.index("--command")+1])\n'
                   f'sys.exit(subprocess.call(argv + ["--proc-root", {str(proc)!r}]))\n')
    fly.chmod(0o700)
    monkeypatch.setenv("PATH", str(tmp_path) + os.pathsep + os.environ["PATH"])
    out = tmp_path / "migrated.sops.json"
    assert secrets.main(["export-fly", "--app", "dummy", "--machine", "dummy",
                         "--names", ",".join(sorted(secrets.REQUIRED)),
                         "--recipient", recipients[0], "--recipient", recipients[1],
                         "--output", str(out)]) == 0
    captured = capsys.readouterr()
    assert not captured.err
    assert SENTINEL not in captured.out
    digest = json.loads(captured.out)["sha256"]
    assert secrets.decrypt(out, keys[1], digest) == bundle


def test_failed_fly_export_leaves_no_bundle(tmp_path, bundle, crypto, monkeypatch, capsys):
    _, recipients = crypto
    fly = tmp_path / "fly"
    fly.write_text('#!' + sys.executable + '\nimport sys\nprint("partial-secret")\nsys.exit(1)\n')
    fly.chmod(0o700)
    monkeypatch.setenv("PATH", str(tmp_path) + os.pathsep + os.environ["PATH"])
    out = tmp_path / "failed.sops.json"
    assert secrets.main(["export-fly", "--app", "dummy", "--machine", "dummy",
                         "--names", ",".join(sorted(secrets.REQUIRED)),
                         "--recipient", recipients[0], "--recipient", recipients[1],
                         "--output", str(out)]) == 2
    captured = capsys.readouterr()
    assert not captured.out
    assert captured.err == "canary-secrets: subprocess_failed\n"
    assert not out.exists()


def test_identity_creation_prints_only_public_recipient(tmp_path, crypto, capsys):
    folder = tmp_path / "private"
    folder.mkdir(mode=0o700)
    key = folder / "new-host"
    assert secrets.main(["create-identity", "--output", str(key)]) == 0
    captured = capsys.readouterr()
    assert not captured.err
    assert "AGE-SECRET-KEY" not in captured.out
    assert json.loads(captured.out)["recipient"].startswith("age1")
    assert key.stat().st_mode & 0o777 == 0o600
    before = key.read_bytes()
    assert secrets.main(["create-identity", "--output", str(key)]) == 2
    assert key.read_bytes() == before


def test_ciphertext_publication_is_exclusive_and_cleans_temporary_files(tmp_path):
    output = tmp_path / "bundle"
    secrets.publish_ciphertext(output, b"ciphertext")
    assert output.stat().st_mode & 0o777 == 0o600
    with pytest.raises(FileExistsError):
        secrets.publish_ciphertext(output, b"replacement")
    assert output.read_bytes() == b"ciphertext"
    assert list(tmp_path.iterdir()) == [output]


def test_encryption_ignores_ambient_sops_settings(tmp_path, bundle, crypto, monkeypatch):
    keys, recipients = crypto
    # A stray recipient variable and a permissive .sops.yaml must not take effect.
    monkeypatch.setenv("SOPS_AGE_RECIPIENTS", recipients[2])
    (tmp_path / ".sops.yaml").write_text('creation_rules:\n  - unencrypted_regex: ".*"\n')
    monkeypatch.chdir(tmp_path)
    out = tmp_path / "app.sops.json"
    digest = secrets.encrypt_export(json.dumps(bundle).encode(), recipients[:2], out)
    assert SENTINEL.encode() not in out.read_bytes()
    assert secrets.ciphertext_recipients(json.loads(out.read_bytes())) == set(recipients[:2])
    with pytest.raises(secrets.SecretError, match="subprocess_failed"):
        secrets.decrypt(out, keys[2], digest)


@pytest.mark.parametrize("extra", [
    {"kms": [{"arn": "arn:aws:kms:us-east-1:1:key/x"}]},
    {"pgp": [{"fp": "ABCD"}]},
    {"hc_vault": [{"vault_address": "https://vault"}]},
    {"key_groups": [{"age": []}]},
    {"age": [{"recipient": "age1" + "q" * 58}, {"recipient": "age1" + "q" * 58}]},
    {"age": "not-a-list"},
])
def test_unexpected_ciphertext_decryptors_are_rejected(extra):
    meta = {"age": [{"recipient": "age1" + "q" * 58}], **extra}
    with pytest.raises(secrets.SecretError, match="unexpected_ciphertext_recipients|invalid_ciphertext"):
        secrets.ciphertext_recipients({"sops": meta})


def test_encryption_rejects_output_for_other_recipients(tmp_path, bundle, crypto, monkeypatch):
    _, recipients = crypto
    real = secrets.checked_process
    def add_foreign_key(argv, **kwargs):
        stored = json.loads(real(argv, **kwargs))
        stored["sops"]["kms"] = [{"arn": "arn:aws:kms:us-east-1:1:key/attacker"}]
        return json.dumps(stored).encode()
    monkeypatch.setattr(secrets, "checked_process", add_foreign_key)
    out = tmp_path / "app.sops.json"
    with pytest.raises(secrets.SecretError, match="unexpected_ciphertext_recipients"):
        secrets.encrypt_export(json.dumps(bundle).encode(), recipients[:2], out)
    assert not out.exists()


def test_plaintext_tools_must_not_be_replaceable_by_others(tmp_path, monkeypatch):
    shared = tmp_path / "shared"
    shared.mkdir()
    tool = shared / "sops"
    tool.write_text("#!/bin/sh\n")
    tool.chmod(0o755)
    shared.chmod(0o777)
    monkeypatch.setenv("PATH", str(shared))
    with pytest.raises(secrets.SecretError, match="untrusted_tool"):
        secrets.trusted_tool("sops")
    shared.chmod(0o755)
    tool.chmod(0o775)
    with pytest.raises(secrets.SecretError, match="untrusted_tool"):
        secrets.trusted_tool("sops")
    tool.chmod(0o755)
    assert secrets.trusted_tool("sops") == str(tool.resolve())
    monkeypatch.setenv("PATH", str(tmp_path / "missing"))
    with pytest.raises(secrets.SecretError, match="tool_missing"):
        secrets.trusted_tool("sops")


def test_plaintext_tools_reject_writable_ancestors(tmp_path, monkeypatch):
    # A safe tool and parent are not enough if any higher directory lets
    # another user replace the subtree.
    shared = tmp_path / "shared"
    bindir = shared / "pkg" / "bin"
    bindir.mkdir(parents=True)
    tool = bindir / "sops"
    tool.write_text("#!/bin/sh\n")
    tool.chmod(0o755)
    monkeypatch.setenv("PATH", str(bindir))
    shared.chmod(0o777)
    try:
        with pytest.raises(secrets.SecretError, match="untrusted_tool"):
            secrets.trusted_tool("sops")
        # Sticky shared directories cannot have our entries renamed by others.
        shared.chmod(0o1777)
        assert secrets.trusted_tool("sops") == str(tool.resolve())
    finally:
        shared.chmod(0o755)


def test_fal_admin_key_is_an_optional_gateway_secret(bundle):
    assert "FAL_ADMIN_KEY" in secrets.OPTIONAL
    bundle["env"]["FAL_ADMIN_KEY"] = "admin"
    assert secrets.validate(bundle) is bundle


@pytest.mark.parametrize("platform,uid,opt_in,prefix,changed,mode,owner,gid,accepted", [
    ("darwin", 501, "1", "/opt/homebrew", "Cellar", 0o775, 501, 80, True),
    ("darwin", 501, "1", "/usr/local", "Cellar", 0o775, 501, 80, True),
    ("darwin", 501, "", "/opt/homebrew", "Cellar", 0o775, 501, 80, False),
    ("linux", 501, "1", "/opt/homebrew", "Cellar", 0o775, 501, 80, False),
    ("darwin", 0, "1", "/opt/homebrew", "Cellar", 0o775, 0, 80, False),
    ("darwin", 501, "1", "/opt/homebrew", "Cellar", 0o777, 501, 80, False),
    ("darwin", 501, "1", "/opt/homebrew", "Cellar", 0o775, 502, 80, False),
    ("darwin", 501, "1", "/opt/homebrew", "Cellar", 0o775, 501, 20, False),
    ("darwin", 501, "1", "/opt/homebrew", "binary", 0o775, 501, 80, False),
    ("darwin", 501, "1", "/opt/homebrew", "/opt", 0o775, 501, 80, False),
    ("darwin", 501, "1", "/somewhere", "Cellar", 0o775, 501, 80, False),
])
def test_homebrew_exception_stays_local_and_narrow(monkeypatch, platform, uid, opt_in,
                                                   prefix, changed, mode, owner, gid, accepted):
    path = Path(prefix) / "Cellar/sops/test/bin/sops"
    changed_path = path if changed == "binary" else Path(prefix) / changed
    monkeypatch.setenv("CANARY_ALLOW_HOMEBREW_TOOLS", opt_in)
    monkeypatch.setattr(secrets.sys, "platform", platform)
    monkeypatch.setattr(secrets.os, "geteuid", lambda: uid)
    monkeypatch.setattr(secrets.grp, "getgrnam", lambda _: SimpleNamespace(gr_gid=80))
    monkeypatch.setattr(secrets.shutil, "which", lambda _: str(path))
    monkeypatch.setattr(Path, "resolve", lambda self: self)

    def file_stat(item):
        kind = stat.S_IFREG if item == path else stat.S_IFDIR
        if item == changed_path:
            return SimpleNamespace(st_uid=owner, st_gid=gid, st_mode=kind | mode)
        return SimpleNamespace(st_uid=0, st_gid=0, st_mode=kind | 0o755)

    monkeypatch.setattr(Path, "stat", file_stat)
    if accepted:
        assert secrets.trusted_tool("sops") == str(path)
    else:
        with pytest.raises(secrets.SecretError, match="untrusted_tool"):
            secrets.trusted_tool("sops")


def test_local_homebrew_opt_in_is_not_forwarded_to_tools(monkeypatch):
    monkeypatch.setenv("CANARY_ALLOW_HOMEBREW_TOOLS", "1")
    assert "CANARY_ALLOW_HOMEBREW_TOOLS" not in secrets.tool_env()


def test_change_values_mirrors_gateway_key_and_keeps_schema(bundle):
    changed = secrets.change_values(bundle, {"LITELLM_MASTER_KEY": "rotated"})
    assert changed["env"]["LITELLM_MASTER_KEY"] == changed["env"]["LITELLM_API_KEY"] == "rotated"
    assert bundle["env"]["LITELLM_MASTER_KEY"] == SENTINEL  # Input is not mutated.
    added = secrets.change_values(bundle, {"OPENAI_API_KEY": SENTINEL})
    assert secrets.change_values(added, {"OPENAI_API_KEY": None}) == bundle
    for changes, code in [({"CANARY_OPS_TOKEN": None}, "invalid_secret_names"),
                          ({"OPENAI_API_KEY": None}, "name_not_present"),
                          ({"PATH": "x"}, "invalid_secret_names"),
                          ({"R2_ACCESS_KEY": "x"}, "incomplete_r2_pair"),
                          ({secrets.ADC_NAME: SENTINEL}, "invalid_json")]:
        with pytest.raises(secrets.SecretError, match=code):
            secrets.change_values(bundle, changes)


def test_set_rotates_one_value_without_plaintext_files(tmp_path, bundle, crypto, monkeypatch, capsys):
    keys, recipients = crypto
    original = tmp_path / "v1.sops.json"
    digest = secrets.encrypt_export(json.dumps(bundle).encode(), recipients[:2], original)
    monkeypatch.setattr(sys, "stdin", type("Pipe", (), {
        "isatty": staticmethod(lambda: False),
        "buffer": __import__("io").BytesIO(b"new-" + SENTINEL.encode() + b"\n")})())
    out = tmp_path / "v2.sops.json"
    assert secrets.main(["set", "--bundle", str(original), "--identity", str(keys[1]),
                         "--sha256", digest, "--name", "STRIPE_SECRET_KEY",
                         "--recipient", recipients[0], "--recipient", recipients[1],
                         "--output", str(out)]) == 0
    captured = capsys.readouterr()
    assert SENTINEL not in captured.out + captured.err
    result = json.loads(captured.out)
    assert result["changed"] == ["STRIPE_SECRET_KEY"]
    updated = secrets.decrypt(out, keys[0], result["sha256"])
    assert updated["env"]["STRIPE_SECRET_KEY"] == "new-" + SENTINEL
    assert {k: v for k, v in updated["env"].items() if k != "STRIPE_SECRET_KEY"} == \
        {k: v for k, v in bundle["env"].items() if k != "STRIPE_SECRET_KEY"}
    assert sorted(p.name for p in tmp_path.iterdir() if p.is_file()) == \
        sorted(["host", "recovery", "stranger", "v1.sops.json", "v2.sops.json"])


def test_set_refuses_silent_recipient_change(tmp_path, bundle, crypto):
    keys, recipients = crypto
    original = tmp_path / "v1.sops.json"
    digest = secrets.encrypt_export(json.dumps(bundle).encode(), recipients[:2], original)
    with pytest.raises(secrets.SecretError, match="recipient_change_requires_flag"):
        secrets.update_bundle(original, keys[0], digest, {"OPENAI_API_KEY": "x"},
                              [recipients[0], recipients[2]], tmp_path / "v2", False)
    digest2 = secrets.update_bundle(original, keys[0], digest, {"OPENAI_API_KEY": "x"},
                                    [recipients[0], recipients[2]], tmp_path / "v2", True)
    assert secrets.decrypt(tmp_path / "v2", keys[2], digest2)["env"]["OPENAI_API_KEY"] == "x"
    with pytest.raises(secrets.SecretError, match="subprocess_failed"):
        secrets.decrypt(tmp_path / "v2", keys[1], digest2)


def test_prune_removes_only_unmounted_plaintext(tmp_path, monkeypatch):
    monkeypatch.setattr(secrets, "require_tmpfs", lambda _: None)
    root = tmp_path / "secrets"
    root.mkdir()
    live, stale, current = "a" * 64, "b" * 64, "c" * 64
    for name in (live, stale, current, ".prepare-x"):
        (root / name / "credentials").mkdir(parents=True)
        private_file(root / name / "runtime.json", SENTINEL)
    (root / "unrelated").mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (root / ("d" * 64)).symlink_to(outside)
    proc = tmp_path / "proc"
    (proc / "900").mkdir(parents=True)
    (proc / "900" / "mountinfo").write_text(
        f"612 590 0:25 /canary/secrets/{live}/runtime.json /run/secrets/runtime.json ro - tmpfs tmpfs rw\n"
        f"613 590 0:25 /canary/secrets/{live}/credentials /run/credentials ro - tmpfs tmpfs rw\n")
    assert secrets.prune(root, current, proc) == [".prepare-x", stale]
    assert sorted(p.name for p in root.iterdir()) == sorted([live, current, "d" * 64, "unrelated"])
    assert outside.exists()
    assert secrets.prune(root, None, proc) == [current]


def test_textract_scoped_credentials_require_a_complete_pair(bundle):
    bundle["env"]["CANARY_TEXTRACT_ACCESS_KEY_ID"] = SENTINEL
    with pytest.raises(secrets.SecretError, match="incomplete_textract_pair"):
        secrets.validate(bundle)
    bundle["env"]["CANARY_TEXTRACT_SECRET_ACCESS_KEY"] = SENTINEL
    bundle["env"]["CANARY_TEXTRACT_SESSION_TOKEN"] = SENTINEL
    secrets.validate(bundle)
