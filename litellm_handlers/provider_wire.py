"""Minimal isolated parser for ``canary.provider-wire/3`` manifests.

This module deliberately imports no application package.  It validates the
portable envelope used by custom LiteLLM handlers; semantic compilation stays
in the application.
"""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path
from typing import Any

DISCRIMINATOR = "canary.provider-wire/3"
SCHEMA_VERSION = 3


def _validate_manifest(manifest: dict[str, Any]) -> None:
    string_fields = (
        "expected_route", "provider_key", "configured_provider_model",
        "compiled_request_sha256", "execution_fingerprint",
    )
    fields = {
        "discriminator", "schema_version", "requested_alias", *string_fields,
        "prompt_parts", "references", "width", "height", "structured_aspect",
        "controls", "edit_parent_indices",
    }
    if set(manifest) != fields:
        raise ValueError("invalid ProviderWireRequest fields")
    if any(not isinstance(manifest[key], str) or not manifest[key] for key in string_fields):
        raise ValueError("invalid ProviderWireRequest string fields")
    for key in ("requested_alias", "structured_aspect"):
        if manifest[key] is not None and not isinstance(manifest[key], str):
            raise ValueError(f"invalid ProviderWireRequest {key}")
    for key in ("width", "height"):
        if type(manifest[key]) is not int or manifest[key] <= 0:
            raise ValueError(f"invalid ProviderWireRequest {key}")
    prompts = manifest["prompt_parts"]
    if not isinstance(prompts, list) or not prompts or any(not isinstance(p, str) for p in prompts):
        raise ValueError("invalid ProviderWireRequest prompt parts")
    controls = manifest["controls"]
    if not isinstance(controls, list) or any(
        not isinstance(pair, list) or len(pair) != 2 or not isinstance(pair[0], str)
        for pair in controls
    ):
        raise ValueError("invalid ProviderWireRequest controls")
    refs = manifest["references"]
    if not isinstance(refs, list):
        raise ValueError("invalid ProviderWireRequest references")
    ref_strings = (
        "source_path", "content_sha256", "role", "role_label", "instruction",
        "provider_binding", "authority_scope",
    )
    ref_fields = {
        "index", *ref_strings, "entity_id", "appearance_state_id",
        "preserve_facets", "ignore_facets",
    }
    for index, ref in enumerate(refs):
        if not isinstance(ref, dict) or set(ref) != ref_fields:
            raise ValueError("invalid ProviderWireRequest reference fields")
        if type(ref["index"]) is not int or ref["index"] != index or ref["provider_binding"] != str(index):
            raise ValueError("invalid ProviderWireRequest reference order")
        if any(not isinstance(ref[key], str) for key in ref_strings):
            raise ValueError("invalid ProviderWireRequest reference strings")
        for key in ("entity_id", "appearance_state_id"):
            if ref[key] is not None and not isinstance(ref[key], str):
                raise ValueError(f"invalid ProviderWireRequest reference {key}")
        for key in ("preserve_facets", "ignore_facets"):
            if not isinstance(ref[key], list) or any(not isinstance(f, str) for f in ref[key]):
                raise ValueError(f"invalid ProviderWireRequest reference {key}")
    parents = manifest["edit_parent_indices"]
    if not isinstance(parents, list) or any(
        type(index) is not int or index < 0 or index >= len(refs) or refs[index]["role"] == "style"
        for index in parents
    ):
        raise ValueError("edit parents must identify supplied non-style references")
    if len(set(parents)) != len(parents):
        raise ValueError("duplicate ProviderWireRequest edit parents")
    digests = [
        manifest["compiled_request_sha256"], manifest["execution_fingerprint"],
        *(ref["content_sha256"] for ref in refs),
    ]
    if any(len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest) for digest in digests):
        raise ValueError("invalid ProviderWireRequest digest")


def parse_provider_wire(payload: str) -> dict[str, Any]:
    try:
        manifest = json.loads(payload)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError("invalid ProviderWireRequest JSON") from exc
    if not isinstance(manifest, dict):
        raise ValueError("invalid ProviderWireRequest object")
    if manifest.get("discriminator") != DISCRIMINATOR:
        raise ValueError("not a ProviderWireRequest")
    if type(manifest.get("schema_version")) is not int or manifest["schema_version"] != SCHEMA_VERSION:
        raise ValueError("unsupported ProviderWireRequest schema")
    _validate_manifest(manifest)
    supplied = manifest.get("execution_fingerprint")
    # Fingerprint projection must not mutate the parsed request that the
    # adapter subsequently consumes (references are nested dictionaries).
    projection = deepcopy(manifest)
    projection.pop("execution_fingerprint", None)
    for ref in projection.get("references", []):
        ref.pop("source_path", None)
    actual = hashlib.sha256(json.dumps(
        projection, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    ).encode("utf-8")).hexdigest()
    if supplied != actual:
        raise ValueError("ProviderWireRequest execution fingerprint mismatch")
    return manifest


def exact_vertex_contents(manifest: dict[str, Any], image_parts: list[Any]) -> list[Any]:
    """Place reference bytes before their instructions and final prompt.

    Vertex's multimodal prompting guidance recommends image-first ordering for
    single-image requests.  Keeping every image adjacent to its compiler-owned
    instruction preserves that advantage for multi-reference requests without
    letting the isolated adapter author labels or semantic prose.
    """
    refs = manifest.get("references", [])
    if len(refs) != len(image_parts):
        raise ValueError("ProviderWireRequest reference count mismatch")
    contents: list[Any] = []
    for ref, part in zip(refs, image_parts, strict=True):
        contents.extend((part, ref["instruction"]))
    contents.extend(manifest.get("prompt_parts", []))
    return contents


def _item_bytes(item: Any) -> bytes | None:
    value = item[1] if isinstance(item, tuple) and len(item) > 1 else item
    if isinstance(value, bytes):
        return value
    if isinstance(value, bytearray):
        return bytes(value)
    if isinstance(value, str) and Path(value).is_file():
        return Path(value).read_bytes()
    reader = getattr(value, "read", None)
    if callable(reader):
        seeker = getattr(value, "seek", None)
        if callable(seeker):
            seeker(0)
        data = reader()
        if callable(seeker):
            seeker(0)
        return data if isinstance(data, bytes) else None
    return None


def verify_wire_images(manifest: dict[str, Any], images: list[Any]) -> None:
    refs = manifest.get("references", [])
    if len(refs) != len(images):
        raise ValueError("ProviderWireRequest reference count mismatch")
    for index, (ref, item) in enumerate(zip(refs, images, strict=True)):
        data = _item_bytes(item)
        if data is None:
            raise ValueError(f"ProviderWireRequest reference {index} is unreadable")
        if hashlib.sha256(data).hexdigest() != ref["content_sha256"]:
            raise ValueError(f"ProviderWireRequest reference {index} digest mismatch")
