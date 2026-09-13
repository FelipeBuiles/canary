"""Cached LiteLLM model pricing and cost calculation helpers."""

from __future__ import annotations

import datetime
import hashlib
import json
import logging
import math
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

PACKAGE_DIR = Path(__file__).parent
LITELLM_COST_MAP_URL = "https://raw.githubusercontent.com/BerriAI/litellm/main/model_prices_and_context_window.json"
DEFAULT_COST_MAP_PATH = PACKAGE_DIR / "litellm_model_prices.cached.json"
DEFAULT_OVERRIDES_PATH = PACKAGE_DIR / "litellm_pricing_overrides.yaml"


@dataclass(frozen=True)
class CostBreakdown:
    cost_usd: float | None
    source: str
    model_alias: str
    provider_model: str
    pricing_snapshot: str
    funding: str = "api"


class PricingResolver:
    """Resolve Canary aliases against a cached LiteLLM cost map."""

    def __init__(
        self,
        *,
        cost_map_path: Path = DEFAULT_COST_MAP_PATH,
        overrides_path: Path = DEFAULT_OVERRIDES_PATH,
    ) -> None:
        self.cost_map_path = cost_map_path
        self.overrides_path = overrides_path
        self._cost_map = self._load_json(cost_map_path)
        self._overrides = self._load_yaml(overrides_path)
        self._pricing_snapshot = self._snapshot_id()

    @staticmethod
    def _load_json(path: Path) -> dict[str, Any]:
        try:
            return json.loads(path.read_text())
        except Exception as exc:
            logger.warning("Could not load LiteLLM cost map %s: %s", path, exc)
            return {}

    @staticmethod
    def _load_yaml(path: Path) -> dict[str, Any]:
        try:
            return yaml.safe_load(path.read_text()) or {}
        except Exception as exc:
            logger.warning("Could not load pricing overrides %s: %s", path, exc)
            return {}

    def _snapshot_id(self) -> str:
        h = hashlib.sha256()
        for path in (self.cost_map_path, self.overrides_path):
            try:
                h.update(path.name.encode("utf-8"))
                h.update(b"\0")
                h.update(path.read_bytes())
            except Exception:
                h.update(path.name.encode("utf-8"))
                h.update(b":<unavailable>")
        return f"{self.cost_map_path.name}+overrides:{h.hexdigest()[:12]}"

    @property
    def pricing_snapshot(self) -> str:
        return self._pricing_snapshot

    def resolve_model(self, model_alias: str, provider_model: str | None = None) -> str:
        if provider_model and provider_model != model_alias:
            return provider_model
        aliases = self._overrides.get("aliases") or {}
        return str(aliases.get(model_alias) or provider_model or model_alias)

    def _candidate_keys(self, model: str) -> list[str]:
        keys = [model]
        if "/" in model:
            keys.append(model.split("/", 1)[1])
        return list(dict.fromkeys(keys))

    def _cache_pricing_for(self, model: str) -> dict[str, Any] | None:
        for key in self._candidate_keys(model):
            spec = self._cost_map.get(key)
            if isinstance(spec, dict):
                return spec
        return None

    def _override_pricing_for(self, model: str) -> dict[str, Any] | None:
        overrides = self._overrides.get("model_overrides") or {}
        for key in self._candidate_keys(model):
            spec = overrides.get(key)
            if isinstance(spec, dict):
                return spec
        return None

    def _pricing_for(self, model: str) -> tuple[dict[str, Any] | None, str]:
        cache_spec = self._cache_pricing_for(model)
        override_spec = self._override_pricing_for(model)
        if cache_spec is not None and override_spec is not None:
            return {
                **cache_spec,
                **override_spec,
            }, "litellm_cost_map+canary_pricing_override"
        if cache_spec is not None:
            return cache_spec, "litellm_cost_map"
        if override_spec is not None:
            return override_spec, "canary_pricing_override"
        return None, "unknown_pricing"

    def model_output_token_limit(
        self,
        model_alias: str,
        *,
        provider_model: str | None = None,
        fallback: int = 65_536,
    ) -> int:
        """Return the configured provider's output ceiling for planning calls."""

        resolved_model = self.resolve_model(model_alias, provider_model)
        pricing, _ = self._pricing_for(resolved_model)
        if pricing is not None:
            for field in ("max_output_tokens", "max_tokens"):
                value = pricing.get(field)
                if isinstance(value, (int, float)) and value > 0:
                    return int(value)
        return fallback

    def calculate(
        self,
        *,
        model_alias: str,
        operation: str,
        input_tokens: int = 0,
        output_tokens: int = 0,
        image_count: int = 0,
        provider_model: str | None = None,
        provider_cost_usd: float | None = None,
        provider_cost_source: str | None = None,
        funding: str = "api",
    ) -> CostBreakdown:
        if funding == "codex_subscription":
            # Monetary liability, not an observation of provider spend or quota.
            # Do not resolve an API alias/tariff for subscription execution.
            return CostBreakdown(
                cost_usd=0.0,
                source="codex_subscription",
                model_alias=model_alias,
                provider_model=provider_model or model_alias,
                pricing_snapshot="codex_subscription",
                funding=funding,
            )
        if funding != "api":
            raise ValueError(f"Unknown usage funding: {funding}")
        resolved_model = self.resolve_model(model_alias, provider_model)
        if provider_cost_usd is not None:
            return CostBreakdown(
                cost_usd=provider_cost_usd,
                source=provider_cost_source or "provider_reported_cost",
                model_alias=model_alias,
                provider_model=resolved_model,
                pricing_snapshot=self.pricing_snapshot,
            )

        pricing, source = self._pricing_for(resolved_model)
        if pricing is None:
            return CostBreakdown(
                cost_usd=0.0,
                source=source,
                model_alias=model_alias,
                provider_model=resolved_model,
                pricing_snapshot=self.pricing_snapshot,
            )

        input_cost = float(pricing.get("input_cost_per_token") or 0.0)
        output_cost = float(pricing.get("output_cost_per_token") or 0.0)
        image_cost = float(
            pricing.get("output_cost_per_image")
            or pricing.get("input_cost_per_image")
            or pricing.get("per_image_usd")
            or 0.0
        )
        has_token_usage = input_tokens > 0 or output_tokens > 0
        has_token_pricing = input_cost > 0 or output_cost > 0

        if operation == "image" and (not has_token_usage or not has_token_pricing):
            cost_usd = image_count * image_cost
        else:
            cost_usd = input_tokens * input_cost + output_tokens * output_cost

        return CostBreakdown(
            cost_usd=cost_usd,
            source=source,
            model_alias=model_alias,
            provider_model=resolved_model,
            pricing_snapshot=self.pricing_snapshot,
        )

    def estimate_text_cost(
        self, model: str, input_tokens: int, output_tokens: int
    ) -> CostBreakdown:
        return self.calculate(
            model_alias=model,
            operation="text",
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )

    def estimate_image_cost(
        self,
        model: str,
        count: int,
        *,
        quality: str | None = None,
        ref_count: int = 0,
        prompt_tokens: int = 0,
        width: int | None = None,
        height: int | None = None,
        ref_image_sizes: list[tuple[int, int]] | None = None,
    ) -> CostBreakdown:
        """Project the USD cost of `count` image requests.

        For models priced per-token (e.g. gpt-image-2), translates the request
        into estimated input/output tokens and uses the same per-token math the
        `calculate()` path uses for actual usage. For models priced per-image,
        falls back to `output_cost_per_image` and adds per-reference input cost
        from the override yaml.
        """
        resolved = self.resolve_model(model)
        pricing, source = self._pricing_for(resolved)
        if pricing is None:
            return CostBreakdown(
                cost_usd=0.0,
                source=source,
                model_alias=model,
                provider_model=resolved,
                pricing_snapshot=self.pricing_snapshot,
            )

        input_per_token = float(pricing.get("input_cost_per_token") or 0.0)
        output_per_token = float(pricing.get("output_cost_per_token") or 0.0)

        # Measured consumption applies only to the observed quality/geometry.
        # Unknown settings retain the conservative allowance below; these
        # estimates never participate in actual-usage settlement.
        measured = pricing.get("estimated_image_tokens_by_quality_and_size") or {}
        output_estimate = (measured.get((quality or "auto").lower()) or {}).get(
            f"{width}x{height}"
        )
        if output_estimate is not None:
            return CostBreakdown(
                cost_usd=(
                    count * float(output_estimate) * output_per_token
                    + ref_count * float(pricing.get("estimated_input_tokens_per_reference") or 0)
                    * float(pricing.get("image_input_cost_per_token") or input_per_token)
                    + prompt_tokens * input_per_token
                ),
                source="measured_consumption_estimate",
                model_alias=model,
                provider_model=resolved,
                pricing_snapshot=self.pricing_snapshot,
            )

        # An allowance is only an estimate, never a per-image settlement tariff.
        # New image models need usage measurements before a token-consumption
        # table is justified. Keep their reservation metadata out of calculate().
        allowance = pricing.get("estimated_output_cost_per_image")
        if allowance is not None:
            return CostBreakdown(
                cost_usd=(
                    count * float(allowance)
                    + ref_count * float(pricing.get("estimated_input_cost_per_reference") or 0.0)
                    + prompt_tokens * input_per_token
                ),
                source="configured_reservation_allowance",
                model_alias=model,
                provider_model=resolved,
                pricing_snapshot=self.pricing_snapshot,
            )

        token_meta = self._image_token_meta(resolved)
        quality_table = token_meta.get("image_output_tokens_by_quality") or {}

        if (input_per_token > 0 or output_per_token > 0) and quality_table:
            image_input_per_token = float(
                pricing.get("image_input_cost_per_token") or input_per_token
            )
            ref_tokens = int(token_meta.get("image_input_tokens_per_ref") or 0)
            quality_key = (quality or "auto").lower()
            output_tokens_per_image = int(
                quality_table.get(quality_key)
                or quality_table.get("auto")
                or quality_table.get("medium")
                or 0
            )
            ref_input_tokens = ref_tokens * ref_count
            output_tokens = output_tokens_per_image * count
            cost_usd = (
                prompt_tokens * input_per_token
                + ref_input_tokens * image_input_per_token
                + output_tokens * output_per_token
            )
            return CostBreakdown(
                cost_usd=cost_usd,
                source=source,
                model_alias=model,
                provider_model=resolved,
                pricing_snapshot=self.pricing_snapshot,
            )

        per_megapixel = self._estimate_megapixel_image_cost(
            pricing,
            count=count,
            width=width,
            height=height,
            ref_count=ref_count,
            ref_image_sizes=ref_image_sizes,
        )
        if per_megapixel is not None:
            return CostBreakdown(
                cost_usd=per_megapixel,
                source=source,
                model_alias=model,
                provider_model=resolved,
                pricing_snapshot=self.pricing_snapshot,
            )

        per_image = float(
            pricing.get("output_cost_per_image")
            or pricing.get("input_cost_per_image")
            or pricing.get("per_image_usd")
            or 0.0
        )
        ref_image_cost = float(pricing.get("input_cost_per_image") or 0.0)
        if ref_image_cost <= 0 and ref_count > 0:
            # Cached cost map often only carries `output_cost_per_image`; the
            # override yaml is where per-reference pricing lives.
            overrides = self._overrides.get("model_overrides") or {}
            for key in self._candidate_keys(resolved):
                spec = overrides.get(key)
                if isinstance(spec, dict) and spec.get("input_cost_per_image"):
                    ref_image_cost = float(spec["input_cost_per_image"])
                    break
        cost_usd = count * per_image + ref_image_cost * ref_count
        return CostBreakdown(
            cost_usd=cost_usd,
            source=source,
            model_alias=model,
            provider_model=resolved,
            pricing_snapshot=self.pricing_snapshot,
        )

    @staticmethod
    def _rounded_megapixels(width: int | None, height: int | None) -> int:
        if not width or not height or width <= 0 or height <= 0:
            return 1
        return max(1, math.ceil((width * height) / float(1024 * 1024)))

    def _estimate_megapixel_image_cost(
        self,
        pricing: dict[str, Any],
        *,
        count: int,
        width: int | None,
        height: int | None,
        ref_count: int,
        ref_image_sizes: list[tuple[int, int]] | None,
    ) -> float | None:
        output_first_mp = pricing.get("output_cost_first_megapixel")
        output_extra_mp = pricing.get("output_cost_per_extra_megapixel")
        output_per_mp = pricing.get("output_cost_per_megapixel")
        input_per_mp = pricing.get("input_cost_per_megapixel")

        if output_first_mp is None and output_per_mp is None and input_per_mp is None:
            return None

        output_mps = self._rounded_megapixels(width, height)
        total = 0.0
        if output_first_mp is not None:
            first = float(output_first_mp)
            extra = float(
                output_extra_mp
                if output_extra_mp is not None
                else output_per_mp or first
            )
            output_cost = first + max(0, output_mps - 1) * extra
        elif output_per_mp is not None:
            output_cost = output_mps * float(output_per_mp)
        else:
            output_cost = 0.0
        total += count * output_cost

        if input_per_mp is not None:
            if ref_image_sizes:
                input_mps = sum(
                    self._rounded_megapixels(w, h) for w, h in ref_image_sizes
                )
            else:
                input_mps = ref_count
            total += input_mps * float(input_per_mp)

        return total

    def _image_token_meta(self, model: str) -> dict[str, Any]:
        """Return image_input_tokens_per_ref / image_output_tokens_by_quality if set."""
        overrides = self._overrides.get("model_overrides") or {}
        for key in self._candidate_keys(model):
            spec = overrides.get(key)
            if not isinstance(spec, dict):
                continue
            if (
                "image_input_tokens_per_ref" in spec
                or "image_output_tokens_by_quality" in spec
            ):
                return spec
        return {}


