#!/usr/bin/env python3
"""Smoke-test a built gateway image with disposable Docker resources only.

Usage: python3 scripts/smoke_gateway.py canary-gateway-ci
Requires Docker and Python 3.12+. No provider credentials or paid requests.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

MASTER_KEY = "sk-local-smoke-fixture"


def docker(*args: str, check: bool = True) -> str:
    result = subprocess.run(["docker", *args], text=True, capture_output=True, check=False)
    if check and result.returncode:
        raise RuntimeError(f"docker {args[0]} failed:\n{result.stderr}\n{result.stdout}")
    return (result.stdout + result.stderr).strip() if args[0] == "logs" else result.stdout.strip()


def request(base: str, path: str, payload: dict | None = None, key: str = MASTER_KEY) -> dict:
    req = urllib.request.Request(
        base + path,
        data=json.dumps(payload).encode() if payload is not None else None,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=10) as response:
        return json.load(response)


def main(image: str) -> None:
    prefix = f"canary-gateway-smoke-{uuid.uuid4().hex[:10]}"
    network, postgres = prefix, f"{prefix}-postgres"
    containers: list[str] = []
    try:
        docker("network", "create", network)
        docker("run", "-d", "--name", postgres, "--network", network,
               "--network-alias", "postgres", "-e", "POSTGRES_USER=smoke",
               "-e", "POSTGRES_PASSWORD=smoke", "-e", "POSTGRES_DB=smoke",
               "postgres:17.11")
        containers.append(postgres)
        for _ in range(60):
            result = subprocess.run(["docker", "exec", postgres, "pg_isready", "-U", "smoke"], capture_output=True)
            if result.returncode == 0:
                break
            time.sleep(1)
        else:
            raise RuntimeError("Disposable PostgreSQL did not become ready")
        with tempfile.TemporaryDirectory(prefix=prefix) as tmp:
            config = Path(tmp) / "config.yaml"
            config.write_text(f"""model_list:
  - model_name: fixture
    litellm_params:
      model: openai/fixture
      api_key: unused-fixture
      mock_response: gateway-ok
general_settings:
  master_key: {MASTER_KEY}
""")
            for database in (False, True):
                name = f"{prefix}-{'db' if database else 'no-db'}"
                args = ["run", "-d", "--name", name, "--network", network,
                        "-p", "127.0.0.1::4000", "-v", f"{config}:/app/config.yaml:ro",
                        "-e", "LITELLM_TELEMETRY=False"]
                if database:
                    args.extend(["-e", "DATABASE_URL=postgresql://smoke:smoke@postgres:5432/smoke",
                                 "-e", "STORE_MODEL_IN_DB=True"])
                docker(*args, image)
                containers.append(name)
                port = docker("port", name, "4000/tcp").splitlines()[0]
                base = f"http://{port}"
                for _ in range(120):
                    try:
                        request(base, "/health/liveliness")
                        break
                    except (urllib.error.URLError, TimeoutError, OSError):
                        if docker("inspect", "-f", "{{.State.Running}}", name) != "true":
                            raise RuntimeError(f"Gateway exited before startup: {name}")
                        time.sleep(2)
                else:
                    raise RuntimeError(f"Gateway did not become healthy: {name}")
                payload = {"model": "fixture", "messages": [{"role": "user", "content": "fixture"}]}
                result = request(base, "/v1/chat/completions", payload)
                assert result["choices"][0]["message"]["content"] == "gateway-ok", result
                if database:
                    generated = request(base, "/key/generate", {"models": ["fixture"], "key_alias": "smoke"})
                    key = generated["key"]
                    result = request(base, "/v1/chat/completions", payload, key=key)
                    assert result["choices"][0]["message"]["content"] == "gateway-ok", result
                print(f"Gateway smoke passed: database={database}", flush=True)
                docker("rm", "-f", name)
                containers.remove(name)
    finally:
        for name in reversed(containers):
            print(docker("logs", name, check=False))
            docker("rm", "-fv", name, check=False)
        docker("network", "rm", network, check=False)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python3 scripts/smoke_gateway.py IMAGE")
    main(sys.argv[1])
