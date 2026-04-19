"""Image generation: routes to Gemini native or Together AI.

Routing rule (checked in order):
  - model name has no '/'         →  Gemini via google-genai
  - model name contains '/'       →  Together AI (FLUX / SD / etc.)
"""

import asyncio
import base64
import io
import logging
import time
from pathlib import Path

from tenacity import retry, stop_after_attempt, wait_exponential
from together import AsyncTogether

from novel_to_comic.config import Config
from novel_to_comic.clients.gemini import describe_provider, get_client

logger = logging.getLogger("canary.google")
image_logger = logging.getLogger("canary.image")


# ── Routing helpers ───────────────────────────────────────────────────────────

def _is_gemini_native(model: str) -> bool:
    """Gemini generateContent path — not Together AI."""
    return bool(model.strip()) and "/" not in model


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
    from google.genai import types as gtypes

    valid_refs = [p for p in (reference_paths or []) if p.exists()]
    valid_style_refs = [p for p in (style_refs or []) if p.exists()]
    started = time.perf_counter()
    logger.info(
        "[bold cyan]Gemini[/] task=image model=[bold]%s[/] refs=[bold]%d[/] "
        "style_refs=[bold]%d[/] provider=[green]%s[/]",
        config.image_model,
        len(valid_refs),
        len(valid_style_refs),
        describe_provider(config),
    )
    client = get_client(config)
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
            logger.info(
                "[bold green]Gemini done[/] task=image model=[bold]%s[/] elapsed=[bold]%.1fs[/]",
                config.image_model,
                time.perf_counter() - started,
            )
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
    started = time.perf_counter()
    image_logger.info(
        "[bold cyan]Image[/] provider=together model=[bold]%s[/] refs=[bold]%d[/] size=%sx%s",
        config.image_model,
        len([p for p in (reference_paths or []) if p.exists()]),
        width or config.image_width,
        height or config.image_height,
    )
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
    image_logger.info(
        "[bold green]Image done[/] provider=together model=[bold]%s[/] elapsed=[bold]%.1fs[/]",
        config.image_model,
        time.perf_counter() - started,
    )
    return output_path


# ── Public API ────────────────────────────────────────────────────────────────


def _generation_config(config: Config) -> Config:
    model = config.effective_image_model()
    if model.lower().startswith("imagen-"):
        raise ValueError(
            "Imagen image models are no longer supported. Use a Gemini image "
            "model such as gemini-3-pro-image-preview or a Together AI model path."
        )
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
    """Generate a single image, routing to Gemini or Together AI.

    ref_type is retained for call-site readability; Gemini receives any
    reference image as normal image context.
    """
    config = _generation_config(config)
    width, height = _effective_dimensions(config, width, height)
    steps = config.effective_image_steps(steps)
    refs = [reference_image_path] if reference_image_path else None
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
                      Placed before subject refs for Gemini. Ignored for
                      Together AI (no separate style conditioning).
    """
    config = _generation_config(config)
    width, height = _effective_dimensions(config, width, height)
    steps = config.effective_image_steps(steps)
    if _is_gemini_native(config.image_model):
        result = await _generate_gemini_image(config, prompt, output_path, reference_paths, width, height, style_refs)
        return await _downscale_dev_output(config, result, width, height)
    result = await _generate_together_image(config, prompt, output_path, width, height, steps, reference_paths)
    return await _downscale_dev_output(config, result, width, height)
