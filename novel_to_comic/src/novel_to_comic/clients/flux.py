"""Image generation: routes to Imagen 4, Gemini native, or Together AI.

Routing rule (checked in order):
  - model starts with 'imagen-'   →  Google Imagen API  (predict endpoint)
  - model name has no '/'         →  Gemini Developer API (generateContent + response_modalities)
  - model name contains '/'       →  Together AI (FLUX / SD / etc.)
"""

import asyncio
import base64
import io
from math import gcd
from pathlib import Path

import httpx
from tenacity import retry, retry_if_not_exception_type, stop_after_attempt, wait_exponential
from together import AsyncTogether

from novel_to_comic.config import Config

_IMAGEN_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:predict"


class ImagenRateLimitError(Exception):
    """Raised on HTTP 429 from Imagen — don't retry, switch to fallback model."""

# Aspect ratios supported by Imagen 4
_IMAGEN_RATIOS: dict[str, float] = {
    "1:1": 1.0,
    "3:4": 0.75,
    "4:3": 1.333,
    "9:16": 0.5625,
    "16:9": 1.777,
}


# ── Routing helpers ───────────────────────────────────────────────────────────

def _is_imagen(model: str) -> bool:
    return model.lower().startswith("imagen-")


def _is_gemini_native(model: str) -> bool:
    """Gemini generateContent path — not Imagen, not Together AI."""
    return "/" not in model and not _is_imagen(model)


# ── Together AI capability flags ──────────────────────────────────────────────

def _supports_steps(model: str) -> bool:
    lower = model.lower()
    return any(x in lower for x in ("schnell", "-dev", "flex", "stable-diffusion", "juggernaut"))


def _supports_n(model: str) -> bool:
    return "google/" not in model.lower()


def _supports_image_url(model: str) -> bool:
    """Only kontext models accept image_url for img2img."""
    return "kontext" in model.lower()


def _supports_negative_prompt(model: str) -> bool:
    lower = model.lower()
    return any(x in lower for x in ("stable-diffusion", "sdxl", "juggernaut", "sd-xl"))


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_together_client(config: Config) -> AsyncTogether:
    return AsyncTogether(api_key=config.together_api_key)


def _encode_image_sync(path: Path) -> str:
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode()


def _closest_aspect_ratio(width: int, height: int) -> str:
    """Map pixel dimensions to the nearest Imagen 4 supported aspect ratio string."""
    ratio = width / height
    return min(_IMAGEN_RATIOS, key=lambda k: abs(_IMAGEN_RATIOS[k] - ratio))


# ── Imagen 4 implementation ───────────────────────────────────────────────────

