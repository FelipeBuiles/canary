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
        "checks": {"supabase": "ok", "litellm": "ok", "generation_queue": "ok"},
    }


def _load_verifier() -> ModuleType:
    path = REPO_ROOT / "scripts" / "verify_deployment.py"
    spec = importlib.util.spec_from_file_location("verify_deployment", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def healthy_verifier(monkeypatch):
    verifier = _load_verifier()
    monkeypatch.setenv("SCENEWRIGHT_APP_URL", "https://example.test")
    monkeypatch.setenv("EXPECTED_CANARY_VERSION", "release-sha")
    monkeypatch.setenv("CANARY_OPS_TOKEN", "operator-secret")
    monkeypatch.setattr(verifier, "_ops_json", lambda *_args: {"draining": False})
    monkeypatch.setattr(verifier, "_get_json", lambda _origin, path: {
        "/api/version": ({"git_sha": "release-sha", "build_timestamp": "2026-10-01T00:00:00Z"}, {}),
        "/api/health": ({"status": "ok"}, {name: "present" for name in verifier.REQUIRED_SECURITY_HEADERS}),
        "/api/health/ready": (_production_readiness(), {}),
    }[path])
    return verifier



def test_verifier_accepts_matching_healthy_release(monkeypatch, capsys, healthy_verifier) -> None:
    verifier = healthy_verifier
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
    assert evidence["admission"]["draining"] is False


@pytest.mark.parametrize("admission", [{"draining": True}, {}])
def test_verifier_rejects_paused_or_unknown_admission(monkeypatch, capsys, healthy_verifier, admission):
    monkeypatch.setattr(healthy_verifier, "_ops_json", lambda *_args: admission)
    assert healthy_verifier.main() == 1
    assert "generation admission is still paused" in capsys.readouterr().out


def test_resume_verifies_release_before_reopening_and_checks_admission(monkeypatch, healthy_verifier):
    calls = []
    public = healthy_verifier._get_json

    def get_json(origin, path):
        calls.append((path, "GET"))
        return public(origin, path)

    def ops_json(origin, path, token, method="GET"):
        assert token == "operator-secret"
        calls.append((path, method))
        return {"draining": False}

    monkeypatch.setattr(healthy_verifier, "_get_json", get_json)
    monkeypatch.setattr(healthy_verifier, "_ops_json", ops_json)
    assert healthy_verifier.main(resume=True) == 0
    assert calls == [
        ("/api/version", "GET"), ("/api/health", "GET"),
        ("/api/health/ready", "GET"), ("/api/health", "GET"),
        ("/api/ops/resume", "POST"), ("/api/ops/deployment-status", "GET"),
    ]


@pytest.mark.parametrize("failure", ["wrong_release", "dependency", "security_headers", "missing_sha", "missing_token"])
def test_resume_never_runs_when_release_checks_fail(monkeypatch, healthy_verifier, failure):
    public = healthy_verifier._get_json

    def get_json(origin, path):
        payload, headers = public(origin, path)
        if failure == "wrong_release" and path == "/api/version":
            payload = {**payload, "git_sha": "old-release"}
        if failure == "dependency" and path == "/api/health/ready":
            payload = {**payload, "checks": {}}
        if failure == "security_headers":
            headers = {}
        return payload, headers

    def no_ops(*_args):
        pytest.fail("Failed verification must not reopen admission")

    monkeypatch.setattr(healthy_verifier, "_get_json", get_json)
    monkeypatch.setattr(healthy_verifier, "_ops_json", no_ops)
    if failure == "missing_sha":
        monkeypatch.delenv("EXPECTED_CANARY_VERSION")
    if failure == "missing_token":
        monkeypatch.delenv("CANARY_OPS_TOKEN")
    assert healthy_verifier.main(resume=True) == 1


@pytest.mark.parametrize("failure", ["resume_denied", "still_draining", "resume_not_confirmed"])
def test_resume_failure_cannot_report_success(monkeypatch, healthy_verifier, failure):
    def ops_json(origin, path, token, method="GET"):
        if failure == "resume_denied":
            raise healthy_verifier.urllib.error.HTTPError(origin + path, 503, "Not ready", {}, None)
        return {"draining": failure == "resume_not_confirmed" or path.endswith("deployment-status")}

    monkeypatch.setattr(healthy_verifier, "_ops_json", ops_json)
    assert healthy_verifier.main(resume=True) == 1


def test_ci_verifies_then_resumes_with_the_expected_release_and_ops_auth():
    import yaml

    workflow = yaml.safe_load((REPO_ROOT / ".depot/workflows/ci.yml").read_text())
    steps = workflow["jobs"]["deploy"]["steps"]
    deploy = next(i for i, step in enumerate(steps) if step.get("name") == "Deploy exact release image")
    record = next(i for i, step in enumerate(steps) if step.get("name") == "Record deployed release")
    assert deploy < record
    assert steps[deploy]["run"] == "python3 scripts/deploy_lightsail.py"
    assert steps[deploy]["env"]["CANARY_RELEASE_VERSION"] == "${{ github.sha }}"
    # The host transaction verifies then resumes; test_lightsail_release tests
    # that ordering and its failure paths. CI must not receive the ops token.
    assert "CANARY_OPS_TOKEN" not in str(workflow)
    assert "if" not in steps[deploy]


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
        ({"checks": {"supabase": "ok", "litellm": "ok"}}, "generation_queue as ok"),
        ({"checks": {"supabase": "ok", "litellm": "ok", "generation_queue": "unavailable"}}, "generation_queue as ok"),
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
