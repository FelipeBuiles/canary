"""Qdrant vector store operations."""

import re
from pathlib import Path

from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    MatchValue,
    PointStruct,
    VectorParams,
)

from novel_to_comic.config import Config

COLLECTION_NAME = "novel_scenes"

# Maps embedding model name → output dimension.
# Add entries here when new models are introduced.
_MODEL_VECTOR_SIZES: dict[str, int] = {
    "gemini-embedding-001": 3072,
    "text-embedding-3-small": 1536,
    "text-embedding-3-large": 3072,
    "text-embedding-ada-002": 1536,
}


def _vector_size(config: Config) -> int:
    return _MODEL_VECTOR_SIZES.get(config.embedding_model, 3072)


def get_client(config: Config) -> QdrantClient:
    return QdrantClient(host=config.qdrant_host, port=config.qdrant_port)


def collection_name(project_dir: Path | None = None) -> str:
    if project_dir is None:
        return COLLECTION_NAME
    slug = re.sub(r"[^a-zA-Z0-9_]+", "_", project_dir.name).strip("_")
    return f"{COLLECTION_NAME}_{slug or 'project'}"


def create_collection(config: Config, project_dir: Path | None = None) -> None:
    """Create the scenes collection in Qdrant.

    Recreates the collection if it exists with a different vector size
    (e.g. after switching embedding models).
    """
    size = _vector_size(config)
    name = collection_name(project_dir)
    client = get_client(config)
    existing = {c.name for c in client.get_collections().collections}
    if name in existing:
        info = client.get_collection(name)
        current_size = info.config.params.vectors.size
        if current_size == size:
            return  # already correct
        client.delete_collection(name)

    client.create_collection(
        collection_name=name,
        vectors_config=VectorParams(size=size, distance=Distance.COSINE),
    )


def upsert_chunks(
    config: Config,
    chunks: list[dict],
    vectors: list[list[float]],
    project_dir: Path | None = None,
) -> None:
    """Upsert text chunks with their embeddings.

    Each chunk dict should have: id (int), scene_id, chapter, character_ids, location_id, text.
    """
    if vectors:
        expected = _vector_size(config)
        actual = len(vectors[0])
        if actual != expected:
            raise ValueError(
                f"Embedding dimension mismatch: model '{config.embedding_model}' returned "
                f"{actual}-dim vectors but collection expects {expected}-dim. "
                f"Rebuild the Qdrant index or update embedding_model in config.yaml."
            )
    client = get_client(config)
    name = collection_name(project_dir)
    points = [
        PointStruct(
            id=chunk["id"],
            vector=vector,
            payload={
                "scene_id": chunk["scene_id"],
                "chapter": chunk["chapter"],
                "character_ids": chunk["character_ids"],
                "location_id": chunk["location_id"],
                "text": chunk["text"],
            },
        )
        for chunk, vector in zip(chunks, vectors)
    ]
    client.upsert(collection_name=name, points=points)


def search(
    config: Config,
    query_vector: list[float],
    limit: int = 5,
    scene_id: str | None = None,
    project_dir: Path | None = None,
) -> list[dict]:
    """Search for relevant chunks. Optionally filter by scene_id."""
    client = get_client(config)
    name = collection_name(project_dir)

    query_filter = None
    if scene_id:
        query_filter = Filter(
            must=[FieldCondition(key="scene_id", match=MatchValue(value=scene_id))]
        )

    results = client.query_points(
        collection_name=name,
        query=query_vector,
        limit=limit,
        query_filter=query_filter,
    )
    return [
        {"score": point.score, **point.payload}
        for point in results.points
    ]
