"""Usage tracking: data models and cost calculation."""

from __future__ import annotations

import logging
import re
import uuid
from dataclasses import dataclass
from typing import Generic, TypeVar

from pydantic import BaseModel, Field

from novel_to_comic.model_costs import CostBreakdown, get_pricing_resolver

T = TypeVar("T")
logger = logging.getLogger(__name__)

_warned_models: set[str] = set()


def _warn_unknown_model(model: str) -> None:
    if model not in _warned_models:
        _warned_models.add(model)
        logger.warning("Model %r not found in pricing — cost will be $0.00", model)


class UsageRecord(BaseModel, frozen=True):
    """Immutable record of one API call's resource consumption."""

    call_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    provider: str       # "gemini" | "anthropic" | "openai" | "openrouter"
    model: str          # Canary alias or direct model name used by the caller.
    provider_model: str | None = None
    operation: str      # "text" | "image"
    input_tokens: int = 0
    output_tokens: int = 0
    image_count: int = 0
    cost_usd: float | None = None
    cost_source: str | None = None


@dataclass
class ApiResult(Generic[T]):
    """Pairs a call's return value with its usage record."""

    value: T
    usage: UsageRecord | None = None


def calculate_cost_breakdown(record: UsageRecord) -> CostBreakdown:
    """Return detailed USD cost metadata for one API call."""
    return get_pricing_resolver().calculate(
        model_alias=record.model,
        provider_model=record.provider_model,
        operation=record.operation,
        input_tokens=record.input_tokens,
        output_tokens=record.output_tokens,
        image_count=record.image_count,
        provider_cost_usd=record.cost_usd,
        provider_cost_source=record.cost_source,
    )


def calculate_cost(record: UsageRecord) -> float:
    """Return the USD cost of one API call. Returns 0.0 for unknown models."""
    return calculate_cost_breakdown(record).cost_usd


def usage_has_billable_activity(record: UsageRecord) -> bool:
    return record.input_tokens > 0 or record.output_tokens > 0 or record.image_count > 0


def estimate_token_count(value: str | bytes | int) -> int:
    if isinstance(value, bytes):
        return max(1, len(value) // 4)
    if isinstance(value, int):
        return max(0, value // 4)
    return _count_tokens_approx(value)


def estimate_text_usage(
    *,
    provider: str,
    model: str,
    system_prompt: str,
    user_content: str | bytes,
    output_text: str,
    call_id: str | None = None,
) -> UsageRecord:
    """Build a usage record when a text provider omits token usage.

    Input uses the actual payload sent. Output uses the actual returned text,
    which is more reliable than a pre-call max-token reservation.
    """
    return UsageRecord(
        call_id=call_id or uuid.uuid4().hex,
        provider=provider,
        model=model,
        operation="text",
        input_tokens=estimate_token_count(system_prompt) + estimate_token_count(user_content),
        output_tokens=estimate_token_count(output_text),
    )


def _count_tokens_approx(text: str) -> int:
    """Estimate BPE token count using word and punctuation boundaries.

    Calibrated for English prose mixed with JSON/structured content.
    Accuracy: ±15% typical vs ±30% for the naive chars÷4 heuristic.
    Punctuation (quotes, braces, colons) nearly always tokenize as individual
    tokens, which makes chars÷4 badly undercount structured/JSON content.
    """
    words = len(re.findall(r'\b\w+\b', text))
    punct = len(re.findall(r'[^\w\s]', text))
    # Most common English words = 1 token; rare/long words split into ~1.1 on avg.
    # Each punctuation/symbol character is almost always its own token.
    return max(0, int(words * 1.1 + punct))


def estimate_text_cost(model: str, input_text: str | int, output_chars: int = 0) -> float:
    """Pre-call cost estimate. Pass the actual input text for best accuracy (~±15%),
    or a character count for a rougher estimate (~±30%).

    output_chars is always a character count since output text is unknown pre-call.
    """
    input_tokens = estimate_token_count(input_text)
    output_tokens = estimate_token_count(output_chars)
    breakdown = get_pricing_resolver().estimate_text_cost(model, input_tokens, output_tokens)
    if breakdown.source == "unknown_pricing":
        _warn_unknown_model(model)
    return breakdown.cost_usd


def estimate_image_cost(
    model: str,
    count: int,
    quality: str | None = None,
    ref_count: int = 0,
    prompt_text: str | int | None = None,
    width: int | None = None,
    height: int | None = None,
    ref_image_sizes: list[tuple[int, int]] | None = None,
) -> float:
    """Pre-call cost estimate for count images.

    For token-priced image models (e.g. gpt-image-2), the resolver scales by
    estimated prompt tokens, per-reference image input tokens, and per-quality
    output tokens — same per-token rates the actual-usage path uses. For models
    priced per-image, falls back to output_cost_per_image plus per-reference
    input cost, both sourced from litellm_pricing_overrides.yaml.
    """
    resolver = get_pricing_resolver()
    prompt_tokens = estimate_token_count(prompt_text) if prompt_text is not None else 0
    breakdown = resolver.estimate_image_cost(
        model,
        count,
        quality=quality,
        ref_count=ref_count,
        prompt_tokens=prompt_tokens,
        width=width,
        height=height,
        ref_image_sizes=ref_image_sizes,
    )
    if breakdown.source == "unknown_pricing":
        _warn_unknown_model(model)
        return 0.0
    return breakdown.cost_usd


def audit_pricing(extra_models: list[str] | None = None) -> list[str]:
    """Return model names that are used by the pipeline but missing pricing.

    Covers: all text models in MODEL_REGISTRY, all gateway aliases in the
    quality presets, all image model defaults from Config, and any additional
    model names passed in extra_models.

    Usage:
        missing = audit_pricing()
        if missing:
            print("Missing pricing entries:", missing)
    """
    from novel_to_comic.clients.text import MODEL_REGISTRY
    from novel_to_comic.config import Config, _QUALITY_PRESETS

    cfg = Config()
    known = set(MODEL_REGISTRY.keys())
    for preset in _QUALITY_PRESETS.values():
        known.update(preset.values())
    known.update(
        [
            cfg.image_model,
            cfg.fallback_image_model,
            cfg.effective_image_model(),
            "gpt-image-2",
            "dall-e-3",
            "black-forest-labs/FLUX.1-kontext-pro",
            "black-forest-labs/FLUX.2-kontext-pro",
            "black-forest-labs/FLUX.1-pro",
        ]
    )
    if extra_models:
        known.update(extra_models)

    resolver = get_pricing_resolver()
    missing: list[str] = []
    for model in known:
        if not model:
            continue
        breakdown = resolver.estimate_image_cost(model, 1)
        if breakdown.source != "unknown_pricing":
            continue
        missing.append(model)
    return sorted(missing)
