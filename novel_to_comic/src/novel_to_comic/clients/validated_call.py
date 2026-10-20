"""A bounded validation round over an unchanged structured request.

Stage validators and named checkpoint adapters retain ownership of their
contracts. This module owns attempts, usage, telemetry, and correction replay.
Transport exceptions escape immediately; only declared validation failures may
start another paid attempt.
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Generic, TypeVar

from pydantic import ValidationError

from novel_to_comic.ai.errors import AIStructuredResponseError

from novel_to_comic.text_models import TextModelJob
from novel_to_comic.usage import ApiResult

T = TypeVar("T")


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 2
    errors: tuple[type[Exception], ...] = (ValueError,)

    def __post_init__(self):
        if self.max_attempts < 1:
            raise ValueError("A validated call needs at least one attempt")


@dataclass(frozen=True)
class ValidatedResult(Generic[T]):
    value: T
    response: ApiResult[Any]
    request: dict[str, Any]
    attempts: int


@dataclass(frozen=True)
class CallCheckpoint(Generic[T]):
    """Named stage storage with current validation, shared by estimates and runs."""
    read: Callable[[], T | None]
    validate: Callable[[T], None]
    view: Callable[[T], Any]
    save: Callable[[T], None] | None = None

    def paid_value(self) -> T | None:
        value = self.read()
        if value is not None:
            try:
                self.validate(value)
            except ValueError:
                return None
        return value

    def is_paid_for(self) -> bool:
        return self.paid_value() is not None


@dataclass(frozen=True)
class ValidatedCall(Generic[T]):
    job: TextModelJob
    policy: RetryPolicy
    parse: Callable[[Any], T]
    correction: Callable[[Any, Exception], str]
    repair: Callable[[Any, Exception], T | None] | None = None

    async def run(
        self, generate: Callable[..., Awaitable[ApiResult[Any]]],
        request: dict[str, Any], *,
        observe: Callable[[ApiResult[Any]], None],
        rejected: Callable[[dict[str, Any], Any, Exception], None] | None = None,
        checkpoint: CallCheckpoint[T] | None = None,
        prepare_attempt: Callable[[dict[str, Any], int], dict[str, Any]] | None = None,
    ) -> ValidatedResult[T]:
        from novel_to_comic.server.telemetry import ai_span, observation_context

        request = dict(request)
        if checkpoint is not None:
            cached = checkpoint.read()
            if cached is not None:
                try:
                    checkpoint.validate(cached)
                except self.policy.errors as error:
                    request["user_content"] = self.correction(checkpoint.view(cached), error)
                else:
                    return ValidatedResult(cached, ApiResult(checkpoint.view(cached)), request, 0)
        feature = request.get("feature", self.job.name)
        with self.job.bind(), ai_span(f"structured.{feature}", feature=feature) as call_span:
            for attempt in range(1, self.policy.max_attempts + 1):
                if prepare_attempt is not None:
                    request = prepare_attempt(request, attempt)
                with ai_span("attempt", attempt_number=attempt) as span, observation_context(attempt_number=attempt):
                    try:
                        result = await generate(**request)
                    except Exception as error:
                        span.set(outcome="unparseable" if isinstance(error, AIStructuredResponseError)
                                 else "provider_failed", error_type=type(error).__name__)
                        call_span.set(outcome="failed", status="failed", attempts=attempt)
                        raise
                    observe(result)
                    try:
                        from novel_to_comic.server.metrics import record_structured_attempt
                        record_structured_attempt(feature=feature, retry=attempt > 1)
                    except Exception:
                        pass
                    try:
                        value = self.parse(result.value)
                    except self.policy.errors as error:
                        span.set(outcome="rejected", error_type=type(error).__name__,
                                 validation_error_count=error.error_count() if isinstance(error, ValidationError) else None)
                        if self.repair is not None:
                            repaired = self.repair(result.value, error)
                            if repaired is not None:
                                if checkpoint is not None and checkpoint.save is not None:
                                    checkpoint.save(repaired)
                                span.set(outcome="repaired")
                                call_span.set(outcome="repaired", attempts=attempt)
                                return ValidatedResult(repaired, result, request, attempt)
                        if rejected is not None:
                            rejected(request, result.value, error)
                        if attempt == self.policy.max_attempts:
                            call_span.set(outcome="failed", status="failed", attempts=attempt)
                            raise
                        request = {**request, "user_content": self.correction(result.value, error)}
                    else:
                        if checkpoint is not None and checkpoint.save is not None:
                            checkpoint.save(value)
                        span.set(outcome="accepted")
                        call_span.set(outcome="accepted" if attempt == 1 else "accepted_after_retry", attempts=attempt)
                        return ValidatedResult(value, result, request, attempt)
        raise AssertionError("validated call must return or raise")
