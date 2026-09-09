from __future__ import annotations

import asyncio
import importlib.metadata
import importlib.util
import json
import os
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
SECRET = "diagnostic-test-secret-never-report"
EMAIL = "private-account@example.test"


class FakeChatgptAccount:
    type = "chatgpt"
    email = EMAIL


class MetadataClient:
    def __init__(self, account):
        self.account_root = account
        self.catalog = SimpleNamespace(data=[], next_cursor=None)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def account(self, *, refresh_token):
        assert refresh_token is False, "Diagnostic must not request token refresh"
        return SimpleNamespace(account=SimpleNamespace(root=self.account_root))

    async def models(self, *, include_hidden):
        if not isinstance(self.account_root, FakeChatgptAccount):
            pytest.fail("Non-ChatGPT identity reached model listing")
        return self.catalog

    def __getattr__(self, name):
        pytest.fail(f"Diagnostic attempted non-metadata SDK operation: {name}")


@pytest.fixture
def diagnostic(monkeypatch):
    path = REPO_ROOT / "scripts" / "codex_dev_diagnostic.py"
    spec = importlib.util.spec_from_file_location("codex_dev_diagnostic", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)

    def forbidden(*args, **kwargs):
        pytest.fail("Diagnostic attempted an unapproved process or SDK operation")

    # Guard imports as well as execution; no installed SDK or real process is used.
    monkeypatch.setattr("subprocess.Popen", forbidden)
    sdk = ModuleType("openai_codex")
    sdk.AsyncCodex = lambda: MetadataClient(FakeChatgptAccount())
    generated = ModuleType("openai_codex.generated")
    schema = ModuleType("openai_codex.generated.v2_all")
    schema.ChatgptAccount = FakeChatgptAccount
    schema.ImageGenerationThreadItem = SimpleNamespace(
        model_fields={"type": None, "status": None, "result": None}
    )
    monkeypatch.setitem(sys.modules, "openai_codex", sdk)
    monkeypatch.setitem(sys.modules, "openai_codex.generated", generated)
    monkeypatch.setitem(sys.modules, "openai_codex.generated.v2_all", schema)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def fake_runtime(diagnostic, monkeypatch):
    monkeypatch.setattr(importlib.metadata, "version", lambda name: "0.147.0")
    monkeypatch.setattr(diagnostic.shutil, "which", lambda name: "/fake/codex")
    commands = []
    environments = []

    class Process:
        pid = 2147483647
        returncode = 0

        def __init__(self, command, **kwargs):
            commands.append(tuple(command))
            environments.append(dict(kwargs["env"]))
            if tuple(command[1:]) == ("--version",):
                payload = "codex-cli 0.153.4\n"
            elif tuple(command[1:]) == (
                "-I", str(REPO_ROOT / "scripts" / "codex_dev_diagnostic.py"),
                "--local-schema-child",
            ):
                payload = json.dumps({"image_event_fields": ["type", "status", "result"]})
            elif tuple(command[1:]) == (
                "-I", str(REPO_ROOT / "scripts" / "codex_dev_diagnostic.py"),
                "--sdk-metadata-child",
            ):
                payload = json.dumps({
                    "account_status": "observed", "account_mode": "chatgpt",
                    "models_status": "observed", "catalog": [],
                    "next_cursor_present": True, "catalog_complete": False,
                })
            elif len(command) == 5 and tuple(command[1:4]) == (
                "-I", str(REPO_ROOT / "scripts" / "codex_dev_diagnostic.py"),
                "--local-auth-child",
            ):
                assert command[4] == "/fake/codex"
                payload = json.dumps({"status": "observed", "mode": "chatgpt"})
            else:
                pytest.fail(f"Non-metadata runtime operation attempted: {command!r}")
            kwargs["stdout"].write(payload.encode())

        def wait(self, timeout=None):
            return self.returncode

    def kill_fake_group(pid, sig):
        assert pid == Process.pid

    monkeypatch.setattr(diagnostic.subprocess, "Popen", Process)
    monkeypatch.setattr(diagnostic.os, "killpg", kill_fake_group)
    return commands, environments


def test_default_allows_metadata_but_never_generation(
    diagnostic, fake_runtime, capsys,
):
    assert diagnostic.main([]) == 0
    report = json.loads(capsys.readouterr().out)

    assert report["schema_version"] == 1
    assert report["generation_attempted"] is False
    assert report["execution_enabled"] is False
    assert report["local_runtime"]["version"] == "0.153.4"
    assert report["local_authentication"]["status"] == "not_requested"
    assert report["local_image_event_schema"]["status"] == "schema_only"
    assert report["account"]["inspection_attempted"] is True
    assert report["models"]["inspection_attempted"] is True
    assert report["models"]["catalog_complete"] is False
    assert all(not item["live_verified"] for item in report["capabilities"].values())


