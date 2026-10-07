"""Shared classification and user-facing copy for image-generation failures."""

from __future__ import annotations

from typing import Literal

ImageFailureClassification = Literal[
    "provider_blocked",
    "rate_limited",
    "shape_mismatch",
    "timed_out",
    "service_unavailable",
    "configuration_error",
    "empty_response",
    "generation_error",
]


def _exception_chain(error: BaseException) -> list[BaseException]:
    chain: list[BaseException] = []
    seen: set[int] = set()
    node: BaseException | None = error
    while node is not None and id(node) not in seen:
        seen.add(id(node))
        chain.append(node)
        node = getattr(node, "__cause__", None) or getattr(node, "__context__", None)
    return chain


def _error_text(error: BaseException) -> str:
    return " ".join(
        " ".join([
            type(node).__name__,
            str(node),
            *(str(arg) for arg in getattr(node, "args", ()) if arg is not None),
            f"status_code={getattr(getattr(node, 'response', None), 'status_code', '')}",
        ])
        for node in _exception_chain(error)
    ).lower()


def classify_image_failure(
    error: BaseException,
    *,
    shape_mismatch: bool = False,
) -> ImageFailureClassification:
    """Turn provider/runtime errors into stable categories for the UI.

    The original exception remains in failure metadata for diagnostics. This
    category is the contract used by every user-facing failure surface.
    """
    text = _error_text(error)
    if shape_mismatch or "shape_mismatch" in text or "aspectmismatcherror" in text:
        return "shape_mismatch"
    if any(token in text for token in (
        "image_prohibited",
        "moderation_blocked",
        "content_policy_violation",
        "content management policy",
        "rejected by the safety system",
        "prohibited_content",
        "responsible ai",
        "filtered out",
        "safety rating",
        "safety_ratings",
        "safety filter",
        "block_reason",
        "blockreason",
        "finish_reason=safety",
        "finish_reason=content_filter",
        "violated google",
        "unable to show the generated image",
        "silently rejected",
    )):
        return "provider_blocked"
    if any(token in text for token in (
        "429",
        "resource_exhausted",
        "rate limit",
        "ratelimit",
        "usage limit",
        "quota",
    )):
        return "rate_limited"
    if any(token in text for token in ("timeout", "timed out", "deadline exceeded")):
        return "timed_out"
    if any(token in text for token in (
        "connection refused",
        "connection reset",
        "connecterror",
        "gateway connection could not be established",
        "gateway disconnected before sending a response",
        "network error",
        "service unavailable",
        "temporarily unavailable",
        "bad gateway",
        " 502",
        " 503",
        " 504",
    )):
        return "service_unavailable"
    if any(token in text for token in (
        "api_key is not set",
        "api key is not set",
        "401",
        "unauthorized",
        "invalid api key",
        "authentication",
        "vertexai_project is not set",
        "fal_key is not set",
        "requires canary_wire_request",
        "model_not_loaded",
        "invalid model name passed",
        "not implemented",
        "unsupported wire",
    )):
        return "configuration_error"
    if any(token in text for token in (
        "no image",
        "empty response",
        "did not contain image",
        "no images",
        "missing url",
        "neither inline image data nor a url",
    )):
        return "empty_response"
    return "generation_error"


def user_message_for_image_failure(classification: ImageFailureClassification) -> str:
    """Return concise English copy for stored failure metadata and APIs."""
    return {
        "provider_blocked": (
            "The image provider declined this scene but did not say which detail "
            "caused it. Your work is unchanged. Review the whole page and try a simpler, "
            "more specific change. The provider may be reacting to existing page content, "
            "not just your note."
        ),
        "rate_limited": (
            "The image service has temporarily reached its quota. "
            "Wait for quota to reset and retry; your prompt does not need editing."
        ),
        "shape_mismatch": (
            "The image service returned the wrong frame shape, so we could not use this image. "
            "Try this page again."
        ),
        "timed_out": (
            "The image service took too long to respond. "
            "Try this page again."
        ),
        "service_unavailable": (
            "We could not reach the image service. "
            "Check your connection and try this page again."
        ),
        "configuration_error": (
            "The image service is not configured correctly for this project. "
            "Try again later or contact support if it continues."
        ),
        "empty_response": (
            "The image service finished without returning an image. "
            "Try this page again; if it repeats, contact support."
        ),
        "generation_error": (
            "The image service returned an unexpected error. "
            "Try this page again; if it keeps happening, try a different image model."
        ),
    }[classification]


__all__ = [
    "ImageFailureClassification",
    "classify_image_failure",
    "user_message_for_image_failure",
]
