"""LiteLLM custom provider for text models through Runware's chat endpoint.

Runware serves third-party text models on an OpenAI-compatible
``/v1/chat/completions``. Behaviour verified against the live API on 2026-10-27:

- Gemini routes are a passthrough to Google's OpenAI-compatible endpoint.
  ``reasoning_effort`` changes the thinking spend, but thinking tokens are
  absent from ``completion_tokens``: they only appear in ``total_tokens``.
  xAI routes report them in ``reasoning_tokens`` yet also leave them out of
  ``completion_tokens``. DeepSeek, GLM and MiniMax include them.
- Responses carry no cost, in the body or the headers.

Google bills thinking as output, so every token in ``total_tokens`` beyond
prompt and completion is settled as output here: LiteLLM prices completion
tokens, and the gap would otherwise be recorded as free.

The handler submits each request exactly once. Runware returns no task UUID
for chat calls, so a lost answer cannot be recovered and is reported as an
error for the caller to surface, never resent.
"""

from __future__ import annotations

import logging
import os
from typing import Any

import httpx
try:
    from litellm import ModelResponse
    from litellm.llms.custom_llm import CustomLLM, CustomLLMError
except ImportError:
    # Keep the pure helpers importable in the application test environment,
    # where the isolated LiteLLM proxy dependency is absent (the repository's
    # ``litellm/`` folder then imports as an empty namespace package).
    class CustomLLM:
        pass

    class CustomLLMError(Exception):
        def __init__(self, status_code: int, message: str):
            self.status_code = status_code
            self.message = message
            super().__init__(message)

    class ModelResponse(dict):
        def __init__(self, **kwargs: Any):
            super().__init__(**kwargs)


RUNWARE_CHAT_URL = "https://api.runware.ai/v1/chat/completions"
CONNECT_TIMEOUT_S = 10.0
# Argon Plan calls run for minutes without streaming.
READ_TIMEOUT_S = 900.0
# Request controls the application sends. LiteLLM rejects any other OpenAI
# control before this handler (drop_params off, deployment
# ``allowed_openai_params``); its own keys such as ``max_retries`` stay here.
_FORWARDED = frozenset({
    "response_format", "reasoning_effort", "max_tokens", "max_completion_tokens",
})

logger = logging.getLogger(__name__)


def request_body(model: str, messages: list[dict[str, Any]], optional_params: dict[str, Any]) -> dict[str, Any]:
    if optional_params.get("stream"):
        raise CustomLLMError(status_code=400, message="Runware text routes do not stream")
    body: dict[str, Any] = {"model": model, "messages": messages}
    body.update({key: value for key, value in optional_params.items() if key in _FORWARDED and value is not None})
    # LiteLLM copies the limit into both spellings; Runware takes either.
    if "max_completion_tokens" in body:
        body.pop("max_tokens", None)
    return body


def normalized_usage(usage: dict[str, Any] | None) -> dict[str, Any]:
    """Count tokens billed outside ``completion_tokens`` as reasoning output."""
    usage = dict(usage or {})
    prompt = int(usage.get("prompt_tokens") or 0)
    completion = int(usage.get("completion_tokens") or 0)
    total = int(usage.get("total_tokens") or prompt + completion)
    hidden = max(0, total - prompt - completion)
    details = dict(usage.get("completion_tokens_details") or {})
    if hidden:
        completion += hidden
        details["reasoning_tokens"] = max(int(details.get("reasoning_tokens") or 0), hidden)
    usage.update(prompt_tokens=prompt, completion_tokens=completion, total_tokens=prompt + completion)
    if details:
        usage["completion_tokens_details"] = details
    return usage


def response_payload(data: dict[str, Any]) -> dict[str, Any]:
    choices = []
    for choice in data.get("choices") or []:
        message = dict(choice.get("message") or {})
        # Google thought signatures only matter for multi-turn tool calls.
        message.pop("extra_content", None)
        choices.append({**choice, "message": message})
    if not choices:
        raise CustomLLMError(status_code=502, message="Runware text response had no choices")
    return {**data, "choices": choices, "usage": normalized_usage(data.get("usage"))}


def _error_message(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return response.text[:400]
    error = body.get("error") if isinstance(body, dict) else None
    if isinstance(error, dict):
        return str(error.get("message") or error.get("code") or "")[:400]
    return str(body)[:400]


def _prepare(model, messages, api_key, optional_params, timeout) -> tuple[dict[str, Any], dict[str, str], httpx.Timeout]:
    key = (api_key or os.environ.get("RUNWARE_API_KEY") or "").strip()
    if not key:
        raise CustomLLMError(status_code=500, message="RUNWARE_API_KEY is not set")
    read = float(timeout) if isinstance(timeout, (int, float)) and timeout > 0 else READ_TIMEOUT_S
    return (request_body(model, messages, optional_params), {"Authorization": f"Bearer {key}"},
            httpx.Timeout(read, connect=CONNECT_TIMEOUT_S))


def _transport_error(model: str, exc: httpx.HTTPError) -> CustomLLMError:
    if isinstance(exc, httpx.ConnectError):
        return CustomLLMError(status_code=503, message=f"Runware text connect failed for {model}: {type(exc).__name__}")
    # The request may have run and been charged; never resent here.
    return CustomLLMError(status_code=504, message=f"Runware text answer lost for {model}: {type(exc).__name__}")


def _model_response(model: str, response: httpx.Response) -> ModelResponse:
    if response.status_code >= 400:
        logger.warning("Runware text request failed model=%s status=%s", model, response.status_code)
        raise CustomLLMError(status_code=response.status_code,
                             message=f"Runware text {model}: {_error_message(response)}")
    try:
        data = response.json()
    except ValueError as exc:
        raise CustomLLMError(status_code=502, message=f"Runware text response for {model} was not JSON") from exc
    # Runware answers with its AIR id; LiteLLM prices the route's model name.
    return ModelResponse(**{**response_payload(data), "model": model})


class RunwareTextLLM(CustomLLM):
    def completion(self, model, messages, api_base, custom_prompt_dict, model_response,
                   print_verbose, encoding, api_key, logging_obj, optional_params,
                   acompletion=None, litellm_params=None, logger_fn=None, headers={},
                   timeout=None, client=None):
        body, auth, limits = _prepare(model, messages, api_key, optional_params, timeout)
        try:
            with httpx.Client(timeout=limits) as http:
                response = http.post(api_base or RUNWARE_CHAT_URL, json=body, headers=auth)
        except (httpx.ConnectError, httpx.TimeoutException) as exc:
            raise _transport_error(model, exc) from exc
        return _model_response(model, response)

    async def acompletion(self, model, messages, api_base, custom_prompt_dict, model_response,
                          print_verbose, encoding, api_key, logging_obj, optional_params,
                          acompletion=None, litellm_params=None, logger_fn=None, headers={},
                          timeout=None, client=None):
        body, auth, limits = _prepare(model, messages, api_key, optional_params, timeout)
        try:
            async with httpx.AsyncClient(timeout=limits) as http:
                response = await http.post(api_base or RUNWARE_CHAT_URL, json=body, headers=auth)
        except (httpx.ConnectError, httpx.TimeoutException) as exc:
            raise _transport_error(model, exc) from exc
        return _model_response(model, response)


runware_text_llm = RunwareTextLLM()
