"""Reve provider for labs experiments.

Calls api.reve.com directly over HTTP, bypassing the LiteLLM proxy gateway,
to support A/B testing and provide detailed logging of parameters.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

import httpx

from .base import LabsImageInput, LabsImageResult, ProviderError

log = logging.getLogger(__name__)

# Aspect ratios supported by Reve
REVE_ASPECT_RATIOS = {
    "1:1": 1.0,
    "3:2": 1.5,
    "2:3": 0.667,
    "4:3": 1.333,
    "3:4": 0.75,
    "16:9": 1.778,
    "9:16": 0.5625,
}

_GENERIC_STEMS = frozenset({
    "image", "img", "photo", "reference", "ref", "portrait", "figure",
    "asset", "texture", "render", "file", "input", "output", "result",
    "sample", "test", "temp", "tmp", "character", "char", "subject",
})


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


def _heuristic_role(filename: str) -> str:
    stem = Path(filename).stem.lower()
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


def _role_reference_prompt(role: str, label: str) -> str:
    if role == "subject":
        name = label if label and label != "character" else None
        return (
            f"Character identity reference for {name} — match face, hair, build, and wardrobe; do not copy its pose or background."
            if name
            else "Character identity reference — match face, hair, build, and wardrobe; do not copy its pose or background."
        )
    if role == "style":
        return "Art style reference — match this rendering style exactly."
    if role == "location_plate":
        return f"Location reference for {label}." if label else "Location reference."
    if role == "prop":
        return f"Object reference for {label}." if label else "Object reference."
    if role == "continuity":
        return "Previous panel — maintain visual continuity."
    return "Reference image."


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


class ReveProvider:
    name = "reve"

    async def generate(
        self,
        *,
        endpoint: str,  # noqa: ARG002
        inp: LabsImageInput,
        params: dict[str, Any] | None = None,
    ) -> LabsImageResult:
        started = time.perf_counter()
        
        # 1. Map aspect ratio
        size = f"{inp.width}x{inp.height}"
        aspect_ratio = _map_aspect_ratio(size)

        # 2. Process reference images (v1 remix: flat base64 list + positional
        # <img>N</img> instructions in the prompt; the v2 structured-references
        # endpoint is gated behind the partnerapi.layout_endpoint feature).
        reference_images: list[str] = []
        prompt_injections: list[str] = []
        for idx, path in enumerate(inp.reference_image_paths[:4]):
            if not path.exists():
                continue
            try:
                data = path.read_bytes()
                b64_str = base64.b64encode(data).decode("ascii")
                reference_images.append(b64_str)
            except OSError as exc:
                log.warning("Failed to read reference image %s: %s", path, exc)
                continue

            role = _heuristic_role(path.name)
            label = _extract_label_from_bare(role, path.name)
            prompt_injections.append(f"Use <img>{idx}</img>: {_role_reference_prompt(role, label)}")

        final_prompt = inp.composed_prompt()
        if "<img>" not in final_prompt and prompt_injections:
            ref_block = "Reference images:\n" + "\n".join(prompt_injections) + "\n\n"
            final_prompt = ref_block + final_prompt

        # 3. Determine endpoint URL and construct payload. Note Reve has no
        # exact-pixel sizing — width/height are rejected as
        # UNRECOGNIZED_PARAMETER; aspect_ratio is the only sizing knob.
        params = params or {}
        seed = params.get("seed")
        steps = params.get("steps")
        quality = params.get("quality")
        negative_prompt = params.get("negative_prompt")

        if reference_images:
            url = "https://api.reve.com/v1/image/remix"
            payload: dict[str, Any] = {
                "prompt": final_prompt,
                "reference_images": reference_images,
                "aspect_ratio": aspect_ratio,
            }
            if seed is not None:
                payload["seed"] = seed
        else:
            url = "https://api.reve.com/v1/image/create"
            payload = {
                "prompt": final_prompt,
                "aspect_ratio": aspect_ratio,
            }
            if seed is not None:
                payload["seed"] = seed
            if steps is not None:
                payload["steps"] = int(steps)
            if quality is not None:
                payload["quality"] = quality
            if negative_prompt is not None:
                payload["negative_prompt"] = negative_prompt

        # 4. Auth headers
        key = (os.environ.get("REVE_API_KEY") or "").strip()
        if not key:
            raise ProviderError("REVE_API_KEY is not set in environment.")
        headers = {
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        }

        # 5. Log the exact parameters sent to the Reve API
        sys.stderr.write("\n=== [REVE DIRECT CALL START] ===\n")
        sys.stderr.write(f"URL: {url}\n")
        # Print Authorization header redacted, others as-is
        logged_headers = {k: ("***REDACTED***" if k.lower() == "authorization" else v) for k, v in headers.items()}
        sys.stderr.write(f"Headers: {json.dumps(logged_headers)}\n")
        
        logged_payload = payload.copy()
        if "reference_images" in logged_payload:
            logged_payload["reference_images"] = [
                f"<Base64 String, length={len(r)}>" for r in logged_payload["reference_images"]
            ]
        sys.stderr.write(f"Payload: {json.dumps(logged_payload, indent=2)}\n")
        sys.stderr.write("=================================\n\n")
        sys.stderr.flush()

        # 6. Make request
        try:
            async with httpx.AsyncClient(timeout=300.0) as client:
                response = await client.post(url, headers=headers, json=payload)
                
                # Log response details
                sys.stderr.write("=== [REVE DIRECT CALL RESPONSE] ===\n")
                sys.stderr.write(f"Status Code: {response.status_code}\n")
                
                try:
                    resp_data = response.json()
                    logged_resp = resp_data.copy() if isinstance(resp_data, dict) else resp_data
                    if isinstance(logged_resp, dict):
                        # Redact large base64 image data in response logging
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
                sys.stderr.write("====================================\n\n")
                sys.stderr.flush()

                if response.status_code >= 400:
                    raise ProviderError(f"Reve API returned error {response.status_code}: {response.text}")
                
                data = response.json()
        except httpx.HTTPStatusError as exc:
            raise ProviderError(f"Reve direct call returned {exc.response.status_code}: {exc.response.text}") from exc
        except Exception as exc:
            if isinstance(exc, ProviderError):
                raise
            raise ProviderError(f"Reve direct call failed: {exc}") from exc

        # 7. Extract image bytes
        b64 = _extract_b64(data)
        if not b64:
            raise ProviderError("Reve API response contained no image data.")
            
        if isinstance(b64, str) and (b64.startswith("http://") or b64.startswith("https://")):
            try:
                async with httpx.AsyncClient(timeout=60.0) as client:
                    img_resp = await client.get(b64)
                    img_resp.raise_for_status()
                    image_bytes = img_resp.content
            except Exception as exc:
                raise ProviderError(f"Failed to download image from url {b64}: {exc}") from exc
        else:
            if isinstance(b64, str) and b64.startswith("data:"):
                if "," in b64:
                    b64 = b64.split(",", 1)[1]
            try:
                image_bytes = base64.b64decode(b64)
            except Exception as exc:
                raise ProviderError(f"Failed to decode base64 image data: {exc}") from exc

        latency = int((time.perf_counter() - started) * 1000)
        return LabsImageResult(
            image_bytes=image_bytes,
            mime="image/png",
            latency_ms=latency,
            cost_usd=0.04,
            provider_model="reve/create" if not reference_images else "reve/remix",
            provider_request_id=data.get("id"),
            raw_response=None,
        )
