"""Request-scoped AI metadata.

This keeps user/project/stage metadata available to the AI client without
threading those fields through every stage function signature.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Callable, Iterator

# Cumulative characters received so far on the in-flight streamed completion.
# Resets to 0 when a retry restarts the stream.
StreamObserver = Callable[[int], None]


@dataclass(frozen=True)
class AIRequestContext:
    user_id: str | None = None
    project_id: str | None = None
    project_name: str | None = None
    workspace_id: str | None = None
    stage: str | None = None
    request_id: str | None = None
    job_id: str | None = None
    page_number: int | None = None
    is_correction: bool = False


_current_ai_request_context: ContextVar[AIRequestContext] = ContextVar(
    "current_ai_request_context",
    default=AIRequestContext(),
)


def current_ai_request_context() -> AIRequestContext:
    """Return the active AI request context, or an empty context."""

    return _current_ai_request_context.get()


@contextmanager
def ai_request_context(
    *,
    user_id: str | None = None,
    project_id: str | None = None,
    project_name: str | None = None,
    workspace_id: str | None = None,
    stage: str | None = None,
    request_id: str | None = None,
    job_id: str | None = None,
    page_number: int | None = None,
    is_correction: bool = False,
) -> Iterator[AIRequestContext]:
    """Temporarily set request metadata for AI calls in this context."""

    context = AIRequestContext(
        user_id=user_id,
        project_id=project_id,
        project_name=project_name,
        workspace_id=workspace_id,
        stage=stage,
        request_id=request_id,
        job_id=job_id,
        page_number=page_number,
        is_correction=is_correction,
    )
    token = _current_ai_request_context.set(context)
    try:
        yield context
    finally:
        _current_ai_request_context.reset(token)


_current_stream_observer: ContextVar[StreamObserver | None] = ContextVar(
    "current_stream_observer",
    default=None,
)


def current_stream_observer() -> StreamObserver | None:
    """The callback to notify as a streamed completion arrives, if any."""

    return _current_stream_observer.get()


@contextmanager
def stream_observer(observer: StreamObserver | None) -> Iterator[None]:
    """Watch streamed-completion progress for AI calls in this context.

    Set per unit of work (one adapt shard, say) rather than per stage: tasks
    spawned under asyncio.gather copy the context at creation, so each gets its
    own observer.
    """

    token = _current_stream_observer.set(observer)
    try:
        yield
    finally:
        _current_stream_observer.reset(token)
