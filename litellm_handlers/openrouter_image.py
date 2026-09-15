"""LiteLLM custom provider for OpenRouter's dedicated Images API.

LiteLLM's OpenAI-compatible Images endpoints do not route OpenRouter image
models.  Keep Canary's gateway boundary intact and translate those requests
to OpenRouter's native ``/api/v1/images`` endpoint here instead.
"""

from __future__ import annotations

import asyncio
import base64
import mimetypes
import os
import time
from pathlib import Path
from typing import Any

import httpx

try:
    import litellm
    from litellm.llms.custom_llm import CustomLLM
    from litellm.types.utils import ImageObject, ImageResponse
except ModuleNotFoundError:
    class CustomLLM:
        pass

    class ImageObject:
        def __init__(self, **kwargs: Any):
            self.__dict__.update(kwargs)

    class ImageResponse:
        pass

    class _LiteLLMFallback:
        class APIError(Exception):
            def __init__(self, status_code: int, message: str, llm_provider: str, model: str):
                super().__init__(message)
                self.status_code = status_code
                self.llm_provider = llm_provider
                self.model = model

    litellm = _LiteLLMFallback()


OPENROUTER_IMAGES_URL = "https://openrouter.ai/api/v1/images"


class OpenRouterImageLLM(CustomLLM):
    """Translate LiteLLM image calls to OpenRouter's native Images API."""

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
        **kwargs: Any,  # noqa: ARG002
    ) -> ImageResponse:
        return asyncio.run(self._generate_async(
            model=model, image=image, prompt=prompt or "", model_response=model_response,
            api_key=api_key, optional_params=optional_params or {}, timeout=timeout,
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
        **kwargs: Any,  # noqa: ARG002
    ) -> ImageResponse:
        return await self._generate_async(
            model=model, image=image, prompt=prompt or "", model_response=model_response,
            api_key=api_key, optional_params=optional_params or {}, timeout=timeout,
        )

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
        **kwargs: Any,  # noqa: ARG002
    ) -> ImageResponse:
        return asyncio.run(self._generate_async(
            model=model, image=[], prompt=prompt, model_response=model_response,
            api_key=api_key, optional_params=optional_params or {}, timeout=timeout,
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
        **kwargs: Any,  # noqa: ARG002
    ) -> ImageResponse:
        return await self._generate_async(
            model=model, image=[], prompt=prompt, model_response=model_response,
            api_key=api_key, optional_params=optional_params or {}, timeout=timeout,
        )

    async def _generate_async(
        self,
        *,
        model: str,
        image: list[Any],
        prompt: str,
        model_response: ImageResponse,
        api_key: str | None,
        optional_params: dict[str, Any],
        timeout: float | httpx.Timeout | None,
    ) -> ImageResponse:
        payload = _build_payload(model, prompt, image, optional_params)
        request_timeout = timeout if timeout is not None else 300.0
        async with httpx.AsyncClient(timeout=request_timeout) as http:
            response = await http.post(
                OPENROUTER_IMAGES_URL,
                headers=_headers(api_key),
                json=payload,
            )
        if response.status_code >= 400:
            raise _provider_http_error(response, model)
        data = response.json()
        encoded = _image_b64(data)
        model_response.created = int(data.get("created") or time.time())
        model_response.data = [ImageObject(b64_json=encoded)]
        model_response.model = str(data.get("model") or f"openrouter/{_model_slug(model)}")
        model_response._hidden_params["model"] = model_response.model
        model_response._hidden_params["custom_llm_provider"] = "openrouter-image"
        model_response._hidden_params["response_cost"] = _response_cost(data)
        return model_response


def _model_slug(model: str) -> str:
    cleaned = (model or "").strip().strip("/")
    for prefix in ("openrouter-image/", "openrouter/"):
        if cleaned.startswith(prefix):
            return cleaned.removeprefix(prefix)
    return cleaned


def _build_payload(
    model: str, prompt: str, images: list[Any], params: dict[str, Any],
) -> dict[str, Any]:
    payload: dict[str, Any] = {"model": _model_slug(model), "prompt": prompt}
    for key in ("n", "size", "resolution", "aspect_ratio", "quality", "output_format", "background", "seed"):
        value = params.get(key)
        if value is not None:
            payload[key] = value
    references = [_input_reference(item) for item in images]
    references = [reference for reference in references if reference is not None]
    if references:
        payload["input_references"] = references
    return payload


def _input_reference(item: Any) -> dict[str, Any] | None:
    filename, data, mime = _image_bytes(item)
    if data is None:
        return None
    media_type = _media_type(filename, data, mime)
    b64 = base64.b64encode(data).decode("ascii")
    return {"type": "image_url", "image_url": {"url": f"data:{media_type};base64,{b64}"}}


def _image_bytes(item: Any) -> tuple[str, bytes | None, str | None]:
    filename = "image.png"
    mime: str | None = None
    raw: Any = item
    if isinstance(item, tuple):
        if item and item[0]:
            filename = Path(str(item[0])).name
        raw = item[1] if len(item) >= 2 else None
        mime = str(item[2]) if len(item) >= 3 and item[2] else None
    else:
        name = getattr(item, "filename", None) or getattr(item, "name", None)
        if name:
            filename = Path(str(name)).name
        content_type = getattr(item, "content_type", None)
        if content_type:
            mime = str(content_type)
    return filename, _read_bytes(raw), mime


def _read_bytes(value: Any) -> bytes | None:
    if value is None:
        return None
    if isinstance(value, bytes):
        return value
    if isinstance(value, bytearray):
        return bytes(value)
    if isinstance(value, str):
        path = Path(value)
        return path.read_bytes() if path.exists() else None
    reader = getattr(value, "read", None)
    if callable(reader):
        try:
            seeker = getattr(value, "seek", None)
            if callable(seeker):
                seeker(0)
            output = reader()
            return output.encode("utf-8") if isinstance(output, str) else bytes(output)
        finally:
            seeker = getattr(value, "seek", None)
            if callable(seeker):
                seeker(0)
    return None


def _media_type(filename: str, data: bytes, declared: str | None) -> str:
    """Return the type proved by the bytes, not a stale artifact extension.

    Providers may return WebP while the pipeline keeps a stable ``.png``
    artifact name. OpenRouter validates the data URL declaration against the
    uploaded bytes, so filename and multipart metadata are insufficient.
    """
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "image/webp"
    guessed, _ = mimetypes.guess_type(filename)
    return guessed or declared or "image/png"


def _headers(api_key: str | None) -> dict[str, str]:
    key = (api_key or os.environ.get("OPENROUTER_API_KEY") or "").strip()
    if not key:
        raise ValueError("OPENROUTER_API_KEY is not set")
    return {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}


def _provider_http_error(response: httpx.Response, model: str) -> BaseException:
    """Preserve a definitive OpenRouter rejection through LiteLLM.

    Raising ``ValueError`` makes LiteLLM report the provider's known 4xx as a
    gateway 500. The application must retain a credit hold for a genuine 500,
    so map the upstream status to LiteLLM's typed API error instead.
    """
    return litellm.APIError(
        status_code=response.status_code,
        message=(
            f"OpenRouter image generation failed ({response.status_code}): "
            f"{response.text[:600]}"
        ),
        llm_provider="openrouter-image",
        model=_model_slug(model),
    )


def _image_b64(payload: Any) -> str:
    if not isinstance(payload, dict):
        raise ValueError("OpenRouter image response must be an object")
    images = payload.get("data")
    first = images[0] if isinstance(images, list) and images else None
    encoded = first.get("b64_json") if isinstance(first, dict) else None
    if not isinstance(encoded, str) or not encoded:
        raise ValueError("OpenRouter image response is missing data[0].b64_json")
    return encoded


def _response_cost(payload: Any) -> float | None:
    usage = payload.get("usage") if isinstance(payload, dict) else None
    cost = usage.get("cost") if isinstance(usage, dict) else None
    return float(cost) if isinstance(cost, int | float) else None


openrouter_image_llm = OpenRouterImageLLM()
