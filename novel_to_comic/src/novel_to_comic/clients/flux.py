"""Image generation compatibility wrapper backed by the internal AI gateway."""

from __future__ import annotations

import asyncio
from pathlib import Path

from novel_to_comic.ai import generate_image as ai_generate_image
from novel_to_comic.ai.providers.base import RefImage
from novel_to_comic.config import Config
from novel_to_comic.models.prompt import PromptLayout
from novel_to_comic.usage import ApiResult


def _generation_config(config: Config) -> Config:
    model = config.effective_image_model()
    if model.lower().startswith("imagen-"):
        raise ValueError(
            "Imagen image models are no longer supported. Use a gateway image "
            "alias such as image-fast, image-balanced, or image-quality."
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
    feature: str = "image.generate",
) -> ApiResult[Path]:
    """Generate a single image through the AI gateway.

    ref_type controls whether the reference image is treated as a subject or
    style reference.
    """
    config = _generation_config(config)
    width, height = _effective_dimensions(config, width, height)
    steps = config.effective_image_steps(steps)
    refs: list[RefImage] = []
    if reference_image_path:
        refs.append(RefImage(path=reference_image_path, role="style" if ref_type == "style" else "subject"))
    result = await ai_generate_image(
        config=config,
        model=config.effective_image_model(),
        prompt=prompt,
        output_path=output_path,
        width=width,
        height=height,
        steps=steps,
        refs=refs,
        feature=feature,
    )
    final = await _downscale_dev_output(config, result.value, width, height)
    return ApiResult(value=final, usage=result.usage)


async def generate_image_multi_ref(
    config: Config,
    prompt: str,
    output_path: Path,
    refs: list[RefImage],
    width: int | None = None,
    height: int | None = None,
    steps: int | None = None,
    layout: PromptLayout | None = None,
    feature: str = "image.generate_multi_ref",
) -> ApiResult[Path]:
    """Generate an image conditioned on subject and style references."""
    config = _generation_config(config)
    width, height = _effective_dimensions(config, width, height)
    steps = config.effective_image_steps(steps)
    result = await ai_generate_image(
        config=config,
        model=config.effective_image_model(),
        prompt=prompt,
        output_path=output_path,
        width=width,
        height=height,
        steps=steps,
        refs=refs,
        layout=layout,
        feature=feature,
    )
    final = await _downscale_dev_output(config, result.value, width, height)
    return ApiResult(value=final, usage=result.usage)
