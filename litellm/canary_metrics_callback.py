"""LiteLLM callback metrics for provider calls and completed gateway work."""
from __future__ import annotations

from datetime import timedelta
from typing import Any

from litellm.integrations.custom_logger import CustomLogger

from canary_metrics import record


_MODELS = frozenset({
    "gpt-6.1-sol", "gpt-6-sol",
    "gpt-6-luna",
    "gemini-3.8-flash", "gemini-4-argon",
    "claude-opus-5-5",
    "claude-sonnet-5-5",
    "claude-haiku-5-5",
    "bedrock-claude-opus-5-5",
    "bedrock-claude-sonnet-5-5",
    "bedrock-claude-haiku-5-5",
    "mimo-v2.6-pro",
    "deepseek-v4.1-flash",
    "image-sunburst",
    "image-sunburst-openai",
    "image-flare",
    "image-nano-banana-2.1",
    "ocr-textract",
})
_PROVIDERS = frozenset({
    "openai",
    "anthropic",
    "bedrock",
    "bedrock_converse",
    "openrouter",
    "together_ai",
    "vertex_ai",
    "vertex-multimodal",
    "fal-queue",
    "openai-stream",
    "textract",
})


def _bounded(value: object, allowed: frozenset[str]) -> str:
    normalized = str(value or "")
    return normalized if normalized in allowed else "other"


def _operation(call_type: object) -> str:
    normalized = str(call_type or "").lower()
    if "image" in normalized:
        return "image"
    if "completion" in normalized or "response" in normalized:
        return "completion"
    return "other"


def _duration_ms(start_time: Any, end_time: Any) -> float:
    duration = end_time - start_time
    if isinstance(duration, timedelta):
        return duration.total_seconds() * 1000
    return float(duration) * 1000


def _attributes(kwargs: dict[str, Any], outcome: str) -> dict[str, str]:
    litellm_params = kwargs.get("litellm_params")
    if not isinstance(litellm_params, dict):
        litellm_params = {}
    return {
        "operation": _operation(kwargs.get("call_type")),
        "provider": _bounded(litellm_params.get("custom_llm_provider"), _PROVIDERS),
        "outcome": outcome,
    }


def _record_call(attributes: dict[str, str], start_time: Any, end_time: Any) -> None:
    record("count", "llm.provider.calls", attributes=attributes)
    try:
        duration = _duration_ms(start_time, end_time)
    except Exception:
        return
    record("histogram", "llm.provider.duration", duration, unit="ms", attributes=attributes)


class CanaryMetricsCallback(CustomLogger):
    async def async_log_success_event(
        self, kwargs: dict[str, Any], response_obj: Any, start_time: Any, end_time: Any
    ) -> None:
        attributes = _attributes(kwargs, "success")
        _record_call(attributes, start_time, end_time)
        record(
            "count",
            "gateway.completions",
            attributes={
                "operation": attributes["operation"],
                "model": _bounded(kwargs.get("model"), _MODELS),
            },
        )

    async def async_log_failure_event(
        self, kwargs: dict[str, Any], response_obj: Any, start_time: Any, end_time: Any
    ) -> None:
        _record_call(_attributes(kwargs, "failure"), start_time, end_time)


metrics_callback = CanaryMetricsCallback()
