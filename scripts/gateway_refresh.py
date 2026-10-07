#!/usr/bin/env python3
"""Detect and refresh a stale local Compose gateway without provider calls."""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

from gateway_state import (
    BUILD_ENV, BUILD_LABEL, SCHEMA_VERSION, STATE_PATH,
    build_fingerprint, runtime_files,
)

ROOT = Path(__file__).resolve().parents[1]
LIVE_PROBE = f"""
import json, os, urllib.request
from pathlib import Path
try:
    state = json.loads(Path({STATE_PATH!r}).read_text())
except (OSError, ValueError):
    state = None
result = {{'state': state, 'models': None}}
try:
    request = urllib.request.Request('http://127.0.0.1:4000/v1/models',
        headers={{'Authorization': 'Bearer ' + os.environ['LITELLM_MASTER_KEY']}})
    with urllib.request.urlopen(request, timeout=3) as response:
        result['models'] = [model['id'] for model in json.load(response)['data']]
except Exception:
    pass
print(json.dumps(result))
"""


@dataclass(frozen=True)
class RefreshPlan:
    action: str
    reasons: tuple[str, ...] = ()


def plan_refresh(*, build: str, files: dict[str, str], config_hash: str,
                 expected_models: set[str], image: dict | None, container: dict | None,
                 live: dict, force_build: bool = False) -> RefreshPlan:
    labels = (image or {}).get("Config", {}).get("Labels") or {}
    if force_build or labels.get(BUILD_LABEL) != build:
        reason = "Rebuild explicitly requested" if force_build else (
            "Gateway image inputs changed or the image has no build fingerprint")
        return RefreshPlan("build", (reason,))
    if not container or not container.get("State", {}).get("Running"):
        return RefreshPlan("recreate", ("Gateway is not running",))
    reasons = []
    if container.get("Image") != image["Id"]:
        reasons.append("A newer gateway image is already built")
    container_labels = container.get("Config", {}).get("Labels") or {}
    if container_labels.get("com.docker.compose.config-hash") != config_hash:
        reasons.append("Gateway environment, mounts, or Compose settings changed")
    state = live.get("state")
    if not isinstance(state, dict) or state.get("schema_version") != SCHEMA_VERSION:
        reasons.append("Gateway has no supported startup fingerprint")
    else:
        if state.get("build_sha256") != build:
            reasons.append("Running gateway uses older image inputs")
        loaded = state.get("runtime_files")
        if not isinstance(loaded, dict):
            loaded = {}
        changed = sorted(name for name in files.keys() | loaded.keys()
                         if files.get(name) != loaded.get(name))
        if changed:
            reasons.append("Changed since gateway startup: " + ", ".join(changed))
    if live.get("models") is not None:
        missing = sorted(expected_models - set(live["models"]))
        if missing:
            reasons.append("Model routes missing from running gateway: " + ", ".join(missing))
    if reasons:
        return RefreshPlan("recreate", tuple(reasons))
    if live.get("models") is None:
        return RefreshPlan("unhealthy", ("Gateway model inventory is unavailable",))
    return RefreshPlan("current")


