#!/usr/bin/env python3
"""Read-only Codex metadata; live generation uses codex_dev_probe.py explicitly.

Local schema/version and supported account/model metadata are inspected in
isolated children. Missing SDK uses CLI auth status when its version is known.
Metadata networking is permitted, not proof of generation eligibility. No auth
cache is inspected directly; no thread, turn, login or refresh is requested.
"""
from __future__ import annotations

import argparse
import asyncio
import importlib.metadata
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import tempfile
from collections.abc import Mapping, Sequence
from typing import Any

SDK_VERSION = "0.156.1"
INSPECTED_RUNTIME_VERSIONS = ("0.147.0", "0.153.4")
TIMEOUT_SECONDS = 10
MAX_OUTPUT_BYTES = 65536
CHILD_ENV_KEYS = ("HOME", "LANG", "LC_ALL", "SYSTEMROOT", "WINDIR")
SOURCE_ROOT = "https://github.com/openai/codex/blob/"
CONFIG_EVIDENCE = (
    "Effective configuration provenance is unverified. The isolated child removes "
    "inherited API/proxy/CODEX environment overrides, but normal runtime-managed "
    "local configuration/authentication remains. Read-only metadata is allowed; "
    "this is not an execution-isolation proof."
)
BOUNDARY_EVIDENCE = [
    "The separate runtime implements restricted preflight through supported "
    "config/read, typed account/model APIs and thread checks before a turn.",
    "Shell, web, MCP, apps and plugins are disabled; utility tools are permitted. "
    "Read-only workspace permissions do not prevent the built-in image extension "
    "from writing its source-fixed ~/.codex/generated_images store.",
    "This metadata diagnostic does not exercise runtime preflight or generation. "
    "Use scripts/codex_dev_probe.py explicitly for allowance-consuming evidence.",
]
IMAGE_FIELDS = ("type", "id", "status", "result", "revised_prompt", "saved_path")


def clean_child_env(environ: Mapping[str, str]) -> dict[str, str]:
    """Replace, never merge; retain HOME but no API/proxy/CODEX overrides."""
    return {key: environ[key] for key in CHILD_ENV_KEYS if key in environ}


def _version(value: Any) -> str | None:
    if isinstance(value, str) and re.fullmatch(r"[0-9]+(?:\.[0-9]+){1,3}", value):
        return value
    return None


def _capability(status: str, *evidence: str) -> dict[str, Any]:
    return {"status": status, "live_verified": False, "evidence": list(evidence)}


def parse_login_status(returncode: int, text: str) -> dict[str, Any]:
    """Reduce version-tagged CLI output to an enum; never return raw text."""
    messages = {
        "Logged in using ChatGPT": "chatgpt",
        "Logged in using workload identity": "workload_identity",
        "Logged in using access token": "access_token",
        "Logged in using personal access token": "personal_access_token",
        "Logged in using Amazon Bedrock API key": "bedrock_api_key",
        "Logged in using Amazon Bedrock AWS access keys": "bedrock_access_keys",
    }
    text = text.strip()
    if returncode == 0:
        mode = messages.get(text)
        if re.fullmatch(r"Logged in using an API key - [^\r\n]+", text):
            mode = "api_key"
        if mode:
            return {"status": "observed", "mode": mode}
    if returncode == 1 and text == "Not logged in":
        return {"status": "observed", "mode": "not_logged_in"}
    return {"status": "failed", "mode": None}


def _catalog(records: Any) -> list[dict[str, Any]]:
    """Allow only selectors and explicit modality evidence, never descriptions."""
    if not isinstance(records, list):
        return []
    result = []
    for record in records[:256]:
        if not isinstance(record, Mapping):
            continue
        selectors = {}
        for key in ("id", "model"):
            value = record.get(key)
            if (isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", value)
                    and not value.startswith("sk-")):
                selectors[key] = value
        if len(selectors) != 2:
            continue
        modalities = record.get("input_modalities")
        result.append({**selectors, "hidden": record.get("hidden") is True,
                       "input_modalities": [item for item in ("text", "image")
                                            if isinstance(modalities, list) and item in modalities]
                       if isinstance(modalities, list) else None})
    return result


