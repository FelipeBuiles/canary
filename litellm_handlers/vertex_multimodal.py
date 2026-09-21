"""LiteLLM custom provider for native Vertex Gemini image generation."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import mimetypes
import os
import re
import time
from pathlib import Path
from typing import Any

import httpx
import struct
try:
    from google import genai
    from google.genai import types
except (ModuleNotFoundError, ImportError):
    class DummyGenAI:
        pass
    class DummyClass:
        def __init__(self, *args, **kwargs):
            pass
    genai = DummyGenAI()
    types = DummyGenAI()
    types.SafetySetting = DummyClass
    types.Part = DummyClass
    types.GenerateContentConfig = DummyClass
    types.ImageConfig = DummyClass
    types.GenerateContentResponse = DummyClass
try:
    import litellm
    from litellm.llms.custom_llm import CustomLLM
    from litellm.types.utils import ImageObject, ImageResponse, ImageUsage, ImageUsageInputTokensDetails
except ModuleNotFoundError:
    class CustomLLM:
        pass
    class ImageObject:
        pass
    class ImageResponse:
        pass
    class ImageUsage:
        pass
    class ImageUsageInputTokensDetails:
        pass
    class DummyLiteLLM:
        class RateLimitError(Exception):
            def __init__(self, message, llm_provider, model):
                super().__init__(message)
                self.llm_provider = llm_provider
                self.model = model
        class APIError(Exception):
            def __init__(self, status_code, message, llm_provider, model):
                super().__init__(message)
                self.status_code = status_code
                self.llm_provider = llm_provider
                self.model = model
    litellm = DummyLiteLLM

_ASPECT_TOLERANCE = 0.12
log = logging.getLogger(__name__)

# Canary renders public-domain literature whose canonical content can include
# violence (e.g. The Girl Without Hands). Vertex's default image safety filters
# return no candidate on such panels, which surfaces as an image-extraction
# failure in the draw stage. Mirror the text models' safety_settings in
# litellm/config.yaml so the image stage doesn't silently drop those panels.
_SAFETY_OFF = [
    types.SafetySetting(category=_c, threshold="OFF")
    for _c in (
        "HARM_CATEGORY_HARASSMENT",
        "HARM_CATEGORY_HATE_SPEECH",
        "HARM_CATEGORY_SEXUALLY_EXPLICIT",
        "HARM_CATEGORY_DANGEROUS_CONTENT",
    )
]


def _translate_vertex_error(
    exc: BaseException,
    model: str,
    *,
    request_context: str | None = None,
) -> BaseException:
    """Map a raw Vertex/genai API error to a typed LiteLLM exception.

    Without this, a Vertex ``429 RESOURCE_EXHAUSTED`` (quota) propagates
    uncaught, LiteLLM wraps it as a generic ``APIConnectionError``, and the
    gateway returns an opaque ``500`` with no body — so the draw stage records
    only "500 Internal Server Error" and tells the user to "edit the prompt"
    when in fact they were rate-limited. Re-raising the correct status + the
    upstream message makes image failures self-explaining, mirroring the
    text-side diagnostics. Returns ``exc`` unchanged when it is not a
    recognized Vertex API error (e.g. our own "no image bytes" ValueError).
    """
    code = getattr(exc, "code", None)
    if not isinstance(code, int):
        code = getattr(exc, "status_code", None)
    status = getattr(exc, "status", None)
    message = getattr(exc, "message", None) or str(exc)
    detail = f"Vertex image generation failed ({status or code or type(exc).__name__}): {message}"
    if request_context:
        detail = f"{detail}; request={request_context}"
    if code == 429 or status == "RESOURCE_EXHAUSTED":
        return litellm.RateLimitError(message=detail, llm_provider="vertex-multimodal", model=model)
    if isinstance(code, int) and 400 <= code < 600:
        return litellm.APIError(
            status_code=code, message=detail, llm_provider="vertex-multimodal", model=model
        )
    return exc


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
        requested_aspect = _requested_aspect(optional_params)
        wire_payload = optional_params.get("canary_wire_request")
        parts: list[types.Part] = []
        for item in image:
            part = _part(item)
            if part is not None:
                parts.append(part)
        ref_count = len(parts)
        page_payload = optional_params.get("canary_complete_page_request")
        requested_image_size: str | None = None
        if page_payload:
            manifest = _parse_complete_page_request(page_payload)
            _verify_complete_page_images(manifest, image)
            if prompt != manifest["prompt"]:
                raise ValueError("complete-page prompt differs from frozen request")
            if _vertex_model(model) != manifest["model"]:
                raise ValueError("complete-page model differs from frozen request")
            expected_aspect = (
                manifest["output_width"] / manifest["output_height"]
            )
            if (
                requested_aspect is None
                or abs((requested_aspect / expected_aspect) - 1.0) > 0.001
            ):
                raise ValueError("complete-page geometry differs from frozen request")
            idempotency_key = optional_params.get("canary_idempotency_key")
            if idempotency_key != manifest["request_sha256"]:
                raise ValueError(
                    "complete-page idempotency key differs from frozen request"
                )
            requested_image_size = _image_size_for_dimensions(
                manifest["output_width"],
                manifest["output_height"],
            )
            contents = _exact_complete_page_contents(manifest, parts)
        elif wire_payload:
            from litellm_handlers.provider_wire import (
                exact_vertex_contents,
                parse_provider_wire,
                verify_wire_images,
            )

            manifest = parse_provider_wire(wire_payload)
            verify_wire_images(manifest, image)
            contents = exact_vertex_contents(manifest, parts)
        else:
            raise ValueError(
                "Vertex image requests require a frozen wire or complete-page request"
            )
        client = genai.Client(vertexai=True, project=project, location=location)
        try:
            # TEXT is not optional: Gemini 3 Pro Image is a thinking model that
            # emits reasoning text alongside the image, and every documented
            # call for it requests both modalities. IMAGE-only works on the
            # Flash image routes but leaves Pro with no legal candidate, which
            # Vertex reports as an opaque prompt block (block_reason=OTHER).
            # _extract_image ignores text parts, so the image path is unchanged.
            config_kwargs: dict[str, Any] = {
                "response_modalities": ["TEXT", "IMAGE"],
                "safety_settings": _SAFETY_OFF,
            }
            controls = dict(manifest.get("controls", []))
            quality = controls.get("quality")
            image_config_kwargs = _image_config_kwargs(
                requested_aspect,
                quality,
                model=vertex_model,
                image_size=requested_image_size,
            )
            native_aspect = image_config_kwargs.get("aspect_ratio")

            # Older LiteLLM images ship a google-genai version without
            # ImageConfig. Gemini defaults to a square image, so square calls
            # remain safe without the optional native controls (and are still
            # verified from the returned bytes below). Dropping a requested
            # non-square aspect could silently return the wrong frame, so keep
            # surfacing that incompatibility before generation.
            image_config_type = getattr(types, "ImageConfig", None)
            if image_config_kwargs and image_config_type is not None:
                config_kwargs["image_config"] = image_config_type(**image_config_kwargs)
            elif _requires_native_aspect_control(native_aspect):
                raise ValueError(
                    "Vertex image SDK does not support native aspect ratio controls; "
                    f"cannot safely generate the requested {native_aspect} frame"
                )
            elif image_config_kwargs:
                log.warning(
                    "Vertex image SDK lacks ImageConfig; using Gemini's default "
                    "square output and verifying returned dimensions"
                )
            response = await asyncio.to_thread(
                client.models.generate_content,
                model=vertex_model,
                contents=contents,
                config=types.GenerateContentConfig(**config_kwargs),
            )
        except Exception as exc:  # noqa: BLE001 — re-raised as a typed LiteLLM error
            translated = _translate_vertex_error(
                exc,
                vertex_model,
                request_context=(
                    f"model={vertex_model}, location={location}, "
                    f"image_config={image_config_kwargs}"
                ),
            )
            if translated is exc:
                raise
            raise translated from exc
        image_bytes, mime = _extract_image(response)
        actual_width, actual_height = _image_dimensions(image_bytes)
        actual_aspect = (actual_width / actual_height) if actual_width and actual_height else None
        if not _aspect_matches(actual_aspect, requested_aspect):
            raise ValueError(
                "shape_mismatch: Vertex returned image aspect "
                f"{actual_aspect:.3f} but requested {requested_aspect:.3f}"
            )
        b64 = base64.b64encode(image_bytes).decode("ascii")
        provider_model = f"vertex_ai/{vertex_model}"
        response_cost = _estimated_image_cost(
            vertex_model,
            ref_count,
            image_size=requested_image_size,
        )
        model_response.created = int(time.time())
        model_response.data = [ImageObject(b64_json=b64)]
        model_response.usage = _image_usage(response, response_cost=response_cost)
        model_response.model = provider_model
        model_response._hidden_params["model"] = provider_model
        model_response._hidden_params["custom_llm_provider"] = "vertex-multimodal"
        model_response._hidden_params["response_cost"] = response_cost
        model_response._hidden_params["vertex_mime_type"] = mime
        model_response._hidden_params["actual_width"] = actual_width
        model_response._hidden_params["actual_height"] = actual_height
        model_response._hidden_params["requested_aspect"] = requested_aspect
        return model_response


def _parse_complete_page_request(payload: str) -> dict[str, Any]:
    """Validate the frozen application request without importing application code."""

    try:
        manifest = json.loads(payload)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError("invalid complete-page request JSON") from exc
    supplied = manifest.get("request_sha256")
    projection = dict(manifest)
    projection.pop("request_sha256", None)
    actual = hashlib.sha256(
        json.dumps(
            projection,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    if supplied != actual:
        raise ValueError("complete-page request identity mismatch")
    if manifest.get("artifact_kind") != "complete_page":
        raise ValueError("Vertex production request must be a complete page")
    references = manifest.get("references")
    if not isinstance(references, list):
        raise ValueError("complete-page references must be an ordered list")
    if [reference.get("order") for reference in references] != list(
        range(1, len(references) + 1)
    ):
        raise ValueError("complete-page reference order is invalid")
    return manifest


def _verify_complete_page_images(
    manifest: dict[str, Any],
    images: list[Any],
) -> None:
    references = manifest["references"]
    correction = manifest.get("correction")
    expected_count = len(references) + (1 if correction is not None else 0)
    if expected_count != len(images):
        filenames = [_item_filename(image) or "<unnamed>" for image in images]
        raise ValueError(
            "complete-page reference count mismatch "
            f"(expected={expected_count}, received={len(images)}, "
            f"references={len(references)}, correction={correction is not None}, "
            f"files={filenames!r})"
        )
    reference_images = images
    if correction is not None:
        if not isinstance(correction, dict):
            raise ValueError("complete-page correction must be an object")
        parent_digest = correction.get("parent_render_image_sha256")
        parent_data = _read_bytes(images[0])
        if parent_data is None:
            raise ValueError("complete-page edit source is unreadable")
        if hashlib.sha256(parent_data).hexdigest() != parent_digest:
            raise ValueError("complete-page edit source digest mismatch")
        reference_images = images[1:]
    for reference, image in zip(references, reference_images, strict=True):
        data = _read_bytes(image)
        if data is None:
            raise ValueError(
                f"complete-page reference {reference['order']} is unreadable"
            )
        if hashlib.sha256(data).hexdigest() != reference["content_sha256"]:
            raise ValueError(
                f"complete-page reference {reference['order']} digest mismatch"
            )


def _exact_complete_page_contents(
    manifest: dict[str, Any],
    image_parts: list[Any],
) -> list[Any]:
    references = manifest["references"]
    correction = manifest.get("correction")
    expected_count = len(references) + (1 if correction is not None else 0)
    if expected_count != len(image_parts):
        raise ValueError("complete-page reference count mismatch")
    contents: list[Any] = []
    reference_parts = image_parts
    if correction is not None:
        contents.extend(
            (
                image_parts[0],
                (
                    "Off-canvas parent-edit-base: the complete page to correct, not an "
                    "approved identity or state reference. Preserve untouched composition "
                    "and framing beneath the current approved identity/state/style, exact "
                    "copy and author pins. Apply the authoritative change list."
                ),
            )
        )
        reference_parts = image_parts[1:]
    for reference, part in zip(references, reference_parts, strict=True):
        index = reference["order"]
        suffix = ""
        while index:
            index, remainder = divmod(index - 1, 26)
            suffix = chr(65 + remainder) + suffix
        contents.extend(
            (
                part,
                (
                    f"Off-canvas asset-{suffix}: this immediately preceding image. "
                    "Use only for its assigned authority scope in the page "
                    "instructions. This binding is never a visible caption or callout."
                ),
            )
        )
    contents.append(manifest["prompt"])
    return contents


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
        raw_prop = re.sub(r"^prop[_\-]", "", Path(bare).stem, flags=re.IGNORECASE)
        raw_prop = re.sub(r"[_\-]?(reference|ref|image|photo)$", "", raw_prop, flags=re.IGNORECASE)
        prop_candidate = raw_prop.replace("_", " ").replace("-", " ").strip()
        prop_trimmed = re.sub(r"\s*\d+$", "", prop_candidate).strip()
        prop_name = (prop_trimmed if prop_trimmed.lower() not in {"", "prop"} else prop_candidate).title()
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


def _requested_aspect(params: dict[str, Any]) -> float | None:
    explicit = params.get("canary_requested_aspect")
    try:
        if explicit is not None:
            value = float(explicit)
            return value if value > 0 else None
    except (TypeError, ValueError):
        pass

    size = str(params.get("size") or "").lower().strip()
    match = re.match(r"^(\d+)x(\d+)$", size)
    if not match:
        return None
    width = int(match.group(1))
    height = int(match.group(2))
    if width <= 0 or height <= 0:
        return None
    return width / height


def _map_to_supported_aspect(requested_aspect: float | None) -> str | None:
    if requested_aspect is None or requested_aspect <= 0:
        return None
    supported = {
        "9:16": 9 / 16,
        "2:3": 2 / 3,
        "3:4": 3 / 4,
        "4:5": 4 / 5,
        "1:1": 1.0,
        "5:4": 5 / 4,
        "4:3": 4 / 3,
        "3:2": 3 / 2,
        "16:9": 16 / 9,
        "21:9": 21 / 9,
    }
    return min(supported.keys(), key=lambda k: abs(supported[k] - requested_aspect))


def _image_config_kwargs(
    requested_aspect: float | None,
    quality: Any,
    *,
    model: str | None = None,
    image_size: str | None = None,
) -> dict[str, str]:
    """Build native Gemini image controls from the exact wire geometry."""
    result: dict[str, str] = {}
    if image_size is not None:
        if image_size not in {"1K", "2K", "4K"}:
            raise ValueError(f"unsupported native image size: {image_size}")
        result["image_size"] = image_size
    elif quality is not None:
        selected_image_size = {"low": "1K", "medium": "2K", "high": "4K", "auto": "2K"}.get(
            str(quality).lower()
        )
        if selected_image_size is None:
            raise ValueError(f"unsupported wire quality: {quality}")
        # Flash Lite Image has a fixed 1K output resolution. Sending the
        # generic medium/high mapping (2K/4K) makes Vertex reject an otherwise
        # valid request with an opaque INVALID_ARGUMENT response.
        if model and "gemini-3.1-flash-lite-image" in model:
            selected_image_size = "1K"
        result["image_size"] = selected_image_size

    # Gemini otherwise defaults to a square image even when the
    # provider-neutral request contains landscape/portrait geometry. Pass the
    # closest supported native aspect explicitly so a retry cannot repeat a
    # known shape mismatch.
    native_aspect = _map_to_supported_aspect(requested_aspect)
    if native_aspect is not None:
        result["aspect_ratio"] = native_aspect
    return result


def _image_size_for_dimensions(width: int, height: int) -> str:
    """Translate frozen provider dimensions back to Gemini's native size tier."""

    pixels = width * height
    tiers = {
        "1K": 1024 * 1024,
        "2K": 2048 * 2048,
        "4K": 4096 * 4096,
    }
    return min(tiers, key=lambda tier: abs(tiers[tier] - pixels))


