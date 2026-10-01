"""Common redaction-safe provenance for every generated image asset."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from novel_to_comic.compiled_request import COMPILED_REQUEST_SCHEMA_VERSION
from novel_to_comic.frozen_requests import (
    FROZEN_REQUEST_PREPARATION_VERSION,
    FROZEN_REQUEST_SOURCE_VERSION,
    FROZEN_REQUEST_VERSION,
)
from novel_to_comic.provider_wire import PROVIDER_WIRE_SCHEMA_VERSION
from novel_to_comic.workspace import series_root

IMAGE_PROVENANCE_SCHEMA_VERSION = 1


def _redact(value: Any, project_dir: Path | None) -> str:
    text = str(value)
    if project_dir is not None:
        try:
            text = text.replace(str(project_dir.resolve()), "<project>")
            text = text.replace(str(project_dir.resolve().parent), "<workspace>")
        except OSError:
            pass
    return text


def _reference_record(asset: Any, index: int, project_dir: Path | None) -> dict[str, Any]:
    path = str(asset.path) if project_dir is not None else None
    if project_dir is not None:
        try:
            # References are series-level Look assets, even for part pages.
            path = str(asset.path.relative_to(series_root(project_dir)))
        except ValueError:
            path = "<external-reference>"
    scope = getattr(asset.authority_scope, "value", asset.authority_scope)
    return {
        "index": index,
        "path": path,
        "role": asset.role,
        "entity_id": asset.entity_id,
        "appearance_state_id": asset.appearance_state_id,
        "authority_scope": scope,
        "preserve_facets": list(asset.preserve_facets),
        "ignore_facets": list(asset.ignore_facets),
        "content_sha256": asset.content_sha256,
        "lineage_parent_sha256": getattr(asset, "lineage_parent_sha256", None),
    }


def _stable_hash(record: dict[str, Any]) -> str:
    projection = {
        key: value for key, value in record.items()
        if key not in {"started_at", "latency_ms"}
    }
    return hashlib.sha256(
        json.dumps(projection, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


def common_image_provenance(
    *,
    asset_kind: str,
    asset_identity: str,
    compiled_sha256: str | None,
    prompt_source_sha256: str | None,
    wire: Any,
    reference_plan: Any,
    request_id: str | None,
    actual_width: int | None = None,
    actual_height: int | None = None,
    actual_provider_model: str | None = None,
    provider_request_id: str | None = None,
    latency_ms: int | None = None,
    cost_usd: float | None = None,
    failure: dict[str, Any] | None = None,
    project_dir: Path | None = None,
    lineage: dict[str, Any] | None = None,
    response_metadata: dict[str, Any] | None = None,
    funding: str = "api",
) -> dict[str, Any]:
    selected = [
        _reference_record(asset, index, project_dir)
        for index, asset in enumerate(getattr(reference_plan, "selected", ()))
    ]
    dropped = []
    for drop in getattr(reference_plan, "dropped", ()):
        candidate = drop.candidate
        dropped.append({
            "role": candidate.role,
            "entity_id": candidate.entity_id,
            "appearance_state_id": candidate.appearance_state_id,
            "reason": getattr(drop.reason, "value", drop.reason),
            "detail": _redact(drop.detail, project_dir),
        })
    record: dict[str, Any] = {
        "schema_version": IMAGE_PROVENANCE_SCHEMA_VERSION,
        "asset_kind": asset_kind,
        "asset_identity": asset_identity,
        "compiled_request_schema_version": COMPILED_REQUEST_SCHEMA_VERSION,
        "prepared_prompt_source_sha256": prompt_source_sha256,
        "compiled_request_sha256": compiled_sha256,
        "provider_wire_schema_version": getattr(wire, "schema_version", PROVIDER_WIRE_SCHEMA_VERSION),
        "frozen_request_preparation_version": FROZEN_REQUEST_PREPARATION_VERSION,
        "frozen_request_source_version": FROZEN_REQUEST_SOURCE_VERSION,
        "frozen_request_version": FROZEN_REQUEST_VERSION,
        "request_id": request_id,
        "execution_fingerprint": getattr(wire, "execution_fingerprint", None),
        "reference_selection_fingerprint": getattr(reference_plan, "selection_fingerprint", None),
        "selected_references": selected,
        "dropped_candidates": dropped,
        "warnings": [_redact(warning, project_dir) for warning in getattr(reference_plan, "warnings", ())],
        "requested_alias": getattr(wire, "requested_alias", None),
        "expected_route": getattr(wire, "expected_route", None),
        "provider_key": getattr(wire, "provider_key", None),
        "configured_provider_model": getattr(wire, "configured_provider_model", None),
        "actual_provider_model": actual_provider_model,
        "actual_provider_model_status": "observed" if actual_provider_model else "UNKNOWN",
        "dimension_control": "prompt_intent" if getattr(wire, "provider_key", None) == "codex-dev" else "provider_parameters",
        "requested_dimensions": {
            "width": getattr(wire, "width", None),
            "height": getattr(wire, "height", None),
        },
        "effective_dimensions": {
            "width": getattr(wire, "width", None),
            "height": getattr(wire, "height", None),
        } if getattr(wire, "provider_key", None) != "codex-dev" else None,
        "actual_dimensions": {"width": actual_width, "height": actual_height},
        "controls": dict(getattr(wire, "controls", ())),
        "provider_request_id": provider_request_id,
        "funding": funding,
        "response_metadata": response_metadata,
        "latency_ms": latency_ms,
        "cost_usd": cost_usd,
        "failure": (
            {
                **failure,
                "message": _redact(failure.get("message", ""), project_dir),
            }
            if isinstance(failure, dict) else failure
        ),
        "lineage": lineage,
        "started_at": datetime.now(UTC).isoformat(),
    }
    record["provenance_record_hash"] = _stable_hash(record)
    return record


def failed_image_provenance(error: BaseException, *, asset_kind: str, asset_identity: str, project_dir: Path | None = None) -> dict[str, Any]:
    record: dict[str, Any] = {
        "schema_version": IMAGE_PROVENANCE_SCHEMA_VERSION,
        "asset_kind": asset_kind,
        "asset_identity": asset_identity,
        "compiled_request_schema_version": COMPILED_REQUEST_SCHEMA_VERSION,
        "provider_wire_schema_version": PROVIDER_WIRE_SCHEMA_VERSION,
        "frozen_request_preparation_version": FROZEN_REQUEST_PREPARATION_VERSION,
        "frozen_request_source_version": FROZEN_REQUEST_SOURCE_VERSION,
        "frozen_request_version": FROZEN_REQUEST_VERSION,
        "request_id": None,
        "execution_fingerprint": None,
        "failure": {"type": type(error).__name__, "message": _redact(error, project_dir)},
        "started_at": datetime.now(UTC).isoformat(),
    }
    record["provenance_record_hash"] = _stable_hash(record)
    return record


__all__ = [
    "IMAGE_PROVENANCE_SCHEMA_VERSION",
    "common_image_provenance",
    "failed_image_provenance",
]
