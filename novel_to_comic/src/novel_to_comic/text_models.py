"""Selectable gateway text models and the request shape each route accepts.

Every alias here needs a matching ``litellm/config.yaml`` route and a pricing
alias in ``litellm_pricing_overrides.yaml``. This table owns request differences
and default effort for routes supporting the shared operator control. The app
sends the job's configured effort; native-JSON Claude routes use output_config
because LiteLLM 1.101 drops reasoning_effort when output_config is present.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
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
    # Structured calls send the compiled schema as instructions (with JSON
    # mode only where verified, ``ai/gemini_schema.py``) instead of provider constrained decoding. Vertex
    # Gemini 3.8 Flash and Claude Haiku 5.5 reject full-size stage schemas before
    # generation ("compiled grammar is too large"); validators decide acceptance.
    schema_instructions: bool = False
    # OpenRouter and Together document ``max_tokens``; the gateway forwards the
    # newer OpenAI spelling to them unchanged.
    token_limit_field: Literal["max_completion_tokens", "max_tokens"] = "max_completion_tokens"
    # Unverified provider controls stay off; structured results can still use
    # prompt instructions and local validation.
    json_mode: bool = True
    streaming: bool = True
    # LiteLLM 1.101 treats Argon as an older Gemini and maps effort to a
    # token budget. This route sends the verified native level instead.
    native_vertex_thinking: bool = False
    vision: bool = True
    # Default effort for configurable routes; Claude uses ``output_config.effort``.
    # None means this route does not accept the shared effort control.
    effort: Literal["low", "medium", "high", "xhigh", "max"] | None = None
    # Models whose thinking cannot be disabled bill it against the same output
    # limit as the answer; callers size limits for the answer alone.
    thinking_headroom_tokens: int = 0
    # Billed thinking allowance for a large call, added to pre-call estimates so
    # holds cover output the caller never asked for. Smaller calls get a scaled
    # share (``usage.thinking_allowance``). The headroom above is a hard ceiling.
    estimated_thinking_tokens: int = 0
    max_output_tokens: int | None = None
    # Narrative-review window bounds. Every window re-sends the whole story as
    # reader context, so smaller windows multiply input; larger ones ask one
    # call to attend to more pages.
    review_window_pages: int = 12
    review_window_source_chars: int = 24_000
    # Another route to the same model shares that model's prompt tuning
    # (``gemini_tuning``) so a fallback sends what the primary would.
    tuning: str = ""
    # A route to the same model that takes a call Vertex rejects with 429
    # (``text_route_fallback``); it must share this model's tuning and controls.
    rate_limit_fallback: str = ""


TEXT_MODELS = (
    TextModel("gpt-6.1-sol", "GPT-6.1 Sol", "OpenAI", "openai", temperature=False, effort="medium"),
    TextModel("gpt-6-sol", "GPT-6 Sol", "OpenAI", "openai", temperature=False, effort="medium"),
    TextModel("gpt-6-luna", "GPT-6 Luna", "OpenAI", "openai", temperature=False, effort="medium"),
    # Low by default since 2026-10-13: Labs runs matched Medium's output at
    # lower cost, as the blinded Extract+Brief comparison found on 2026-10-03.
    TextModel("gemini-3.8-flash", "Gemini 3.8 Flash", "Google Vertex AI", "vertex_ai",
              temperature=False, effort="low", thinking_headroom_tokens=16_384,
              estimated_thinking_tokens=4_096, max_output_tokens=65_536,
              schema_instructions=True),
    # Vertex probes verified JSON mode and small native schemas (2026-10-13).
    # Full Extract native decoding rejects the same schema as Gemini 3.8.
    # Thinking allowances use the existing Vertex reservation policy, not model limits.
    # Labs run 20261013-143611-7df22e: Low matched Medium on Extract through
    # Plan at lower cost, and Argon's reviews found real defects on a whole
    # 32-page book, so one window replaces three repetitions of the story.
    # Gateway image input verified 2026-10-13 (one page render: panels and
    # lettering read exactly), so Argon can run lettering checks and visual review.
    TextModel("gemini-4-argon", "Gemini 4 Argon", "Google Vertex AI", "vertex_ai",
              temperature=False, streaming=False, effort="low",
              native_vertex_thinking=True, schema_instructions=True,
              thinking_headroom_tokens=16_384, estimated_thinking_tokens=4_096,
              review_window_pages=48, review_window_source_chars=120_000,
              rate_limit_fallback="runware-gemini-4-argon"),
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
    TextModel("claude-haiku-5-5", "Claude Haiku 5.5", "Anthropic", "anthropic",
              temperature=False, claude_native_json=True, effort="medium",
              thinking_headroom_tokens=16_384, estimated_thinking_tokens=4_096,
              max_output_tokens=128_000, schema_instructions=True),
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
    TextModel("bedrock-claude-haiku-5-5", "Claude Haiku 5.5 · Bedrock", "AWS Bedrock", "bedrock",
              temperature=False, claude_native_json=True, effort="medium",
              thinking_headroom_tokens=16_384, estimated_thinking_tokens=4_096,
              max_output_tokens=128_000, schema_instructions=True),
    # Runware routes (litellm_handlers/runware_text.py): a second quota when
    # Vertex rate-limits. Probed 2026-10-27: Argon honours reasoning_effort and
    # reads images; none of these stream through the handler.
    TextModel("runware-gemini-4-argon", "Gemini 4 Argon · Runware", "Runware", "runware",
              temperature=False, streaming=False, effort="low", schema_instructions=True,
              thinking_headroom_tokens=16_384, estimated_thinking_tokens=4_096,
              max_output_tokens=32_768, review_window_pages=48,
              review_window_source_chars=120_000, tuning="gemini-4-argon"),
    # JSON mode verified; native schema support unprobed, so schema instructions.
    TextModel("runware-deepseek-v4.1-flash-1017", "DeepSeek V4.1 Flash 1017 · Runware", "Runware", "runware",
              temperature=False, streaming=False, effort="low", schema_instructions=True,
              vision=False, thinking_headroom_tokens=16_384, estimated_thinking_tokens=4_096),
    # Rejected by Runware's API for this account as of 2026-10-27 (see
    # litellm/config.yaml); vision is unverified there.
    TextModel("runware-gpt-6.1-terra", "GPT-6.1 Terra · Runware", "Runware", "runware",
              temperature=False, streaming=False, effort="medium", vision=False,
              max_output_tokens=128_000),
    TextModel("mimo-v2.6-pro", "MiMo V2.6 Pro", "OpenRouter", "openrouter",
              token_limit_field="max_tokens"),
    TextModel("deepseek-v4.1-flash", "DeepSeek V4.1 Flash", "Together AI", "together_ai",
              token_limit_field="max_tokens"),
)
TEXT_MODEL_BY_ID = {model.id: model for model in TEXT_MODELS}
_SHARED_CONTROLS = ("vision", "schema_instructions", "json_mode", "effort", "review_window_pages",
                    "review_window_source_chars")
for _model in TEXT_MODELS:
    if _model.rate_limit_fallback:
        _fallback = TEXT_MODEL_BY_ID[_model.rate_limit_fallback]
        if _fallback.tuning != _model.id or _fallback.rate_limit_fallback or any(
            getattr(_fallback, name) != getattr(_model, name) for name in _SHARED_CONTROLS
        ):
            raise ValueError(f"{_fallback.id} cannot take {_model.id}'s rate-limited calls")
# Mock and test aliases outside the catalog get the plain OpenAI shape.
DEFAULT_TEXT_WIRE = TextModel("", "", "", "")


def text_wire(model: str) -> TextModel:
    return TEXT_MODEL_BY_ID.get(model, DEFAULT_TEXT_WIRE)


def tuning_model(model: str) -> str:
    """The model whose prompt tuning this route sends."""
    return text_wire(model).tuning or model


def is_gemini_model(model: str) -> bool:
    wire = text_wire(tuning_model(model))
    return wire.provider_key in {"vertex_ai", "gemini"} and wire.id.startswith("gemini-")


TEXT_REASONING_STAGES = ("extract", "brief", "prompt", "adapt", "plan", "ocr", "visual_review", "correction")
# Stage defaults that differ from the operator's shared effort. Gemini 3.8
# Flash at low matched medium on blinded Extract+Brief comparisons (2026-10-03)
# at a third of the time; saved per-stage choices still win.
DEFAULT_STAGE_EFFORTS = {"extract": "low", "brief": "low"}


def reasoning_options(model: str) -> tuple[str, ...]:
    wire = text_wire(model)
    if wire.provider_key in {"openrouter", "together_ai"}:
        return ("none", "enabled")
    return ("low", "medium", "high")


def default_reasoning(model: str, effort: str | None = None) -> str:
    """The shared effort when given, otherwise the route's own default."""
    effort = effort or text_wire(model).effort or "medium"
    return effort if effort in reasoning_options(model) else "none"


