#!/usr/bin/env python3
"""Exit successfully only when Canary reports no active generation work."""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request


def main() -> int:
    origin = os.environ.get(
        "SCENEWRIGHT_APP_URL", "https://canary-web.fly.dev"
    ).rstrip("/")
    token = os.environ.get("CANARY_OPS_TOKEN", "").strip()
    if not token:
        print("CANARY_OPS_TOKEN is required", file=sys.stderr)
        return 2

    def fetch(path: str, method: str = "GET"):
        request = urllib.request.Request(
            f"{origin}{path}",
            headers={"X-Canary-Ops-Token": token},
            method=method,
        )
        with urllib.request.urlopen(request, timeout=10) as response:
            return json.load(response)

    try:
        fetch("/api/ops/drain", "POST")
        deadline = time.monotonic() + 1800
        while True:
            payload = fetch("/api/ops/deployment-status")
            print(json.dumps(payload, sort_keys=True), flush=True)
            if payload.get("draining") is True and payload.get("safe_to_deploy") is True:
                print("Safe to deploy: admission is closed and generation is idle.")
                return 0
            if time.monotonic() >= deadline:
                print("Drain timed out; admission remains closed. Explicit ops resume required.", file=sys.stderr)
                return 1
            time.sleep(5)
    except (OSError, urllib.error.HTTPError, json.JSONDecodeError) as exc:
        print(f"Could not establish deployment drain: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