def _requires_native_aspect_control(native_aspect: str | None) -> bool:
    """Whether omitting ImageConfig could change the requested frame shape."""
    return native_aspect not in (None, "1:1")


def _shape_for_aspect(aspect: float | None) -> str | None:
    if aspect is None or aspect <= 0:
        return None
    if aspect < 0.9:
        return "portrait"
    if aspect > 1.15:
        return "landscape"
    return "square"


def _aspect_instruction(shape: str, aspect: float | None) -> str:
    frame = {
        "portrait": "vertical portrait frame",
        "landscape": "wide horizontal frame",
        "square": "square frame",
    }.get(shape, "single frame")
    if aspect and aspect > 0:
        return f"Output aspect ratio must be {shape} (about {aspect:.2f}:1). Fill one {frame}."
    return f"Output must fill one {frame}."


def _image_dimensions(image_bytes: bytes) -> tuple[int | None, int | None]:
    try:
        if image_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
            # PNG: el primer chunk es IHDR. Ancho y alto son enteros de 32 bits (big-endian).
            # Signature (8B) + Length (4B) + Chunk Type (4B) = 16B de offset.
            w, h = struct.unpack(">II", image_bytes[16:24])
            return w, h
        elif image_bytes.startswith(b"\xff\xd8"):
            # JPEG: buscar marcadores SOF (Start Of Frame)
            size = len(image_bytes)
            idx = 2
            while idx < size:
                if image_bytes[idx] != 0xff:
                    idx += 1
                    continue
                while idx < size and image_bytes[idx] == 0xff:
                    idx += 1
                if idx >= size:
                    break
                marker = image_bytes[idx]
                idx += 1
                if (0xc0 <= marker <= 0xcf) and marker not in (0xc4, 0xc8, 0xcc):
                    if idx + 7 < size:
                        # Estructura SOF: Length (2B) + Precision (1B) + Height (2B) + Width (2B)
                        h, w = struct.unpack(">HH", image_bytes[idx+3:idx+7])
                        return w, h
                    break
                else:
                    if idx + 2 < size:
                        chunk_len = struct.unpack(">H", image_bytes[idx:idx+2])[0]
                        idx += chunk_len
                    else:
                        break
    except Exception:
        pass
    return None, None