@retry(
    wait=wait_exponential(min=5, max=120),
    stop=stop_after_attempt(4),
    retry=retry_if_not_exception_type(ImagenRateLimitError),
)
async def _generate_imagen_image(
    config: Config,
    prompt: str,
    output_path: Path,
    width: int | None = None,
    height: int | None = None,
    reference_paths: list[Path] | None = None,
    ref_type: str = "subject",
    style_refs: list[Path] | None = None,
) -> Path:
    """Generate image via Google Imagen 4 predict endpoint.

    Imagen 4 is a dedicated image generation model — higher quality than
    Gemini's built-in generateContent image path. Uses aspect ratio strings
    rather than pixel dimensions.

    reference_paths — subject references (character identity, REFERENCE_TYPE_SUBJECT)
    style_refs      — style references (art style / environment, REFERENCE_TYPE_STYLE)

    Imagen 4 supports a maximum of 4 reference images total. Style refs are
    allocated first (up to 2), remaining slots go to subject refs.
    """
    w = width or config.image_width
    h = height or config.image_height
    aspect_ratio = _closest_aspect_ratio(w, h)

    instance: dict = {"prompt": prompt}

    valid_style = [p for p in (style_refs or []) if p.exists()][:2]
    max_subject = max(0, 4 - len(valid_style))

    # For character-sheet generation (legacy ref_type="style" call site in s2),
    # treat all reference_paths as style refs when ref_type == "style".
    if ref_type == "style":
        valid_style = [p for p in (reference_paths or []) if p.exists()][:4]
        valid_subject: list[Path] = []
    else:
        valid_subject = [p for p in (reference_paths or []) if p.exists()][:max_subject]

    if valid_style or valid_subject:
        ref_list = []
        ref_idx = 1
        for ref_path in valid_style:
            ref_bytes = await asyncio.to_thread(ref_path.read_bytes)
            b64 = base64.b64encode(ref_bytes).decode()
            ref_list.append({
                "referenceType": "REFERENCE_TYPE_STYLE",
                "referenceId": ref_idx,
                "referenceImage": {"bytesBase64Encoded": b64},
                "styleImageConfig": {},
            })
            ref_idx += 1
        for ref_path in valid_subject:
            ref_bytes = await asyncio.to_thread(ref_path.read_bytes)
            b64 = base64.b64encode(ref_bytes).decode()
            ref_list.append({
                "referenceType": "REFERENCE_TYPE_SUBJECT",
                "referenceId": ref_idx,
                "referenceImage": {"bytesBase64Encoded": b64},
                "subjectImageConfig": {"subjectType": "SUBJECT_TYPE_PERSON"},
            })
            ref_idx += 1
        if ref_list:
            instance["referenceImages"] = ref_list

    body = {
        "instances": [instance],
        "parameters": {
            "sampleCount": 1,
            "aspectRatio": aspect_ratio,
            "safetyFilterLevel": "block_some",
            "personGeneration": "allow_adult",
        },
    }

    url = _IMAGEN_URL.format(model=config.image_model)
    async with httpx.AsyncClient(timeout=120.0) as client:
        response = await client.post(
            url, params={"key": config.gemini_api_key}, json=body
        )

    if response.status_code == 429:
        raise ImagenRateLimitError(f"Imagen API 429: {response.text[:300]}")
    if response.status_code != 200:
        raise ValueError(f"Imagen API {response.status_code}: {response.text[:300]}")

    data = response.json()
    predictions = data.get("predictions", [])
    if not predictions:
        raise ValueError(f"No predictions in Imagen response: {list(data.keys())}")

    b64_data = predictions[0].get("bytesBase64Encoded", "")
    if not b64_data:
        raise ValueError("Empty bytesBase64Encoded in Imagen prediction")

    image_bytes = base64.b64decode(b64_data)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    await asyncio.to_thread(output_path.write_bytes, image_bytes)
    return output_path


# ── Gemini native implementation ──────────────────────────────────────────────

@retry(wait=wait_exponential(min=5, max=120), stop=stop_after_attempt(4))
async def _generate_gemini_image(
    config: Config,
    prompt: str,
    output_path: Path,
    reference_paths: list[Path] | None = None,
    width: int | None = None,
    height: int | None = None,
    style_refs: list[Path] | None = None,
) -> Path:
    """Generate image via Gemini generateContent with response_modalities=IMAGE.

    ``width`` and ``height``, when provided, override ``config.image_width/height``
    for the aspect ratio hint and post-crop.  Pass per-panel dimensions (from
    the ImagePrompt) so each shot type gets the correct portrait ratio rather
    than always using the global config default.

    style_refs are placed BEFORE subject refs in the contents list so they
    receive higher positional weight in the model's attention.
    """
    from google import genai
    from google.genai import types as gtypes

    client = genai.Client(api_key=config.gemini_api_key)
    contents: list = []

    # Style refs first — positional weight is highest at the start of the context.
    for ref_path in [p for p in (style_refs or []) if p.exists()][:3]:
        ref_bytes = await asyncio.to_thread(ref_path.read_bytes)
        contents.append(gtypes.Part.from_bytes(data=ref_bytes, mime_type="image/png"))

    # Subject refs (character sheets) after style refs.
    if reference_paths:
        for ref_path in [p for p in reference_paths if p.exists()][:3]:
            ref_bytes = await asyncio.to_thread(ref_path.read_bytes)
            contents.append(gtypes.Part.from_bytes(data=ref_bytes, mime_type="image/png"))

    # Nudge Gemini toward the requested aspect ratio.  The model picks its own
    # resolution, so we hint in the prompt and then center-crop as a fallback.
    w = width or config.image_width
    h = height or config.image_height
    target_ratio = w / h
    if abs(target_ratio - 1.0) < 0.05:
        shape_hint = "SQUARE panel (equal width and height, 1:1 ratio)."
    elif target_ratio < 1.0:
        shape_hint = "VERTICAL PORTRAIT panel (taller than wide)."
    else:
        shape_hint = "HORIZONTAL LANDSCAPE panel (wider than tall)."
    contents.append(prompt + f"\n\nCompose as a {shape_hint}")

    response = await client.aio.models.generate_content(
        model=config.image_model,
        contents=contents,
        config=gtypes.GenerateContentConfig(response_modalities=["IMAGE", "TEXT"]),
    )

    for part in response.candidates[0].content.parts:
        if hasattr(part, "inline_data") and part.inline_data:
            raw = part.inline_data.data
            image_bytes = base64.b64decode(raw) if isinstance(raw, str) else bytes(raw)

            # Post-process: center-crop to the configured aspect ratio if the
            # returned image is significantly off (handles both landscape→square
            # and portrait→square corrections).
            try:
                from PIL import Image as _PILImage
                _img = _PILImage.open(io.BytesIO(image_bytes))
                _sw, _sh = _img.size
                _src_ratio = _sw / _sh
                if abs(_src_ratio - target_ratio) > 0.1:
                    if _src_ratio > target_ratio:
                        # Too wide — crop horizontally
                        _new_w = int(_sh * target_ratio)
                        _left = (_sw - _new_w) // 2
                        _img = _img.crop((_left, 0, _left + _new_w, _sh))
                    else:
                        # Too tall — crop vertically
                        _new_h = int(_sw / target_ratio)
                        _top = (_sh - _new_h) // 2
                        _img = _img.crop((0, _top, _sw, _top + _new_h))
                    _buf = io.BytesIO()
                    _img.save(_buf, format="PNG")
                    image_bytes = _buf.getvalue()
            except Exception:
                pass  # if crop fails, save the original

            output_path.parent.mkdir(parents=True, exist_ok=True)
            await asyncio.to_thread(output_path.write_bytes, image_bytes)
            return output_path

    text = getattr(response, "text", "no text")
    raise ValueError(f"No image part in Gemini response. Model said: {text}")


