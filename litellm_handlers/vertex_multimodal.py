"""LiteLLM custom provider for native Vertex Gemini image generation."""

from __future__ import annotations

import asyncio
import base64
import mimetypes
import os
import re
import time
from pathlib import Path
from typing import Any

import httpx
from google import genai
from google.genai import types
from litellm.llms.custom_llm import CustomLLM
from litellm.types.utils import ImageObject, ImageResponse, ImageUsage, ImageUsageInputTokensDetails


class VertexMultimodalLLM(CustomLLM):
    """Custom LiteLLM provider that keeps Gemini image calls in native Vertex shape."""

    def image_edit(
        self,
        model: str,
        image: list[Any],
        prompt: str | None,
        model_response: ImageResponse,
        api_key: str | None = None,  # noqa: ARG002
        api_base: str | None = None,  # noqa: ARG002
        optional_params: dict[str, Any] | None = None,
        logging_obj: Any | None = None,  # noqa: ARG002
        timeout: float | httpx.Timeout | None = None,  # noqa: ARG002
        client: Any | None = None,  # noqa: ARG002
        **kwargs: Any,  # noqa: ARG002
    ) -> ImageResponse:
        return asyncio.run(self._generate_async(
            model=model,
            image=image,
            prompt=prompt or "",
            model_response=model_response,
            optional_params=optional_params or {},
        ))

    async def aimage_edit(
        self,
        model: str,
        image: list[Any],
        prompt: str | None,
        model_response: ImageResponse,
        api_key: str | None = None,  # noqa: ARG002
        api_base: str | None = None,  # noqa: ARG002
        optional_params: dict[str, Any] | None = None,
        logging_obj: Any | None = None,  # noqa: ARG002
        timeout: float | httpx.Timeout | None = None,  # noqa: ARG002
        client: Any | None = None,  # noqa: ARG002
        **kwargs: Any,  # noqa: ARG002
    ) -> ImageResponse:
        return await self._generate_async(
            model=model,
            image=image,
            prompt=prompt or "",
            model_response=model_response,
            optional_params=optional_params or {},
        )

    def image_generation(
        self,
        model: str,
        prompt: str,
        model_response: ImageResponse,
        api_key: str | None = None,  # noqa: ARG002
        api_base: str | None = None,  # noqa: ARG002
        optional_params: dict[str, Any] | None = None,
        logging_obj: Any | None = None,  # noqa: ARG002
        timeout: float | httpx.Timeout | None = None,  # noqa: ARG002
        client: Any | None = None,  # noqa: ARG002
        **kwargs: Any,  # noqa: ARG002
    ) -> ImageResponse:
        return asyncio.run(self._generate_async(
            model=model,
            image=[],
            prompt=prompt,
            model_response=model_response,
            optional_params=optional_params or {},
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
        timeout: float | httpx.Timeout | None = None,  # noqa: ARG002
        client: Any | None = None,  # noqa: ARG002
        **kwargs: Any,  # noqa: ARG002
    ) -> ImageResponse:
        return await self._generate_async(
            model=model,
            image=[],
            prompt=prompt,
            model_response=model_response,
            optional_params=optional_params or {},
        )

    async def _generate_async(
        self,
        *,
        model: str,
        image: list[Any],
        prompt: str,
        model_response: ImageResponse,
        optional_params: dict[str, Any],
    ) -> ImageResponse:
        vertex_model = _vertex_model(model)
        project = _vertex_project(optional_params)
        location = _vertex_location(optional_params)
        contents: list[str | types.Part] = [prompt]
        ref_count = 0
        labeled: list[tuple[str, str, types.Part]] = []  # (role, bare_name, Part)
        for item in image:
            filename = _item_filename(item)
            role, bare = _parse_role_and_name(filename)
            if role is None:
                role = _heuristic_role(bare)
            part = _part(item)
            if part is not None:
                labeled.append((role, bare, part))
                ref_count += 1
        if labeled:
            from collections import Counter
            role_totals: Counter[str] = Counter(role for role, _, _ in labeled)
            role_seen: Counter[str] = Counter()
            contents.append("\n\nThe following reference images guide this illustration:")
            for role, bare, part in labeled:
                role_seen[role] += 1
                contents.append(_role_label(role, bare, index=role_seen[role], total=role_totals[role]))
                contents.append(part)
        client = genai.Client(vertexai=True, project=project, location=location)
        response = await asyncio.to_thread(
            client.models.generate_content,
            model=vertex_model,
            contents=contents,
            config=types.GenerateContentConfig(response_modalities=["IMAGE"]),
        )
        image_bytes, mime = _extract_image(response)
        b64 = base64.b64encode(image_bytes).decode("ascii")
        provider_model = f"vertex_ai/{vertex_model}"
        response_cost = _estimated_image_cost(vertex_model, ref_count)
        model_response.created = int(time.time())
        model_response.data = [ImageObject(b64_json=b64)]
        model_response.usage = _image_usage(response, response_cost=response_cost)
        model_response.model = provider_model
        model_response._hidden_params["model"] = provider_model
        model_response._hidden_params["custom_llm_provider"] = "vertex-multimodal"
        model_response._hidden_params["response_cost"] = response_cost
        model_response._hidden_params["vertex_mime_type"] = mime
        return model_response


_ROLE_PREFIX = "__role_"
_ROLE_SEP = "__"


def _item_filename(item: Any) -> str:
    """Extract the filename from whatever shape LiteLLM hands the custom handler."""
    if isinstance(item, tuple) and len(item) >= 1 and item[0]:
        return str(item[0])
    for attr in ("filename", "name"):
        val = getattr(item, attr, None)
        if val:
            return str(val)
    return ""


def _parse_role_and_name(filename: str) -> tuple[str | None, str]:
    """Return (role, bare_filename) from a __role_{role}__{name} encoded string.

    Falls back to (None, filename) when the encoding is absent so heuristics
    can still fire on plain filenames (e.g. direct script calls).
    """
    if filename.startswith(_ROLE_PREFIX):
        rest = filename[len(_ROLE_PREFIX):]
        role, sep, bare = rest.partition(_ROLE_SEP)
        if sep:
            return role, bare
    return None, filename


def _heuristic_role(bare: str) -> str:
    """Guess role from a bare filename when no encoding is present."""
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


_GENERIC_STEMS = frozenset({
    "image", "img", "photo", "reference", "ref", "portrait", "figure",
    "asset", "texture", "render", "file", "input", "output", "result",
    "sample", "test", "temp", "tmp", "character", "char", "subject",
})


def _character_name(bare: str) -> str | None:
    """Extract a human-readable name from a character reference filename.

    Tries known prefixes first (char_anya.png → "Anya"), then falls back to
    the bare stem for files named after the character directly (anya.png → "Anya").
    Returns None for obviously generic stems like reference_1.png or portrait.png.
    """
    stem = Path(bare).stem
    # Try known prefixes first — most reliable
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
    # Fall back to the stem itself — strip trailing digits/descriptors and reject generic words
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


def _location_name(bare: str) -> str | None:
    """Extract a human-readable name from a location/plate filename."""
    stem = Path(bare).stem
    for prefix in ("loc_", "location_", "setting_", "plate_"):
        if stem.lower().startswith(prefix):
            raw = stem[len(prefix):]
            cleaned = raw.replace("_", " ").replace("-", " ").strip()
            return cleaned.title() if cleaned else None
    return stem.replace("_", " ").replace("-", " ").title() or None


def _role_label(role: str, bare: str, *, index: int = 1, total: int = 1) -> str:
    """Build a descriptive text label for Gemini to understand each reference image's purpose.

    index/total are used as a fallback when a meaningful name can't be extracted and
    there are multiple refs with the same role — prevents identical labels that would
    leave Gemini unable to distinguish between e.g. two character references.
    """
    if role == "subject":
        name = _character_name(bare)
        _border_note = (
            " Ignore any decorative colored outline or glow border visible around "
            "the character — focus only on the character's face, body, hair, and costume."
        )
        if name:
            return (
                f"Character reference — {name} "
                f"(this is {name}; use ONLY this reference for {name}'s face, hair, costume, and body proportions; "
                f"do not blend {name}'s appearance with any other character reference.{_border_note}):"
            )
        if total > 1:
            return (
                f"Character reference {index} of {total} "
                f"(this is a distinct character — preserve their exact appearance separately from "
                f"every other character reference; do not blend or average appearances.{_border_note}):"
            )
        return (
            "Character/subject reference "
            f"(preserve this subject's exact appearance: face, hair, costume, and proportions precisely as shown.{_border_note}):"
        )
    if role == "prop":
        prop_name = re.sub(r"^prop[_\-]", "", Path(bare).stem, flags=re.IGNORECASE).replace("_", " ").replace("-", " ").strip()
        prop_name = re.sub(r"\s*\d+$", "", prop_name).strip().title()
        if prop_name and prop_name.lower() not in _GENERIC_STEMS:
            return f"Prop reference — {prop_name} (include this prop in the scene exactly as depicted, matching its shape, color, and details):"
        if total > 1:
            return f"Prop reference {index} of {total} (include this specific prop in the scene exactly as depicted):"
        return "Prop reference (include this prop in the scene exactly as depicted, matching its shape, color, and details):"
    if role == "continuity":
        return (
            "Previous panel for visual continuity "
            "(maintain the same characters, costumes, setting, art style, and color palette as shown in this preceding panel):"
        )
    if role == "style":
        return (
            "Visual style reference "
            "(match this exact artistic style throughout: line weight, color palette, shading technique, rendering style, and level of detail):"
        )
    if role == "location_plate":
        name = _location_name(bare)
        label = f" — {name}" if name else ""
        return (
            f"Location/setting reference{label} "
            f"(use this as the environment and background: preserve the architecture, lighting, and atmosphere of this setting):"
        )
    return "Reference image:"


def _vertex_model(model: str) -> str:
    cleaned = (model or "").strip().strip("/")
    for prefix in ("vertex-multimodal/", "vertex_ai/"):
        if cleaned.startswith(prefix):
            return cleaned[len(prefix):]
    return cleaned


def _vertex_project(params: dict[str, Any]) -> str:
    value = (
        params.get("vertex_project")
        or params.get("project")
        or os.environ.get("VERTEXAI_PROJECT")
        or os.environ.get("GOOGLE_CLOUD_PROJECT")
        or ""
    )
    value = str(value).strip()
    if not value:
        raise ValueError("VERTEXAI_PROJECT is not set")
    return value


def _vertex_location(params: dict[str, Any]) -> str:
    return str(
        params.get("vertex_location")
        or params.get("location")
        or os.environ.get("VERTEXAI_LOCATION")
        or os.environ.get("GOOGLE_CLOUD_LOCATION")
        or "global"
    ).strip()


def _part(item: Any) -> types.Part | None:
    data = _read_bytes(item)
    if data is None:
        return None
    return types.Part.from_bytes(data=data, mime_type=_mime_type(item))


def _read_bytes(value: Any) -> bytes | None:
    if value is None:
        return None
    if isinstance(value, bytes):
        return value
    if isinstance(value, bytearray):
        return bytes(value)
    if isinstance(value, tuple):
        if len(value) >= 2:
            return _read_bytes(value[1])
        return None
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


def _mime_type(item: Any) -> str:
    if isinstance(item, tuple):
        filename = str(item[0]) if len(item) >= 1 and item[0] else ""
        if len(item) >= 3 and item[2]:
            return str(item[2])
        guessed, _ = mimetypes.guess_type(filename)
        return guessed or "image/png"
    content_type = getattr(item, "content_type", None)
    if content_type:
        return str(content_type)
    name = getattr(item, "filename", None) or getattr(item, "name", None)
    guessed, _ = mimetypes.guess_type(str(name or ""))
    return guessed or "image/png"


def _extract_image(response: types.GenerateContentResponse) -> tuple[bytes, str]:
    for candidate in response.candidates or []:
        content = candidate.content
        for part in content.parts if content and content.parts else []:
            inline = getattr(part, "inline_data", None)
            if inline and inline.data:
                return inline.data, inline.mime_type or "image/png"
    raise ValueError(f"Vertex response did not contain image bytes: {response}")


def _detail_value(detail: Any, key: str) -> Any:
    dump = getattr(detail, "model_dump", None)
    if callable(dump):
        return dump(exclude_none=True).get(key)
    return getattr(detail, key, None)


def _image_usage(response: types.GenerateContentResponse, *, response_cost: float | None) -> ImageUsage:
    usage = getattr(response, "usage_metadata", None)
    prompt_tokens = int(getattr(usage, "prompt_token_count", 0) or 0)
    output_tokens = int(getattr(usage, "candidates_token_count", 0) or 0)
    total_tokens = int(getattr(usage, "total_token_count", 0) or prompt_tokens + output_tokens)
    image_tokens = 0
    text_tokens = 0
    for detail in getattr(usage, "prompt_tokens_details", None) or []:
        modality = str(_detail_value(detail, "modality") or "").upper()
        token_count = int(_detail_value(detail, "token_count") or 0)
        if "IMAGE" in modality:
            image_tokens += token_count
        elif "TEXT" in modality:
            text_tokens += token_count
    return ImageUsage(
        input_tokens=prompt_tokens,
        input_tokens_details=ImageUsageInputTokensDetails(
            image_tokens=image_tokens,
            text_tokens=text_tokens,
        ),
        output_tokens=output_tokens,
        total_tokens=total_tokens,
        cost=response_cost,
        response_cost=response_cost,
    )


def _estimated_image_cost(model: str, ref_count: int) -> float | None:
    normalized = _vertex_model(model)
    if normalized == "gemini-3.1-flash-image-preview":
        return 0.067 + 0.00056 * ref_count
    if normalized == "gemini-3-pro-image-preview":
        return 0.134 + 0.00112 * ref_count
    return None


vertex_multimodal_llm = VertexMultimodalLLM()