async def inspect_sdk_metadata(sdk: Any, chatgpt_account_type: type) -> dict[str, Any]:
    """Supported read-only APIs; typed ChatGPT is required before model listing."""
    result: dict[str, Any] = {"account_status": "failed", "account_mode": None,
                              "models_status": "blocked", "catalog": [],
                              "next_cursor_present": None, "catalog_complete": False}
    try:
        async with sdk.AsyncCodex() as codex:
            account = await codex.account(refresh_token=False)
            root = account.account.root if account.account is not None else None
            result["account_status"] = "observed"
            if not isinstance(root, chatgpt_account_type) or root.type != "chatgpt":
                mode = getattr(root, "type", None)
                result["account_mode"] = mode if mode in ("apiKey", "amazonBedrock") else "unknown"
                return result
            result["account_mode"] = "chatgpt"
            result["models_status"] = "failed"
            models = await codex.models(include_hidden=True)
            records = [
                {"id": model.id, "model": model.model, "hidden": model.hidden,
                 "input_modalities": [getattr(item, "value", item) for item in model.input_modalities]
                 if "input_modalities" in model.model_fields_set and model.input_modalities is not None
                 else None}
                for model in models.data
            ]
            result["catalog"] = _catalog(records)
            result["models_status"] = "observed"
            result["next_cursor_present"] = models.next_cursor is not None
            result["catalog_complete"] = (
                models.next_cursor is None and len(result["catalog"]) == len(records)
            )
    except Exception:
        # Never disclose RPC errors, identity fields, configuration or endpoints.
        pass
    return result


def _sdk_metadata_child() -> int:
    try:
        import openai_codex
        from openai_codex.generated.v2_all import ChatgptAccount

        result = asyncio.run(inspect_sdk_metadata(openai_codex, ChatgptAccount))
    except Exception:
        result = {"account_status": "unavailable", "models_status": "unavailable"}
    print(json.dumps(result))
    return 0


