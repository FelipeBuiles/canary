"""Portable, versioned provider-bound image request contract.

The wire compiler is the sole owner of provider syntax.  Transports and
isolated handlers may parse and serialize this manifest, but must not add
semantic prose, reorder/cap references, or reinterpret authority.
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
from dataclasses import asdict, dataclass, replace
from collections.abc import Mapping, Sequence
from pathlib import Path
from types import MappingProxyType
from typing import Any

from novel_to_comic.compiled_request import CompiledGenerationRequest
from novel_to_comic.image_models import ImageRoute
from novel_to_comic.models.prompt import PromptLayout
from novel_to_comic.panel_aspect import (
    REVE_LAYOUT_MAX_DIMENSION,
    REVE_LAYOUT_MAX_PIXELS,
    REVE_LAYOUT_MIN_PIXELS,
    aspect_for_dimensions,
    dimensions_for_reve_layout,
)

PROVIDER_WIRE_SCHEMA_VERSION = 1
PROVIDER_WIRE_DISCRIMINATOR = "canary.provider-wire/1"

# Slice 12 completes the non-panel migration. Keep this as an explicit empty
# ledger so architecture tests fail loudly if a raw caller is reintroduced.


class ProviderWireError(ValueError):
    """The exact wire request cannot be safely serialized."""


class _FrozenMapping(Mapping[str, Any]):
    """Read-only mapping used inside a frozen wire request."""

    __slots__ = ("_data",)

    def __init__(self, values: Mapping[str, Any]) -> None:
        self._data = MappingProxyType(dict(values))

    def __getitem__(self, key: str) -> Any:
        return self._data[key]

    def __iter__(self):
        return iter(self._data)

    def __len__(self) -> int:
        return len(self._data)

    def __eq__(self, other: object) -> bool:
        return self._data == other

    def __deepcopy__(self, _memo: dict[int, Any]) -> "_FrozenMapping":
        return self


class _FrozenSequence(Sequence[Any]):
    """Read-only sequence used inside a frozen wire request."""

    __slots__ = ("_data",)

    def __init__(self, values: Sequence[Any]) -> None:
        self._data = tuple(values)

    def __getitem__(self, index):
        return self._data[index]

    def __len__(self) -> int:
        return len(self._data)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, Sequence) and not isinstance(other, (str, bytes, bytearray)):
            return tuple(other) == self._data
        return False

    def __deepcopy__(self, _memo: dict[int, Any]) -> "_FrozenSequence":
        return self


def _freeze_layout(value: Any) -> Any:
    if isinstance(value, Mapping):
        return _FrozenMapping({key: _freeze_layout(item) for key, item in value.items()})
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return _FrozenSequence([_freeze_layout(item) for item in value])
    return value


def _thaw_layout(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _thaw_layout(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_thaw_layout(item) for item in value]
    return value


@dataclass(frozen=True, slots=True)
class ProviderWireReference:
    index: int
    source_path: str
    content_sha256: str
    role: str
    role_label: str
    instruction: str
    provider_binding: str
    entity_id: str | None
    appearance_state_id: str | None
    authority_scope: str
    preserve_facets: tuple[str, ...]
    ignore_facets: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ProviderWireRequest:
    discriminator: str
    schema_version: int
    requested_alias: str | None
    expected_route: str
    configured_provider_model: str
    prompt_parts: tuple[str, ...]
    references: tuple[ProviderWireReference, ...]
    width: int
    height: int
    structured_aspect: str | None
    controls: tuple[tuple[str, Any], ...]
    compiled_request_sha256: str
    execution_fingerprint: str
    # Strict Reve v2 render_layout payload, already bound to the final
    # reference indices. None keeps the existing flat-provider path intact.
    layout: Mapping[str, Any] | None = None

    def __post_init__(self) -> None:
        if self.layout is not None:
            if not isinstance(self.layout, Mapping):
                raise ProviderWireError("ProviderWireRequest layout must be an object")
            object.__setattr__(self, "layout", _freeze_layout(self.layout))

    def layout_payload(self) -> dict[str, Any] | None:
        """Return a detached JSON-compatible copy for provider transport."""
        return _thaw_layout(self.layout) if self.layout is not None else None

    def _fingerprint_projection(self) -> dict[str, Any]:
        data = asdict(self)
        data["layout"] = self.layout_payload()
        data.pop("execution_fingerprint", None)
        # Local paths locate bytes during the temporary pre-freeze era; they do
        # not affect provider execution. Their verified digests do.
        for ref in data["references"]:
            ref.pop("source_path", None)
        return data

    def recompute_execution_fingerprint(self) -> str:
        encoded = json.dumps(
            self._fingerprint_projection(), sort_keys=True, separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def to_json(self) -> str:
        data = asdict(self)
        data["layout"] = self.layout_payload()
        return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)

    @classmethod
    def from_json(cls, payload: str) -> "ProviderWireRequest":
        try:
            raw = json.loads(payload)
            if raw.get("discriminator") != PROVIDER_WIRE_DISCRIMINATOR:
                raise ProviderWireError("not a ProviderWireRequest payload")
            if raw.get("schema_version") != PROVIDER_WIRE_SCHEMA_VERSION:
                raise ProviderWireError(f"unsupported provider wire schema: {raw.get('schema_version')}")
            raw["prompt_parts"] = tuple(raw["prompt_parts"])
            raw["controls"] = tuple((str(k), v) for k, v in raw["controls"])
            raw["references"] = tuple(
                ProviderWireReference(
                    **{
                        **ref,
                        "preserve_facets": tuple(ref["preserve_facets"]),
                        "ignore_facets": tuple(ref["ignore_facets"]),
                    }
                )
                for ref in raw["references"]
            )
            request = cls(**raw)
        except (KeyError, TypeError, json.JSONDecodeError) as exc:
            raise ProviderWireError("invalid ProviderWireRequest payload") from exc
        if request.execution_fingerprint != request.recompute_execution_fingerprint():
            raise ProviderWireError("ProviderWireRequest execution fingerprint mismatch")
        return request


def _role_label(role: str, label: str | None) -> str:
    return f"{role}:{label}" if label else role


def _wire_prompt(compiled: CompiledGenerationRequest) -> str:
    prompt = compiled.final_prompt
    if compiled.expected_route is ImageRoute.REVE:
        for instruction in compiled.reference_instructions:
            prompt = prompt.replace(
                instruction.marker, f"<frame>{instruction.index}</frame>"
            )
    return prompt


def without_layout(request: ProviderWireRequest) -> ProviderWireRequest:
    """Derive the exact flat v2-create request used by rollout fallback.

    The original request remains unchanged. The returned request has its own
    execution fingerprint, while retaining the compiler-owned flat prompt and
    ordered reference bytes needed by the ordinary v2 create path.
    """
    if request.layout is None:
        return request
    updated = replace(request, layout=None, execution_fingerprint="")
    return replace(updated, execution_fingerprint=updated.recompute_execution_fingerprint())


def _wire_layout(
    compiled: CompiledGenerationRequest,
    refs: tuple[ProviderWireReference, ...],
) -> dict[str, Any] | None:
    """Project semantic layout IR into Reve's strict render_layout shape."""
    if compiled.expected_route is not ImageRoute.REVE or not compiled.layout:
        return None
    layout = PromptLayout.model_validate(compiled.layout).sanitized()
    if not layout.regions:
        return None

    reference_indices: dict[str, int] = {}
    for ref in refs:
        if ref.entity_id:
            reference_indices.setdefault(ref.entity_id, ref.index)

    frame_width, frame_height = dimensions_for_reve_layout(*compiled.effective_dimensions)
    if (
        layout.width
        and layout.height
        and layout.width <= REVE_LAYOUT_MAX_DIMENSION
        and layout.height <= REVE_LAYOUT_MAX_DIMENSION
        and layout.width * layout.height >= REVE_LAYOUT_MIN_PIXELS
        and layout.width * layout.height <= REVE_LAYOUT_MAX_PIXELS
    ):
        frame_width, frame_height = layout.width, layout.height

    regions: list[dict[str, Any]] = []
    for region in layout.regions:
        entry: dict[str, Any] = {
            "label": region.label,
            "prompt": region.prompt,
            "bbox": region.bbox.model_dump(mode="json"),
        }
        if region.parent:
            entry["parent"] = region.parent
        if region.region_type:
            entry["region_type"] = region.region_type
        if region.image_region_index is not None:
            entry["image_region_index"] = region.image_region_index
        if region.reference_key and region.reference_key in reference_indices:
            entry["image_index"] = reference_indices[region.reference_key]
        regions.append(entry)

    payload: dict[str, Any] = {
        "regions": regions,
        "width": frame_width,
        "height": frame_height,
        # render_layout has no separate prompt field. This is the exact
        # provider-independent instruction that would otherwise be sent as the
        # flat prompt, so anchors/style/constraints remain in the request.
        "normalized_edit_instruction": compiled.final_prompt,
    }
    if layout.prompt:
        payload["prompt"] = layout.prompt
    return payload


