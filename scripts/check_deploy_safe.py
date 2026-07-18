#!/usr/bin/env python3
"""Exit successfully only when Canary reports no active generation work."""

from __future__ import annotations

import json
import os
import sys
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

    request = urllib.request.Request(
        f"{origin}/api/ops/deployment-status",
        headers={"X-Canary-Ops-Token": token},
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            payload = json.load(response)
    except (OSError, urllib.error.HTTPError, json.JSONDecodeError) as exc:
        print(f"Could not read deployment status: {exc}", file=sys.stderr)
        return 2

    print(json.dumps(payload, indent=2, sort_keys=True))
    if payload.get("safe_to_deploy") is True:
        print("Safe to deploy: no generation work is active.")
        return 0
    print("Do not deploy: generation work is still active.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
