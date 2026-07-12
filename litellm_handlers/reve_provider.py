"""LiteLLM custom provider for Reve image generation and remix endpoints."""

from __future__ import annotations

import asyncio
import base64
import os
import re
import time
from pathlib import Path
from typing import Any

import httpx
try:
    from litellm.llms.custom_llm import CustomLLM
    from litellm.types.utils import ImageObject, ImageResponse
except ModuleNotFoundError:
    class CustomLLM:
        pass

    class ImageObject:
        def __init__(self, b64_json=None):
            self.b64_json = b64_json

    class ImageResponse:
        def __init__(self):
            self.created = None
            self.data = []
            self.model = None
            self._hidden_params = {}

REVE_ASPECT_RATIOS = {
    "1:1": 1.0,
    "3:2": 1.5,
    "2:3": 0.667,
    "4:3": 1.333,
    "3:4": 0.75,
    "16:9": 1.778,
    "9:16": 0.5625,
}

_ROLE_PREFIX = "__role_"
_ROLE_SEP = "__"
_GENERIC_STEMS = frozenset({
    "image", "img", "photo", "reference", "ref", "portrait", "figure",
    "asset", "texture", "render", "file", "input", "output", "result",
    "sample", "test", "temp", "tmp", "character", "char", "subject",
})

def _log_request(url: str, api_key: str | None, payload: dict[str, Any]) -> None:
    import sys
    import json
    _headers(api_key)  # Validate configuration without logging the credential.
    descriptor = {
        "endpoint": url.rsplit("/", 1)[-1],
        "prompt_length": len(str(payload.get("prompt") or "")),
        "reference_count": len(payload.get("reference_images") or []),
        "aspect_ratio": payload.get("aspect_ratio"),
        "control_keys": sorted(
            key for key in payload
            if key not in {"prompt", "reference_images", "references", "aspect_ratio"}
        ),
    }
    sys.stderr.write(f"REVE request {json.dumps(descriptor, sort_keys=True)}\n")
    sys.stderr.flush()


def _log_response(response: httpx.Response) -> None:
    import sys
    import json
    descriptor: dict[str, Any] = {"status_code": response.status_code}
    try:
        resp_data = response.json()
        descriptor["response_keys"] = (
            sorted(resp_data) if isinstance(resp_data, dict) else []
        )
    except Exception:
        descriptor["response_json"] = False
    sys.stderr.write(f"REVE response {json.dumps(descriptor, sort_keys=True)}\n")
    sys.stderr.flush()


