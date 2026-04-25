"""Image generation: routes to Gemini native, OpenAI, Together AI, or OpenRouter.

Routing rule:
  - config.image_provider == "gemini"     →  Gemini via google-genai
  - config.image_provider == "openai"     →  OpenAI Images API
  - config.image_provider == "openrouter" →  OpenRouter (OpenAI API-compatible endpoint)
  - config.image_provider == "together"   →  Together AI
"""

import asyncio
import base64
import io
import logging
from pathlib import Path
from typing import Any

from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
    wait_random_exponential,
)
from openai import AsyncOpenAI
from together import AsyncTogether

from novel_to_comic.clients.api_logging import image_payload_summary, log_call_end, log_call_start
from novel_to_comic.config import Config
from novel_to_comic.clients.gemini import get_client

logger = logging.getLogger("canary.google")
image_logger = logging.getLogger("canary.image")


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


def _get_openai_client(config: Config) -> AsyncOpenAI:
    return AsyncOpenAI(api_key=config.openai_api_key)


def _get_openrouter_client(config: Config) -> AsyncOpenAI:
    return AsyncOpenAI(
        api_key=config.openrouter_api_key,
        base_url="https://openrouter.ai/api/v1",
    )


def _encode_image_sync(path: Path) -> str:
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode()


def _openai_size_for_dims(width: int, height: int) -> str:
    """Map arbitrary dimensions to OpenAI-supported output sizes."""
    if height <= 0:
        return "1024x1024"
    ratio = width / height
    # OpenAI GPT Image supports portrait 1024x1536, square 1024x1024, landscape 1536x1024.
    if ratio < 0.87:
        return "1024x1536"
    if ratio > 1.15:
        return "1536x1024"
    return "1024x1024"


def _exception_chain(exc: BaseException) -> list[BaseException]:
    chain: list[BaseException] = []
    seen: set[int] = set()
    node: BaseException | None = exc
    while node is not None and id(node) not in seen:
        seen.add(id(node))
        chain.append(node)
        node = getattr(node, "__cause__", None) or getattr(node, "__context__", None)
    return chain


def is_rate_limited_error(exc: BaseException) -> bool:
    """Return True when an exception chain indicates provider throttling/quota."""
    tokens = ("429", "resource_exhausted", "rate limit", "quota")
    for node in _exception_chain(exc):
        code = getattr(node, "code", None)
        status = getattr(node, "status", None)
        if code == 429:
            return True
        if isinstance(status, str) and status.upper() == "RESOURCE_EXHAUSTED":
            return True
        text = str(node).lower()
        if any(tok in text for tok in tokens):
            return True
        # Some SDK errors put structured details on .args / .response
        args_text = " ".join(str(a).lower() for a in getattr(node, "args", ()) if a is not None)
        if any(tok in args_text for tok in tokens):
            return True
        response: Any = getattr(node, "response", None)
        if response is not None:
            resp_text = str(response).lower()
            if any(tok in resp_text for tok in tokens):
                return True
    return False


def _is_retryable_gemini_image_error(exc: BaseException) -> bool:
    # Always retry on explicit quota/rate-limit failures.
    if is_rate_limited_error(exc):
        return True
    # Retry common transient transport/server failures.
    transient_tokens = (
        "deadline exceeded",
        "timed out",
        "timeout",
        "temporarily unavailable",
        "internal server error",
        "service unavailable",
        "connection reset",
        "connecterror",
    )
    chain_text = " ".join(str(node).lower() for node in _exception_chain(exc))
    return any(tok in chain_text for tok in transient_tokens)


# ── Gemini native implementation ──────────────────────────────────────────────

