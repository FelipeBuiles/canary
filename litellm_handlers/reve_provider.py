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


def _normalize_layout(layout: Any) -> Any:
    if not isinstance(layout, dict):
        return layout

    normalized = layout.copy()

    # 1. Map 'description' to 'overall_prompt' at the root level if overall_prompt is missing
    if "description" in normalized and "overall_prompt" not in normalized:
        normalized["overall_prompt"] = normalized["description"]

    # 2. Extract regions list
    regions = normalized.get("regions")
    if isinstance(regions, list):
        normalized_regions = []
        for reg in regions:
            if not isinstance(reg, dict):
                normalized_regions.append(reg)
                continue
            r = reg.copy()

            # Map 'description' to 'prompt' at region level if prompt is missing
            if "description" in r and "prompt" not in r:
                r["prompt"] = r["description"]

            # Handle coordinate normalization to 'bbox' dict with x0, y0, x1, y1
            if "bbox" not in r:
                # Scenario A: direct x, y, w, h keys
                if all(k in r for k in ("x", "y", "w", "h")):
                    try:
                        x = float(r["x"])
                        y = float(r["y"])
                        w = float(r["w"])
                        h = float(r["h"])
                        r["bbox"] = {"x0": x, "y0": y, "x1": x + w, "y1": y + h}
                    except (ValueError, TypeError):
                        pass
                # Scenario B: direct x0, y0, x1, y1 keys
                elif all(k in r for k in ("x0", "y0", "x1", "y1")):
                    try:
                        r["bbox"] = {
                            "x0": float(r["x0"]),
                            "y0": float(r["y0"]),
                            "x1": float(r["x1"]),
                            "y1": float(r["y1"]),
                        }
                    except (ValueError, TypeError):
                        pass
            else:
                bbox_val = r["bbox"]
                # Scenario C: bbox is a list [x0, y0, x1, y1] or [x, y, w, h]
                if isinstance(bbox_val, list) and len(bbox_val) == 4:
                    try:
                        coords = [float(c) for c in bbox_val]
                        r["bbox"] = {
                            "x0": coords[0],
                            "y0": coords[1],
                            "x1": coords[2],
                            "y1": coords[3]
                        }
                    except (ValueError, TypeError):
                        pass
                # Scenario D: bbox is a dict
                elif isinstance(bbox_val, dict):
                    # Check if dict has x0, y0, x1, y1
                    if all(k in bbox_val for k in ("x0", "y0", "x1", "y1")):
                        try:
                            r["bbox"] = {
                                "x0": float(bbox_val["x0"]),
                                "y0": float(bbox_val["y0"]),
                                "x1": float(bbox_val["x1"]),
                                "y1": float(bbox_val["y1"]),
                            }
                        except (ValueError, TypeError):
                            pass
                    # Check if dict has x, y, w, h
                    elif all(k in bbox_val for k in ("x", "y", "w", "h")):
                        try:
                            x = float(bbox_val["x"])
                            y = float(bbox_val["y"])
                            w = float(bbox_val["w"])
                            h = float(bbox_val["h"])
                            r["bbox"] = {"x0": x, "y0": y, "x1": x + w, "y1": y + h}
                        except (ValueError, TypeError):
                            pass

            normalized_regions.append(r)
        normalized["regions"] = normalized_regions

    return normalized


def _log_request(url: str, api_key: str | None, payload: dict[str, Any]) -> None:
    import sys
    import json
    sys.stderr.write("\n=== [REVE API CALL START] ===\n")
    sys.stderr.write(f"URL: {url}\n")
    headers = _headers(api_key)
    logged_headers = {k: ("***REDACTED***" if k.lower() == "authorization" else v) for k, v in headers.items()}
    sys.stderr.write(f"Headers: {json.dumps(logged_headers)}\n")
    
    logged_payload = payload.copy()
    if "reference_images" in logged_payload:
        logged_payload["reference_images"] = [
            f"<Base64 String, length={len(r)}>" for r in logged_payload["reference_images"]
        ]
    sys.stderr.write(f"Payload: {json.dumps(logged_payload, indent=2)}\n")
    sys.stderr.write("==============================\n\n")
    sys.stderr.flush()


