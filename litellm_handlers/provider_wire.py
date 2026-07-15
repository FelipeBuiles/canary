"""Minimal isolated parser for ``canary.provider-wire/1`` manifests.

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

DISCRIMINATOR = "canary.provider-wire/1"
SCHEMA_VERSION = 1


def parse_provider_wire(payload: str) -> dict[str, Any]:
    try:
        manifest = json.loads(payload)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError("invalid ProviderWireRequest JSON") from exc
    if manifest.get("discriminator") != DISCRIMINATOR:
        raise ValueError("not a ProviderWireRequest")
    if manifest.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("unsupported ProviderWireRequest schema")
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
