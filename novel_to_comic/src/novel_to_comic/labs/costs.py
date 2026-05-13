"""Cost helpers for Labs image-model experiments."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, UnidentifiedImageError

from novel_to_comic.model_costs import CostBreakdown, get_pricing_resolver
from novel_to_comic.usage import estimate_token_count

from .providers.base import LabsImageInput, LabsImageResult
from .registry import LabsModelEntry


def _image_size(path: Path) -> tuple[int, int] | None:
    try:
        with Image.open(path) as image:
            return image.size
    except (OSError, UnidentifiedImageError):
        return None


def _reference_sizes(inp: LabsImageInput) -> list[tuple[int, int]]:
    sizes: list[tuple[int, int]] = []
    for path in inp.reference_image_paths:
        size = _image_size(path)
        if size is not None:
            sizes.append(size)
    return sizes


def estimate_labs_image_cost(
    entry: LabsModelEntry,
    inp: LabsImageInput,
    *,
    provider_cost_usd: float | None = None,
    provider_cost_source: str | None = None,
    provider_model: str | None = None,
) -> CostBreakdown:
    """Return the best available cost for one successful Labs cell.

    Provider-reported cost wins when present. Otherwise use the same pricing
    resolver as the production pipeline, keyed by the provider endpoint rather
    than the Labs display id.
    """
    resolver = get_pricing_resolver()
    if provider_cost_usd is not None:
        return resolver.calculate(
            model_alias=entry.id,
            provider_model=provider_model or resolver.resolve_model(entry.endpoint),
            operation="image",
            image_count=1,
            provider_cost_usd=provider_cost_usd,
            provider_cost_source=provider_cost_source,
        )

    prompt = inp.composed_prompt()
    ref_sizes = _reference_sizes(inp)
    breakdown = resolver.estimate_image_cost(
        entry.endpoint,
        1,
        quality=str(entry.params.get("quality")) if entry.params.get("quality") else None,
        ref_count=len(inp.reference_image_paths),
        prompt_tokens=estimate_token_count(prompt),
        width=inp.width,
        height=inp.height,
        ref_image_sizes=ref_sizes or None,
    )
    if breakdown.source != "unknown_pricing" or entry.approx_cost is None:
        return breakdown

    return CostBreakdown(
        cost_usd=entry.approx_cost,
        source="labs_registry_approx_cost",
        model_alias=entry.id,
        provider_model=entry.endpoint,
        pricing_snapshot=resolver.pricing_snapshot,
    )


def settle_labs_result_cost(
    entry: LabsModelEntry,
    inp: LabsImageInput,
    result: LabsImageResult,
) -> CostBreakdown:
    return estimate_labs_image_cost(
        entry,
        inp,
        provider_cost_usd=result.cost_usd,
        provider_cost_source=result.cost_source,
        provider_model=result.provider_model,
    )
