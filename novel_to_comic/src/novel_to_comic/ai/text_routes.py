"""Transport adapters returning text and usage evidence without fake chat completions."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
import httpx

from novel_to_comic.ai.admission import post as admitted_post
from novel_to_comic.ai.text_requests import TextRequest
from novel_to_comic.config import Config
from novel_to_comic.text_models import text_wire


@dataclass
class TextRouteResult:
    text: str | None = None
    finish_reason: str | None = None
    data: dict[str, Any] = field(default_factory=dict)
    runtime_metadata: dict[str, Any] = field(default_factory=dict)
    response: httpx.Response | None = None
    submission_started: bool = False


async def execute_text_route(
    request: TextRequest, *, config: Config, event_id: str,
    image_attachments: tuple[tuple[bytes, str], ...], max_output_tokens: int | None,
    retry_transport: bool, paid_call: bool, state: TextRouteResult,
) -> TextRouteResult:
    from novel_to_comic.ai import client

    route, streaming, payload = request.route, request.streaming, request.payload
    effective_system, user_content = request.system_prompt, request.user_content
    json_schema, effort = request.json_schema, request.effort
    endpoint = "/v1/chat/completions"
    response = None
    data = {}
    if route is not None and route.runtime == "claude":
        from novel_to_comic.ai.claude_runtime import run_text as run_claude_text

        # The API route's model controls, so the two runs are comparable.
        claude_wire = text_wire(route.reasoning_model)
        claude_limit = (max_output_tokens or 16_384) + claude_wire.thinking_headroom_tokens
        if claude_wire.max_output_tokens:
            claude_limit = min(claude_limit, claude_wire.max_output_tokens)
        claude_result = await run_claude_text(
            model=route.reasoning_model,
            system_prompt=effective_system,
            user_content=user_content,
            json_schema=json_schema,
            image_attachments=image_attachments,
            effort=effort,
            max_output_tokens=claude_limit,
        )
        state.runtime_metadata = claude_result.metadata
        state.text = claude_result.text
        data = {
            "model": claude_result.model,
            "usage": client._claude_token_usage({
                "input_tokens": claude_result.input_tokens,
                "output_tokens": claude_result.output_tokens,
                "cache_read_input_tokens": claude_result.cache_read_input_tokens,
                "cache_creation_input_tokens": claude_result.cache_creation_input_tokens,
            }),
        }
    elif route is not None:
        from novel_to_comic.ai.codex_runtime import run_text

        result = await run_text(
            model=route.reasoning_model,
            system_prompt=effective_system,
            user_content=user_content,
            json_schema=json_schema,
            image_attachments=image_attachments,
            effort=effort,
        )
        state.runtime_metadata = result.metadata
        state.text = result.text
        data = {
            "model": result.model,
            "usage": {"prompt_tokens": result.input_tokens, "completion_tokens": result.output_tokens},
        }
    elif streaming:
        state.submission_started = True
        if retry_transport:
            data, response = await client._stream_with_retry(
                f"{client._base_url(config)}{endpoint}",
                headers=client._headers(config, event_id),
                payload=payload,
                **({"retry_ambiguous": False} if paid_call else {}),
            )
        else:
            data, response = await client._read_chat_stream(
                f"{client._base_url(config)}{endpoint}",
                headers=client._headers(config, event_id),
                payload=payload,
            )
    else:
        state.submission_started = True
        if retry_transport:
            response = await client._post_with_retry(
                f"{client._base_url(config)}{endpoint}",
                headers=client._headers(config, event_id),
                json=payload,
                **({"retry_ambiguous": False} if paid_call else {}),
            )
        else:
            response = await admitted_post(
                client._http, f"{client._base_url(config)}{endpoint}",
                headers=client._headers(config, event_id),
                json=payload,
            )
        data = {}

    state.data, state.response = data, response
    if route is not None:
        state.finish_reason = "stop"
    elif response is not None and response.status_code < 400:
        if not streaming:
            state.data = response.json()
        choice = (state.data.get("choices") or [{}])[0]
        state.text = (choice.get("message") or {}).get("content")
        state.finish_reason = choice.get("finish_reason")
    return state
