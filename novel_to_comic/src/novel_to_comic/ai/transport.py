"""What a text transport can actually do, independent of a caller's settings."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TextTransportLimits:
    # Requests the transport executes at once; None when it adds no bound.
    parallel_calls: int | None = None
    # Hard wall-clock ceiling on one request; None when the transport sets none.
    call_deadline_seconds: int | None = None


def text_transport_limits(model: str) -> TextTransportLimits:
    """Limits of the transport that will carry ``model``'s text requests.

    A caller asking for more parallelism than the transport has only turns
    queued requests into apparently in-flight ones, and a request sized past
    the deadline fails after spending its whole budget.
    """

    from novel_to_comic.codex_dev import CodexRoutingError, route_for

    try:
        route = route_for("text", model)
        runtime = route.runtime if route is not None else None
    except CodexRoutingError:
        # Submission raises the actionable routing error; sizing only needs
        # to know which transport the selector names.
        runtime = ("claude" if model.startswith("claude-dev/")
                   else "codex" if model.startswith("codex-dev/") else None)
    if runtime is None:
        return TextTransportLimits()
    if runtime == "claude":
        from novel_to_comic.ai import claude_runtime as subscription_runtime
    else:
        from novel_to_comic.ai import codex_runtime as subscription_runtime

    return TextTransportLimits(
        parallel_calls=subscription_runtime.PARALLEL_CALLS,
        call_deadline_seconds=subscription_runtime.TEXT_TIMEOUT_SECONDS,
    )