class ReveLLM(CustomLLM):
    """Custom LiteLLM provider for Reve API (api.reve.com)."""

    def image_generation(
        self,
        model: str,
        prompt: str,
        model_response: ImageResponse,
        api_key: str | None = None,
        api_base: str | None = None,  # noqa: ARG002
        optional_params: dict[str, Any] | None = None,
        logging_obj: Any | None = None,  # noqa: ARG002
        timeout: float | httpx.Timeout | None = None,
        client: Any | None = None,  # noqa: ARG002
        **kwargs: Any,
    ) -> ImageResponse:
        return asyncio.run(self.aimage_generation(
            model=model,
            prompt=prompt,
            api_key=api_key,
            api_base=api_base,
            model_response=model_response,
            optional_params=optional_params or {},
            logging_obj=logging_obj,
            timeout=timeout,
            client=client,
            **kwargs,
        ))

    async def aimage_generation(
        self,
        model: str,
        prompt: str,
        api_key: str | None,
        api_base: str | None,  # noqa: ARG002
        model_response: ImageResponse,
        optional_params: dict[str, Any],
        logging_obj: Any,  # noqa: ARG002
        timeout: float | httpx.Timeout | None = None,
        client: Any | None = None,  # noqa: ARG002
        **kwargs: Any,
    ) -> ImageResponse:
        wire_payload = optional_params.get("canary_wire_request")
        if not wire_payload:
            raise ValueError("Reve image requests require canary_wire_request")
        from litellm_handlers.provider_wire import parse_provider_wire

        wire_manifest = parse_provider_wire(wire_payload)
        aspect_ratio = wire_manifest.get("structured_aspect") or "1:1"

        # v1 create. The v2 layout-aware endpoint is gated behind the Reve
        # partner feature `partnerapi.layout_endpoint` (403 FEATURE_NOT_ENABLED
        # without it), so the gateway stays on v1. Note v1 has no exact-pixel
        # sizing — width/height are rejected as UNRECOGNIZED_PARAMETER;
        # aspect_ratio is the only sizing knob.
        final_prompt = wire_manifest["prompt_parts"][0]
        payload: dict[str, Any] = {
            "prompt": final_prompt,
            "aspect_ratio": aspect_ratio,
        }
        payload.update(wire_manifest.get("controls") or {})

        request_timeout = timeout if timeout is not None else 300.0
        _log_request("https://api.reve.com/v1/image/create", api_key, payload)
        async with httpx.AsyncClient(timeout=request_timeout) as http:
            response = await http.post(
                "https://api.reve.com/v1/image/create",
                headers=_headers(api_key),
                json=payload,
            )
            _log_response(response)
            _raise_for_status(response)
            data = response.json()
        _raise_for_content_violation(data)

        b64 = _extract_b64(data)
        if isinstance(b64, str) and (b64.startswith("http://") or b64.startswith("https://")):
            async with httpx.AsyncClient() as http:
                img_resp = await http.get(b64)
                img_resp.raise_for_status()
                b64 = base64.b64encode(img_resp.content).decode("ascii")
        elif isinstance(b64, str) and b64.startswith("data:"):
            if "," in b64:
                b64 = b64.split(",", 1)[1]

        model_response.created = int(time.time())
        model_response.data = [ImageObject(b64_json=b64)]
        actual_model = data.get("model") if isinstance(data.get("model"), str) else model
        model_response.model = actual_model
        model_response._hidden_params["model"] = actual_model
        model_response._hidden_params["custom_llm_provider"] = "reve"
        model_response._hidden_params["response_cost"] = 0.04
        return model_response

    def image_edit(
        self,
        model: str,
        image: list[Any],
        prompt: str | None,
        model_response: ImageResponse,
        api_key: str | None = None,
        api_base: str | None = None,  # noqa: ARG002
        optional_params: dict[str, Any] | None = None,
        logging_obj: Any | None = None,  # noqa: ARG002
        timeout: float | httpx.Timeout | None = None,
        client: Any | None = None,  # noqa: ARG002
        **kwargs: Any,
    ) -> ImageResponse:
        return asyncio.run(self.aimage_edit(
            model=model,
            image=image,
            prompt=prompt,
            model_response=model_response,
            api_key=api_key,
            api_base=api_base,
            optional_params=optional_params or {},
            logging_obj=logging_obj,
            timeout=timeout,
            client=client,
            **kwargs,
        ))

    async def aimage_edit(
        self,
        model: str,
        image: list[Any],
        prompt: str | None,
        model_response: ImageResponse,
        api_key: str | None = None,
        api_base: str | None = None,  # noqa: ARG002
        optional_params: dict[str, Any] | None = None,
        logging_obj: Any | None = None,  # noqa: ARG002
        timeout: float | httpx.Timeout | None = None,
        client: Any | None = None,  # noqa: ARG002
        **kwargs: Any,
    ) -> ImageResponse:
        optional_params = optional_params or {}
        wire_payload = optional_params.get("canary_wire_request")
        if not wire_payload:
            raise ValueError("Reve image requests require canary_wire_request")
        from litellm_handlers.provider_wire import parse_provider_wire, verify_wire_images

        wire_manifest = parse_provider_wire(wire_payload)
        verify_wire_images(wire_manifest, image)
        aspect_ratio = wire_manifest.get("structured_aspect") or "1:1"

        # v1 remix (the v2 layout endpoint is feature-gated, see
        # aimage_generation). References upload as a flat base64 list and the
        # prompt references them positionally via <img>N</img> instructions.
        reference_images: list[str] = []
        for idx, item in enumerate(image):
            b64_str = _image_to_base64(item)
            if not b64_str:
                raise ValueError(f"ProviderWireRequest reference {idx} is unreadable")
            reference_images.append(b64_str)

        final_prompt = wire_manifest["prompt_parts"][0]

        payload: dict[str, Any] = {
            "prompt": final_prompt,
            "reference_images": reference_images,
            "aspect_ratio": aspect_ratio,
        }
        payload.update(wire_manifest.get("controls") or {})

        request_timeout = timeout if timeout is not None else 300.0
        _log_request("https://api.reve.com/v1/image/remix", api_key, payload)
        async with httpx.AsyncClient(timeout=request_timeout) as http:
            response = await http.post(
                "https://api.reve.com/v1/image/remix",
                headers=_headers(api_key),
                json=payload,
            )
            _log_response(response)
            _raise_for_status(response)
            data = response.json()
        _raise_for_content_violation(data)

        b64 = _extract_b64(data)
        if isinstance(b64, str) and (b64.startswith("http://") or b64.startswith("https://")):
            async with httpx.AsyncClient() as http:
                img_resp = await http.get(b64)
                img_resp.raise_for_status()
                b64 = base64.b64encode(img_resp.content).decode("ascii")
        elif isinstance(b64, str) and b64.startswith("data:"):
            if "," in b64:
                b64 = b64.split(",", 1)[1]

        model_response.created = int(time.time())
        model_response.data = [ImageObject(b64_json=b64)]
        actual_model = data.get("model") if isinstance(data.get("model"), str) else model
        model_response.model = actual_model
        model_response._hidden_params["model"] = actual_model
        model_response._hidden_params["custom_llm_provider"] = "reve"
        model_response._hidden_params["response_cost"] = 0.04
        return model_response


