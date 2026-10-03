"""Compact database projections; never modify provider or telemetry payloads."""
from __future__ import annotations

import hashlib
import json
from typing import Any


def fingerprint(value: Any) -> dict[str, Any]:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    return {"sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}


def _scalars(value: dict[str, Any], names: str) -> dict[str, Any]:
    return {
        key: item[:256] if isinstance(item, str) else item
        for key in names.split()
        if isinstance((item := value.get(key)), (str, int, float, bool))
    }


def compact_params(params: dict[str, Any]) -> dict[str, Any]:
    """Allowlist controls; opaque nested provider envelopes never reach SQL."""
    result = _scalars(params, "model temperature top_p max_tokens max_output_tokens max_completion_tokens "
                      "n size quality output_format background moderation response_format stream "
                      "reasoning_effort service_tier profile_id adapter_version execution_fingerprint request_sha256 "
                      "canary_requested_width canary_requested_height canary_requested_aspect")
    for key in ("response_format", "output_config", "canary_wire_request"):
        value = params.get(key)
        if value is not None and (key != "response_format" or isinstance(value, (dict, list))):
            result[key + "_summary"] = fingerprint(value)
    return result


def compact_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    result = _scalars(metadata, "page_number is_correction funding subscription_runtime "
                      "codex_reasoning_model pricing_estimate_drift_pct api_equivalent_cost_usd")
    context = metadata.get("metadata")
    if isinstance(context, dict):
        result.update(_scalars(context, "source_scope"))
        units = context.get("source_unit_ids")
        if isinstance(units, list) and units:
            result["source_units"] = {"count": len(units), **fingerprint(units)}
    runtime = metadata.get("codex_runtime")
    if isinstance(runtime, dict):
        result["codex_runtime"] = _scalars(runtime, "thread_id turn_id tool_id request_id "
            "turn_status funding usage_scope boundary execution_fingerprint prompt_sha256 "
            "requested_service_tier service_tier "
            "adapter_version profile_id transport_profile submitted indeterminate image_status "
            "completed_result_available execution_elapsed_seconds exception_type")
        error = runtime.get("provider_error")
        if isinstance(error, dict):
            result["codex_runtime"]["provider_error"] = _scalars(error, "code rpc_code http_status_code message")
    unsupported = metadata.get("unsupported_controls")
    if isinstance(unsupported, dict):
        result["unsupported_controls"] = _scalars(unsupported, "temperature max_output_tokens")
    return result