def test_missing_optional_sdk_still_produces_valid_metadata_report(
    diagnostic, monkeypatch, capsys,
):
    def missing_package(name):
        raise importlib.metadata.PackageNotFoundError(name)

    monkeypatch.setattr(importlib.metadata, "version", missing_package)
    monkeypatch.setattr(diagnostic.shutil, "which", lambda name: None)

    assert diagnostic.main([]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["packages"]["sdk"]["status"] == "unavailable"
    assert report["account"]["inspection_attempted"] is False
    assert report["models"]["catalog_complete"] is False
    assert report["execution_enabled"] is False


def test_child_environment_drops_inherited_credentials_and_provider_overrides(
    diagnostic, fake_runtime, monkeypatch, capsys,
):
    overrides = {
        "OPENAI_API_KEY": SECRET,
        "OPENAI_BASE_URL": "https://unapproved.example.test",
        "CODEX_API_KEY": SECRET,
        "CODEX_HOME": "/private/auth-cache",
        "CODEX_CONFIG": SECRET,
        "ANTHROPIC_API_KEY": SECRET,
        "HTTP_PROXY": f"http://user:{SECRET}@proxy.example.test",
        "HTTPS_PROXY": f"http://user:{SECRET}@proxy.example.test",
        "ALL_PROXY": SECRET,
        "http_proxy": SECRET,
        "https_proxy": SECRET,
        "XDG_CONFIG_HOME": "/private/config",
        "PYTHONPATH": "/untrusted/python",
    }
    for key, value in overrides.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("HOME", "/private/developer-home")
    before = dict(os.environ)

    assert diagnostic.main([]) == 0
    captured = capsys.readouterr()
    _, environments = fake_runtime
    assert environments, "Expected isolated local metadata inspection"
    for child_env in environments:
        assert overrides.keys().isdisjoint(child_env)
    assert dict(os.environ) == before
    assert SECRET not in captured.out + captured.err
    assert "/private/" not in captured.out + captured.err


def test_untrusted_local_evidence_cannot_leak_secrets_or_claim_live_verification(diagnostic):
    report = diagnostic.build_report(evidence={
        "sdk_version": f"0.147.0 {SECRET}",
        "bundled_runtime_version": EMAIL,
        "local_runtime_version": SECRET,
        "local_runtime_status": SECRET,
        "sdk_schema_status": EMAIL,
        "image_event_fields": ["result", SECRET, EMAIL],
        "account": {"type": "chatgpt", "email": EMAIL},
        "models": {"catalog_complete": True},
        "execution_enabled": True,
        "error": SECRET,
    })
    serialized = json.dumps(report)
    assert SECRET not in serialized
    assert EMAIL not in serialized
    assert report["execution_enabled"] is False
    assert report["account"]["inspection_attempted"] is False
    assert report["models"]["catalog_complete"] is False
    assert all(not capability["live_verified"] for capability in report["capabilities"].values())


@pytest.mark.parametrize("sdk_version", ["0.147.0", "9.0.0"])
def test_installed_versions_and_schema_cannot_claim_live_capability(diagnostic, sdk_version):
    report = diagnostic.build_report(evidence={
        "sdk_version": sdk_version,
        "bundled_runtime_version": sdk_version,
        "local_runtime_version": "0.153.4",
        "local_runtime_status": "observed",
        "sdk_schema_status": "observed",
        "image_event_fields": ["type", "status", "result", "saved_path"],
    })
    capabilities = report["capabilities"]
    assert all(value["live_verified"] is False for value in capabilities.values())
    assert capabilities["image_model_selection"]["status"] == "blocked"
    assert capabilities["execution_boundary"]["status"] == "unverified"
    assert report["local_image_event_schema"]["live_verified"] is False
    assert report["account"]["inspection_attempted"] is False
    assert report["execution_enabled"] is False


def test_schema_child_only_inspects_types_never_constructs_sdk(diagnostic, capsys):
    assert diagnostic.main(["--local-schema-child"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert "result" in report["image_event_fields"]


def test_process_failure_does_not_echo_raw_credentials(diagnostic, monkeypatch, capsys):
    monkeypatch.setattr(importlib.metadata, "version", lambda name: "0.147.0")
    monkeypatch.setattr(diagnostic.shutil, "which", lambda name: "/fake/codex")

    def failed_process(*args, **kwargs):
        raise OSError(f"Cannot launch for {EMAIL}: token={SECRET}")

    monkeypatch.setattr(diagnostic.subprocess, "Popen", failed_process)
    assert diagnostic.main([]) == 0
    captured = capsys.readouterr()
    report = json.loads(captured.out)
    assert report["local_runtime"]["status"] == "unavailable"
    assert report["execution_enabled"] is False
    assert SECRET not in captured.out + captured.err
    assert EMAIL not in captured.out + captured.err


def test_cli_auth_child_discards_api_key_fragments(diagnostic, monkeypatch, capsys):
    def login_status(command, **kwargs):
        assert command == ["/fake/codex", "login", "status"]
        return SimpleNamespace(
            returncode=0, stdout=b"",
            stderr=f"Logged in using an API key - {SECRET}\n".encode(),
        )

    monkeypatch.setattr(diagnostic.subprocess, "run", login_status)
    assert diagnostic.main(["--local-auth-child", "/fake/codex"]) == 0
    captured = capsys.readouterr()
    assert json.loads(captured.out)["mode"] == "api_key"
    assert SECRET not in captured.out + captured.err


def test_cli_auth_parser_does_not_infer_chatgpt_from_unrecognized_output(diagnostic):
    result = diagnostic.parse_login_status(
        0, f"Logged in using ChatGPT\nAccount: {EMAIL}\nToken: {SECRET}"
    )
    assert result["mode"] is None
    assert result["status"] != "observed"
    assert EMAIL not in json.dumps(result)
    assert SECRET not in json.dumps(result)


def test_sdk_metadata_keeps_partial_catalog_and_omitted_modalities_honest(
    diagnostic, monkeypatch, capsys,
):
    client = MetadataClient(FakeChatgptAccount())
    client.catalog = SimpleNamespace(
        data=[
            SimpleNamespace(
                id="reasoning-test", model="reasoning-test", hidden=False,
                input_modalities=["text", "image"], model_fields_set={"id", "model"},
                description=f"{EMAIL} {SECRET}",
            ),
            SimpleNamespace(
                id="vision-test", model="vision-test", hidden=True,
                input_modalities=["text", "image"],
                model_fields_set={"id", "model", "input_modalities"},
            ),
        ],
        next_cursor=SECRET,
    )
    monkeypatch.setattr(sys.modules["openai_codex"], "AsyncCodex", lambda: client)

    assert diagnostic.main(["--sdk-metadata-child"]) == 0
    captured = capsys.readouterr()
    evidence = json.loads(captured.out)
    assert evidence["account_mode"] == "chatgpt"
    assert evidence["catalog_complete"] is False
    assert evidence["next_cursor_present"] is True
    assert evidence["catalog"][0]["input_modalities"] is None
    assert evidence["catalog"][1]["input_modalities"] == ["text", "image"]
    assert SECRET not in captured.out + captured.err
    assert EMAIL not in captured.out + captured.err

    report = diagnostic.build_report(evidence=evidence)
    assert report["execution_enabled"] is False
    assert all(not value["live_verified"] for value in report["capabilities"].values())
    assert report["models"]["catalog_complete"] is False


@pytest.mark.parametrize("mode", ["apiKey", "chatgpt"])
def test_sdk_metadata_refuses_non_chatgpt_and_untyped_identity_claims(diagnostic, mode):
    # A matching string on an untyped object is not a verified SDK identity.
    client = MetadataClient(SimpleNamespace(type=mode, email=EMAIL))
    evidence = asyncio.run(diagnostic.inspect_sdk_metadata(
        SimpleNamespace(AsyncCodex=lambda: client), FakeChatgptAccount,
    ))
    assert evidence["account_mode"] != "chatgpt"
    assert evidence["models_status"] == "blocked"
    assert evidence["catalog"] == []
    assert evidence["catalog_complete"] is False
    assert EMAIL not in json.dumps(evidence)


def test_sdk_metadata_failure_preserves_account_without_leaking_rpc_error(diagnostic):
    class FailingModelsClient(MetadataClient):
        async def models(self, **kwargs):
            raise RuntimeError(f"Provider rejected {EMAIL}, bearer {SECRET}")

    client = FailingModelsClient(FakeChatgptAccount())
    evidence = asyncio.run(diagnostic.inspect_sdk_metadata(
        SimpleNamespace(AsyncCodex=lambda: client), FakeChatgptAccount,
    ))
    assert evidence["account_mode"] == "chatgpt"
    assert evidence["models_status"] == "failed"
    assert evidence["catalog_complete"] is False
    assert SECRET not in json.dumps(evidence)
    assert EMAIL not in json.dumps(evidence)
