"""Google Gemini API wrapper with async support and retry logic."""

import json
import logging
import os
import time

from google import genai
from google.genai import types
from tenacity import retry, stop_after_attempt, wait_exponential

from novel_to_comic.config import Config

logger = logging.getLogger("canary.google")


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
    if config.google_use_vertex_ai:
        return genai.Client(
            vertexai=True,
            project=_vertex_project(config),
            location=(
                config.google_cloud_location
                or os.environ.get("GOOGLE_CLOUD_LOCATION")
                or "global"
            ),
            http_options=types.HttpOptions(api_version="v1"),
        )
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
    started = time.perf_counter()
    logger.info(
        "[bold cyan]Gemini[/] task=json model=[bold]%s[/] provider=[green]%s[/]",
        model,
        describe_provider(config),
    )
    client = get_client(config)
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
    logger.info(
        "[bold green]Gemini done[/] task=json model=[bold]%s[/] elapsed=[bold]%.1fs[/]",
        model,
        time.perf_counter() - started,
    )
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
    started = time.perf_counter()
    logger.info(
        "[bold cyan]Gemini[/] task=text model=[bold]%s[/] provider=[green]%s[/]",
        model,
        describe_provider(config),
    )
    client = get_client(config)
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
    logger.info(
        "[bold green]Gemini done[/] task=text model=[bold]%s[/] elapsed=[bold]%.1fs[/]",
        model,
        time.perf_counter() - started,
    )
    return response.text