def _headers(api_key: str | None) -> dict[str, str]:
    key = (api_key or os.environ.get("REVE_API_KEY") or "").strip()
    if not key:
        raise ValueError("REVE_API_KEY is not set")
    return {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }


def _raise_for_status(response: httpx.Response) -> None:
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as e:
        raise ValueError(f"Reve API returned error {response.status_code}: {response.text}") from e


def _raise_for_content_violation(data: Any) -> None:
    if isinstance(data, dict) and str(data.get("content_violation", "")).lower() in {"true", "1", "yes"}:
        raise ValueError(
            "Reve flagged a content violation for this request "
            f"(request_id={data.get('request_id')})"
        )


def _extract_b64(data: Any) -> str:
    if isinstance(data, dict):
        images_list = data.get("images") or data.get("data")
        if isinstance(images_list, list) and len(images_list) > 0:
            first_item = images_list[0]
            if isinstance(first_item, dict):
                return first_item.get("b64_json") or first_item.get("image") or first_item.get("url") or ""
            elif isinstance(first_item, str):
                return first_item
        return data.get("b64_json") or data.get("image") or data.get("url") or ""
    return ""


def _item_filename(item: Any) -> str:
    if isinstance(item, tuple) and len(item) >= 1 and item[0]:
        return str(item[0])
    for attr in ("filename", "name"):
        val = getattr(item, attr, None)
        if val:
            return str(val)
    return ""


def _parse_role_and_name(filename: str) -> tuple[str | None, str]:
    if filename.startswith(_ROLE_PREFIX):
        rest = filename[len(_ROLE_PREFIX):]
        role, sep, bare = rest.partition(_ROLE_SEP)
        if sep:
            return role, bare
    return None, filename


def _heuristic_role(bare: str) -> str:
    stem = Path(bare).stem.lower()
    if any(stem.startswith(p) for p in ("loc_", "location_", "setting_", "plate_")):
        return "location_plate"
    if any(stem.startswith(p) for p in ("style_", "art_style_", "art_")):
        return "style"
    if stem.startswith("prop_"):
        return "prop"
    if stem.startswith("panel_") and stem[len("panel_"):].isdigit():
        return "continuity"
    return "subject"


