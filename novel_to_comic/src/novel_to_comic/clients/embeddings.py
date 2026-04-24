"""Embeddings wrapper with async support.

Uses Google's Gemini embedding model by default.
Falls back to OpenAI if configured.
"""

import logging

from google.genai.errors import ClientError
from openai import AsyncOpenAI
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from novel_to_comic.clients.api_logging import log_call_end, log_call_start
from novel_to_comic.clients.gemini import get_client
from novel_to_comic.config import Config

# Google gemini-embedding-001 = 3072 dims on Vertex AI
# OpenAI text-embedding-3-small = 1536 dims
GOOGLE_EMBEDDING_MODEL = "gemini-embedding-001"
logger = logging.getLogger("canary.google")


def _should_retry_embedding_error(exc: BaseException) -> bool:
    if isinstance(exc, ClientError):
        return exc.code == 429
    return True


@retry(
    wait=wait_exponential(min=1, max=30),
    stop=stop_after_attempt(3),
    retry=retry_if_exception(_should_retry_embedding_error),
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

    if not texts:
        return []

    call_id, started = log_call_start(
        logger,
        provider="gemini",
        operation="embed",
        task="embed",
        params={
            "model": config.embedding_model,
            "count": len(texts),
        },
        payload={"input_chars_total": sum(len(t) for t in texts)},
    )
    client = get_client(config)
    try:
        response = await client.aio.models.embed_content(
            model=config.embedding_model,
            contents=texts,
            config=types.EmbedContentConfig(task_type="RETRIEVAL_DOCUMENT"),
        )
        if not response.embeddings:
            raise ValueError("Empty embedding response from Google API")
        if len(response.embeddings) != len(texts):
            raise ValueError(
                "Google embedding response count mismatch: "
                f"expected {len(texts)}, got {len(response.embeddings)}"
            )
        results = []
        for embedding in response.embeddings:
            if not embedding.values:
                raise ValueError("Empty embedding in Google response")
            results.append(embedding.values)
        log_call_end(
            logger,
            call_id=call_id,
            started=started,
            provider="gemini",
            operation="embed",
            task="embed",
            ok=True,
            result={
                "count": len(results),
                "dims": len(results[0]) if results else 0,
            },
        )
        return results
    except Exception as e:
        log_call_end(
            logger,
            call_id=call_id,
            started=started,
            provider="gemini",
            operation="embed",
            task="embed",
            ok=False,
            error=e,
        )
        raise


async def _embed_openai(config: Config, texts: list[str]) -> list[list[float]]:
    """Embed via OpenAI text-embedding-3-small (1536 dims)."""
    call_id, started = log_call_start(
        logger,
        provider="openai",
        operation="embed",
        task="embed",
        params={
            "model": config.embedding_model,
            "count": len(texts),
        },
        payload={"input_chars_total": sum(len(t) for t in texts)},
    )
    client = AsyncOpenAI(api_key=config.openai_api_key)
    try:
        response = await client.embeddings.create(
            model=config.embedding_model,
            input=texts,
        )
        if not response.data:
            raise ValueError("Empty embedding response from OpenAI API")
        vectors = [item.embedding for item in response.data]
        log_call_end(
            logger,
            call_id=call_id,
            started=started,
            provider="openai",
            operation="embed",
            task="embed",
            ok=True,
            result={
                "count": len(vectors),
                "dims": len(vectors[0]) if vectors else 0,
            },
        )
        return vectors
    except Exception as e:
        log_call_end(
            logger,
            call_id=call_id,
            started=started,
            provider="openai",
            operation="embed",
            task="embed",
            ok=False,
            error=e,
        )
        raise


async def embed_single(config: Config, text: str) -> list[float]:
    """Embed a single text string."""
    results = await embed_texts(config, [text])
    return results[0]
