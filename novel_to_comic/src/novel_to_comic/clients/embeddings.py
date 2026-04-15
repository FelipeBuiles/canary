"""Embeddings wrapper with async support.

Uses Google's text-embedding-004 by default (768 dims, $0.00625/M tokens).
Falls back to OpenAI text-embedding-3-small if configured.
"""

import httpx
from openai import AsyncOpenAI
from tenacity import retry, stop_after_attempt, wait_exponential

from novel_to_comic.config import Config

# Google gemini-embedding-2-preview = 3072 dims (via Gemini Developer REST API)
# OpenAI text-embedding-3-small = 1536 dims
GOOGLE_EMBEDDING_MODEL = "gemini-embedding-2-preview"

_GOOGLE_EMBED_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/{model}:embedContent"
)


@retry(wait=wait_exponential(min=1, max=30), stop=stop_after_attempt(3))
async def embed_texts(
    config: Config,
    texts: list[str],
) -> list[list[float]]:
    """Embed a batch of texts. Uses Google or OpenAI depending on config."""
    if config.embedding_model == GOOGLE_EMBEDDING_MODEL:
        return await _embed_google(config, texts)
    return await _embed_openai(config, texts)


async def _embed_google(config: Config, texts: list[str]) -> list[list[float]]:
    """Embed via Google text-embedding-004 using the REST API directly.

    The google-genai SDK routes embedding requests to a path that isn't
    available for Developer API keys. Calling the REST endpoint directly
    sidesteps the SDK routing issue.
    """
    url = _GOOGLE_EMBED_URL.format(model=config.embedding_model)
    params = {"key": config.gemini_api_key}

    results: list[list[float]] = []
    async with httpx.AsyncClient(timeout=30.0) as client:
        for text in texts:
            body = {
                "content": {"parts": [{"text": text}]},
                "taskType": "RETRIEVAL_DOCUMENT",
            }
            response = await client.post(url, params=params, json=body)
            if response.status_code != 200:
                raise ValueError(
                    f"Google embedding API error {response.status_code}: {response.text}"
                )
            data = response.json()
            values = data.get("embedding", {}).get("values")
            if not values:
                raise ValueError(f"Empty embedding in response: {data}")
            results.append(values)

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