@retry(
    wait=wait_random_exponential(multiplier=4, max=180),
    stop=stop_after_attempt(8),
    retry=retry_if_exception(_is_retryable_gemini_image_error),
    reraise=True,
)
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

    Subject refs are placed BEFORE style refs so character identity — the
    hardest consistency problem — gets the strongest positional weight.
    Caller is responsible for deduping style_refs (prefer a single scene
    anchor once available, otherwise a global style sample + optional plate).
    """
    from google.genai import types as gtypes

    valid_refs = [p for p in (reference_paths or []) if p.exists()]
    valid_style_refs = [p for p in (style_refs or []) if p.exists()]
    call_id, started = log_call_start(
        logger,
        provider="gemini",
        operation="generate",
        task="image",
        params={
            "model": config.image_model,
            "refs": len(valid_refs),
            "style_refs": len(valid_style_refs),
            "width": width or config.image_width,
            "height": height or config.image_height,
        },
        payload=image_payload_summary(prompt),
    )
    client = get_client(config)
    contents: list = []
    reference_notes: list[str] = []

    # Subject refs first — strongest positional weight goes to character identity.
    # Cap at 4 to support multi-character dialogue panels without overrunning the
    # model's effective reference-image budget.
    subject_count = 0
    if reference_paths:
        for ref_path in [p for p in reference_paths if p.exists()][:4]:
            ref_bytes = await asyncio.to_thread(ref_path.read_bytes)
            contents.append(gtypes.Part.from_bytes(data=ref_bytes, mime_type="image/png"))
            subject_count += 1
    if subject_count:
        if subject_count == 1:
            reference_notes.append(
                "Image 1 is a character identity reference. Preserve that "
                "character's face, build, hair, and clothing continuity."
            )
        else:
            reference_notes.append(
                f"Images 1-{subject_count} are character identity references. "
                "Preserve each character's face, build, hair, and clothing continuity."
            )

    # Style / continuity refs after subjects. Capped at 2; caller dedups so this
    # is typically a single scene anchor, or style_sample (+ plate) for the
    # first panel of a scene.
    style_count = 0
    for ref_path in [p for p in (style_refs or []) if p.exists()][:2]:
        ref_bytes = await asyncio.to_thread(ref_path.read_bytes)
        contents.append(gtypes.Part.from_bytes(data=ref_bytes, mime_type="image/png"))
        style_count += 1
    if style_count:
        start = subject_count + 1
        end = subject_count + style_count
        if style_count == 1:
            reference_notes.append(
                f"Image {start} is a visual style reference. "
                "Match its rendering medium, palette, mark-making, and lighting language "
                "without copying its exact composition unless requested."
            )
        else:
            # Two style refs: first is the global style sample, second is the location plate.
            reference_notes.append(
                f"Image {start} is a global visual style reference: match its rendering "
                "medium, palette, mark-making, and lighting language."
            )
            reference_notes.append(
                f"Image {end} is a location/environment reference: match its spatial "
                "setting and atmosphere, not its rendering style."
            )

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
    reference_instruction = "\n".join(reference_notes)
    if reference_instruction:
        reference_instruction = (
            "REFERENCE IMAGE INSTRUCTIONS:\n"
            f"{reference_instruction}\n"
            "The written panel prompt is authoritative for action, camera, framing, and subject count.\n\n"
        )
    contents.append(reference_instruction + prompt + f"\n\nCompose as a {shape_hint}")

    try:
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
                log_call_end(
                    logger,
                    call_id=call_id,
                    started=started,
                    provider="gemini",
                    operation="generate",
                    task="image",
                    ok=True,
                    result={
                        "image_bytes": len(image_bytes),
                        "candidates": len(getattr(response, "candidates", []) or []),
                    },
                )
                return output_path

        text = getattr(response, "text", "no text")
        raise ValueError(f"No image part in Gemini response. Model said: {text}")
    except Exception as e:
        log_call_end(
            logger,
            call_id=call_id,
            started=started,
            provider="gemini",
            operation="generate",
            task="image",
            ok=False,
            error=e,
        )
        raise


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
    call_id, started = log_call_start(
        image_logger,
        provider="together",
        operation="generate",
        task="image",
        params={
            "model": config.image_model,
            "refs": len([p for p in (reference_paths or []) if p.exists()]),
            "width": width or config.image_width,
            "height": height or config.image_height,
            "steps": steps or config.image_steps,
        },
        payload=image_payload_summary(prompt),
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
                    log_call_end(
                        image_logger,
                        call_id=call_id,
                        started=started,
                        provider="together",
                        operation="generate",
                        task="image",
                        ok=True,
                        result={"image_bytes": len(image_data), "ref_mode": "multi"},
                    )
                    return output_path
                except Exception:
                    kwargs.pop("image_urls", None)
                    kwargs["image_url"] = encoded[0]

    try:
        response = await client.images.generate(**kwargs)
        if not response.data or not response.data[0].b64_json:
            raise ValueError("Empty image response from Together AI")

        image_data = base64.b64decode(response.data[0].b64_json)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(output_path.write_bytes, image_data)
        log_call_end(
            image_logger,
            call_id=call_id,
            started=started,
            provider="together",
            operation="generate",
            task="image",
            ok=True,
            result={"image_bytes": len(image_data), "ref_mode": "single_or_none"},
        )
        return output_path
    except Exception as e:
        log_call_end(
            image_logger,
            call_id=call_id,
            started=started,
            provider="together",
            operation="generate",
            task="image",
            ok=False,
            error=e,
        )
        raise


@retry(wait=wait_exponential(min=5, max=120), stop=stop_after_attempt(5))
async def _generate_openai_image(
    config: Config,
    prompt: str,
    output_path: Path,
    width: int | None = None,
    height: int | None = None,
    reference_paths: list[Path] | None = None,
    style_refs: list[Path] | None = None,
) -> Path:
    """Generate image via OpenAI Images API (GPT Image family)."""
    subject_refs = [p for p in (reference_paths or []) if p.exists()]
    aux_refs = [p for p in (style_refs or []) if p.exists()]
    edit_refs = (subject_refs + aux_refs)[:8]
    call_id, started = log_call_start(
        image_logger,
        provider="openai",
        operation="generate",
        task="image",
        params={
            "model": config.image_model,
            "subject_refs": len(subject_refs),
            "style_refs": len(aux_refs),
            "width": width or config.image_width,
            "height": height or config.image_height,
        },
        payload=image_payload_summary(prompt),
    )
    client = _get_openai_client(config)
    w = width or config.image_width
    h = height or config.image_height
    size = _openai_size_for_dims(w, h)
    quality = (getattr(config, "image_quality", "auto") or "auto").lower()
    if quality not in {"auto", "low", "medium", "high"}:
        quality = "auto"

    file_handles = []
    try:
        if edit_refs:
            # Condition generation on references through the edit endpoint.
            # OpenAI supports up to 16 input images; we cap to 8 for latency.
            for path in edit_refs:
                file_handles.append(open(path, "rb"))
            response = await client.images.edit(
                model=config.image_model,
                prompt=prompt,
                image=file_handles,
                size=size,
                quality=quality,
            )
        else:
            response = await client.images.generate(
                model=config.image_model,
                prompt=prompt,
                size=size,
                quality=quality,
            )
        if not response.data or not response.data[0].b64_json:
            raise ValueError("Empty image response from OpenAI")

        image_data = base64.b64decode(response.data[0].b64_json)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(output_path.write_bytes, image_data)
        log_call_end(
            image_logger,
            call_id=call_id,
            started=started,
            provider="openai",
            operation="generate",
            task="image",
            ok=True,
            result={"image_bytes": len(image_data)},
        )
        return output_path
    except Exception as e:
        log_call_end(
            image_logger,
            call_id=call_id,
            started=started,
            provider="openai",
            operation="generate",
            task="image",
            ok=False,
            error=e,
        )
        raise
    finally:
        for handle in file_handles:
            try:
                handle.close()
            except Exception:
                pass


# ── OpenRouter implementation ───────────────────────────────────────────────────

_OPENROUTER_IMG2IMG_MODELS: frozenset = frozenset({
    "stability-ai/stable-diffusion-xl-base-1.0",
    "stability-ai/sd3.5-medium",
    "stability-ai/sd3-large",
    "playgroundai/playground-v2.5",
    "playgroundai/playground-v2",
})


def _supports_openrouter_img2img(model: str) -> bool:
    return model.lower() in _OPENROUTER_IMG2IMG_MODELS


@retry(wait=wait_exponential(min=5, max=120), stop=stop_after_attempt(5))
async def _generate_openrouter_image(
    config: Config,
    prompt: str,
    output_path: Path,
    width: int | None = None,
    height: int | None = None,
    reference_paths: list[Path] | None = None,
    style_refs: list[Path] | None = None,
) -> Path:
    """Generate image via OpenRouter (OpenAI API-compatible endpoint).

    Reference images are passed as image_url for models that support img2img.
    """
    subject_refs = [p for p in (reference_paths or []) if p.exists()]
    aux_refs = [p for p in (style_refs or []) if p.exists()]
    # OpenRouter's images.generate compatibility path only supports one
    # image_url here. Prefer the style anchor when present; character identity
    # still comes through the written visual anchors in the prompt.
    edit_refs = (aux_refs or subject_refs)[:1]
    call_id, started = log_call_start(
        image_logger,
        provider="openrouter",
        operation="generate",
        task="image",
        params={
            "model": config.image_model,
            "subject_refs": len(subject_refs),
            "style_refs": len(aux_refs),
            "width": width or config.image_width,
            "height": height or config.image_height,
        },
        payload=image_payload_summary(prompt),
    )
    client = _get_openrouter_client(config)
    w = width or config.image_width
    h = height or config.image_height
    size = _openai_size_for_dims(w, h)

    kwargs: dict = {
        "model": config.image_model,
        "prompt": prompt,
        "size": size,
        "response_format": "b64_json",
    }

    # Add reference image as image_url for img2img models
    if edit_refs and _supports_openrouter_img2img(config.image_model):
        encoded = f"data:image/png;base64,{await asyncio.to_thread(_encode_image_sync, edit_refs[0])}"
        kwargs["image_url"] = encoded

    try:
        response = await client.images.generate(**kwargs)
        if not response.data or not response.data[0].b64_json:
            raise ValueError("Empty image response from OpenRouter")

        image_data = base64.b64decode(response.data[0].b64_json)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(output_path.write_bytes, image_data)
        log_call_end(
            image_logger,
            call_id=call_id,
            started=started,
            provider="openrouter",
            operation="generate",
            task="image",
            ok=True,
            result={"image_bytes": len(image_data)},
        )
        return output_path
    except Exception as e:
        log_call_end(
            image_logger,
            call_id=call_id,
            started=started,
            provider="openrouter",
            operation="generate",
            task="image",
            ok=False,
            error=e,
        )
        raise


# ── Public API ────────────────────────────────────────────────────────────────


def _generation_config(config: Config) -> Config:
    model = config.effective_image_model()
    if model.lower().startswith("imagen-"):
        raise ValueError(
            "Imagen image models are no longer supported. Use a Gemini image "
            "model such as gemini-3-pro-image-preview or a supported provider model path."
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
    """Generate a single image using the configured image provider.

    ref_type controls whether the reference image is treated as a subject
    (character identity) or style reference by the Gemini provider.
    """
    config = _generation_config(config)
    width, height = _effective_dimensions(config, width, height)
    steps = config.effective_image_steps(steps)
    is_style = ref_type == "style"
    refs = None if is_style else ([reference_image_path] if reference_image_path else None)
    srefs = [reference_image_path] if (is_style and reference_image_path) else None
    provider = config.image_provider
    if provider == "gemini":
        result = await _generate_gemini_image(config, prompt, output_path, refs, width, height, srefs)
        return await _downscale_dev_output(config, result, width, height)
    if provider == "openai":
        result = await _generate_openai_image(config, prompt, output_path, width, height, refs, srefs)
        return await _downscale_dev_output(config, result, width, height)
    if provider == "openrouter":
        result = await _generate_openrouter_image(config, prompt, output_path, width, height, refs, srefs)
        return await _downscale_dev_output(config, result, width, height)
    if provider != "together":
        raise ValueError(f"Unsupported image provider: {provider}")
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
                      Placed after subject refs for Gemini so character identity
                      has priority. Together currently uses subject refs only.
                      OpenAI uses subject+style refs through the image edit endpoint.
    """
    config = _generation_config(config)
    width, height = _effective_dimensions(config, width, height)
    steps = config.effective_image_steps(steps)
    provider = config.image_provider
    if provider == "gemini":
        result = await _generate_gemini_image(config, prompt, output_path, reference_paths, width, height, style_refs)
        return await _downscale_dev_output(config, result, width, height)
    if provider == "openai":
        result = await _generate_openai_image(
            config,
            prompt,
            output_path,
            width,
            height,
            reference_paths,
            style_refs,
        )
        return await _downscale_dev_output(config, result, width, height)
    if provider == "openrouter":
        result = await _generate_openrouter_image(
            config, prompt, output_path, width, height, reference_paths, style_refs
        )
        return await _downscale_dev_output(config, result, width, height)
    if provider != "together":
        raise ValueError(f"Unsupported image provider: {provider}")
    result = await _generate_together_image(config, prompt, output_path, width, height, steps, reference_paths)
    return await _downscale_dev_output(config, result, width, height)