def _aspect_matches(actual: float | None, requested: float | None) -> bool:
    if actual is None or requested is None or requested <= 0:
        return True
    actual_shape = _shape_for_aspect(actual)
    requested_shape = _shape_for_aspect(requested)
    if actual_shape == requested_shape:
        return True
    return abs((actual / requested) - 1.0) <= _ASPECT_TOLERANCE


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

    # Build a detailed diagnostic message
    details = []

    # Inspect candidates
    if response.candidates:
        for idx, candidate in enumerate(response.candidates):
            cand_details = [f"candidate #{idx}"]
            # With TEXT+IMAGE requested, a refusal arrives as prose in place of
            # the image — the only place the provider says why.
            texts = [
                part.text
                for part in (
                    candidate.content.parts
                    if candidate.content and candidate.content.parts
                    else []
                )
                if getattr(part, "text", None)
            ]
            if texts:
                cand_details.append(f"text={' '.join(texts)[:500]!r}")
            finish_reason = getattr(candidate, "finish_reason", None)
            if finish_reason is not None:
                cand_details.append(f"finish_reason={finish_reason}")
            finish_message = getattr(candidate, "finish_message", None)
            if finish_message:
                cand_details.append(f"finish_message={finish_message}")
            safety_ratings = getattr(candidate, "safety_ratings", None)
            if safety_ratings:
                ratings = []
                for rating in safety_ratings:
                    category = getattr(rating, "category", None)
                    probability = getattr(rating, "probability", None)
                    blocked = getattr(rating, "blocked", None)
                    rating_str = f"{category or 'UNKNOWN'}(prob={probability or 'UNKNOWN'}, blocked={blocked})"
                    ratings.append(rating_str)
                cand_details.append(f"safety_ratings=[{', '.join(ratings)}]")
            details.append("; ".join(cand_details))
    else:
        details.append("no candidates returned")

    # Inspect prompt feedback
    feedback = getattr(response, "prompt_feedback", None)
    prompt_block_reason = None
    if feedback:
        feedback_details = []
        block_reason = getattr(feedback, "block_reason", None)
        if block_reason:
            prompt_block_reason = block_reason
            feedback_details.append(f"block_reason={block_reason}")
        safety_ratings = getattr(feedback, "safety_ratings", None)
        if safety_ratings:
            ratings = []
            for rating in safety_ratings:
                category = getattr(rating, "category", None)
                probability = getattr(rating, "probability", None)
                blocked = getattr(rating, "blocked", None)
                rating_str = f"{category or 'UNKNOWN'}(prob={probability or 'UNKNOWN'}, blocked={blocked})"
                ratings.append(rating_str)
            feedback_details.append(f"safety_ratings=[{', '.join(ratings)}]")
        details.append(f"prompt_feedback: {'; '.join(feedback_details)}")

    detail_str = " | ".join(details)
    # A terminal policy refusal has a known outcome. Reporting it as a 500
    # makes the caller retain a paid-submission hold indefinitely.
    policy_reasons = {"SAFETY", "PROHIBITED_CONTENT", "IMAGE_SAFETY", "IMAGE_PROHIBITED_CONTENT"}
    candidate_blocked = any(
        str(getattr(getattr(candidate, "finish_reason", None), "value",
                    getattr(candidate, "finish_reason", ""))) in policy_reasons
        for candidate in response.candidates or []
    )
    if prompt_block_reason is not None or candidate_blocked:
        raise litellm.APIError(
            status_code=400,
            message=f"Vertex image request blocked: {detail_str}",
            llm_provider="vertex-multimodal",
            model=str(getattr(response, "model_version", None) or "vertex-image"),
        )
    raise ValueError(f"Vertex response did not contain image bytes: {detail_str} (Full response: {response})")


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


def _estimated_image_cost(
    model: str,
    ref_count: int,
    *,
    image_size: str | None = None,
) -> float | None:
    normalized = _vertex_model(model)
    if normalized == "gemini-3.1-flash-image":
        output_cost = {
            "1K": 0.067,
            "2K": 0.101,
            "4K": 0.151,
        }.get(image_size or "1K", 0.067)
        return output_cost + 0.00056 * ref_count
    if normalized == "gemini-3.1-flash-lite-image":
        # Nano Banana 2 Lite — image output at $30/1M tokens (1120 tokens for a
        # 1K image = $0.0336); input refs at $0.25/1M tokens (1120 tokens = $0.00028).
        return 0.0336 + 0.00028 * ref_count
    if normalized in {"gemini-3-pro-image", "gemini-3-pro-image-preview"}:
        return 0.134 + 0.00112 * ref_count
    return None


vertex_multimodal_llm = VertexMultimodalLLM()
