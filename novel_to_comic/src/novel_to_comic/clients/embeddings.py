"""Embeddings wrapper with async support.

Uses Google's Gemini embedding model by default.
Falls back to OpenAI if configured.
"""

import logging
import time

from google.genai.errors import ClientError
from openai import AsyncOpenAI
from tenacity import retry, retry_if_not_exception_type, stop_after_attempt, wait_exponential

from novel_to_comic.clients.gemini import describe_provider, get_client
from novel_to_comic.config import Config

# Google gemini-embedding-001 = 3072 dims on Vertex AI
# OpenAI text-embedding-3-small = 1536 dims
GOOGLE_EMBEDDING_MODEL = "gemini-embedding-001"
logger = logging.getLogger("canary.google")


@retry(
    wait=wait_exponential(min=1, max=30),
    stop=stop_after_attempt(3),
    retry=retry_if_not_exception_type(ClientError),
)
async def embed_texts(
    config: Config,
    texts: list[str],
) -> list[list[float]]:
    """Embed a batch of texts. Uses Google or OpenAI depending on config."""
    if config.embedding_model == GOOGLE_EMBEDDING_MODEL:
        return await _embed_google(config, texts)
    return await _embed_openai(config, texts)


async def _embed_google(config: Config, texts: list[str]) -> list[list[float]]:
    """Embed via Google Gen AI, using Vertex AI when configured."""
    from google.genai import types

    started = time.perf_counter()
    logger.info(
        "[bold cyan]Gemini[/] task=embedding model=[bold]%s[/] count=[bold]%d[/] "
        "provider=[green]%s[/]",
        config.embedding_model,
        len(texts),
        describe_provider(config),
    )
    client = get_client(config)
    results: list[list[float]] = []
    for text in texts:
        response = await client.aio.models.embed_content(
            model=config.embedding_model,
            contents=text,
            config=types.EmbedContentConfig(task_type="RETRIEVAL_DOCUMENT"),
        )
        if not response.embeddings or not response.embeddings[0].values:
            raise ValueError("Empty embedding in Google response")
        results.append(response.embeddings[0].values)

    logger.info(
        "[bold green]Gemini done[/] task=embedding model=[bold]%s[/] count=[bold]%d[/] "
        "elapsed=[bold]%.1fs[/]",
        config.embedding_model,
        len(texts),
        time.perf_counter() - started,
    )
    return results


async def _embed_openai(config: Config, texts: list[str]) -> list[list[float]]:
    """Embed via OpenAI text-embedding-3-small (1536 dims)."""
    client = AsyncOpenAI(api_key=config.openai_api_key)
    response = await client.embeddings.create(
        model=config.embedding_model,
        input=texts,
    )
    if not response.data:
        raise ValueError("Empty embedding response from OpenAI API")
    return [item.embedding for item in response.data]


async def embed_single(config: Config, text: str) -> list[float]:
    """Embed a single text string."""
    results = await embed_texts(config, [text])
    return results[0]
