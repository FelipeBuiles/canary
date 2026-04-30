"""Cached LiteLLM model pricing and cost calculation helpers."""

from __future__ import annotations

import datetime
import hashlib
import json
import logging
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
    cost_usd: float
    source: str
    model_alias: str
    provider_model: str
    pricing_snapshot: str


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
        try:
            digest = hashlib.sha256(self.cost_map_path.read_bytes()).hexdigest()[:12]
        except Exception:
            digest = "unavailable"
        return f"{self.cost_map_path.name}:{digest}"

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

    def _pricing_for(self, model: str) -> tuple[dict[str, Any] | None, str]:
        for key in self._candidate_keys(model):
            spec = self._cost_map.get(key)
            if isinstance(spec, dict):
                return spec, "litellm_cost_map"
        overrides = self._overrides.get("model_overrides") or {}
        for key in self._candidate_keys(model):
            spec = overrides.get(key)
            if isinstance(spec, dict):
                return spec, "canary_pricing_override"
        return None, "unknown_pricing"

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
    ) -> CostBreakdown:
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

    def estimate_text_cost(self, model: str, input_tokens: int, output_tokens: int) -> CostBreakdown:
        return self.calculate(
            model_alias=model,
            operation="text",
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )

    def estimate_image_cost(self, model: str, count: int) -> CostBreakdown:
        return self.calculate(model_alias=model, operation="image", image_count=count)

    def estimate_ref_input_cost(self, model: str, ref_count: int) -> float:
        """Estimate input cost for reference images in image edit operations.

        Checks model_overrides first so entries can extend models already in the
        LiteLLM cost map (e.g. adding input_cost_per_image to a model that only
        has output_cost_per_image in the cached map).
        """
        if ref_count <= 0:
            return 0.0
        resolved = self.resolve_model(model)
        overrides = self._overrides.get("model_overrides") or {}
        spec: dict[str, Any] | None = None
        for key in self._candidate_keys(resolved):
            spec = overrides.get(key)
            if spec:
                break
        if not spec:
            for key in self._candidate_keys(resolved):
                spec = self._cost_map.get(key)
                if spec:
                    break
        if not spec:
            return 0.0
        cost_per_ref = float(spec.get("input_cost_per_image") or 0.0)
        return ref_count * cost_per_ref


_DEFAULT_RESOLVER: PricingResolver | None = None


def get_pricing_resolver() -> PricingResolver:
    global _DEFAULT_RESOLVER
    if _DEFAULT_RESOLVER is None:
        _DEFAULT_RESOLVER = PricingResolver()
    return _DEFAULT_RESOLVER


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
    return {
        "source_url": source_url,
        "output_path": str(output_path),
        "fetched_at": datetime.datetime.now(datetime.UTC).isoformat(),
        "sha256": hashlib.sha256(raw).hexdigest(),
    }
