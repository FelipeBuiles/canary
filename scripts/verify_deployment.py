#!/usr/bin/env python3
"""Verify the public contracts required after a Canary production deploy."""

from __future__ import annotations

import argparse
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


def _ops_json(origin: str, path: str, token: str, method: str = "GET") -> dict[str, Any]:
    request = urllib.request.Request(
        f"{origin}{path}",
        headers={
            "User-Agent": DEPLOYMENT_VERIFIER_USER_AGENT,
            "X-Canary-Ops-Token": token,
        },
        method=method,
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.load(response)


def main(*, resume: bool = False) -> int:
    origin = os.environ.get(
        "SCENEWRIGHT_APP_URL", "https://canary-web.fly.dev"
    ).rstrip("/")
    expected_sha = os.environ.get("EXPECTED_CANARY_VERSION", "").strip()
    failures: list[str] = []
    evidence: dict[str, Any] = {"origin": origin}
    if resume and not expected_sha:
        failures.append("EXPECTED_CANARY_VERSION is required before resuming generation")

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
        # A persisted deployment drain survives replacement of the process.
        # Reopen only after the exact release and all public checks pass; never
        # run this as unconditional cleanup for a failed/cancelled deployment.
        if not failures:
            token = os.environ.get("CANARY_OPS_TOKEN", "").strip()
            if not token:
                failures.append("CANARY_OPS_TOKEN is required to verify generation admission")
            else:
                if resume:
                    resumed = _ops_json(origin, "/api/ops/resume", token, "POST")
                    evidence["resume"] = resumed
                    if resumed.get("draining") is not False:
                        failures.append("deployment resume did not reopen generation admission")
                admission = _ops_json(origin, "/api/ops/deployment-status", token)
                evidence["admission"] = admission
                if admission.get("draining") is not False:
                    failures.append("generation admission is still paused for deployment")
    except (OSError, urllib.error.HTTPError, json.JSONDecodeError) as exc:
        failures.append(f"public verification request failed: {exc}")

    evidence["status"] = "failed" if failures else "passed"
    evidence["failures"] = failures
    print(json.dumps(evidence, indent=2, sort_keys=True))
    return 1 if failures else 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--resume", action="store_true",
        help="Explicitly reopen generation after release verification succeeds.",
    )
    raise SystemExit(main(resume=parser.parse_args().resume))