def compile_provider_wire_request(compiled: CompiledGenerationRequest) -> ProviderWireRequest:
    """Compile exact provider syntax from a finalized compiled request."""
    if len(compiled.reference_plan.selected) != len(compiled.reference_instructions):
        raise ProviderWireError("selected references and instructions are not one-to-one")
    refs = tuple(
        ProviderWireReference(
            index=index,
            source_path=str(asset.path),
            content_sha256=asset.content_sha256,
            role=asset.role,
            role_label=_role_label(asset.role, asset.label),
            instruction=instruction.semantic_instruction,
            provider_binding=str(index),
            entity_id=asset.entity_id,
            appearance_state_id=asset.appearance_state_id,
            authority_scope=asset.authority_scope.value,
            preserve_facets=instruction.preserve_facets,
            ignore_facets=instruction.ignore_facets,
        )
        for index, (asset, instruction) in enumerate(
            zip(compiled.reference_plan.selected, compiled.reference_instructions, strict=True)
        )
    )
    width, height = compiled.effective_dimensions
    structured_aspect = None
    if compiled.expected_route is ImageRoute.REVE:
        ratio = aspect_for_dimensions(width, height)
        modes = {
            "4:1": 4.0,
            "3:1": 3.0,
            "21:9": 21 / 9,
            "2:1": 2.0,
            "17:9": 17 / 9,
            "16:9": 16 / 9,
            "3:2": 1.5,
            "4:3": 4 / 3,
            "5:4": 1.25,
            "1:1": 1.0,
            "4:5": 0.8,
            "3:4": 3 / 4,
            "2:3": 2 / 3,
            "9:16": 9 / 16,
            "1:2": 0.5,
            "1:3": 1 / 3,
            "1:4": 0.25,
        }
        structured_aspect = min(modes, key=lambda key: abs(modes[key] - ratio))
    layout = _wire_layout(compiled, refs)
    request = ProviderWireRequest(
        discriminator=PROVIDER_WIRE_DISCRIMINATOR,
        schema_version=PROVIDER_WIRE_SCHEMA_VERSION,
        requested_alias=compiled.requested_alias,
        expected_route=compiled.expected_route.value,
        configured_provider_model=compiled.configured_provider_model,
        # Keep the flat v2-create form available even when the primary request
        # uses render_layout. The layout adapter consumes ``layout`` and the
        # rollout fallback consumes this exact prompt/reference ordering.
        prompt_parts=(_wire_prompt(compiled),),
        references=refs,
        width=width,
        height=height,
        structured_aspect=structured_aspect,
        controls=tuple(sorted(compiled.controls.active_controls().items())),
        compiled_request_sha256=compiled.compiled_request_sha256,
        execution_fingerprint="",
        layout=layout,
    )
    return replace(request, execution_fingerprint=request.recompute_execution_fingerprint())


