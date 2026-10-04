"""Selectable gateway text models and the request shape each route accepts.

Every alias here needs a matching ``litellm/config.yaml`` route and a pricing
alias in ``litellm_pricing_overrides.yaml``. This table owns request differences
and default effort for routes supporting the shared operator control. The app
sends the job's configured effort; native-JSON Claude routes use output_config
because LiteLLM 1.101 drops reasoning_effort when output_config is present.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from novel_to_comic.config import Config


@dataclass(frozen=True)
class TextModel:
    id: str
    label: str
    provider: str
    provider_key: str
    # Reasoning models and current Claude routes reject sampling temperature.
    temperature: bool = True
    # Claude routes use native ``output_config`` JSON; the pinned gateway turns
    # a Claude ``response_format`` into forced tool calls, which these routes do not use.
    claude_native_json: bool = False
    # OpenRouter and Together document ``max_tokens``; the gateway forwards the
    # newer OpenAI spelling to them unchanged.
    token_limit_field: Literal["max_completion_tokens", "max_tokens"] = "max_completion_tokens"
    vision: bool = True
    # Default effort for configurable routes; Claude uses ``output_config.effort``.
    # None means this route does not accept the shared effort control.
    effort: Literal["low", "medium", "high", "xhigh", "max"] | None = None
    # Models whose thinking cannot be disabled bill it against the same output
    # limit as the answer; callers size limits for the answer alone.
    thinking_headroom_tokens: int = 0
    # Typical billed thinking per call, added to pre-call estimates so holds
    # cover output the caller never asked for. The headroom above is a ceiling.
    estimated_thinking_tokens: int = 0
    max_output_tokens: int | None = None


TEXT_MODELS = (
    TextModel("gpt-6.1-sol", "GPT-6.1 Sol", "OpenAI", "openai", temperature=False, effort="medium"),
    TextModel("gpt-6-sol", "GPT-6 Sol", "OpenAI", "openai", temperature=False, effort="medium"),
    TextModel("gpt-6-luna", "GPT-6 Luna", "OpenAI", "openai", temperature=False, effort="medium"),
    TextModel("gemini-3.8-flash", "Gemini 3.8 Flash", "Google Vertex AI", "vertex_ai",
              temperature=False, effort="medium", thinking_headroom_tokens=16_384,
              estimated_thinking_tokens=4_096, max_output_tokens=65_536),
    # Text routes default to medium effort; Claude defaults (``high`` on Sonnet,
    # ``medium`` on Opus 5.5) are never left implicit.
    # Thinking is always on (disabling it is a 400 at every effort).
    TextModel("claude-opus-5-5", "Claude Opus 5.5", "Anthropic", "anthropic",
              temperature=False, claude_native_json=True, effort="medium",
              thinking_headroom_tokens=16_384, estimated_thinking_tokens=4_096,
              max_output_tokens=128_000),
    # Adaptive thinking is on by default and bills against the same limit.
    TextModel("claude-sonnet-5-5", "Claude Sonnet 5.5", "Anthropic", "anthropic",
              temperature=False, claude_native_json=True, effort="medium",
              thinking_headroom_tokens=16_384, estimated_thinking_tokens=4_096,
              max_output_tokens=128_000),
    # Distinct aliases preserve the selected billing/provider route in job snapshots.
    # Converse maps the shared Claude output_config to Bedrock's native JSON format.
    TextModel("bedrock-claude-opus-5-5", "Claude Opus 5.5 · Bedrock", "AWS Bedrock", "bedrock",
              temperature=False, claude_native_json=True, effort="medium",
              thinking_headroom_tokens=16_384, estimated_thinking_tokens=4_096,
              max_output_tokens=128_000),
    TextModel("bedrock-claude-sonnet-5-5", "Claude Sonnet 5.5 · Bedrock", "AWS Bedrock", "bedrock",
              temperature=False, claude_native_json=True, effort="medium",
              thinking_headroom_tokens=16_384, estimated_thinking_tokens=4_096,
              max_output_tokens=128_000),
    TextModel("mimo-v2.6-pro", "MiMo V2.6 Pro", "OpenRouter", "openrouter",
              token_limit_field="max_tokens"),
    TextModel("deepseek-v4.1-flash", "DeepSeek V4.1 Flash", "Together AI", "together_ai",
              token_limit_field="max_tokens"),
)
TEXT_MODEL_BY_ID = {model.id: model for model in TEXT_MODELS}
# Mock and test aliases outside the catalog get the plain OpenAI shape.
DEFAULT_TEXT_WIRE = TextModel("", "", "", "")


def text_wire(model: str) -> TextModel:
    return TEXT_MODEL_BY_ID.get(model, DEFAULT_TEXT_WIRE)


def is_gemini_model(model: str) -> bool:
    wire = text_wire(model)
    return wire.provider_key in {"vertex_ai", "gemini"} and wire.id.startswith("gemini-")


TEXT_REASONING_STAGES = ("extract", "brief", "prompt", "adapt", "plan", "ocr", "visual_review")
# Stage defaults that differ from the operator's shared effort. Gemini 3.8
# Flash at low matched medium on blinded Extract+Brief comparisons (2026-10-03)
# at a third of the time; saved per-stage choices still win.
DEFAULT_STAGE_EFFORTS = {"extract": "low", "brief": "low"}


def reasoning_options(model: str) -> tuple[str, ...]:
    wire = text_wire(model)
    if wire.provider_key in {"openrouter", "together_ai"}:
        return ("none", "enabled")
    return ("low", "medium", "high")


def default_reasoning(model: str, effort: str = "medium") -> str:
    return effort if effort in reasoning_options(model) else "none"


def reasoning_stage(feature: str) -> str | None:
    if feature.endswith("visual_review"):
        return "visual_review"
    if feature == "draw.page_ocr":
        return "ocr"
    owner = feature.split(".", 1)[0]
    if owner in {"style", "cast"}:
        return "prompt"
    if owner == "lettering":
        return "adapt"
    return owner if owner in TEXT_REASONING_STAGES else None


def request_reasoning(config: Config, model: str, feature: str) -> str:
    effort = config.text_reasoning_efforts.get(reasoning_stage(feature), default_reasoning(model, config.text_reasoning_effort))
    if effort not in reasoning_options(model):
        raise ValueError(f"Unsupported reasoning setting for {model}: {effort}")
    return effort
