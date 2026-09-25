"""Selectable gateway text models and the request shape each route accepts.

Every alias here needs a matching ``litellm/config.yaml`` route and a pricing
alias in ``litellm_pricing_overrides.yaml``. Provider-side controls such as
reasoning effort stay on the gateway route; this table owns only fields the
app itself must send differently per model. Claude effort is the exception:
LiteLLM 1.101 drops a route's ``reasoning_effort`` whenever the request carries
``output_config``, so native-JSON Claude routes send effort from here.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class TextModel:
    id: str
    label: str
    provider: str
    provider_key: str
    # Reasoning models and current Claude routes reject sampling temperature.
    temperature: bool = True
    # Claude routes use native ``output_config`` JSON; the pinned gateway turns
    # a Claude ``response_format`` into forced tool calls, which Fable rejects.
    claude_native_json: bool = False
    # OpenRouter and Together document ``max_tokens``; the gateway forwards the
    # newer OpenAI spelling to them unchanged.
    token_limit_field: Literal["max_completion_tokens", "max_tokens"] = "max_completion_tokens"
    vision: bool = True
    # Sent as ``output_config.effort`` on native-JSON Claude routes. None keeps
    # the provider default (Opus 5.5 defaults to ``medium``, one below Opus 5).
    effort: Literal["low", "medium", "high", "xhigh", "max"] | None = None
    # Models whose thinking cannot be disabled bill it against the same output
    # limit as the answer; callers size limits for the answer alone.
    thinking_headroom_tokens: int = 0
    # Typical billed thinking per call, added to pre-call estimates so holds
    # cover output the caller never asked for. The headroom above is a ceiling.
    estimated_thinking_tokens: int = 0
    max_output_tokens: int | None = None


TEXT_MODELS = (
    TextModel("gpt-6-sol", "GPT-6 Sol", "OpenAI", "openai", temperature=False),
    TextModel("gpt-6-luna", "GPT-6 Luna", "OpenAI", "openai", temperature=False),
    TextModel("claude-fable-5-1", "Claude Fable 5.1", "Anthropic", "anthropic",
              temperature=False, claude_native_json=True),
    # Thinking is always on (disabling it is a 400 at every effort). ``high``
    # keeps parity with the Opus 5 route it replaces.
    TextModel("claude-opus-5-5", "Claude Opus 5.5", "Anthropic", "anthropic",
              temperature=False, claude_native_json=True, effort="low",
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