def compose_context(root: Path, existing: dict | None, environment: dict[str, str]):
    """Resolve current settings while retaining credentials absent from .env."""
    env = dict(environment)
    labels = (existing or {}).get("Config", {}).get("Labels") or {}
    files = [Path(path) for path in labels.get("com.docker.compose.project.config_files", "").split(",") if path]
    if not files:
        files = [root / "docker-compose.yml"]
    if root / "docker-compose.yml" not in files:
        raise RuntimeError("Gateway is not managed by this checkout's Docker Compose configuration")
    old_env = dict(item.split("=", 1) for item in (existing or {}).get("Config", {}).get("Env", []) if "=" in item)
    mounts = {item["Destination"]: item["Source"] for item in (existing or {}).get("Mounts", [])}
    credential_settings = {
        "CANARY_VERTEX_CREDENTIALS_FILE": "/run/credentials/google-adc.json",
        "CANARY_AWS_CONFIG_FILE": "/run/aws/config",
        "CANARY_AWS_LOGIN_CACHE_DIRECTORY": "/run/aws/login/cache",
    }
    for variable, target in credential_settings.items():
        if variable not in env and target in mounts:
            env[variable] = mounts[target]
    for variable, filename in (
        ("CANARY_VERTEX_CREDENTIALS_FILE", "docker-compose.vertex.yml"),
        ("CANARY_AWS_LOGIN_CACHE_DIRECTORY", "docker-compose.aws-login.yml"),
    ):
        if env.get(variable) and root / filename not in files:
            files.append(root / filename)
    variables = set(re.findall(r"\$\{([A-Z][A-Z0-9_]*)", "\n".join(path.read_text() for path in files)))
    for name in variables & old_env.keys():
        if name not in env and name not in {"HOME", "PATH", "CODEX_HOME"}:
            env[name] = old_env[name]
    if "LITELLM_DATABASE_URL" not in env and old_env.get("DATABASE_URL"):
        env["LITELLM_DATABASE_URL"] = old_env["DATABASE_URL"]
    project = env.get("COMPOSE_PROJECT_NAME") or labels.get("com.docker.compose.project") or root.name
    command = ["docker", "compose", "--project-name", project]
    for path in files:
        command.extend(["-f", str(path)])
    return command, env