_DEFAULT_RESOLVER: PricingResolver | None = None


def get_pricing_resolver() -> PricingResolver:
    global _DEFAULT_RESOLVER
    if _DEFAULT_RESOLVER is None:
        _DEFAULT_RESOLVER = PricingResolver()
    return _DEFAULT_RESOLVER


def reset_pricing_resolver() -> None:
    """Force the next pricing lookup to reload the cache and override files."""
    global _DEFAULT_RESOLVER
    _DEFAULT_RESOLVER = None


def refresh_litellm_cost_cache(
    *,
    output_path: Path = DEFAULT_COST_MAP_PATH,
    source_url: str = LITELLM_COST_MAP_URL,
    timeout_seconds: int = 20,
) -> dict[str, str]:
    """Fetch LiteLLM's public cost map into the local cache file.

    This is intentionally explicit rather than part of request-time billing; user
    charges should never depend on a live network fetch.
    """

    with urllib.request.urlopen(source_url, timeout=timeout_seconds) as response:
        raw = response.read()
    json.loads(raw.decode("utf-8"))
    output_path.write_bytes(raw)
    if output_path == DEFAULT_COST_MAP_PATH:
        reset_pricing_resolver()
    return {
        "source_url": source_url,
        "output_path": str(output_path),
        "fetched_at": datetime.datetime.now(datetime.UTC).isoformat(),
        "sha256": hashlib.sha256(raw).hexdigest(),
    }
