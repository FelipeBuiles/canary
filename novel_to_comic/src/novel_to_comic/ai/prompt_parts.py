"""Cache-friendly user-content parts.

Vertex implicit caching reuses an earlier request's leading content parts. In
probes (work/argon-cache-probe-20261013) Argon reused a prefix sent as its own
part, while text appended inside the same part missed. Prompts mark where
their stable leading content ends with ``CACHE_BREAK``; Gemini routes send
each piece as a separate text part, and every other route sees a blank line.
"""
from __future__ import annotations

CACHE_BREAK = "\n\n<<canary-cache-break>>\n\n"


def cache_join(*pieces: str) -> str:
    """Join prompt pieces so each later piece can change without moving the earlier ones."""
    return CACHE_BREAK.join(piece for piece in pieces if piece)


def prompt_parts(content: str) -> list[str]:
    return [part for part in content.split(CACHE_BREAK) if part]


def plain_prompt(content: str) -> str:
    return "\n\n".join(prompt_parts(content))