# ── Together AI implementation ────────────────────────────────────────────────

@retry(wait=wait_exponential(min=5, max=120), stop=stop_after_attempt(5))
async def _generate_together_image(
    config: Config,
    prompt: str,
    output_path: Path,
    width: int | None = None,
    height: int | None = None,
    steps: int | None = None,
    reference_paths: list[Path] | None = None,
) -> Path:
    """Generate image via Together AI (FLUX.2, SD, etc.)."""
    client = _get_together_client(config)

    kwargs: dict = {
        "model": config.image_model,
        "prompt": prompt,
        "width": width or config.image_width,
        "height": height or config.image_height,
        "response_format": "b64_json",
    }
    if _supports_n(config.image_model):
        kwargs["n"] = 1
    if _supports_steps(config.image_model):
        kwargs["steps"] = steps or config.image_steps
    neg = getattr(config, "negative_prompt", "")
    if neg and _supports_negative_prompt(config.image_model):
        kwargs["negative_prompt"] = neg

    if reference_paths and _supports_image_url(config.image_model):
        valid = [p for p in reference_paths if p.exists()][:8]
        if valid:
            encoded = [
                f"data:image/png;base64,{await asyncio.to_thread(_encode_image_sync, p)}"
                for p in valid
            ]
            if len(encoded) == 1:
                kwargs["image_url"] = encoded[0]
            else:
                try:
                    kwargs["image_urls"] = encoded
                    response = await client.images.generate(**kwargs)
                    if not response.data or not response.data[0].b64_json:
                        raise ValueError("Empty multi-ref response")
                    image_data = base64.b64decode(response.data[0].b64_json)
                    output_path.parent.mkdir(parents=True, exist_ok=True)
                    await asyncio.to_thread(output_path.write_bytes, image_data)
                    return output_path
                except Exception:
                    kwargs.pop("image_urls", None)
                    kwargs["image_url"] = encoded[0]

    response = await client.images.generate(**kwargs)
    if not response.data or not response.data[0].b64_json:
        raise ValueError("Empty image response from Together AI")

    image_data = base64.b64decode(response.data[0].b64_json)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    await asyncio.to_thread(output_path.write_bytes, image_data)
    return output_path


# ── Public API ────────────────────────────────────────────────────────────────

def _fallback_config(config: Config) -> Config | None:
    """Return a config with fallback_image_model set as image_model, or None."""
    fallback = config.fallback_image_model.strip()
    if fallback and fallback != config.image_model:
        return config.model_copy(update={"image_model": fallback})
    return None


def _generation_config(config: Config) -> Config:
    model = config.effective_image_model()
    if model != config.image_model:
        return config.model_copy(update={"image_model": model})
    return config


def _effective_dimensions(config: Config, width: int | None, height: int | None) -> tuple[int, int]:
    w = width or config.image_width
    h = height or config.image_height
    return config.effective_image_dimensions(w, h)


