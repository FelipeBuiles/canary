"""Redaction-safe projections of prepared and frozen image requests.

The preview layer is deliberately downstream of compilation and freezing.  It
never prepares prompts, resolves references, or calls a provider; an exact
preview is therefore always a projection of the persisted request record.
"""

from __future__ import annotations

import json
from pathlib import Path, PurePosixPath
from typing import Any

from novel_to_comic.frozen_requests import FrozenGenerationRequest
from novel_to_comic.compiled_request import COMPILED_REQUEST_SCHEMA_VERSION


PREVIEW_SCHEMA_VERSION = 1

_STATE_LABELS = {
    "prepared": "Prepared request",
    "submitted": "Submitted request",
    "queued": "Submitted request",
    "running": "Submitted request",
    "complete": "Completed request",
    "failed": "Completed request",
    "retained": "Completed request",
    "invalidated": "Draft projection",
}


def compiled_request_context(compiled: Any) -> dict[str, Any]:
    """Return the semantic portion safe to persist beside a frozen wire."""
    sections = [
        {
            "kind": section.kind,
            "title": section.title,
            "lines": list(section.lines),
        }
        for section in getattr(compiled, "sections", ())
    ]
    anchors = [
        {
            "kind": anchor.kind,
            "entity_id": anchor.entity_id,
            "name": anchor.name,
            "appearance_state_id": anchor.appearance_state_id,
            "text": anchor.text,
        }
        for anchor in getattr(compiled, "protected_anchors", ())
    ]
    dropped = []
    for item in getattr(getattr(compiled, "reference_plan", None), "dropped", ()):
        candidate = item.candidate
        dropped.append({
            "role": candidate.role,
            "entity_id": candidate.entity_id,
            "appearance_state_id": candidate.appearance_state_id,
            "reason": getattr(item.reason, "value", item.reason),
            "detail": item.detail,
        })
    return {
        "asset_kind": getattr(compiled, "asset_kind", None),
        "asset_identity": getattr(compiled, "asset_identity", None),
        "compiled_request_sha256": getattr(compiled, "compiled_request_sha256", None),
        "compiled_request_schema_version": COMPILED_REQUEST_SCHEMA_VERSION,
        "prompt_source_sha256": getattr(compiled, "prompt_source_sha256", None),
        "semantic_prompt": {
            "sections": sections,
            "final_prompt": getattr(compiled, "final_prompt", ""),
            "protected_anchors": anchors,
        },
        "dropped_references": dropped,
        "warnings": list(getattr(compiled, "warnings", ())),
    }


def _portable_wire(frozen: FrozenGenerationRequest) -> tuple[dict[str, Any], str]:
    wire = json.loads(frozen.wire.to_json())
    for reference, snapshot in zip(
        wire["references"], frozen.snapshots, strict=True,
    ):
        # This is the portable locator from the immutable manifest, never the
        # absolute path used by the transport adapter.
        reference["source_path"] = snapshot.locator
    encoded = json.dumps(
        wire, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    )
    return wire, encoded


def _safe_provenance(provenance: Any) -> Any:
    if isinstance(provenance, list):
        return [_safe_provenance(item) for item in provenance]
    if isinstance(provenance, dict):
        return {
            key: _safe_provenance(value)
            for key, value in provenance.items()
            if key not in {"path", "source_path", "locator", "signed_url", "url"}
        }
    return provenance


def _read_provenance(project_dir: Path, frozen: FrozenGenerationRequest) -> dict[str, Any] | None:
    links: list[str] = []
    if frozen.provenance_link:
        links.append(frozen.provenance_link)
    if frozen.result_link:
        links.extend([
            f"{frozen.result_link}.meta.json",
            f"{frozen.result_link}.failure.json",
        ])
    root = project_dir.resolve()
    for link in links:
        parsed = PurePosixPath(link)
        if parsed.is_absolute() or ".." in parsed.parts:
            continue
        path = project_dir.joinpath(*parsed.parts)
        try:
            path.resolve(strict=False).relative_to(root)
        except ValueError:
            continue
        if not path.is_file():
            continue
        try:
            value = json.loads(path.read_text())
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue
        if isinstance(value, dict):
            return _safe_provenance(value)
    return None


def frozen_request_preview(
    frozen: FrozenGenerationRequest | None,
    *,
    include_dev_content: bool = False,
    draft: dict[str, Any] | None = None,
    project_dir: Path | None = None,
) -> dict[str, Any]:
    """Project a draft or immutable request using the plan's state labels."""
    if frozen is None:
        draft = draft or {}
        result: dict[str, Any] = {
            "state_label": "Draft projection",
            "exact": False,
            "exactness": "non-exact",
            "warnings": list(draft.get("warnings", ())),
            "draft": {key: value for key, value in draft.items() if key != "warnings"},
        }
        return result

    state_label = _STATE_LABELS.get(frozen.status, "Submitted request")
    exact = state_label != "Draft projection"
    context = frozen.request_context or {}
    result = {
        "schema_version": PREVIEW_SCHEMA_VERSION,
        "state_label": state_label,
        "exact": exact,
        "exactness": "exact" if exact else "non-exact",
        "warnings": list(context.get("warnings", ())),
    }
    if frozen.status == "invalidated":
        result["warnings"].append("prepared request invalidated by an authoritative source change")

    if not include_dev_content:
        return result

    wire, wire_json = _portable_wire(frozen)
    semantic = context.get("semantic_prompt")
    result.update({
        "request_id": frozen.request_id,
        "execution_fingerprint": frozen.execution_fingerprint,
        "compiled_request_sha256": context.get("compiled_request_sha256", wire.get("compiled_request_sha256")),
        "prompt_source_sha256": context.get("prompt_source_sha256"),
        "asset_kind": context.get("asset_kind"),
        "asset_identity": context.get("asset_identity"),
        "semantic_prompt": semantic,
        "provider_wire": wire,
        "wire_json": wire_json,
        "requested_model": {
            "alias": wire.get("requested_alias"),
            "expected_route": wire.get("expected_route"),
            "provider_key": wire.get("provider_key"),
            "configured_target": wire.get("configured_provider_model"),
        },
        "geometry": {
            "requested_aspect": wire.get("structured_aspect"),
            "effective_dimensions": {
                "width": wire.get("width"),
                "height": wire.get("height"),
            },
        },
        "references": wire.get("references", []),
        "dropped_references": context.get("dropped_references", []),
        "controls": {
            "requested": dict(wire.get("controls", [])),
            "supported_or_filtered": dict(wire.get("controls", [])),
        },
        "versions": {
            "compiled_request": context.get("compiled_request_schema_version"),
            "provider_wire": frozen.wire.schema_version,
            "frozen_request": frozen.request_version,
        },
        "manifest_sha256": frozen.manifest_sha256,
        "submitted_at": frozen.submitted_at,
    })
    provenance = _read_provenance(project_dir, frozen) if project_dir else None
    if provenance is not None:
        result["provenance"] = provenance
        actual_model = provenance.get("actual_provider_model")
        actual_dimensions = provenance.get("actual_dimensions")
        if actual_model is not None:
            result["actual_model"] = actual_model
        if isinstance(actual_dimensions, dict) and any(
            value is not None for value in actual_dimensions.values()
        ):
            result["actual_dimensions"] = actual_dimensions
    return result


__all__ = ["PREVIEW_SCHEMA_VERSION", "compiled_request_context", "frozen_request_preview"]
