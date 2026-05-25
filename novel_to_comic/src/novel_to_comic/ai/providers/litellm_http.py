"""LiteLLM OpenAI-compatible HTTP image provider."""

from __future__ import annotations

import re
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
        if loaded_refs:
            files = [("image", (_ref_filename(ref), data, _mime_type(ref.path))) for ref, data in loaded_refs]
            form_params = {k: str(v) for k, v in request_params.items() if v is not None}
            response = await ai_client._post_with_retry(
                f"{ai_client._base_url(config)}{endpoint}",
                headers=ai_client._headers(config, event_id),
                data={
                    "prompt": prompt,
                    "metadata": ai_client._json_dumps(metadata),
                    **form_params,
                },
                files=files,
            )
        else:
            response = await ai_client._post_with_retry(
                f"{ai_client._base_url(config)}{endpoint}",
                headers=ai_client._headers(config, event_id),
                json={
                    "prompt": prompt,
                    "metadata": metadata,
                    **{k: v for k, v in request_params.items() if v is not None},
                },
            )
        response.raise_for_status()
        data = response.json()
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