async def _downscale_dev_output(config: Config, path: Path, width: int, height: int) -> Path:
    if not config.dev_mode or not path.exists():
        return path
    try:
        from PIL import Image as _PILImage
        img = await asyncio.to_thread(_PILImage.open, path)
        if img.width <= width and img.height <= height:
            return path
        img.thumbnail((width, height), _PILImage.Resampling.LANCZOS)
        await asyncio.to_thread(img.save, path)
    except Exception:
        pass
    return path


async def _dispatch(
    config: Config,
    prompt: str,
    output_path: Path,
    width: int | None,
    height: int | None,
    steps: int | None,
    refs: list[Path] | None,
    ref_type: str,
    style_refs: list[Path] | None = None,
) -> Path:
    """Route a generation request to the correct backend for config.image_model."""
    if _is_imagen(config.image_model):
        return await _generate_imagen_image(config, prompt, output_path, width, height, refs, ref_type, style_refs)
    if _is_gemini_native(config.image_model):
        return await _generate_gemini_image(config, prompt, output_path, refs, width, height, style_refs)
    return await _generate_together_image(config, prompt, output_path, width, height, steps, refs)


async def generate_image(
    config: Config,
    prompt: str,
    output_path: Path,
    width: int | None = None,
    height: int | None = None,
    steps: int | None = None,
    reference_image_path: Path | None = None,
    ref_type: str = "subject",
) -> Path:
    """Generate a single image, routing to Imagen 4, Gemini, or Together AI.

    ref_type: "subject" (character identity) or "style" (art style transfer).
    Only meaningful for Imagen 4. On 429, automatically retries with fallback_image_model.
    """
    config = _generation_config(config)
    width, height = _effective_dimensions(config, width, height)
    steps = config.effective_image_steps(steps)
    refs = [reference_image_path] if reference_image_path else None
    if _is_imagen(config.image_model):
        try:
            result = await _generate_imagen_image(config, prompt, output_path, width, height, refs, ref_type)
            return await _downscale_dev_output(config, result, width, height)
        except ImagenRateLimitError:
            fb = _fallback_config(config)
            if fb:
                from rich.console import Console
                Console().print(f"[yellow]Rate limited on {config.image_model} → falling back to {fb.image_model}[/yellow]")
                result = await _dispatch(fb, prompt, output_path, width, height, steps, refs, ref_type)
                return await _downscale_dev_output(config, result, width, height)
            raise
    if _is_gemini_native(config.image_model):
        result = await _generate_gemini_image(config, prompt, output_path, refs, width, height)
        return await _downscale_dev_output(config, result, width, height)
    result = await _generate_together_image(config, prompt, output_path, width, height, steps, refs)
    return await _downscale_dev_output(config, result, width, height)


async def generate_image_multi_ref(
    config: Config,
    prompt: str,
    output_path: Path,
    reference_paths: list[Path],
    width: int | None = None,
    height: int | None = None,
    steps: int | None = None,
    ref_type: str = "subject",
    style_refs: list[Path] | None = None,
) -> Path:
    """Generate a panel image conditioned on character reference images and style refs.

    reference_paths — subject/character refs (identity conditioning).
    style_refs      — style/environment refs: style sample, location plate, scene anchor.
                      Placed before subject refs for Gemini; sent as REFERENCE_TYPE_STYLE
                      for Imagen. Ignored for Together AI (no separate style conditioning).
    On 429, automatically retries with fallback_image_model.
    """
    config = _generation_config(config)
    width, height = _effective_dimensions(config, width, height)
    steps = config.effective_image_steps(steps)
    if _is_imagen(config.image_model):
        try:
            result = await _generate_imagen_image(config, prompt, output_path, width, height, reference_paths, ref_type, style_refs)
            return await _downscale_dev_output(config, result, width, height)
        except ImagenRateLimitError:
            fb = _fallback_config(config)
            if fb:
                from rich.console import Console
                Console().print(f"[yellow]Rate limited on {config.image_model} → falling back to {fb.image_model}[/yellow]")
                result = await _dispatch(fb, prompt, output_path, width, height, steps, reference_paths, ref_type, style_refs)
                return await _downscale_dev_output(config, result, width, height)
            raise
    if _is_gemini_native(config.image_model):
        result = await _generate_gemini_image(config, prompt, output_path, reference_paths, width, height, style_refs)
        return await _downscale_dev_output(config, result, width, height)
    result = await _generate_together_image(config, prompt, output_path, width, height, steps, reference_paths)
    return await _downscale_dev_output(config, result, width, height)
