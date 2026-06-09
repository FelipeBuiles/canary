"""LiteLLM OpenAI-compatible HTTP image provider."""

from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path
from typing import Any

from novel_to_comic.ai.errors import AIRefusalError
from novel_to_comic.ai.providers.base import ProviderRawResult, RefImage
from novel_to_comic.config import Config, is_gpt_image_2
from novel_to_comic.panel_aspect import aspect_for_dimensions, generation_shape_for_aspect


class LitellmHttpProvider:
    name = "litellm_http"

    def request_params(
        self,
        *,
        model_alias: str,
        width: int,
        height: int,
        config: Config,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "model": model_alias,
            "size": _image_size(model_alias, width, height),
            "n": 1,
            "canary_requested_width": width,
            "canary_requested_height": height,
            "canary_requested_aspect": aspect_for_dimensions(width, height),
            "canary_requested_shape": generation_shape_for_aspect(aspect_for_dimensions(width, height)),
        }
        if config.image_quality:
            params["quality"] = config.image_quality
        return params

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
        event_id: str,
        metadata: dict[str, Any],
    ) -> ProviderRawResult:
        from novel_to_comic.ai import client as ai_client

        request_params = params or self.request_params(
            model_alias=model_alias,
            width=width,
            height=height,
            config=config,
        )
        loaded_refs = _load_refs(refs)
        started = time.perf_counter()
        endpoint = "/v1/images/edits" if loaded_refs else "/v1/images/generations"
        response = None
        
        # Log Canary LiteLLM call parameters
        url = f"{ai_client._base_url(config)}{endpoint}"
        headers = ai_client._headers(config, event_id)
        sys.stderr.write("\n=== [CANARY LITELLM GATEWAY CALL START] ===\n")
        sys.stderr.write(f"URL: {url}\n")
        logged_headers = {k: ("***REDACTED***" if k.lower() == "authorization" else v) for k, v in headers.items()}
        sys.stderr.write(f"Headers: {json.dumps(logged_headers)}\n")
        if loaded_refs:
            sys.stderr.write(f"Prompt: {prompt}\n")
            sys.stderr.write(f"Metadata: {json.dumps(metadata)}\n")
            form_params = {k: str(v) for k, v in request_params.items() if v is not None}
            sys.stderr.write(f"Form Params: {json.dumps(form_params)}\n")
            sys.stderr.write(f"Files count: {len(loaded_refs)} ({[ref.path.name for ref, _ in loaded_refs]})\n")
        else:
            payload = {
                "prompt": prompt,
                "metadata": metadata,
                **{k: v for k, v in request_params.items() if v is not None},
            }
            sys.stderr.write(f"Payload: {json.dumps(payload, indent=2)}\n")
        sys.stderr.write("===========================================\n\n")
        sys.stderr.flush()

        if loaded_refs:
            files = [("image", (_ref_filename(ref), data, _mime_type(ref.path))) for ref, data in loaded_refs]
            form_params = {k: str(v) for k, v in request_params.items() if v is not None}
            response = await ai_client._post_with_retry(
                url,
                headers=headers,
                data={
                    "prompt": prompt,
                    "metadata": ai_client._json_dumps(metadata),
                    **form_params,
                },
                files=files,
            )
        else:
            response = await ai_client._post_with_retry(
                url,
                headers=headers,
                json={
                    "prompt": prompt,
                    "metadata": metadata,
                    **{k: v for k, v in request_params.items() if v is not None},
                },
            )
            
        # Log Canary LiteLLM call response
        sys.stderr.write("=== [CANARY LITELLM GATEWAY RESPONSE] ===\n")
        sys.stderr.write(f"Status Code: {response.status_code}\n")
        sys.stderr.write(f"Latency: {int((time.perf_counter() - started) * 1000)}ms\n")
        resp_data = None
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
            sys.stderr.write(f"Raw Response: {response.text[:500]}...\n")
        sys.stderr.write("==========================================\n\n")
        sys.stderr.flush()

        response.raise_for_status()
        data = resp_data if resp_data is not None else response.json()
        if ai_client._is_refusal(data):
            raise AIRefusalError(
                "AI image request was refused by gateway/provider",
                response_data=data,
                response_headers=response.headers,
                response=response,
            )
        image_bytes = await ai_client._decode_image_response(data)
        return ProviderRawResult(
            image_bytes=image_bytes,
            mime="image/png",
            latency_ms=int((time.perf_counter() - started) * 1000),
            raw_response=data,
            response_headers=response.headers,
            provider_request_id=data.get("id"),
            request_params=request_params,
        )


