"""Request-scoped AI metadata.

This keeps user/project/stage metadata available to the AI client without
threading those fields through every stage function signature.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Iterator


@dataclass(frozen=True)
class AIRequestContext:
    user_id: str | None = None
    project_id: str | None = None
    project_name: str | None = None
    workspace_id: str | None = None
    stage: str | None = None
    request_id: str | None = None
    job_id: str | None = None


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
    )
    token = _current_ai_request_context.set(context)
    try:
        yield context
    finally:
        _current_ai_request_context.reset(token)
