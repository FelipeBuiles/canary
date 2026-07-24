from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType


REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_verifier() -> ModuleType:
    path = REPO_ROOT / "scripts" / "verify_deployment.py"
    spec = importlib.util.spec_from_file_location("verify_deployment", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_verifier_accepts_matching_healthy_release(monkeypatch, capsys) -> None:
    verifier = _load_verifier()
    headers = {name: "present" for name in verifier.REQUIRED_SECURITY_HEADERS}
    responses = iter(
        [
            (
                {
                    "application_version": "0.1.0",
                    "git_sha": "release-sha",
                    "build_timestamp": "2026-07-24T12:00:00Z",
                },
                {},
            ),
            ({"status": "ok"}, {}),
            ({"status": "ok", "checks": {}}, {}),
            ({"status": "ok"}, headers),
        ]
    )
    monkeypatch.setenv("SCENEWRIGHT_APP_URL", "https://example.test")
    monkeypatch.setenv("EXPECTED_CANARY_VERSION", "release-sha")
    monkeypatch.setattr(verifier, "_get_json", lambda *_args: next(responses))

    assert verifier.main() == 0
    evidence = json.loads(capsys.readouterr().out)
    assert evidence["status"] == "passed"
    assert evidence["security_headers"]["missing"] == []


def test_verifier_rejects_wrong_release_and_missing_headers(
    monkeypatch,
    capsys,
) -> None:
    verifier = _load_verifier()
    responses = iter(
        [
            (
                {
                    "application_version": "0.1.0",
                    "git_sha": "wrong-sha",
                    "build_timestamp": "unknown",
                },
                {},
            ),
            ({"status": "ok"}, {}),
            ({"status": "ok", "checks": {}}, {}),
            ({"status": "ok"}, {}),
        ]
    )
    monkeypatch.setenv("SCENEWRIGHT_APP_URL", "https://example.test")
    monkeypatch.setenv("EXPECTED_CANARY_VERSION", "release-sha")
    monkeypatch.setattr(verifier, "_get_json", lambda *_args: next(responses))

    assert verifier.main() == 1
    evidence = json.loads(capsys.readouterr().out)
    assert evidence["status"] == "failed"
    assert any("release SHA mismatch" in item for item in evidence["failures"])
    assert any("build timestamp" in item for item in evidence["failures"])
    assert evidence["security_headers"]["missing"] == sorted(
        verifier.REQUIRED_SECURITY_HEADERS
    )