def build_report(*, evidence: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Pure JSON report builder. Untrusted evidence never supplies report prose.

    Evidence keys: sdk_version, bundled_runtime_version, local_runtime_version,
    local_runtime_status, sdk_schema_status, image_event_fields. Status values
    are allowlisted and image field names restricted to the known public schema.
    No evidence, even a future SDK version, can enable execution.
    """
    local = evidence or {}
    sdk_version = _version(local.get("sdk_version"))
    bundled_version = _version(local.get("bundled_runtime_version"))
    runtime_version = _version(local.get("local_runtime_version"))
    statuses = {"observed", "unavailable", "timeout", "failed", "unsupported_version",
                "blocked", "not_requested"}
    schema_status = local.get("sdk_schema_status")
    if not isinstance(schema_status, str) or schema_status not in statuses:
        schema_status = "unavailable"
    runtime_status = local.get("local_runtime_status")
    if not isinstance(runtime_status, str) or runtime_status not in statuses:
        runtime_status = "unavailable"
    supplied_fields = local.get("image_event_fields", ())
    fields = [field for field in IMAGE_FIELDS if isinstance(supplied_fields, (list, tuple))
              and field in supplied_fields]
    schema_observed = sdk_version == SDK_VERSION and schema_status == "observed"
    if sdk_version and sdk_version != SDK_VERSION:
        schema_status = "unsupported_version"
    account_status = local.get("account_status")
    if not isinstance(account_status, str) or account_status not in statuses:
        account_status = "unavailable"
    account_mode = local.get("account_mode")
    if account_mode not in ("chatgpt", "apiKey", "amazonBedrock", "unknown"):
        account_mode = None
    models_status = local.get("models_status")
    if not isinstance(models_status, str) or models_status not in statuses:
        models_status = "unavailable"
    catalog = _catalog(local.get("catalog")) if account_mode == "chatgpt" else []
    auth_status = local.get("auth_status")
    if not isinstance(auth_status, str) or auth_status not in statuses:
        auth_status = "unavailable"
    auth_mode = local.get("auth_mode")
    if auth_mode not in ("chatgpt", "api_key", "workload_identity", "access_token",
                         "personal_access_token", "bedrock_api_key", "bedrock_access_keys",
                         "not_logged_in") or auth_status != "observed":
        auth_mode = None
    return {
        "schema_version": 1,
        "generation_attempted": False,
        "execution_enabled": False,
        "diagnostic_kind": "local_read_only_capability_report",
        "packages": {
            "sdk": {"name": "openai-codex", "version": sdk_version,
                    "status": "observed" if sdk_version else "unavailable",
                    "inspected_version": SDK_VERSION},
            "bundled_runtime": {"name": "openai-codex-cli-bin", "version": bundled_version,
                                "status": "observed" if bundled_version else "unavailable"},
        },
        "local_runtime": {"version": runtime_version, "status": runtime_status,
                          "used_for_sdk": False},
        "local_authentication": {
            "status": auth_status, "mode": auth_mode,
            "inspection_attempted": local.get("auth_inspection_attempted") is True,
            "supported_command": "codex login status",
            "evidence": "Supplementary CLI auth mode only, not verified SDK account identity, plan, "
                        "credential validity or generation eligibility. Auth metadata networking and "
                        "runtime-managed credential handling may occur. Raw status is never reported.",
        },
        "local_image_event_schema": {
            "status": "schema_only" if schema_observed else schema_status,
            "type": "ImageGenerationThreadItem",
            "fields": fields if schema_observed else [],
            "live_verified": False,
            "evidence": "Installed generated SDK model fields only; no image event received.",
        },
        "account": {"status": account_status, "mode": account_mode,
                    "inspection_attempted": local.get("sdk_metadata_attempted") is True,
                    "supported_api": "await codex.account(refresh_token=False)",
                    "evidence": "Typed SDK account only; email, plan and credentials are not reported."},
        "models": {"status": models_status,
                   "inspection_attempted": account_mode == "chatgpt",
                   "supported_api": "await codex.models(include_hidden=True)",
                   "catalog": catalog,
                   "catalog_complete": local.get("catalog_complete") is True
                                       and models_status == "observed"
                                       and local.get("next_cursor_present") is False,
                   "next_cursor_present": local.get("next_cursor_present")
                                          if isinstance(local.get("next_cursor_present"), bool) else None,
                   "evidence": "Only queried after typed ChatGPT account. Selectors do not attest "
                               "actual image backend or safe generation capability.",
                   "pagination": "High-level models() returns one page and no cursor input; "
                                 "an unconsumed next_cursor means a partial catalog."},
        "capabilities": {
            "text": _capability("schema_only", "TurnStartParams.outputSchema constrains the final "
                                "assistant message, not preceding tools. No JSON generation verified."),
            "image_input": _capability("schema_only", "ImageInput(url) and LocalImageInput(path) "
                                       "are typed inputs; no account/model vision call verified."),
            "image_generation": _capability("schema_only", "Typed imageGeneration result carries base64 "
                                             "image bytes, not a prose path. This diagnostic receives "
                                             "no generated bytes."),
            "image_editing": _capability("unverified", "Image tool accepts referenced_image_paths; "
                                          "editing fidelity and source-image behavior were not exercised."),
            "image_model_selection": _capability("blocked", "Both inspected runtimes hardcode "
                    "gpt-image-2; imagegen arguments expose no Sunburst/Flare or other image-model "
                    "selector. A thread reasoning-model selector does not select the image backend."),
            "reference_count_order": _capability("unverified", "Source allows at most five referenced "
                    "image paths and 1..5 previous images; eight ordered Draw references are not proved."),
            "output_dimensions": _capability("blocked", "Inspected image tool requests size=auto, "
                    "quality=Auto; no exact 1696x2528 output control is exposed."),
            "actual_model_reporting": _capability("unverified", "Image event fields do not attest "
                    "an actual image model. Source's gpt-image-2 constant is not live model evidence."),
            "execution_boundary": _capability("unverified", *BOUNDARY_EVIDENCE),
        },
        "safety": {"sdk_remote_metadata_requested": local.get("sdk_metadata_attempted") is True,
                   "auth_cache_inspected_directly": False,
                   "auth_metadata_network_possible": local.get("auth_inspection_attempted") is True
                                                     or local.get("sdk_metadata_attempted") is True,
                   "explicit_token_refresh_requested": False, "fallback_enabled": False,
                   "child_environment_keys": list(CHILD_ENV_KEYS),
                   "child_timeout_seconds": TIMEOUT_SECONDS,
                   "effective_config_provenance": "unverified", "config_evidence": CONFIG_EVIDENCE},
        "sources": [
            "https://pypi.org/pypi/openai-codex/0.156.1/json",
            SOURCE_ROOT + "rust-v0.156.1/sdk/python/src/openai_codex/api.py",
            SOURCE_ROOT + "rust-v0.156.1/sdk/python/src/openai_codex/client.py",
            SOURCE_ROOT + "rust-v0.156.1/sdk/python/src/openai_codex/generated/v2_all.py",
            SOURCE_ROOT + "rust-v0.153.4/codex-rs/cli/src/login.rs",
            SOURCE_ROOT + "rust-v0.153.4/codex-rs/login/src/auth/manager.rs",
            SOURCE_ROOT + "rust-v0.153.4/codex-rs/login/src/auth/personal_access_token.rs",
            *[SOURCE_ROOT + f"rust-v{version}/codex-rs/{path}" for version in
              INSPECTED_RUNTIME_VERSIONS for path in
              ("core/src/tools/spec_plan.rs", "ext/image-generation/src/tool.rs")],
        ],
        "scope": "Read-only metadata only; execution_enabled=false describes this diagnostic, "
                 "not the separate opt-in pipeline adapter. Live probes use scripts/codex_dev_probe.py.",
    }


def _bounded_command(command: Sequence[str], *, cwd: str) -> tuple[str, str]:
    """Discard stderr/raw errors; bound duration, readback, and descendant lifetime."""
    with tempfile.TemporaryFile() as output:
        try:
            process = subprocess.Popen(
                command, cwd=cwd, env=clean_child_env(os.environ), stdin=subprocess.DEVNULL,
                stdout=output, stderr=subprocess.DEVNULL, start_new_session=True,
            )
        except (OSError, ValueError):
            return "unavailable", ""
        status = "observed"
        try:
            process.wait(timeout=TIMEOUT_SECONDS)
            if process.returncode != 0:
                status = "failed"
        except subprocess.TimeoutExpired:
            status = "timeout"
        finally:
            # The diagnostic targets POSIX development machines. The process
            # group also covers children accidentally left behind by a runtime.
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()
        if status != "observed":
            return status, ""
        if output.tell() > MAX_OUTPUT_BYTES:
            return "failed", ""
        output.seek(0)
        return status, output.read(MAX_OUTPUT_BYTES).decode("utf-8", errors="replace")


def _installed_version(name: str) -> str | None:
    try:
        return _version(importlib.metadata.version(name))
    except Exception:
        # Broken/missing optional package metadata must not break this command.
        return None


def collect_local_evidence() -> dict[str, Any]:
    """Collect bounded metadata without starting any SDK thread or turn."""
    evidence: dict[str, Any] = {
        "sdk_version": _installed_version("openai-codex"),
        "bundled_runtime_version": _installed_version("openai-codex-cli-bin"),
        "sdk_schema_status": "unavailable", "local_runtime_status": "unavailable",
    }
    with tempfile.TemporaryDirectory(prefix="canary-codex-diagnostic-") as cwd:
        executable = shutil.which("codex")
        if executable:
            status, text = _bounded_command([str(Path(executable).resolve()), "--version"], cwd=cwd)
            match = re.fullmatch(r"codex-cli ([0-9]+(?:\.[0-9]+){1,3})\s*", text)
            evidence["local_runtime_status"] = status if status != "observed" or match else "failed"
            if match:
                evidence["local_runtime_version"] = match.group(1)
                if match.group(1) == "0.153.4" and evidence["sdk_version"] is None:
                    evidence["auth_inspection_attempted"] = True
                    auth_status, auth_text = _bounded_command(
                        [sys.executable, "-I", str(Path(__file__).resolve()), "--local-auth-child",
                         str(Path(executable).resolve())], cwd=cwd,
                    )
                    evidence["auth_status"] = auth_status
                    if auth_status == "observed":
                        try:
                            auth = json.loads(auth_text)
                            evidence["auth_status"] = auth["status"]
                            evidence["auth_mode"] = auth["mode"]
                        except (ValueError, KeyError, TypeError):
                            evidence["auth_status"] = "failed"
                elif match.group(1) == "0.153.4":
                    evidence["auth_status"] = "not_requested"
                else:
                    evidence["auth_status"] = "unsupported_version"
        if evidence["sdk_version"] == SDK_VERSION:
            status, text = _bounded_command(
                [sys.executable, "-I", str(Path(__file__).resolve()), "--local-schema-child"], cwd=cwd,
            )
            evidence["sdk_schema_status"] = status
            if status == "observed":
                try:
                    result = json.loads(text)
                    evidence["image_event_fields"] = result["image_event_fields"]
                except (ValueError, KeyError, TypeError):
                    evidence["sdk_schema_status"] = "failed"
            evidence["sdk_metadata_attempted"] = True
            status, text = _bounded_command(
                [sys.executable, "-I", str(Path(__file__).resolve()), "--sdk-metadata-child"], cwd=cwd,
            )
            evidence["account_status"] = status
            if status == "observed":
                try:
                    metadata = json.loads(text)
                    if not isinstance(metadata, dict):
                        raise ValueError("Invalid metadata shape")
                    evidence.update(metadata)
                except (ValueError, TypeError):
                    evidence["account_status"] = "failed"
        elif evidence["sdk_version"]:
            evidence["sdk_schema_status"] = "unsupported_version"
    return evidence


def _local_auth_child(executable: str) -> int:
    """Capture potentially identifying CLI output only in this isolated child."""
    try:
        result = subprocess.run(
            [executable, "login", "status"], stdin=subprocess.DEVNULL,
            capture_output=True, env=clean_child_env(os.environ), timeout=TIMEOUT_SECONDS - 2,
            check=False,
        )
        parsed = parse_login_status(
            result.returncode, (result.stdout + result.stderr).decode("utf-8", errors="replace"),
        )
    except subprocess.TimeoutExpired:
        parsed = {"status": "timeout", "mode": None}
    except (OSError, ValueError):
        parsed = {"status": "unavailable", "mode": None}
    print(json.dumps(parsed))
    return 0


def _local_schema_child() -> int:
    """Lazy schema import only. Intentionally never constructs AsyncCodex."""
    try:
        from openai_codex.generated.v2_all import ImageGenerationThreadItem

        fields = [field for field in IMAGE_FIELDS if field in ImageGenerationThreadItem.model_fields]
    except Exception:
        return 1
    print(json.dumps({"image_event_fields": fields}))
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--local-schema-child", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--local-auth-child", help=argparse.SUPPRESS)
    parser.add_argument("--sdk-metadata-child", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.local_schema_child:
        return _local_schema_child()
    if args.local_auth_child:
        return _local_auth_child(args.local_auth_child)
    if args.sdk_metadata_child:
        return _sdk_metadata_child()
    print(json.dumps(build_report(evidence=collect_local_evidence()), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
