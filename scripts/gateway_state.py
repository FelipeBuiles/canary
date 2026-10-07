"""Content fingerprints for the standalone development gateway (stdlib only)."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sys

SCHEMA_VERSION = 1
BUILD_LABEL = "com.canary.gateway.build-sha256"
BUILD_ENV = "CANARY_GATEWAY_BUILD_SHA256"
STATE_PATH = "/app/gateway-state.json"
BUILD_INPUTS = (
    ".dockerignore",
    "litellm/Dockerfile",
    "litellm/pyproject.toml",
    "litellm/uv.lock",
    "litellm/patch_http_errors.py",
    "litellm/patch_anthropic_refusals.py",
    "litellm/patch_model_response.py",
    "scripts/gateway_state.py",
)
RUNTIME_INPUTS = (
    "litellm/config.yaml",
    "litellm/canary_metrics.py",
    "litellm/canary_metrics_callback.py",
)


def file_hashes(files: dict[str, Path]) -> dict[str, str]:
    return {name: hashlib.sha256(path.read_bytes()).hexdigest()
            for name, path in sorted(files.items())}


def build_fingerprint(root: Path) -> str:
    files = file_hashes({name: root / name for name in BUILD_INPUTS})
    payload = {"schema_version": SCHEMA_VERSION, "files": files}
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def runtime_files(root: Path, *, container: bool = False) -> dict[str, str]:
    files = {name: root / (Path(name).name if container else name)
             for name in RUNTIME_INPUTS}
    for path in (root / "litellm_handlers").glob("*.py"):
        if not path.name.startswith("test_"):
            files[f"litellm_handlers/{path.name}"] = path
    return file_hashes(files)


def record_startup(root: Path, output: Path, environment: dict[str, str]) -> None:
    # Store content digests once before exec, rather than re-reading bind mounts
    # later and mistaking the files on disk for what the process loaded.
    state = {"schema_version": SCHEMA_VERSION,
             "build_sha256": environment.get(BUILD_ENV, "untracked"),
             "runtime_files": runtime_files(root, container=True)}
    temporary = output.with_suffix(".tmp")
    temporary.write_text(json.dumps(state, sort_keys=True))
    temporary.replace(output)


if __name__ == "__main__":
    record_startup(Path("/app"), Path(STATE_PATH), dict(os.environ))
    command = "/app/.venv/bin/litellm"
    os.execv(command, [command, *sys.argv[1:]])
