"""Pure text request shaping, shared by submission and request identity consumers."""
from __future__ import annotations

import base64
import re
from dataclasses import dataclass
from typing import Any

from novel_to_comic.ai.anthropic_schema import anthropic_output_schema
from novel_to_comic.ai.codex_schema import strict_output_schema
from novel_to_comic.ai.prompt_parts import plain_prompt, prompt_parts
from novel_to_comic.codex_dev import CodexRoute, CodexRoutingError, route_for
from novel_to_comic.config import Config, mock_mode_active
from novel_to_comic.gemini_tuning import tuned_request
from novel_to_comic.text_models import is_gemini_model, request_reasoning, text_wire


@dataclass(frozen=True)
class TextRequest:
    payload: dict[str, Any]
    effective_request: dict[str, Any]
    system_prompt: str
    user_content: str
    json_schema: dict[str, Any] | None
    route: CodexRoute | None
    effort: str
    streaming: bool
    open_thinking: bool


def build_text_request(
    *, config: Config, model: str, system_prompt: str, user_content: str,
    temperature: float, max_output_tokens: int | None, json_mode: bool,
    feature: str, metadata: dict[str, Any],
    json_schema: dict[str, Any] | None = None,
    image_attachments: tuple[tuple[bytes, str], ...] = (),
    streaming_enabled: bool = True,
) -> TextRequest:
    effective_request = tuned_request(model, {
        "system_prompt": system_prompt, "user_content": user_content,
        "feature": feature, "json_schema": json_schema, "json_mode": json_mode,
    })
    system_prompt = effective_request["system_prompt"]
    # Cache-break markers never reach a model: Gemini receives the pieces as
    # separate parts (ai/prompt_parts.py); everything else sees plain text.
    user_parts = prompt_parts(effective_request["user_content"])
    user_content = plain_prompt(effective_request["user_content"])
    json_schema = effective_request["json_schema"]
    json_mode = effective_request["json_mode"]
    route = route_for("text", model)
    if config.mock_mode and (route is not None or not mock_mode_active(config)):
        raise CodexRoutingError("Mock projects cannot execute live Codex requests")
    if route is not None:
        metadata.update({
            "funding": route.funding,
            "subscription_runtime": route.runtime,
            "codex_reasoning_model": route.reasoning_model,
            "unsupported_controls": {
                "temperature": temperature,
                "max_output_tokens": max_output_tokens,
            },
        })
    wire = text_wire(model)
    if image_attachments and not wire.vision:
        raise ValueError(f"Vision is not enabled for {model}")
    effort = request_reasoning(config, model, feature)
    open_thinking = wire.provider_key in {"openrouter", "together_ai"} and effort != "none"
    response_format: dict[str, Any] | None
    effective_system = system_prompt
    if json_schema:
        request_schema = json_schema
        if route is None and not wire.claude_native_json and not is_gemini_model(model):
            request_schema = strict_output_schema(json_schema)
        schema_name = re.sub(r"[^a-zA-Z0-9_-]", "_", feature)[:64]
        response_format = {
            "type": "json_schema",
            "json_schema": {
                "name": schema_name,
                "strict": True,
                "schema": request_schema,
            },
        }
    elif json_mode:
        response_format = {"type": "json_object"}
    else:
        response_format = None
    if json_mode and "json" not in (system_prompt + user_content).lower():
        effective_system += "\n\nRespond with valid JSON."
    # An image-reading call keeps ``user_content`` as its text part so cost
    # estimation, request summaries, and Langfuse logging stay comparable with
    # text-only calls; only the wire message becomes multimodal.
    message_content: str | list[dict[str, Any]] = user_content
    if route is None and not image_attachments and len(user_parts) > 1 and is_gemini_model(model):
        message_content = [{"type": "text", "text": part} for part in user_parts]
    if image_attachments and route is None:
        message_content = [{"type": "text", "text": user_content}]
        for image_bytes, media_type in image_attachments:
            encoded = base64.b64encode(image_bytes).decode()
            message_content.append(
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{media_type};base64,{encoded}"},
                }
            )
    payload: dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": effective_system},
            {"role": "user", "content": message_content},
        ],
        "metadata": metadata,
    }
    if route is None and wire.native_vertex_thinking:
        payload["thinkingConfig"] = {"thinkingLevel": effort, "includeThoughts": True}
    elif route is None and wire.effort and not wire.claude_native_json:
        payload["reasoning_effort"] = effort
    if route is None and wire.provider_key in {"openrouter", "together_ai"}:
        payload["extra_body"] = {"reasoning": {"enabled": effort != "none"}}
        if wire.provider_key == "openrouter":
            payload["extra_body"]["provider"] = {"require_parameters": True}
    if route is None and wire.temperature:
        payload["temperature"] = temperature
    if route is None and wire.claude_native_json:
        output_config: dict[str, Any] = {}
        # The gateway drops a route's reasoning_effort once output_config is
        # present, so effort travels with the format it would otherwise lose to.
        if wire.effort:
            output_config["effort"] = effort
        # Schema-less JSON uses the instruction and parser above.
        if json_schema:
            output_config["format"] = {
                "type": "json_schema", "schema": anthropic_output_schema(json_schema),
            }
        if output_config:
            payload["output_config"] = output_config
    elif response_format is not None and wire.json_mode:
        payload["response_format"] = response_format
    effective_max_output_tokens = (max_output_tokens or 16_384) + (16_384 if open_thinking else wire.thinking_headroom_tokens)
    if wire.max_output_tokens:
        effective_max_output_tokens = min(effective_max_output_tokens, wire.max_output_tokens)
    if route is None:
        payload[wire.token_limit_field] = effective_max_output_tokens
    # Stream so the read timeout is per-chunk: long adapt repairs exceed the
    # read budget as a single blocking response. include_usage puts the usage
    # block on a final chunk, which streaming otherwise omits.
    streaming = route is None and wire.streaming and streaming_enabled
    if streaming:
        payload["stream"] = True
        payload["stream_options"] = {"include_usage": True}
    return TextRequest(
        payload, effective_request, effective_system, user_content, json_schema,
        route, effort, streaming, open_thinking,
    )