def _load_refs(refs: list[RefImage]) -> list[tuple[RefImage, bytes]]:
    loaded: list[tuple[RefImage, bytes]] = []
    for ref in _flatten_refs(refs):
        try:
            loaded.append((ref, ref.path.read_bytes()))
        except OSError:
            continue
    return loaded


def _ref_filename(ref: RefImage) -> str:
    """Encode role into the multipart filename so custom handlers (e.g. vertex_multimodal) can reconstruct it.

    When a human-readable label is known, include it in the filename so the
    custom handler can describe each image to Gemini before the binary part.
    Otherwise, preserve useful path context such as character/prop directory ids.
    """
    label_slug = _label_slug(ref.label)
    if label_slug:
        if ref.role == "subject":
            pose = ref.path.stem
            suffix = f"_{pose}" if pose else ""
            return f"__role_{ref.role}__character_{label_slug}{suffix}{ref.path.suffix or '.png'}"
        if ref.role == "location_plate":
            return f"__role_{ref.role}__location_{label_slug}{ref.path.suffix or '.png'}"
        if ref.role == "prop":
            return f"__role_{ref.role}__prop_{label_slug}{ref.path.suffix or '.png'}"
        if ref.role == "style":
            return f"__role_{ref.role}__style_{label_slug}{ref.path.suffix or '.png'}"

    if ref.role == "subject":
        parent = ref.path.parent.name
        if parent.lower().startswith(("char_", "character_", "chara_")):
            bare = f"{parent}_{ref.path.name}"
            return f"__role_{ref.role}__{bare}"
    if ref.role == "prop":
        parent = ref.path.parent.name
        if parent:
            return f"__role_{ref.role}__prop_{parent}_{ref.path.name}"
    return f"__role_{ref.role}__{ref.path.name}"


def _label_slug(label: str | None) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "_", (label or "").strip().lower()).strip("_")
    return cleaned[:80]


def _flatten_refs(refs: list[RefImage]) -> list[RefImage]:
    priority = {
        "subject": 0,
        "prop": 1,
        "continuity": 2,
        "style": 3,
        "location_plate": 4,
    }
    return sorted(refs, key=lambda ref: priority.get(ref.role, 99))


def _valid_gpt_image_2_size(width: int, height: int) -> bool:
    if width <= 0 or height <= 0:
        return False
    if width % 16 != 0 or height % 16 != 0:
        return False
    if max(width, height) > 3840:
        return False
    if max(width, height) / min(width, height) > 3:
        return False
    pixels = width * height
    return 655_360 <= pixels <= 8_294_400


def _image_size(model: str, width: int, height: int) -> str:
    if is_gpt_image_2(model) and _valid_gpt_image_2_size(width, height):
        return f"{width}x{height}"

    # Thresholds map to OpenAI-supported sizes: portrait, square, landscape.
    if height <= 0:
        return "1024x1024"
    ratio = width / height
    if ratio < 0.87:
        return "1024x1536"
    if ratio > 1.15:
        return "1536x1024"
    return "1024x1024"


def _mime_type(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in {".jpg", ".jpeg"}:
        return "image/jpeg"
    if suffix == ".webp":
        return "image/webp"
    return "image/png"
