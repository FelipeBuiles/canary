"""Google Gemini API wrapper with async support and retry logic."""

import json

from google import genai
from google.genai import types
from tenacity import retry, stop_after_attempt, wait_exponential

from novel_to_comic.config import Config


def _get_client(config: Config) -> genai.Client:
    return genai.Client(api_key=config.gemini_api_key)


@retry(wait=wait_exponential(min=2, max=60), stop=stop_after_attempt(3))
async def generate_json(
    config: Config,
    model: str,
    system_prompt: str,
    user_content: str,
    temperature: float = 0.7,
    max_output_tokens: int | None = None,
) -> dict:
    """Call Gemini async and parse the JSON response."""
    client = _get_client(config)
    gen_config = types.GenerateContentConfig(
        system_instruction=system_prompt,
        response_mime_type="application/json",
        temperature=temperature,
    )
    if max_output_tokens is not None:
        gen_config.max_output_tokens = max_output_tokens
    response = await client.aio.models.generate_content(
        model=model,
        contents=user_content,
        config=gen_config,
    )
    if not response.text:
        raise ValueError(f"Empty response from Gemini ({model})")
    return json.loads(response.text)


@retry(wait=wait_exponential(min=2, max=60), stop=stop_after_attempt(3))
async def generate_text(
    config: Config,
    model: str,
    system_prompt: str,
    user_content: str,
    temperature: float = 0.7,
) -> str:
    """Call Gemini async and return raw text response."""
    client = _get_client(config)
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
    return response.text
