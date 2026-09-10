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
from pathlib import Path
from typing import Any

from novel_to_comic.compiled_request import CompiledGenerationRequest
from novel_to_comic.image_models import ImageRoute

PROVIDER_WIRE_SCHEMA_VERSION = 3
PROVIDER_WIRE_DISCRIMINATOR = "canary.provider-wire/3"

# Slice 12 completes the non-panel migration. Keep this as an explicit empty
# ledger so architecture tests fail loudly if a raw caller is reintroduced.


class ProviderWireError(ValueError):
    """The exact wire request cannot be safely serialized."""


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
    provider_key: str
    configured_provider_model: str
    prompt_parts: tuple[str, ...]
    references: tuple[ProviderWireReference, ...]
    width: int
    height: int
    structured_aspect: str | None
    controls: tuple[tuple[str, Any], ...]
    compiled_request_sha256: str
    execution_fingerprint: str
    edit_parent_indices: tuple[int, ...] = ()
    def _fingerprint_projection(self) -> dict[str, Any]:
        data = asdict(self)
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
        return json.dumps(
            asdict(self), sort_keys=True, separators=(",", ":"), ensure_ascii=False
        )

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
            raw["edit_parent_indices"] = tuple(raw["edit_parent_indices"])
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


def _wire_prompt(compiled: CompiledGenerationRequest, edit_parent_indices: tuple[int, ...]) -> str:
    prompt = compiled.final_prompt
    if edit_parent_indices:
        parents = ", ".join(str(index) for index in edit_parent_indices)
        prompt += (
            f"\n\nImage operation: edit supplied parent image indices [{parents}] (zero-based). "
            "Preserve only their compatible identity and composition; canonical anchors, active states, "
            "and explicit changes outrank conflicting parent pixels. Other references retain their assigned roles."
        )
    else:
        prompt += (
            "\n\nImage operation: create a new image from the specification. "
            "Supplied references are scoped evidence, not edit parents. Rendering-only references "
            "do not supply scene layout, subject identity, or anatomy."
        )
    return prompt


def compile_provider_wire_request(
    compiled: CompiledGenerationRequest, *, edit_parent_indices: tuple[int, ...] = (),
) -> ProviderWireRequest:
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
    if any(index < 0 or index >= len(refs) or refs[index].role == "style" for index in edit_parent_indices):
        raise ProviderWireError("edit parents must identify supplied non-style references")
    width, height = compiled.effective_dimensions
    structured_aspect = None
    controls = tuple(sorted(compiled.controls.active_controls().items()))
    if compiled.provider_key == "codex-dev":
        from novel_to_comic.ai.codex_runtime import image_execution_controls
        from novel_to_comic.codex_dev import route_for

        route = route_for("image", compiled.requested_alias or "")
        if (
            route is None
            or compiled.expected_route is not ImageRoute.CODEX_BUILTIN
            or compiled.configured_provider_model != route.image_model
            or controls
            or len(refs) > 5
        ):
            raise ProviderWireError("compiled Codex image route/profile mismatch")
        controls = tuple(sorted((
            ("reasoning_model", route.reasoning_model),
            *image_execution_controls(),
        )))
    request = ProviderWireRequest(
        discriminator=PROVIDER_WIRE_DISCRIMINATOR,
        schema_version=PROVIDER_WIRE_SCHEMA_VERSION,
        requested_alias=compiled.requested_alias,
        expected_route=compiled.expected_route.value,
        provider_key=compiled.provider_key,
        configured_provider_model=compiled.configured_provider_model,
        prompt_parts=(_wire_prompt(compiled, edit_parent_indices),),
        references=refs,
        width=width,
        height=height,
        structured_aspect=structured_aspect,
        controls=controls,
        compiled_request_sha256=compiled.compiled_request_sha256,
        execution_fingerprint="",
        edit_parent_indices=edit_parent_indices,
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
    "compile_provider_wire_request", "materialize_wire_references",
]
