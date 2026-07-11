"""Direct Reve v2 layout-aware image provider.

Calls ``POST /v2/image/create`` on api.reve.com directly instead of going
through the LiteLLM gateway. The gateway's OpenAI-compatible image endpoints
cannot carry the structured request (per-reference prompts, region →
reference binding) or return the response's layout echo, so layout-aware
generation bypasses it. Flat Reve generation (no layout) keeps using the
gateway via LitellmHttpProvider.

Wire format (verified against reve-sdk v2):
    {
      "instruction": "<free text, max 4000 chars>",
      "description": {"prompt": "...", "regions": [
          {"label": "...", "prompt": "...",
           "bbox": {"x0": 0.0, "y0": 0.0, "x1": 1.0, "y1": 1.0},
           "image_index": 0}
      ]},
      "references": [{"image": {"data": "<b64>"}, "prompt": "..."}],
      "aspect_ratio": "3:2"
    }
"""

from __future__ import annotations

import base64
import os
import re
import time
from pathlib import Path
from typing import Any

import httpx

from novel_to_comic.ai.errors import AIRefusalError
from novel_to_comic.ai.providers.base import ProviderRawResult, RefImage
from novel_to_comic.config import Config
from novel_to_comic.models.prompt import PromptLayout

REVE_API_URL = "https://api.reve.com"
_INSTRUCTION_MAX_CHARS = 4000
_MAX_REFERENCES = 4
_REQUEST_TIMEOUT_S = 300.0

_ASPECT_RATIOS: dict[str, float] = {
    "1:1": 1.0,
    "3:2": 1.5,
    "2:3": 0.667,
    "4:3": 1.333,
    "3:4": 0.75,
    "16:9": 1.778,
    "9:16": 0.5625,
}


def _aspect_ratio_for(width: int, height: int) -> str:
    if width <= 0 or height <= 0:
        return "1:1"
    ratio = width / height
    return min(_ASPECT_RATIOS, key=lambda k: abs(_ASPECT_RATIOS[k] - ratio))


def _api_base() -> str:
    return (os.environ.get("REVE_API_HOST") or REVE_API_URL).rstrip("/")


def _api_key() -> str:
    key = (os.environ.get("REVE_API_KEY") or os.environ.get("REVE_API_TOKEN") or "").strip()
    if not key:
        raise ValueError(
            "REVE_API_KEY is not set — layout-aware generation calls api.reve.com "
            "directly and needs the key in the pipeline server environment."
        )
    return key


def _ref_binding_key(ref: RefImage) -> str | None:
    """Derive the reference's binding key from its path, matching how the
    direct stage assigns LayoutRegion.reference_key (character id from the
    char_* directory, prop id from the props/<id>/ directory)."""
    parts = ref.path.parts
    for index, part in enumerate(reversed(parts)):
        lowered = part.lower()
        if lowered.startswith(("char_", "character_", "chara_")):
            return part
        if lowered == "props":
            forward = len(parts) - index  # index of the part after "props"
            if forward < len(parts):
                return parts[forward]
    return None


def _reference_prompt(ref: RefImage) -> str:
    label = (ref.label or "").strip()
    if ref.role == "subject":
        return (
            f"Character identity reference for {label} — match face, hair, build, and wardrobe; do not copy its pose or background."
            if label
            else "Character identity reference — match face, hair, build, and wardrobe; do not copy its pose or background."
        )
    if ref.role == "style":
        return "Art style reference — match this rendering style exactly."
    if ref.role == "location_plate":
        return f"Location reference for {label}." if label else "Location reference."
    if ref.role == "prop":
        return f"Object reference for {label}." if label else "Object reference."
    if ref.role == "continuity":
        return "Previous panel — maintain visual continuity."
    return "Reference image."


