"""Shared text helpers for prompt composition and indexing."""

from __future__ import annotations

import httpx


def clean(value: str | None) -> str:
    """Collapse whitespace and strip a string."""
    return " ".join((value or "").replace("\n", " ").split())


def shorten(value: str, limit: int) -> str:
    """Truncate to *limit* characters on a word boundary."""
    value = clean(value)
    if len(value) <= limit:
        return value
    shortened = value[:limit].rsplit(" ", 1)[0].rstrip(" ,.;:")
    return f"{shortened}."


def clean_exception_message(exc: Exception) -> str:
    """Format an exception to a clean, user-friendly string without verbose info like Mozilla URLs."""
    # Try to extract LiteLLM/API response message if it's an HTTPStatusError
    if isinstance(exc, httpx.HTTPStatusError):
        try:
            body = exc.response.json()
            if isinstance(body, dict):
                # Standard OpenAI/LiteLLM error: {"error": {"message": "..."}}
                err_detail = body.get("error", {})
                if isinstance(err_detail, dict) and err_detail.get("message"):
                    return f"HTTPStatusError: {exc.response.status_code} {exc.response.reason_phrase} - {err_detail['message']}"
                # FastAPI detail: {"detail": "..."}
                elif body.get("detail"):
                    return f"HTTPStatusError: {exc.response.status_code} {exc.response.reason_phrase} - {body['detail']}"
                # Other formats: {"message": "..."}
                elif body.get("message"):
                    return f"HTTPStatusError: {exc.response.status_code} {exc.response.reason_phrase} - {body['message']}"
        except Exception:
            pass

    msg = str(exc)
    if "For more information check:" in msg:
        lines = [
            line for line in msg.splitlines()
            if "For more information check:" not in line and "http://Status/" not in line
        ]
        return "\n".join(lines).strip()
    return msg