def materialize_wire_references(request: ProviderWireRequest) -> tuple[bytes, ...]:
    """Read and digest-check every selected reference without skipping."""
    loaded: list[bytes] = []
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    for ref in request.references:
        descriptor = -1
        try:
            path = Path(ref.source_path)
            descriptor = os.open(path, os.O_RDONLY | nofollow)
            file_stat = os.fstat(descriptor)
            if (
                not stat.S_ISREG(file_stat.st_mode)
                or file_stat.st_nlink != 1
            ):
                raise OSError("selected reference is not an independent regular file")
            with os.fdopen(os.dup(descriptor), "rb") as handle:
                data = handle.read()
        except OSError as exc:
            raise ProviderWireError(f"selected reference {ref.index} is unreadable") from exc
        finally:
            if descriptor >= 0:
                os.close(descriptor)
        actual = hashlib.sha256(data).hexdigest()
        if actual != ref.content_sha256:
            raise ProviderWireError(
                f"selected reference {ref.index} digest mismatch: expected "
                f"{ref.content_sha256}, got {actual}"
            )
        loaded.append(data)
    return tuple(loaded)


__all__ = [
    "PROVIDER_WIRE_DISCRIMINATOR", "PROVIDER_WIRE_SCHEMA_VERSION",
    "ProviderWireError", "ProviderWireReference", "ProviderWireRequest",
    "compile_provider_wire_request", "materialize_wire_references", "without_layout",
]