class ReveLayoutProvider:
    name = "reve_layout"

    def request_params(
        self,
        *,
        model_alias: str,
        width: int,
        height: int,
        config: Config,  # noqa: ARG002
    ) -> dict[str, Any]:
        return {
            "model": model_alias,
            "size": f"{width}x{height}",
            "aspect_ratio": _aspect_ratio_for(width, height),
            "canary_requested_width": width,
            "canary_requested_height": height,
        }

    async def generate(
        self,
        *,
        model_alias: str,
        prompt: str,
        refs: list[RefImage],
        width: int,
        height: int,
        params: dict[str, Any] | None,
        config: Config,
        event_id: str,  # noqa: ARG002
        metadata: dict[str, Any],  # noqa: ARG002
    ) -> ProviderRawResult:
        request_params = params or self.request_params(
            model_alias=model_alias, width=width, height=height, config=config,
        )
        raw_layout = request_params.get("layout")
        if not raw_layout:
            raise ValueError("ReveLayoutProvider requires a layout in params")
        layout = PromptLayout.model_validate(raw_layout).sanitized()
        if not layout.regions:
            raise ValueError("ReveLayoutProvider received a layout with no usable regions")

        references, index_by_key = self._build_references(refs)
        payload: dict[str, Any] = {
            "instruction": _strip_inline_ref_tags(prompt or "")[:_INSTRUCTION_MAX_CHARS],
            "description": self._description(layout, index_by_key),
            "aspect_ratio": request_params.get("aspect_ratio") or _aspect_ratio_for(width, height),
        }
        if references:
            payload["references"] = references

        url = f"{_api_base()}/v2/image/create"
        headers = {
            "Authorization": f"Bearer {_api_key()}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        started = time.perf_counter()
        async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT_S) as client:
            response = await client.post(url, headers=headers, json=payload)
        data: dict[str, Any] = {}
        try:
            parsed = response.json()
            if isinstance(parsed, dict):
                data = parsed
        except Exception:
            pass
        if str(data.get("content_violation", "")).lower() in {"true", "1", "yes"}:
            raise AIRefusalError(
                "Reve flagged a content violation for this panel",
                response_data={k: v for k, v in data.items() if k != "image"},
                response_headers=response.headers,
                response=response,
            )
        if response.status_code >= 400:
            response.raise_for_status()

        encoded = data.get("image") or ""
        if isinstance(encoded, str) and encoded.startswith("data:") and "," in encoded:
            encoded = encoded.split(",", 1)[1]
        image_bytes = base64.b64decode(encoded) if encoded else b""
        if not image_bytes:
            raise ValueError(
                f"Reve v2 response contained no image data (request_id={data.get('request_id')})"
            )

        # Keep the response JSON for events/Langfuse, minus the image payload;
        # the description echo is the layout the model actually generated.
        raw_response = {k: v for k, v in data.items() if k != "image"}
        return ProviderRawResult(
            image_bytes=image_bytes,
            mime="image/png",
            latency_ms=int((time.perf_counter() - started) * 1000),
            provider_request_id=data.get("request_id"),
            raw_response=raw_response,
            response_headers=response.headers,
            request_params=request_params,
            layout_echo=data.get("description") if isinstance(data.get("description"), dict) else None,
        )

    def _build_references(
        self, refs: list[RefImage],
    ) -> tuple[list[dict[str, Any]], dict[str, int]]:
        """Encode refs in canonical upload order; map binding keys to indices."""
        if len(refs) > _MAX_REFERENCES:
            raise ValueError(
                f"Finalized reference plan exceeds Reve cap: {len(refs)} > {_MAX_REFERENCES}"
            )
        references: list[dict[str, Any]] = []
        index_by_key: dict[str, int] = {}
        for ref in refs:
            data = _read_ref_bytes(ref.path)
            if data is None:
                raise ValueError(f"Finalized reference became unreadable: {ref.path}")
            index = len(references)
            references.append({
                "image": {"data": base64.b64encode(data).decode("ascii")},
                "prompt": _reference_prompt(ref),
            })
            key = _ref_binding_key(ref)
            if key and key not in index_by_key:
                index_by_key[key] = index
        return references, index_by_key

    @staticmethod
    def _description(layout: PromptLayout, index_by_key: dict[str, int]) -> dict[str, Any]:
        regions: list[dict[str, Any]] = []
        for region in layout.regions:
            entry: dict[str, Any] = {
                "label": region.label,
                "prompt": region.prompt,
                "bbox": region.bbox.model_dump(),
            }
            key = (region.reference_key or "").strip()
            if key and key in index_by_key:
                entry["image_index"] = index_by_key[key]
            regions.append(entry)
        out: dict[str, Any] = {"regions": regions}
        if layout.prompt:
            out["prompt"] = layout.prompt
        return out


def _read_ref_bytes(path: Path) -> bytes | None:
    try:
        return path.read_bytes()
    except OSError:
        return None


_INLINE_REF_LINE_RE = re.compile(r"^.*<img>\d+</img>.*$", re.MULTILINE)


def _strip_inline_ref_tags(prompt: str) -> str:
    """Drop v1-remix positional <img>N</img> instructions from the prompt.

    The renderer emits them for Reve's v1 remix path; on v2 each reference
    carries its own prompt in the structured payload, so inline tags are
    noise in the instruction text.
    """
    if "<img>" not in prompt:
        return prompt
    cleaned = _INLINE_REF_LINE_RE.sub("", prompt)
    cleaned = cleaned.replace("Reference images:\n\n", "").replace("Reference images:\n", "")
    return re.sub(r"\n{3,}", "\n\n", cleaned).strip()