class Gateway:
    def __init__(self, root: Path, environment: dict[str, str]):
        self.root, self.env = root, dict(environment)
        self.compose: list[str] = []

    def capture(self, command: list[str], *, optional=False, stdin=None) -> str:
        result = subprocess.run(command, cwd=self.root, env=self.env, input=stdin,
                                capture_output=True, text=True, timeout=30)
        if result.returncode:
            if optional:
                return ""
            # Compose config and inspect output can contain credentials. Never
            # print their bodies or subprocess exception representations.
            raise RuntimeError("Docker inspection failed; check Docker and the gateway's .env/credential settings")
        return result.stdout

    def discover(self) -> dict | None:
        ids = self.capture(["docker", "ps", "--all", "--filter", "label=com.docker.compose.service=litellm", "--format", "{{.ID}}"])
        if not ids.strip():
            return None
        containers = json.loads(self.capture(["docker", "inspect", *ids.split()]))
        matches = []
        for container in containers:
            labels = container["Config"].get("Labels") or {}
            if Path(labels.get("com.docker.compose.project.working_dir", "/")).resolve() != self.root:
                continue
            project = self.env.get("COMPOSE_PROJECT_NAME")
            if project and labels.get("com.docker.compose.project") != project:
                continue
            matches.append(container)
        if len(matches) > 1:
            raise RuntimeError("Multiple gateways belong to this checkout; set COMPOSE_PROJECT_NAME to select one")
        return matches[0] if matches else None

    def probe(self, container: dict | None) -> dict:
        if not container or not container["State"].get("Running"):
            return {}
        output = self.capture(["docker", "exec", "-i", container["Id"], "/app/.venv/bin/python", "-"],
                              optional=True, stdin=LIVE_PROBE)
        return json.loads(output) if output.strip() else {}

    def inspect(self) -> RefreshPlan:
        import yaml

        self.container = self.discover()
        self.compose, self.env = compose_context(self.root, self.container, self.env)
        config = json.loads(self.capture([*self.compose, "config", "--format", "json"]))
        service = config["services"]["litellm"]
        for volume in service.get("volumes", []):
            if volume["type"] == "bind" and volume["target"].startswith(("/run/credentials/", "/run/aws/")):
                if not Path(volume["source"]).exists():
                    raise RuntimeError("A configured gateway credential mount is missing; restore it before refreshing")
        self.image_name = service["image"]
        inspected = self.capture(["docker", "image", "inspect", self.image_name], optional=True)
        image = json.loads(inspected)[0] if inspected.strip() else None
        config_hash = self.capture([*self.compose, "config", "--hash", "litellm"]).split()[-1]
        self.build = build_fingerprint(self.root)
        self.files = runtime_files(self.root)
        try:
            routes = yaml.safe_load((self.root / "litellm/config.yaml").read_text())["model_list"]
        except yaml.YAMLError:
            raise RuntimeError("Gateway route configuration is invalid; fix litellm/config.yaml before refreshing") from None
        self.models = {route["model_name"] for route in routes}
        return plan_refresh(build=self.build, files=self.files, config_hash=config_hash,
                            expected_models=self.models, image=image, container=self.container,
                            live=self.probe(self.container))

    def execute(self, plan: RefreshPlan) -> None:
        if plan.action == "build":
            print("[gateway] Building updated gateway image; the running gateway stays available during the build.", flush=True)
            self.run(["build", "--build-arg", f"{BUILD_ENV}={self.build}", "litellm"])
            if build_fingerprint(self.root) != self.build:
                raise RuntimeError("Gateway build inputs changed during the build; rerun ./scripts/gateway.sh")
        # Reuse a healthy database; never run down, delete volumes, or recreate
        # other services as a side effect of a gateway refresh.
        database_id = self.capture([*self.compose, "ps", "-q", "litellm-db"]).strip()
        if not database_id:
            print("[gateway] Starting the missing gateway database.", flush=True)
            self.run(["up", "-d", "--wait", "litellm-db"])
        print("[gateway] Recreating LiteLLM with the current routes and handlers.", flush=True)
        self.run(["up", "-d", "--no-deps", "--force-recreate", "litellm"])
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            container = self.discover()
            live = self.probe(container)
            if live.get("models") is not None:
                verified = self.inspect()
                if verified.action == "current":
                    print("[gateway] Current: startup fingerprints and all configured model routes verified. No generation requests sent.")
                    return
                raise RuntimeError("Gateway refresh did not match the checkout: " + "; ".join(verified.reasons))
            if container and not container["State"].get("Running"):
                raise RuntimeError("Gateway exited during startup; inspect its logs")
            time.sleep(1)
        raise RuntimeError("Gateway did not expose its model inventory within 45 seconds; inspect its logs")

    def run(self, arguments: list[str]) -> None:
        result = subprocess.run([*self.compose, *arguments], cwd=self.root, env=self.env)
        if result.returncode:
            raise RuntimeError("Gateway " + arguments[0] + " failed; inspect the Docker output above")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="./scripts/gateway.sh", description=(
        "Refresh only the local LiteLLM gateway. Rebuild changed image inputs, "
        "recreate changed routes/handlers/settings, and leave a current gateway running. "
        "Run between generation jobs; refreshing can interrupt active provider calls."))
    parser.add_argument("--check", action="store_true", help="report freshness without building or restarting anything")
    parser.add_argument("--rebuild", action="store_true", help="force an image rebuild and gateway recreate")
    args = parser.parse_args(argv)
    if args.check and args.rebuild:
        parser.error("--check cannot be combined with --rebuild")
    try:
        gateway = Gateway(ROOT, dict(os.environ))
        plan = gateway.inspect()
        if args.rebuild:
            plan = RefreshPlan("build", ("Rebuild explicitly requested",))
        if plan.action == "current":
            print("[gateway] Current: loaded files, image, settings, and model routes match. Nothing to refresh.")
            return 0
        for reason in plan.reasons:
            print("[gateway] " + reason)
        if args.check or plan.action == "unhealthy":
            print("[gateway] Refresh with ./scripts/gateway.sh (or ./scripts/dev.sh --refresh-gateway).")
            return 1
        gateway.execute(plan)
        return 0
    except (RuntimeError, OSError, ValueError, KeyError, subprocess.TimeoutExpired):
        # Only deliberately safe RuntimeError diagnostics are shown; all other
        # failures omit raw process/config/HTTP payloads.
        error = sys.exc_info()[1]
        message = str(error) if isinstance(error, RuntimeError) else "Gateway inspection failed; check Docker and local configuration"
        print("[gateway] " + message, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
