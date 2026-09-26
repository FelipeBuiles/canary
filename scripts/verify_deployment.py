#!/usr/bin/env python3
"""Verify the public contracts required after a Canary production deploy."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any


REQUIRED_SECURITY_HEADERS = {
    "content-security-policy",
    "permissions-policy",
    "referrer-policy",
    "strict-transport-security",
    "x-content-type-options",
}
DEPLOYMENT_VERIFIER_USER_AGENT = "Canary-deployment-verifier/1.0"
EXPECTED_PIPELINE_CONTRACT = "eight-stage-v2"


def _get_json(origin: str, path: str) -> tuple[dict[str, Any], Any]:
    request = urllib.request.Request(
        f"{origin}{path}",
        headers={"User-Agent": DEPLOYMENT_VERIFIER_USER_AGENT},
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        payload = json.load(response)
        return payload, response.headers


def main() -> int:
    origin = os.environ.get(
        "SCENEWRIGHT_APP_URL", "https://canary-web.fly.dev"
    ).rstrip("/")
    expected_sha = os.environ.get("EXPECTED_CANARY_VERSION", "").strip()
    failures: list[str] = []
    evidence: dict[str, Any] = {"origin": origin}

    try:
        version, _ = _get_json(origin, "/api/version")
        evidence["version"] = version
        if expected_sha and version.get("git_sha") != expected_sha:
            failures.append(
                "release SHA mismatch: "
                f"expected {expected_sha}, received {version.get('git_sha')}"
            )
        if version.get("build_timestamp") in {None, "", "unknown"}:
            failures.append("release build timestamp is missing")

        liveness, _ = _get_json(origin, "/api/health")
        evidence["health"] = liveness
        if liveness.get("status") != "ok":
            failures.append("/api/health did not report ok")

        readiness, _ = _get_json(origin, "/api/health/ready")
        evidence["readiness"] = readiness
        if readiness.get("status") != "ok":
            failures.append("/api/health/ready did not report ok")
        if readiness.get("pipeline_contract") != EXPECTED_PIPELINE_CONTRACT:
            failures.append(
                "production pipeline contract mismatch: "
                f"expected {EXPECTED_PIPELINE_CONTRACT}"
            )
        if readiness.get("model_mode") != "api":
            failures.append("production readiness must report API model mode")
        checks = readiness.get("checks")
        if not isinstance(checks, dict):
            failures.append("production readiness dependency checks are missing or malformed")
        else:
            for dependency in ("supabase", "litellm", "generation_queue"):
                if checks.get(dependency) != "ok":
                    failures.append(
                        f"production readiness must report {dependency} as ok"
                    )

        _, headers = _get_json(origin, "/api/health")
        header_names = {name.lower() for name in headers}
        missing_headers = sorted(REQUIRED_SECURITY_HEADERS - header_names)
        evidence["security_headers"] = {
            "present": sorted(REQUIRED_SECURITY_HEADERS & header_names),
            "missing": missing_headers,
        }
        if missing_headers:
            failures.append(
                "required security headers missing: " + ", ".join(missing_headers)
            )
    except (OSError, urllib.error.HTTPError, json.JSONDecodeError) as exc:
        failures.append(f"public verification request failed: {exc}")

    evidence["status"] = "failed" if failures else "passed"
    evidence["failures"] = failures
    print(json.dumps(evidence, indent=2, sort_keys=True))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
