"""Shared text helpers for prompt composition and indexing."""

from __future__ import annotations

import re
import unicodedata

import httpx


# Comparison-only normalizers.
#
# These fold representations that different producers spell differently: a model
# writing an em dash as "--", an OCR engine reading "—" as "-", a balloon whose
# wording is line-broken by the letterer. Every stage seam that compares text
# from two independent producers must fold through the same function, or the two
# sides disagree on formatting and a valid artifact blocks.
#
# They are NOT offset-preserving: ``…`` expands and whitespace collapses. Never
# use them to locate text inside a source document — see
# ``source_extraction._norm_quote_text`` for the offset-faithful variant.
_TYPOGRAPHIC_EQUIVALENTS = {
    "‘": "'",
    "’": "'",
    "‚": "'",
    "‛": "'",
    "“": '"',
    "”": '"',
    "′": "'",
    "″": '"',
    "–": "-",
    "—": "-",
    "―": "-",
    "−": "-",
    " ": " ",
    "…": "...",
}
_TYPOGRAPHIC_TABLE = str.maketrans(_TYPOGRAPHIC_EQUIVALENTS)


def normalize_typography(text: str) -> str:
    """Fold quote, dash, ellipsis, and non-breaking-space variants."""

    folded = unicodedata.normalize("NFC", text).translate(_TYPOGRAPHIC_TABLE)
    return re.sub(r"-{2,}", "-", folded)


def normalize_display_text(text: str) -> str:
    """Canonical comparison form for lettering and other display wording."""

    return " ".join(normalize_typography(text).split())


def normalize_requirement(text: str) -> str:
    """Canonical comparison form for brief requirements echoed by a model.

    Requirement strings travel from the Brief through a treatment and back into
    beat citations. Case, surrounding quotes, and terminal punctuation drift on
    every hop and none of that drift changes the requirement's identity.
    """

    collapsed = normalize_display_text(text).casefold()
    return collapsed.strip("\"'").strip().rstrip(".!?;:,").strip()


OFFSCREEN_MARKERS = (
    "off-screen",
    "off screen",
    "off-panel",
    "off panel",
    "unseen speaker",
    "unseen voice",
    "voice-only",
    "voice only",
    "heard but not seen",
    "not physically shown",
    "never physically shown",
)


def has_offscreen_marker(text: str) -> bool:
    """True when a character description marks a voice-only / never-shown entity."""
    lowered = text.lower()
    return any(marker in lowered for marker in OFFSCREEN_MARKERS)


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
    if isinstance(exc, httpx.TimeoutException):
        return (
            f"{type(exc).__name__}: "
            "The AI provider did not respond before the request timeout."
        )

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
