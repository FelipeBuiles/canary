"""Scene-boundary chunking for RAG index construction."""

from pathlib import Path


def chunk_scene_text(text: str, target_tokens: int = 600, max_tokens: int = 800) -> list[str]:
    """Split scene text into chunks at paragraph boundaries.

    Targets ~600 tokens per chunk (approx 4 chars per token), never splits mid-sentence.
    """
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0
    chars_per_token = 4  # rough approximation

    for para in paragraphs:
        para_tokens = len(para) // chars_per_token
        if current and (current_len + para_tokens) > max_tokens:
            chunks.append("\n\n".join(current))
            current = [para]
            current_len = para_tokens
        else:
            current.append(para)
            current_len += para_tokens

    if current:
        chunks.append("\n\n".join(current))

    return chunks


def load_scene_texts(scenes_dir: Path) -> dict[str, str]:
    """Load all scene text files from the scenes directory.

    Returns a dict mapping scene_id to text content.
    """
    texts: dict[str, str] = {}
    if not scenes_dir.exists():
        return texts
    for path in sorted(scenes_dir.glob("*.txt")):
        scene_id = path.stem  # e.g., "scene_001"
        texts[scene_id] = path.read_text()
    return texts
