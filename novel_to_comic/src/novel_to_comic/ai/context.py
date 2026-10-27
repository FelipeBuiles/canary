"""Request-scoped AI metadata.

This keeps user/project/stage metadata available to the AI client without
threading those fields through every stage function signature.
"""

from __future__ import annotations

import hashlib
import json
import time
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, replace
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
    source_scope: str | None = None
    source_unit_ids: tuple[str, ...] = ()
    # Canary pays for these calls itself (the Cold Open). They are recorded with
    # their provider cost but never authorized against or debited from the user.
    sponsor: str | None = None


_current_ai_request_context: ContextVar[AIRequestContext] = ContextVar(
    "current_ai_request_context",
    default=AIRequestContext(),
)


def current_ai_request_context() -> AIRequestContext:
    """Return the active AI request context, or an empty context."""

    return _current_ai_request_context.get()


@contextmanager
def ai_source_context(scope: str, source_unit_ids: tuple[str, ...]) -> Iterator[None]:
    """Attach source provenance to one call without losing the enclosing job."""

    token = _current_ai_request_context.set(replace(
        current_ai_request_context(), source_scope=scope,
        source_unit_ids=source_unit_ids,
    ))
    try:
        yield
    finally:
        _current_ai_request_context.reset(token)


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
    sponsor: str | None = None,
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
        sponsor=sponsor,
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


# Called once when a provider actually starts executing a request, as opposed
# to when the caller admitted it. Serialized transports (the local Codex
# runtime) queue admitted calls behind a lock, so the two can be far apart.
ExecutionObserver = Callable[[], None]

_current_execution_observers: ContextVar[tuple[ExecutionObserver, ...]] = ContextVar(
    "current_execution_observers",
    default=(),
)


@contextmanager
def execution_observer(observer: ExecutionObserver) -> Iterator[None]:
    """Be told when AI calls in this context begin executing.

    Observers nest: a budget ledger and a stage's progress view can both watch
    the same call.
    """

    token = _current_execution_observers.set(
        (*_current_execution_observers.get(), observer)
    )
    try:
        yield
    finally:
        _current_execution_observers.reset(token)


def notify_execution_started() -> None:
    """Transports call this when a request leaves their queue.

    Observation must never fail the request it describes.
    """

    mark_generation_executing()
    for observer in _current_execution_observers.get():
        try:
            observer()
        except Exception:
            import logging

            logging.getLogger(__name__).exception("Execution observer failed")


class GenerationProbe:
    """Telemetry-only facts about one provider call, gathered where they occur.

    Timings are monotonic; a phase never observed stays absent rather than
    zero. Prompt and output bodies are kept only when the caller opted in and
    are released to telemetry solely through its content-capture gate.
    """

    __slots__ = ("started", "executing", "first_content", "stream", "prompt_sha",
                 "schema_sha", "request_sha", "wire_schema_version", "input_messages", "output_text")

    def __init__(self) -> None:
        self.started = time.perf_counter()
        self.executing: float | None = None
        self.first_content: float | None = None
        self.stream: bool | None = None
        self.prompt_sha: str | None = None
        self.schema_sha: str | None = None
        self.request_sha: str | None = None
        self.wire_schema_version: int | None = None
        self.input_messages: list[dict[str, str]] | None = None
        self.output_text: str | None = None

    def describe(self, *, system_prompt: str, user_content: str, json_schema: dict | None,
                 stream: bool, keep_content: bool) -> None:
        # The system prompt is the stage's instruction template; user content
        # varies per input and is fingerprinted only by the usage row.
        self.prompt_sha = _short_sha(system_prompt)
        self.schema_sha = _short_sha(json.dumps(json_schema, sort_keys=True)) if json_schema else None
        self.stream = stream
        if keep_content:
            self.input_messages = [{"role": "system", "content": system_prompt},
                                   {"role": "user", "content": user_content}]

    def telemetry_fields(self, latency_ms: int) -> dict[str, object]:
        fields: dict[str, object] = {"prompt_sha": self.prompt_sha, "schema_sha": self.schema_sha,
                                     "request_sha": self.request_sha, "wire_schema_version": self.wire_schema_version}
        if self.stream is not None:
            fields["$ai_stream"] = self.stream
        if self.executing is not None:
            admission_ms = int((self.executing - self.started) * 1000)
            fields["admission_ms"] = admission_ms
            fields["execution_ms"] = max(0, latency_ms - admission_ms)
        if self.first_content is not None:
            fields["$ai_time_to_first_token"] = round(
                self.first_content - (self.executing or self.started), 3)
        return {key: value for key, value in fields.items() if value is not None}

    def content_fields(self) -> dict[str, object]:
        if self.input_messages is None:
            return {}
        fields: dict[str, object] = {"$ai_input": self.input_messages}
        if self.output_text is not None:
            fields["$ai_output_choices"] = [{"role": "assistant", "content": self.output_text}]
        return fields


def _short_sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()[:16]


_current_generation_probe: ContextVar[GenerationProbe | None] = ContextVar(
    "current_generation_probe",
    default=None,
)


def current_generation_probe() -> GenerationProbe | None:
    return _current_generation_probe.get()


@contextmanager
def generation_probe() -> Iterator[GenerationProbe]:
    """Scope one provider call's telemetry probe."""

    probe = GenerationProbe()
    token = _current_generation_probe.set(probe)
    try:
        yield probe
    finally:
        _current_generation_probe.reset(token)


def mark_generation_executing() -> None:
    """The provider began work; a serialized queue may release after admission."""

    if (probe := _current_generation_probe.get()) is not None:
        probe.executing = time.perf_counter()


def mark_generation_first_content() -> None:
    if (probe := _current_generation_probe.get()) is not None and probe.first_content is None:
        probe.first_content = time.perf_counter()