def _log_response(response: httpx.Response) -> None:
    import sys
    import json
    sys.stderr.write("=== [REVE API CALL RESPONSE] ===\n")
    sys.stderr.write(f"Status Code: {response.status_code}\n")
    try:
        resp_data = response.json()
        logged_resp = resp_data.copy() if isinstance(resp_data, dict) else resp_data
        if isinstance(logged_resp, dict):
            for key_to_redact in ("images", "data"):
                if key_to_redact in logged_resp:
                    items = logged_resp[key_to_redact]
                    if isinstance(items, list):
                        logged_resp[key_to_redact] = [
                            {k: ("<Base64 Redacted>" if k in ("b64_json", "image") else v) for k, v in item.items()}
                            if isinstance(item, dict) else item
                            for item in items
                        ]
            for key_to_redact in ("b64_json", "image"):
                if key_to_redact in logged_resp:
                    logged_resp[key_to_redact] = "<Base64 Redacted>"
        sys.stderr.write(f"JSON Response: {json.dumps(logged_resp, indent=2)}\n")
    except Exception:
        sys.stderr.write(f"Raw Response: {response.text[:1000]}...\n")
    sys.stderr.write("=================================\n\n")
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
        size = optional_params.get("size") or kwargs.get("size")
        aspect_ratio = _map_aspect_ratio(size)

        # Prefer exact dimensions when provided by the caller
        width = optional_params.get("canary_requested_width") or kwargs.get("canary_requested_width")
        height = optional_params.get("canary_requested_height") or kwargs.get("canary_requested_height")

        # Check for layout prompt
        import json
        layout = optional_params.get("layout") or kwargs.get("layout")
        is_layout = False
        if layout:
            is_layout = True
        else:
            if isinstance(prompt, str) and prompt.strip().startswith("{"):
                try:
                    parsed = json.loads(prompt)
                    if "layout" in parsed:
                        layout = parsed["layout"]
                        is_layout = True
                    elif "regions" in parsed:
                        layout = parsed
                        is_layout = True
                except Exception:
                    pass

        if is_layout:
            layout = _normalize_layout(layout)
            layout_model = "layout2image"
            if model and "/" in model:
                model_suffix = model.split("/")[-1]
                if model_suffix in ("layout2image", "text2layout", "image2layout", "layout2layout"):
                    layout_model = model_suffix

            payload = {
                "model": layout_model,
                "layout": layout,
            }
            seed = optional_params.get("seed") or kwargs.get("seed")
            if seed is not None:
                payload["seed"] = seed

            postprocessing = optional_params.get("postprocessing") or kwargs.get("postprocessing")
            if postprocessing:
                payload["postprocessing"] = postprocessing

            request_timeout = timeout if timeout is not None else 300.0
            _log_request("https://api.reve.com/v1/image/layout", api_key, payload)
            async with httpx.AsyncClient(timeout=request_timeout) as http:
                response = await http.post(
                    "https://api.reve.com/v1/image/layout",
                    headers=_headers(api_key),
                    json=payload,
                )
                _log_response(response)
                _raise_for_status(response)
                data = response.json()
        else:
            final_prompt = prompt or ""
            # Reve accepts very long prompts; only truncate as a last resort
            if len(final_prompt) > 8000:
                final_prompt = final_prompt[:8000]
            payload: dict[str, Any] = {
                "prompt": final_prompt,
                "aspect_ratio": aspect_ratio,
            }
            # Pass through exact dimensions when available
            if width and height:
                payload["width"] = int(width)
                payload["height"] = int(height)
            seed = optional_params.get("seed") or kwargs.get("seed")
            if seed is not None:
                payload["seed"] = seed
            steps = optional_params.get("steps") or kwargs.get("steps")
            if steps is not None:
                payload["steps"] = int(steps)
            quality = optional_params.get("quality") or kwargs.get("quality")
            if quality is not None:
                payload["quality"] = quality
            negative_prompt = optional_params.get("negative_prompt") or kwargs.get("negative_prompt")
            if negative_prompt is not None:
                payload["negative_prompt"] = negative_prompt

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
        model_response.model = model
        model_response._hidden_params["model"] = model
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
        size = (optional_params or {}).get("size") or kwargs.get("size")
        aspect_ratio = _map_aspect_ratio(size)

        reference_images = []
        prompt_injections = []

        # Limit to max 4 reference images
        for idx, item in enumerate(image[:4]):
            b64_str = _image_to_base64(item)
            if not b64_str:
                continue
            reference_images.append(b64_str)

            filename = _item_filename(item)
            role, bare = _parse_role_and_name(filename)
            if role is None:
                role = _heuristic_role(bare)

            label = _extract_label_from_bare(role, bare)

            if role == "subject":
                injection = f"Use <img>{idx}</img> as the character reference for {label}." if label else f"Use <img>{idx}</img> as the character reference."
            elif role == "style":
                injection = f"Use <img>{idx}</img> as the style reference for {label}." if label else f"Use <img>{idx}</img> as the style reference."
            elif role == "location_plate":
                injection = f"Use <img>{idx}</img> as the location reference for {label}." if label else f"Use <img>{idx}</img> as the location reference."
            elif role == "prop":
                injection = f"Use <img>{idx}</img> as the object reference for {label}." if label else f"Use <img>{idx}</img> as the object reference."
            elif role == "continuity":
                injection = f"Use <img>{idx}</img> for visual continuity."
            else:
                injection = f"Use <img>{idx}</img> as a reference."
            prompt_injections.append(injection)

        # Check for layout
        import json
        layout = (optional_params or {}).get("layout") or kwargs.get("layout")
        is_layout = False
        if layout:
            is_layout = True
        else:
            if isinstance(prompt, str) and prompt.strip().startswith("{"):
                try:
                    parsed = json.loads(prompt)
                    if "layout" in parsed:
                        layout = parsed["layout"]
                        is_layout = True
                    elif "regions" in parsed:
                        layout = parsed
                        is_layout = True
                except Exception:
                    pass

        if is_layout:
            layout = _normalize_layout(layout)
            layout_model = "layout2image"
            if model and "/" in model:
                model_suffix = model.split("/")[-1]
                if model_suffix in ("layout2image", "text2layout", "image2layout", "layout2layout"):
                    layout_model = model_suffix

            payload = {
                "model": layout_model,
                "layout": layout,
                "reference_images": reference_images,
            }
            seed = (optional_params or {}).get("seed") or kwargs.get("seed")
            if seed is not None:
                payload["seed"] = seed

            postprocessing = (optional_params or {}).get("postprocessing") or kwargs.get("postprocessing")
            if postprocessing:
                payload["postprocessing"] = postprocessing

            request_timeout = timeout if timeout is not None else 300.0
            _log_request("https://api.reve.com/v1/image/layout", api_key, payload)
            async with httpx.AsyncClient(timeout=request_timeout) as http:
                response = await http.post(
                    "https://api.reve.com/v1/image/layout",
                    headers=_headers(api_key),
                    json=payload,
                )
                _log_response(response)
                _raise_for_status(response)
                data = response.json()
        else:
            final_prompt = prompt or ""

            # Integrate reference instructions naturally into the prompt
            if "<img>" not in final_prompt and prompt_injections:
                # Add reference instructions at the beginning for better integration
                ref_block = "Reference images:\n" + "\n".join(prompt_injections) + "\n\n"
                final_prompt = ref_block + final_prompt

            # Reve accepts very long prompts; only truncate as a last resort
            if len(final_prompt) > 8000:
                suffix = ""
                if "Reference images:" in final_prompt:
                    # Preserve reference block when truncating
                    parts = final_prompt.split("\n\n", 1)
                    if len(parts) == 2 and parts[0].startswith("Reference images:"):
                        suffix = parts[0] + "\n\n"
                        remaining = parts[1]
                        limit = 8000 - len(suffix)
                        final_prompt = suffix + remaining[:limit]
                    else:
                        final_prompt = final_prompt[:8000]
                else:
                    final_prompt = final_prompt[:8000]

            payload: dict[str, Any] = {
                "prompt": final_prompt,
                "reference_images": reference_images,
                "aspect_ratio": aspect_ratio,
            }
            seed = (optional_params or {}).get("seed") or kwargs.get("seed")
            if seed is not None:
                payload["seed"] = seed

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
        model_response.model = model
        model_response._hidden_params["model"] = model
        model_response._hidden_params["custom_llm_provider"] = "reve"
        model_response._hidden_params["response_cost"] = 0.04
        return model_response


def _map_aspect_ratio(size: Any) -> str:
    if not isinstance(size, str):
        return "1:1"
    match = re.match(r"^(\d+)x(\d+)$", size.lower().strip())
    if not match:
        return "1:1"
    try:
        width = int(match.group(1))
        height = int(match.group(2))
        ratio = width / height
    except (ValueError, ZeroDivisionError):
        return "1:1"

    closest = min(REVE_ASPECT_RATIOS.keys(), key=lambda k: abs(REVE_ASPECT_RATIOS[k] - ratio))
    return closest


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