def _character_name(bare: str) -> str | None:
    stem = Path(bare).stem
    for prefix in ("char_", "character_", "chara_"):
        if stem.lower().startswith(prefix):
            raw = stem[len(prefix):]
            raw = re.sub(
                r"[_\-]?(portrait|reference|ref|full|face|front|back|side|standing"
                r"|three_quarter|gesture|sheet|profile|pose|body|head)$",
                "", raw, flags=re.IGNORECASE,
            )
            raw = re.sub(r"[_\-]?\d+$", "", raw)
            cleaned = raw.replace("_", " ").replace("-", " ").strip()
            return cleaned.title() if cleaned else None
    raw = re.sub(
        r"[_\-]?(portrait|reference|ref|full|face|front|back|side|standing"
        r"|three_quarter|gesture|sheet|profile|pose|body|head)$",
        "", stem, flags=re.IGNORECASE,
    )
    raw = re.sub(r"[_\-]?\d+$", "", raw)
    cleaned = raw.replace("_", " ").replace("-", " ").strip().lower()
    if not cleaned or cleaned in _GENERIC_STEMS:
        return None
    return cleaned.title()


def _prop_label(bare: str) -> str:
    raw_prop = re.sub(r"^prop[_\-]", "", Path(bare).stem, flags=re.IGNORECASE)
    raw_prop = re.sub(r"[_\-]?(reference|ref|image|photo)$", "", raw_prop, flags=re.IGNORECASE)
    prop_candidate = raw_prop.replace("_", " ").replace("-", " ").strip()
    prop_trimmed = re.sub(r"\s*\d+$", "", prop_candidate).strip()
    label = (prop_trimmed if prop_trimmed.lower() not in {"", "prop"} else prop_candidate).title()
    if not label or label.lower() in _GENERIC_STEMS:
        return "object"
    return label


def _location_name(bare: str) -> str:
    stem = Path(bare).stem
    for prefix in ("loc_", "location_", "setting_", "plate_"):
        if stem.lower().startswith(prefix):
            raw = stem[len(prefix):]
            cleaned = raw.replace("_", " ").replace("-", " ").strip()
            return cleaned.title() if cleaned else "location"
    return stem.replace("_", " ").replace("-", " ").title() or "location"


def _extract_label_from_bare(role: str, bare: str) -> str:
    if role == "subject":
        name = _character_name(bare)
        return name if name else "character"
    if role == "prop":
        return _prop_label(bare)
    if role == "location_plate":
        return _location_name(bare)
    return "reference"


def _image_to_base64(item: Any) -> str | None:
    data: bytes | None = None
    if isinstance(item, tuple):
        if len(item) >= 1 and item[0]:
            str(item[0])
        if len(item) >= 2:
            data = _read_bytes(item[1])
        if len(item) >= 3 and item[2]:
            str(item[2])
    else:
        name = getattr(item, "filename", None) or getattr(item, "name", None)
        if name:
            Path(str(name)).name
        content_type = getattr(item, "content_type", None)
        if content_type:
            str(content_type)
        data = _read_bytes(item)
    if data is None:
        return None
    b64 = base64.b64encode(data).decode("ascii")
    return b64


def _read_bytes(value: Any) -> bytes | None:
    if value is None:
        return None
    if isinstance(value, bytes):
        return value
    if isinstance(value, bytearray):
        return bytes(value)
    if isinstance(value, str):
        path = Path(value)
        if path.exists():
            return path.read_bytes()
        return value.encode("utf-8")
    reader = getattr(value, "read", None)
    if callable(reader):
        try:
            seeker = getattr(value, "seek", None)
            if callable(seeker):
                seeker(0)
            out = reader()
            if isinstance(out, str):
                return out.encode("utf-8")
            if isinstance(out, bytearray):
                return bytes(out)
            return out
        finally:
            seeker = getattr(value, "seek", None)
            if callable(seeker):
                seeker(0)
    return None


reve_llm = ReveLLM()
