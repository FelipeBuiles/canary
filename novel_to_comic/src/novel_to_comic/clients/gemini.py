"""Google Gemini API wrapper with async support and retry logic."""

import json
import logging
import os

from google import genai
from google.genai import types
from tenacity import retry, stop_after_attempt, wait_exponential

from novel_to_comic.clients.api_logging import log_call_end, log_call_start, payload_summary
from novel_to_comic.config import Config
from novel_to_comic.usage import ApiResult, UsageRecord

logger = logging.getLogger("canary.google")

_client_cache: dict[str, genai.Client] = {}


def _vertex_project(config: Config) -> str:
    project = config.google_cloud_project or os.environ.get("GOOGLE_CLOUD_PROJECT", "")
    if not project.strip():
        raise ValueError(
            "Vertex AI is enabled but no Google Cloud project is configured. "
            "Set google_cloud_project in config.yaml or GOOGLE_CLOUD_PROJECT in your .env/shell."
        )
    return project.strip()


def describe_provider(config: Config) -> str:
    if config.google_use_vertex_ai:
        return (
            f"vertex project={_vertex_project(config)} "
            f"location={config.google_cloud_location or os.environ.get('GOOGLE_CLOUD_LOCATION') or 'global'}"
        )
    return "developer_api auth=api_key"


def get_client(config: Config) -> genai.Client:
    cache_key = f"{config.google_use_vertex_ai}:{config.google_cloud_project}:{config.google_cloud_location}"
    if cache_key in _client_cache:
        return _client_cache[cache_key]
    if config.google_use_vertex_ai:
        client = genai.Client(
            vertexai=True,
            project=_vertex_project(config),
            location=(
                config.google_cloud_location
                or os.environ.get("GOOGLE_CLOUD_LOCATION")
                or "global"
            ),
            http_options=types.HttpOptions(api_version="v1"),
        )
    else:
        client = genai.Client(api_key=config.gemini_api_key)
    _client_cache[cache_key] = client
    return client


def _extract_gemini_usage(response, model: str) -> UsageRecord | None:
    usage_meta = getattr(response, "usage_metadata", None)
    if usage_meta is None:
        return None
    return UsageRecord(
        provider="gemini",
        model=model,
        operation="text",
        input_tokens=getattr(usage_meta, "prompt_token_count", 0) or 0,
        output_tokens=getattr(usage_meta, "candidates_token_count", 0) or 0,
    )


@retry(wait=wait_exponential(min=2, max=60), stop=stop_after_attempt(3))
async def generate_json(
    config: Config,
    model: str,
    system_prompt: str,
    user_content: str | bytes,
    temperature: float = 0.7,
    max_output_tokens: int | None = None,
) -> ApiResult[dict]:
    """Call Gemini async and parse the JSON response.

    user_content may be a plain string or raw PDF bytes (passed as inline data).
    """
    payload_str = user_content if isinstance(user_content, str) else f"<pdf bytes len={len(user_content)}>"
    call_id, started = log_call_start(
        logger,
        provider="gemini",
        operation="generate",
        task="json",
        params={"model": model},
        payload=payload_summary(system_prompt=system_prompt, user_content=payload_str),
    )
    client = get_client(config)
    gen_config = types.GenerateContentConfig(
        system_instruction=system_prompt,
        response_mime_type="application/json",
        temperature=temperature,
    )
    if max_output_tokens is not None:
        gen_config.max_output_tokens = max_output_tokens
    if isinstance(user_content, bytes):
        contents = [types.Part.from_bytes(data=user_content, mime_type="application/pdf")]
    else:
        contents = user_content
    try:
        response = await client.aio.models.generate_content(
            model=model,
            contents=contents,
            config=gen_config,
        )
        if not response.text:
            raise ValueError(f"Empty response from Gemini ({model})")
        parsed = json.loads(response.text)
        log_call_end(
            logger,
            call_id=call_id,
            started=started,
            provider="gemini",
            operation="generate",
            task="json",
            ok=True,
            result={
                "response_chars": len(response.text),
                "candidates": len(getattr(response, "candidates", []) or []),
                "response_type": type(parsed).__name__,
            },
        )
        return ApiResult(value=parsed, usage=_extract_gemini_usage(response, model))
    except Exception as e:
        log_call_end(
            logger,
            call_id=call_id,
            started=started,
            provider="gemini",
            operation="generate",
            task="json",
            ok=False,
            error=e,
        )
        raise


@retry(wait=wait_exponential(min=2, max=60), stop=stop_after_attempt(3))
async def generate_text(
    config: Config,
    model: str,
    system_prompt: str,
    user_content: str,
    temperature: float = 0.7,
) -> ApiResult[str]:
    """Call Gemini async and return raw text response."""
    call_id, started = log_call_start(
        logger,
        provider="gemini",
        operation="generate",
        task="text",
        params={"model": model},
        payload=payload_summary(system_prompt=system_prompt, user_content=user_content),
    )
    client = get_client(config)
    try:
        response = await client.aio.models.generate_content(
            model=model,
            contents=user_content,
            config=types.GenerateContentConfig(
                system_instruction=system_prompt,
                temperature=temperature,
            ),
        )
        if not response.text:
            raise ValueError(f"Empty response from Gemini ({model})")
        log_call_end(
            logger,
            call_id=call_id,
            started=started,
            provider="gemini",
            operation="generate",
            task="text",
            ok=True,
            result={
                "response_chars": len(response.text),
                "candidates": len(getattr(response, "candidates", []) or []),
            },
        )
        return ApiResult(value=response.text, usage=_extract_gemini_usage(response, model))
    except Exception as e:
        log_call_end(
            logger,
            call_id=call_id,
            started=started,
            provider="gemini",
            operation="generate",
            task="text",
            ok=False,
            error=e,
        )
        raise