def reasoning_stage(feature: str) -> str | None:
    if feature.endswith("visual_review"):
        return "visual_review"
    if feature == "draw.page_ocr":
        return "ocr"
    if feature == "draw.correction_interpret":
        return "correction"
    owner = feature.split(".", 1)[0]
    if owner in {"style", "cast"}:
        return "prompt"
    if owner == "lettering":
        return "adapt"
    return owner if owner in TEXT_REASONING_STAGES else None


@dataclass(frozen=True)
class TextModelJob:
    """Explicit model and reasoning owner, independent of telemetry labels."""

    name: str
    model: str

    @classmethod
    def from_config(cls, config: Config, name: str) -> TextModelJob:
        getters = {
            "extract": config.effective_extraction_model,
            "brief": config.effective_brief_model,
            "prompt": config.effective_prompt_model,
            "adapt": config.effective_adapt_model,
            "plan": config.effective_plan_model,
            "ocr": config.effective_page_ocr_model,
            "visual_review": config.effective_visual_review_model,
            "correction": config.effective_correction_model,
        }
        return cls(name, getters[name]())

    @classmethod
    def for_feature(cls, feature: str, model: str) -> TextModelJob:
        """The job a stage-scoped feature label already names; never a guessed owner."""
        owner = reasoning_stage(feature)
        if owner is None:
            raise ValueError(f"Feature {feature!r} names no model job; pass an explicit TextModelJob")
        return cls(owner, model)

    @contextmanager
    def bind(self):
        token = _bound_text_job.set(self)
        try:
            yield self
        finally:
            _bound_text_job.reset(token)


_bound_text_job: ContextVar[TextModelJob | None] = ContextVar("text_model_job", default=None)


def request_reasoning(config: Config, model: str, feature: str) -> str:
    job = _bound_text_job.get()
    if job is not None and model not in {job.model, text_wire(job.model).rate_limit_fallback}:
        raise ValueError(f"Model job {job.name} is bound to {job.model}, not {model}")
    owner = job.name if job is not None else reasoning_stage(feature)
    effort = config.text_reasoning_efforts.get(owner, default_reasoning(model, config.text_reasoning_effort))
    if effort not in reasoning_options(model):
        raise ValueError(f"Unsupported reasoning setting for {model}: {effort}")
    return effort
