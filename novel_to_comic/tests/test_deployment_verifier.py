from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]


def _production_readiness() -> dict:
    return {
        "status": "ok",
        "pipeline_contract": "eight-stage-v2",
        "model_mode": "api",
        "checks": {"supabase": "ok", "litellm": "ok"},
    }


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
            (_production_readiness(), {}),
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
            (_production_readiness(), {}),
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


@pytest.mark.parametrize(
    ("override", "expected_failure"),
    [
        ({"pipeline_contract": None}, "pipeline contract mismatch"),
        ({"pipeline_contract": "old-pipeline"}, "pipeline contract mismatch"),
        ({"model_mode": None}, "API model mode"),
        ({"model_mode": "mock"}, "API model mode"),
        ({"model_mode": "codex"}, "API model mode"),
        ({"checks": None}, "missing or malformed"),
        ({"checks": []}, "missing or malformed"),
        ({"checks": {}}, "supabase as ok"),
        ({"checks": {"supabase": "ok", "mock_models": "ok"}}, "litellm as ok"),
        ({"checks": {"supabase": "skipped", "litellm": "ok"}}, "supabase as ok"),
        ({"checks": {"supabase": "ok", "litellm": "skipped"}}, "litellm as ok"),
        ({"checks": {"supabase": "ok", "litellm": "error: timeout"}}, "litellm as ok"),
    ],
)
def test_verifier_rejects_nonproduction_readiness_despite_top_level_ok(
    monkeypatch, capsys, override, expected_failure,
) -> None:
    verifier = _load_verifier()
    responses = iter(
        [
            ({"git_sha": "release-sha", "build_timestamp": "2026-09-09T12:00:00Z"}, {}),
            ({"status": "ok"}, {}),
            ({**_production_readiness(), **override}, {}),
            ({"status": "ok"}, {name: "present" for name in verifier.REQUIRED_SECURITY_HEADERS}),
        ]
    )
    monkeypatch.setenv("SCENEWRIGHT_APP_URL", "https://example.test")
    monkeypatch.setenv("EXPECTED_CANARY_VERSION", "release-sha")
    monkeypatch.setattr(verifier, "_get_json", lambda *_args: next(responses))

    assert verifier.main() == 1
    evidence = json.loads(capsys.readouterr().out)
    assert evidence["status"] == "failed"
    assert any(expected_failure in failure for failure in evidence["failures"])


def test_verifier_uses_cloudflare_compatible_user_agent(monkeypatch) -> None:
    verifier = _load_verifier()
    captured = {}

    class Response:
        headers = {}

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return b'{"status": "ok"}'

    def urlopen(request, **_kwargs):
        captured["request"] = request
        return Response()

    monkeypatch.setattr(verifier.urllib.request, "urlopen", urlopen)

    verifier._get_json("https://example.test", "/api/version")

    assert captured["request"].get_header("User-agent") == (
        "Canary-deployment-verifier/1.0"
    )
